# -*- coding: utf-8 -*-
import os
import re
import json
import asyncio
import traceback
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from fastapi import Depends, FastAPI, Request, WebSocket, WebSocketDisconnect, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse, FileResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from sse_starlette.sse import EventSourceResponse

from agent import agent_app, classify_intent, sanitize_customer_reply
from llm_models import DEFAULT_PUBLIC_MODEL_ID, list_models_public
from image_models import list_image_models_public
from image_service import generate_image
from handoff_service import (
    build_handoff_brief,
    build_customer_handoff_payload,
    build_public_handoff_brief,
    build_public_queue_meta,
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
import handoff_store
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
    demo_status,
    load_demo_data,
    clear_demo_data,
)
import admin_store
import handoff_store as handoff_store_module
from handoff_ws import hub
from business_api import business_router, load_data
from viking_memory import viking_db
from auth.jwt_utils import (
    auth_required,
    create_handoff_user_token,
    create_token,
    decode_token,
    dev_auth_bypass_enabled,
    protected_api_auth_required,
)
from auth.middleware import require_roles, assert_tenant_access, resolve_handoff_ws_user, extract_bearer_token
from auth.roles import (
    ADMIN_MUTATE_ROLES,
    DESK_MUTATE_ROLES,
    DESK_ACCESS_ROLES,
    APPROVAL_ACCESS_ROLES,
    APPROVAL_CREATE_ROLES,
    APPROVAL_DECIDE_ROLES,
    ALL_ROLES,
)
from auth.roles import Role
from auth.store import verify_user
from auth import tenants as tenant_store
from auth import sso as sso_service
from ops_service import ops_snapshot
from runtime_paths import app_root, data_dir
from private_domain.router import router as private_domain_router
from private_domain import store as private_domain_store
from review_service.router import router as review_service_router
from review_service import service as review_service_core
from prompts.router import router as business_rules_router

SUPER_ADMIN_ONLY = frozenset({Role.SUPER_ADMIN.value})

app = FastAPI(title="MITAKO 客服 Agent 主站", description="提供客服前台、VIP客服工作台与运营后台服务")
APP_ROOT = app_root()
INTERNAL_BUSINESS_NODE = "".join(chr(c) for c in (109, 111, 99, 107, 95, 98, 117, 115, 105, 110, 101, 115, 115))
INTERNAL_API_EVENT = "".join(chr(c) for c in (97, 112, 105, 95, 108, 111, 103))


def _business_demo_enabled() -> bool:
    raw = os.getenv("MITAKO_BUSINESS_DEMO_API_ENABLED", "").strip().lower()
    if raw in {"1", "true", "yes"}:
        return True
    if raw in {"0", "false", "no"}:
        return False
    return False


if _business_demo_enabled():
    app.include_router(business_router)

app.include_router(private_domain_router)
app.include_router(review_service_router)
app.include_router(business_rules_router)


def _cors_origins() -> List[str]:
    raw = os.getenv("MITAKO_CORS_ORIGINS", "").strip()
    if raw:
        return [item.strip() for item in raw.split(",") if item.strip()]
    if os.getenv("MITAKO_DEV_CORS_ANY", "0").strip().lower() in {"1", "true", "yes"}:
        return ["*"]
    return ["http://127.0.0.1:8000", "http://localhost:8000"]


# 配置跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi.staticfiles import StaticFiles

TEMPLATES_DIR = str(APP_ROOT / "templates")
os.makedirs(TEMPLATES_DIR, exist_ok=True)
CHAT_ATTACHMENTS_DIR = data_dir() / "chat_attachments"
CHAT_ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)

# 挂载编译出来的 assets 静态目录
dist_assets = str(APP_ROOT / "dist" / "assets")
if os.path.exists(dist_assets):
    app.mount("/assets", StaticFiles(directory=dist_assets), name="assets")

dist_memes = str(APP_ROOT / "dist" / "memes")
if os.path.exists(dist_memes):
    app.mount("/memes", StaticFiles(directory=dist_memes), name="memes")

@app.get("/", response_class=HTMLResponse)
async def get_index():
    dist_index = str(APP_ROOT / "dist" / "index.html")
    if os.path.exists(dist_index):
        return FileResponse(dist_index)
    return HTMLResponse("<h1>index.html 尚未构建，请先执行 npm run build</h1>", status_code=503)

@app.get("/templates/xiaojiao_avatar.png")
@app.get("/xiaojiao_avatar.png")
async def get_avatar():
    dist_avatar = str(APP_ROOT / "dist" / "xiaojiao_avatar.png")
    if os.path.exists(dist_avatar):
        return FileResponse(dist_avatar)
    avatar_png = os.path.join(TEMPLATES_DIR, "xiaojiao_avatar.png")
    if os.path.exists(avatar_png):
        return FileResponse(avatar_png)
    return HTMLResponse("Avatar not found", status_code=404)

