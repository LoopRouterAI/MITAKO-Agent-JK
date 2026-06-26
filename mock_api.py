# -*- coding: utf-8 -*-
import json
import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional

# 数据文件路径
DATA_FILE = os.path.join(os.path.dirname(__file__), "mock_data.json")

mock_router = APIRouter(tags=["mock-business"])


def load_data():
    if not os.path.exists(DATA_FILE):
        return {"users": {}, "orders": {}, "logistics": {}, "supply_chain_warnings": []}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def get_supply_chain_warnings(ip_name: Optional[str] = None) -> List[dict]:
    """供 agent 进程内直接调用，避免 HTTP 端口冲突"""
    warnings = load_data().get("supply_chain_warnings", [])
    if ip_name:
        warnings = [w for w in warnings if ip_name in w.get("ip_name", "")]
    return warnings


def _order_priority_score(order: dict, weights: Optional[dict] = None) -> float:
    """演示排序：异常/咨询/延误订单优先展示（权重可配置）"""
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
    if order.get("status") == "pending_shipment":
        score += float(w.get("pending_shipment", 20))
    score += float(order.get("delay_days") or 0) * float(w.get("delay_days", 0.15))
    return score


def _load_viking_case(user_id: str) -> Optional[dict]:
    """读取演示用 Viking 纠纷案例（与 agent MockOpenViking 初始化一致）"""
    case_path = os.path.join(os.path.dirname(__file__), "viking_memory", "user", user_id, "cases", "case_001.json")
    if os.path.exists(case_path):
        try:
            with open(case_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    if user_id == "usr_001":
        return {
            "title": "2024年6月排球周边出荷延期客诉",
            "detail": "曾因排球少年周边出荷延期发起咨询，对官方腔回复较敏感。",
        }
    return None


@mock_router.get("/api/v1/welcome/{user_id}")
def get_welcome(user_id: str, weights: Optional[str] = None):
    """个性化欢迎语 + 推荐咨询订单（权重可由运行态面板传入 JSON）"""
    db = load_data()
    user = db.get("users", {}).get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")

    weight_cfg = {}
    if weights:
        try:
            weight_cfg = json.loads(weights)
        except json.JSONDecodeError:
            weight_cfg = {}

    user_orders = [ord for ord in db.get("orders", {}).values() if ord.get("user_id") == user_id]
    user_orders.sort(
        key=lambda o: (_order_priority_score(o, weight_cfg), o.get("created_at") or ""),
        reverse=True,
    )
    recommended = user_orders[0] if user_orders else None
    case = _load_viking_case(user_id)
    nickname = user.get("nickname", "谷友")
    member_label = user.get("member_label") or user.get("member_level", "")

    memory_line = ""
    if case:
        memory_line = f"记得您之前关于「{case.get('title', '历史咨询')}」的事，我一直有帮您留意着。"
    elif user_orders:
        memory_line = f"欢迎回来，{nickname}。我已同步您近期的订单与服务记录。"

    order_line = ""
    reason = ""
    if recommended:
        item_name = recommended.get("items", [{}])[0].get("name", recommended.get("order_id"))
        order_line = f"刚帮您查了订单库，#{recommended.get('order_id')}（{item_name}）目前最需要跟进。"
        if recommended.get("delay_days", 0) > 30:
            reason = f"该单已延误约 {recommended.get('delay_days')} 天"
        elif "had_consultation" in (recommended.get("tags") or []):
            reason = "系统记录您曾咨询过这单"
        elif recommended.get("status") == "pending_shipment":
            reason = "当前仍处于待出荷/待发状态"
        else:
            reason = recommended.get("status_label") or "状态需确认"

    greeting = f"{nickname}您好，我是虾饺，您的专属客服助手。"
    if member_label:
        greeting += f"（{member_label}）"

    return {
        "greeting": greeting,
        "memory_line": memory_line,
        "order_line": order_line,
        "recommend_reason": reason,
        "recommended_order": recommended,
        "weights_applied": weight_cfg or None,
    }


@mock_router.get("/api/v1/users/{user_id}")
def get_user(user_id: str):
    db = load_data()
    user = db.get("users", {}).get(user_id)
    if not user:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")
    return {"user": user}


@mock_router.get("/api/v1/orders/{user_id}")
def get_orders(user_id: str, status: Optional[str] = None, sort: Optional[str] = None, weights: Optional[str] = None):
    db = load_data()
    user_orders = [ord for ord in db.get("orders", {}).values() if ord.get("user_id") == user_id]
    if status:
        user_orders = [ord for ord in user_orders if ord.get("status") == status]
    weight_cfg = {}
    if weights:
        try:
            weight_cfg = json.loads(weights)
        except json.JSONDecodeError:
            weight_cfg = {}
    if sort == "priority":
        user_orders.sort(
            key=lambda o: (_order_priority_score(o, weight_cfg), o.get("created_at") or ""),
            reverse=True,
        )
    return {"orders": user_orders, "total": len(user_orders)}


@mock_router.get("/api/v1/logistics/{order_id}")
def get_logistics(order_id: str):
    db = load_data()
    log = db.get("logistics", {}).get(order_id)
    if not log:
        raise HTTPException(status_code=404, detail=f"Logistics info for order {order_id} not found")
    return log


@mock_router.get("/api/v1/supply_chain/warnings")
def get_warnings(ip_name: Optional[str] = None):
    return {"warnings": get_supply_chain_warnings(ip_name)}


class CompensateReq(BaseModel):
    user_id: str
    order_id: str
    type: str
    amount: float
    reason: str
    agent_session_id: str


@mock_router.post("/api/v1/compensate")
def post_compensate(req: CompensateReq):
    if req.type == "points":
        return {
            "success": True,
            "compensation_id": f"COMP_MOCK_{req.order_id}",
            "message": f"成功为用户 {req.user_id} 自动发放 500 平台积分，并加挂订单优先发货特权！原因：{req.reason}"
        }
    if req.amount > 22.0:
        raise HTTPException(status_code=400, detail="[风控拦截] AI自动发放安抚性补偿单次金额不得超过22元。如需更高赔付，请转人工审批。")
    return {
        "success": True,
        "compensation_id": f"COMP_MOCK_{req.order_id}",
        "message": f"成功为用户 {req.user_id} 的订单 {req.order_id} 发放 {req.amount} 元【{req.type}】补偿，原因：{req.reason}"
    }


class UrgentReq(BaseModel):
    user_id: str
    urgency_level: str
    reason: str
    agent_session_id: str


@mock_router.post("/api/v1/orders/{order_id}/urgent")
def post_order_urgent(order_id: str, req: UrgentReq):
    db = load_data()
    order = db.get("orders", {}).get(order_id)
    if not order:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
    return {
        "success": True,
        "is_expeditable": True,
        "estimated_ship_date": "2024-12-20",
        "message": f"订单 {order_id} 已成功标记为【{req.urgency_level}】加急，预计12月20日左右优先出荷。"
    }


# 独立启动 Mock 服务（开发调试用）
if __name__ == "__main__":
    import socket
    import uvicorn
    from fastapi import FastAPI

    app = FastAPI(title="MITAKO Mock Business API")
    app.include_router(mock_router)

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
    print(f"\n[Mock API] http://127.0.0.1:{port}\n")
    uvicorn.run(app, host="127.0.0.1", port=port)
