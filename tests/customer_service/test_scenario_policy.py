# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient

from customer_service.contracts import (
    ActionState,
    ActionStatus,
    Fact,
    FactSource,
    IntentResult,
)


def _intent(intent_code: str, scenario_code: str) -> IntentResult:
    return IntentResult(
        intent_code=intent_code,
        scenario_code=scenario_code,
        confidence=0.99,
    )


def _fact(field: str, value: Any, source: FactSource = FactSource.USER_STATEMENT) -> Fact:
    return Fact(field=field, value=value, source=source)


@pytest.mark.parametrize(
    "message",
    [
        "运营商发票登记的是孩子本人手机号，不是监护人手机号。",
        "这张实名账单用的是未成年人自己的号码。",
        "手机号归属人是小孩本人，可以通过吗？",
    ],
)
def test_child_mobile_invoice_is_rejected(message: str) -> None:
    from customer_service.scenario_policy import decide_scenario

    decision = decide_scenario(
        intent=_intent("minor_refund_material", "minor_refund"),
        facts=[_fact("mobile.owner_role", "minor")],
        message=message,
    )

    assert decision.core_conclusion == "child_mobile_invoice_not_acceptable"
    assert decision.next_step.code == "request_guardian_mobile_proof"
    assert decision.action_state.status == ActionStatus.NOT_REQUESTED


@pytest.mark.parametrize("role", ["guardian", "parent", "legal_guardian"])
def test_guardian_mobile_proof_does_not_trigger_child_rejection(role: str) -> None:
    from customer_service.scenario_policy import decide_scenario

    decision = decide_scenario(
        intent=_intent("minor_refund_material", "minor_refund"),
        facts=[_fact("mobile.owner_role", role)],
        message="我提交的是监护人本人实名手机号材料。",
    )

    assert decision.core_conclusion != "child_mobile_invoice_not_acceptable"
    assert decision.next_step.code != "request_guardian_mobile_proof"


def _catalog() -> dict[str, dict[str, Any]]:
    return {
        "HQ-BADGE-01": {
            "product_id": "SKU-HQ-BADGE-01",
            "name": "排球少年 登校系列吧唧套装",
            "product_url": "https://shop.example/products/hq-badge-01",
            "order_line_id": "ORDER-LINE-001",
            "variants": [{"sku": "HQ-HINATA-75", "name": "日向翔阳 75mm"}],
        },
        "JJK-BADGE-01": {
            "product_id": "SKU-JJK-BADGE-01",
            "name": "咒术回战 五条悟方形徽章",
            "product_url": "https://shop.example/products/jjk-badge-01",
            "order_line_id": "ORDER-LINE-002",
            "variants": [{"sku": "JJK-GOJO-SQUARE", "name": "五条悟方形款"}],
        },
    }


@pytest.mark.parametrize(
    "message",
    [
        "想问五条悟圆形徽章的库存和直径，我没有商品链接。",
        "这个徽章什么时候发货？",
        "想查一下吧唧库存。",
    ],
)
def test_product_without_unique_identity_is_ambiguous(message: str) -> None:
    from customer_service.scenario_policy import decide_scenario

    decision = decide_scenario(
        intent=_intent("product_consultation", "product_consultation"),
        facts=[],
        message=message,
        catalog=_catalog(),
    )

    assert decision.core_conclusion == "product_identity_ambiguous"
    assert decision.next_step.code == "request_product_identity"
    assert decision.resolved_product is None


@pytest.mark.parametrize(
    "message",
    [
        "请查 SKU-HQ-BADGE-01 的库存。",
        "这个链接的规格是什么：https://shop.example/products/hq-badge-01",
        "订单行 ORDER-LINE-001 什么时候发货？",
        "排球少年登校系列吧唧套装还有现货吗？",
    ],
)
def test_explicit_or_unique_product_identity_resolves(message: str) -> None:
    from customer_service.scenario_policy import decide_scenario

    decision = decide_scenario(
        intent=_intent("product_consultation", "product_consultation"),
        facts=[],
        message=message,
        catalog=_catalog(),
    )

    assert decision.core_conclusion == "product_identity_resolved"
    assert decision.next_step.code == "show_verified_product_facts"
    assert decision.resolved_product == _catalog()["HQ-BADGE-01"]


