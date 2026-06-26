# -*- coding: utf-8 -*-
import os
import re
import json
import asyncio
import traceback
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from sse_starlette.sse import EventSourceResponse

from agent import agent_app
from llm_models import DEFAULT_MODEL_ID, list_models_public
from image_models import list_image_models_public
from image_service import generate_image
from handoff_service import (
    build_handoff_brief,
    build_human_welcome,
    enqueue_handoff,
    get_queue_status,
    reset_session_handoff,
    list_desk_sessions,
    get_desk_session,
    append_desk_message,
    accept_handoff,
    escalate_to_supervisor,
    transfer_to_colleague,
    list_demo_agents,
    post_user_message,
    get_messages_since,
    process_sla_timeouts,
    get_routing_config,
    update_routing_config,
    close_handoff_session,
)
from admin_service import (
    list_agents_public,
    queue_snapshot,
    manual_reassign,
    list_audit_events,
    session_transcript,
    create_compensation_approval,
    list_compensation_approvals,
    decide_compensation_approval,
    reports_summary,
    reports_csv_rows,
)
import admin_store
import handoff_store as handoff_store_module
from companion_api import companion_router
from handoff_ws import hub
from mock_api import mock_router
from auth.jwt_utils import auth_required, create_token, create_handoff_user_token, companion_auth_required
from auth.middleware import require_roles, assert_tenant_access, resolve_handoff_ws_user
from auth.roles import ADMIN_MUTATE_ROLES, DESK_MUTATE_ROLES, DESK_ACCESS_ROLES
from auth.store import verify_user
from auth import tenants as tenant_store
from auth import sso as sso_service
from ops_service import ops_snapshot

app = FastAPI(title="MITAKO 客服 Agent 演示主站", description="提供双栏演示前端渲染与 SSE 对话流交互")
app.include_router(mock_router)
app.include_router(companion_router)

# 配置跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi.staticfiles import StaticFiles

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
os.makedirs(TEMPLATES_DIR, exist_ok=True)

# 挂载编译出来的 assets 静态目录
dist_assets = os.path.join(os.path.dirname(__file__), "dist", "assets")
if os.path.exists(dist_assets):
    app.mount("/assets", StaticFiles(directory=dist_assets), name="assets")

@app.get("/", response_class=HTMLResponse)
async def get_index():
    dist_index = os.path.join(os.path.dirname(__file__), "dist", "index.html")
    if os.path.exists(dist_index):
        return FileResponse(dist_index)
    index_html = os.path.join(TEMPLATES_DIR, "index.html")
    if os.path.exists(index_html):
        return FileResponse(index_html)
    return HTMLResponse("<h1>index.html 尚未创建，请等待写入...</h1>")

@app.get("/templates/xiaojiao_avatar.png")
@app.get("/xiaojiao_avatar.png")
async def get_avatar():
    dist_avatar = os.path.join(os.path.dirname(__file__), "dist", "xiaojiao_avatar.png")
    if os.path.exists(dist_avatar):
        return FileResponse(dist_avatar)
    avatar_png = os.path.join(TEMPLATES_DIR, "xiaojiao_avatar.png")
    if os.path.exists(avatar_png):
        return FileResponse(avatar_png)
    return HTMLResponse("Avatar not found", status_code=404)

