# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from customer_service.contracts import IntentResult


def _parse_sse(text: str) -> list[dict]:
    events = []
    for block in re.split(r"\r?\n\r?\n", text.strip()):
        event_type = "message"
        data = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event_type = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data.append(line.split(":", 1)[1].strip())
        if data:
            events.append({"event": event_type, "data": json.loads("\n".join(data))})
    return events


def _reset_handoff_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import handoff_store

    monkeypatch.setattr(handoff_store, "_DB_DIR", str(tmp_path))
    monkeypatch.setattr(handoff_store, "_DB_PATH", str(tmp_path / "handoff.db"))
    monkeypatch.setattr(handoff_store, "_db_ready", False)
    monkeypatch.setenv("MITAKO_JWT_SECRET", "customer-agent-acceptance-secret-20260818")
    monkeypatch.setenv("MITAKO_AUTH_REQUIRED", "1")
    monkeypatch.setenv("MITAKO_PROTECTED_API_AUTH_REQUIRED", "1")


def _chat_token(user_id: str, session_id: str) -> str:
    from auth.jwt_utils import create_token
    from auth.roles import Role

    return create_token(
        sub=user_id,
        role=Role.CUSTOMER_USER.value,
        tenant_id="mitako",
        extra={"session_id": session_id},
    )


def _run_chat(
    client: TestClient,
    user_id: str,
    session_id: str,
    content: str,
    attachments: list[dict] | None = None,
) -> list[dict]:
    response = client.post(
        "/api/v1/chat",
        headers={"Authorization": f"Bearer {_chat_token(user_id, session_id)}"},
        json={
            "user_id": user_id,
            "session_id": session_id,
            "content": content,
            "history": [],
            "stream_reply": False,
            "attachments": attachments or [],
        },
    )
    assert response.status_code == 200, response.text
    return _parse_sse(response.text)