def test_catalog_alias_is_not_a_valid_product_identity() -> None:
    from customer_service.scenario_policy import decide_scenario

    decision = decide_scenario(
        intent=_intent("product_consultation", "product_consultation"),
        facts=[],
        message="请查 CATALOG-ALIAS 的库存。",
        catalog={
            "CATALOG-ALIAS": {
                "product_id": "SKU-REAL-PRODUCT-01",
                "name": "真实商品名称",
            }
        },
    )

    assert decision.core_conclusion == "product_identity_ambiguous"
    assert decision.resolved_product is None


@pytest.mark.parametrize(
    "message",
    [
        "请查 XSKU-HQ-BADGE-01-OLD 的库存。",
        "请查 HQ-HINATA-75-FAKE 的库存。",
        "订单行 ORDER-LINE-001-OTHER 什么时候发货？",
        "https://evil.example/?redirect=https://shop.example/products/hq-badge-01",
    ],
)
def test_product_identity_requires_exact_token_or_url(message: str) -> None:
    from customer_service.scenario_policy import decide_scenario

    decision = decide_scenario(
        intent=_intent("product_consultation", "product_consultation"),
        facts=[],
        message=message,
        catalog=_catalog(),
    )

    assert decision.core_conclusion == "product_identity_ambiguous"
    assert decision.resolved_product is None


@pytest.mark.parametrize("term", ["特典卡", "随单赠品", "满赠礼"])
def test_missing_entitlement_requires_activity_baseline(term: str) -> None:
    from customer_service.scenario_policy import decide_scenario

    decision = decide_scenario(
        intent=_intent("entitlement_missing", "missing_item"),
        facts=[],
        message=f"活动页写了有{term}，但包裹里没有。",
        activity={"draw_rule": "每次抽选独立", "prize_pool": [{"tier": "S"}]},
    )

    assert decision.core_conclusion == "entitlement_baseline_required"
    assert decision.next_step.code == "lookup_entitlement_rule"
    assert decision.action_state == ActionState(
        action="entitlement_lookup",
        status="requested",
        reason_code="entitlement_baseline_required",
    )
    assert all("lottery" not in ref for ref in decision.policy_refs)


def test_lottery_rule_is_not_misclassified_as_missing_entitlement() -> None:
    from customer_service.scenario_policy import decide_scenario

    decision = decide_scenario(
        intent=_intent("lottery_rule", "lottery_rule"),
        facts=[],
        message="重复抽会改变中奖概率吗？",
    )

    assert decision.core_conclusion != "entitlement_baseline_required"


def test_business_readiness_does_not_route_entitlement_missing_to_lottery() -> None:
    from business_readiness_service import classify_sop_branch

    result = classify_sop_branch(
        "活动规则承诺限定特典，但包裹里没有。",
        "换货补发/商品破损",
    )

    assert result["ticket_type"] == "missing"


def test_wrong_item_requires_core_unboxing_evidence_with_static_downgrade() -> None:
    from customer_service.scenario_policy import decide_scenario

    decision = decide_scenario(
        intent=_intent("wrong_item", "wrong_item"),
        facts=[],
        message="订单买的是手办，收到的是另一个角色，发错货需要提交哪些材料？",
    )

    assert decision.core_conclusion == "wrong_item_materials_required"
    assert decision.next_step.code == "request_wrong_item_evidence"
    assert decision.details["evidence_grade"] == "required_opening_video_or_static_three_images"
    assert decision.details["video_optional"] is False
    assert decision.details["static_fallback"]["route"] == "static_three_images"
    assert decision.details["static_fallback"]["downgrade_condition"]
    assert decision.details["static_fallback"]["required_fields"] == [
        "received_group_photo",
        "green_bag_or_package_view",
        "matching_waybill",
    ]


def test_wrong_item_static_three_images_selects_downgrade_route_without_video_block() -> None:
    from customer_service.scenario_policy import decide_scenario

    facts = [
        Fact(
            field=f"wrong_item.{field}",
            value=True,
            source=FactSource.ATTACHMENT_SERVICE,
            source_ref=f"ATTACH-{index}",
            verified=True,
        )
        for index, field in enumerate(
            ("received_group_photo", "green_bag_or_package_view", "matching_waybill"),
            start=1,
        )
    ]
    decision = decide_scenario(
        intent=_intent("wrong_item", "wrong_item"),
        facts=facts,
        message="没有合规开箱视频，我已上传商品全家福、包装袋和匹配面单。",
    )

    assert decision.details["selected_evidence_route"] == "static_three_images"
    assert decision.next_step.code == "review_wrong_item_static_evidence"
    assert decision.details["video_missing_blocks_review"] is False


