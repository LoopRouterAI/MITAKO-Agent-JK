# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from customer_service.contracts import ActionState, Fact, NextStep, ReplyPlan


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "customer_agent_20260818_cases.json"


def _action(action: str = "none", status: str = "not_requested") -> dict:
    payload = {"action": action, "status": status}
    if status in {"queued", "succeeded"}:
        payload.update({
            "receipt_id": f"RECEIPT-{action}",
            "tool_name": f"{action}_service",
            "occurred_at": "2026-08-18T20:00:00+08:00",
        })
    return payload


def _state(
    *,
    action: dict | None = None,
    facts: list[dict] | None = None,
    conclusion: str = "scenario_policy_not_applicable",
    next_step: str = "continue_existing_flow",
    decision: dict | None = None,
) -> dict:
    action_state = action or _action()
    return {
        "facts": facts or [],
        "core_conclusion": conclusion,
        "action_state": action_state,
        "next_step": {"code": next_step, "label": "继续当前服务流程"},
        "scenario_decision": decision or {
            "core_conclusion": conclusion,
            "action_state": action_state,
            "next_step": {"code": next_step, "label": "继续当前服务流程"},
            "policy_refs": [],
            "details": {},
            "required_reply_fields": [],
        },
    }


def _plan(state: dict) -> ReplyPlan:
    return ReplyPlan(
        facts=[Fact.model_validate(item) for item in state.get("facts") or [] if item.get("verified")],
        must_say=["当前信息仍需核对。"],
        must_not_say=[],
        action=ActionState.model_validate(state["action_state"]),
        next_step=NextStep.model_validate(state["next_step"]),
    )


def _claim_plan(state: dict, claim: str, *, must_not_say: list[str] | None = None) -> ReplyPlan:
    return ReplyPlan(
        facts=[Fact.model_validate(item) for item in state.get("facts") or [] if item.get("verified")],
        must_say=[claim],
        must_not_say=must_not_say or [],
        action=ActionState.model_validate(state["action_state"]),
        next_step=NextStep(code="claim_check", label=""),
    )


@pytest.mark.parametrize(
    "claim",
    ["已上传", "已收到", "已解析", "已建单", "审核中", "已转接", "已进入队列", "已审批", "已退款", "已修改", "已删除"],
)
def test_completed_claim_requires_verified_fact_or_matching_receipt(claim: str) -> None:
    from customer_service.reply_guard import guard_reply

    result = guard_reply(claim, conversation_state=_state())

    assert result.allowed is False
    assert result.reason_code == "unsupported_completed_action"


@pytest.mark.parametrize(
    ("claim", "conversation_state"),
    [
        (
            "材料已上传并收到。",
            _state(facts=[{
                "field": "material.received",
                "value": True,
                "source": "attachment_service",
                "source_ref": "attachment:A-1",
                "verified": True,
            }]),
        ),
        (
            "材料已解析。",
            _state(facts=[{
                "field": "material.parsed",
                "value": True,
                "source": "review_service",
                "source_ref": "review_task:R-1",
                "verified": True,
            }]),
        ),
        ("审核任务已建单，正在审核中。", _state(action=_action("review_job_create", "queued"))),
        ("已进入队列。", _state(action=_action("human_handoff", "queued"))),
        ("申请已审批。", _state(action=_action("review_approval", "succeeded"))),
        ("退款已完成。", _state(action=_action("refund_request", "succeeded"))),
        ("地址已修改。", _state(action=_action("address_change", "succeeded"))),
        ("隐私资料已删除。", _state(action=_action("privacy_deletion", "succeeded"))),
    ],
)
def test_matching_verified_evidence_allows_completed_claim(claim: str, conversation_state: dict) -> None:
    from customer_service.reply_guard import guard_reply

    assert guard_reply(
        claim,
        conversation_state=conversation_state,
        reply_plan=_claim_plan(conversation_state, claim),
    ).allowed is True


