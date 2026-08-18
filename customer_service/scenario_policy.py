# -*- coding: utf-8 -*-
"""客服 P1 场景的确定性策略。"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field

from .contracts import ActionState, ActionStatus, Fact, IntentResult, NextStep


POLICY_VERSION = "MITAKO-CUSTOMER-CHAT-20260818.1"


class ScenarioDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    core_conclusion: str
    action_state: ActionState
    next_step: NextStep
    policy_refs: list[str] = Field(default_factory=list)
    resolved_product: dict[str, Any] | None = None
    privacy_entry: str = ""
    privacy_sla: str = ""


def _action(action: str, status: ActionStatus = ActionStatus.NOT_REQUESTED, reason_code: str = "") -> ActionState:
    return ActionState(action=action, status=status, reason_code=reason_code)


def _next(code: str, label: str, *, user_action_required: bool = False) -> NextStep:
    return NextStep(code=code, label=label, user_action_required=user_action_required)


def _normalized(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").lower())


def _product_records(catalog: Mapping[str, Any] | None) -> list[tuple[str, dict[str, Any]]]:
    if not isinstance(catalog, Mapping):
        return []
    return [
        (str(key), dict(value))
        for key, value in catalog.items()
        if isinstance(value, Mapping)
    ]


def _product_identifiers(product: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    for field in ("sku", "order_line_id", "order_line", "order_line_ref"):
        value = product.get(field)
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
    product_id = product.get("product_id")
    if isinstance(product_id, str) and product_id.upper().startswith("SKU-"):
        values.extend([product_id.strip(), product_id.strip()[4:]])
    for variant in product.get("variants") or []:
        if isinstance(variant, Mapping) and isinstance(variant.get("sku"), str):
            values.append(str(variant["sku"]).strip())
    return list(dict.fromkeys(value for value in values if value))


def _product_urls(product: Mapping[str, Any]) -> list[str]:
    return [
        value.strip()
        for field in ("product_url", "url")
        if isinstance((value := product.get(field)), str) and value.strip()
    ]


def _has_exact_token(text: str, token: str) -> bool:
    return bool(re.search(
        rf"(?<![0-9A-Za-z_-]){re.escape(token)}(?![0-9A-Za-z_-])",
        text,
        flags=re.IGNORECASE,
    ))


def _canonical_url(value: str) -> str:
    parsed = urlsplit(str(value or "").strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return ""
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, parsed.query, ""))


def resolve_unique_product(message: str, catalog: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """仅通过明确标识或唯一完整商品名解析商品。"""
    text = str(message or "")
    normalized_text = _normalized(text)
    token_text = re.sub(r"https?://[^\s，。；！？]+", " ", text, flags=re.IGNORECASE)
    message_urls = {
        canonical
        for match in re.finditer(r"https?://[^\s，。；！？]+", text, flags=re.IGNORECASE)
        if (canonical := _canonical_url(match.group(0)))
    }
    identifier_matches: list[dict[str, Any]] = []
    name_matches: list[dict[str, Any]] = []

    for _, product in _product_records(catalog):
        if any(_has_exact_token(token_text, identifier) for identifier in _product_identifiers(product)) or any(
            _canonical_url(url) in message_urls for url in _product_urls(product)
        ):
            identifier_matches.append(product)
            continue
        name = _normalized(product.get("name"))
        if name and name in normalized_text:
            name_matches.append(product)

    matches = identifier_matches or name_matches
    return matches[0] if len(matches) == 1 else None


def _fact_values(facts: Sequence[Fact | Mapping[str, Any]], field: str) -> list[Any]:
    values: list[Any] = []
    for item in facts:
        fact = item if isinstance(item, Fact) else Fact.model_validate(item)
        if fact.field == field:
            values.append(fact.value)
    return values


def _verified_material_received(facts: Sequence[Fact | Mapping[str, Any]]) -> bool:
    for item in facts:
        fact = item if isinstance(item, Fact) else Fact.model_validate(item)
        if fact.field == "material.received" and fact.value is True and fact.verified:
            return True
    return False


def _minor_mobile_owner(message: str, facts: Sequence[Fact | Mapping[str, Any]]) -> str:
    roles = {
        str(value or "").strip().lower()
        for field in ("mobile.owner_role", "mobile_owner_role", "minor.mobile_owner_role")
        for value in _fact_values(facts, field)
    }
    if roles & {"minor", "child", "underage", "self_minor"}:
        return "minor"
    if roles & {"guardian", "parent", "legal_guardian", "father", "mother"}:
        return "guardian"

    text = str(message or "")
    if any(term in text for term in (
        "孩子本人手机号",
        "未成年人本人手机号",
        "未成年人自己的号码",
        "小孩自己的手机号",
        "手机号归属人是小孩本人",
        "孩子名下手机号",
        "未成年人名下手机号",
    )):
        return "minor"
    if any(term in text for term in (
        "监护人本人手机号",
        "监护人本人实名",
        "家长本人手机号",
        "家长本人实名",
        "父亲实名手机号",
        "母亲实名手机号",
    )):
        return "guardian"
    return "unknown"


def _privacy_config(config: Mapping[str, Any] | None) -> tuple[str, str]:
    privacy = config.get("privacy") if isinstance(config, Mapping) else None
    if not isinstance(privacy, Mapping):
        return "", ""
    entry = privacy.get("entry")
    sla = privacy.get("sla")
    return (
        str(entry).strip() if isinstance(entry, str) else "",
        str(sla).strip() if isinstance(sla, str) else "",
    )


def decide_scenario(
    *,
    intent: IntentResult,
    facts: Sequence[Fact | Mapping[str, Any]],
    message: str,
    action: ActionState | None = None,
    config: Mapping[str, Any] | None = None,
    catalog: Mapping[str, Any] | None = None,
    activity: Mapping[str, Any] | None = None,
) -> ScenarioDecision:
    """按优先意图返回可序列化的确定性场景决策。"""
    del activity  # 本轮只要求先查活动权益，不能用抽奖字段替代权益基线。
    code = intent.intent_code

    if code == "minor_refund_material":
        if _minor_mobile_owner(message, facts) == "minor":
            return ScenarioDecision(
                core_conclusion="child_mobile_invoice_not_acceptable",
                action_state=_action("minor_refund_material"),
                next_step=_next(
                    "request_guardian_mobile_proof",
                    "补充监护人本人手机号实名归属证明",
                    user_action_required=True,
                ),
                policy_refs=[f"{POLICY_VERSION}/minor-mobile-owner"],
            )
        return ScenarioDecision(
            core_conclusion="minor_materials_require_verification",
            action_state=_action("minor_refund_material"),
            next_step=_next("review_minor_refund_materials", "核对未成年人退款材料"),
            policy_refs=[f"{POLICY_VERSION}/minor-material-verification"],
        )

    if code == "product_consultation":
        product = resolve_unique_product(message, catalog)
        if product is None:
            return ScenarioDecision(
                core_conclusion="product_identity_ambiguous",
                action_state=_action("product_lookup"),
                next_step=_next(
                    "request_product_identity",
                    "提供商品 SKU、链接或订单行",
                    user_action_required=True,
                ),
                policy_refs=[f"{POLICY_VERSION}/unique-product-identity"],
            )
        return ScenarioDecision(
            core_conclusion="product_identity_resolved",
            action_state=_action("product_lookup", ActionStatus.REQUESTED, "verified_product_lookup_required"),
            next_step=_next("show_verified_product_facts", "展示已匹配商品事实"),
            policy_refs=[f"{POLICY_VERSION}/unique-product-identity"],
            resolved_product=product,
        )

    if code == "entitlement_missing":
        return ScenarioDecision(
            core_conclusion="entitlement_baseline_required",
            action_state=_action(
                "entitlement_lookup",
                ActionStatus.REQUESTED,
                "entitlement_baseline_required",
            ),
            next_step=_next("lookup_entitlement_rule", "先查询活动权益基线"),
            policy_refs=[f"{POLICY_VERSION}/entitlement-baseline"],
        )

    if code == "product_damage" and not _verified_material_received(facts):
        return ScenarioDecision(
            core_conclusion="material_not_received",
            action_state=_action("material_upload"),
            next_step=_next("upload_materials", "上传本轮待审核材料", user_action_required=True),
            policy_refs=[f"{POLICY_VERSION}/material-receipt"],
        )
    if code == "product_damage":
        return ScenarioDecision(
            core_conclusion="material_received",
            action_state=_action("review_material"),
            next_step=_next("review_received_materials", "按已接收材料继续审核"),
            policy_refs=[f"{POLICY_VERSION}/material-receipt"],
        )

    if code == "address_change":
        current = action if action and action.action == "address_change" else _action("address_change")
        if current.status == ActionStatus.FAILED:
            next_step = _next("show_retry_and_human_entry", "显示重试与人工入口")
        elif current.status == ActionStatus.SUCCEEDED:
            return ScenarioDecision(
                core_conclusion="address_change_succeeded",
                action_state=current,
                next_step=_next("show_address_change_receipt", "显示地址修改回执"),
                policy_refs=[f"{POLICY_VERSION}/address-action-receipt"],
            )
        elif current.status == ActionStatus.NOT_REQUESTED:
            next_step = _next("request_address_change_tool", "调用地址修改工具")
        else:
            next_step = _next("show_address_change_pending", "显示地址修改处理状态")
        return ScenarioDecision(
            core_conclusion="address_change_requires_tool",
            action_state=current,
            next_step=next_step,
            policy_refs=[f"{POLICY_VERSION}/address-action-receipt"],
        )

    if code == "privacy_deletion":
        entry, sla = _privacy_config(config)
        configured = bool(entry and sla)
        return ScenarioDecision(
            core_conclusion="privacy_verification_required",
            action_state=_action("privacy_deletion"),
            next_step=_next(
                "show_configured_privacy_entry" if configured else "show_privacy_human_entry",
                "显示已配置的隐私申请入口" if configured else "转人工确认隐私申请入口",
            ),
            policy_refs=[f"{POLICY_VERSION}/privacy-explicit-config"],
            privacy_entry=entry if configured else "",
            privacy_sla=sla if configured else "",
        )

    return ScenarioDecision(
        core_conclusion="scenario_policy_not_applicable",
        action_state=action or _action(code or "none"),
        next_step=_next("continue_existing_flow", "继续现有服务流程"),
    )