def test_missing_item_parses_expected_received_and_difference() -> None:
    from customer_service.scenario_policy import decide_scenario

    decision = decide_scenario(
        intent=_intent("missing_item", "missing_item"),
        facts=[],
        message="一单应有12个吧唧，实收11个，少了一个，怎么证明漏发？",
    )

    assert decision.core_conclusion == "expected_12_received_11"
    assert decision.details["expected_quantity"] == 12
    assert decision.details["received_quantity"] == 11
    assert decision.details["missing_quantity"] == 1
    assert decision.next_step.code == "request_missing_item_evidence"


def test_missing_item_without_order_association_starts_with_order_lookup() -> None:
    from customer_service.scenario_policy import decide_scenario

    decision = decide_scenario(
        intent=_intent("missing_item", "missing_item"),
        facts=[],
        message="少了一件商品，怎么证明漏发？",
    )

    assert decision.core_conclusion == "missing_item_order_association_required"
    assert decision.next_step.code == "associate_order_before_missing_item"
    assert decision.details["order_association_required"] is True


def test_high_risk_complaint_has_required_reply_fields_and_human_action_plan() -> None:
    from customer_service.scenario_policy import decide_scenario

    decision = decide_scenario(
        intent=_intent("high_risk_complaint", "complaint"),
        facts=[],
        message="不要只道歉，直接说谁处理、多久处理完，否则我投诉。",
    )

    assert decision.core_conclusion == "complaint_protocol_required"
    assert decision.required_reply_fields == [
        "responsible_role",
        "current_action",
        "first_response_sla",
        "tracking_receipt",
    ]
    assert decision.details["human_action_plan"]["required"] is True
    assert decision.details["human_action_plan"]["status"] == "planned"
    assert decision.action_state.action == "human_handoff"
    assert decision.action_state.status == ActionStatus.REQUESTED
    assert decision.next_step.code == "show_owner_sla_receipt"


@pytest.mark.parametrize(
    "message",
    [
        "我有特写照片和面单，但还没有上传。",
        "照片都拍好了，网页里还没提交文件。",
        "手里有开箱视频，不过附件尚未传上来。",
    ],
)
def test_claimed_material_without_attachment_receipt_is_not_received(message: str) -> None:
    from customer_service.scenario_policy import decide_scenario

    decision = decide_scenario(
        intent=_intent("product_damage", "product_damage"),
        facts=[
            _fact("material.user_claimed", True),
            _fact("material.received", False, FactSource.ATTACHMENT_SERVICE),
        ],
        message=message,
    )

    assert decision.core_conclusion == "material_not_received"
    assert decision.next_step.code == "upload_materials"
    assert decision.action_state.status == ActionStatus.NOT_REQUESTED


def test_attachment_receipt_prevents_material_not_received_decision() -> None:
    from customer_service.scenario_policy import decide_scenario

    received = Fact(
        field="material.received",
        value=True,
        source=FactSource.ATTACHMENT_SERVICE,
        source_ref="attachment:A-1",
        verified=True,
    )
    decision = decide_scenario(
        intent=_intent("product_damage", "product_damage"),
        facts=[received],
        message="请审核我刚上传的照片。",
    )

    assert decision.core_conclusion != "material_not_received"
    assert decision.next_step.code == "review_received_materials"


@pytest.mark.parametrize("reason_code", ["tool_timeout", "upstream_rejected"])
def test_failed_address_change_shows_retry_and_human_entry(reason_code: str) -> None:
    from customer_service.scenario_policy import decide_scenario

    action = ActionState(
        action="address_change",
        status="failed",
        tool_name="business_api",
        reason_code=reason_code,
        occurred_at="2026-08-18T20:00:00+08:00",
    )
    decision = decide_scenario(
        intent=_intent("address_change", "order_change"),
        facts=[],
        message="订单还没出库，我填错地址了。",
        action=action,
    )

    assert decision.core_conclusion == "address_change_requires_tool"
    assert decision.action_state is action
    assert decision.next_step.code == "show_retry_and_human_entry"


