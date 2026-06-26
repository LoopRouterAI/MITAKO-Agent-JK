# -*- coding: utf-8 -*-
"""转人工系统消息 i18n — 后端存 key+params，前端按 locale 渲染"""
from __future__ import annotations

from typing import Any, Dict, Tuple

_TEMPLATES: Dict[str, Tuple[str, str]] = {
    "transfer": (
        "handoff.sysTransfer",
        "会话已由 {from_agent} 转交至 {to_agent} 待确认接管。{note}",
    ),
    "escalate": (
        "handoff.sysEscalate",
        "已升级至总部客诉队列，请主管确认接管。{note}",
    ),
    "sla_timeout": (
        "handoff.sysSlaTimeout",
        "因 SLA 超时（{reason}），系统已将会话转交至 {to_agent} 待确认接管。",
    ),
    "closed": (
        "handoff.sysClosed",
        "{note}",
    ),
}


def build_system_message(kind: str, **params: Any) -> Tuple[str, Dict[str, Any]]:
    key, fallback = _TEMPLATES.get(kind, ("handoff.sysGeneric", "{text}"))
    safe = {k: str(v or "") for k, v in params.items()}
    if kind == "closed" and not safe.get("note"):
        safe["note"] = "会话已结束"
    if kind == "transfer" and not safe.get("note"):
        safe["note"] = ""
    try:
        content = fallback.format(**safe)
    except KeyError:
        content = fallback
    meta: Dict[str, Any] = {"kind": kind, "i18n_key": key, "i18n_params": safe}
    return content, meta
