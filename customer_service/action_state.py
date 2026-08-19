# -*- coding: utf-8 -*-
"""工具返回到客服动作状态的统一归一化。"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import math
from typing import Any

from .contracts import ActionState, ActionStatus


_STATUS_ALIASES = {
    "requested": ActionStatus.REQUESTED,
    "accepted": ActionStatus.ACCEPTED,
    "connected": ActionStatus.ACCEPTED,
    "closed": ActionStatus.ACCEPTED,
    "queued": ActionStatus.QUEUED,
    "queuing": ActionStatus.QUEUED,
    "succeeded": ActionStatus.SUCCEEDED,
    "success": ActionStatus.SUCCEEDED,
    "completed": ActionStatus.SUCCEEDED,
    "done": ActionStatus.SUCCEEDED,
    "failed": ActionStatus.FAILED,
    "error": ActionStatus.FAILED,
    "rejected": ActionStatus.FAILED,
    "pending_human": ActionStatus.PENDING_HUMAN,
    "pending": ActionStatus.PENDING_HUMAN,
    "ready_for_review": ActionStatus.PENDING_HUMAN,
    "approval_required": ActionStatus.PENDING_HUMAN,
    "escalated": ActionStatus.PENDING_HUMAN,
    "transferring": ActionStatus.PENDING_HUMAN,
}
_COMPLETED_STATUSES = {ActionStatus.QUEUED, ActionStatus.SUCCEEDED}
_DEFAULT_REASON = {
    ActionStatus.REQUESTED: "tool_requested",
    ActionStatus.ACCEPTED: "tool_accepted",
    ActionStatus.QUEUED: "queue_joined",
    ActionStatus.SUCCEEDED: "tool_succeeded",
    ActionStatus.FAILED: "tool_failed",
    ActionStatus.PENDING_HUMAN: "pending_human_review",
}
_RECEIPT_KEYS = ("receipt_id", "queue_id", "ticket_id", "task_id", "card_id", "compensation_id", "session_id", "id")
_OCCURRED_KEYS = ("occurred_at", "created_at", "enqueued_at", "accepted_at", "updated_at")
_MISSING = object()
_PUBLIC_REASON_CODES = set(_DEFAULT_REASON.values()) | {
    "action_mismatch",
    "address_updated",
    "connected",
    "entitlement_baseline_required",
    "human_handoff_accepted",
    "invalid_action_request",
    "invalid_tool_receipt",
    "invalid_tool_response",
    "invalid_tool_status",
    "invalid_tool_timestamp",
    "order_selection_required",
    "partner_integration_not_connected",
    "pending_human_handoff",
    "queue_already_joined",
    "tool_error",
    "tool_forbidden",
    "tool_rejected",
    "tool_timeout",
    "tool_unavailable",
    "upstream_rejected",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def normalize_reason_code(value: Any, fallback: str = "tool_error") -> str:
    code = _text(value)
    return code if code in _PUBLIC_REASON_CODES else fallback


def _field(*sources: Mapping[str, Any], keys: tuple[str, ...]) -> str:
    for source in sources:
        for key in keys:
            text = _text(source.get(key))
            if text:
                return text
    return ""


def _raw_field(*sources: Mapping[str, Any], keys: tuple[str, ...]) -> object:
    for source in sources:
        for key in keys:
            if key in source:
                return source[key]
    return _MISSING


def _has_field(source: Mapping[str, Any], keys: tuple[str, ...]) -> bool:
    return any(key in source for key in keys)


def _explicit_field_is_blank(source: Mapping[str, Any], keys: tuple[str, ...]) -> bool:
    value = _raw_field(source, keys=keys)
    return value is None or isinstance(value, str) and not value.strip()


def _receipt_field(*sources: Mapping[str, Any]) -> tuple[str, bool]:
    value = _raw_field(*sources, keys=_RECEIPT_KEYS)
    if not isinstance(value, str):
        return "", False
    receipt_id = value.strip()
    return receipt_id, bool(receipt_id)


def _timestamp_field(*sources: Mapping[str, Any]) -> tuple[str, bool]:
    value = _raw_field(*sources, keys=_OCCURRED_KEYS)
    if isinstance(value, bool) or value is _MISSING:
        return "", False
    if isinstance(value, str):
        timestamp = value.strip()
        if not timestamp:
            return "", False
        try:
            datetime.fromisoformat(timestamp[:-1] + "+00:00" if timestamp.endswith("Z") else timestamp)
        except ValueError:
            return "", False
        return timestamp, True
    if isinstance(value, (int, float)):
        try:
            epoch = float(value)
            if not math.isfinite(epoch):
                return "", False
            return datetime.fromtimestamp(epoch, timezone.utc).isoformat(), True
        except (OverflowError, OSError, TypeError, ValueError):
            return "", False
    return "", False


def _failed(action: str, tool_name: str, reason_code: str, occurred_at: str = "") -> ActionState:
    return ActionState(
        action=action,
        status=ActionStatus.FAILED,
        tool_name=tool_name,
        reason_code=reason_code,
        occurred_at=occurred_at or _now(),
    )


def _is_unconnected_mock(response: Mapping[str, Any]) -> bool:
    return (
        response.get("real_partner_integration") is False
        or _text(response.get("integration_status")).lower() in {"not_connected", "mock", "contract_only"}
        or _text(response.get("write_effect")).lower() == "none"
    )


def action_from_tool(action: str, tool_name: str, response: object) -> ActionState:
    action_name = _text(action)
    normalized_tool = _text(tool_name)
    if not action_name or not normalized_tool:
        return _failed(action_name, normalized_tool, "invalid_action_request")
    if not isinstance(response, Mapping) or not response:
        return _failed(action_name, normalized_tool, "invalid_tool_response")

    nested = response.get("action_state")
    state_source = nested if isinstance(nested, Mapping) else {}
    top_action = _text(response.get("action"))
    top_tool = _text(response.get("tool_name"))
    nested_action = _text(state_source.get("action"))
    nested_tool = _text(state_source.get("tool_name"))
    if (
        ("action" in response and top_action != action_name)
        or ("tool_name" in response and top_tool != normalized_tool)
        or ("action" in state_source and nested_action != action_name)
        or ("tool_name" in state_source and nested_tool != normalized_tool)
    ):
        return _failed(action_name, normalized_tool, "action_mismatch")

    status_keys = ("status", "action_status")
    top_status_text = _text(_raw_field(response, keys=status_keys)) if _has_field(response, status_keys) else ""
    nested_status_text = _text(_raw_field(state_source, keys=status_keys)) if _has_field(state_source, status_keys) else ""
    top_status = _STATUS_ALIASES.get(top_status_text.lower()) if top_status_text else None
    nested_status = _STATUS_ALIASES.get(nested_status_text.lower()) if nested_status_text else None
    if (
        _has_field(response, status_keys) and top_status is None
        or _has_field(state_source, status_keys) and nested_status is None
    ):
        return _failed(action_name, normalized_tool, "invalid_tool_status")
    if top_status and nested_status and top_status != nested_status:
        return _failed(action_name, normalized_tool, "invalid_tool_receipt")
    status = nested_status or top_status
    if status is None:
        return _failed(action_name, normalized_tool, "invalid_tool_status")

    nested_receipt_provided = _has_field(state_source, _RECEIPT_KEYS)
    top_receipt_provided = _has_field(response, _RECEIPT_KEYS)
    nested_receipt, nested_receipt_valid = _receipt_field(state_source)
    top_receipt, top_receipt_valid = _receipt_field(response)
    if (
        nested_receipt_provided
        and not nested_receipt_valid
        and (status in _COMPLETED_STATUSES or not _explicit_field_is_blank(state_source, _RECEIPT_KEYS))
        or top_receipt_provided
        and not top_receipt_valid
        and (status in _COMPLETED_STATUSES or not _explicit_field_is_blank(response, _RECEIPT_KEYS))
    ):
        return _failed(action_name, normalized_tool, "invalid_tool_receipt")
    if nested_receipt_valid and top_receipt_valid and nested_receipt != top_receipt:
        return _failed(action_name, normalized_tool, "invalid_tool_receipt")
    receipt_id = nested_receipt if nested_receipt_valid else top_receipt
    receipt_valid = nested_receipt_valid or top_receipt_valid

    nested_timestamp_provided = _has_field(state_source, _OCCURRED_KEYS)
    top_timestamp_provided = _has_field(response, _OCCURRED_KEYS)
    nested_timestamp, nested_timestamp_valid = _timestamp_field(state_source)
    top_timestamp, top_timestamp_valid = _timestamp_field(response)
    if (
        nested_timestamp_provided
        and not nested_timestamp_valid
        and (status in _COMPLETED_STATUSES or not _explicit_field_is_blank(state_source, _OCCURRED_KEYS))
        or top_timestamp_provided
        and not top_timestamp_valid
        and (status in _COMPLETED_STATUSES or not _explicit_field_is_blank(response, _OCCURRED_KEYS))
    ):
        return _failed(action_name, normalized_tool, "invalid_tool_timestamp")
    if nested_timestamp_valid and top_timestamp_valid and nested_timestamp != top_timestamp:
        return _failed(action_name, normalized_tool, "invalid_tool_timestamp")
    occurred_at = nested_timestamp if nested_timestamp_valid else top_timestamp
    timestamp_valid = nested_timestamp_valid or top_timestamp_valid
    mock_response = dict(response)
    if state_source:
        mock_response.update(state_source)
    unconnected_mock = _is_unconnected_mock(mock_response)
    negative_result = any(
        source.get(key) is False
        for source in (response, state_source)
        for key in ("ok", "success")
    )
    if negative_result and not (
        unconnected_mock and status in {ActionStatus.REQUESTED, ActionStatus.PENDING_HUMAN}
    ):
        reason = normalize_reason_code(
            _field(state_source, response, keys=("reason_code", "code")),
            "tool_rejected",
        )
        return _failed(action_name, normalized_tool, reason, occurred_at)

    if unconnected_mock and status in _COMPLETED_STATUSES:
        status = ActionStatus.REQUESTED
        reason_code = "partner_integration_not_connected"
    else:
        reason_code = normalize_reason_code(
            _field(state_source, response, keys=("reason_code", "code")),
            _DEFAULT_REASON[status],
        )

    if status in _COMPLETED_STATUSES:
        if not receipt_valid:
            return _failed(action_name, normalized_tool, "invalid_tool_receipt", occurred_at)
        if not timestamp_valid:
            return _failed(action_name, normalized_tool, "invalid_tool_timestamp")

    return ActionState(
        action=action_name,
        status=status,
        receipt_id=receipt_id,
        tool_name=normalized_tool,
        reason_code=reason_code,
        occurred_at=occurred_at,
    )


def action_from_exception(action: str, tool_name: str, error: BaseException) -> ActionState:
    if isinstance(error, TimeoutError):
        reason_code = "tool_timeout"
    elif isinstance(error, PermissionError):
        reason_code = "tool_forbidden"
    else:
        reason_code = "tool_error"
    return _failed(_text(action), _text(tool_name), reason_code)


def action_envelope(action: ActionState, *, include_status: bool = True) -> dict[str, Any]:
    payload = action.model_dump(mode="json")
    result = {
        "action": payload["action"],
        "action_status": payload["status"],
        "receipt_id": payload["receipt_id"],
        "tool_name": payload["tool_name"],
        "occurred_at": payload["occurred_at"],
        "reason_code": payload["reason_code"],
        "action_state": payload,
    }
    if include_status:
        result["status"] = payload["status"]
    return result
