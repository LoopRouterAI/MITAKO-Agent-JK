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


def test_refund_handoff_keeps_all_atomic_intents_and_evidence() -> None:
    result = _route("延期180天了，我要求退款并转人工。")

    assert result.intent_code == "human_handoff"
    assert result.scenario_code == "refund_progress"
    assert result.intent_codes == ["human_handoff", "refund_progress"]
    assert result.scenario_codes == ["refund_progress"]
    assert {"转人工", "退款"} <= set(result.matched_evidence)


def test_damage_with_missing_entitlement_keeps_both_atomic_scenes() -> None:
    result = _route("商品有划痕，而且同一包裹还少了一张特典卡。")

    assert result.intent_code == "product_damage"
    assert result.scenario_code == "product_damage"
    assert result.intent_codes == ["product_damage", "entitlement_missing"]
    assert result.scenario_codes == ["product_damage", "missing_item"]
    assert {"划痕", "少了", "特典"} <= set(result.matched_evidence)


@pytest.mark.parametrize(
    ("message", "expected_evidence"),
    [
        ("商品有划痕，而且同一包裹还少特典。", "少特典"),
        ("商品有划痕，而且同一包裹还少一张特典卡。", "少一张特典"),
    ],
)
def test_damage_with_compact_entitlement_missing_phrases_keeps_both_scenes(
    message: str, expected_evidence: str,
) -> None:
    result = _route(message)

    assert result.intent_code == "product_damage"
    assert result.scenario_code == "product_damage"
    assert result.intent_codes == ["product_damage", "entitlement_missing"]
    assert result.scenario_codes == ["product_damage", "missing_item"]
    assert expected_evidence in result.matched_evidence


def test_unknown_input_requires_clarification() -> None:
    result = _route("这个情况能帮我看看吗？")

    assert result.intent_code == "casual_chat"
    assert result.scenario_code == "casual_chat"
    assert result.requires_clarification is True
    assert result.clarification_fields == ["request"]


def test_second_order_request_requires_order_identity() -> None:
    result = _route("我想查第二笔订单，不是刚才那一笔。")

    assert result.intent_code == "order_logistics"
    assert result.requires_clarification is True
    assert "order_id" in result.clarification_fields


@pytest.mark.parametrize(
    "message",
    [
        "我想咨询这笔订单：订单 #024001。当前页面显示状态：待核对。请帮我核对现在进度和下一步处理。",
        "我想咨询这件商品：抽奖排球少年限定色纸。当前页面显示状态：抽奖名额待发。请帮我核对现在进度和下一步处理。订单 #025012。",
    ],
)
def test_order_card_progress_request_enters_order_workflow(message: str) -> None:
    result = _route(message)

    assert result.intent_code == "order_logistics"
    assert result.scenario_code == "order_logistics"
    assert "订单" in result.matched_evidence or "#" in result.matched_evidence


def test_order_card_progress_runs_order_and_logistics_nodes(monkeypatch: pytest.MonkeyPatch) -> None:
    import agent

    async def run_case() -> dict:
        monkeypatch.setattr(agent, "LOCAL_BUSINESS_URL", "http://127.0.0.1:9")
        message = "我想咨询这笔订单：订单 #024001。当前页面显示状态：待核对。请帮我核对现在进度和下一步处理。"
        state = {
            "messages": [{"role": "user", "content": message}],
            "raw_user_content": message,
            "user_id": "usr_001",
            "session_id": "order-progress-regression",
            "active_order_id": "",
            "intent": "",
            "conversation_state": {},
            "emotion_level": 2,
            "order_data": {},
            "logistics_data": {},
            "sop_results": [],
            "user_memory": {},
            "reply_draft": "",
            "safety_check_result": "",
            "should_transfer": False,
            "transfer_reason": "",
            "handoff_offer_id": "",
            "compensation_given": [],
            "meme_tags": [],
            "fixtures": [],
            "attachments": [],
            "sop_state": {},
            "business_events": [],
            "business_cards": [],
        }
        for node in (agent.classify_intent, agent.query_order_system, agent.query_logistics, agent.search_knowledge_base):
            state.update(await node(state, {"configurable": {}}))
        return state

    state = asyncio.run(run_case())
    assert state["conversation_state"]["intent"]["intent_code"] == "order_logistics"
    assert state["conversation_state"]["core_conclusion"] == "show_verified_order_progress"
    assert state["order_data"]["focused_order_id"] == "ORD_2024_001"
    assert state["logistics_data"]["timeline"]


@pytest.mark.parametrize(
    "message",
    [
        "查第二笔订单的退款进度。",
        "第二笔订单退款并转人工。",
    ],
)
def test_compound_second_order_request_still_requires_order_identity(message: str) -> None:
    result = _route(message)

    assert "order_logistics" in result.intent_codes
    assert result.requires_clarification is True
    assert "order_id" in result.clarification_fields


