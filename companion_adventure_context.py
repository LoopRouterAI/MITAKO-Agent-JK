# -*- coding: utf-8 -*-
"""冒险模式上下文 — World Bible、OOC 纠偏、128K 压缩"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from llm_models import get_model_api_key, get_model_config
from companion_richtext import (
    ADVENTURE_MARKUP_VERSION,
    history_has_legacy_markup,
    sanitize_history_for_llm,
    strip_adventure_markers,
)

CONTEXT_TOKEN_BUDGET = int(os.getenv("ADVENTURE_CONTEXT_TOKEN_BUDGET", "128000"))
COMPRESS_THRESHOLD = int(os.getenv("ADVENTURE_CONTEXT_COMPRESS_THRESHOLD", "100000"))
RECENT_FULL_TURNS = int(os.getenv("ADVENTURE_RECENT_FULL_TURNS", "8"))

# 时代错位检测（轻量 regex）
_ANACHRONISM_PATTERNS = [
    (re.compile(r"加特林|机关枪|AK47|步枪扫射|冲锋枪", re.I), "modern_firearm"),
    (re.compile(r"飞机|直升机|无人机|导弹|坦克|核弹", re.I), "modern_vehicle_weapon"),
    (re.compile(r"手机|微信|抖音|互联网|电脑|笔记本|WiFi|GPS", re.I), "modern_tech"),
    (re.compile(r"汽车|高铁|地铁|火箭", re.I), "modern_transport"),
]


def estimate_tokens(text: str) -> int:
    """启发式 token 估算（中文约 1.5 char/token）"""
    if not text:
        return 0
    return max(1, int(len(text) * 1.5))


def estimate_messages_tokens(messages: List[Dict[str, str]]) -> int:
    total = 0
    for m in messages:
        total += estimate_tokens(m.get("content") or "") + 4
    return total


def build_fallback_bible(
    persona: Dict[str, Any],
    world_setting: str,
    world_title: str = "",
) -> Dict[str, Any]:
    """无 LLM 时的规则 bible"""
    user_title = persona.get("user_title") or "主人"
    agent_name = persona.get("agent_name") or "小伴"
    world = (world_setting or "自由幻想世界").strip()
    title = (world_title or world[:24]).strip()
    era = "幻想"
    if any(k in world for k in ("三国", "汉代", "唐朝", "宋朝", "明朝", "清朝", "古代")):
        era = "古代东方"
    elif any(k in world for k in ("原神", "提瓦特", "二次元", "异世界")):
        era = "幻想异世界"
    elif any(k in world for k in ("科幻", "赛博", "未来")):
        era = "近未来科幻"
    return {
        "era_label": era,
        "world_title": title,
        "world_setting": world[:500],
        "tech_ceiling": "符合「" + era + "」的技术与常识，无未解释的现代科技",
        "address_user": user_title,
        "address_agent": agent_name,
        "visual_style": f"与「{world}」世界观一致的 cinematic semi-realistic 电影感",
        "color_mood": "跟随场景自然光影",
        "anachronism_policy": "unknown_object",
        "taboo_list": ["现代枪械直述", "现实政治", "色情描写"],
    }


async def generate_world_bible_llm(
    persona: Dict[str, Any],
    world_setting: str,
    world_title: str = "",
    model_id: Optional[str] = None,
) -> Dict[str, Any]:
    """LLM 生成 World Bible JSON"""
    import httpx

    fallback = build_fallback_bible(persona, world_setting, world_title)
    api_key = get_model_api_key(model_id)
    if not api_key:
        return fallback

    cfg = get_model_config(model_id)
    user_title = persona.get("user_title") or "主人"
    agent_name = persona.get("agent_name") or "小伴"
    prompt = (
        f"为文字冒险生成世界观锁定 JSON。世界观：{world_setting}\n"
        f"用户称谓：{user_title}，伙伴名：{agent_name}。\n"
        "只输出 JSON，字段：era_label, tech_ceiling, address_user, address_agent, "
        "visual_style, color_mood, anachronism_policy, taboo_list(数组)。"
    )
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            r = await client.post(
                f"{cfg['api_base']}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": cfg["model"],
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 600,
                },
            )
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            start = content.find("{")
            end = content.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(content[start:end])
                data["world_title"] = (world_title or world_setting[:24]).strip()
                data["world_setting"] = world_setting[:500]
                data.setdefault("address_user", user_title)
                data.setdefault("address_agent", agent_name)
                return data
    except Exception:
        pass
    return fallback


def detect_anachronism(text: str, bible: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """检测用户输入是否含时代错位概念，返回类别或 None"""
    msg = text or ""
    for pat, category in _ANACHRONISM_PATTERNS:
        if pat.search(msg):
            if bible and bible.get("era_label") == "近未来科幻":
                if category == "modern_tech":
                    return None
            return category
    return None


def wrap_user_message_for_ooc(
    user_message: str,
    bible: Optional[Dict[str, Any]],
) -> Tuple[str, Optional[str]]:
    """若检测到错位，返回增强后的 user 消息与纠偏提示"""
    category = detect_anachronism(user_message, bible)
    if not category:
        return user_message, None
    era = (bible or {}).get("era_label") or "当前世界观"
    tech = (bible or {}).get("tech_ceiling") or "时代常识"
    hint = (
        f"（世界观守卫：用户提到了可能超出「{era}」的事物（{category}）。"
        f"请以 {bible.get('address_agent', '伙伴')} 的身份，在「{tech}」范围内回应——"
        f"可表示不解、用相近古风/幻想概念类比，并拉回当前场景；勿硬接现代设定。）"
    )
    return f"{user_message}\n\n{hint}", category


def format_bible_for_system(bible: Dict[str, Any]) -> str:
    if not bible:
        return ""
    return (
        f"【世界观锁定】时代：{bible.get('era_label', '')}；"
        f"技术上限：{bible.get('tech_ceiling', '')}；"
        f"视觉风格：{bible.get('visual_style', '')}；"
        f"错位策略：{bible.get('anachronism_policy', 'unknown_object')}。"
    )


def build_context_bundle(
    system_base: str,
    bible: Optional[Dict[str, Any]],
    summary_text: str,
    history: List[Dict[str, str]],
    user_message: str,
    asset_captions: Optional[List[str]] = None,
) -> Tuple[List[Dict[str, str]], int, bool]:
    """
    组装 LLM messages，返回 (messages, estimated_tokens, compressed_used)
    历史 assistant 消息会先 normalize 为 v2 契约，避免旧 markup 污染模型输出。
    """
    bible_block = format_bible_for_system(bible or {})
    asset_block = ""
    if asset_captions:
        asset_block = "【视觉资产索引】\n" + "\n".join(asset_captions[:12])

    system = system_base
    if bible_block:
        system += "\n\n" + bible_block
    if asset_block:
        system += "\n\n" + asset_block
    if summary_text:
        system += f"\n\n【前情摘要】\n{summary_text}"
    if history_has_legacy_markup(history):
        system += (
            f"\n\n【格式提醒 v{ADVENTURE_MARKUP_VERSION}】"
            "对话历史中可能含旧版错误标记；请严格按当前契约输出，"
            "场景用 >>标题<<，对白用 <say role=\"…\" name=\"…\">…</say>，"
            "禁止 <>、>标题>、>/SAY>>。"
        )

    messages: List[Dict[str, str]] = [{"role": "system", "content": system}]

    clean_history = sanitize_history_for_llm(history or [])
    recent = clean_history[-RECENT_FULL_TURNS * 2 :] if clean_history else []
    older = clean_history[: max(0, len(clean_history) - len(recent))]

    compressed_used = bool(summary_text and older)
    for m in recent:
        messages.append({"role": m.get("role", "user"), "content": (m.get("content") or "")[:1200]})

    messages.append({"role": "user", "content": user_message})
    tokens = estimate_messages_tokens(messages)
    return messages, tokens, compressed_used


async def maybe_compress_history_summary(
    history: List[Dict[str, str]],
    existing_summary: str,
    persona: Dict[str, Any],
    model_id: Optional[str] = None,
) -> str:
    """超阈值时滚动摘要较早回合"""
    import httpx

    full_text = existing_summary + "\n" + "\n".join(
        f"{m.get('role')}: {strip_adventure_markers((m.get('content') or '')[:400])}"
        for m in history[:-RECENT_FULL_TURNS * 2]
    )
    if estimate_tokens(full_text) < COMPRESS_THRESHOLD:
        return existing_summary

    api_key = get_model_api_key(model_id)
    if not api_key:
        return (existing_summary + "\n" + full_text[-3000:])[:8000]

    cfg = get_model_config(model_id)
    agent = persona.get("agent_name") or "小伴"
    user_title = persona.get("user_title") or "主人"
    prompt = (
        f"将以下冒险对话压缩为第三人称摘要（500字内），保留关键抉择、NPC、场景。"
        f"用 {user_title} 与 {agent} 称呼，禁止「我」「你」。\n\n{full_text[-12000:]}"
    )
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                f"{cfg['api_base']}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": cfg["model"],
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.4,
                    "max_tokens": 800,
                },
            )
            r.raise_for_status()
            return (r.json()["choices"][0]["message"]["content"] or existing_summary).strip()
    except Exception:
        return (existing_summary + "\n" + full_text[-2000:])[:8000]
