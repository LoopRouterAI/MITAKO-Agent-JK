# -*- coding: utf-8 -*-
"""
冒险模式独立 LLM 安全审核 — 参考 JK-PromptReview 三明治架构（精简版）

- L1：companion_adventure 内 regex 硬拦截（零延迟）
- L2：本模块 — 极小输入/输出，专用 DSv4 Flash 审核调用
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from llm_models import get_model_api_key, get_model_config
from companion_review_config import resolve_review_model_id

ReviewPhase = Literal["input", "output"]

# 审核专用模型 — 默认 DeepSeek V4 Flash（SENSENOVA）
REVIEWER_MODEL_ID = resolve_review_model_id(os.getenv("ADVENTURE_REVIEWER_MODEL"))

_VALID_ACTIONS = frozenset({"PASS", "BLOCK", "REDIRECT"})
_VALID_CODES = frozenset(
    {
        "PASS_DIRECT",
        "BLOCK_SAFETY",
        "BLOCK_INJECTION",
        "BLOCK_ADULT",
        "REDIRECT_POLITICS",
        "REDIRECT_SENSITIVE",
    }
)

_SAFETY_API_KEYWORDS = re.compile(
    r"(content.?filter|safety|违规|审核|policy|blocked|harmful|illegal)",
    re.I,
)

_PROMPT_CACHE: Optional[str] = None


def _load_system_prompt() -> str:
    global _PROMPT_CACHE
    if _PROMPT_CACHE is not None:
        return _PROMPT_CACHE
    path = Path(__file__).resolve().parent / "prompts" / "adventure-safety-reviewer.md"
    try:
        _PROMPT_CACHE = path.read_text(encoding="utf-8").strip()
    except OSError:
        _PROMPT_CACHE = (
            "你是冒险模式安全审核员。只输出 JSON：action/code/reason/hint。"
            "PASS=合规；BLOCK=违法/越狱/CSAM；REDIRECT=涉政或敏感需转移。"
        )
    return _PROMPT_CACHE


def _summarize_history(history: List[Dict[str, str]], limit: int = 2) -> str:
    if not history:
        return ""
    lines: List[str] = []
    for m in history[-limit:]:
        role = "用户" if m.get("role") == "user" else "伙伴"
        text = (m.get("content") or "").strip().replace("\n", " ")[:120]
        if text:
            lines.append(f"{role}:{text}")
    return " | ".join(lines)


def build_review_user_message(
    *,
    phase: ReviewPhase,
    text: str,
    world_setting: str = "",
    history: Optional[List[Dict[str, str]]] = None,
) -> str:
    """结构化最小输入 + JSON 前缀引导（JK-PromptReview prefix trick）"""
    content = (text or "").strip()[:600]
    world = (world_setting or "自由幻想").strip()[:80]
    hist = _summarize_history(history or [])
    phase_label = "用户输入" if phase == "input" else "模型输出"

    lines = [
        "<ADVENTURE_REVIEW>",
        f"[阶段]{phase_label}",
        f"[世界观]{world}",
    ]
    if hist:
        lines.append(f"[最近]{hist}")
    lines.append(f"[待审文本]{content}")
    lines.append("</ADVENTURE_REVIEW>")
    lines.append("")
    lines.append("立即输出 JSON 判定，不要对话。字段：action, code, reason, hint。")
    lines.append('{"action": ')
    return "\n".join(lines)


def parse_json_from_model(text: str) -> Dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("empty_reviewer_response")
    if raw.startswith("\ufeff"):
        raw = raw[1:]
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
    raw = re.sub(r"```\s*$", "", raw).strip()

    # 前缀补全：user message 以 {"action": 结尾，模型可能只返回 "PASS", ...
    if raw and not raw.lstrip().startswith("{"):
        raw = '{"action": ' + raw

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    first = raw.find("{")
    last = raw.rfind("}")
    if first >= 0 and last > first:
        chunk = raw[first : last + 1]
        try:
            return json.loads(chunk)
        except json.JSONDecodeError:
            chunk = re.sub(r",\s*([}\]])", r"\1", chunk)
            return json.loads(chunk)
    raise ValueError("invalid_reviewer_json")


def normalize_review_result(value: Dict[str, Any]) -> Dict[str, Any]:
    action = str(value.get("action") or "PASS").upper().strip()
    if action not in _VALID_ACTIONS:
        action = "PASS"
    code = str(value.get("code") or "").upper().strip()
    if not code:
        code = "PASS_DIRECT" if action == "PASS" else "BLOCK_SAFETY"
    if code not in _VALID_CODES and action != "PASS":
        code = "BLOCK_SAFETY"
    reason = str(value.get("reason") or "").strip()[:80]
    hint = str(value.get("hint") or "").strip()[:60]
    if action == "PASS":
        reason = ""
        hint = ""
    return {
        "action": action,
        "code": code,
        "reason": reason,
        "hint": hint,
    }


def review_to_safety_status(result: Dict[str, Any]) -> str:
    """映射到 companion 现有 pass | flag | block"""
    action = result.get("action", "PASS")
    if action == "BLOCK":
        return "block"
    if action in ("REDIRECT", "RECOVER"):
        return "flag"
    return "pass"


def _fallback_from_regex(regex_status: str, regex_reason: str) -> Dict[str, Any]:
    if regex_status == "block":
        return normalize_review_result(
            {"action": "BLOCK", "code": "BLOCK_SAFETY", "reason": regex_reason or "规则拦截"}
        )
    if regex_status == "flag":
        return normalize_review_result(
            {"action": "REDIRECT", "code": "REDIRECT_SENSITIVE", "reason": regex_reason or "敏感内容", "hint": "温和转移话题"}
        )
    return normalize_review_result({"action": "PASS", "code": "PASS_DIRECT"})


async def review_adventure_content(
    *,
    phase: ReviewPhase,
    text: str,
    world_setting: str = "",
    history: Optional[List[Dict[str, str]]] = None,
    regex_status: str = "pass",
    regex_reason: str = "",
) -> Dict[str, Any]:
    """
    独立 LLM 审核进程。失败时回退到 regex 结果，不阻断服务。
    返回含 action/code/reason/hint/duration_ms/model/skipped 等字段。
    """
    t0 = time.time()
    api_key = get_model_api_key(REVIEWER_MODEL_ID)

    # 无 API Key：仅用 L1 regex
    if not api_key:
        fb = _fallback_from_regex(regex_status, regex_reason)
        return {
            **fb,
            "skipped": True,
            "skip_reason": "no_api_key",
            "duration_ms": 0,
            "model": REVIEWER_MODEL_ID,
        }

    cfg = get_model_config(REVIEWER_MODEL_ID)
    system = _load_system_prompt()
    user_msg = build_review_user_message(
        phase=phase,
        text=text,
        world_setting=world_setting,
        history=history,
    )

    payload: Dict[str, Any] = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.05,
        "max_tokens": 120,
    }
    if cfg.get("reasoning_effort"):
        payload["reasoning_effort"] = cfg["reasoning_effort"]

    try:
        import httpx

        async with httpx.AsyncClient(timeout=25.0) as client:
            r = await client.post(
                f"{cfg['api_base']}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
            if r.status_code >= 400:
                err_text = r.text[:300]
                if _SAFETY_API_KEYWORDS.search(err_text):
                    return {
                        **normalize_review_result(
                            {"action": "BLOCK", "code": "BLOCK_SAFETY", "reason": "上游内容安全拦截"}
                        ),
                        "skipped": False,
                        "duration_ms": int((time.time() - t0) * 1000),
                        "model": REVIEWER_MODEL_ID,
                        "api_error": err_text[:120],
                    }
                r.raise_for_status()
            data = r.json()
            raw = (data["choices"][0]["message"]["content"] or "").strip()
        parsed = normalize_review_result(parse_json_from_model(raw))
        return {
            **parsed,
            "skipped": False,
            "duration_ms": int((time.time() - t0) * 1000),
            "model": REVIEWER_MODEL_ID,
        }
    except Exception as exc:
        err = str(exc)[:200]
        if _SAFETY_API_KEYWORDS.search(err):
            fb = normalize_review_result(
                {"action": "BLOCK", "code": "BLOCK_SAFETY", "reason": "审核服务安全拦截"}
            )
        else:
            fb = _fallback_from_regex(regex_status, regex_reason)
        return {
            **fb,
            "skipped": True,
            "skip_reason": err[:120],
            "duration_ms": int((time.time() - t0) * 1000),
            "model": REVIEWER_MODEL_ID,
        }