@pytest.mark.parametrize("status", ["requested", "accepted", "pending_human", "failed"])
def test_non_completed_action_status_never_allows_completed_claim(status: str) -> None:
    from customer_service.reply_guard import guard_reply

    result = guard_reply("退款已完成。", conversation_state=_state(action=_action("refund_request", status)))

    assert result.allowed is False
    assert result.reason_code == "unsupported_completed_action"


@pytest.mark.parametrize(
    ("action", "claim"),
    [
        ("refund_request", "退款已完成。"),
        ("address_change", "地址已修改。"),
        ("privacy_deletion", "隐私资料已删除。"),
    ],
)
def test_queued_write_action_cannot_claim_business_completion(action: str, claim: str) -> None:
    from customer_service.reply_guard import guard_reply

    result = guard_reply(claim, conversation_state=_state(action=_action(action, "queued")))

    assert result.allowed is False
    assert result.reason_code == "unsupported_completed_action"


def test_handoff_queue_receipt_allows_queue_claim_but_not_transfer_claim() -> None:
    from customer_service.reply_guard import guard_reply

    state = _state(action=_action("human_handoff", "queued"))

    plan = _claim_plan(state, "已进入队列。", must_not_say=["已转接"])
    assert guard_reply("已进入队列。", conversation_state=state, reply_plan=plan).allowed is True
    rejected = guard_reply("已转接人工客服。", conversation_state=state, reply_plan=plan)
    assert rejected.allowed is False
    assert rejected.reason_code == "unsupported_completed_action"


def test_user_statement_never_allows_completed_claim() -> None:
    from customer_service.reply_guard import guard_reply

    state = _state(facts=[{
        "field": "material.received",
        "value": True,
        "source": "user_statement",
        "source_ref": "current_message",
        "verified": True,
    }])

    assert guard_reply("材料已收到。", conversation_state=state).allowed is False


def test_matching_receipt_must_match_claimed_action() -> None:
    from customer_service.reply_guard import guard_reply

    result = guard_reply(
        "退款已完成。",
        conversation_state=_state(action=_action("human_handoff", "queued")),
    )

    assert result.allowed is False
    assert result.reason_code == "unsupported_completed_action"


@pytest.mark.parametrize(
    "reply",
    [
        "五条悟徽章当前有库存。",
        "五条悟徽章直径65毫米。",
        "已确认 SKU-UNKNOWN-9。",
        "保证明天发货。",
        "预计下周发货。",
        "我们会很快处理完成。",
        "责任角色：仓库主管。",
        "首次响应时效：30分钟。",
        "跟进凭证：FAKE-100。",
        "隐私入口：https://example.invalid/privacy，3个工作日完成。",
    ],
)
def test_business_claims_must_come_from_public_reply_plan(reply: str) -> None:
    from customer_service.reply_guard import guard_reply

    state = _state()
    result = guard_reply(reply, conversation_state=state, reply_plan=_plan(state))

    assert result.allowed is False
    assert result.reason_code == "unsupported_business_fact"


def test_reply_must_include_reply_plan_required_content() -> None:
    from customer_service.reply_guard import guard_reply
    from customer_service.reply_plan import build_reply_plan

    state = _state(
        conclusion="product_identity_ambiguous",
        next_step="request_product_identity",
    )
    result = guard_reply(
        "好的，请稍等。",
        conversation_state=state,
        reply_plan=build_reply_plan(state),
    )

    assert result.allowed is False
    assert result.reason_code == "missing_required_reply_fact"


def test_unknown_product_plan_does_not_invent_default_product() -> None:
    from customer_service.reply_plan import build_reply_plan, render_reply_plan

    state = _state(
        conclusion="product_identity_ambiguous",
        next_step="request_product_identity",
    )
    reply = render_reply_plan(build_reply_plan(state))

    assert "SKU、商品链接或订单行" in reply
    assert "排球少年" not in reply
    assert "库存有" not in reply
    assert "预计发货" not in reply


