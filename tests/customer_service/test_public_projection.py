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
