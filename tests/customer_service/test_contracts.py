# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_completed_action_requires_receipt() -> None:
    from customer_service.contracts import ActionState

    with pytest.raises(ValidationError, match="completed_action_requires_receipt"):
        ActionState(action="human_handoff", status="queued")


def test_user_statement_cannot_verify_system_fact() -> None:
    from customer_service.contracts import Fact

    fact = Fact(field="material.received", value=True, source="user_statement", verified=True)
    assert fact.verified is False


def test_queued_action_with_receipt_is_valid() -> None:
    from customer_service.contracts import ActionState

    action = ActionState(
        action="human_handoff",
        status="queued",
        receipt_id="QUEUE-1",
        tool_name="handoff_service",
        occurred_at="2026-08-18T20:00:00+08:00",
        reason_code="queue_joined",
    )
    assert action.status == "queued"


def test_succeeded_action_with_receipt_is_valid() -> None:
    from customer_service.contracts import ActionState

    action = ActionState(
        action="order_lookup",
        status="succeeded",
        receipt_id="ORDER-1",
        tool_name="order_service",
        occurred_at="2026-08-18T20:00:00+08:00",
    )
    assert action.status == "succeeded"


@pytest.mark.parametrize("status", ["queued", "succeeded"])
@pytest.mark.parametrize("field", ["receipt_id", "tool_name", "occurred_at"])
def test_receipt_fields_reject_whitespace(status: str, field: str) -> None:
    from customer_service.contracts import ActionState

    payload = {
        "action": "human_handoff",
        "status": status,
        "receipt_id": "QUEUE-1",
        "tool_name": "handoff_service",
        "occurred_at": "2026-08-18T20:00:00+08:00",
    }
    payload[field] = "   "

    with pytest.raises(ValidationError, match="completed_action_requires_receipt"):
        ActionState.model_validate(payload)


def test_completed_action_rejects_one_missing_receipt_field() -> None:
    from customer_service.contracts import ActionState

    with pytest.raises(ValidationError, match="completed_action_requires_receipt"):
        ActionState(
            action="human_handoff",
            status="queued",
            receipt_id="QUEUE-1",
            tool_name="handoff_service",
        )


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_intent_confidence_rejects_out_of_range_values(confidence: float) -> None:
    from customer_service.contracts import IntentResult

    with pytest.raises(ValidationError):
        IntentResult(
            intent_code="privacy_deletion",
            scenario_code="privacy_compliance",
            confidence=confidence,
        )


def test_intent_result_defaults_atomic_lists_to_primary_codes() -> None:
    from customer_service.contracts import IntentResult

    result = IntentResult(
        intent_code="human_handoff",
        scenario_code="refund_progress",
        confidence=0.95,
    )

    assert result.intent_codes == ["human_handoff"]
    assert result.scenario_codes == ["refund_progress"]


def test_intent_result_stably_deduplicates_and_keeps_primary_codes_first() -> None:
    from customer_service.contracts import IntentResult

    result = IntentResult(
        intent_code="human_handoff",
        scenario_code="refund_progress",
        intent_codes=["refund_progress", "human_handoff", "refund_progress"],
        scenario_codes=["refund_progress", "refund_progress"],
        confidence=0.95,
    )

    assert result.intent_codes == ["human_handoff", "refund_progress"]
    assert result.scenario_codes == ["refund_progress"]


@pytest.mark.parametrize("source_ref", ["", "   "])
def test_verified_system_fact_requires_source_ref(source_ref: str) -> None:
    from customer_service.contracts import Fact

    with pytest.raises(ValidationError, match="verified_system_fact_requires_source_ref"):
        Fact(
            field="material.received",
            value=True,
            source="attachment_service",
            source_ref=source_ref,
            verified=True,
        )


def test_conversation_state_rejects_unknown_fields() -> None:
    from customer_service.contracts import ConversationState

    payload = {
        "intent": {
            "intent_code": "privacy_deletion",
            "scenario_code": "privacy_compliance",
            "confidence": 0.95,
        },
        "facts": [],
        "material_state": {},
        "action_state": {"action": "privacy_deletion", "status": "not_requested"},
        "next_step": {"code": "show_privacy_entry", "label": "查看隐私申请入口"},
        "core_conclusion": "privacy_verification_required",
        "unexpected": "must fail",
    }
    with pytest.raises(ValidationError, match="extra_forbidden"):
        ConversationState.model_validate(payload)


def test_conversation_state_rejects_nested_unknown_fields() -> None:
    from customer_service.contracts import ConversationState

    payload = {
        "intent": {
            "intent_code": "privacy_deletion",
            "scenario_code": "privacy_compliance",
            "confidence": 0.95,
            "unexpected": "must fail",
        },
        "facts": [],
        "material_state": {},
        "action_state": {"action": "privacy_deletion", "status": "not_requested"},
        "next_step": {"code": "show_privacy_entry", "label": "查看隐私申请入口"},
        "core_conclusion": "privacy_verification_required",
    }
    with pytest.raises(ValidationError, match="extra_forbidden"):
        ConversationState.model_validate(payload)
