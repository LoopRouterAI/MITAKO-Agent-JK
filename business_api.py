# -*- coding: utf-8 -*-
"""本地演示业务服务。

这些接口只用于验证客服 Agent 的流程编排与处理建议，不连接也不写入客户真实业务系统。
"""
from __future__ import annotations

import json
import os
import socket
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from customer_service.action_state import action_envelope, action_from_tool
from runtime_paths import mock_data_file, viking_memory_dir

DATA_FILE = str(mock_data_file())
business_router = APIRouter(tags=["local-readiness-service"])


def _public_ref(value: str, prefix: str = "订单") -> str:
    raw = str(value or "").strip()
    if not raw:
        return f"{prefix} -"
    compact = "".join(ch for ch in raw if ch.isalnum())
    return f"{prefix} #{(compact or raw)[-6:].upper()}"


def _demo_meta() -> Dict[str, Any]:
    return {
        "demo_only": True,
        "real_partner_integration": False,
        "execution_mode": "local_readiness",
        "data_mode": "demo",
        "source_system": "mitako_fixture",
        "integration_status": "not_connected",
        "write_effect": "none",
    }


def _mock_action(action: str, receipt_id: str) -> Dict[str, Any]:
    state = action_from_tool(
        action,
        "business_api",
        {
            "ok": True,
            "status": "requested",
            "receipt_id": receipt_id,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "reason_code": "partner_integration_not_connected",
            **_demo_meta(),
        },
    )
    return action_envelope(state)


def load_data() -> Dict[str, Any]:
    if not os.path.exists(DATA_FILE):
        return {"users": {}, "orders": {}, "logistics": {}, "supply_chain_warnings": []}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def get_supply_chain_warnings(ip_name: Optional[str] = None) -> List[dict]:
    warnings = load_data().get("supply_chain_warnings", [])
    if ip_name:
        warnings = [item for item in warnings if ip_name in item.get("ip_name", "")]
    return warnings


def _order_priority_score(order: dict, weights: Optional[dict] = None) -> float:
    w = weights or {}
    score = 0.0
    tags = order.get("tags") or []
    if "needs_attention" in tags:
        score += float(w.get("needs_attention", 100))
    if "delay_risk" in tags:
        score += float(w.get("delay_risk", 50))
    if "had_consultation" in tags:
        score += float(w.get("had_consultation", 30))
    if "refund_history" in tags:
        score += float(w.get("refund_history", 25))
    if "lottery_win" in tags:
        score += float(w.get("lottery_win", 5))
    if "damage_claim" in tags:
        score += float(w.get("damage_claim", 75))
    if "minor_refund" in tags:
        score += float(w.get("minor_refund", 90))
    if "lottery_rule_question" in tags:
        score += float(w.get("lottery_rule_question", 70))
    if order.get("status") == "pending_shipment":
        score += float(w.get("pending_shipment", 20))
    score += float(order.get("delay_days") or 0) * float(w.get("delay_days", 0.15))
    return score


