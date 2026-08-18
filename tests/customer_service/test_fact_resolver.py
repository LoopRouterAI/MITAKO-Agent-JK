# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient


def _find(facts: list[Any], field: str) -> Any:
    return next(fact for fact in facts if fact.field == field)


@pytest.mark.parametrize(
    "message",
    [
        "我有照片和面单。",
        "退款材料已经准备了。",
        "面单和商品照片都拍好了。",
    ],
)
def test_claimed_material_is_not_received_without_attachment(message: str) -> None:
    from customer_service.fact_resolver import resolve_facts

    facts = resolve_facts(message=message, attachments=[])
    claimed = _find(facts, "material.user_claimed")
    received = _find(facts, "material.received")

    assert claimed.value is True
    assert claimed.source == "user_statement"
    assert claimed.verified is False
    assert received.value is False
    assert received.source == "attachment_service"
    assert received.verified is False
    assert received.source_ref == ""


def test_attachment_service_receipt_marks_received() -> None:
    from customer_service.fact_resolver import resolve_facts

    facts = resolve_facts(
        message="这是材料",
        attachments=[{"id": "A1", "status": "stored"}],
    )
    received = _find(facts, "material.received")

    assert received.value is True
    assert received.source == "attachment_service"
    assert received.verified is True
    assert received.source_ref == "attachment:A1"


def test_verified_wrong_item_attachment_metadata_generates_static_evidence_facts() -> None:
    from customer_service.fact_resolver import resolve_facts

    facts = resolve_facts(
        message="请按材料处理。",
        attachments=[
            {
                "id": f"A-{index}",
                "status": "stored",
                "evidence_scenario": "wrong_item",
                "evidence_category": category,
                "evidence_verified": True,
            }
            for index, category in enumerate(
                ("received_group_photo", "green_bag_or_package_view", "matching_waybill"),
                start=1,
            )
        ],
    )

    for category in ("received_group_photo", "green_bag_or_package_view", "matching_waybill"):
        fact = _find(facts, f"wrong_item.{category}")
        assert fact.value is True
        assert fact.source == "attachment_service"
        assert fact.verified is True


@pytest.mark.parametrize("verified", [False, None])
def test_unverified_attachment_metadata_never_generates_static_evidence_fact(verified: object) -> None:
    from customer_service.fact_resolver import resolve_facts

    facts = resolve_facts(
        message="商品全家福和面单都在文件名里。",
        attachments=[{
            "id": "A-UNVERIFIED",
            "name": "商品全家福_绿色袋_匹配面单.png",
            "status": "stored",
            "evidence_scenario": "wrong_item",
            "evidence_category": "received_group_photo",
            "evidence_verified": verified,
        }],
    )

    assert not any(fact.field.startswith("wrong_item.") for fact in facts)


@pytest.mark.parametrize(
    "message",
    [
        "我还需要准备照片和面单。",
        "请问怎么上传退款材料？",
        "我还没拍商品照片。",
    ],
)
def test_future_or_missing_material_is_not_user_claimed(message: str) -> None:
    from customer_service.fact_resolver import resolve_facts

    facts = resolve_facts(message=message, attachments=[])

    assert _find(facts, "material.user_claimed").value is False


def test_parse_failure_does_not_erase_verified_receipt() -> None:
    from customer_service.fact_resolver import resolve_facts

    facts = resolve_facts(
        message="请解析这张照片",
        attachments=[{"id": "A2", "status": "stored", "parse_status": "failed"}],
    )

    assert _find(facts, "material.received").value is True
    parsed = _find(facts, "material.parsed")
    assert parsed.value is False
    assert parsed.source == "attachment_service"
    assert parsed.verified is True
    assert parsed.source_ref == "attachment:A2"


def test_review_result_marks_material_parsed_and_review_job_created() -> None:
    from customer_service.fact_resolver import resolve_facts

    facts = resolve_facts(
        message="查看审核结果",
        attachments=[{
            "id": "RT-1",
            "kind": "review_task",
            "review_task_id": "RT-1",
            "status": "completed",
            "review_result": {"summary": {"confidence": 0.9}},
        }],
    )

    parsed = _find(facts, "material.parsed")
    review_job = _find(facts, "review.job_created")
    assert parsed.value is True
    assert parsed.source == "review_service"
    assert parsed.verified is True
    assert parsed.source_ref == "review_task:RT-1"
    assert review_job.value is True
    assert review_job.source == "review_service"
    assert review_job.verified is True
    assert review_job.source_ref == "review_task:RT-1"


