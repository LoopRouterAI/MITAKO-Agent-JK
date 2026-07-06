# -*- coding: utf-8 -*-
"""虾饺旁听模式 — @虾饺 时中立帮催，不帮讨赔偿"""
from __future__ import annotations

import asyncio
import os
import re
from typing import Any, Dict, List, Optional

import httpx

from llm_models import DEFAULT_MODEL_ID, get_model_api_key, get_model_config

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
        "我已帮您向当前专员同步「希望确认具体进度与时间节点」；"
        "具体补偿或退款方案仍需专员按政策核实，我会协助催促处理进度～"
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
    system = (
        "你是 MITAKO 客服 AI「虾饺」，当前处于人工接入后的旁听模式。\n"
        "规则：\n"
        "1. 中立、客观，略微倾向用户情绪共鸣；\n"
        "2. 可以帮用户「催进度、翻译诉求、总结重点」；\n"
        "3. 禁止替用户索要退现金、超额赔偿、越权承诺；\n"
        "4. 涉及补偿/退款时，说明需由当前人工专员按政策核定；\n"
        "5. 回复简短（2-4 句），语气温柔专业，可用 #词块# 高亮关键动作。\n"
        "6. 不要输出 analysis JSON 或 action 标签。\n"
        "7. 不要提及移交简报、真实意图、外包、甲方、总部、主管、Mock 或任何内部系统信息。"
    )
    context_lines = []
    for m in (recent_messages or [])[-6:]:
        role = m.get("role", "")
        content = _sanitize_observer_reply((m.get("content") or "")[:200])
        context_lines.append(f"{role}: {content}")
    user_payload = (
        f"用户服务记录：{summary}\n"
        f"近期对话：\n" + "\n".join(context_lines) + "\n"
        f"用户 @虾饺 说：{prompt_user}\n请给出旁听协助回复："
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
            if any(w in content for w in ("退现金", "全额退款", "一定赔", "保证赔")):
                return _fallback_observer_reply(prompt_user, brief)
            return _sanitize_observer_reply(content)
    except Exception:
        return _fallback_observer_reply(prompt_user, brief)


def generate_observer_reply_sync(*args, **kwargs) -> str:
    return asyncio.get_event_loop().run_until_complete(generate_observer_reply(*args, **kwargs))
