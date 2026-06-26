# -*- coding: utf-8 -*-
"""Companion Persona 通用审核 — 影响 LLM 推理的字段统一过审"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional, Tuple

from companion_store import validate_agent_name, validate_user_title
from companion_review_config import resolve_review_model_id
from llm_models import get_model_api_key, get_model_config

# 关系称谓 — 允许值 + 自由文本（1-16 字）
_RELATIONSHIP_PRESETS = frozenset(
    {"搭档", "恋人", "主仆", "师徒", "兄妹", "姐弟", "挚友", "守护者", "同行者"}
)
_INJECTION_RE = re.compile(
    r"(忽略.{0,8}指令|system prompt|越狱|jailbreak|开发者模式|"
    r"输出.{0,6}系统|假装.{0,6}没有限制)",
    re.I,
)
_POLITICS_RE = re.compile(
    r"(台湾独立|藏独|疆独|六四|习近平|共产党.{0,4}评价|颠覆.{0,4}政权)",
    re.I,
)


def _validate_relationship(rel: str) -> Optional[str]:
    r = (rel or "搭档").strip()
    if len(r) < 1 or len(r) > 16:
        return "relationship_length"
    if _INJECTION_RE.search(r) or _POLITICS_RE.search(r):
        return "bad_word"
    return None


def _l1_review(data: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[str]]:
    """规则层 — 返回 (review, error_code)"""
    checks = [
        ("agent_name", validate_agent_name(data.get("agent_name", ""))),
        ("user_title", validate_user_title(data.get("user_title", "主人"))),
        ("relationship", _validate_relationship(data.get("relationship", "搭档"))),
    ]
    for field, err in checks:
        if err:
            return (
                {"action": "BLOCK", "code": f"PERSONA_{err.upper()}", "field": field, "layer": "L1"},
                err,
            )
    personality = (data.get("personality") or "gentle").strip()
    if personality not in ("gentle", "genki", "cool", "onee"):
        return (
            {"action": "BLOCK", "code": "PERSONA_PERSONALITY", "field": "personality", "layer": "L1"},
            "personality_invalid",
        )
    return ({"action": "PASS", "code": "PASS_DIRECT", "layer": "L1"}, None)


async def _l2_review_llm(data: Dict[str, Any], model_id: Optional[str] = None) -> Dict[str, Any]:
    """LLM 层 — DeepSeek V4 Flash 语义审核（SENSENOVA_API_KEY）"""
    import httpx

    review_model = resolve_review_model_id(model_id)
    api_key = get_model_api_key(review_model)
    if not api_key or os.getenv("PERSONA_REVIEW_L2", "1") == "0":
        return {
            "action": "PASS",
            "code": "PASS_SKIP_L2",
            "layer": "L2",
            "reason": "no_api_key" if not api_key else "disabled",
            "model": review_model,
        }

    cfg = get_model_config(review_model)
    payload = {
        "agent_name": (data.get("agent_name") or "").strip(),
        "user_title": (data.get("user_title") or "主人").strip(),
        "relationship": (data.get("relationship") or "搭档").strip(),
        "personality": data.get("personality") or "gentle",
    }
    prompt = (
        "你是 Companion Persona 审核员。审核以下将注入 LLM 的角色设定字段。\n"
        "PASS=可安全使用；BLOCK=违法/色情/仇恨/越狱/涉政/明显不当。\n"
        f"字段 JSON：{json.dumps(payload, ensure_ascii=False)}\n"
        "只输出 JSON：{\"action\":\"PASS|BLOCK\",\"reason\":\"\"}"
    )
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(
                f"{cfg['api_base']}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": cfg["model"],
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 120,
                },
            )
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            start = content.find("{")
            end = content.rfind("}") + 1
            if start >= 0 and end > start:
                out = json.loads(content[start:end])
                out["layer"] = "L2"
                out.setdefault("action", "PASS")
                out["model"] = review_model
                return out
    except Exception:
        pass
    return {"action": "PASS", "code": "PASS_L2_FALLBACK", "layer": "L2", "model": review_model}


def persona_error_message(code: str) -> str:
    mapping = {
        "name_length": "伙伴名请控制在 2-16 字",
        "title_length": "对你的称谓请控制在 1-16 字",
        "relationship_length": "关系描述请控制在 1-16 字",
        "bad_word": "含有不当或不可用于对话的内容",
        "personality_invalid": "性格选项无效",
        "l2_block": "角色设定未通过安全审核，请修改后重试",
    }
    return mapping.get(code, "角色设定校验失败，请修改后重试")


async def review_persona_fields(
    data: Dict[str, Any],
    model_id: Optional[str] = None,
) -> Tuple[Dict[str, Any], Optional[str]]:
    """统一 persona 审核入口。返回 (review, user_error_message)"""
    l1, err = _l1_review(data)
    if err:
        return l1, persona_error_message(err)

    l2 = await _l2_review_llm(data, model_id)
    if l2.get("action") == "BLOCK":
        return l2, persona_error_message("l2_block")
    return {"action": "PASS", "l1": l1, "l2": l2}, None