def test_address_change_without_receipt_never_becomes_success() -> None:
    from customer_service.scenario_policy import decide_scenario

    decision = decide_scenario(
        intent=_intent("address_change", "order_change"),
        facts=[],
        message="帮我修改收货地址。",
    )

    assert decision.core_conclusion == "address_change_requires_tool"
    assert decision.action_state.status == ActionStatus.NOT_REQUESTED
    assert decision.next_step.code == "request_address_change_tool"


def test_succeeded_address_change_requires_and_preserves_receipt() -> None:
    from customer_service.scenario_policy import decide_scenario

    action = ActionState(
        action="address_change",
        status="succeeded",
        receipt_id="ADDR-1",
        tool_name="business_api",
        reason_code="address_updated",
        occurred_at="2026-08-18T20:00:00+08:00",
    )
    decision = decide_scenario(
        intent=_intent("address_change", "order_change"),
        facts=[],
        message="修改收货地址。",
        action=action,
    )

    assert decision.core_conclusion == "address_change_succeeded"
    assert decision.action_state is action
    assert decision.next_step.code == "show_address_change_receipt"


def test_non_address_receipt_cannot_complete_address_change() -> None:
    from customer_service.scenario_policy import decide_scenario

    decision = decide_scenario(
        intent=_intent("address_change", "order_change"),
        facts=[],
        message="修改收货地址。",
        action=ActionState(
            action="human_handoff",
            status="succeeded",
            receipt_id="HANDOFF-1",
            tool_name="handoff_service",
            reason_code="connected",
            occurred_at="2026-08-18T20:00:00+08:00",
        ),
    )

    assert decision.core_conclusion == "address_change_requires_tool"
    assert decision.action_state.status == ActionStatus.NOT_REQUESTED
    assert decision.next_step.code == "request_address_change_tool"


def test_address_change_reaches_policy_instead_of_legacy_handoff() -> None:
    import agent

    transfer = asyncio.run(agent.check_transfer_rules(
        {
            "messages": [{"role": "user", "content": "订单还没出库，请修改收货地址。"}],
            "raw_user_content": "订单还没出库，请修改收货地址。",
            "intent": "订单信息/地址修改",
            "emotion_level": 2,
            "conversation_state": {},
            "user_id": "usr_004",
            "session_id": "address-policy",
        },
        {"configurable": {}},
    ))

    assert transfer["should_transfer"] is False


def test_privacy_deletion_uses_only_explicit_entry_and_sla() -> None:
    from customer_service.scenario_policy import decide_scenario

    decision = decide_scenario(
        intent=_intent("privacy_deletion", "privacy_compliance"),
        facts=[],
        message="我要清除手机号、证件资料和聊天内容。",
        config={
            "privacy": {
                "entry": "https://privacy.example/delete",
                "sla": "身份核验后 10 个工作日内处理",
            }
        },
    )

    assert decision.core_conclusion == "privacy_verification_required"
    assert decision.next_step.code == "show_configured_privacy_entry"
    assert decision.privacy_entry == "https://privacy.example/delete"
    assert decision.privacy_sla == "身份核验后 10 个工作日内处理"
    assert decision.action_state.status == ActionStatus.NOT_REQUESTED


@pytest.mark.parametrize("config", [{}, {"privacy": {"entry": "https://privacy.example/delete"}}])
def test_privacy_deletion_without_complete_config_uses_human_path(config: dict[str, Any]) -> None:
    from customer_service.scenario_policy import decide_scenario

    decision = decide_scenario(
        intent=_intent("privacy_deletion", "privacy_compliance"),
        facts=[],
        message="删除我的全部个人资料，请给入口和时效。",
        config=config,
    )

    assert decision.core_conclusion == "privacy_verification_required"
    assert decision.next_step.code == "show_privacy_human_entry"
    assert decision.privacy_sla == ""
    assert "3-5" not in decision.model_dump_json()
    assert "app" not in decision.privacy_entry.lower()