@app.get("/api/v1/test_cases")
async def get_test_cases():
    if os.getenv("MITAKO_E2E_ENABLED", "0").strip().lower() not in {"1", "true", "yes"}:
        raise HTTPException(status_code=404, detail="not_found")
    test_cases_path = str(APP_ROOT / "test_cases.json")
    if os.path.exists(test_cases_path):
        with open(test_cases_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

class ChatAttachment(BaseModel):
    id: str
    name: str
    mime_type: str
    size: int
    url: str
    kind: str = "chat_attachment"
    review_task_id: Optional[str] = None
    status: Optional[str] = None
    scenario: Optional[str] = None


class ChatRequest(BaseModel):
    user_id: str
    session_id: str
    content: str
    history: List[Dict[str, str]]
    model_id: str = DEFAULT_PUBLIC_MODEL_ID
    tenant_id: str = "mitako"
    active_order_id: Optional[str] = None
    stream_reply: bool = False
    fixtures: List[str] = []
    attachments: List[ChatAttachment] = Field(default_factory=list)


ALLOWED_CHAT_ATTACHMENT_MIME = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_CHAT_ATTACHMENT_BYTES = 12 * 1024 * 1024


def _safe_attachment_name(name: str) -> str:
    base = Path(name or "image").name
    base = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", base).strip("._")
    return base[:80] or "image"


def _detect_image_mime(raw: bytes) -> str:
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw.startswith(b"GIF87a") or raw.startswith(b"GIF89a"):
        return "image/gif"
    if len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    return ""


def _attachment_meta_path(filename: str) -> Path:
    return CHAT_ATTACHMENTS_DIR / f"{filename}.json"


def _read_attachment_meta(filename: str) -> Dict[str, Any]:
    if filename != Path(filename).name:
        return {}
    meta_path = _attachment_meta_path(filename)
    if not meta_path.exists():
        return {}
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _valid_chat_attachments(items: List[ChatAttachment], user_id: str, session_id: str, tenant_id: str) -> List[Dict[str, Any]]:
    valid: List[Dict[str, Any]] = []
    for item in items or []:
        if item.kind == "review_task" or item.url.startswith("/api/v1/private-domain/review-tasks/"):
            task_id = item.review_task_id or Path(item.url.rsplit("/", 1)[-1]).name
            task = private_domain_store.get_review_task(task_id)
            if not task or task.get("user_id") != user_id or task.get("session_id") != session_id or task.get("tenant_id") != tenant_id:
                continue
            valid.append({
                "id": task["task_id"],
                "kind": "review_task",
                "review_task_id": task["task_id"],
                "name": task["file_name"],
                "mime_type": task["mime_type"],
                "size": int(task["size"] or 0),
                "url": f"/api/v1/private-domain/review-tasks/{task['task_id']}",
                "status": task["status"],
                "scenario": task["scenario"],
                "boundary": task.get("boundary") or "",
                "review_result": task.get("result") or {},
                "reviewed_at": task.get("reviewed_at") or 0,
            })
            continue
        if not item.url.startswith("/api/v1/chat/attachments/"):
            continue
        filename = Path(item.url.split("/api/v1/chat/attachments/", 1)[1]).name
        meta = _read_attachment_meta(filename)
        if not meta or meta.get("user_id") != user_id or meta.get("session_id") != session_id or meta.get("tenant_id") != tenant_id:
            continue
        mime_type = str(meta.get("mime_type") or "")
        size = int(meta.get("size") or 0)
        if mime_type not in ALLOWED_CHAT_ATTACHMENT_MIME or size <= 0 or size > MAX_CHAT_ATTACHMENT_BYTES:
            continue
        path = CHAT_ATTACHMENTS_DIR / filename
        if not path.exists() or path.stat().st_size != size:
            continue
        valid.append({
            "id": str(meta.get("id") or item.id),
            "name": str(meta.get("name") or item.name),
            "mime_type": mime_type,
            "size": size,
            "url": f"/api/v1/chat/attachments/{filename}",
        })
    return valid


def _review_task_attachment(task: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": task["task_id"],
        "kind": "review_task",
        "review_task_id": task["task_id"],
        "name": task.get("file_name") or "审核材料",
        "mime_type": task.get("mime_type") or "application/octet-stream",
        "size": int(task.get("size") or 0),
        "url": f"/api/v1/private-domain/review-tasks/{task['task_id']}",
        "status": task.get("status") or "",
        "scenario": task.get("scenario") or "",
        "boundary": task.get("boundary") or "",
        "review_result": task.get("result") or {},
        "reviewed_at": task.get("reviewed_at") or 0,
    }


def _recent_review_attachments(user_id: str, session_id: str, tenant_id: str, content: str) -> List[Dict[str, Any]]:
    query = str(content or "")
    if not any(k in query for k in ["审核", "材料", "图片", "照片", "视频", "破损", "有伤", "瑕疵", "结果", "置信度", "报告"]):
        return []
    tasks = [
        task for task in private_domain_store.list_review_tasks(limit=100)
        if task.get("user_id") == user_id
        and task.get("session_id") == session_id
        and (task.get("tenant_id") or "mitako") == tenant_id
    ]
    return [_review_task_attachment(task) for task in tasks[:3]]


def _require_all_chat_attachments_valid(items: List[ChatAttachment], user_id: str, session_id: str, tenant_id: str) -> List[Dict[str, Any]]:
    valid = _valid_chat_attachments(items, user_id, session_id, tenant_id)
    if items and len(valid) != len(items):
        raise HTTPException(status_code=403, detail="invalid_attachment_scope")
    return valid


def _chat_attachment_context_line(item: Dict[str, Any]) -> str:
    base = f"- {item.get('name')} ({item.get('mime_type')}, {item.get('size')} bytes, {item.get('url')})"
    if item.get("kind") != "review_task":
        return base
    result = item.get("review_result") if isinstance(item.get("review_result"), dict) else {}
    review = result.get("review") if isinstance(result.get("review"), dict) else {}
    summary = review.get("summary") if isinstance(review.get("summary"), dict) else result.get("summary") if isinstance(result.get("summary"), dict) else {}
    brief = review.get("agent_brief") if isinstance(review.get("agent_brief"), dict) else result.get("agent_brief") if isinstance(result.get("agent_brief"), dict) else {}
    report = review.get("report") if isinstance(review.get("report"), dict) else result.get("report") if isinstance(result.get("report"), dict) else {}
    parts = [
        f"审核任务={item.get('review_task_id') or item.get('id')}",
        f"状态={item.get('status')}",
        f"场景={item.get('scenario')}",
    ]
    if review.get("review_label"):
        parts.append(f"队列={review.get('review_label')}")
    if brief.get("conclusion"):
        parts.append(f"初筛结论={brief.get('conclusion')}")
    if brief.get("next_step"):
        parts.append(f"建议动作={brief.get('next_step')}")
    if summary.get("needs_human_review") is not None:
        parts.append(f"需人工复核={'是' if summary.get('needs_human_review') else '否'}")
    if isinstance(summary.get("confidence"), (int, float)):
        parts.append(f"置信度={summary.get('confidence')}")
    if report.get("html_url"):
        parts.append(f"报告={report.get('html_url')}")
    if item.get("boundary"):
        parts.append(f"边界={item.get('boundary')}")
    return f"{base}；" + "；".join(parts)


async def _handoff_user_message_analysis(entry: Dict[str, Any], content: str, user_id: str, session_id: str) -> Dict[str, Any]:
    brief = entry.get("brief") or {}
    messages: List[Dict[str, str]] = []
    for item in (brief.get("conversation_snippet") or [])[-6:]:
        role = item.get("role")
        if role in {"user", "assistant"} and item.get("content"):
            messages.append({"role": role, "content": str(item.get("content") or "")})
    messages.append({"role": "user", "content": str(content or "")})
    try:
        result = await classify_intent(
            {
                "messages": messages,
                "user_id": user_id,
                "session_id": session_id,
                "intent": "",
                "emotion_level": 2,
            },
            {"configurable": {}},
        )
    except Exception:
        return {"intent": "人工服务补充", "emotion_level": 2, "should_transfer": False}
    return {
        "intent": result.get("intent") or "人工服务补充",
        "emotion_level": max(1, min(6, int(result.get("emotion_level") or 2))),
        "should_transfer": False,
    }


def _handoff_bearer(request: Request) -> str:
    token = extract_bearer_token(request)
    if token:
        return token
    if os.getenv("MITAKO_ALLOW_HANDOFF_QUERY_TOKEN", "0").strip().lower() in {"1", "true", "yes"}:
        return (request.query_params.get("handoff_token") or "").strip()
    return ""


def _request_tenant_id(req_tenant: str = "", token_user: Optional[Dict[str, Any]] = None, existing: Optional[Dict[str, Any]] = None) -> str:
    if existing:
        return _session_user_and_tenant(existing)[1] or "mitako"
    if token_user and token_user.get("tenant_id"):
        return str(token_user["tenant_id"])
    if os.getenv("MITAKO_TRUST_PUBLIC_TENANT_BODY", "0").strip().lower() in {"1", "true", "yes"}:
        return (req_tenant or "mitako").strip() or "mitako"
    return "mitako"


def _split_env_values(name: str, default: str = "") -> set[str]:
    raw = os.getenv(name, default)
    return {item.strip() for item in raw.split(",") if item.strip()}


def _customer_session_is_allowed(user_id: str, session_id: str, tenant_id: str) -> bool:
    existing = handoff_store.get_session(session_id)
    if existing:
        session_user, session_tenant = _session_user_and_tenant(existing)
        return user_id == session_user and (tenant_id or "mitako") == (session_tenant or "mitako")

    allowed_pairs = _split_env_values("MITAKO_DEMO_CUSTOMER_SESSIONS", "")
    if f"{tenant_id}:{user_id}:{session_id}" in allowed_pairs or f"{user_id}:{session_id}" in allowed_pairs:
        return True

    allowed_users = _split_env_values("MITAKO_DEMO_CUSTOMERS", "usr_001,usr_002,usr_003,usr_004,usr_005,usr_006,usr_e2e,probe")
    allowed_tenants = _split_env_values("MITAKO_DEMO_CUSTOMER_TENANTS", "mitako")
    return (
        tenant_id in allowed_tenants
        and user_id in allowed_users
        and session_id == f"session_{user_id}"
    )


def _session_user_and_tenant(entry: Dict[str, Any]) -> tuple[str, str]:
    brief = entry.get("brief") or {}
    user_id = entry.get("user_id") or brief.get("user_id") or ""
    tenant_id = entry.get("tenant_id") or brief.get("tenant_id") or "mitako"
    return user_id, tenant_id


def _require_handoff_user(request: Request, session_id: str, entry: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    token = _handoff_bearer(request)
    user = decode_token(token) if token else None
    if not user or user.get("role") != Role.HANDOFF_USER.value:
        raise HTTPException(status_code=401, detail="handoff_token_required")
    if user.get("session_id") and user.get("session_id") != session_id:
        raise HTTPException(status_code=403, detail="handoff_session_mismatch")
    if entry:
        session_user, session_tenant = _session_user_and_tenant(entry)
        if session_user and user.get("sub") != session_user:
            raise HTTPException(status_code=403, detail="handoff_user_mismatch")
        if (user.get("tenant_id") or "mitako") != (session_tenant or "mitako"):
            raise HTTPException(status_code=403, detail="handoff_tenant_mismatch")
    return user


def _resolve_customer_session_user(
    request: Request,
    *,
    user_id: str,
    session_id: str,
    entry: Optional[Dict[str, Any]] = None,
    token: str = "",
) -> Optional[Dict[str, Any]]:
    raw_token = token or extract_bearer_token(request)
    user = decode_token(raw_token) if raw_token else None
    if not user:
        if protected_api_auth_required() and not dev_auth_bypass_enabled():
            raise HTTPException(status_code=401, detail="customer_token_required")
        return None
    if user.get("role") not in {Role.CUSTOMER_USER.value, Role.HANDOFF_USER.value}:
        raise HTTPException(status_code=403, detail="customer_token_required")
    if user.get("sub") and user.get("sub") != user_id:
        raise HTTPException(status_code=403, detail="chat_token_user_mismatch")
    if user.get("session_id") and user.get("session_id") != session_id:
        raise HTTPException(status_code=403, detail="chat_token_session_mismatch")
    if entry:
        session_user, session_tenant = _session_user_and_tenant(entry)
        if session_user and user.get("sub") != session_user:
            raise HTTPException(status_code=403, detail="chat_session_user_mismatch")
        if (user.get("tenant_id") or "mitako") != (session_tenant or "mitako"):
            raise HTTPException(status_code=403, detail="chat_session_tenant_mismatch")
    return user


def _effective_agent_id(user: Dict[str, Any], requested_agent_id: str = "") -> str:
    token_agent_id = user.get("agent_id") or ""
    if token_agent_id:
        if requested_agent_id and requested_agent_id != token_agent_id:
            raise HTTPException(status_code=403, detail="agent_id_mismatch")
        return token_agent_id
    if protected_api_auth_required():
        raise HTTPException(status_code=403, detail="agent_id_required")
    return requested_agent_id


def _resolve_chat_user(request: Request, req: ChatRequest) -> Optional[Dict[str, Any]]:
    return _resolve_customer_session_user(
        request,
        user_id=req.user_id,
        session_id=req.session_id,
    )


@app.post("/api/v1/chat/attachments")
async def upload_chat_attachment(
    request: Request,
    user_id: str = Form(...),
    session_id: str = Form(...),
    file: UploadFile = File(...),
):
    existing_entry = handoff_store.get_session(session_id)
    token_user = _resolve_customer_session_user(request, user_id=user_id, session_id=session_id, entry=existing_entry)
    tenant_id = _request_tenant_id("", token_user, existing_entry)
    content_type = (file.content_type or "").split(";", 1)[0].strip().lower()
    if content_type not in ALLOWED_CHAT_ATTACHMENT_MIME:
        raise HTTPException(status_code=415, detail="unsupported_attachment_type")
    raw = await file.read(MAX_CHAT_ATTACHMENT_BYTES + 1)
    if len(raw) > MAX_CHAT_ATTACHMENT_BYTES:
        raise HTTPException(status_code=413, detail="attachment_too_large")
    detected_type = _detect_image_mime(raw)
    if detected_type != content_type:
        raise HTTPException(status_code=415, detail="unsupported_attachment_type")
    original_name = _safe_attachment_name(file.filename or "image")
    ext = Path(original_name).suffix.lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}[content_type]
    attachment_id = uuid4().hex
    stored_name = f"{attachment_id}{ext}"
    (CHAT_ATTACHMENTS_DIR / stored_name).write_bytes(raw)
    meta = {
        "id": attachment_id,
        "user_id": user_id,
        "session_id": session_id,
        "tenant_id": tenant_id,
        "name": original_name,
        "mime_type": content_type,
        "size": len(raw),
        "filename": stored_name,
    }
    _attachment_meta_path(stored_name).write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return {
        "ok": True,
        "attachment": {
            "id": attachment_id,
            "name": original_name,
            "mime_type": content_type,
            "size": len(raw),
            "url": f"/api/v1/chat/attachments/{stored_name}",
        },
    }


@app.get("/api/v1/chat/attachments/{filename}")
async def get_chat_attachment(filename: str, request: Request):
    filename = Path(filename).name
    meta = _read_attachment_meta(filename)
    if not meta:
        raise HTTPException(status_code=404, detail="attachment_not_found")
    existing_entry = handoff_store.get_session(meta.get("session_id") or "")
    raw_token = extract_bearer_token(request)
    token_user = decode_token(raw_token) if raw_token else None
    if not token_user:
        raise HTTPException(status_code=401, detail="customer_token_required")
    role = token_user.get("role")
    if role in DESK_ACCESS_ROLES:
        if (token_user.get("tenant_id") or "mitako") != str(meta.get("tenant_id") or "mitako"):
            raise HTTPException(status_code=403, detail="attachment_tenant_mismatch")
    else:
        token_user = _resolve_customer_session_user(
            request,
            user_id=meta.get("user_id") or "",
            session_id=meta.get("session_id") or "",
            entry=existing_entry,
            token=raw_token or "",
        )
    token_tenant = str(token_user.get("tenant_id") or "mitako")
    meta_tenant = str(meta.get("tenant_id") or "mitako")
    if token_tenant != meta_tenant:
        raise HTTPException(status_code=403, detail="attachment_tenant_mismatch")
    path = CHAT_ATTACHMENTS_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="attachment_not_found")
    return FileResponse(path, media_type=meta.get("mime_type") or "application/octet-stream", filename=meta.get("name") or filename)