def test_privacy_url_and_sla_only_use_explicit_scenario_config() -> None:
    from customer_service.reply_plan import build_reply_plan, render_reply_plan

    unconfigured = _state(
        conclusion="privacy_verification_required",
        next_step="show_privacy_human_entry",
    )
    assert "http" not in render_reply_plan(build_reply_plan(unconfigured))
    assert "工作日" not in render_reply_plan(build_reply_plan(unconfigured))

    decision = {
        **unconfigured["scenario_decision"],
        "privacy_entry": "https://privacy.example.test/apply",
        "privacy_sla": "7个工作日内反馈受理结果",
    }
    configured = {**unconfigured, "scenario_decision": decision}
    reply = render_reply_plan(build_reply_plan(configured))
    assert "https://privacy.example.test/apply" in reply
    assert "7个工作日内反馈受理结果" in reply


def test_complaint_plan_uses_deterministic_four_fields_and_real_receipt() -> None:
    from customer_service.reply_plan import build_reply_plan, render_reply_plan

    action = _action("human_handoff", "queued")
    state = _state(
        action=action,
        conclusion="complaint_protocol_required",
        next_step="show_owner_sla_receipt",
        decision={
            "core_conclusion": "complaint_protocol_required",
            "action_state": action,
            "next_step": {"code": "show_owner_sla_receipt", "label": "展示投诉处理信息"},
            "policy_refs": ["MITAKO-CUSTOMER-CHAT-20260818.1/complaint-protocol"],
            "details": {
                "complaint_protocol": {
                    "responsible_role": "VIP客服主管",
                    "current_action": "同步投诉简报",
                    "first_response_sla": "入队后3分钟内首次响应",
                }
            },
            "required_reply_fields": [
                "responsible_role",
                "current_action",
                "first_response_sla",
                "tracking_receipt",
            ],
        },
    )

    reply = render_reply_plan(build_reply_plan(state))

    assert "责任角色：VIP客服主管" in reply
    assert "当前动作：已进入人工队列并同步投诉简报" in reply
    assert "首次响应时效：入队后3分钟内首次响应" in reply
    assert f"跟进凭证：{action['receipt_id']}" in reply


def test_complaint_fields_cannot_reuse_value_from_another_field() -> None:
    from customer_service.reply_guard import guard_reply
    from customer_service.reply_plan import build_reply_plan

    action = _action("human_handoff", "queued")
    state = _state(
        action=action,
        conclusion="complaint_protocol_required",
        next_step="show_owner_sla_receipt",
        decision={
            "core_conclusion": "complaint_protocol_required",
            "action_state": action,
            "next_step": {"code": "show_owner_sla_receipt", "label": "展示投诉处理信息"},
            "policy_refs": [],
            "details": {"complaint_protocol": {
                "responsible_role": "VIP客服主管",
                "first_response_sla": "入队后3分钟内首次响应",
            }},
            "required_reply_fields": [],
        },
    )
    plan = build_reply_plan(state)

    for reply in (
        "责任角色：VIP客服主管。当前动作：已进入人工队列并同步投诉简报。首次响应时效：入队后3分钟内首次响应。跟进凭证：VIP客服主管。",
        f"责任角色：VIP客服主管。当前动作：已进入人工队列并同步投诉简报。首次响应时效：{action['receipt_id']}。跟进凭证：{action['receipt_id']}。",
    ):
        result = guard_reply(reply, conversation_state=state, reply_plan=plan)
        assert result.allowed is False
        assert result.reason_code == "unsupported_business_fact"