def test_agent_product_inventory_reply_does_not_fallback_to_first_product(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agent

    monkeypatch.setattr(agent, "_load_demo_business_catalog", lambda: {"product_catalog": _catalog()})

    reply = agent._build_product_inventory_reply({}, "想问五条悟圆形徽章的库存和发货时间")

    assert "排球少年" not in reply
    assert "现货" not in reply
    assert "付款后" not in reply
    assert "商品链接" in reply or "SKU" in reply or "订单行" in reply


def test_review_attachment_projects_only_public_four_scene_fields() -> None:
    import agent

    material_state = agent._public_review_material_state([{
        "kind": "review_task",
        "review_task_id": "RT-1",
        "scenario": "missing_item",
        "status": "succeeded",
        "review_result": {
            "review": {
                "summary": {"confidence": 0.91, "needs_human_review": False, "internal_score": 99},
                "agent_report": {
                    "public_brief": {"conclusion": "活动权益基线待核对", "next_step": "查询活动规则"},
                    "parsed": {"internal_prompt": "不得进入客服状态"},
                },
            },
            "provider": "internal-provider",
        },
    }])

    assert material_state == {
        "contract_version": "MITAKO-FOUR-SCENE@20260814.1",
        "review_task_id": "RT-1",
        "scenario": "missing_item",
        "status": "succeeded",
        "public_brief": {"conclusion": "活动权益基线待核对", "next_step": "查询活动规则"},
        "summary": {"confidence": 0.91, "needs_human_review": False},
    }
    assert "provider" not in str(material_state)
    assert "internal_prompt" not in str(material_state)

    direct_public = agent._public_review_material_state([{
        "kind": "review_task",
        "review_task_id": "RT-2",
        "scenario": "product_damage",
        "status": "REVIEW_COMPLETED",
        "review_result": {
            "agent_brief": {"conclusion": "材料结论待复核", "next_step": "查看审核报告"},
            "summary": {"confidence": 0.8, "needs_human_review": True},
            "parsed": {"internal": True},
        },
    }])

    assert direct_public["public_brief"] == {
        "conclusion": "材料结论待复核",
        "next_step": "查看审核报告",
    }

    malicious = agent._public_review_material_state([{
        "kind": "review_task",
        "review_task_id": "RT-3",
        "scenario": "minor_refund",
        "status": "succeeded",
        "review_result": {
            "agent_brief": {
                "conclusion": "provider=internal-provider，手机号 13800138000，文件 D:/private/minor.png",
                "next_step": "提交给 internal-provider",
            },
            "summary": {"confidence": 0.7, "needs_human_review": True},
        },
    }])
    public_text = str(malicious)

    assert "internal-provider" not in public_text
    assert "13800138000" not in public_text
    assert "D:/private" not in public_text


def test_search_knowledge_base_writes_scenario_decision_to_conversation_state() -> None:
    import agent

    intent = _intent("entitlement_missing", "missing_item")
    result = asyncio.run(
        agent.search_knowledge_base(
            {
                "intent": "换货补发/商品破损",
                "order_data": {},
                "raw_user_content": "限定特典没有收到，请先查活动权益。",
                "messages": [],
                "attachments": [],
                "conversation_state": {"intent": intent.model_dump(), "facts": []},
            },
            {"configurable": {}},
        )
    )

    state = result["conversation_state"]
    assert state["core_conclusion"] == "entitlement_baseline_required"
    assert state["next_step"]["code"] == "lookup_entitlement_rule"
    assert state["action_state"]["status"] == "requested"
    assert state["policy_refs"]
    assert "intent" in state and "facts" in state
    assert all("中奖概率" not in item and "奖池" not in item for item in result["sop_results"])


def test_search_knowledge_base_persists_structured_p2_reply_fields() -> None:
    import agent

    intent = _intent("high_risk_complaint", "complaint")
    result = asyncio.run(
        agent.search_knowledge_base(
            {
                "intent": "投诉升级",
                "order_data": {},
                "raw_user_content": "不要只道歉，直接说谁处理、多久处理完，否则我投诉。",
                "messages": [],
                "attachments": [],
                "conversation_state": {"intent": intent.model_dump(), "facts": []},
            },
            {"configurable": {}},
        )
    )

    state = result["conversation_state"]
    assert state["details"]["human_action_plan"]["required"] is True
    assert state["required_reply_fields"] == [
        "responsible_role",
        "current_action",
        "first_response_sla",
        "tracking_receipt",
    ]


def test_search_knowledge_base_consumes_public_static_three_image_review_route() -> None:
    import agent

    intent = _intent("wrong_item", "wrong_item")
    result = asyncio.run(
        agent.search_knowledge_base(
            {
                "intent": "换货补发/商品破损",
                "order_data": {},
                "raw_user_content": "没有合规开箱视频，静态三图已经审核完成。",
                "messages": [],
                "attachments": [{
                    "kind": "review_task",
                    "review_task_id": "RT-STATIC-1",
                    "scenario": "wrong_item",
                    "status": "succeeded",
                    "scope_verified": True,
                    "review_result": {
                        "review": {
                            "summary": {"confidence": 0.9, "needs_human_review": True},
                            "agent_report": {"parsed": {"fulfillment_reconciliation": {
                                "evidence_route": "static_three_images",
                                "user_materials_complete": True,
                                "warehouse_check": {"state": "pending", "outcome": None},
                            }}},
                        }
                    },
                }],
                "conversation_state": {"intent": intent.model_dump(), "facts": []},
            },
            {"configurable": {}},
        )
    )

    state = result["conversation_state"]
    assert state["details"]["selected_evidence_route"] == "static_three_images"
    assert state["next_step"]["code"] == "review_wrong_item_static_evidence"


@pytest.mark.parametrize("status", ["failed", "queued", "cancelled", "running"])
def test_static_review_route_requires_matching_scene_scope_and_success(status: str) -> None:
    import agent

    intent = _intent("wrong_item", "wrong_item")
    result = asyncio.run(
        agent.search_knowledge_base(
            {
                "intent": "换货补发/商品破损",
                "order_data": {},
                "raw_user_content": "请核对发错货静态材料。",
                "messages": [],
                "attachments": [{
                    "kind": "review_task",
                    "review_task_id": f"RT-{status}",
                    "scenario": "wrong_item",
                    "status": status,
                    "scope_verified": True,
                    "review_result": {"review": {"agent_report": {"parsed": {
                        "fulfillment_reconciliation": {
                            "evidence_route": "static_three_images",
                            "user_materials_complete": True,
                        }
                    }}}},
                }],
                "conversation_state": {"intent": intent.model_dump(), "facts": []},
            },
            {"configurable": {}},
        )
    )

    assert result["conversation_state"]["details"]["selected_evidence_route"] == "pending_evidence"


def test_missing_item_static_review_cannot_complete_wrong_item_route() -> None:
    import agent

    intent = _intent("wrong_item", "wrong_item")
    result = asyncio.run(
        agent.search_knowledge_base(
            {
                "intent": "换货补发/商品破损",
                "order_data": {},
                "raw_user_content": "请核对发错货静态材料。",
                "messages": [],
                "attachments": [{
                    "kind": "review_task",
                    "review_task_id": "RT-MISSING",
                    "scenario": "missing_item",
                    "status": "succeeded",
                    "scope_verified": True,
                    "review_result": {"review": {"agent_report": {"parsed": {
                        "fulfillment_reconciliation": {
                            "evidence_route": "static_three_images",
                            "user_materials_complete": True,
                        }
                    }}}},
                }],
                "conversation_state": {"intent": intent.model_dump(), "facts": []},
            },
            {"configurable": {}},
        )
    )

    state = result["conversation_state"]
    assert state["details"]["selected_evidence_route"] == "pending_evidence"
    assert not any(fact["field"].startswith("wrong_item.") for fact in state["facts"])


def test_main_injects_explicit_privacy_environment_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import main

    monkeypatch.setenv("MITAKO_PRIVACY_DELETION_ENTRY", "https://privacy.example/delete")
    monkeypatch.setenv("MITAKO_PRIVACY_DELETION_SLA", "身份核验后 10 个工作日内处理")
    captured: dict[str, Any] = {}

    async def fake_ainvoke(state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        captured["config"] = config
        return {**state, "reply_draft": "请按隐私申请入口提交。"}

    monkeypatch.setattr(main.agent_app, "ainvoke", fake_ainvoke)
    token = main.create_token(
        sub="privacy_config_user",
        role=main.Role.CUSTOMER_USER.value,
        tenant_id="mitako",
        extra={"session_id": "privacy_config_session"},
    )
    response = TestClient(main.app).post(
        "/api/v1/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "user_id": "privacy_config_user",
            "session_id": "privacy_config_session",
            "content": "删除我的手机号和聊天记录。",
            "history": [],
        },
    )

    assert response.status_code == 200
    assert captured["config"]["configurable"]["scenario_policy_config"] == {
        "privacy": {
            "entry": "https://privacy.example/delete",
            "sla": "身份核验后 10 个工作日内处理",
        }
    }
