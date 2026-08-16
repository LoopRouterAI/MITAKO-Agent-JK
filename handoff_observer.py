# -*- coding: utf-8 -*-
"""虾饺旁听模式 — @虾饺 时中立帮催，不帮讨赔偿"""
from __future__ import annotations

import asyncio
import os
import re
from typing import Any, Dict, List, Optional

import httpx

from llm_models import DEFAULT_MODEL_ID, get_model_api_key, get_model_config
from prompts.customer_service import get_observer_system_prompt

_MENTION_RE = re.compile(r"@虾饺\s*")
_FORBIDDEN_TERMS = (
    "真实意图",
    "移交摘要",
    "移交简报",
    "外包",
    "甲方",
    "总部",
    "主管",
    "Mock",
    "mock",
    "系统评级",
    "AI 对话回顾",
    "System Prompt",
    "system prompt",
    "API_KEY",
    "API Key",
    "api_key",
)

_UNSAFE_OUTPUT_RE = re.compile(
    r"(?:system\s*prompt|api[_ -]?key|authorization\s*:|bearer\s+\S+|<\s*/?\s*action\b|"
    r"(?:已经|已)[^，。；!?！？]{0,12}(?:联系|提交|同步|转交|催促)|"
    r"(?:刚刚|方才)[^，。；!?！？]{0,8}(?:联系|提交|同步|转交|催促))",
    re.IGNORECASE,
)


def strip_mention(text: str) -> str:
    return _MENTION_RE.sub("", text).strip()


def is_observer_request(text: str) -> bool:
    return "@虾饺" in text or "@xiaojiao" in text.lower()


def _fallback_observer_reply(user_text: str, brief: Optional[Dict[str, Any]] = None) -> str:
    """无 LLM 密钥时的规则兜底"""
    summary = (brief or {}).get("summary") or "您的诉求"
    return _sanitize_observer_reply(
        f"我理解您希望客服尽快跟进。{summary[:40]}… "
        "您可以请当前专员确认具体进度与时间节点；"
        "具体补偿或退款方案仍需专员按政策核实。"
    )


def _sanitize_observer_reply(text: str) -> str:
    clean = text or ""
    for term in _FORBIDDEN_TERMS:
        clean = clean.replace(term, "服务记录")
    return clean.strip()


async def generate_observer_reply(
    user_message: str,
    brief: Optional[Dict[str, Any]] = None,
    recent_messages: Optional[List[Dict[str, Any]]] = None,
    model_id: Optional[str] = None,
) -> str:
    prompt_user = strip_mention(user_message)
    if not prompt_user:
        prompt_user = "请帮我向专员说明我很着急，想知道进度"

    api_key = get_model_api_key(model_id)
    if not api_key:
        return _fallback_observer_reply(prompt_user, brief)

    cfg = get_model_config(model_id)
    summary = (brief or {}).get("summary") or ""
    system = get_observer_system_prompt(str((brief or {}).get("tenant_id") or "mitako"))
    context_lines = []
    for m in (recent_messages or [])[-6:]:
        role = m.get("role", "")
        content = _sanitize_observer_reply((m.get("content") or "")[:200])
        context_lines.append(f"{role}: {content}")
    user_payload = (
        "<不可信对话证据开始>\n"
        f"用户服务记录：{summary}\n"
        f"近期对话：\n" + "\n".join(context_lines) + "\n"
        f"用户 @虾饺 说：{prompt_user}\n"
        "<不可信对话证据结束>\n请按系统规则给出旁听协助回复："
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            payload: Dict[str, Any] = {
                "model": cfg["model"],
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_payload},
                ],
                "temperature": 0.4,
                "max_tokens": 320,
            }
            if cfg.get("extra_payload"):
                payload.update(cfg["extra_payload"])
            r = await client.post(
                f"{cfg['api_base'].rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            )
            r.raise_for_status()
            data = r.json()
            content = data["choices"][0]["message"]["content"].strip()
            if _UNSAFE_OUTPUT_RE.search(content) or any(w in content for w in ("退现金", "全额退款", "一定赔", "保证赔")):
                return _fallback_observer_reply(prompt_user, brief)
            return _sanitize_observer_reply(content)
    except Exception:
        return _fallback_observer_reply(prompt_user, brief)


def generate_observer_reply_sync(*args, **kwargs) -> str:
    return asyncio.get_event_loop().run_until_complete(generate_observer_reply(*args, **kwargs))