def test_program_templates_cover_pdf_cases_without_forbidden_claims() -> None:
    from customer_service.reply_guard import guard_reply
    from customer_service.reply_plan import build_reply_plan, render_reply_plan

    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]
    covered = 0
    for case in cases:
        status = case["expected_action_status"]
        action_name = {
            "human_handoff": "human_handoff",
            "high_risk_complaint": "human_handoff",
            "address_change": "address_change",
            "order_logistics": "order_lookup",
        }.get(case["expected_intent"], case["expected_intent"])
        action = _action(action_name, status)
        decision = {
            "core_conclusion": case["expected_core_conclusion"],
            "action_state": action,
            "next_step": {"code": case["expected_next_step"], "label": "继续当前确定性流程"},
            "policy_refs": ["MITAKO-CUSTOMER-CHAT-20260818.1/fixture"],
            "details": {},
            "required_reply_fields": [],
        }
        if case["expected_intent"] == "high_risk_complaint":
            decision["details"] = {
                "complaint_protocol": {
                    "responsible_role": "VIP客服主管",
                    "current_action": "同步投诉简报",
                    "first_response_sla": "入队后3分钟内首次响应",
                }
            }
        state = _state(
            action=action,
            conclusion=case["expected_core_conclusion"],
            next_step=case["expected_next_step"],
            decision=decision,
        )
        plan = build_reply_plan(state)
        reply = render_reply_plan(plan)
        result = guard_reply(reply, conversation_state=state, reply_plan=plan)

        assert result.allowed is True, (case["case_id"], result.reason_code, reply)
        assert all(claim not in reply for claim in case["forbidden_claims"]), (case["case_id"], reply)
        assert all(term not in reply for term in ("咪好", "模型", "Key", "Prompt", "演示数据"))
        for claim in case["forbidden_claims"]:
            rejected = guard_reply(claim, conversation_state=state, reply_plan=plan)
            assert rejected.allowed is False, (case["case_id"], claim)
        covered += bool(reply.strip())

    assert covered >= 10


def test_agent_only_sends_public_reply_plan_to_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    import agent

    captured: dict[str, object] = {}

    async def fake_call_llm(system_prompt, user_payload, history, queue, **kwargs):
        captured.update({
            "system_prompt": system_prompt,
            "user_payload": user_payload,
            "history": history,
            "kwargs": kwargs,
        })
        return "当前信息仍需核对。"

    monkeypatch.setattr(agent, "call_llm", fake_call_llm)
    state = {
        "messages": [
            {"role": "assistant", "content": "SECRET-HISTORY"},
            {"role": "user", "content": "SECRET-USER-MESSAGE"},
        ],
        "raw_user_content": "SECRET-RAW-CONTENT",
        "user_id": "reply-plan-user",
        "session_id": "reply-plan-session",
        "tenant_id": "mitako",
        "intent": "售前商品咨询",
        "conversation_state": _state(
            conclusion="product_identity_ambiguous",
            next_step="request_product_identity",
        ),
        "emotion_level": 2,
        "order_data": {"secret": "SECRET-ORDER"},
        "logistics_data": {"secret": "SECRET-LOGISTICS"},
        "sop_results": ["SECRET-SOP"],
        "user_memory": {"nickname": "SECRET-NICKNAME"},
        "compensation_given": [],
        "should_transfer": False,
        "transfer_reason": "",
        "attachments": [{"path": "SECRET-PATH"}],
        "sop_state": {},
    }

    result = asyncio.run(agent.generate_reply_with_persona(state, {"configurable": {}}))
    payload = str(captured["user_payload"])

    assert '"must_say"' in payload
    assert captured["history"] == []
    assert all(secret not in payload for secret in (
        "SECRET-USER-MESSAGE",
        "SECRET-RAW-CONTENT",
        "SECRET-ORDER",
        "SECRET-LOGISTICS",
        "SECRET-SOP",
        "SECRET-NICKNAME",
        "SECRET-PATH",
    ))
    assert result["conversation_state"]["reply_plan"]


