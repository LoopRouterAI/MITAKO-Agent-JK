# -*- coding: utf-8 -*-
"""把确定性客服状态投影成可公开回复计划。"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .contracts import ActionState, ActionStatus, Fact, NextStep, ReplyPlan


PUBLIC_BLOCKED_TERMS = (
    "咪好",
    "模型",
    "API Key",
    "Prompt",
    "演示数据",
    "演示口径",
    "外包",
    "调试参数",
    "内部提示",
)

COMPLETED_CLAIMS = (
    "已上传",
    "已收到",
    "已解析",
    "已建单",
    "审核中",
    "已转接",
    "已进入队列",
    "已审批",
    "已退款",
    "已修改",
    "已删除",
)

_FORBIDDEN_BY_CONCLUSION = {
    "child_mobile_invoice_not_acceptable": ("孩子本人手机号也可以", "审核通过", "已建单"),
    "product_identity_ambiguous": ("排球少年", "库存有", "预计发货"),
    "entitlement_baseline_required": ("中奖概率", "奖池", "抽号"),
    "material_not_received": ("已收到", "已上传", "已建单", "审核中"),
    "wrong_item_materials_required": ("开箱视频可选", "闲聊互动"),
    "missing_item_evidence_required": ("闲聊互动", "无法确认数量"),
    "missing_item_order_association_required": ("闲聊互动", "无法确认数量"),
    "handoff_receipt_required": ("已转接",),
    "complaint_protocol_required": ("请耐心等待", "很快处理"),
    "address_change_requires_tool": ("已修改", "请刷新页面"),
    "privacy_verification_required": ("账号换绑", "闲聊互动", "已删除"),
    "published_rule_required": ("概率一定不变", "绝对随机"),
    "show_verified_logistics_node": ("已丢件", "已退款"),
    "order_selection_required": ("没有订单权限", "查询的是第一笔订单"),
    "guardianship_chain_not_established": ("可以证明", "资料齐全"),
    "show_verified_order_progress": ("海关新政", "保证明天发货"),
}
_INTERNAL_FACT_FIELD = re.compile(r"(?:^|[._-])(?:error|exception|reason|raw|debug|internal)(?:$|[._-])", re.IGNORECASE)
_INTERNAL_FACT_VALUE = re.compile(
    r"\b(?:postgres|mysql|redis)\s+(?:timeout|error)\b|\bsk-[A-Za-z0-9_-]+|"
    r"\b\d{1,3}(?:\.\d{1,3}){3}\b",
    re.IGNORECASE,
)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _action(data: Mapping[str, Any]) -> ActionState:
    raw = _mapping(data.get("action_state"))
    try:
        return ActionState.model_validate(raw)
    except Exception:
        return ActionState(
            action=str(raw.get("action") or "none"),
            status=ActionStatus.FAILED if raw else ActionStatus.NOT_REQUESTED,
            reason_code="invalid_action_state" if raw else "",
        )


def _next_step(data: Mapping[str, Any]) -> NextStep:
    raw = _mapping(data.get("next_step"))
    try:
        return NextStep.model_validate(raw)
    except Exception:
        return NextStep(
            code="request_clarification",
            label="补充可核验信息后继续处理",
            user_action_required=True,
        )


def _verified_facts(data: Mapping[str, Any]) -> list[Fact]:
    facts: list[Fact] = []
    for item in data.get("facts") or []:
        try:
            fact = Fact.model_validate(item)
        except Exception:
            continue
        if fact.verified and fact.source.value != "user_statement" and fact.source_ref.strip():
            facts.append(fact)
    return facts


def _unsupported_completed_claims(facts: list[Fact], action: ActionState) -> list[str]:
    verified_fields = {fact.field for fact in facts if bool(fact.value)}
    allowed: set[str] = set()
    if "material.received" in verified_fields:
        allowed.update({"已上传", "已收到"})
    if "material.parsed" in verified_fields:
        allowed.add("已解析")
    if "review.job_created" in verified_fields:
        allowed.update({"已建单", "审核中"})
    if "handoff.queued" in verified_fields:
        allowed.update({"已转接", "已进入队列"})
    if "review.approved" in verified_fields:
        allowed.add("已审批")
    if "refund.completed" in verified_fields:
        allowed.add("已退款")
    if "address.changed" in verified_fields:
        allowed.add("已修改")
    if "privacy.deleted" in verified_fields:
        allowed.add("已删除")

    if action.status in {ActionStatus.QUEUED, ActionStatus.SUCCEEDED}:
        allowed.update({
            "review_job_create": {"已建单", "审核中"},
            "review_material": {"审核中"},
            "human_handoff": {"已进入队列"},
        }.get(action.action, set()))
    if action.status == ActionStatus.SUCCEEDED:
        allowed.update({
            "material_upload": {"已上传", "已收到"},
            "material_parse": {"已解析"},
            "review_material": {"已解析"},
            "human_handoff": {"已转接", "已进入队列"},
            "review_approval": {"已审批"},
            "refund_request": {"已退款"},
            "address_change": {"已修改"},
            "privacy_deletion": {"已删除"},
        }.get(action.action, set()))
    return [claim for claim in COMPLETED_CLAIMS if claim not in allowed]


def _decision(data: Mapping[str, Any]) -> dict[str, Any]:
    return _mapping(data.get("scenario_decision")) or dict(data)


def _intent_code(data: Mapping[str, Any]) -> str:
    intent = _mapping(data.get("intent"))
    codes = [str(intent.get("intent_code") or ""), *(intent.get("intent_codes") or [])]
    for preferred in ("high_risk_complaint", "lottery_rule", "order_logistics", "minor_refund_material"):
        if preferred in codes:
            return preferred
    return next((code for code in codes if code), "")


def _privacy_lines(decision: Mapping[str, Any]) -> tuple[list[str], str | None]:
    entry = str(decision.get("privacy_entry") or "").strip()
    sla = str(decision.get("privacy_sla") or "").strip()
    if entry and sla:
        return [f"隐私申请入口：{entry}。", f"处理时效：{sla}。"], sla
    return ["当前没有可公开确认的隐私申请入口或处理时效，请通过人工入口核对。"], None


def _complaint_lines(
    decision: Mapping[str, Any],
    action: ActionState,
    public_config: Mapping[str, Any],
) -> tuple[list[str], str | None]:
    details = _mapping(decision.get("details"))
    configured = _mapping(details.get("complaint_protocol"))
    configured.update(_mapping(public_config.get("complaint_protocol")))
    role = str(configured.get("responsible_role") or "客服主管").strip()
    sla = str(configured.get("first_response_sla") or "").strip()

    if action.status in {ActionStatus.QUEUED, ActionStatus.SUCCEEDED}:
        current_action = "已进入人工队列并同步投诉简报"
        receipt = action.receipt_id
    elif action.status == ActionStatus.FAILED:
        current_action = "尚未进入人工队列，请重试或使用人工入口"
        receipt = "暂无有效队列回执"
    else:
        current_action = "正在申请人工接入并同步投诉简报"
        receipt = "等待人工队列回执"

    lines = [
        f"责任角色：{role}。",
        f"当前动作：{current_action}。",
        f"首次响应时效：{sla or '进入队列后以公开服务配置为准'}。",
        f"跟进凭证：{receipt}。",
    ]
    return lines, sla or None


def _product_lines(decision: Mapping[str, Any]) -> list[str]:
    product = _mapping(decision.get("resolved_product"))
    name = str(product.get("name") or "").strip()
    sku = str(product.get("sku") or product.get("product_id") or "").strip()
    if not name and not sku:
        return ["当前无法唯一确认具体商品，请提供商品 SKU、商品链接或订单行；在此之前不能提供商品名、库存或发货时间结论。"]
    identity = "，".join(value for value in (name, f"SKU {sku}" if sku else "") if value)
    return [f"当前唯一匹配的商品标识为：{identity}。", "库存和发货时间仍需以商品服务的可核验结果为准。"]


def _template_lines(
    conclusion: str,
    decision: Mapping[str, Any],
    action: ActionState,
    public_config: Mapping[str, Any],
) -> tuple[list[str], str | None]:
    if conclusion == "child_mobile_invoice_not_acceptable":
        return ["孩子本人手机号的实名归属材料不能替代监护人本人手机号证明，需要补充监护人本人手机号实名归属证明。"], None
    if conclusion == "minor_materials_require_verification":
        return [
            "未成年人退款材料需要逐项核对：监护人与未成年人身份证明、监护关系证明、双方亲笔签名的退款承诺书、订单/支付凭证、绑定手机号实名归属证明。",
            "运营商材料需包含可与平台账号比对的业务手机号，支付截图不能替代手机号归属证明；最终由VIP客服终审。",
        ], None
    if conclusion == "product_identity_ambiguous":
        return _product_lines({}), None
    if conclusion == "product_identity_resolved":
        return _product_lines(decision), None
    if conclusion == "entitlement_baseline_required":
        return ["需要先核对活动权益基线，确认该特典是否属于应发内容，再确定漏发证据。"], None
    if conclusion == "material_not_received":
        return ["当前没有附件服务的接收回执，请先在本轮会话上传待审核材料。"], None
    if conclusion == "material_received":
        return ["附件服务已有材料接收回执；是否解析、建单或进入审核仍以对应状态回执为准。"], None
    if conclusion == "wrong_item_materials_required":
        return ["发错货的核心证据是合规连续开箱视频；没有合规视频时，可补充实收商品全景、绿色袋或商品包装视图、匹配面单三项静态证据。"], None
    if conclusion.startswith("expected_") and "_received_" in conclusion:
        match = re.fullmatch(r"expected_(\d+)_received_(\d+)", conclusion)
        if match:
            expected, received = match.groups()
            return [f"当前陈述为应发 {expected} 件、实收 {received} 件，需要继续核对订单、包裹和实收清单证据。"], None
    if conclusion in {"missing_item_evidence_required", "missing_item_order_association_required"}:
        return ["需要先关联订单和包裹，再核对应发数量、实收数量和缺失 SKU。"], None
    if conclusion == "handoff_receipt_required":
        if action.status in {ActionStatus.QUEUED, ActionStatus.SUCCEEDED}:
            return [f"已进入人工队列，跟进凭证：{action.receipt_id}。"], None
        if action.status == ActionStatus.FAILED:
            return ["尚未进入人工队列，请重试或使用人工入口。"], None
        return ["正在申请人工接入，当前仍在等待队列回执。"], None
    if conclusion == "complaint_protocol_required":
        return _complaint_lines(decision, action, public_config)
    if conclusion == "address_change_succeeded":
        return [f"收货地址已修改，处理凭证：{action.receipt_id}。"], None
    if conclusion == "address_change_requires_tool":
        if action.status == ActionStatus.FAILED:
            return ["收货地址修改未成功，请根据失败状态重试或使用人工入口。"], None
        return ["收货地址是否可修改需要调用地址工具确认，当前没有完成回执。"], None
    if conclusion == "privacy_verification_required":
        return _privacy_lines(decision)
    if conclusion == "published_rule_required":
        return ["抽选规则需要以活动公示规则和可复核记录为准，当前不能据此断定概率变化或人工干预。"], None
    if conclusion == "show_verified_logistics_node":
        return ["订单仍在运输途中，当前节点只按物流服务的已核验结果展示。"], None
    if conclusion == "order_selection_required":
        return ["当前需要先选择第二笔订单，避免把第一笔订单的状态当成本次查询结果。"], None
    if conclusion == "guardianship_chain_not_established":
        return ["分列在两本户口本的现有材料不能直接建立完整监护关系链，需要补充出生证明或合法监护证明。"], None
    if conclusion == "show_verified_order_progress":
        return ["订单进度只按订单和物流服务的已核验节点展示，当前不作具体发货日期承诺。"], None
    if conclusion == "order_progress_requires_verification":
        return ["理解长时间等待会让人焦虑；订单和物流进度需要按订单与物流服务的可核验节点核对，当前不作无回执结论。"], None
    if action.status == ActionStatus.FAILED:
        return ["当前操作未成功，请按下一步入口重试或转人工核对。"], None
    return ["当前没有可确认的已执行结果，请按下一步补充或核对信息。"], None


def build_reply_plan(
    conversation_state: Mapping[str, Any],
    *,
    public_config: Mapping[str, Any] | None = None,
) -> ReplyPlan:
    """只使用公开确定性状态生成回复计划。"""
    state = _mapping(conversation_state)
    decision = _decision(state)
    action = _action(state)
    next_step = _next_step(state)
    facts = _verified_facts(state)
    conclusion = str(state.get("core_conclusion") or decision.get("core_conclusion") or "").strip()
    verified_true_fields = {fact.field for fact in facts if bool(fact.value)}
    if conclusion == "material_received" and "material.received" not in verified_true_fields:
        conclusion = "material_not_received"
        next_step = NextStep(
            code="upload_materials",
            label="上传本轮待审核材料",
            user_action_required=True,
        )
    if conclusion == "address_change_succeeded" and action.status != ActionStatus.SUCCEEDED:
        conclusion = "address_change_requires_tool"
        next_step = NextStep(
            code="show_retry_and_human_entry" if action.status == ActionStatus.FAILED else "request_address_change_tool",
            label="显示重试与人工入口" if action.status == ActionStatus.FAILED else "调用地址修改工具",
        )
    if conclusion in {"show_verified_logistics_node", "show_verified_order_progress"} and action.status != ActionStatus.SUCCEEDED:
        conclusion = "order_progress_requires_verification"
    if conclusion in {"", "scenario_policy_not_applicable"}:
        conclusion = {
            "lottery_rule": "published_rule_required",
            "order_logistics": "order_progress_requires_verification",
            "minor_refund_material": "minor_materials_require_verification",
        }.get(_intent_code(state), conclusion)
    lines, allowed_time = _template_lines(conclusion, decision, action, _mapping(public_config))
    must_not_say = [
        *PUBLIC_BLOCKED_TERMS,
        *_unsupported_completed_claims(facts, action),
        *_FORBIDDEN_BY_CONCLUSION.get(conclusion, ()),
    ]
    if conclusion.startswith("expected_") and "_received_" in conclusion:
        must_not_say.extend(("闲聊互动", "无法确认数量"))
    return ReplyPlan(
        facts=facts,
        must_say=lines,
        must_not_say=list(dict.fromkeys(must_not_say)),
        action=action,
        next_step=next_step,
        allowed_time_commitment=allowed_time,
    )


def render_reply_plan(plan: ReplyPlan) -> str:
    """渲染不依赖模型的安全回复。"""
    lines = [str(item).strip() for item in plan.must_say if str(item).strip()]
    next_label = plan.next_step.label.strip()
    if next_label and all(next_label not in line for line in lines):
        lines.append(f"下一步：{next_label}。")
    return "".join(lines)


def public_reply_plan_payload(plan: ReplyPlan) -> dict[str, Any]:
    """生成提供给模型的公开投影，排除工具实现和原始错误。"""
    action = {
        "action": plan.action.action,
        "status": plan.action.status.value,
    }
    if plan.action.status in {ActionStatus.QUEUED, ActionStatus.SUCCEEDED}:
        action["receipt_id"] = plan.action.receipt_id
    return {
        "facts": [
            {"field": fact.field, "value": fact.value}
            for fact in plan.facts
            if not _INTERNAL_FACT_FIELD.search(fact.field)
            and not _INTERNAL_FACT_VALUE.search(str(fact.value))
        ],
        "must_say": list(plan.must_say),
        "must_not_say": [
            claim for claim in plan.must_not_say
            if claim not in PUBLIC_BLOCKED_TERMS
        ],
        "action": action,
        "next_step": plan.next_step.model_dump(mode="json"),
        "allowed_time_commitment": plan.allowed_time_commitment,
    }