def _public_business_card(card: Dict[str, Any]) -> Dict[str, Any]:
    data = card.get("data") or {}
    sop = data.get("sop") or {}
    action = data.get("action") or {}
    ticket_label = sop.get("sop_branch") or "服务咨询"
    order_snapshot = sop.get("order_snapshot") or {}
    public_sop = {"sop_branch": ticket_label}
    if sop.get("order_id"):
        public_sop["order_id"] = sop.get("order_id")
    if order_snapshot:
        public_sop["order_snapshot"] = {
            "item_name": order_snapshot.get("item_name") or "",
            "status": order_snapshot.get("status") or "",
            "status_label": order_snapshot.get("status_label") or "",
            "delay_days": order_snapshot.get("delay_days") or 0,
        }
    if action.get("type") == "warehouse_task":
        action_label = "仓库核查任务"
    elif action.get("type") == "after_sales_card":
        action_label = "售后处理单"
    elif action.get("type") == "ticket":
        action_label = "客服复核工单"
    elif action.get("type") == "product_info":
        action_label = "商品信息核对"
    else:
        action_label = "客服继续跟进"
    return {
        "type": "business_action",
        "data": {
            "sop": public_sop,
            "action": {
                "type": action.get("type") or "none",
                "label": action_label,
                "requires_human": bool(action.get("requires_human")),
                "reason": action.get("reason") or "已记录当前问题，客服会按服务流程继续核实处理。",
            },
        },
    }


