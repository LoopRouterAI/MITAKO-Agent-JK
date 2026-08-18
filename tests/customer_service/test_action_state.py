# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import sys

import pytest

import business_api
import handoff_service
from customer_service.action_state import action_from_exception, action_from_tool
from customer_service.contracts import ActionState, ActionStatus


def test_handoff_queue_response_becomes_queued_action() -> None:
    action = action_from_tool(
        "human_handoff",
        "handoff_service",
        {
            "ok": True,
            "status": "queued",
            "queue_id": "Q-1",
            "created_at": "2026-08-18T20:00:00+08:00",
        },
    )

    assert action == ActionState(
        action="human_handoff",
        status="queued",
        receipt_id="Q-1",
        tool_name="handoff_service",
        occurred_at="2026-08-18T20:00:00+08:00",
        reason_code="queue_joined",
    )


def test_timeout_never_becomes_success() -> None:
    action = action_from_exception("address_change", "business_api", TimeoutError())

    assert action.status == ActionStatus.FAILED
    assert action.reason_code == "tool_timeout"
    assert action.occurred_at


def test_rejected_tool_response_is_failed_even_if_it_claims_requested() -> None:
    action = action_from_tool(
        "address_change",
        "business_api",
        {"ok": False, "status": "requested", "error": "upstream_rejected"},
    )

    assert action.status == ActionStatus.FAILED
    assert action.reason_code == "upstream_rejected"


@pytest.mark.parametrize(
    "response",
    [
        None,
        "   ",
        {},
        {
            "ok": True,
            "status": "queued",
            "queue_id": "   ",
            "created_at": "2026-08-18T20:00:00+08:00",
        },
        {"ok": True, "status": "queued", "queue_id": "Q-1"},
        {
            "ok": True,
            "status": "succeeded",
            "created_at": "2026-08-18T20:00:00+08:00",
        },
        {
            "ok": False,
            "status": "queued",
            "queue_id": "Q-1",
            "created_at": "2026-08-18T20:00:00+08:00",
        },
        {
            "ok": True,
            "status": "mystery_complete",
            "queue_id": "Q-1",
            "created_at": "2026-08-18T20:00:00+08:00",
        },
    ],
)
def test_invalid_tool_responses_never_become_completed(response: object) -> None:
    action = action_from_tool("human_handoff", "handoff_service", response)

    assert action.status == ActionStatus.FAILED
    assert action.status not in {ActionStatus.QUEUED, ActionStatus.SUCCEEDED}


def test_duplicate_receipt_normalization_is_stable() -> None:
    response = {
        "ok": True,
        "status": "queued",
        "receipt_id": "Q-1",
        "occurred_at": "2026-08-18T20:00:00+08:00",
        "reason_code": "queue_joined",
    }

    first = action_from_tool("human_handoff", "handoff_service", response)
    second = action_from_tool("human_handoff", "handoff_service", dict(response))

    assert first == second
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


@pytest.mark.parametrize("claimed_status", ["queued", "succeeded"])
def test_unconnected_partner_mock_cannot_claim_completion(claimed_status: str) -> None:
    action = action_from_tool(
        "address_change",
        "business_api",
        {
            "ok": True,
            "status": claimed_status,
            "receipt_id": "MOCK-1",
            "occurred_at": "2026-08-18T20:00:00+08:00",
            "real_partner_integration": False,
            "integration_status": "not_connected",
            "write_effect": "none",
        },
    )

    assert action.status == ActionStatus.REQUESTED
    assert action.reason_code == "partner_integration_not_connected"


def test_enqueue_handoff_returns_legacy_queue_fields_and_standard_action(monkeypatch: pytest.MonkeyPatch) -> None:
    fixed_time = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc).timestamp()
    monkeypatch.setattr(handoff_service.time, "time", lambda: fixed_time)
    monkeypatch.setattr(handoff_service, "_get_entry", lambda _session_id: None)
    monkeypatch.setattr(handoff_service.store, "list_active_sessions", lambda tenant_id=None: [])
    monkeypatch.setattr(
        handoff_service,
        "_pick_suggested_agent",
        lambda _session_id, _tier, tenant_id=None: {
            "agent_id": "CS-1001",
            "name": "测试客服",
            "tier": "standard",
        },
    )
    monkeypatch.setattr(handoff_service, "_save", lambda entry: entry)
    monkeypatch.setattr(handoff_service, "_emit_status", lambda _session_id, _entry: None)
    monkeypatch.setitem(
        sys.modules,
        "im_sync_service",
        SimpleNamespace(sync_handoff_created=lambda _session_id, _entry: None),
    )

    result = handoff_service.enqueue_handoff(
        "SESSION-QUEUE-1",
        {"user_id": "USER-1", "required_tier": "standard"},
    )

    assert result["position"] == 1
    assert result["ahead"] == 0
    assert result["eta"] == 1
    assert result["session_id"] == "SESSION-QUEUE-1"
    assert result["ok"] is True
    assert result["status"] == "queuing"
    assert result["action_status"] == "queued"
    assert result["receipt_id"] == "SESSION-QUEUE-1"
    assert result["tool_name"] == "handoff_service"
    assert ActionState.model_validate(result["action_state"]).status == ActionStatus.QUEUED


def test_unconnected_business_writes_return_requested_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        business_api,
        "load_data",
        lambda: {"orders": {"ORDER-1": {"order_id": "ORDER-1", "status": "pending_shipment"}}},
    )
    responses = [
        business_api.post_compensate(
            business_api.CompensateReq(
                user_id="USER-1",
                order_id="ORDER-1",
                type="virtual_pack",
                amount=10,
                reason="延期",
                agent_session_id="SESSION-1",
            )
        ),
        business_api.post_order_urgent(
            "ORDER-1",
            business_api.UrgentReq(
                user_id="USER-1",
                urgency_level="normal",
                reason="延期",
                agent_session_id="SESSION-1",
            ),
        ),
        business_api.create_ticket(
            business_api.TicketCreateReq(
                user_id="USER-1",
                order_id="ORDER-1",
                category="shipping",
                content="查询进度",
            )
        ),
        business_api.create_after_sales_card(
            business_api.AfterSalesCardReq(
                user_id="USER-1",
                order_id="ORDER-1",
                card_type="damage",
            )
        ),
        business_api.create_warehouse_task(
            business_api.WarehouseTaskReq(order_id="ORDER-1", task_type="inventory_check")
        ),
    ]

    allowed = {
        ActionStatus.REQUESTED,
        ActionStatus.ACCEPTED,
        ActionStatus.FAILED,
        ActionStatus.PENDING_HUMAN,
    }
    for response in responses:
        action = ActionState.model_validate(response["action_state"])
        assert "ok" in response
        assert action.status in allowed
        assert action.status not in {ActionStatus.QUEUED, ActionStatus.SUCCEEDED}
        assert response["action"] == action.action
        assert response["action_status"] == action.status.value
        assert response["receipt_id"] == action.receipt_id
        assert response["tool_name"] == "business_api"
        assert response["real_partner_integration"] is False

    assert responses[0]["success"] is False
    assert responses[2]["ok"] is True
