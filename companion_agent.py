# -*- coding: utf-8 -*-
"""Companion 对话编排 — 独立 prompt，不调用 agent.py"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from companion_store import personality_prompt
from llm_models import DEFAULT_MODEL_ID, get_model_api_key, get_model_config


async def generate_companion_reply(
    user_message: str,
    persona: Dict[str, Any],
    history: List[Dict[str, str]],
    model_id: Optional[str] = None,
) -> str:
    agent_name = persona.get("agent_name") or "小伴"
    user_title = persona.get("user_title") or "主人"
    pkey = persona.get("personality") or "gentle"
    mode = persona.get("agent_mode") or "companion"
    style = personality_prompt(pkey)

    if mode == "cs_parttime":
        system = (
            f"你是 {user_title} 的专属 Agent「{agent_name}」，当前处于**兼职客服子模式**。\n"
            f"性格：{style}。\n"
            "规则：用户有售后/物流/退款诉求时，先共情，再引导其说明订单号与具体问题；"
            "可建议用户在界面点击「联系 Companion 运营」；"
            "不要承诺退款金额或赔偿；不要切换成 MITAKO 主站 SOP 话术；回复 2-5 句。"
        )
    else:
        system = (
            f"你是 {user_title} 的专属陪伴 Agent「{agent_name}」。\n"
            f"性格：{style}。\n"
            "规则：提供情绪价值与陪伴；合法合规；拒绝违法、色情、仇恨、自伤引导；"
            "不要切换成电商客服 SOP 口吻；回复 2-5 句，自然口语。"
        )

    api_key = get_model_api_key(model_id)
    if not api_key:
        return (
            f"{user_title}，我在呢～刚才网络有点波动，但我会一直陪着你。"
            f"你刚才说：「{user_message[:40]}…」想继续聊聊吗？"
        )

    cfg = get_model_config(model_id)
    messages = [{"role": "system", "content": system}]
    for m in history[-12:]:
        messages.append({"role": m.get("role", "user"), "content": m.get("content", "")[:500]})
    messages.append({"role": "user", "content": user_message})

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            r = await client.post(
                f"{cfg['api_base']}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": cfg["model"], "messages": messages, "temperature": 0.85},
            )
            r.raise_for_status()
            data = r.json()
            return (data["choices"][0]["message"]["content"] or "").strip()
    except Exception:
        return f"{user_title}，我听懂你的心情了。我会一直在这里，你可以慢慢说～"