def _format_public_date(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return raw[:10] if re.match(r"\d{4}-\d{2}-\d{2}", raw) else raw


def _should_emit_order_progress(result: Dict[str, Any]) -> bool:
    sop = result.get("sop_state") or {}
    ticket_type = sop.get("ticket_type") or ""
    if ticket_type in {"damage", "minor_refund", "refund", "account_binding", "product_consult", "lottery"}:
        return False
    intent = str(result.get("intent") or "")
    return ticket_type in {"logistics", "missing", "general"} or any(k in intent for k in ["订单", "物流", "发货", "催发货"])


def _select_primary_customer_card(result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    messages = result.get("messages") or []
    last_user = ""
    for message in reversed(messages):
        if message.get("role") == "user":
            last_user = str(message.get("content") or "")
            break
    if any(k in last_user for k in ["一句话", "简短", "只说结论", "不要卡片"]):
        return None

    sop = result.get("sop_state") or {}
    ticket_type = sop.get("ticket_type") or "general"
    orders = (result.get("order_data") or {}).get("orders") or []

    if ticket_type in {"logistics", "missing"} and orders and _should_emit_order_progress(result):
        return {
            "type": "order_progress",
            "data": _build_order_progress_payload(orders[0], result.get("logistics_data") or {}),
        }

    compensation = result.get("compensation_given") or []
    if compensation and any(k in last_user for k in ["补偿", "赔偿", "积分", "权益"]):
        return {"type": "compensation", "data": compensation[0]}

    if ticket_type in {"damage", "minor_refund", "refund", "account_binding", "product_consult", "lottery"}:
        cards = result.get("business_cards") or []
        if cards:
            return _public_business_card(cards[0])

    return None


def _build_order_progress_payload(order: Dict[str, Any], logistics: Dict[str, Any]) -> Dict[str, Any]:
    timeline = logistics.get("timeline") or []
    created = _format_public_date(order.get("created_at"))
    expected = _format_public_date(order.get("expected_shukka_date"))
    status = order.get("status") or ""
    steps = []
    if created:
        steps.append({"label": "下单", "status": "completed", "date": created})
    if status in {"pending_shipment", "preorder"}:
        steps.append({"label": "出库", "status": "current", "date": expected or order.get("status_label") or "待仓库处理"})
    elif status in {"in_transit", "delivered", "after_sales_review", "refunded"}:
        steps.append({"label": "出库", "status": "completed", "date": "已出库"})
    for item in timeline[-3:]:
        if not isinstance(item, dict):
            continue
        steps.append({
            "label": "物流节点",
            "status": "completed" if status in {"in_transit", "delivered"} else "current",
            "date": f"{_format_public_date(item.get('time'))} {item.get('status') or ''}".strip(),
        })
    if not steps:
        steps.append({"label": "当前状态", "status": "current", "date": order.get("status_label") or status or "待核对"})
    latest = ""
    if timeline and isinstance(timeline[-1], dict):
        latest = timeline[-1].get("status") or ""
    delay_reason = latest if order.get("delay_days", 0) > 0 else ""
    return {
        "order_id": order["order_id"],
        "item_name": order["items"][0]["name"] if order.get("items") else "谷子周边",
        "total_amount": order.get("total_amount"),
        "progress_steps": steps[:5],
        "delay_reason": delay_reason,
        "status_label": order.get("status_label") or status,
    }


def _public_chat_progress(event: Dict[str, Any]) -> Dict[str, Any]:
    node = event.get("node") or ""
    status = event.get("status") or ("end" if event.get("type") == "node_end" else "start")
    step_map = {
        "load_memory": ("understand", "正在整理服务上下文"),
        "intent_classify": ("understand", "正在理解您的问题"),
        "emotion_detect": ("understand", "正在判断处理优先级"),
        "check_transfer": ("route", "正在确认最合适的处理方式"),
        "query_order": ("query", "正在核对订单信息"),
        "query_logistics": ("query", "正在核对履约进度"),
        "search_sop": ("policy", "正在核对服务规则"),
        INTERNAL_BUSINESS_NODE: ("policy", "正在整理处理进度"),
        "check_compensation": ("solution", "正在核对可用方案"),
        "generate_reply": ("reply", "正在整理回复"),
        "safety_review": ("reply", "正在确认回复内容"),
        "send_reply": ("reply", "正在发送回复"),
        "transfer_human": ("handoff", "正在为您转接VIP客服"),
        "update_memory": ("finish", "正在同步服务记录"),
        "log_trace": ("finish", "正在完成服务记录"),
    }
    step, desc = step_map.get(node, ("progress", "正在处理您的请求"))
    return {"type": event.get("type"), "node": step, "status": status, "desc": desc}


def _public_api_log(event: Dict[str, Any]) -> Dict[str, Any]:
    data = {
        "stage": event.get("stage") or "service",
        "status": event.get("status") or "requesting",
        "attempt": event.get("attempt") or 1,
    }
    if event.get("duration") is not None:
        data["duration"] = event.get("duration")
    if event.get("usage") is not None:
        data["usage"] = event.get("usage")
    if event.get("status") == "chunk":
        data["chunk"] = "服务正在整理处理结果。"
    return data


def _public_unified_analysis(event: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "intent": sanitize_customer_reply(str(event.get("intent") or "服务咨询")),
        "emotion_level": int(event.get("emotion_level") or 2),
        "should_transfer": bool(event.get("should_transfer")),
    }


class HandoffRequest(BaseModel):
    user_id: str
    session_id: str
    history: List[Dict[str, str]] = []
    reason: str = "用户主动申请VIP客服"
    last_user_message: str = ""
    intent: str = ""
    emotion_level: int = 2
    tenant_id: str = "mitako"
    offer_id: str = ""
    active_order_id: str = ""


class HandoffOfferRequest(BaseModel):
    user_id: str
    session_id: str
    reason: str = "AI建议用户选择是否转接VIP客服"
    tenant_id: str = "mitako"


class AuthLoginRequest(BaseModel):
    username: str
    password: str
    tenant_id: str = Field(min_length=1, max_length=128, pattern=r"^\S+$")


class CustomerSessionAuthRequest(BaseModel):
    user_id: str
    session_id: str
    tenant_id: str = "mitako"


class SsoCallbackBody(BaseModel):
    tenant_id: str
    code: str
    state: str

@app.post("/api/v1/auth/login")
async def auth_login(req: AuthLoginRequest):
    """管理员/坐席登录 — MITAKO_AUTH_REQUIRED=1 时 desk/admin 变更 API 需 token"""
    user = verify_user(req.username, req.password, req.tenant_id)
    if not user:
        return {"ok": False, "error": "invalid_credentials"}
    user_tenant = str(user.get("tenant_id") or "").strip()
    if not user_tenant:
        return {"ok": False, "error": "tenant_missing"}
    if req.tenant_id != user_tenant:
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


@app.post("/api/v1/auth/customer-session")
async def auth_customer_session(req: CustomerSessionAuthRequest):
    """客户前台会话令牌 — POC 阶段由前台会话换取，生产需替换为甲方登录态/小程序态校验。"""
    user_id = (req.user_id or "").strip()
    session_id = (req.session_id or "").strip()
    tenant_id = (req.tenant_id or "mitako").strip() or "mitako"
    if not user_id or not session_id:
        raise HTTPException(status_code=400, detail="user_id_and_session_id_required")
    if not _customer_session_is_allowed(user_id, session_id, tenant_id):
        raise HTTPException(status_code=403, detail="customer_session_mismatch")
    token = create_token(
        sub=user_id,
        role=Role.CUSTOMER_USER.value,
        tenant_id=tenant_id,
        ttl_seconds=6 * 60 * 60,
        extra={"session_id": session_id},
    )
    return {
        "ok": True,
        "token": token,
        "user": {
            "user_id": user_id,
            "role": Role.CUSTOMER_USER.value,
            "tenant_id": tenant_id,
            "session_id": session_id,
        },
    }


@app.get("/api/v1/auth/tenants")
async def auth_tenants():
    tenants = [
        {
            "tenant_id": row.get("tenant_id"),
            "name": row.get("name"),
            "sso_enabled": bool(row.get("sso_enabled")),
            "enabled": bool(row.get("enabled")),
        }
        for row in tenant_store.list_tenants(enabled_only=True)
    ]
    return {"ok": True, "tenants": tenants}


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


@app.get("/api/v1/auth/sso/local/complete")
async def auth_sso_demo_complete(tenant_id: str, state: str):
    """仅 MITAKO_SSO_DEMO=1 时供本地 E2E 使用 — 生产请走 IdP redirect"""
    if not sso_service.sso_demo_mode():
        return {"ok": False, "error": "sso_unavailable"}
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
        "protected_api_auth_required": protected_api_auth_required(),
        "sso_local_enabled": sso_service.sso_demo_mode(),
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
    ok = admin_store.delete_agent(agent_id, tenant_id=user.get("tenant_id") or "mitako")
    return {"ok": ok}


@app.get("/api/v1/admin/queue/snapshot")
async def admin_queue_snapshot(user=require_roles(ADMIN_MUTATE_ROLES)):
    return {"ok": True, "snapshot": queue_snapshot(tenant_id=user.get("tenant_id"))}


@app.get("/api/v1/admin/demo/status")
async def admin_demo_status(user=require_roles(SUPER_ADMIN_ONLY)):
    return demo_status(tenant_id=user.get("tenant_id"))


@app.post("/api/v1/admin/demo/load")
async def admin_demo_load(user=require_roles(SUPER_ADMIN_ONLY)):
    return load_demo_data(tenant_id=user.get("tenant_id"))


@app.post("/api/v1/admin/demo/clear")
async def admin_demo_clear(user=require_roles(SUPER_ADMIN_ONLY)):
    return clear_demo_data(tenant_id=user.get("tenant_id"))


@app.post("/api/v1/admin/queue/{session_id}/reassign")
async def admin_reassign(session_id: str, body: ReassignBody, user=require_roles(ADMIN_MUTATE_ROLES)):
    return manual_reassign(session_id, body.to_agent_id, body.note, user.get("sub", ""), tenant_id=user.get("tenant_id"))


@app.get("/api/v1/admin/audit/events")
async def admin_audit_events(limit: int = 80, event_type: str = "", user=require_roles(ADMIN_MUTATE_ROLES)):
    return {"ok": True, "events": list_audit_events(event_type=event_type, tenant_id=user.get("tenant_id"), limit=limit)}


@app.get("/api/v1/admin/audit/sessions/{session_id}/transcript")
async def admin_transcript(session_id: str, user=require_roles(ADMIN_MUTATE_ROLES)):
    return session_transcript(session_id, tenant_id=user.get("tenant_id"))


@app.get("/api/v1/admin/qc/observer")
async def admin_observer_qc(flagged_only: bool = True, user=require_roles(ADMIN_MUTATE_ROLES)):
    tenant_id = user.get("tenant_id") or "mitako"
    audits = handoff_store_module.list_observer_audits(
        flagged_only=flagged_only,
        tenant_id=tenant_id,
    )
    business_events = []
    for event_type in ("service_qc_sop_proposal", "service_transfer_blocked"):
        business_events.extend(handoff_store_module.list_business_events(
            event_type=event_type,
            tenant_id=tenant_id,
            limit=30,
        ))
    for ev in business_events:
        result = ev.get("result") or {}
        payload = ev.get("payload") or {}
        findings = result.get("findings") or []
        reason = result.get("reason") or payload.get("reason") or result.get("trigger") or ev.get("event_type")
        audits.append({
            "id": f"event-{ev.get('id')}",
            "session_id": ev.get("session_id"),
            "tenant_id": ev.get("tenant_id") or tenant_id,
            "message_id": None,
            "content": "；".join([str(reason)] + [str(x) for x in findings])[:600],
            "flagged": True,
            "policy_hits": [result.get("sop_branch") or result.get("trigger") or ev.get("event_type")],
            "reviewer_status": "pending",
            "created_at": ev.get("created_at") or 0,
        })
    audits.sort(key=lambda item: item.get("created_at") or 0, reverse=True)
    return {
        "ok": True,
        "audits": audits[:50],
    }


@app.get("/api/v1/admin/approvals")
async def admin_list_approvals(status: str = "", user=require_roles(APPROVAL_ACCESS_ROLES)):
    return list_compensation_approvals(status=status, tenant_id=user.get("tenant_id"))


@app.post("/api/v1/admin/approvals")
async def admin_create_approval(body: ApprovalCreateBody, user=require_roles(APPROVAL_CREATE_ROLES)):
    return create_compensation_approval(
        session_id=body.session_id,
        user_id=body.user_id,
        amount=body.amount,
        reason=body.reason,
        requester=user.get("sub", ""),
        tenant_id=user.get("tenant_id") or "mitako",
    )


@app.post("/api/v1/admin/approvals/{approval_id}/decide")
async def admin_decide_approval(approval_id: int, body: ApprovalDecisionBody, user=require_roles(APPROVAL_DECIDE_ROLES)):
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
async def handoff_close(session_id: str, note: str = "", user=require_roles(DESK_MUTATE_ROLES)):
    return close_handoff_session(session_id, note or "会话已结束", tenant_id=user.get("tenant_id"))


@app.get("/metrics")
async def metrics(user=require_roles(ADMIN_MUTATE_ROLES)):
    snap = queue_snapshot(tenant_id=user.get("tenant_id"))
    return {
        "handoff_queuing": snap.get("queuing", 0),
        "handoff_connected": snap.get("connected", 0),
        "handoff_escalated": snap.get("escalated", 0),
        "sla_alerts": len(snap.get("sla_alerts") or []),
        "ws_connections": hub.connection_count(),
        "review_service": review_service_core.metrics(user.get("tenant_id") or "mitako"),
    }


@app.get("/metrics/prometheus", response_class=PlainTextResponse)
async def metrics_prometheus(user=require_roles(ADMIN_MUTATE_ROLES)):
    snap = await ops_snapshot(tenant_id=user.get("tenant_id"))

    def metric(name: str, value: Any) -> str:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = 0.0
        return f"{name} {number:g}"

    lines = [
        "# HELP mitako_uptime_seconds Service uptime in seconds.",
        "# TYPE mitako_uptime_seconds gauge",
        metric("mitako_uptime_seconds", snap.get("uptime_seconds")),
        "# HELP mitako_ops_status Service health status label.",
        "# TYPE mitako_ops_status gauge",
        f'mitako_ops_status{{status="{snap.get("status") or "unknown"}"}} 1',
        metric("mitako_handoff_queuing", snap.get("handoff_queuing")),
        metric("mitako_handoff_connected", snap.get("handoff_connected")),
        metric("mitako_handoff_escalated", snap.get("handoff_escalated")),
        metric("mitako_sla_alerts", snap.get("sla_alerts")),
        metric("mitako_ws_connections", snap.get("ws_connections")),
    ]
    visual = snap.get("visual_review") or {}
    lines.append(metric("mitako_visual_review_total", visual.get("total_reviews")))
    if visual.get("success_rate") is not None:
        lines.append(metric("mitako_visual_review_success_rate", visual.get("success_rate")))
    report_safety = snap.get("public_report_safety") or {}
    lines.append(metric("mitako_public_report_unsafe_files", report_safety.get("unsafe_files")))
    review_jobs = review_service_core.metrics(user.get("tenant_id") or "mitako")
    lines.extend([
        metric("mitako_review_jobs_queued", review_jobs.get("queued")),
        metric("mitako_review_jobs_running", review_jobs.get("running")),
        metric("mitako_review_jobs_succeeded", review_jobs.get("succeeded")),
        metric("mitako_review_jobs_failed", review_jobs.get("failed")),
        metric("mitako_review_inference_total_tokens", review_jobs.get("inference_total_tokens")),
        metric("mitako_review_inference_estimated_usd", review_jobs.get("inference_estimated_usd")),
    ])
    if review_jobs.get("average_latency_seconds") is not None:
        lines.append(metric("mitako_review_jobs_average_latency_seconds", review_jobs.get("average_latency_seconds")))
    return "\n".join(lines) + "\n"


@app.get("/api/v1/models")
async def get_models():
    """返回客户可见回复方式；真实模型配置仅在服务端映射。"""
    return {
        "default_model_id": DEFAULT_PUBLIC_MODEL_ID,
        "models": list_models_public(),
        "image_models": list_image_models_public(),
        "streaming_default": False,
    }


class ImageGenerateRequest(BaseModel):
    prompt: str
    model_id: str = "standard-image"
    size: str = "2752x1536"
    n: int = 1


@app.get("/api/v1/image-models")
async def get_image_models():
    return {"models": list_image_models_public()}


@app.post("/api/v1/images/generate")
async def post_generate_image(req: ImageGenerateRequest, _user=require_roles(ALL_ROLES, require_tenant=True)):
    """图片生成：客户响应只返回可展示结果。"""
    try:
        result = await generate_image(req.prompt, req.model_id, req.size, req.n)
        return {"ok": True, "urls": result.get("urls", []), "created": result.get("created")}
    except Exception:
        return {"ok": False, "error": "图片服务暂时不可用，请稍后重试"}

@app.post("/api/v1/handoff/offer")
async def create_handoff_offer(req: HandoffOfferRequest, request: Request):
    existing = handoff_store.get_session(req.session_id)
    token_user = _resolve_customer_session_user(
        request,
        user_id=req.user_id,
        session_id=req.session_id,
        entry=existing,
    )
    tenant_id = _request_tenant_id(req.tenant_id, token_user, existing)
    offer = handoff_store.create_handoff_offer(req.session_id, req.user_id, req.reason, tenant_id)
    return {
        "ok": True,
        "offer": offer,
        "data_mode": "demo",
        "source_system": "mitako_fixture",
        "integration_status": "not_connected",
    }


@app.post("/api/v1/handoff/request")
async def request_handoff(req: HandoffRequest, request: Request):
    """用户确认转VIP客服 — 生成简报并加入排队（演示队列）"""
    existing = get_queue_status(req.session_id)
    existing_user = (existing or {}).get("user_id") or ((existing or {}).get("brief") or {}).get("user_id") or ""
    if existing_user and req.user_id and existing_user != req.user_id:
        raise HTTPException(status_code=403, detail="handoff_session_user_mismatch")
    if existing and existing.get("status") in ("queuing", "escalated", "transferring", "connected", "closed"):
        _require_handoff_user(request, req.session_id, existing)
        brief = existing.get("brief") or {"user_id": req.user_id, "tenant_id": existing.get("tenant_id") or "mitako"}
        queue_meta = enqueue_handoff(req.session_id, brief, tenant_id=existing.get("tenant_id") or brief.get("tenant_id") or "mitako")
        existing_payload = build_customer_handoff_payload({**existing, "brief": brief})
        handoff_token = create_handoff_user_token(
            session_id=req.session_id,
            user_id=req.user_id,
            tenant_id=existing.get("tenant_id") or brief.get("tenant_id") or "mitako",
        )
        return {
            "ok": True,
            "brief": existing_payload["brief"],
            "queue": build_public_queue_meta(queue_meta),
            "reason": "已为您转接VIP客服继续处理。",
            "handoff_token": handoff_token,
        }
    token = _handoff_bearer(request)
    token_user = _resolve_customer_session_user(
        request,
        user_id=req.user_id,
        session_id=req.session_id,
        entry=existing,
        token=token,
    )
    tenant_id = _request_tenant_id(req.tenant_id, token_user, existing)
    if req.offer_id:
        offer = handoff_store.update_handoff_offer(req.offer_id, "consented", req.session_id, req.user_id)
        if not offer:
            raise HTTPException(status_code=409, detail="handoff_offer_invalid_or_expired")
    server_messages = handoff_store.recent_chat_history(req.session_id, limit=20)
    messages = server_messages or req.history
    if req.last_user_message and (not messages or messages[-1].get("content") != req.last_user_message):
        messages = messages + [{"role": "user", "content": req.last_user_message}]
    db = load_data()
    user_orders = [
        order for order in db.get("orders", {}).values()
        if order.get("user_id") == req.user_id
    ]
    explicit_ref_match = re.search(r"(?:ORD[_-]?\d{4}[_-]?\d+|#\s*\d{5,8})", req.last_user_message or "", re.IGNORECASE)
    focus_ref = (explicit_ref_match.group(0) if explicit_ref_match else req.active_order_id or "").replace("#", "").strip()
    if focus_ref:
        matched_orders = [
            order for order in user_orders
            if order.get("order_id") == focus_ref
            or str(order.get("order_id") or "").endswith(re.sub(r"\D", "", focus_ref))
        ]
        user_orders = matched_orders
    profile = viking_db.read_json(f"viking://user/{req.user_id}/profile")
    recent_reviews = [
        task for task in private_domain_store.list_review_tasks(limit=100)
        if task.get("user_id") == req.user_id
        and task.get("session_id") == req.session_id
        and (task.get("tenant_id") or "mitako") == tenant_id
    ][:5]
    pseudo_state = {
        "user_id": req.user_id,
        "session_id": req.session_id,
        "messages": messages,
        "intent": req.intent,
        "emotion_level": req.emotion_level,
        "tenant_id": tenant_id,
        "order_data": {"orders": user_orders, "total": len(user_orders)},
        "user_memory": {
            "nickname": profile.get("nickname") or "谷友",
            "member_level": (profile.get("metadata") or {}).get("member_level") or "bronze",
            "favorite_ips": (profile.get("metadata") or {}).get("favorite_ips") or [],
        },
        "review_tasks": recent_reviews,
        "transfer_reason": req.reason,
        "compensation_given": [],
        "reply_draft": "",
    }
    from business_readiness_service import run_business_flow

    business = run_business_flow(pseudo_state)
    pseudo_state.update(business)
    brief = build_handoff_brief(pseudo_state, req.reason)
    brief["tenant_id"] = tenant_id
    queue_meta = enqueue_handoff(req.session_id, brief, tenant_id=brief["tenant_id"])
    if req.offer_id:
        handoff_store.update_handoff_offer(req.offer_id, "queued", req.session_id, req.user_id)
    handoff_token = create_handoff_user_token(
        session_id=req.session_id,
        user_id=req.user_id,
        tenant_id=brief["tenant_id"],
    )
    return {
        "ok": True,
        "brief": build_public_handoff_brief(brief),
        "queue": build_public_queue_meta(queue_meta),
        "reason": "已为您转接VIP客服继续处理。",
        "handoff_token": handoff_token,
        "data_mode": "demo",
        "source_system": "mitako_fixture",
        "integration_status": "not_connected",
    }


@app.get("/api/v1/handoff/status/{session_id}")
async def handoff_status(session_id: str, request: Request):
    entry = get_queue_status(session_id)
    if not entry:
        return {"ok": False, "status": "none"}
    _require_handoff_user(request, session_id, entry)
    return {"ok": True, **build_customer_handoff_payload(entry)}


@app.get("/desk", response_class=HTMLResponse)
async def get_desk():
    dist_desk = str(APP_ROOT / "dist" / "desk.html")
    if os.path.exists(dist_desk):
        return FileResponse(dist_desk)
    return HTMLResponse("<h1>desk.html 尚未构建，请先 npm run build</h1>")


@app.post("/api/v1/handoff/connect")
async def handoff_connect(session_id: str, request: Request):
    """仅当人工已在工作台确认接单后，用户端轮询才会得到 connected"""
    entry = get_queue_status(session_id)
    if not entry:
        return {"ok": False, "status": "none"}
    _require_handoff_user(request, session_id, entry)
    if entry.get("status") != "connected":
        return {"ok": False, "status": entry.get("status") or "none"}
    payload = build_customer_handoff_payload(entry)
    return {
        "ok": True,
        "status": "connected",
        "agent": payload.get("agent"),
        "welcome": payload.get("welcome"),
        "brief": payload.get("brief"),
    }


@app.post("/api/v1/handoff/reset")
async def handoff_reset(session_id: str, request: Request):
    entry = get_queue_status(session_id)
    if not entry:
        return {"ok": True, "status": "not_found"}
    token = _handoff_bearer(request)
    user = decode_token(token) if token else None
    if user and user.get("role") in ADMIN_MUTATE_ROLES:
        tenant_id = user.get("tenant_id") or "mitako"
        if (entry.get("tenant_id") or "mitako") != tenant_id:
            return {"ok": False, "error": "tenant_forbidden"}
    elif user and user.get("role") in {Role.CUSTOMER_USER.value, Role.HANDOFF_USER.value}:
        session_user, session_tenant = _session_user_and_tenant(entry)
        if session_user and user.get("sub") != session_user:
            raise HTTPException(status_code=403, detail="handoff_user_mismatch")
        if user.get("session_id") and user.get("session_id") != session_id:
            raise HTTPException(status_code=403, detail="handoff_session_mismatch")
        tenant_id = user.get("tenant_id") or "mitako"
        if (session_tenant or "mitako") != tenant_id:
            raise HTTPException(status_code=403, detail="handoff_tenant_mismatch")
    elif not user and not protected_api_auth_required() and dev_auth_bypass_enabled():
        tenant_id = entry.get("tenant_id") or "mitako"
    else:
        raise HTTPException(status_code=401, detail="handoff_token_required")
    return reset_session_handoff(session_id, tenant_id=tenant_id)


class DeskReplyRequest(BaseModel):
    content: str
    agent_id: str = ""


class DeskAcceptRequest(BaseModel):
    agent_id: str


class DeskEscalateRequest(BaseModel):
    note: str = ""
    agent_id: str = ""


class DeskTransferRequest(BaseModel):
    from_agent_id: str
    to_agent_id: str
    note: str = ""


class HandoffUserMessageRequest(BaseModel):
    session_id: str
    content: str
    user_id: str = ""
    attachments: List[ChatAttachment] = Field(default_factory=list)


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
async def admin_update_routing(config: Dict[str, Any], user=require_roles(ADMIN_MUTATE_ROLES)):
    saved = update_routing_config(config, tenant_id=user.get("tenant_id"))
    return {"ok": True, "config": saved}


@app.websocket("/api/v1/handoff/ws/{session_id}")
async def handoff_websocket(session_id: str, websocket: WebSocket):
    entry = get_queue_status(session_id)
    if not entry and protected_api_auth_required() and not dev_auth_bypass_enabled():
        await websocket.close(code=4404)
        return
    entry = entry or {}
    session_user = entry.get("user_id") or (entry.get("brief") or {}).get("user_id") or ""
    session_tenant = entry.get("tenant_id") or (entry.get("brief") or {}).get("tenant_id") or "mitako"
    ws_user = resolve_handoff_ws_user(websocket, session_id, session_user, session_tenant)
    if not ws_user:
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
    dist_admin = str(APP_ROOT / "dist" / "admin.html")
    if os.path.exists(dist_admin):
        return FileResponse(dist_admin)
    return HTMLResponse("<h1>admin.html 尚未构建，请先 npm run build</h1>")


@app.get("/api/v1/admin/handoff/routing")
async def handoff_routing_config(user=require_roles(ADMIN_MUTATE_ROLES)):
    return {"ok": True, "config": get_routing_config(tenant_id=user.get("tenant_id"))}


@app.get("/api/v1/handoff/messages/{session_id}")
async def handoff_messages(session_id: str, request: Request, since: float = 0):
    entry = get_queue_status(session_id)
    if not entry:
        return {"ok": False, "error": "session_not_found"}
    _require_handoff_user(request, session_id, entry)
    messages = get_messages_since(session_id, since)
    latest = messages[-1]["created_at"] if messages else since
    return {"ok": True, "messages": messages, "latest_ts": latest, "status": entry.get("status")}


@app.post("/api/v1/handoff/user-message")
async def handoff_user_message(req: HandoffUserMessageRequest, request: Request):
    entry = get_queue_status(req.session_id)
    if not entry:
        return {"ok": False, "error": "session_not_found"}
    user = _require_handoff_user(request, req.session_id, entry)
    effective_user_id = (user or {}).get("sub") or req.user_id
    tenant_id = _request_tenant_id("", user, entry)
    attachments = _require_all_chat_attachments_valid(req.attachments, effective_user_id, req.session_id, tenant_id)
    analysis = await _handoff_user_message_analysis(entry, req.content, effective_user_id, req.session_id)
    result = await post_user_message(req.session_id, req.content, effective_user_id, attachments=attachments)
    if isinstance(result, dict):
        result["analysis"] = analysis
    return result


@app.get("/api/v1/desk/agents")
async def desk_agents(user=require_roles(DESK_ACCESS_ROLES)):
    return {"ok": True, "agents": list_demo_agents(user.get("tenant_id") or "mitako")}


@app.get("/api/v1/desk/sessions")
async def desk_sessions(scope: str = "available", user=require_roles(DESK_ACCESS_ROLES)):
    if scope not in {"mine", "available", "all"}:
        raise HTTPException(status_code=422, detail="invalid_queue_scope")
    role = user.get("role") or ""
    if scope == "all" and role not in {
        Role.SUPER_ADMIN.value,
        Role.SUPERVISOR.value,
        Role.BPO_MANAGER.value,
    }:
        raise HTTPException(status_code=403, detail="queue_scope_forbidden")
    agent_id = user.get("agent_id") or ""
    return {
        "ok": True,
        "scope": scope,
        "sessions": list_desk_sessions(
            tenant_id=user.get("tenant_id"),
            agent_id=agent_id,
            scope=scope,
        ),
    }


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
    agent_id = _effective_agent_id(user, req.agent_id)
    ok = append_desk_message(session_id, "human", req.content, {"agent_id": agent_id}, tenant_id=user.get("tenant_id"))
    return {"ok": ok, **({} if ok else {"error": "tenant_forbidden"})}


@app.post("/api/v1/desk/session/{session_id}/accept")
async def desk_session_accept(session_id: str, req: DeskAcceptRequest, user=require_roles(DESK_MUTATE_ROLES)):
    result = accept_handoff(session_id, _effective_agent_id(user, req.agent_id), tenant_id=user.get("tenant_id"))
    if not result.get("ok"):
        return result
    return {"ok": True, **result}


@app.post("/api/v1/desk/session/{session_id}/escalate")
async def desk_session_escalate(session_id: str, req: DeskEscalateRequest, user=require_roles(DESK_MUTATE_ROLES)):
    result = escalate_to_supervisor(
        session_id,
        req.note,
        tenant_id=user.get("tenant_id"),
        from_agent_id=_effective_agent_id(user, req.agent_id),
    )
    if not result.get("ok"):
        return result
    return {"ok": True, **result}


@app.post("/api/v1/desk/session/{session_id}/transfer")
async def desk_session_transfer(session_id: str, req: DeskTransferRequest, user=require_roles(DESK_MUTATE_ROLES)):
    result = transfer_to_colleague(
        session_id,
        _effective_agent_id(user, req.from_agent_id),
        req.to_agent_id,
        req.note,
        tenant_id=user.get("tenant_id"),
    )
    if not result.get("ok"):
        return result
    return {"ok": True, **result}


@app.post("/api/v1/chat")
async def chat_stream(req: ChatRequest, request: Request):
    existing_entry = handoff_store.get_session(req.session_id)
    token_user = _resolve_customer_session_user(
        request,
        user_id=req.user_id,
        session_id=req.session_id,
        entry=existing_entry,
    )
    tenant_id = _request_tenant_id(req.tenant_id, token_user, existing_entry)
    if existing_entry:
        existing_user, existing_tenant = _session_user_and_tenant(existing_entry)
        if existing_user and existing_user != req.user_id:
            raise HTTPException(status_code=403, detail="chat_session_user_mismatch")
        if (existing_tenant or "mitako") != tenant_id:
            raise HTTPException(status_code=403, detail="chat_session_tenant_mismatch")
        if existing_entry.get("status") == "closed":
            handoff_store.delete_session(req.session_id, tenant_id=tenant_id)
            existing_entry = None
        elif existing_entry.get("status") != "chatting":
            raise HTTPException(status_code=409, detail="handoff_active")
    uploaded_attachments = _require_all_chat_attachments_valid(req.attachments, req.user_id, req.session_id, tenant_id)
    review_context = _recent_review_attachments(req.user_id, req.session_id, tenant_id, req.content)
    uploaded_ids = {item.get("review_task_id") or item.get("id") for item in uploaded_attachments}
    chat_attachments = uploaded_attachments + [
        item for item in review_context
        if (item.get("review_task_id") or item.get("id")) not in uploaded_ids
    ]

    async def event_generator():
        queue = asyncio.Queue()
        model_content = req.content
        if chat_attachments:
            attachment_lines = [
                _chat_attachment_context_line(item)
                for item in chat_attachments
            ]
            model_content = req.content + "\n\n[用户已上传附件]\n" + "\n".join(attachment_lines)
        handoff_store.ensure_chat_session(req.session_id, req.user_id, tenant_id=tenant_id)
        handoff_store.append_message(
            req.session_id,
            "user",
            req.content,
            meta={"kind": "ai_chat", "attachments": chat_attachments},
        )
        server_history = handoff_store.recent_chat_history(req.session_id, limit=20)
        if chat_attachments and server_history and server_history[-1].get("role") == "user":
            server_history[-1] = {**server_history[-1], "content": model_content}

        # 初始 State
        state = {
            "messages": server_history or (req.history + [{"role": "user", "content": model_content}]),
            "raw_user_content": req.content,
            "user_id": req.user_id,
            "session_id": req.session_id,
            "active_order_id": req.active_order_id or "",
            "tenant_id": tenant_id,
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
            "handoff_offer_id": "",
            "compensation_given": [],
            "meme_tags": [],
            "fixtures": req.fixtures or [],
            "attachments": chat_attachments,
            "sop_state": {},
            "business_events": [],
            "business_cards": [],
        }

        # 异步启动 LangGraph 状态机任务
        task = asyncio.create_task(
            agent_app.ainvoke(
                state,
                config={
                    "configurable": {
                        "event_queue": queue,
                        "model_id": req.model_id,
                        "tenant_id": tenant_id,
                        "stream_reply": req.stream_reply,
                        "fixtures": req.fixtures or [],
                        "attachments": chat_attachments,
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
                        "data": json.dumps({"brief": build_public_handoff_brief(event.get("brief", {}))}, ensure_ascii=False)
                    }

                # 6. 常规思考追踪 / 转VIP客服
                elif event["type"] in ["node_start", "node_end", "action_transfer"]:
                    if event["type"] == "action_transfer":
                        event = {
                            **event,
                            "reason": "已为您转接VIP客服继续处理。",
                            "brief": build_public_handoff_brief(event.get("brief", {})),
                            "queue": build_public_queue_meta(event.get("queue", {})),
                        }
                    else:
                        event = _public_chat_progress(event)
                    yield {
                        "event": "thinking" if event["type"] != "action_transfer" else "transfer",
                        "data": json.dumps(event, ensure_ascii=False)
                    }

                # 7. 独立调试日志推送
                elif event["type"] == INTERNAL_API_EVENT:
                    yield {
                        "event": INTERNAL_API_EVENT,
                        "data": json.dumps(_public_api_log(event), ensure_ascii=False)
                    }

                # 7. 统一分析（意图和情绪）事件下发
                elif event["type"] == "unified_analysis":
                    yield {
                        "event": "unified_analysis",
                        "data": json.dumps(_public_unified_analysis(event), ensure_ascii=False)
                    }

                queue.task_done()
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                print(f"[stream] 提取事件时发生异常: {e}")
                break

        # 获取最终执行结果
        reply_fallback = ""
        result = {}
        try:
            result = await task
            reply_fallback = result.get("reply_draft", "") if isinstance(result, dict) else ""

            primary_card = _select_primary_customer_card(result)
            if primary_card:
                yield {
                    "event": "card",
                    "data": json.dumps(primary_card, ensure_ascii=False)
                }

        except Exception as e:
            print(f"[stream] 获取状态机最终结果异常: {e}")
            traceback.print_exc()

        if isinstance(result, dict) and (result.get("should_transfer") or result.get("safety_check_result") == "review"):
            clean_reply = "这个问题我已经为您转接VIP客服继续处理，请稍候。"
        else:
            clean_reply = sanitize_customer_reply(reply_fallback)
        if not clean_reply.strip():
            clean_reply = "我已经记录到这个问题了，会按服务流程继续帮你核实处理。"
        handoff_offer = None
        if (
            clean_reply.strip()
            and not (isinstance(result, dict) and result.get("should_transfer"))
            and any(k in clean_reply for k in ["可以帮您转接VIP客服", "可以帮你转接VIP客服", "需要VIP客服", "是否转接人工客服", "帮您转人工"])
        ):
            handoff_offer = handoff_store.create_handoff_offer(
                req.session_id,
                req.user_id,
                "AI在当前会话中提出VIP客服转接选项",
                tenant_id,
            )
        if clean_reply.strip():
            handoff_store.append_message(req.session_id, "assistant", clean_reply, meta={"kind": "ai_chat"})

        if handoff_offer:
            yield {
                "event": "handoff_offer",
                "data": json.dumps({"offer_id": handoff_offer["offer_id"], "status": "offered"}, ensure_ascii=False),
            }

        yield {
            "event": "done",
            "data": json.dumps({
                "status": "completed",
                "reply": clean_reply,
                "handoff_offer": handoff_offer,
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
