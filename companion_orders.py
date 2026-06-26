# -*- coding: utf-8 -*-
"""Companion 演示订单 — 独立租户数据，结构对齐 mock_data"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

_DATA_FILE = os.path.join(os.path.dirname(__file__), "mock_data.json")

# Companion 用户共用演示订单池（与 usr_001 订单镜像，user_id 映射为 companion）
_COMPANION_ORDER_IDS = ("ORD_2024_001", "ORD_2025_012", "ORD_2025_044")


def _load_db() -> dict:
    if not os.path.exists(_DATA_FILE):
        return {"orders": {}, "users": {}}
    with open(_DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def list_companion_orders(user_id: str = "") -> List[Dict[str, Any]]:
    db = _load_db()
    orders = []
    for oid in _COMPANION_ORDER_IDS:
        raw = db.get("orders", {}).get(oid)
        if not raw:
            continue
        item = dict(raw)
        item["user_id"] = user_id or item.get("user_id") or "companion_demo"
        orders.append(item)
    return orders


def get_companion_order(order_id: str) -> Optional[Dict[str, Any]]:
    needle = (order_id or "").strip().upper()
    if not needle:
        return None
    db = _load_db()
    for oid in _COMPANION_ORDER_IDS:
        if oid.upper() == needle:
            return db.get("orders", {}).get(oid)
    # 模糊匹配 mock 全库
    for ord_obj in db.get("orders", {}).values():
        if str(ord_obj.get("order_id", "")).upper() == needle:
            return ord_obj
    return None


def order_to_progress_card(order: Dict[str, Any]) -> Dict[str, Any]:
    """生成 OrderProgressCard OpenUI 数据"""
    status = order.get("status")
    progress_steps = [
        {"label": "下单", "status": "completed", "date": "2024-06-01"},
        {
            "label": "出荷",
            "status": "completed" if status != "pending_shipment" else "delayed",
            "date": "原定9月 → 延至12月" if order.get("delay_days", 0) > 0 else "已出荷",
        },
        {"label": "清关", "status": "current" if status == "pending_shipment" else "pending", "date": "进行中" if status == "pending_shipment" else "待清关"},
        {"label": "入库", "status": "pending", "date": "待入库"},
        {"label": "派送", "status": "pending", "date": "待派送"},
    ]
    if status == "delivered":
        progress_steps = [
            {"label": "下单", "status": "completed", "date": "2025-05-20"},
            {"label": "出荷", "status": "completed", "date": "已出荷"},
            {"label": "清关", "status": "completed", "date": "已清关"},
            {"label": "入库", "status": "completed", "date": "已入库"},
            {"label": "派送", "status": "completed", "date": "已妥投"},
        ]
    return {
        "order_id": order.get("order_id"),
        "item_name": order.get("items", [{}])[0].get("name") if order.get("items") else "谷子周边",
        "total_amount": order.get("total_amount"),
        "progress_steps": progress_steps,
        "delay_reason": "海关港口突击抽检查验，预计12月15日出荷完成" if order.get("delay_days", 0) > 0 else "",
    }
