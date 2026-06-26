# -*- coding: utf-8 -*-
"""Companion 模式检测 — 兼职客服子模式触发"""
from __future__ import annotations

import re

_CS_KEYWORDS = re.compile(
    r"(退款|退货|物流|破损|投诉|售后|工单|没发货|延迟|赔偿|补偿|黑猫|客服介入)",
    re.I,
)


def detect_cs_parttime_intent(text: str) -> bool:
    """用户消息是否应切换为 cs_parttime 子模式"""
    return bool(_CS_KEYWORDS.search((text or "").strip()))
