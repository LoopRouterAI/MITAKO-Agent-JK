# -*- coding: utf-8 -*-
"""Companion 消费助理意图 — 规则检测 + 结构化 payload（供 OpenUI 卡片与 Tools 使用）"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

_ORDER_ID_RE = re.compile(r"(ORD_\d{4}_\d+|ORD[A-Z0-9_-]{4,})", re.I)
_ORDER_REF_RE = re.compile(r"\[@引用订单\s+([^\]]+)\]", re.I)

_WATCH_PATTERNS = re.compile(
    r"(盯单|跟踪订单|关注物流|帮我看.{0,8}订单|订单.{0,6}(到哪|进度|状态)|物流.{0,6}提醒)",
    re.I,
)
_ORDER_CONTEXT = re.compile(r"(订单|物流|出荷|发货|到哪|进度|状态|查下|帮我看)", re.I)
_SEARCH_PATTERNS = re.compile(
    r"(查价|多少钱|什么价|有货吗|有没有|想买|搜一下|搜索|找一下|帮我找|看看有没有)",
    re.I,
)
_WISHLIST_PATTERNS = re.compile(r"(心愿单|加入清单|记下来|先收藏|想要这个)", re.I)
_PRODUCT_HINT = re.compile(r"(吧唧|手办|盲盒|谷子|周边|模型|卡牌|挂件|立牌|玩偶)")


def _extract_order_id(text: str) -> Optional[str]:
    ref = _ORDER_REF_RE.search(text or "")
    if ref:
        return ref.group(1).strip().upper()
    m = _ORDER_ID_RE.search(text or "")
    return m.group(1).upper() if m else None


def _extract_search_query(text: str) -> str:
    t = (text or "").strip()
    for prefix in ("帮我找", "搜一下", "搜索", "查一下", "找一下", "看看有没有", "有没有"):
        if prefix in t:
            idx = t.find(prefix)
            q = t[idx + len(prefix) :].strip(" ，。！？…")
            if q:
                return q[:40]
    m = _PRODUCT_HINT.search(t)
    if m:
        start = max(0, m.start() - 8)
        return t[start : m.end() + 12].strip(" ，。！？")[:40]
    return t[:40] if _SEARCH_PATTERNS.search(t) else ""


def detect_consumption_intents(text: str) -> List[Dict[str, Any]]:
    """
    返回按优先级排序的助理意图列表。
    intent: order_reference | watch_order | product_search | wishlist_hint
    """
    t = (text or "").strip()
    if not t:
        return []

    intents: List[Dict[str, Any]] = []
    order_id = _extract_order_id(t)
    has_order_ref = bool(_ORDER_REF_RE.search(t) or "引用订单" in t)

    if has_order_ref or (order_id and _ORDER_CONTEXT.search(t)):
        intents.append(
            {
                "intent": "order_reference",
                "order_id": order_id or "",
                "needs_input": not bool(order_id),
            }
        )

    if not any(i["intent"] == "order_reference" for i in intents) and (
        _WATCH_PATTERNS.search(t) or order_id
    ):
        intents.append(
            {
                "intent": "watch_order",
                "order_id": order_id or "",
                "needs_input": not bool(order_id),
            }
        )

    if _SEARCH_PATTERNS.search(t) or _PRODUCT_HINT.search(t):
        query = _extract_search_query(t)
        intents.append(
            {
                "intent": "product_search",
                "query": query,
                "needs_input": len(query) < 2,
            }
        )

    if _WISHLIST_PATTERNS.search(t):
        intents.append({"intent": "wishlist_hint", "needs_input": True})

    seen = set()
    out: List[Dict[str, Any]] = []
    for item in intents:
        key = item["intent"]
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= 3:
            break
    return out
