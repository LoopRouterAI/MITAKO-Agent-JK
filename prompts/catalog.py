# -*- coding: utf-8 -*-
"""可由高级客服校对的业务规则目录；不包含内部安全提示词。"""
from __future__ import annotations

from typing import Any, Dict, List


RULE_CATALOG: tuple[Dict[str, Any], ...] = (
    {
        "key": "customer.service",
        "name": "用户客服业务口径",
        "category": "客服 Agent",
        "description": "补充售前、物流、售后和材料引导口径，不改变权限与隐私边界。",
        "format_hint": "按“适用条件、证据要求、明确结论、需人工情形”四部分填写。",
    },
    {
        "key": "customer.observer",
        "name": "人工接入后旁听口径",
        "category": "客服 Agent",
        "description": "补充人工接入后催进度、诉求转述和风险提醒口径。",
        "format_hint": "说明允许协助的表达、禁止越权的动作及必须转人工的条件。",
    },
    {
        "key": "visual.product_damage",
        "name": "商品有伤审核",
        "category": "视觉审核",
        "description": "校对损伤事实、视频连续性、成因与材料合规的判断口径。",
        "format_hint": "分别写明支持、反驳、证据不足和仅作风险信号的条件。",
    },
    {
        "key": "visual.wrong_item",
        "name": "发错货审核",
        "category": "视觉审核",
        "description": "校对应收商品、实收商品、规格与 SKU 的证据判断口径。",
        "format_hint": "说明订单基准、实物证据、明确错发和仍需核实的条件。",
    },
    {
        "key": "visual.missing_item",
        "name": "漏发货审核",
        "category": "视觉审核",
        "description": "校对数量、拆单、全家福、面单和仓库终核的证据优先级。",
        "format_hint": "说明可直接支持、可直接反驳、需要仓库核实和拆单例外。",
    },
    {
        "key": "visual.minor_refund",
        "name": "未成年人退款材料审核",
        "category": "视觉审核",
        "description": "校对五类材料、监护关系、签字、支付和手机号归属规则。",
        "format_hint": "逐类写明有效材料、异常材料、补件条件和必须重点复核的风险。",
    },
)

RULE_KEYS = frozenset(item["key"] for item in RULE_CATALOG)

SCENARIO_RULE_KEYS = {
    "product_damage": "visual.product_damage",
    "wrong_item": "visual.wrong_item",
    "missing_item": "visual.missing_item",
    "minor_material": "visual.minor_refund",
    "minor_refund": "visual.minor_refund",
}


def list_rule_catalog() -> List[Dict[str, Any]]:
    return [dict(item) for item in RULE_CATALOG]


def ensure_rule_key(prompt_key: str) -> str:
    normalized = str(prompt_key or "").strip()
    if normalized not in RULE_KEYS:
        raise ValueError("未知的业务规则标识")
    return normalized
