# -*- coding: utf-8 -*-
"""转VIP客服路由规则：按租户隔离的外置 JSON 配置。"""
from __future__ import annotations

import json
import os
from typing import Any, Dict

from runtime_paths import app_root

_DEFAULT: Dict[str, Any] = {
    "default_required_tier": "standard",
    "rules": [],
    "sla": {
        "first_response_seconds": 180,
        "reply_timeout_seconds": 300,
        "auto_transfer_enabled": True,
    },
}

_CONFIG_PATH = os.path.join(str(app_root()), "config", "handoff_routing.json")
_cached: Dict[str, Dict[str, Any]] = {}


def _tenant_key(tenant_id: str | None = None) -> str:
    return (tenant_id or "mitako").strip() or "mitako"


def _config_path(tenant_id: str | None = None) -> str:
    tenant = _tenant_key(tenant_id)
    if tenant == "mitako":
        return _CONFIG_PATH
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in tenant)
    return os.path.join(os.path.dirname(_CONFIG_PATH), "tenants", safe, "handoff_routing.json")


def _merge_default(config: Dict[str, Any] | None) -> Dict[str, Any]:
    raw = config or {}
    merged = {**_DEFAULT, **raw}
    merged["sla"] = {**(_DEFAULT.get("sla") or {}), **(raw.get("sla") or {})}
    return merged


def load_routing_config(force_reload: bool = False, tenant_id: str | None = None) -> Dict[str, Any]:
    tenant = _tenant_key(tenant_id)
    if tenant in _cached and not force_reload:
        return _cached[tenant]
    path = _config_path(tenant)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            _cached[tenant] = _merge_default(json.load(f))
    else:
        _cached[tenant] = _merge_default({})
    return _cached[tenant]


def resolve_required_tier(brief: Dict[str, Any], tenant_id: str | None = None) -> str:
    """按租户配置计算 required_tier；默认 standard，仅启用规则时升级。"""
    cfg = load_routing_config(tenant_id=tenant_id or (brief or {}).get("tenant_id"))
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


def get_sla_config(tenant_id: str | None = None) -> Dict[str, Any]:
    return load_routing_config(tenant_id=tenant_id).get("sla") or _DEFAULT["sla"]


def save_routing_config(config: Dict[str, Any], tenant_id: str | None = None) -> Dict[str, Any]:
    """持久化当前租户的路由配置。"""
    tenant = _tenant_key(tenant_id)
    merged = _merge_default(config)
    path = _config_path(tenant)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
        f.write("\n")
    _cached[tenant] = merged
    return merged