def _write_verified_attachments(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    user_id: str,
    session_id: str,
    categories: tuple[str, ...],
) -> list[dict]:
    import main

    attachment_dir = tmp_path / "attachments"
    attachment_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(main, "CHAT_ATTACHMENTS_DIR", attachment_dir)
    items = []
    for index, category in enumerate(categories, start=1):
        attachment_id = f"verified-{index}"
        filename = f"{attachment_id}.png"
        raw = f"image-{index}".encode()
        (attachment_dir / filename).write_bytes(raw)
        (attachment_dir / f"{filename}.json").write_text(
            json.dumps({
                "id": attachment_id,
                "user_id": user_id,
                "session_id": session_id,
                "tenant_id": "mitako",
                "name": f"材料-{index}.png",
                "mime_type": "image/png",
                "size": len(raw),
                "filename": filename,
                "evidence_scenario": "wrong_item",
                "evidence_category": category,
                "evidence_verified": True,
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        items.append({
            "id": attachment_id,
            "name": f"用户自定义-{index}.png",
            "mime_type": "image/png",
            "size": len(raw),
            "url": f"/api/v1/chat/attachments/{filename}",
        })
    return items


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


def test_high_risk_graph_waits_for_scenario_and_reply_plan_before_transfer() -> None:
    import agent

    base = _state(
        "不要只道歉，直接说谁处理、多久处理完，否则我投诉。",
        "high_risk_complaint",
        "complaint",
    )
    base["should_transfer"] = True
    assert agent.router_after_transfer_check(base) == "continue"

    planned = {
        **base,
        "conversation_state": {
            **base["conversation_state"],
            "scenario_decision": {"core_conclusion": "complaint_protocol_required"},
        },
    }
    assert agent.router_after_transfer_check(planned) == "continue"

    ready = {**planned, "reply_draft": "责任角色：客服主管；当前动作：提交人工队列；首次响应时效：30分钟；跟进凭证：待回执。"}
    assert agent.router_after_transfer_check(ready) == "transfer"


def test_model_reply_analysis_cannot_raise_deterministic_emotion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agent

    async def fake_call_llm(*_args, **_kwargs) -> str:
        return '<analysis>{"emotion_level": 5, "should_transfer": true}</analysis>请先上传材料。'

    monkeypatch.setattr(agent, "call_llm", fake_call_llm)
    state = _state(
        "我只有特写照片和面单，但还没有上传文件。",
        "product_damage",
        "product_damage",
        emotion_level=2,
    )
    state["should_transfer"] = False
    state["conversation_state"].update({
        "scenario_decision": {
            "core_conclusion": "material_not_received",
            "action_state": {
                "action": "material_upload",
                "status": "not_requested",
                "receipt_id": "",
                "tool_name": "",
                "reason_code": "",
                "occurred_at": "",
            },
            "next_step": {
                "code": "upload_materials",
                "label": "上传本轮待审核材料",
                "user_action_required": True,
            },
        },
        "action_state": {
            "action": "material_upload",
            "status": "not_requested",
            "receipt_id": "",
            "tool_name": "",
            "reason_code": "",
            "occurred_at": "",
        },
        "next_step": {
            "code": "upload_materials",
            "label": "上传本轮待审核材料",
            "user_action_required": True,
        },
        "core_conclusion": "material_not_received",
    })

    result = asyncio.run(agent.generate_reply_with_persona(state, {"configurable": {}}))

    assert result.get("emotion_level", 2) == 2


def test_material_collection_turn_does_not_emit_unverified_order_card() -> None:
    import main

    card = main._select_primary_customer_card({
        "messages": [{"role": "user", "content": "我还没有上传材料。"}],
        "sop_state": {"ticket_type": "damage", "material_collection_turn": True},
        "business_cards": [{
            "type": "business_action",
            "data": {
                "sop": {"ticket_type": "damage"},
                "action": {
                    "type": "after_sales_card",
                    "reason": "已生成售后处理单",
                    "requires_human": True,
                },
            },
        }],
    })

    assert card is None


def test_business_readiness_marks_material_collection_in_persisted_sop_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agent
    import business_readiness_service

    monkeypatch.setattr(
        business_readiness_service,
        "run_business_flow",
        lambda _state, _fixtures: {
            "sop_state": {"ticket_type": "damage"},
            "business_events": [],
            "business_cards": [{"type": "business_action", "data": {}}],
        },
    )
    result = asyncio.run(agent.plan_business_readiness_flow({
        "raw_user_content": "我有照片和面单，但还没有上传材料。",
        "intent": "换货补发/商品破损",
        "attachments": [],
    }, {"configurable": {}}))

    assert result["sop_state"]["material_collection_turn"] is True


def test_address_change_without_partner_write_returns_failed_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agent

    class FailingClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *_args, **_kwargs):
            raise OSError("partner unavailable")

    monkeypatch.setattr(agent.httpx, "AsyncClient", FailingClient)
    result = asyncio.run(agent.query_order_system({
        "user_id": "usr_004",
        "intent": "订单修改/收货地址",
        "messages": [{"role": "user", "content": "订单026403还没出库，我填错了收货地址，能修改吗？"}],
        "raw_user_content": "订单026403还没出库，我填错了收货地址，能修改吗？",
        "active_order_id": "",
        "conversation_state": {"intent": _intent("address_change", "order_change")},
    }, {"configurable": {}}))

    action = result["conversation_state"]["action_state"]
    assert action["action"] == "address_change"
    assert action["status"] == "failed"
    assert action["reason_code"] == "partner_integration_not_connected"


def test_verified_logistics_query_returns_succeeded_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agent

    class Response:
        status_code = 200

        def json(self):
            return {"carrier": "受控承运商", "status": "in_transit", "timeline": [{"status": "运输中"}]}

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(agent.httpx, "AsyncClient", Client)
    result = asyncio.run(agent.query_logistics({
        "order_data": {"orders": [{"order_id": "ORD-LOG-1"}]},
        "conversation_state": {"intent": _intent("order_logistics", "order_logistics")},
    }, {"configurable": {}}))

    action = result["conversation_state"]["action_state"]
    assert action["action"] == "order_lookup"
    assert action["status"] == "succeeded"
    assert action["receipt_id"] == "LOGISTICS-ORD-LOG-1"


def test_transfer_success_requires_canonical_queue_receipt(monkeypatch: pytest.MonkeyPatch) -> None:
    import agent
    import auth.jwt_utils
    import handoff_service

    queue_meta = {
        "ok": True,
        "status": "queuing",
        "session_id": "acceptance-session",
        "queue_id": "acceptance-session",
        "action_state": {
            "action": "human_handoff",
            "status": "queued",
            "receipt_id": "acceptance-session",
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
    assert action["receipt_id"] == "acceptance-session"
    transfer = next(event for event in events if event["type"] == "action_transfer")
    assert transfer["queue"]["action_state"]["receipt_id"] == "acceptance-session"


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


def test_transfer_rejects_queue_receipt_from_other_session(monkeypatch: pytest.MonkeyPatch) -> None:
    import agent
    import auth.jwt_utils
    import handoff_service
    from handoff_service import build_public_queue_meta

    monkeypatch.setattr(handoff_service, "build_handoff_brief", lambda *_args, **_kwargs: {"tenant_id": "mitako"})
    monkeypatch.setattr(
        handoff_service,
        "enqueue_handoff",
        lambda *_args, **_kwargs: {
            "ok": True,
            "status": "queuing",
            "session_id": "other-session",
            "queue_id": "other-session",
            "action_state": {
                "action": "human_handoff",
                "tool_name": "handoff_service",
                "status": "queued",
                "receipt_id": "other-session",
                "occurred_at": "2026-08-18T20:00:00+08:00",
                "session_id": "other-session",
            },
        },
    )
    monkeypatch.setattr(auth.jwt_utils, "create_handoff_user_token", lambda **_kwargs: "must-not-issue")

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
    assert action["status"] == "failed"
    assert action["reason_code"] == "session_mismatch"
    assert result["handoff_token"] == ""
    transfer = next(event for event in events if event["type"] == "action_transfer")
    assert transfer["queue"]["status"] == "failed"
    assert transfer["queue"]["session_id"] == "acceptance-session"
    assert "other-session" not in json.dumps(transfer, ensure_ascii=False)
    assert not any(key in transfer["queue"] for key in ("position", "ahead", "eta", "suggested_agent"))
    public_queue = build_public_queue_meta(transfer["queue"])
    assert public_queue["status"] == "failed"
    assert not any(key in public_queue for key in ("position", "ahead", "eta", "suggested_agent"))


def test_real_complaint_chat_persists_queue_receipt_and_four_reply_fields(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import handoff_store
    import main

    _reset_handoff_store(monkeypatch, tmp_path)
    session_id = "complaint-queued-session"
    events = _run_chat(
        TestClient(main.app),
        "complaint-user",
        session_id,
        "不要只道歉，直接说谁处理、多久处理完，否则我投诉。",
    )

    transfer = next(event["data"] for event in events if event["event"] == "transfer")
    done = next(event["data"] for event in events if event["event"] == "done")
    stored = handoff_store.get_session(session_id)
    assert stored and stored["status"] == "queuing"
    assert transfer["reason"] == "已进入人工队列。"
    assert transfer["action_state"]["receipt_id"] == session_id
    assert done["status"] == "completed"
    assert done["action_state"]["status"] == "queued"
    assert done["reply_fields"]["tracking_receipt"] == session_id
    assert done["required_reply_fields"] == [
        "responsible_role",
        "current_action",
        "first_response_sla",
        "tracking_receipt",
    ]
    for label in ("责任角色", "当前动作", "首次响应时效", "跟进凭证"):
        assert label in done["reply"]


def test_compound_human_and_complaint_still_uses_four_field_protocol(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import handoff_store
    import main

    _reset_handoff_store(monkeypatch, tmp_path)
    session_id = "compound-complaint-session"
    events = _run_chat(
        TestClient(main.app),
        "compound-complaint-user",
        session_id,
        "我要转人工，同时投诉你们，直接说谁处理、多久处理完。",
    )

    transfer = next(event["data"] for event in events if event["event"] == "transfer")
    done = next(event["data"] for event in events if event["event"] == "done")
    assert handoff_store.get_session(session_id)["status"] == "queuing"
    assert transfer["required_reply_fields"] == [
        "responsible_role",
        "current_action",
        "first_response_sla",
        "tracking_receipt",
    ]
    assert done["status"] == "completed"
    assert done["reply_fields"]["tracking_receipt"] == session_id
    for label in ("责任角色", "当前动作", "首次响应时效", "跟进凭证"):
        assert label in done["reply"]


@pytest.mark.parametrize(
    ("session_id", "message"),
    [
        (
            "privacy-complaint-session",
            "我要删除手机号和聊天记录，并投诉你们，直接说谁处理、多久响应。",
        ),
        (
            "address-complaint-session",
            "我要修改收货地址，并投诉你们，直接说谁处理、多久响应。",
        ),
    ],
)
def test_compound_business_and_complaint_executes_the_planned_handoff(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    session_id: str,
    message: str,
) -> None:
    import handoff_store
    import main

    _reset_handoff_store(monkeypatch, tmp_path)
    events = _run_chat(
        TestClient(main.app),
        f"{session_id}-user",
        session_id,
        message,
    )

    transfer = next(event["data"] for event in events if event["event"] == "transfer")
    done = next(event["data"] for event in events if event["event"] == "done")
    assert handoff_store.get_session(session_id)["status"] == "queuing"
    assert transfer["action_state"]["receipt_id"] == session_id
    assert done["status"] == "completed"
    assert done["reply_fields"]["tracking_receipt"] == session_id
    assert "等待人工队列回执" not in done["reply"]


def test_failed_complaint_queue_sse_and_done_only_show_retry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import handoff_service
    import main

    _reset_handoff_store(monkeypatch, tmp_path)
    monkeypatch.setattr(
        handoff_service,
        "enqueue_handoff",
        lambda *_args, **_kwargs: {
            "ok": True,
            "status": "failed",
            "session_id": "complaint-failed-session",
            "queue_id": "REAL-FAILED",
            "action_state": {
                "action": "address_change",
                "tool_name": "business_api",
                "status": "queued",
                "receipt_id": "FAKE-QUEUED",
                "occurred_at": "2026-08-18T20:00:00+08:00",
            },
        },
    )
    events = _run_chat(
        TestClient(main.app),
        "complaint-failed-user",
        "complaint-failed-session",
        "不要只道歉，直接说谁处理、多久处理完，否则我投诉。",
    )

    transfer = next(event["data"] for event in events if event["event"] == "transfer")
    done = next(event["data"] for event in events if event["event"] == "done")
    assert transfer["action_state"]["status"] == "failed"
    assert "尚未进入人工队列" in transfer["reason"]
    assert done["status"] == "failed"
    assert "尚未进入人工队列" in done["reply"]
    assert "已进入人工队列" not in json.dumps(events, ensure_ascii=False)


@pytest.mark.parametrize(
    ("user_id", "session_id", "message"),
    [
        ("wrong-user", "wrong-session", "订单买的是手办，收到的是另一个角色，发错货需要提交哪些材料？"),
        ("missing-user", "missing-session", "一单应有12个吧唧，实收11个，少了一个，怎么证明漏发？"),
    ],
)
def test_wrong_and_missing_full_chat_never_auto_enqueue(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    user_id: str,
    session_id: str,
    message: str,
) -> None:
    import agent
    import handoff_store
    import main

    _reset_handoff_store(monkeypatch, tmp_path)

    async def fake_call_llm(*_args, **_kwargs):
        return "我会按当前场景的材料要求继续核对。"

    monkeypatch.setattr(agent, "call_llm", fake_call_llm)
    events = _run_chat(TestClient(main.app), user_id, session_id, message)

    assert not any(event["event"] == "transfer" for event in events)
    assert next(event["data"] for event in events if event["event"] == "done")["status"] == "completed"
    stored = handoff_store.get_session(session_id)
    assert stored and stored["status"] == "chatting"


@pytest.mark.parametrize(
    ("categories", "expected_route", "expected_missing"),
    [
        (
            ("received_group_photo", "green_bag_or_package_view", "matching_waybill"),
            "static_three_images",
            [],
        ),
        (
            ("received_group_photo", "matching_waybill"),
            "pending_evidence",
            ["green_bag_or_package_view"],
        ),
    ],
)
def test_verified_attachment_metadata_drives_static_route_in_full_chat(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    categories: tuple[str, ...],
    expected_route: str,
    expected_missing: list[str],
) -> None:
    import agent
    import main

    _reset_handoff_store(monkeypatch, tmp_path)
    user_id = f"static-user-{len(categories)}"
    session_id = f"static-session-{len(categories)}"
    attachments = _write_verified_attachments(
        monkeypatch,
        tmp_path,
        user_id=user_id,
        session_id=session_id,
        categories=categories,
    )
    captured: dict[str, dict] = {}
    real_agent = main.agent_app

    class CapturingAgent:
        async def ainvoke(self, state: dict, config: dict) -> dict:
            result = await real_agent.ainvoke(state, config=config)
            captured["result"] = result
            return result

    async def fake_call_llm(*_args, **_kwargs):
        return "我会按发错货材料要求继续核对。"

    monkeypatch.setattr(main, "agent_app", CapturingAgent())
    monkeypatch.setattr(agent, "call_llm", fake_call_llm)
    events = _run_chat(
        TestClient(main.app),
        user_id,
        session_id,
        "订单买的是手办，收到的是另一个角色，请核对材料。",
        attachments,
    )

    assert not any(event["event"] == "transfer" for event in events)
    details = captured["result"]["conversation_state"]["details"]
    assert details["selected_evidence_route"] == expected_route
    assert details["missing_static_fields"] == expected_missing
    public_text = json.dumps(events, ensure_ascii=False)
    assert "evidence_verified" not in public_text
    assert "evidence_category" not in public_text


_PERSONA_USERS = {
    "gold_member": "usr_001",
    "silver_member": "usr_002",
    "platinum_member": "usr_003",
    "regular_member": "usr_004",
    "new_user": "usr_005",
    "guardian": "usr_006",
}
_CASE_USER_OVERRIDES = {
    # 该控制场景必须具备受信订单上下文；usr_005 的演示账号明确没有订单。
    "CHAT-15-SHIPMENT-PROGRESS": "usr_004",
}


async def _reply_plan_only(_system: str, user: str, *_args, **_kwargs) -> str:
    try:
        plan = json.loads(user).get("reply_plan") or {}
        lines = [str(item) for item in plan.get("must_say") or [] if str(item).strip()]
        return "".join(lines) or "请按当前处理状态继续。"
    except Exception:
        return "请按当前处理状态继续。"


def _acceptance_signature(done: dict) -> tuple[str, str, str, str, str]:
    state = done.get("conversation_state") or {}
    intent = state.get("intent") or {}
    action = state.get("action_state") or {}
    next_step = state.get("next_step") or {}
    return (
        str(intent.get("intent_code") or ""),
        str(intent.get("scenario_code") or ""),
        str(state.get("core_conclusion") or ""),
        str(action.get("status") or ""),
        str(next_step.get("code") or ""),
    )


def run_acceptance(rounds: int, output: Path) -> int:
    import agent
    import main

    cases = json.loads(
        (ROOT / "tests" / "fixtures" / "customer_agent_20260818_cases.json").read_text(encoding="utf-8")
    )["cases"]
    rows = []
    failures = []
    with tempfile.TemporaryDirectory(prefix="mitako-customer-chat-acceptance-") as temp_dir:
        monkeypatch = pytest.MonkeyPatch()
        try:
            _reset_handoff_store(monkeypatch, Path(temp_dir))
            monkeypatch.setenv("MITAKO_PRIVACY_DELETION_ENTRY", "联系隐私专席提交身份核验申请")
            monkeypatch.setenv("MITAKO_PRIVACY_DELETION_SLA", "身份核验通过后 15 个工作日内处理")
            monkeypatch.setattr(agent, "call_llm", _reply_plan_only)
            client = TestClient(main.app)
            for round_no in range(1, rounds + 1):
                for case in cases:
                    user_id = _CASE_USER_OVERRIDES.get(case["case_id"], _PERSONA_USERS[case["persona"]])
                    session_id = f"accept-{round_no}-{case['case_id'].lower()}"
                    events = _run_chat(client, user_id, session_id, case["message"])
                    done = next((item["data"] for item in events if item["event"] == "done"), None)
                    expected = (
                        case["expected_intent"],
                        case["expected_scenario"],
                        case["expected_core_conclusion"],
                        case["expected_action_status"],
                        case["expected_next_step"],
                    )
                    actual = _acceptance_signature(done or {})
                    forbidden = [
                        claim for claim in case.get("forbidden_claims", [])
                        if claim in str((done or {}).get("reply") or "")
                    ]
                    passed = done is not None and actual == expected and not forbidden
                    row = {
                        "round": round_no,
                        "case_id": case["case_id"],
                        "priority": case["priority"],
                        "passed": passed,
                        "expected": expected,
                        "actual": actual,
                        "forbidden_claims_found": forbidden,
                        "done_status": (done or {}).get("status"),
                    }
                    rows.append(row)
                    if not passed:
                        failures.append(row)
        finally:
            monkeypatch.undo()

    output.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "version": "MITAKO-CUSTOMER-CHAT-20260818.1",
        "tested_at": "2026-08-19",
        "rounds": rounds,
        "case_count": len(cases),
        "run_count": len(rows),
        "passed": len(rows) - len(failures),
        "failed": len(failures),
        "model_mode": "deterministic_reply_plan_renderer",
        "rows": rows,
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("rounds", "case_count", "run_count", "passed", "failed")}, ensure_ascii=False))
    if failures:
        print(json.dumps(failures, ensure_ascii=False, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="运行 2026-08-18 客服沟通 15 场景稳定性验收")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "tests" / "reports" / "customer_chat_20260819_acceptance.json",
    )
    args = parser.parse_args()
    raise SystemExit(run_acceptance(max(1, args.rounds), args.output))