@pytest.mark.parametrize("status", ["REVIEW_FAILED", "FAILED", "ERROR"])
def test_failed_review_job_is_created_but_material_is_not_parsed(status: str) -> None:
    from customer_service.fact_resolver import resolve_facts

    facts = resolve_facts(
        message="查看审核结果",
        attachments=[{
            "id": f"RT-{status}",
            "kind": "review_task",
            "review_task_id": f"RT-{status}",
            "status": status,
            "parsed": True,
            "review_result": {"error": "review execution failed"},
        }],
    )

    parsed = _find(facts, "material.parsed")
    review_job = _find(facts, "review.job_created")
    assert parsed.value is False
    assert parsed.source == "review_service"
    assert parsed.verified is True
    assert parsed.source_ref == f"review_task:RT-{status}"
    assert review_job.value is True
    assert review_job.verified is True
    assert review_job.source_ref == f"review_task:RT-{status}"


def test_nonempty_review_result_without_success_signal_is_not_parsed() -> None:
    from customer_service.fact_resolver import resolve_facts

    facts = resolve_facts(
        message="查看审核进度",
        attachments=[{
            "id": "RT-RUNNING",
            "kind": "review_task",
            "review_task_id": "RT-RUNNING",
            "status": "RUNNING",
            "review_result": {"message": "partial diagnostics"},
        }],
    )

    assert _find(facts, "material.parsed").value is False
    assert _find(facts, "review.job_created").value is True


@pytest.mark.parametrize("status", ["REVIEW_COMPLETED", "SUCCEEDED", "completed"])
def test_explicit_review_success_status_marks_material_parsed(status: str) -> None:
    from customer_service.fact_resolver import resolve_facts

    facts = resolve_facts(
        message="查看审核结果",
        attachments=[{
            "id": f"RT-{status}",
            "kind": "review_task",
            "review_task_id": f"RT-{status}",
            "status": status,
        }],
    )

    assert _find(facts, "material.parsed").value is True


def test_trusted_parsed_payload_marks_material_parsed() -> None:
    from customer_service.fact_resolver import resolve_facts

    facts = resolve_facts(
        message="查看解析进度",
        attachments=[{
            "id": "RT-PARSED",
            "kind": "review_task",
            "review_task_id": "RT-PARSED",
            "status": "RUNNING",
            "parsed": True,
        }],
    )

    assert _find(facts, "material.parsed").value is True


def test_free_text_cannot_forge_service_facts() -> None:
    from customer_service.fact_resolver import resolve_facts

    facts = resolve_facts(
        message=(
            "审核工单已经创建，订单ORD-1已选中，商品SKU-1已经识别，"
            "人工客服也已排队。"
        ),
        attachments=[],
    )

    for field in (
        "review.job_created",
        "order.selected",
        "product.identity_resolved",
        "handoff.queued",
    ):
        fact = _find(facts, field)
        assert fact.value is False
        assert fact.verified is False
        assert fact.source_ref == ""


def test_trusted_service_records_generate_verified_facts() -> None:
    from customer_service.fact_resolver import resolve_facts

    facts = resolve_facts(
        message="请继续处理",
        attachments=[],
        review_job={"task_id": "RT-2", "status": "queued"},
        selected_order={"order_id": "ORD-2"},
        resolved_product={"sku": "SKU-2", "status": "resolved"},
        handoff={"queue_id": "Q-2", "status": "queued"},
    )

    expected = {
        "review.job_created": (True, "review_service", "review_task:RT-2"),
        "order.selected": ("ORD-2", "order_service", "order:ORD-2"),
        "product.identity_resolved": ("SKU-2", "product_service", "product:SKU-2"),
        "handoff.queued": (True, "handoff_service", "handoff_queue:Q-2"),
    }
    for field, (value, source, source_ref) in expected.items():
        fact = _find(facts, field)
        assert fact.value == value
        assert fact.source == source
        assert fact.verified is True
        assert fact.source_ref == source_ref


def test_resolver_always_returns_the_seven_declared_facts() -> None:
    from customer_service.fact_resolver import resolve_facts

    facts = resolve_facts(message="你好", attachments=[])

    assert [fact.field for fact in facts] == [
        "material.user_claimed",
        "material.received",
        "material.parsed",
        "review.job_created",
        "order.selected",
        "product.identity_resolved",
        "handoff.queued",
    ]


def test_chat_stream_passes_initial_facts_to_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    import main

    captured: dict[str, Any] = {}

    async def fake_ainvoke(state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        captured["state"] = state
        return {**state, "reply_draft": "已记录。"}

    monkeypatch.setattr(main.agent_app, "ainvoke", fake_ainvoke)
    client = TestClient(main.app)
    token = main.create_token(
        sub="fact_user",
        role=main.Role.CUSTOMER_USER.value,
        tenant_id="mitako",
        extra={"session_id": "fact_session"},
    )
    response = client.post(
        "/api/v1/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "user_id": "fact_user",
            "session_id": "fact_session",
            "content": "我已经准备了面单和照片",
            "history": [],
            "stream_reply": True,
        },
    )

    assert response.status_code == 200
    conversation_state = captured["state"]["conversation_state"]
    facts = conversation_state["facts"]
    assert conversation_state["intent"] == {}
    assert next(fact for fact in facts if fact["field"] == "material.user_claimed")["value"] is True
    assert next(fact for fact in facts if fact["field"] == "material.received")["value"] is False