def _load_local_case(user_id: str) -> Optional[dict]:
    case_path = os.path.join(str(viking_memory_dir()), "user", user_id, "cases", "case_001.json")
    if os.path.exists(case_path):
        try:
            with open(case_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    if user_id == "usr_001":
        return {
            "title": "历史物流延期咨询",
            "detail": "用户曾因周边商品出货延期发起咨询，对官方回复时效较敏感。",
        }
    return None


@business_router.get("/api/v1/welcome/{user_id}")
def get_welcome(user_id: str, weights: Optional[str] = None):
    db = load_data()
    user = db.get("users", {}).get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")

    weight_cfg: Dict[str, Any] = {}
    if weights:
        try:
            weight_cfg = json.loads(weights)
        except json.JSONDecodeError:
            weight_cfg = {}

    user_orders = [order for order in db.get("orders", {}).values() if order.get("user_id") == user_id]
    user_orders.sort(
        key=lambda item: (_order_priority_score(item, weight_cfg), item.get("created_at") or ""),
        reverse=True,
    )
    recommended = user_orders[0] if user_orders else None
    case = _load_local_case(user_id)
    if case:
        memory_line = f"我已同步您之前的服务记录，如这次仍和「{case.get('title', '历史咨询')}」有关，可以直接告诉我。"
    elif user_orders:
        memory_line = "我也同步了您近期的订单与服务记录，您可以选订单咨询，也可以直接描述问题。"
    else:
        memory_line = ""

    order_line = ""
    reason = ""
    if recommended:
        item_name = recommended.get("items", [{}])[0].get("name", recommended.get("order_id"))
        order_line = f"我看到有一笔可能相关的订单：{_public_ref(recommended.get('order_id'))}（{item_name}）。如果要问这单，可以点下方卡片。"
        tags = recommended.get("tags") or []
        if "minor_refund" in tags:
            reason = "这笔订单涉及材料审核，我可以先帮您整理需要准备的资料。"
        elif "damage_claim" in tags:
            reason = "这笔订单涉及破损售后，我可以先帮您核对图片、开箱视频和签收节点。"
        elif "lottery_rule_question" in tags:
            reason = "如果您想核对抽选规则或结果，我可以帮您整理规则入口和复核信息。"
        elif recommended.get("delay_days", 0) > 30:
            reason = "这笔订单等待时间比较久，我可以先帮您看现在卡在哪一步。"
        elif "had_consultation" in tags:
            reason = "这笔订单之前咨询过，我可以接着帮您看最新处理进展。"
        elif "newly_shipped" in tags:
            reason = "这笔订单刚发货或刚清关，我可以帮您确认当前物流节点。"
        elif recommended.get("status") == "pending_shipment":
            if (recommended.get("delay_days") or 0) <= 3:
                reason = "这笔订单刚付款，我可以帮您确认仓库出库节奏。"
            else:
                reason = "这笔订单还在待出库状态，我可以帮您核对仓库或供应链节点。"
        else:
            reason = recommended.get("status_label") or "状态需要确认"

    greeting_map = {
        "usr_002": "您好，我是小蛟。抽奖规则、中奖结果、订单状态或售后问题，都可以直接告诉我。",
        "usr_003": "您好，我是小蛟。破损售后、补发、退款或凭证材料，我会先帮您整理清楚。",
        "usr_004": "您好，我是小蛟。您可以直接问订单物流、商品库存、地址派送或售后规则。",
        "usr_005": "您好，我是小蛟。您还没有近期订单，可以先发商品、照片或问题，我会一步步帮您确认。",
        "usr_006": "您好，我是小蛟。涉及未成年人退款、材料审核或支付凭证时，我会先帮您整理需要确认的事项。",
    }
    greeting = greeting_map.get(user_id, "您好，我是小蛟。需要查订单、售后、物流或活动规则，都可以直接告诉我。")

    return {
        **_demo_meta(),
        "greeting": greeting,
        "memory_line": memory_line,
        "order_line": order_line,
        "recommend_reason": reason,
        "recommended_order": recommended,
        "weights_applied": weight_cfg or None,
    }


@business_router.get("/api/v1/users/{user_id}")
def get_user(user_id: str):
    user = load_data().get("users", {}).get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")
    return {"user": user, **_demo_meta()}


@business_router.get("/api/v1/orders/{user_id}")
def get_orders(user_id: str, status: Optional[str] = None, sort: Optional[str] = None, weights: Optional[str] = None):
    db = load_data()
    user_orders = [order for order in db.get("orders", {}).values() if order.get("user_id") == user_id]
    if status:
        user_orders = [order for order in user_orders if order.get("status") == status]
    weight_cfg: Dict[str, Any] = {}
    if weights:
        try:
            weight_cfg = json.loads(weights)
        except json.JSONDecodeError:
            weight_cfg = {}
    if sort == "priority":
        user_orders.sort(
            key=lambda item: (_order_priority_score(item, weight_cfg), item.get("created_at") or ""),
            reverse=True,
        )
    return {"orders": user_orders, "total": len(user_orders), **_demo_meta()}


@business_router.get("/api/v1/logistics/{order_id}")
def get_logistics(order_id: str):
    log = load_data().get("logistics", {}).get(order_id)
    if not log:
        raise HTTPException(status_code=404, detail=f"Logistics info for order {order_id} not found")
    return {**log, **_demo_meta()}


@business_router.get("/api/v1/supply_chain/warnings")
def get_warnings(ip_name: Optional[str] = None):
    return {"warnings": get_supply_chain_warnings(ip_name), **_demo_meta()}


class CompensateReq(BaseModel):
    user_id: str
    order_id: str
    type: str
    amount: float
    reason: str
    agent_session_id: str
    idempotency_key: str = ""


class UrgentReq(BaseModel):
    user_id: str
    urgency_level: str
    reason: str
    agent_session_id: str


class TicketCreateReq(BaseModel):
    user_id: str
    order_id: str = ""
    category: str
    content: str
    source: str = "agent_service"
    idempotency_key: str = ""


class AfterSalesCardReq(BaseModel):
    user_id: str
    order_id: str
    card_type: str
    reason: str = ""
    amount: float = 0
    idempotency_key: str = ""


class WarehouseTaskReq(BaseModel):
    order_id: str
    task_type: str
    reason: str = ""
    priority: str = "normal"
    idempotency_key: str = ""


@business_router.post("/api/v1/compensate")
def post_compensate(req: CompensateReq):
    if req.amount > 22.0:
        raise HTTPException(status_code=400, detail="超过自动建议额度，请转VIP客服审批。")
    return {
        "ok": False,
        "success": False,
        "would_create": True,
        **_demo_meta(),
        "compensation_id": f"COMP_{req.order_id}",
        "message": f"已生成补偿申请建议：用户 {req.user_id}，订单 {req.order_id}，类型 {req.type}，金额 {req.amount}。原因：{req.reason}",
        **_mock_action("compensation", f"COMP_{req.order_id}"),
    }


@business_router.post("/api/v1/orders/{order_id}/urgent")
def post_order_urgent(order_id: str, req: UrgentReq):
    order = load_data().get("orders", {}).get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
    return {
        "ok": False,
        "success": False,
        "would_create": True,
        **_demo_meta(),
        "is_expeditable": True,
        "estimated_ship_date": "",
        "message": f"已生成加急处理建议：订单 {order_id}，级别 {req.urgency_level}。原因：{req.reason}",
        **_mock_action("order_urgent", f"URGENT_{order_id}"),
    }


@business_router.get("/api/v1/products")
def get_products(q: Optional[str] = None):
    db = load_data()
    products = list((db.get("product_catalog") or {}).values())
    seen = set()
    for item in products:
        seen.add(item.get("product_id") or item.get("name"))
    for order in db.get("orders", {}).values():
        for item in order.get("items") or []:
            item_id = item.get("item_id") or item.get("name")
            if not item_id or item_id in seen:
                continue
            seen.add(item_id)
            products.append(
                {
                    "product_id": item_id,
                    "name": item.get("name", ""),
                    "price": item.get("price", 0),
                    "support_policy": "sop_required",
                    "stock_status": "available" if order.get("status") != "pending_shipment" else "pending_shipment",
                }
            )
    if q:
        products = [item for item in products if q in item.get("name", "") or q in item.get("product_id", "")]
    return {"products": products, "total": len(products), **_demo_meta()}


@business_router.post("/api/v1/tickets")
def create_ticket(req: TicketCreateReq):
    ticket_id = f"TICKET_{abs(hash((req.user_id, req.order_id, req.category, req.content))) % 100000:05d}"
    return {
        "ok": True,
        "would_create": True,
        **_demo_meta(),
        "ticket": {
            "ticket_id": ticket_id,
            "user_id": req.user_id,
            "order_id": req.order_id,
            "category": req.category,
            "status": "ready_for_review",
            "source": req.source,
            "content": req.content,
        },
        **_mock_action("ticket", ticket_id),
    }


@business_router.get("/api/v1/tickets/{ticket_id}")
def get_ticket(ticket_id: str):
    return {
        "ok": True,
        **_demo_meta(),
        "ticket": {
            "ticket_id": ticket_id,
            "status": "ready_for_review",
            "latest_action": "等待客服根据 SOP 继续处理",
        },
    }


@business_router.post("/api/v1/after-sales/cards")
def create_after_sales_card(req: AfterSalesCardReq):
    order = load_data().get("orders", {}).get(req.order_id)
    if not order:
        raise HTTPException(status_code=404, detail=f"Order {req.order_id} not found")
    card_id = f"ASC_{req.order_id}_{req.card_type}"
    return {
        "ok": True,
        "would_create": True,
        **_demo_meta(),
        "card": {
            "card_id": card_id,
            "user_id": req.user_id,
            "order_id": req.order_id,
            "card_type": req.card_type,
            "status": "ready_for_review",
            "amount": req.amount,
            "reason": req.reason,
            "requires_user_confirm": True,
        },
        **_mock_action("after_sales_card", card_id),
    }


@business_router.post("/api/v1/warehouse/tasks")
def create_warehouse_task(req: WarehouseTaskReq):
    task_id = f"WH_{req.order_id}_{req.task_type}"
    return {
        "ok": True,
        "would_create": True,
        **_demo_meta(),
        "task": {
            "task_id": task_id,
            "order_id": req.order_id,
            "task_type": req.task_type,
            "priority": req.priority,
            "status": "ready_for_review",
            "reason": req.reason,
        },
        **_mock_action("warehouse_task", task_id),
    }


@business_router.get("/api/v1/finance/refunds/{order_id}")
def get_refund_status(order_id: str):
    order = load_data().get("orders", {}).get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
    refunded = order.get("status") == "refunded"
    return {
        "ok": True,
        **_demo_meta(),
        "refund": {
            "order_id": order_id,
            "status": "refunded" if refunded else "not_started",
            "amount": order.get("total_amount", 0) if refunded else 0,
            "channel": "original_payment",
            "eta": "3-7 个工作日" if refunded else "",
        },
    }


@business_router.get("/api/v1/multimodal/materials/{material_id}")
def get_multimodal_material(material_id: str):
    materials = {
        "damage_photo_clear": {
            "material_id": material_id,
            "type": "image_damage",
            "result": {"damage_type": "明显划痕", "confidence": 0.92, "sop": "商品有伤-初步判定"},
        },
        "unboxing_video_ok": {
            "material_id": material_id,
            "type": "video_unboxing",
            "result": {"has_unboxing_video": True, "package_opened_before_damage": False, "sop": "商品有伤-开箱视频"},
        },
        "minor_refund_material": {
            "material_id": material_id,
            "type": "minor_refund",
            "result": {"guardian_material_complete": False, "sop": "未成年人退款资料审核"},
        },
    }
    data = materials.get(material_id)
    if not data:
        raise HTTPException(status_code=404, detail="material_not_found")
    return {"ok": True, "material": data, **_demo_meta()}


if __name__ == "__main__":
    import uvicorn
    from fastapi import FastAPI

    app = FastAPI(title="MITAKO Local Readiness Service")
    app.include_router(business_router)

    def find_free_port(start_port: int) -> int:
        port = start_port
        while port < 65535:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(("127.0.0.1", port))
                    return port
                except OSError:
                    port += 1
        return start_port

    port = find_free_port(int(os.getenv("MOCK_API_PORT", "8002")))
    print(f"\n[本地演示服务] http://127.0.0.1:{port}\n")
    uvicorn.run(app, host="127.0.0.1", port=port)
