# -*- coding: utf-8 -*-
"""转人工系统消息 i18n — 后端存 key+params，前端按 locale 渲染"""
from __future__ import annotations

from typing import Any, Dict, Tuple

_TEMPLATES: Dict[str, Tuple[str, str]] = {
    "transfer": (
        "handoff.sysTransfer",
        "已为您转接更合适的客服专员继续处理，请稍候。",
    ),
    "escalate": (
        "handoff.sysEscalate",
        "已为您升级处理，客服团队会继续跟进。",
    ),
    "sla_timeout": (
        "handoff.sysSlaTimeout",
        "已为您转接下一位客服专员继续处理，请稍候。",
    ),
    "closed": (
        "handoff.sysClosed",
        "本次服务已结束，如需继续咨询可以重新发起会话。",
    ),
}


def build_system_message(kind: str, **params: Any) -> Tuple[str, Dict[str, Any]]:
    key, fallback = _TEMPLATES.get(kind, ("handoff.sysGeneric", "{text}"))
    safe = {k: str(v or "") for k, v in params.items()}
    if kind in ("transfer", "escalate", "sla_timeout", "closed"):
        safe.pop("note", None)
        safe.pop("reason", None)
    try:
        content = fallback.format(**safe)
    except KeyError:
        content = fallback
    meta: Dict[str, Any] = {"kind": kind, "i18n_key": key, "i18n_params": safe}
    return content, meta
