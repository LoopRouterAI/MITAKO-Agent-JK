# -*- coding: utf-8 -*-
"""Companion 服务端 Tools — 消费助理能力（盯单 / 查价 / 心愿单）"""
from __future__ import annotations

from typing import Any, Dict, List

import companion_store as store


def tool_search_products(query: str, limit: int = 8) -> Dict[str, Any]:
    products = store.search_products(query, limit=min(limit, 20))
    return {
        "ok": True,
        "tool": "search_products",
        "query": query,
        "products": products,
        "count": len(products),
    }


def tool_add_watch_order(user_id: str, order_id: str, tenant_id: str = "mitako") -> Dict[str, Any]:
    oid = (order_id or "").strip().upper()
    if not oid:
        return {"ok": False, "tool": "watch_order", "error": "empty_order_id"}
    row = store.add_watch_order(user_id, oid, tenant_id=tenant_id)
    return {"ok": True, "tool": "watch_order", "watch": row}


def tool_add_wishlist(
    user_id: str,
    product_id: str,
    note: str = "",
    tenant_id: str = "mitako",
) -> Dict[str, Any]:
    pid = (product_id or "").strip()
    if not pid:
        return {"ok": False, "tool": "add_wishlist", "error": "empty_product_id"}
    row = store.add_wishlist(user_id, pid, note=note, tenant_id=tenant_id)
    return {"ok": True, "tool": "add_wishlist", "item": row}


def tool_list_watch_orders(user_id: str, tenant_id: str = "mitako") -> Dict[str, Any]:
    orders = store.list_watch_orders(user_id, tenant_id=tenant_id)
    return {"ok": True, "tool": "list_watch_orders", "orders": orders}


def execute_tool(action: str, user_id: str, payload: Dict[str, Any], tenant_id: str = "mitako") -> Dict[str, Any]:
    """统一 Tool 入口 — 供 OpenUI 卡片回调与 E2E 调用"""
    if action == "search_products":
        return tool_search_products(payload.get("query") or "", limit=int(payload.get("limit") or 8))
    if action == "watch_order":
        return tool_add_watch_order(user_id, payload.get("order_id") or "", tenant_id=tenant_id)
    if action == "add_wishlist":
        return tool_add_wishlist(
            user_id,
            payload.get("product_id") or "",
            note=payload.get("note") or "",
            tenant_id=tenant_id,
        )
    if action == "list_watch_orders":
        return tool_list_watch_orders(user_id, tenant_id=tenant_id)
    return {"ok": False, "error": "unknown_action", "action": action}