def test_entitlement_keyword_without_missing_signal_does_not_hide_damage() -> None:
    result = _route("限定特典卡表面有明显划痕。")

    assert result.intent_code == "product_damage"
    assert result.scenario_code == "product_damage"


@pytest.mark.parametrize("keyword", ["开箱视频", "剪辑", "离开镜头", "视频审核"])
def test_legacy_damage_evidence_keywords_stay_product_damage(keyword: str) -> None:
    result = _route(f"这个售后材料涉及{keyword}，请帮我看看。")

    assert result.intent_code == "product_damage"
    assert result.scenario_code == "product_damage"


@pytest.mark.parametrize(
    ("message", "expected_intent"),
    [
        ("未成年人退款材料需要视频审核吗？", "minor_refund_material"),
        ("漏发货的开箱视频被剪辑了。", "missing_item"),
        ("发错货的视频审核需要多久？", "wrong_item"),
    ],
)
def test_video_evidence_keywords_do_not_pollute_specific_business_scenes(
    message: str, expected_intent: str
) -> None:
    result = _route(message)

    assert result.intent_code == expected_intent
    assert "product_damage" not in result.intent_codes
    assert not ({"开箱视频", "剪辑", "离开镜头", "视频审核"} & set(result.matched_evidence))


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


def test_generate_reply_cannot_override_deterministic_intent_or_emotion(monkeypatch: pytest.MonkeyPatch) -> None:
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
    assert updates.get("emotion_level", state["emotion_level"]) == 2
    assert updates["conversation_state"]["intent"]["intent_code"] == "product_consultation"


def test_reply_generation_does_not_emit_a_second_analysis_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agent
    import agent_llm

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [{
                    "message": {
                        "content": (
                            '<analysis>{"intent":"物流追踪/催发货","emotion_level":4,'
                            '"should_transfer":false}</analysis>\n回复正文'
                        )
                    }
                }]
            }

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(agent_llm.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(
        agent_llm,
        "get_model_config",
        lambda model_id: {"id": "test", "api_base": "https://example.invalid/v1", "model": "test"},
    )
    monkeypatch.setattr(agent_llm, "get_model_api_key", lambda model_id: "test-key")
    queue = asyncio.Queue()
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
                "intent_codes": ["product_consultation"],
                "scenario_codes": ["product_consultation"],
                "confidence": 0.95,
                "matched_evidence": ["库存"],
                "requires_clarification": False,
                "clarification_fields": [],
            }
        },
    }

    asyncio.run(
        agent.generate_reply_with_persona(
            state,
            {"configurable": {"event_queue": queue, "stream_reply": False, "model_id": "test"}},
        )
    )
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    analyses = [event for event in events if event["type"] == "unified_analysis"]

    assert analyses == []


def test_non_stream_empty_analysis_wrapper_is_not_reported_as_parse_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import agent_llm

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "<analysis></analysis>\n订单已进入核对流程。"}}]}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(agent_llm.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(
        agent_llm,
        "get_model_config",
        lambda model_id: {"id": "test", "api_base": "https://example.invalid/v1", "model": "test"},
    )
    monkeypatch.setattr(agent_llm, "get_model_api_key", lambda model_id: "test-key")
    queue = asyncio.Queue()

    asyncio.run(agent_llm.call_llm(
        "系统提示", "用户消息", [], queue, model_id="test", stream_reply=False,
        emit_text_chunks=True, emit_analysis_event=False,
    ))

    assert "analysis 解析失败" not in capsys.readouterr().out
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    assert any(event.get("type") == "text_chunk" and "订单已进入核对流程" in event.get("content", "") for event in events)


def test_llm_event_filter_preserves_thinking_and_text_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agent_llm

    class FakeStreamResponse:
        status_code = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def aiter_lines(self):
            yield 'data: {"choices":[{"delta":{"reasoning_content":"思考"}}]}'
            yield (
                'data: {"choices":[{"delta":{"content":"<analysis>{\\"intent\\":'
                '\\"物流追踪/催发货\\",\\"emotion_level\\":4}</analysis>回复正文"}}]}'
            )
            yield "data: [DONE]"

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def stream(self, *args, **kwargs):
            return FakeStreamResponse()

    monkeypatch.setattr(agent_llm.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(
        agent_llm,
        "get_model_config",
        lambda model_id: {
            "id": "test",
            "api_base": "https://example.invalid/v1",
            "model": "test",
            "supports_reasoning_stream": True,
        },
    )
    monkeypatch.setattr(agent_llm, "get_model_api_key", lambda model_id: "test-key")
    queue = asyncio.Queue()

    asyncio.run(
        agent_llm.call_llm(
            "系统提示",
            "用户消息",
            [],
            event_queue=queue,
            model_id="test",
            stream_reply=True,
            emit_text_chunks=True,
            emit_analysis_event=False,
        )
    )
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())

    assert any(event["type"] == "llm_thinking" and event["content"] == "思考" for event in events)
    assert any(event["type"] == "text_chunk" and event["content"] == "回复正文" for event in events)
    assert not any(event["type"] == "unified_analysis" for event in events)
