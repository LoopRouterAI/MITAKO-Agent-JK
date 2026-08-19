# -*- coding: utf-8 -*-
import json
from pathlib import Path

import pytest

from customer_service.action_state import action_from_tool
from customer_service.contracts import ActionState, ActionStatus
from customer_service.fact_resolver import resolve_facts
from customer_service.intent_router import route_intent
from customer_service.reply_guard import guard_reply
from customer_service.reply_plan import build_reply_plan, render_reply_plan
from customer_service.scenario_policy import decide_scenario


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "customer_agent_20260818_cases.json"
FIXED_TIME = "2026-08-19T09:00:00+08:00"


def _cases() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]


def _tool_action(case: dict) -> ActionState | None:
    case_id = case["case_id"]
    if case_id in {"CHAT-07-REFUND-HANDOFF", "CHAT-08-HIGH-RISK-COMPLAINT"}:
        return action_from_tool("human_handoff", "handoff_service", {
            "status": "queued",
            "queue_id": f"QUEUE-{case_id}",
            "enqueued_at": FIXED_TIME,
        })
    if case_id == "CHAT-09-ADDRESS-CHANGE-FAILURE":
        return action_from_tool("address_change", "order_service", {
            "status": "failed",
            "reason_code": "tool_unavailable",
        })
    if case_id in {"CHAT-12-LOGISTICS-IN-TRANSIT", "CHAT-15-SHIPMENT-PROGRESS"}:
        return action_from_tool("order_lookup", "order_service", {
            "status": "succeeded",
            "receipt_id": f"ORDER-{case_id}",
            "occurred_at": FIXED_TIME,
        })
    if case_id == "CHAT-13-SECOND-ORDER":
        return ActionState(
            action="order_lookup",
            status=ActionStatus.REQUESTED,
            reason_code="order_selection_required",
        )
    return None


def _run_case(case: dict) -> tuple[tuple[str, str, str, str, str], str, dict]:
    intent = route_intent(case["message"], history=[])
    facts = resolve_facts(message=case["message"], attachments=[])
    action = _tool_action(case)
    decision = decide_scenario(
        intent=intent,
        facts=facts,
        message=case["message"],
        action=action,
        config={
            "privacy": {
                "entry": "联系隐私专席提交身份核验申请",
                "sla": "身份核验通过后 15 个工作日内处理",
            }
        },
    )
    if action is not None and action.action == decision.action_state.action:
        decision.action_state = action
    state = {
        "intent": intent.model_dump(mode="json"),
        "facts": [fact.model_dump(mode="json") for fact in facts],
        "scenario_decision": decision.model_dump(mode="json"),
        "core_conclusion": decision.core_conclusion,
        "action_state": decision.action_state.model_dump(mode="json"),
        "next_step": decision.next_step.model_dump(mode="json"),
    }
    plan = build_reply_plan(state)
    reply = guard_reply(
        render_reply_plan(plan),
        conversation_state=state,
        reply_plan=plan,
    ).reply
    signature = (
        intent.intent_code,
        intent.scenario_code,
        decision.core_conclusion,
        decision.action_state.status.value,
        decision.next_step.code,
    )
    return signature, reply, state


@pytest.mark.parametrize("case", _cases(), ids=lambda row: row["case_id"])
def test_each_case_matches_frozen_contract_for_three_rounds(case: dict) -> None:
    runs = [_run_case(case) for _ in range(3)]
    signatures = {run[0] for run in runs}
    expected = (
        case["expected_intent"],
        case["expected_scenario"],
        case["expected_core_conclusion"],
        case["expected_action_status"],
        case["expected_next_step"],
    )

    assert signatures == {expected}
    for _, reply, state in runs:
        for forbidden in case.get("forbidden_claims", []):
            assert forbidden not in reply
        action = state["action_state"]
        if action["status"] in {"queued", "succeeded"}:
            assert action["receipt_id"]
            assert action["occurred_at"]