@app.get("/api/v1/test_cases")
async def get_test_cases():
    test_cases_path = os.path.join(os.path.dirname(__file__), "test_cases.json")
    if os.path.exists(test_cases_path):
        with open(test_cases_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

class ChatRequest(BaseModel):
    user_id: str
    session_id: str
    content: str
    history: List[Dict[str, str]]
    model_id: str = DEFAULT_MODEL_ID
    active_order_id: Optional[str] = None
    stream_reply: bool = False


class HandoffRequest(BaseModel):
    user_id: str
    session_id: str
    history: List[Dict[str, str]] = []
    reason: str = "用户主动申请人工客服"
    last_user_message: str = ""
    intent: str = ""
    emotion_level: int = 2
    tenant_id: str = "mitako"


class AuthLoginRequest(BaseModel):
    username: str
    password: str
    tenant_id: str = "mitako"


class SsoCallbackBody(BaseModel):
    tenant_id: str
    code: str
    state: str

@app.post("/api/v1/auth/login")
async def auth_login(req: AuthLoginRequest):
    """管理员/坐席登录 — MITAKO_AUTH_REQUIRED=1 时 desk/admin 变更 API 需 token"""
    user = verify_user(req.username, req.password)
    if not user:
        return {"ok": False, "error": "invalid_credentials"}
    user_tenant = user.get("tenant_id") or "mitako"
    if req.tenant_id and req.tenant_id != user_tenant:
        return {"ok": False, "error": "tenant_mismatch"}
    token = create_token(
        sub=user["username"],
        role=user["role"],
        agent_id=user.get("agent_id") or "",
        display_name=user.get("display_name") or user["username"],
        tenant_id=user_tenant,
    )
    return {
        "ok": True,
        "token": token,
        "user": {
            "username": user["username"],
            "role": user["role"],
            "agent_id": user.get("agent_id") or "",
            "display_name": user.get("display_name") or user["username"],
            "tenant_id": user_tenant,
        },
    }


@app.get("/api/v1/auth/tenants")
async def auth_tenants():
    return {"ok": True, "tenants": tenant_store.list_tenants(enabled_only=True)}


@app.get("/api/v1/auth/sso/{tenant_id}/authorize")
async def auth_sso_authorize(tenant_id: str):
    return sso_service.build_authorize_url(tenant_id)


@app.post("/api/v1/auth/sso/callback")
async def auth_sso_callback(body: SsoCallbackBody):
    exchanged = await sso_service.exchange_code_async(body.tenant_id, body.code, body.state)
    if not exchanged.get("ok"):
        return exchanged
    mapped = sso_service.map_sso_profile_to_user(exchanged["profile"], body.tenant_id)
    token = create_token(
        sub=mapped["username"],
        role=mapped["role"],
        display_name=mapped["display_name"],
        tenant_id=mapped["tenant_id"],
        agent_id=mapped.get("agent_id") or "",
    )
    return {"ok": True, "token": token, "user": mapped}


@app.get("/api/v1/auth/sso/demo/complete")
async def auth_sso_demo_complete(tenant_id: str, state: str):
    """仅 MITAKO_SSO_DEMO=1 时供本地 E2E 使用 — 生产请走 IdP redirect"""
    if not sso_service.sso_demo_mode():
        return {"ok": False, "error": "demo_disabled"}
    exchanged = sso_service.exchange_code(tenant_id, "demo_ok", state)
    if not exchanged.get("ok"):
        return exchanged
    mapped = sso_service.map_sso_profile_to_user(exchanged["profile"], tenant_id)
    token = create_token(
        sub=mapped["username"],
        role=mapped["role"],
        display_name=mapped["display_name"],
        tenant_id=mapped["tenant_id"],
    )
    return {"ok": True, "token": token, "user": mapped}


@app.get("/api/v1/ops/snapshot")
async def ops_snapshot_api(user=require_roles(ADMIN_MUTATE_ROLES)):
    snap = await ops_snapshot(tenant_id=user.get("tenant_id"))
    return {"ok": True, "snapshot": snap}


@app.get("/api/v1/auth/status")
async def auth_status():
    return {
        "ok": True,
        "auth_required": auth_required(),
        "companion_auth_required": companion_auth_required(),
        "sso_demo_enabled": sso_service.sso_demo_mode(),
    }


class AdminAgentBody(BaseModel):
    agent_id: str
    name: str
    title: str = ""
    tier: str = "standard"
    team: str = ""
    skills: List[str] = []
    enabled: bool = True


class ReassignBody(BaseModel):
    to_agent_id: str
    note: str = ""


class ApprovalCreateBody(BaseModel):
    session_id: str = ""
    user_id: str = ""
    amount: float
    reason: str = ""


class ApprovalDecisionBody(BaseModel):
    decision: str


@app.get("/api/v1/admin/agents")
async def admin_list_agents(user=require_roles(ADMIN_MUTATE_ROLES)):
    return {"ok": True, "agents": admin_store.list_agents(enabled_only=False, tenant_id=user.get("tenant_id"))}


@app.post("/api/v1/admin/agents")
async def admin_upsert_agent(body: AdminAgentBody, user=require_roles(ADMIN_MUTATE_ROLES)):
    data = body.model_dump()
    data["tenant_id"] = user.get("tenant_id") or "mitako"
    agent = admin_store.upsert_agent(data)
    return {"ok": True, "agent": agent}


@app.delete("/api/v1/admin/agents/{agent_id}")
async def admin_delete_agent(agent_id: str, user=require_roles(ADMIN_MUTATE_ROLES)):
    existing = admin_store.get_agent(agent_id, tenant_id=user.get("tenant_id"))
    if not existing:
        return {"ok": False, "error": "not_found"}
    ok = admin_store.delete_agent(agent_id)
    return {"ok": ok}


@app.get("/api/v1/admin/queue/snapshot")
async def admin_queue_snapshot(user=require_roles(ADMIN_MUTATE_ROLES)):
    return {"ok": True, "snapshot": queue_snapshot(tenant_id=user.get("tenant_id"))}


@app.post("/api/v1/admin/queue/{session_id}/reassign")
async def admin_reassign(session_id: str, body: ReassignBody, user=require_roles(ADMIN_MUTATE_ROLES)):
    return manual_reassign(session_id, body.to_agent_id, body.note, user.get("sub", ""), tenant_id=user.get("tenant_id"))


@app.get("/api/v1/admin/audit/events")
async def admin_audit_events(limit: int = 80, event_type: str = "", _user=require_roles(ADMIN_MUTATE_ROLES)):
    return {"ok": True, "events": list_audit_events(event_type=event_type, limit=limit)}


@app.get("/api/v1/admin/audit/sessions/{session_id}/transcript")
async def admin_transcript(session_id: str, _user=require_roles(ADMIN_MUTATE_ROLES)):
    return session_transcript(session_id)


@app.get("/api/v1/admin/qc/observer")
async def admin_observer_qc(flagged_only: bool = True, _user=require_roles(ADMIN_MUTATE_ROLES)):
    return {"ok": True, "audits": handoff_store_module.list_observer_audits(flagged_only=flagged_only)}


@app.get("/api/v1/admin/approvals")
async def admin_list_approvals(status: str = "", user=require_roles(ADMIN_MUTATE_ROLES)):
    return list_compensation_approvals(status=status, tenant_id=user.get("tenant_id"))


@app.post("/api/v1/admin/approvals")
async def admin_create_approval(body: ApprovalCreateBody, user=require_roles(ADMIN_MUTATE_ROLES)):
    return create_compensation_approval(
        session_id=body.session_id,
        user_id=body.user_id,
        amount=body.amount,
        reason=body.reason,
        requester=user.get("sub", ""),
        tenant_id=user.get("tenant_id") or "mitako",
    )


@app.post("/api/v1/admin/approvals/{approval_id}/decide")
async def admin_decide_approval(approval_id: int, body: ApprovalDecisionBody, user=require_roles(ADMIN_MUTATE_ROLES)):
    return decide_compensation_approval(approval_id, body.decision, user.get("sub", ""), tenant_id=user.get("tenant_id"))


@app.get("/api/v1/admin/reports/summary")
async def admin_reports_summary(days: int = 7, user=require_roles(ADMIN_MUTATE_ROLES)):
    return {"ok": True, "summary": reports_summary(days=max(1, min(days, 90)), tenant_id=user.get("tenant_id"))}


@app.get("/api/v1/admin/reports/export.csv")
async def admin_reports_export(days: int = 7, user=require_roles(ADMIN_MUTATE_ROLES)):
    from fastapi.responses import PlainTextResponse

    csv_text = reports_csv_rows(days=max(1, min(days, 90)), tenant_id=user.get("tenant_id"))
    return PlainTextResponse(csv_text, media_type="text/csv; charset=utf-8")


@app.post("/api/v1/handoff/close")
async def handoff_close(session_id: str, note: str = "", _user=require_roles(DESK_MUTATE_ROLES)):
    return close_handoff_session(session_id, note or "会话已结束")


@app.get("/metrics")
async def metrics():
    snap = queue_snapshot()
    return {
        "handoff_queuing": snap.get("queuing", 0),
        "handoff_connected": snap.get("connected", 0),
        "handoff_escalated": snap.get("escalated", 0),
        "sla_alerts": len(snap.get("sla_alerts") or []),
        "ws_connections": hub.connection_count(),
        "sla_worker_mode": os.getenv("SLA_WORKER_MODE", "inline"),
    }


@app.get("/api/v1/models")
async def get_models():
    """返回可用 LLM 模型列表（供前端切换）"""
    return {
        "default_model_id": DEFAULT_MODEL_ID,
        "models": list_models_public(),
        "image_models": list_image_models_public(),
        "streaming_default": False,
    }


class ImageGenerateRequest(BaseModel):
    prompt: str
    model_id: str = "sensenova-u1-fast"
    size: str = "2752x1536"
    n: int = 1


@app.get("/api/v1/image-models")
async def get_image_models():
    return {"models": list_image_models_public()}


@app.post("/api/v1/images/generate")
async def post_generate_image(req: ImageGenerateRequest):
    """SenseNova U1 Fast 信息图生成"""
    try:
        result = await generate_image(req.prompt, req.model_id, req.size, req.n)
        return {"ok": True, **result}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.post("/api/v1/handoff/request")
async def request_handoff(req: HandoffRequest):
    """用户确认转人工 — 生成简报并加入排队（演示队列）"""
    pseudo_state = {
        "user_id": req.user_id,
        "session_id": req.session_id,
        "messages": req.history + ([{"role": "user", "content": req.last_user_message}] if req.last_user_message else req.history[-2:]),
        "intent": req.intent,
        "emotion_level": req.emotion_level,
        "order_data": {},
        "transfer_reason": req.reason,
        "compensation_given": [],
        "reply_draft": "",
    }
    brief = build_handoff_brief(pseudo_state, req.reason)
    brief["tenant_id"] = req.tenant_id or "mitako"
    queue_meta = enqueue_handoff(req.session_id, brief, tenant_id=brief["tenant_id"])
    handoff_token = create_handoff_user_token(
        session_id=req.session_id,
        user_id=req.user_id,
        tenant_id=brief["tenant_id"],
    )
    return {
        "ok": True,
        "brief": brief,
        "queue": queue_meta,
        "reason": req.reason,
        "handoff_token": handoff_token,
    }


@app.get("/api/v1/handoff/status/{session_id}")
async def handoff_status(session_id: str):
    entry = get_queue_status(session_id)
    if not entry:
        return {"ok": False, "status": "none"}
    return {"ok": True, **entry}


@app.get("/desk", response_class=HTMLResponse)
async def get_desk():
    dist_desk = os.path.join(os.path.dirname(__file__), "dist", "desk.html")
    if os.path.exists(dist_desk):
        return FileResponse(dist_desk)
    return HTMLResponse("<h1>desk.html 尚未构建，请先 npm run build</h1>")


@app.get("/companion", response_class=HTMLResponse)
async def get_companion():
    dist_path = os.path.join(os.path.dirname(__file__), "dist", "companion.html")
    if os.path.exists(dist_path):
        return FileResponse(dist_path)
    return HTMLResponse("<h1>companion.html 尚未构建，请先 npm run build</h1>")


@app.get("/companion-desk", response_class=HTMLResponse)
async def get_companion_desk():
    dist_path = os.path.join(os.path.dirname(__file__), "dist", "companion-desk.html")
    if os.path.exists(dist_path):
        return FileResponse(dist_path)
    return HTMLResponse("<h1>companion-desk.html 尚未构建，请先 npm run build</h1>")


@app.post("/api/v1/handoff/connect")
async def handoff_connect(session_id: str):
    """仅当人工已在工作台确认接单后，用户端轮询才会得到 connected"""
    entry = get_queue_status(session_id)
    if not entry or entry.get("status") != "connected":
        return {"ok": False, "status": entry.get("status") if entry else "none"}
    agent = entry.get("assigned_agent") or entry.get("agent") or {}
    brief = entry.get("brief") or {}
    return {
        "ok": True,
        "status": "connected",
        "agent": agent,
        "welcome": entry.get("welcome") or build_human_welcome(agent, brief),
        "brief": brief,
    }


@app.post("/api/v1/handoff/reset")
async def handoff_reset(session_id: str, _user=require_roles(ADMIN_MUTATE_ROLES)):
    reset_session_handoff(session_id)
    return {"ok": True}


class DeskReplyRequest(BaseModel):
    content: str
    agent_id: str = ""


class DeskAcceptRequest(BaseModel):
    agent_id: str


class DeskEscalateRequest(BaseModel):
    note: str = ""


class DeskTransferRequest(BaseModel):
    from_agent_id: str
    to_agent_id: str
    note: str = ""


class HandoffUserMessageRequest(BaseModel):
    session_id: str
    content: str
    user_id: str = ""


@app.on_event("startup")
async def startup_handoff_sla():
    from logging_utils import log_event

    await hub.start_redis_listener()
    sla_mode = os.getenv("SLA_WORKER_MODE", "inline")
    log_event("server_startup", sla_mode=sla_mode, redis=bool(os.getenv("REDIS_HOST")))

    if sla_mode == "celery":
        return

    async def _sla_loop():
        while True:
            try:
                process_sla_timeouts()
            except Exception:
                traceback.print_exc()
            await asyncio.sleep(30)

    asyncio.create_task(_sla_loop())


@app.put("/api/v1/admin/handoff/routing")
async def admin_update_routing(config: Dict[str, Any], _user=require_roles(ADMIN_MUTATE_ROLES)):
    saved = update_routing_config(config)
    return {"ok": True, "config": saved}


@app.websocket("/api/v1/handoff/ws/{session_id}")
async def handoff_websocket(session_id: str, websocket: WebSocket):
    entry = get_queue_status(session_id) or {}
    session_user = entry.get("user_id") or (entry.get("brief") or {}).get("user_id") or ""
    session_tenant = entry.get("tenant_id") or (entry.get("brief") or {}).get("tenant_id") or "mitako"
    ws_user = resolve_handoff_ws_user(websocket, session_id, session_user, session_tenant)
    if auth_required() and not ws_user:
        await websocket.close(code=4401)
        return
    await hub.connect(session_id, websocket)
    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                if data.strip().lower() in ("ping", "pong"):
                    if data.strip().lower() == "ping":
                        await websocket.send_text('{"type":"pong"}')
            except asyncio.TimeoutError:
                await websocket.send_text('{"type":"ping"}')
    except WebSocketDisconnect:
        await hub.disconnect(session_id, websocket)


@app.get("/admin", response_class=HTMLResponse)
async def get_admin():
    dist_admin = os.path.join(os.path.dirname(__file__), "dist", "admin.html")
    if os.path.exists(dist_admin):
        return FileResponse(dist_admin)
    return HTMLResponse("<h1>admin.html 尚未构建，请先 npm run build</h1>")


@app.get("/api/v1/handoff/routing")
async def handoff_routing_config():
    return {"ok": True, "config": get_routing_config()}


@app.get("/api/v1/handoff/messages/{session_id}")
async def handoff_messages(session_id: str, since: float = 0):
    entry = get_queue_status(session_id)
    if not entry:
        return {"ok": False, "error": "session_not_found"}
    messages = get_messages_since(session_id, since)
    latest = messages[-1]["created_at"] if messages else since
    return {"ok": True, "messages": messages, "latest_ts": latest, "status": entry.get("status")}


@app.post("/api/v1/handoff/user-message")
async def handoff_user_message(req: HandoffUserMessageRequest):
    return await post_user_message(req.session_id, req.content, req.user_id)


@app.get("/api/v1/desk/agents")
async def desk_agents(_user=require_roles(DESK_ACCESS_ROLES)):
    return {"ok": True, "agents": list_demo_agents()}


@app.get("/api/v1/desk/sessions")
async def desk_sessions(user=require_roles(DESK_ACCESS_ROLES)):
    return {"ok": True, "sessions": list_desk_sessions(tenant_id=user.get("tenant_id"))}


@app.get("/api/v1/desk/session/{session_id}")
async def desk_session_detail(session_id: str, user=require_roles(DESK_ACCESS_ROLES)):
    data = get_desk_session(session_id, tenant_id=user.get("tenant_id"))
    if not data:
        return {"ok": False, "error": "session_not_found"}
    return {"ok": True, **data}


@app.post("/api/v1/desk/session/{session_id}/reply")
async def desk_session_reply(session_id: str, req: DeskReplyRequest, user=require_roles(DESK_MUTATE_ROLES)):
    entry = get_desk_session(session_id, tenant_id=user.get("tenant_id"))
    if not entry:
        return {"ok": False, "error": "session_not_found"}
    if not entry.get("can_chat"):
        return {"ok": False, "error": "not_accepted", "message": "请先确认阅读并接受转接后再回复用户"}
    append_desk_message(session_id, "human", req.content, {"agent_id": req.agent_id})
    return {"ok": True}


@app.post("/api/v1/desk/session/{session_id}/accept")
async def desk_session_accept(session_id: str, req: DeskAcceptRequest, _user=require_roles(DESK_MUTATE_ROLES)):
    result = accept_handoff(session_id, req.agent_id)
    if not result.get("ok"):
        return result
    return {"ok": True, **result}


@app.post("/api/v1/desk/session/{session_id}/escalate")
async def desk_session_escalate(session_id: str, req: DeskEscalateRequest, _user=require_roles(DESK_MUTATE_ROLES)):
    result = escalate_to_supervisor(session_id, req.note)
    if not result.get("ok"):
        return result
    return {"ok": True, **result}


@app.post("/api/v1/desk/session/{session_id}/transfer")
async def desk_session_transfer(session_id: str, req: DeskTransferRequest, _user=require_roles(DESK_MUTATE_ROLES)):
    result = transfer_to_colleague(session_id, req.from_agent_id, req.to_agent_id, req.note)
    if not result.get("ok"):
        return result
    return {"ok": True, **result}


@app.post("/api/v1/chat")
async def chat_stream(req: ChatRequest):
    async def event_generator():
        queue = asyncio.Queue()
        
        # 初始 State
        state = {
            "messages": req.history + [{"role": "user", "content": req.content}],
            "user_id": req.user_id,
            "session_id": req.session_id,
            "active_order_id": req.active_order_id or "",
            "intent": "",
            "emotion_level": 2,
            "order_data": {},
            "logistics_data": {},
            "sop_results": [],
            "user_memory": {},
            "reply_draft": "",
            "safety_check_result": "pass",
            "should_transfer": False,
            "transfer_reason": "",
            "compensation_given": [],
            "meme_tags": []
        }

        # 异步启动 LangGraph 状态机任务
        task = asyncio.create_task(
            agent_app.ainvoke(
                state,
                config={
                    "configurable": {
                        "event_queue": queue,
                        "model_id": req.model_id,
                        "stream_reply": req.stream_reply,
                    }
                }
            )
        )

        current_emotion_level = 2
        buffer_sent = {
            "search": False,
            "api": False
        }

        # 监听执行状态队列
        while not task.done() or not queue.empty():
            try:
                # 0.05s 超时检查 task.done
                event = await asyncio.wait_for(queue.get(), timeout=0.05)
                
                # 1. 监测到情绪变化时更新本地延时参考
                if event["type"] == "node_end" and event["node"] == "intent_classify":
                    # 从日志流中解析出情绪，如 "情绪等级=【Level 4】"
                    desc = event.get("desc", "")
                    match = re.search(r"Level\s*(\d)", desc)
                    if match:
                        current_emotion_level = int(match.group(1))



                # 3. 大模型 Thinking 思考流实时推送
                if event["type"] == "llm_thinking":
                    yield {
                        "event": "thinking",
                        "data": json.dumps({
                            "type": "llm_thinking",
                            "content": event["content"]
                        }, ensure_ascii=False)
                    }

                # 4. 大模型正式回复的流直接推送 (去除后端强行限速，改为由前端控制打字缓冲)
                elif event["type"] == "text_chunk":
                    char_content = event["content"]
                    yield {
                        "event": "chunk",
                        "data": json.dumps({"content": char_content}, ensure_ascii=False)
                    }

                # 5. 移交简报
                elif event["type"] == "handoff_brief":
                    yield {
                        "event": "handoff_brief",
                        "data": json.dumps({"brief": event.get("brief", {})}, ensure_ascii=False)
                    }

                # 6. 常规思考追踪 / 转人工
                elif event["type"] in ["node_start", "node_end", "action_transfer"]:
                    yield {
                        "event": "thinking" if event["type"] != "action_transfer" else "transfer",
                        "data": json.dumps(event, ensure_ascii=False)
                    }

                # 7. 独立调试日志推送
                elif event["type"] == "api_log":
                    yield {
                        "event": "api_log",
                        "data": json.dumps(event, ensure_ascii=False)
                    }

                # 7. 统一分析（意图和情绪）事件下发
                elif event["type"] == "unified_analysis":
                    yield {
                        "event": "unified_analysis",
                        "data": json.dumps(event, ensure_ascii=False)
                    }

                queue.task_done()
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                print(f"[SSE] 提取事件时发生异常: {e}")
                break

        # 获取最终执行结果
        reply_fallback = ""
        try:
            result = await task
            reply_fallback = result.get("reply_draft", "") if isinstance(result, dict) else ""
            
            # 推送卡片
            if result.get("compensation_given"):
                for comp in result["compensation_given"]:
                    yield {
                        "event": "card",
                        "data": json.dumps({
                            "type": "compensation",
                            "data": comp
                        }, ensure_ascii=False)
                    }
            
            if result.get("order_data") and result["order_data"].get("orders"):
                order = result["order_data"]["orders"][0]
                status = order.get("status")
                
                # 带有受海关延误标记的二次元进度卡片
                progress_steps = [
                    {"label": "下单", "status": "completed", "date": "2024-06-01"},
                    {"label": "出荷", "status": "completed" if status != "pending_shipment" else "delayed", "date": "原定9月 → 延至12月" if order.get("delay_days", 0) > 0 else "已出荷", "highlight": order.get("delay_days", 0) > 0},
                    {"label": "清关", "status": "current" if status == "pending_shipment" else "pending", "date": "进行中" if status == "pending_shipment" else "待清关"},
                    {"label": "入库", "status": "pending", "date": "待入库"},
                    {"label": "派送", "status": "pending", "date": "待派送"}
                ]
                
                if status == "delivered":
                    progress_steps = [
                        {"label": "下单", "status": "completed", "date": "2025-05-20"},
                        {"label": "出荷", "status": "completed", "date": "已出荷"},
                        {"label": "清关", "status": "completed", "date": "已清关"},
                        {"label": "入库", "status": "completed", "date": "已入库"},
                        {"label": "派送", "status": "completed", "date": "已妥投"}
                    ]

                yield {
                    "event": "card",
                    "data": json.dumps({
                        "type": "order_progress",
                        "data": {
                            "order_id": order["order_id"],
                            "item_name": order["items"][0]["name"] if order.get("items") else "谷子周边",
                            "total_amount": order.get("total_amount"),
                            "progress_steps": progress_steps,
                            "delay_reason": "海关港口突击抽检查验，预计12月15日出荷完成" if order.get("delay_days", 0) > 0 else ""
                        }
                    }, ensure_ascii=False)
                }

        except Exception as e:
            print(f"[SSE] 获取状态机最终结果异常: {e}")
            traceback.print_exc()

        yield {
            "event": "done",
            "data": json.dumps({
                "status": "completed",
                "reply": reply_fallback,
            }, ensure_ascii=False)
        }

    import re
    return EventSourceResponse(event_generator())

if __name__ == "__main__":
    import uvicorn
    import socket

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

    port = int(os.getenv("APP_PORT", "8000"))
    allow_fallback = os.getenv("ALLOW_PORT_FALLBACK", "0").strip().lower() in ("1", "true", "yes")
    if allow_fallback:
        port = find_free_port(port)
    print(f"\n[MITAKO AI Customer Service System] Starting...")
    print(f"Local browser access: http://localhost:{port}\n")
    uvicorn.run(app, host="127.0.0.1", port=port)
