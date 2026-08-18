# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio

import pytest

from customer_service.contracts import IntentResult


def _intent(intent_code: str, scenario_code: str) -> dict:
    return IntentResult(
        intent_code=intent_code,
        scenario_code=scenario_code,
        confidence=0.99,
    ).model_dump(mode="json")


def _state(message: str, intent_code: str, scenario_code: str, *, emotion_level: int = 2) -> dict:
    return {
        "messages": [{"role": "user", "content": message}],
        "raw_user_content": message,
        "intent": intent_code,
        "emotion_level": emotion_level,
        "conversation_state": {"intent": _intent(intent_code, scenario_code)},
        "user_id": "acceptance-user",
        "session_id": "acceptance-session",
        "tenant_id": "mitako",
        "transfer_reason": "",
        "handoff_offer_id": "",
        "business_events": [{"event_type": "service_transfer_blocked"}],
        "sop_state": {},
    }


def test_transfer_rules_only_route_explicit_human_high_risk_or_l5() -> None:
    import agent

    explicit = asyncio.run(agent.check_transfer_rules(
        _state("延期180天了，我要求退款并转人工。", "human_handoff", "refund_progress"),
        {"configurable": {}},
    ))
    assert explicit["should_transfer"] is True

    complaint = asyncio.run(agent.check_transfer_rules(
        _state("不要只道歉，直接说谁处理、多久处理完，否则我投诉。", "high_risk_complaint", "complaint"),
        {"configurable": {}},
    ))
    assert complaint["should_transfer"] is True

    l4 = asyncio.run(agent.check_transfer_rules(
        _state("这次排期为什么延误？", "order_logistics", "order_logistics", emotion_level=4),
        {"configurable": {}},
    ))
    assert l4["should_transfer"] is False
    assert l4["handoff_recommended"] is True

    for message, intent_code in (
        ("订单买的是手办，收到的是另一个角色，发错货需要提交哪些材料？", "wrong_item"),
        ("一单应有12个吧唧，实收11个，少了一个，怎么证明漏发？", "missing_item"),
    ):
        ordinary = asyncio.run(agent.check_transfer_rules(
            _state(message, intent_code, intent_code),
            {"configurable": {}},
        ))
        assert ordinary["should_transfer"] is False


def test_transfer_success_requires_canonical_queue_receipt(monkeypatch: pytest.MonkeyPatch) -> None:
    import agent
    import auth.jwt_utils
    import handoff_service

    queue_meta = {
        "ok": True,
        "status": "queuing",
        "session_id": "acceptance-session",
        "queue_id": "QUEUE-ACCEPT-1",
        "action_state": {
            "action": "human_handoff",
            "status": "queued",
            "receipt_id": "QUEUE-ACCEPT-1",
            "tool_name": "handoff_service",
            "reason_code": "queue_joined",
            "occurred_at": "2026-08-18T20:00:00+08:00",
        },
    }
    monkeypatch.setattr(handoff_service, "build_handoff_brief", lambda *_args, **_kwargs: {"tenant_id": "mitako"})
    monkeypatch.setattr(handoff_service, "enqueue_handoff", lambda *_args, **_kwargs: queue_meta)
    monkeypatch.setattr(auth.jwt_utils, "create_handoff_user_token", lambda **_kwargs: "handoff-token")

    async def run() -> tuple[dict, list[dict]]:
        queue = asyncio.Queue()
        result = await agent.transfer_to_chatwoot(
            _state("延期180天了，我要求退款并转人工。", "human_handoff", "refund_progress"),
            {"configurable": {"event_queue": queue}},
        )
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())
        return result, events

    result, events = asyncio.run(run())
    action = result["conversation_state"]["action_state"]
    assert result["should_transfer"] is True
    assert action["status"] == "queued"
    assert action["receipt_id"] == "QUEUE-ACCEPT-1"
    transfer = next(event for event in events if event["type"] == "action_transfer")
    assert transfer["queue"]["action_state"]["receipt_id"] == "QUEUE-ACCEPT-1"


def test_transfer_failure_never_claims_queued(monkeypatch: pytest.MonkeyPatch) -> None:
    import agent
    import auth.jwt_utils
    import handoff_service

    monkeypatch.setattr(handoff_service, "build_handoff_brief", lambda *_args, **_kwargs: {"tenant_id": "mitako"})
    def fail_enqueue(*_args, **_kwargs):
        raise RuntimeError("queue unavailable")
    monkeypatch.setattr(handoff_service, "enqueue_handoff", fail_enqueue)
    monkeypatch.setattr(auth.jwt_utils, "create_handoff_user_token", lambda **_kwargs: "handoff-token")

    result = asyncio.run(agent.transfer_to_chatwoot(
        _state("延期180天了，我要求退款并转人工。", "human_handoff", "refund_progress"),
        {"configurable": {}},
    ))

    action = result["conversation_state"]["action_state"]
    assert action["status"] == "failed"
    assert action["status"] != "queued"
    assert result["should_transfer"] is True
