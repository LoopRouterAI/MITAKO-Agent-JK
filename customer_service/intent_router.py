# -*- coding: utf-8 -*-
"""客服消息的确定性意图路由。"""
from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from .contracts import IntentResult


RULES = (
    ("privacy_deletion", "privacy_compliance", ("删除手机号", "删除身份证", "删除聊天记录", "全部聊天记录", "注销隐私")),
    ("address_change", "order_change", ("修改收货地址", "修改地址", "改收货地址", "改地址", "填错了收货地址", "填错地址")),
    ("human_handoff", "human_handoff", ("转人工", "人工客服", "真人客服", "VIP客服", "找人工", "不想和机器人")),
    ("high_risk_complaint", "complaint", ("12315", "投诉", "起诉", "黑猫", "曝光", "谁处理", "多久处理")),
    ("notification_channel", "notification_channel", ("电话提醒", "电话通知", "打电话", "来电", "电话联系", "手机提醒", "短信提醒")),
    ("minor_refund_material", "minor_refund", ("未成年人", "未成年", "孩子", "小孩", "家长", "监护人", "监护关系", "户口本", "承诺书")),
    ("wrong_item", "wrong_item", ("发错", "错货", "收到的是另一个", "另一个角色", "不是买的", "串单", "串了")),
    ("entitlement_missing", "missing_item", ("赠品", "特典", "满赠", "随单赠")),
    ("missing_item", "missing_item", ("漏发", "少发", "少了", "缺件", "应有", "实收")),
    ("product_damage", "product_damage", ("有伤", "划痕", "破损", "瑕疵", "烂了", "特写照片")),
    ("product_consultation", "product_consultation", ("库存", "直径", "尺寸", "规格", "发货时间", "SKU", "sku", "现货", "预售", "想买", "支付方式")),
    ("refund_progress", "refund_progress", ("退款", "退钱", "退费", "退款进度", "退款到哪", "多久到账")),
    ("order_logistics", "order_logistics", ("物流", "运输途中", "发货到哪", "发货进度", "催发货", "出库", "清关", "通关", "仓库", "第二笔订单", "引用订单")),
    ("refund_compensation", "refund_progress", ("补偿", "赔偿", "免邮")),
    ("lottery_rule", "lottery_rule", ("盲盒", "概率", "重复抽", "保底", "奖池", "抽号", "抽赏", "抽选", "中奖率", "中奖名单", "活动规则")),
    ("lottery_exchange", "lottery_rule", ("置换区", "交换")),
    ("casual_chat", "casual_chat", ("你好", "您好", "在吗", "谢谢", "感谢", "哈哈")),
)


PUBLIC_LABELS = {
    "privacy_deletion": "隐私合规/资料删除",
    "address_change": "订单信息/地址修改",
    "human_handoff": "VIP客服请求",
    "high_risk_complaint": "投诉升级",
    "notification_channel": "通知渠道/服务建议",
    "minor_refund_material": "退款退货/未成年人退款",
    "wrong_item": "换货补发/商品破损",
    "entitlement_missing": "换货补发/商品破损",
    "missing_item": "换货补发/商品破损",
    "product_damage": "换货补发/商品破损",
    "product_consultation": "售前商品咨询",
    "refund_progress": "退款退货/申请退款",
    "order_logistics": "物流追踪/催发货",
    "refund_compensation": "退款退货/补偿",
    "lottery_rule": "盲盒相关/吞烫质疑",
    "lottery_exchange": "盲盒相关/置换区咨询",
    "casual_chat": "闲聊互动",
}


def _rule_evidence(text: str, intent: str, phrases: tuple[str, ...]) -> list[str]:
    evidence = [phrase for phrase in phrases if phrase in text]
    if intent == "entitlement_missing" and not any(
        phrase in text for phrase in ("没有", "没收到", "未收到", "漏发", "少了", "缺少")
    ):
        return []
    return evidence


def route_intent(message: str, history: Sequence[dict[str, Any]] | None = None) -> IntentResult:
    """按固定优先级返回本轮主意图及首要业务场景。"""
    text = str(message or "").strip()
    matches = [
        (intent, scenario, evidence)
        for intent, scenario, phrases in RULES
        if (evidence := _rule_evidence(text, intent, phrases))
    ]

    count_match = re.search(r"应有\s*\d+.*?实收\s*\d+", text)
    if count_match and not any(intent == "missing_item" for intent, _, _ in matches):
        matches.append(("missing_item", "missing_item", [count_match.group(0)]))
        matches.sort(key=lambda item: next(index for index, rule in enumerate(RULES) if rule[0] == item[0]))

    if not matches:
        return IntentResult(
            intent_code="casual_chat",
            scenario_code="casual_chat",
            confidence=0.3,
            requires_clarification=True,
            clarification_fields=["request"],
        )

    intent_code, scenario_code, evidence = matches[0]
    if intent_code == "human_handoff":
        refund_match = next((item for item in matches if item[0] == "refund_progress"), None)
        if refund_match:
            scenario_code = refund_match[1]
            evidence = evidence + refund_match[2]

    clarification_fields: list[str] = []
    if intent_code == "product_consultation" and any(
        phrase in text for phrase in ("没有商品链接", "没有链接", "没商品链接", "没链接")
    ):
        clarification_fields.append("product_identity")

    unique_evidence = list(dict.fromkeys(evidence))
    return IntentResult(
        intent_code=intent_code,
        scenario_code=scenario_code,
        confidence=min(0.99, 0.9 + 0.02 * len(unique_evidence)),
        matched_evidence=unique_evidence,
        requires_clarification=bool(clarification_fields),
        clarification_fields=clarification_fields,
    )


def public_intent_label(result: IntentResult) -> str:
    return PUBLIC_LABELS[result.intent_code]
