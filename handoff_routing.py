# -*- coding: utf-8 -*-
"""转人工路由规则 — 外置 JSON，默认外包一线接单"""
from __future__ import annotations

import json
import os
from typing import Any, Dict

_DEFAULT: Dict[str, Any] = {
    "default_required_tier": "standard",
    "rules": [],
    "sla": {
        "first_response_seconds": 180,
        "reply_timeout_seconds": 300,
        "auto_transfer_enabled": True,
    },
}

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config", "handoff_routing.json")
_cached: Dict[str, Any] | None = None


def load_routing_config(force_reload: bool = False) -> Dict[str, Any]:
    global _cached
    if _cached is not None and not force_reload:
        return _cached
    if os.path.exists(_CONFIG_PATH):
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            _cached = {**_DEFAULT, **json.load(f)}
    else:
        _cached = dict(_DEFAULT)
    return _cached


def resolve_required_tier(brief: Dict[str, Any]) -> str:
    """按配置计算 required_tier；默认 standard，仅启用规则时升级"""
    cfg = load_routing_config()
    default = cfg.get("default_required_tier") or "standard"
    emotion = int(brief.get("emotion_level") or 2)
    profile = brief.get("user_profile") or {}
    member = profile.get("member_level") or ""

    for rule in cfg.get("rules") or []:
        if not rule.get("enabled"):
            continue
        cond = rule.get("condition") or {}
        if cond.get("emotion_level_gte") is not None and emotion >= int(cond["emotion_level_gte"]):
            return rule.get("required_tier") or default
        levels = cond.get("member_level_in") or []
        if levels and member in levels:
            return rule.get("required_tier") or default
    return default


def get_sla_config() -> Dict[str, Any]:
    return load_routing_config().get("sla") or _DEFAULT["sla"]


def save_routing_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """持久化路由配置（管理后台）"""
    global _cached
    merged = {**_DEFAULT, **config}
    os.makedirs(os.path.dirname(_CONFIG_PATH), exist_ok=True)
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    _cached = merged
    return merged
