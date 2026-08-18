# -*- coding: utf-8 -*-
"""工具返回到客服动作状态的统一归一化。"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _field(*sources: Mapping[str, Any], keys: tuple[str, ...]) -> str:
    for source in sources:
        for key in keys:
            value = source.get(key)
            if isinstance(value, (int, float)) and key in _OCCURRED_KEYS:
                return datetime.fromtimestamp(value, timezone.utc).isoformat()
            text = _text(value)
            if text:
                return text
    return ""


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
    raw_status = _field(state_source, response, keys=("status", "action_status"))
    status = _STATUS_ALIASES.get(raw_status.lower())
    if status is None:
        return _failed(action_name, normalized_tool, "invalid_tool_status")

    occurred_at = _field(state_source, response, keys=_OCCURRED_KEYS)
    mock_response = dict(response)
    if state_source:
        mock_response.update(state_source)
    unconnected_mock = _is_unconnected_mock(mock_response)
    negative_result = response.get("ok") is False or response.get("success") is False
    if negative_result and not (
        unconnected_mock and status in {ActionStatus.REQUESTED, ActionStatus.PENDING_HUMAN}
    ):
        reason = _field(state_source, response, keys=("reason_code", "error", "code")) or "tool_rejected"
        return _failed(action_name, normalized_tool, reason, occurred_at)

    if unconnected_mock and status in _COMPLETED_STATUSES:
        status = ActionStatus.REQUESTED
        reason_code = "partner_integration_not_connected"
    else:
        reason_code = _field(state_source, response, keys=("reason_code", "error", "code")) or _DEFAULT_REASON[status]

    receipt_id = _field(state_source, response, keys=_RECEIPT_KEYS)
    if status in _COMPLETED_STATUSES and (not receipt_id or not occurred_at):
        return _failed(action_name, normalized_tool, "invalid_tool_response", occurred_at)

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
