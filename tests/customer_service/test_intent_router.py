# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "customer_agent_20260818_cases.json"
CASES = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]


def _route(message: str):
    from customer_service.intent_router import route_intent

    return route_intent(message, history=[])


@pytest.mark.parametrize("case", CASES, ids=lambda row: row["case_id"])
def test_intent_matches_frozen_case(case: dict[str, object]) -> None:
    result = _route(str(case["message"]))

    assert result.intent_code == case["expected_intent"]
    assert result.scenario_code == case["expected_scenario"]
    assert 0.0 <= result.confidence <= 1.0
    assert result.matched_evidence


@pytest.mark.parametrize(
    ("message", "expected_intent", "expected_scenario"),
    [
        ("延期180天了，我要求退款并转人工。", "human_handoff", "refund_progress"),
        ("想问五条悟徽章的发货时间。", "product_consultation", "product_consultation"),
        ("先核对活动规则，限定特典没有收到。", "entitlement_missing", "missing_item"),
        ("删除手机号后再处理账号换绑。", "privacy_deletion", "privacy_compliance"),
        ("别敷衍，直接说谁处理、多久，否则我投诉。", "high_risk_complaint", "complaint"),
        ("这单应有8个，实收7个。", "missing_item", "missing_item"),
    ],
)
def test_priority_and_compound_scenarios(
    message: str, expected_intent: str, expected_scenario: str
) -> None:
    result = _route(message)

    assert result.intent_code == expected_intent
    assert result.scenario_code == expected_scenario


def test_unknown_input_requires_clarification() -> None:
    result = _route("这个情况能帮我看看吗？")

    assert result.intent_code == "casual_chat"
    assert result.scenario_code == "casual_chat"
    assert result.requires_clarification is True
    assert result.clarification_fields == ["request"]


def test_entitlement_keyword_without_missing_signal_does_not_hide_damage() -> None:
    result = _route("限定特典卡表面有明显划痕。")

    assert result.intent_code == "product_damage"
    assert result.scenario_code == "product_damage"


@pytest.mark.parametrize(
    ("message", "expected_code", "expected_label"),
    [
        ("物流更新后请电话提醒我。", "notification_channel", "通知渠道/服务建议"),
        ("这单延误了，我想申请补偿。", "refund_compensation", "退款退货/补偿"),
        ("重复款能去置换区交换吗？", "lottery_exchange", "盲盒相关/置换区咨询"),
    ],
)
def test_legacy_public_intent_labels_remain_compatible(
    message: str, expected_code: str, expected_label: str
) -> None:
    from customer_service.intent_router import public_intent_label

    result = _route(message)

    assert result.intent_code == expected_code
    assert public_intent_label(result) == expected_label


def test_classify_intent_keeps_public_label_and_stores_typed_result() -> None:
    import agent

    async def run_case():
        queue = asyncio.Queue()
        result = await agent.classify_intent(
            {"messages": [{"role": "user", "content": "想问五条悟徽章的库存和发货时间"}]},
            {"configurable": {"event_queue": queue}},
        )
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())
        return result, events

    result, events = asyncio.run(run_case())
    typed_intent = result["conversation_state"]["intent"]
    analysis_event = next(event for event in events if event["type"] == "unified_analysis")

    assert result["intent"] == "售前商品咨询"
    assert typed_intent["intent_code"] == "product_consultation"
    assert typed_intent["scenario_code"] == "product_consultation"
    assert analysis_event["intent"] == result["intent"]
    assert analysis_event["intent_code"] == typed_intent["intent_code"]
    assert analysis_event["scenario_code"] == typed_intent["scenario_code"]


def test_generate_reply_cannot_override_deterministic_intent(monkeypatch: pytest.MonkeyPatch) -> None:
    import agent

    async def fake_call_llm(*args, **kwargs):
        return (
            '<analysis>{"intent":"物流追踪/催发货","emotion_level":4,'
            '"analysis":"用户焦虑","should_transfer":false}</analysis>\n回复正文'
        )

    monkeypatch.setattr(agent, "call_llm", fake_call_llm)
    state = {
        "messages": [{"role": "user", "content": "想问五条悟徽章的库存"}],
        "intent": "售前商品咨询",
        "emotion_level": 2,
        "order_data": {},
        "logistics_data": {},
        "sop_results": [],
        "user_memory": {},
        "compensation_given": [],
        "should_transfer": False,
        "transfer_reason": "",
        "attachments": [],
        "sop_state": {},
        "conversation_state": {
            "intent": {
                "intent_code": "product_consultation",
                "scenario_code": "product_consultation",
                "confidence": 0.95,
                "matched_evidence": ["库存"],
                "requires_clarification": False,
                "clarification_fields": [],
            }
        },
    }

    updates = asyncio.run(agent.generate_reply_with_persona(state, {"configurable": {}}))

    assert "intent" not in updates
    assert updates["emotion_level"] == 4
