# -*- coding: utf-8 -*-
"""客服 API、用户端和坐席端共用的最小公开状态投影。"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from review_public_safety import redact_public_review_data


_SENSITIVE_FACT_FIELD = re.compile(
    r"(?:^|[._-])(?:identity|id_card|phone|mobile|address|email|name|account|bank|tracking)(?:$|[._-])",
    re.IGNORECASE,
)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _strings(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _intent(value: Any) -> dict[str, Any]:
    raw = _mapping(value)
    if not raw:
        return {}
    return {
        "intent_code": str(raw.get("intent_code") or ""),
        "scenario_code": str(raw.get("scenario_code") or ""),
        "intent_codes": _strings(raw.get("intent_codes")),
        "scenario_codes": _strings(raw.get("scenario_codes")),
        "confidence": raw.get("confidence"),
        "requires_clarification": bool(raw.get("requires_clarification")),
        "clarification_fields": _strings(raw.get("clarification_fields")),
    }


def _facts(value: Any) -> list[dict[str, Any]]:
    public: list[dict[str, Any]] = []
    for item in value if isinstance(value, list) else []:
        raw = _mapping(item)
        field = str(raw.get("field") or "")
        if not field or _SENSITIVE_FACT_FIELD.search(field):
            continue
        row = {
            "field": field,
            "source": str(raw.get("source") or ""),
            "verified": bool(raw.get("verified")),
        }
        fact_value = raw.get("value")
        if isinstance(fact_value, (bool, int, float)) or fact_value is None:
            row["value"] = fact_value
        public.append(row)
    return public


def _material_state(value: Any) -> dict[str, Any]:
    raw = _mapping(value)
    allowed = {
        "scenario",
        "status",
        "missing",
        "warnings",
        "received_count",
        "required_count",
    }
    return redact_public_review_data({key: raw[key] for key in allowed if key in raw})


def _action_state(value: Any) -> dict[str, Any]:
    raw = _mapping(value)
    return {
        "action": str(raw.get("action") or ""),
        "status": str(raw.get("status") or "not_requested"),
        "receipt_id": str(raw.get("receipt_id") or ""),
        "reason_code": str(raw.get("reason_code") or ""),
        "occurred_at": str(raw.get("occurred_at") or ""),
    }


def _next_step(value: Any) -> dict[str, Any]:
    raw = _mapping(value)
    if not raw:
        return {}
    return redact_public_review_data({
        "code": str(raw.get("code") or ""),
        "label": str(raw.get("label") or ""),
        "user_action_required": bool(raw.get("user_action_required")),
    })


def project_conversation_state(value: Any) -> dict[str, Any]:
    """只输出用户与坐席需要核对的结构化状态。"""
    raw = _mapping(value)
    scenario = _mapping(raw.get("scenario_decision"))
    required_fields = _strings(raw.get("required_reply_fields"))
    reply_fields = _mapping(raw.get("reply_fields"))
    return {
        "intent": _intent(raw.get("intent")),
        "facts": _facts(raw.get("facts")),
        "material_state": _material_state(raw.get("material_state")),
        "action_state": _action_state(raw.get("action_state")),
        "next_step": _next_step(raw.get("next_step") or scenario.get("next_step")),
        "core_conclusion": str(raw.get("core_conclusion") or scenario.get("core_conclusion") or ""),
        "required_reply_fields": required_fields,
        "reply_fields": redact_public_review_data({
            key: reply_fields.get(key)
            for key in required_fields
            if key in reply_fields
        }),
    }
