# -*- coding: utf-8 -*-
"""校验客服回复中的完成态和业务事实是否有公开证据。"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict

from .contracts import ActionState, ActionStatus, Fact, ReplyPlan
from .reply_plan import PUBLIC_BLOCKED_TERMS, build_reply_plan, render_reply_plan


class ReplyGuardResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed: bool
    reason_code: str = ""
    reply: str


_COMPLETED_RULES = (
    (re.compile(r"已(?:经)?上传|上传已完成"), {"material.received"}, {"material_upload"}, {ActionStatus.SUCCEEDED}),
    (re.compile(r"已(?:经)?收到|已接收(?:到)?(?:材料|附件|文件)?|已有材料接收回执"), {"material.received"}, {"material_upload"}, {ActionStatus.SUCCEEDED}),
    (re.compile(r"已(?:经)?解析|解析已完成"), {"material.parsed"}, {"material_parse", "review_material"}, {ActionStatus.SUCCEEDED}),
    (re.compile(r"已建单|(?:审核任务|工单)已创建"), {"review.job_created"}, {"review_job_create"}, {ActionStatus.QUEUED, ActionStatus.SUCCEEDED}),
    (re.compile(r"审核中|正在审核"), {"review.job_created", "review.in_progress"}, {"review_job_create", "review_material"}, {ActionStatus.QUEUED, ActionStatus.SUCCEEDED}),
    (re.compile(r"已转接|人工(?:已经|已)?(?:对接|接入|接通|转接)(?:成功|完成)|人工(?:客服)?已接手"), set(), {"human_handoff"}, {ActionStatus.SUCCEEDED}),
    (re.compile(r"已进入(?:人工)?队列"), {"handoff.queued"}, {"human_handoff"}, {ActionStatus.QUEUED, ActionStatus.SUCCEEDED}),
    (re.compile(r"已审批|审核(?:已经)?通过"), {"review.approved"}, {"review_approval"}, {ActionStatus.SUCCEEDED}),
    (re.compile(r"已退款|退款(?:处理)?(?:已)?(?:成功|完成|到账|办结)"), {"refund.completed"}, {"refund_request"}, {ActionStatus.SUCCEEDED}),
    (re.compile(r"已修改|修改已完成|地址(?:修改|变更)(?:成功|完成)|成功(?:修改|变更)地址"), {"address.changed"}, {"address_change"}, {ActionStatus.SUCCEEDED}),
    (re.compile(r"已删除|删除已完成|(?:资料|信息|记录)(?:删除|清除)(?:成功|完成)"), {"privacy.deleted"}, {"privacy_deletion"}, {ActionStatus.SUCCEEDED}),
)

_FIELD_PATTERNS = {
    "product_name": (re.compile(r"(?:商品名|商品名称)\s*[:：]\s*([^，。；\n]+)"),),
    "sku": (
        re.compile(r"SKU\s*[:：]\s*([^，。；\n]+)", re.IGNORECASE),
        re.compile(r"\bSKU\s+([-_A-Za-z0-9]+)\b", re.IGNORECASE),
    ),
    "inventory": (re.compile(r"库存(?:数量)?\s*[:：]\s*([^，。；\n]+)"),),
    "responsible_role": (
        re.compile(r"责任角色\s*[:：]\s*([^，。；\n]+)"),
        re.compile(r"(?:最终)?(?:由|交由)([^，。；\n]{1,20}?)(?:负责|处理|跟进)"),
    ),
    "current_action": (re.compile(r"当前动作\s*[:：]\s*([^，。；\n]+)"),),
    "first_response_sla": (re.compile(r"首次响应时效\s*[:：]\s*([^，。；\n]+)"),),
    "tracking_receipt": (
        re.compile(r"跟进凭证\s*[:：]\s*([^，。；\n]+)"),
        re.compile(r"(?:另一个)?(?:凭证号|回执号|跟进凭证)(?:为|是|[:：])\s*([A-Za-z0-9_-]{3,})"),
    ),
    "processing_sla": (re.compile(r"处理时效\s*[:：]\s*([^，。；\n]+)"),),
    "privacy_entry": (re.compile(r"(?:隐私申请入口|隐私入口)\s*[:：]\s*([^，。；\n]+)"),),
}
_TIME_PATTERN = re.compile(r"\d+\s*(?:分钟|小时|个?工作日|天|日|月|年)|明天|明日|后天|本周|下周|月底|\d{1,2}月\d{1,2}日|\d{4}-\d{1,2}-\d{1,2}")
_URL_PATTERN = re.compile(r"https?://[^\s，。；]+", re.IGNORECASE)
_SKU_PATTERN = re.compile(r"\bSKU[-_A-Za-z0-9]+\b", re.IGNORECASE)
_POSITIVE_STOCK_PATTERN = re.compile(r"有库存|(?:另有|还剩)?\s*[零一二三四五六七八九十百千万两\d]+\s*件(?:可售)?|库存(?:数量)?\s*[零一二三四五六七八九十百千万两\d]+\s*件|库存(?:有|为|剩余|充足)|现货(?:\s*\d+\s*件)?|缺货|预售")
_ABSOLUTE_PROMISE_PATTERN = re.compile(r"(?:保证|一定|肯定)[^，。；]{0,24}(?:发货|到货|到账|完成|响应)")
_SHIP_COMMITMENT_PATTERN = re.compile(r"(?:预计|计划|承诺)[^，。；]{0,24}发货|(?:本周|本星期|下周|下星期|月底|明天|明日|后天|\d{4}-\d{1,2}-\d{1,2}|\d{1,2}月\d{1,2}日)[^，。；]{0,12}发货")
_VAGUE_TIME_PATTERN = re.compile(r"(?:很快|马上|立即|尽快)[^，。；]{0,12}(?:处理|回复|完成|发货|退款|响应)")
_PRODUCT_NAME_PATTERN = re.compile(r"[\u4e00-\u9fffA-Za-z0-9·]{2,24}(?:徽章|吧唧|手办|立牌|色纸|挂件|卡片|特典|盲盒|周边)")
_SECRET_PATTERN = re.compile(
    r"\b(?:api[_ -]?key|key)\b\s*[:：=]|\bsk-[A-Za-z0-9_-]+|"
    r"\b(?:postgres|mysql|redis)\s+(?:timeout|error)\b|"
    r"\b\d{1,3}(?:\.\d{1,3}){3}\b|\b[a-z0-9_]+_(?:tool|service)\b|"
    r"\b(?:DeepSeek(?:-V?\d+)?|Gemini|GPT-?\d*|Claude|OpenAI|SenseNova)\b",
    re.IGNORECASE,
)
_SEMANTIC_FORBIDDEN = (
    (
        "孩子本人手机号也可以",
        re.compile(r"孩子(?:本人|自己(?:的)?|名下)(?:手机)?号[^，。；]{0,10}(?:也|同样)?(?:可以|可)(?:用|使用|接受|通过)"),
    ),
)


def _verified_facts(state: Mapping[str, Any]) -> list[Fact]:
    facts: list[Fact] = []
    for item in state.get("facts") or []:
        try:
            fact = Fact.model_validate(item)
        except Exception:
            continue
        if (
            fact.verified
            and fact.source.value != "user_statement"
            and fact.source_ref.strip()
            and bool(fact.value)
        ):
            facts.append(fact)
    return facts


def _action_state(state: Mapping[str, Any]) -> ActionState | None:
    try:
        action = ActionState.model_validate(state.get("action_state") or {})
    except Exception:
        return None
    return action


def _rule_supported(
    fact_fields: set[str],
    action_names: set[str],
    allowed_statuses: set[ActionStatus],
    facts: list[Fact],
    action: ActionState | None,
) -> bool:
    return any(fact.field in fact_fields for fact in facts) or bool(
        action
        and action.action in action_names
        and action.status in allowed_statuses
    )


def _has_unsupported_completed_action(
    text: str,
    facts: list[Fact],
    action: ActionState | None,
) -> bool:
    return any(
        pattern.search(text)
        and not _rule_supported(fact_fields, action_names, allowed_statuses, facts, action)
        for pattern, fact_fields, action_names, allowed_statuses in _COMPLETED_RULES
    )


def _evidence_safe_fallback(action: ActionState | None) -> str:
    if action and action.status == ActionStatus.FAILED:
        return "当前操作未成功，请重试或使用人工入口。"
    return "当前没有可确认的已执行结果，请补充可核验信息或使用人工入口。"


def _field_values(text: str) -> dict[str, set[str]]:
    values = {field: set() for field in _FIELD_PATTERNS}
    for field, patterns in _FIELD_PATTERNS.items():
        for pattern in patterns:
            values[field].update(match.group(1).strip() for match in pattern.finditer(text))
    values["product_name"].update(match.group(0) for match in _PRODUCT_NAME_PATTERN.finditer(text))
    return values


def _allowed_field_values(plan: ReplyPlan) -> dict[str, set[str]]:
    values = _field_values("".join(plan.must_say))
    if plan.allowed_time_commitment:
        values["first_response_sla"].add(plan.allowed_time_commitment)
        values["processing_sla"].add(plan.allowed_time_commitment)
    return values


def _unsupported_business_fact(reply: str, plan: ReplyPlan) -> bool:
    plan_text = "".join(plan.must_say)
    allowed_fields = _allowed_field_values(plan)
    reply_fields = _field_values(reply)
    for field, values in reply_fields.items():
        if any(value not in allowed_fields[field] for value in values):
            return True

    if _ABSOLUTE_PROMISE_PATTERN.search(reply) and _ABSOLUTE_PROMISE_PATTERN.search(plan_text) is None:
        return True
    if _SHIP_COMMITMENT_PATTERN.search(reply) and _SHIP_COMMITMENT_PATTERN.search(plan_text) is None:
        return True
    if _VAGUE_TIME_PATTERN.search(reply) and _VAGUE_TIME_PATTERN.search(plan_text) is None:
        return True
    if _POSITIVE_STOCK_PATTERN.search(reply) and _POSITIVE_STOCK_PATTERN.search(plan_text) is None:
        return True
    allowed_times = allowed_fields["first_response_sla"] | allowed_fields["processing_sla"]
    for match in _TIME_PATTERN.finditer(reply):
        if not any(match.group(0) in value for value in allowed_times):
            return True
    for match in _URL_PATTERN.finditer(reply):
        if match.group(0) not in allowed_fields["privacy_entry"]:
            return True
    for match in _SKU_PATTERN.finditer(reply):
        token = match.group(0).removeprefix("SKU").lstrip(" _:-")
        if token and token not in allowed_fields["sku"]:
            return True
    return False


def _has_forbidden_plan_claim(text: str, plan: ReplyPlan) -> bool:
    if any(claim and claim in text for claim in plan.must_not_say):
        return True
    return any(
        marker in plan.must_not_say and pattern.search(text)
        for marker, pattern in _SEMANTIC_FORBIDDEN
    )


def guard_reply(
    reply: str,
    *,
    conversation_state: Mapping[str, Any],
    reply_plan: ReplyPlan | Mapping[str, Any] | None = None,
) -> ReplyGuardResult:
    """冲突时返回程序模板，不再次调用模型。"""
    state = dict(conversation_state or {})
    if isinstance(reply_plan, ReplyPlan):
        plan = reply_plan
    elif isinstance(reply_plan, Mapping):
        plan = ReplyPlan.model_validate(reply_plan)
    else:
        plan = build_reply_plan(state)
    facts = _verified_facts(state)
    action = _action_state(state)
    fallback = render_reply_plan(plan)
    fallback_unsafe = (
        _has_unsupported_completed_action(fallback, facts, action)
        or any(term.lower() in fallback.lower() for term in PUBLIC_BLOCKED_TERMS)
        or bool(_SECRET_PATTERN.search(fallback))
        or _unsupported_business_fact(fallback, plan)
        or _has_forbidden_plan_claim(fallback, plan)
    )
    if fallback_unsafe:
        fallback = _evidence_safe_fallback(action)

    def rejected(reason_code: str) -> ReplyGuardResult:
        return ReplyGuardResult(
            allowed=False,
            reason_code="unsafe_reply_plan_fallback" if fallback_unsafe else reason_code,
            reply=fallback,
        )

    text = str(reply or "").strip()
    if not text:
        return rejected("empty_reply")

    lowered = text.lower()
    if any(term.lower() in lowered for term in PUBLIC_BLOCKED_TERMS) or _SECRET_PATTERN.search(text):
        return rejected("internal_text_exposure")

    if _has_unsupported_completed_action(text, facts, action):
        return rejected("unsupported_completed_action")

    if _unsupported_business_fact(text, plan):
        return rejected("unsupported_business_fact")
    if _has_forbidden_plan_claim(text, plan):
        return rejected("forbidden_reply_plan_claim")
    if any(required and required not in text for required in plan.must_say):
        return rejected("missing_required_reply_fact")
    if re.sub(r"\s+", "", text) != re.sub(r"\s+", "", fallback):
        return rejected("unexpected_reply_content")
    return ReplyGuardResult(allowed=True, reply=text)