def test_agent_llm_payload_excludes_internal_action_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    import agent

    captured: dict[str, str] = {}

    async def fake_call_llm(_system_prompt, user_payload, _history, _queue, **_kwargs):
        captured["payload"] = user_payload
        return "当前没有可确认的已执行结果，请按下一步补充或核对信息。"

    monkeypatch.setattr(agent, "call_llm", fake_call_llm)
    conversation_state = _state(
        action={
            "action": "address_change",
            "status": "failed",
            "tool_name": "internal_address_tool",
            "reason_code": "postgres timeout at 10.0.0.8",
            "occurred_at": "2026-08-18T20:00:00+08:00",
        },
        facts=[{
            "field": "review.error",
            "value": "postgres timeout at 10.0.0.8",
            "source": "review_service",
            "source_ref": "review_task:R-ERROR",
            "verified": True,
        }],
    )
    state = {
        "messages": [{"role": "user", "content": "请改地址"}],
        "raw_user_content": "请改地址",
        "intent": "订单信息/地址修改",
        "emotion_level": 2,
        "should_transfer": False,
        "conversation_state": conversation_state,
    }

    asyncio.run(agent.generate_reply_with_persona(state, {"configurable": {}}))

    assert "internal_address_tool" not in captured["payload"]
    assert "postgres timeout" not in captured["payload"]
    assert '"tool_name"' not in captured["payload"]
    assert '"reason_code"' not in captured["payload"]
    assert '"occurred_at"' not in captured["payload"]
    assert "review.error" not in captured["payload"]
    assert "API Key" not in captured["payload"]
    assert "Prompt" not in captured["payload"]
    assert "模型" not in captured["payload"]


def test_key_like_internal_secret_is_blocked() -> None:
    from customer_service.reply_guard import guard_reply

    result = guard_reply("Key: sk-secret", conversation_state=_state())

    assert result.allowed is False
    assert result.reason_code == "internal_text_exposure"


@pytest.mark.parametrize(
    ("conversation_state", "suffix"),
    [
        (_state(action=_action("refund_request", "queued")), "退款处理成功。"),
        (
            _state(
                action=_action("human_handoff", "queued"),
                conclusion="handoff_receipt_required",
                next_step="show_queue_status",
            ),
            "人工已经对接成功。",
        ),
        (
            _state(
                action=_action("human_handoff", "queued"),
                conclusion="complaint_protocol_required",
                next_step="show_owner_sla_receipt",
                decision={
                    "core_conclusion": "complaint_protocol_required",
                    "action_state": _action("human_handoff", "queued"),
                    "next_step": {"code": "show_owner_sla_receipt", "label": "展示投诉处理信息"},
                    "policy_refs": [],
                    "details": {"complaint_protocol": {
                        "responsible_role": "VIP客服主管",
                        "first_response_sla": "入队后3分钟内首次响应",
                    }},
                    "required_reply_fields": [],
                },
            ),
            "最终由仓库主管负责，另一个凭证号为FAKE-2。",
        ),
        (
            _state(
                conclusion="product_identity_ambiguous",
                next_step="request_product_identity",
            ),
            "另有二十件可售，下星期发货。",
        ),
        (
            _state(
                conclusion="child_mobile_invoice_not_acceptable",
                next_step="request_guardian_mobile_proof",
            ),
            "不过孩子自己的手机号同样可以使用。",
        ),
        (_state(), "Key：secret。"),
        (_state(), "本回复由DeepSeek-V4生成。"),
    ],
)
def test_adversarial_reply_variants_are_blocked(conversation_state: dict, suffix: str) -> None:
    from customer_service.reply_guard import guard_reply
    from customer_service.reply_plan import build_reply_plan, render_reply_plan

    plan = build_reply_plan(conversation_state)
    candidate = render_reply_plan(plan) + suffix

    assert guard_reply(
        candidate,
        conversation_state=conversation_state,
        reply_plan=plan,
    ).allowed is False


def test_inconsistent_address_success_plan_never_returns_completed_fallback() -> None:
    from customer_service.reply_guard import guard_reply

    state = _state(
        action=_action("address_change", "failed"),
        conclusion="address_change_succeeded",
        next_step="show_address_change_receipt",
    )
    result = guard_reply("", conversation_state=state)

    assert result.allowed is False
    assert "已修改" not in result.reply
    assert "处理凭证：。" not in result.reply


