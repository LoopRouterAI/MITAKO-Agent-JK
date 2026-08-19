# -*- coding: utf-8 -*-
import asyncio
import json
from typing import Any

from fastapi.testclient import TestClient

import main


def _conversation_state() -> dict[str, Any]:
    return {
        "intent": {
            "intent_code": "product_damage",
            "scenario_code": "product_damage",
            "intent_codes": ["product_damage"],
            "scenario_codes": ["product_damage"],
            "confidence": 0.99,
            "matched_evidence": ["划痕"],
            "requires_clarification": False,
            "clarification_fields": [],
        },
        "facts": [
            {
                "field": "material.received",
                "value": False,
                "source": "attachment_service",
                "source_ref": "ATT-SECRET-1",
                "verified": True,
                "observed_at": "2026-08-19T09:00:00+08:00",
            },
            {
                "field": "identity.number",
                "value": "310101199001011234",
                "source": "user_statement",
                "source_ref": "",
                "verified": False,
                "observed_at": "",
            },
        ],
        "material_state": {
            "status": "not_received",
            "missing": ["待审核附件"],
            "internal_prompt": "不得公开",
        },
        "action_state": {
            "action": "material_upload",
            "status": "not_requested",
            "receipt_id": "",
            "tool_name": "internal_attachment_service",
            "reason_code": "",
            "occurred_at": "",
        },
        "next_step": {
            "code": "upload_materials",
            "label": "上传本轮待审核材料",
            "user_action_required": True,
        },
        "core_conclusion": "material_not_received",
        "scenario_decision": {"policy_refs": ["INTERNAL-POLICY"]},
        "reply_plan": {"must_not_say": ["内部规则"]},
        "internal_prompt": "不得公开",
    }


def _events(response_text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for block in response_text.strip().split("\n\n"):
        event = "message"
        data = ""
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data += line.split(":", 1)[1].strip()
        if data:
            events.append({"event": event, "data": json.loads(data)})
    return events


def test_public_projection_removes_internal_and_sensitive_fields() -> None:
    from customer_service.public_projection import project_conversation_state

    public = project_conversation_state(_conversation_state())
    encoded = json.dumps(public, ensure_ascii=False)

    assert public["intent"]["intent_code"] == "product_damage"
    assert public["action_state"] == {
        "action": "material_upload",
        "status": "not_requested",
        "receipt_id": "",
        "reason_code": "",
        "occurred_at": "",
    }
    assert public["facts"] == [
        {
            "field": "material.received",
            "value": False,
            "source": "attachment_service",
            "verified": True,
        }
    ]
    assert "internal_prompt" not in encoded
    assert "tool_name" not in encoded
    assert "ATT-SECRET-1" not in encoded
    assert "310101199001011234" not in encoded


def test_public_projection_rejects_unbounded_internal_codes() -> None:
    from customer_service.public_projection import project_conversation_state

    state = _conversation_state()
    state["action_state"]["reason_code"] = "API_KEY=sk-secret C:\\private\\service.py"
    state["core_conclusion"] = "provider token sk-secret at C:\\private\\service.py"

    public = project_conversation_state(state)
    encoded = json.dumps(public, ensure_ascii=False)

    assert public["action_state"]["reason_code"] == "tool_error"
    assert public["core_conclusion"] == ""
    assert "sk-secret" not in encoded
    assert "service.py" not in encoded


def test_done_event_contains_same_public_conversation_state(monkeypatch) -> None:
    state = _conversation_state()

    async def fake_ainvoke(input_state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        del config
        return {
            **input_state,
            "conversation_state": state,
            "reply_draft": "当前没有收到可核验附件，请先上传材料。",
        }

    monkeypatch.setattr(main.agent_app, "ainvoke", fake_ainvoke)
    token = main.create_token(
        sub="projection-user",
        role=main.Role.CUSTOMER_USER.value,
        tenant_id="mitako",
        extra={"session_id": "projection-session"},
    )
    response = TestClient(main.app).post(
        "/api/v1/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "user_id": "projection-user",
            "session_id": "projection-session",
            "content": "我还没有上传材料",
            "history": [],
            "stream_reply": False,
        },
    )

    assert response.status_code == 200
    done = next(item["data"] for item in _events(response.text) if item["event"] == "done")
    assert done["conversation_state"]["core_conclusion"] == "material_not_received"
    assert done["conversation_state"]["next_step"]["code"] == "upload_materials"
    assert "internal_prompt" not in json.dumps(done, ensure_ascii=False)


def test_handoff_desk_brief_keeps_the_same_public_state() -> None:
    from handoff_service import build_desk_brief, build_handoff_brief

    source = _conversation_state()
    brief = build_handoff_brief({
        "messages": [{"role": "user", "content": "请转人工继续处理"}],
        "intent": "商品有伤",
        "emotion_level": 4,
        "conversation_state": source,
        "user_id": "desk-state-user",
        "session_id": "desk-state-session",
        "tenant_id": "mitako",
    })
    desk = build_desk_brief(brief)

    assert desk["conversation_state"] == {
        **desk["conversation_state"],
        "core_conclusion": "material_not_received",
    }
    assert desk["conversation_state"]["action_state"]["status"] == "not_requested"
    assert "tool_name" not in json.dumps(desk["conversation_state"], ensure_ascii=False)


def test_desk_session_uses_current_queue_receipt_instead_of_stale_brief(
    tmp_path,
    monkeypatch,
) -> None:
    import handoff_service
    import handoff_store

    monkeypatch.setattr(handoff_store, "_DB_DIR", str(tmp_path))
    monkeypatch.setattr(handoff_store, "_DB_PATH", str(tmp_path / "handoff.db"))
    monkeypatch.setattr(handoff_store, "_db_ready", False)
    state = _conversation_state()
    state["action_state"]["action"] = "human_handoff"
    state["action_state"]["status"] = "requested"
    brief = handoff_service.build_handoff_brief({
        "messages": [{"role": "user", "content": "请转人工"}],
        "intent": "VIP客服请求",
        "emotion_level": 2,
        "conversation_state": state,
        "user_id": "queue-state-user",
        "session_id": "queue-state-session",
        "tenant_id": "mitako",
    })
    handoff_service.enqueue_handoff(
        "queue-state-session",
        brief,
        tenant_id="mitako",
        publish=False,
    )

    desk = handoff_service.get_desk_session("queue-state-session", tenant_id="mitako")
    customer = handoff_service.build_customer_handoff_payload(
        handoff_service.get_queue_status("queue-state-session")
    )

    action = desk["brief"]["conversation_state"]["action_state"]
    assert action["status"] == "queued"
    assert action["receipt_id"] == "queue-state-session"
    assert customer["conversation_state"]["action_state"] == action
