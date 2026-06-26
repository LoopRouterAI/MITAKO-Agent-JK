# -*- coding: utf-8 -*-
"""
Companion × OpenViking — LangGraph load_memory / update_memory 节点的数据层

与客服 Agent 共用 viking:// 虚拟文件系统；Companion 用户 ID 形如 cmp_xxx。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from companion_memory import extract_memories_from_text, format_memories_for_prompt
from viking_memory import viking_db


def _profile_uri(user_id: str) -> str:
    return f"viking://user/{user_id}/profile"


def _normalize_item(raw: Dict[str, Any], idx: int = 0) -> Dict[str, Any]:
    return {
        "id": raw.get("id") or raw.get("fingerprint") or f"ov_{idx}",
        "category": raw.get("category") or "profile",
        "memory_key": raw.get("memory_key") or raw.get("key") or "记忆",
        "memory_value": raw.get("memory_value") or raw.get("value") or "",
        "source_message": raw.get("source_message") or "",
        "confidence": float(raw.get("confidence") or 0.75),
        "fingerprint": raw.get("fingerprint") or "",
        "updated_at": raw.get("updated_at") or time.time(),
    }


def _ensure_profile(user_id: str, persona: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    uri = _profile_uri(user_id)
    profile = viking_db.read_json(uri)
    persona = persona or {}
    if not profile:
        profile = {
            "user_id": user_id,
            "nickname": persona.get("user_title") or "主人",
            "metadata": {
                "agent_name": persona.get("agent_name") or "",
                "personality": persona.get("personality") or "gentle",
                "favorite_ips": [],
                "companion_source": True,
            },
            "communication_preferences": persona.get("communication_preferences") or {},
            "behavior_patterns": {
                "avg_emotion_level": 3.0,
                "companion_turns": 0,
            },
            "companion_memories": [],
            "chat_history": [],
        }
        viking_db.write_json(uri, profile)
    return profile


def _resolve_viking_level(profile: Dict[str, Any], emotion_level: int = 3) -> str:
    memories = profile.get("companion_memories") or []
    avg = float(profile.get("behavior_patterns", {}).get("avg_emotion_level") or 3.0)
    if avg >= 4.0 or emotion_level >= 5:
        return "L2"
    if len(memories) >= 3 or avg >= 3.5 or emotion_level >= 4:
        return "L1"
    return "L0"


def load_companion_memory(
    user_id: str,
    persona: Optional[Dict[str, Any]] = None,
    emotion_level: int = 3,
) -> Dict[str, Any]:
    """LangGraph load_memory 节点 — 从 OpenViking 装载 Companion 画像"""
    profile = _ensure_profile(user_id, persona)
    raw_items = profile.get("companion_memories") or []
    items = [_normalize_item(m, i) for i, m in enumerate(raw_items)]
    level = _resolve_viking_level(profile, emotion_level)
    line = format_memories_for_prompt(items)
    return {
        "user_memories": items,
        "memory_line": line,
        "viking_level": level,
        "memory_capsule": f"OpenViking: 已装载 {level} ({len(items)}条记忆)",
    }


def update_companion_memory(
    user_id: str,
    persona: Optional[Dict[str, Any]],
    user_message: str,
    assistant_reply: str,
    emotion_level: int = 3,
    emotion_label: str = "",
) -> Dict[str, Any]:
    """LangGraph update_memory 节点 — 提取并回写 OpenViking"""
    profile = _ensure_profile(user_id, persona)
    extracted = extract_memories_from_text(user_message, assistant_reply)
    stored: List[Dict[str, Any]] = list(profile.get("companion_memories") or [])
    fp_index = {m.get("fingerprint"): i for i, m in enumerate(stored) if m.get("fingerprint")}
    now = time.time()

    for item in extracted:
        fp = item.get("fingerprint") or ""
        if not fp:
            continue
        row = {
            "category": item.get("category"),
            "memory_key": item.get("memory_key"),
            "memory_value": item.get("memory_value"),
            "source_message": item.get("source_message"),
            "confidence": item.get("confidence"),
            "fingerprint": fp,
            "updated_at": now,
        }
        if fp in fp_index:
            old = stored[fp_index[fp]]
            row["confidence"] = max(float(old.get("confidence") or 0), float(row["confidence"] or 0))
            stored[fp_index[fp]] = row
        else:
            stored.append(row)

    # 同步 IP 到 metadata.favorite_ips
    fav_ips = set(profile.get("metadata", {}).get("favorite_ips") or [])
    for item in extracted:
        if item.get("category") == "interest":
            fav_ips.add(item.get("memory_value"))
    profile.setdefault("metadata", {})["favorite_ips"] = list(fav_ips)[:12]

    prev_avg = float(profile.get("behavior_patterns", {}).get("avg_emotion_level") or 3.0)
    profile.setdefault("behavior_patterns", {})["avg_emotion_level"] = round(prev_avg * 0.7 + emotion_level * 0.3, 2)
    profile["behavior_patterns"]["companion_turns"] = int(profile["behavior_patterns"].get("companion_turns") or 0) + 1

    history = list(profile.get("chat_history") or [])
    history.append({"role": "user", "content": user_message[:300], "emotion": emotion_level, "label": emotion_label})
    history.append({"role": "assistant", "content": assistant_reply[:300]})
    profile["chat_history"] = history[-20:]
    profile["companion_memories"] = stored[-40:]
    viking_db.write_json(_profile_uri(user_id), profile)

    items = [_normalize_item(m, i) for i, m in enumerate(profile["companion_memories"])]
    level = _resolve_viking_level(profile, emotion_level)
    return {
        "new_memories": extracted,
        "user_memories": items,
        "viking_level": level,
        "memory_capsule": f"OpenViking: {level} · 共 {len(items)} 条"
        + (f" (+{len(extracted)})" if extracted else ""),
    }


def list_companion_memories(user_id: str, limit: int = 30) -> List[Dict[str, Any]]:
    profile = viking_db.read_json(_profile_uri(user_id))
    raw = profile.get("companion_memories") or []
    items = [_normalize_item(m, i) for i, m in enumerate(raw)]
    return items[:limit]


def memory_summary(user_id: str) -> Dict[str, Any]:
    items = list_companion_memories(user_id, limit=40)
    by_cat: Dict[str, int] = {}
    for m in items:
        cat = m.get("category") or "other"
        by_cat[cat] = by_cat.get(cat, 0) + 1
    profile = viking_db.read_json(_profile_uri(user_id))
    level = _resolve_viking_level(profile) if profile else "L0"
    return {
        "total": len(items),
        "by_category": by_cat,
        "items": items,
        "viking_level": level,
        "storage": "openviking",
    }