def test_main_inconsistent_address_success_state_never_sends_completed_claim() -> None:
    import main

    state = _state(
        action=_action("address_change", "failed"),
        conclusion="address_change_succeeded",
        next_step="show_address_change_receipt",
    )
    final = main._finalize_customer_reply({"conversation_state": state, "reply_draft": ""})

    assert final["status"] == "failed"
    assert "已修改" not in final["reply"]


def test_material_received_conclusion_without_verified_fact_uses_upload_template() -> None:
    import main

    state = _state(
        conclusion="material_received",
        next_step="review_received_materials",
    )
    final = main._finalize_customer_reply({"conversation_state": state, "reply_draft": ""})

    assert final["status"] == "failed"
    assert "已有材料接收回执" not in final["reply"]
    assert "上传" in final["reply"]


def test_safety_review_replaces_conflict_without_second_model_call(monkeypatch: pytest.MonkeyPatch) -> None:
    import agent

    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("回复冲突后不得再次调用模型")

    monkeypatch.setattr(agent, "call_llm", fail_if_called)
    state = {
        "messages": [{"role": "user", "content": "退款到哪了？"}],
        "raw_user_content": "退款到哪了？",
        "intent": "退款退货/申请退款",
        "conversation_state": _state(
            action=_action("refund_request", "failed"),
            conclusion="scenario_policy_not_applicable",
        ),
        "reply_draft": "退款已完成。",
        "order_data": {},
        "logistics_data": {},
        "sop_state": {},
    }

    result = asyncio.run(agent.safety_review_agent(state, {"configurable": {}}))

    assert "退款已完成" not in result["reply_draft"]
    assert result["conversation_state"]["reply_guard_reason"] == "unsupported_completed_action"


def test_send_only_emits_guarded_text_chunk() -> None:
    import agent

    async def run() -> tuple[dict, list[dict]]:
        queue = asyncio.Queue()
        conversation_state = _state(
            action=_action("refund_request", "failed"),
            conclusion="scenario_policy_not_applicable",
        )
        result = await agent.send_to_user(
            {
                "conversation_state": conversation_state,
                "reply_draft": "退款已完成。",
            },
            {"configurable": {"event_queue": queue}},
        )
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())
        return result, events

    result, events = asyncio.run(run())
    chunks = [event["content"] for event in events if event["type"] == "text_chunk"]

    assert chunks == [result["reply_draft"]]
    assert "退款已完成" not in chunks[0]


def test_main_final_reply_uses_failed_action_template_instead_of_empty_success() -> None:
    import main

    conversation_state = _state(
        action=_action("address_change", "failed"),
        conclusion="address_change_requires_tool",
        next_step="show_retry_and_human_entry",
    )
    result = {"conversation_state": conversation_state, "reply_draft": ""}

    final = main._finalize_customer_reply(result)

    assert final["status"] == "failed"
    assert "修改未成功" in final["reply"]
    assert "已记录" not in final["reply"]
    assert "已修改" not in final["reply"]


def test_main_final_reply_uses_reply_plan_for_unknown_empty_reply() -> None:
    import main

    conversation_state = _state(
        conclusion="product_identity_ambiguous",
        next_step="request_product_identity",
    )

    final = main._finalize_customer_reply({"conversation_state": conversation_state})

    assert final["status"] == "completed"
    assert "商品 SKU、商品链接或订单行" in final["reply"]
    assert "已记录" not in final["reply"]
    assert final["conversation_state"]["reply_plan"]
    assert final["conversation_state"]["reply_guard_reason"] == "empty_reply"


def test_main_internal_or_structured_reply_cannot_fall_back_to_recorded_claim() -> None:
    import main

    conversation_state = _state(
        conclusion="product_identity_ambiguous",
        next_step="request_product_identity",
    )
    final = main._finalize_customer_reply({
        "conversation_state": conversation_state,
        "reply_draft": '{"model":"internal"}',
    })

    assert "商品 SKU、商品链接或订单行" in final["reply"]
    assert "已记录" not in final["reply"]
    assert final["conversation_state"]["reply_guard_reason"] == "empty_reply"
