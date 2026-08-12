# -*- coding: utf-8 -*-
"""私域 Agent API：后台可追踪，用户上传材料可创建审核任务。"""
from __future__ import annotations

import json
from typing import Any, Dict

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Request, UploadFile

from auth.jwt_utils import decode_token, dev_auth_bypass_enabled, protected_api_auth_required
from auth.middleware import extract_bearer_token, require_roles
from auth.roles import ADMIN_MUTATE_ROLES, Role

from .schemas import (
    ContractsResponse,
    DashboardResponse,
    DemoClearResponse,
    DemoLoadResponse,
    GroupMessageIn,
    GroupMessageResponse,
    ProductEventIn,
    ProductEventResponse,
    ReviewTaskDetailResponse,
    ReviewTaskUploadResponse,
)
from . import service, store


router = APIRouter(prefix="/api/v1/private-domain", tags=["private-domain"])


def _admin_user():
    return require_roles(ADMIN_MUTATE_ROLES, require_tenant=True)


def _customer_user(request: Request, user_id: str, session_id: str) -> Dict[str, Any]:
    token = extract_bearer_token(request)
    user = decode_token(token) if token else None
    if not user:
        if protected_api_auth_required() and not dev_auth_bypass_enabled():
            raise HTTPException(status_code=401, detail="customer_token_required")
        return {"sub": user_id, "role": Role.CUSTOMER_USER.value, "tenant_id": "mitako", "session_id": session_id}
    if user.get("role") not in {Role.CUSTOMER_USER.value, Role.HANDOFF_USER.value}:
        raise HTTPException(status_code=403, detail="customer_token_required")
    if user.get("sub") and user.get("sub") != user_id:
        raise HTTPException(status_code=403, detail="review_task_user_mismatch")
    if user.get("session_id") and user.get("session_id") != session_id:
        raise HTTPException(status_code=403, detail="review_task_session_mismatch")
    return user


def _assert_review_task_access(request: Request, task: Dict[str, Any]) -> None:
    token = extract_bearer_token(request)
    user = decode_token(token) if token else None
    if not user:
        if not protected_api_auth_required() and dev_auth_bypass_enabled():
            return
        raise HTTPException(status_code=401, detail="review_task_token_required")

    role = user.get("role")
    if role not in ADMIN_MUTATE_ROLES | {Role.CUSTOMER_USER.value, Role.HANDOFF_USER.value}:
        raise HTTPException(status_code=403, detail="review_task_forbidden")
    if not user.get("tenant_id") or user.get("tenant_id") != task.get("tenant_id"):
        raise HTTPException(status_code=403, detail="review_task_tenant_mismatch")
    if role in ADMIN_MUTATE_ROLES:
        return
    if user.get("sub") != task.get("user_id"):
        raise HTTPException(status_code=403, detail="review_task_user_mismatch")
    if user.get("session_id") and user.get("session_id") != task.get("session_id"):
        raise HTTPException(status_code=403, detail="review_task_session_mismatch")


@router.on_event("startup")
async def startup() -> None:
    store.init_db()


@router.get("/dashboard", response_model=DashboardResponse)
async def dashboard(user=_admin_user()):
    return {"ok": True, **service.dashboard_payload(tenant_id=user["tenant_id"])}


@router.get("/contracts", response_model=ContractsResponse)
async def contracts(user=_admin_user()):
    return {"ok": True, "integration_contracts": service.integration_contracts()}


@router.post("/demo/load", response_model=DemoLoadResponse)
async def demo_load(user=_admin_user()):
    return {"ok": True, **service.load_demo_data(tenant_id=user["tenant_id"])}


@router.post("/demo/clear", response_model=DemoClearResponse)
async def demo_clear(user=_admin_user()):
    return {"ok": True, **service.clear_demo_data(tenant_id=user["tenant_id"])}


@router.post("/group-message", response_model=GroupMessageResponse)
async def group_message(payload: GroupMessageIn, user=_admin_user()):
    try:
        return {
            "ok": True,
            **service.process_group_message(
                payload.model_dump(exclude_none=True), tenant_id=user["tenant_id"]
            ),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/product-event", response_model=ProductEventResponse)
async def product_event(payload: ProductEventIn, user=_admin_user()):
    try:
        return {
            "ok": True,
            **service.process_product_event(
                payload.model_dump(exclude_none=True), tenant_id=user["tenant_id"]
            ),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/review-tasks", response_model=ReviewTaskUploadResponse)
async def review_task_upload(
    request: Request,
    background_tasks: BackgroundTasks,
    user_id: str = Form(...),
    session_id: str = Form(...),
    source: str = Form("customer_upload"),
    client_case_id: str = Form(""),
    order_id: str = Form(""),
    scenario: str = Form(""),
    context_json: str = Form("{}"),
    async_review: bool = Form(False),
    file: UploadFile = File(...),
):
    user = _customer_user(request, user_id, session_id)
    mime_type = (file.content_type or "").split(";", 1)[0].strip().lower()
    raw = await file.read(300 * 1024 * 1024 + 1)
    try:
        context = json.loads(context_json or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="invalid_context_json") from exc
    if not isinstance(context, dict):
        raise HTTPException(status_code=422, detail="context_json_must_be_object")
    try:
        task = service.create_review_task_from_upload(
            user_id=user_id,
            session_id=session_id,
            tenant_id=user.get("tenant_id") or "mitako",
            file_name=file.filename or "material",
            mime_type=mime_type,
            raw=raw,
            source=source,
            client_case_id=client_case_id,
            order_id=order_id,
            scenario=scenario,
            context=context,
            run_review=not async_review,
        )
        if async_review:
            background_tasks.add_task(service.run_visual_review_for_task, task["task_id"])
    except ValueError as exc:
        detail = str(exc)
        status = 413 if detail == "file_too_large" else 415 if detail == "unsupported_review_material" else 422 if detail == "unsupported_review_scenario" else 400
        if detail == "file_too_large":
            raise HTTPException(status_code=status, detail={
                "error": detail,
                "message": "聊天附件入口单文件上限为 300MB；大文件请使用标准审核服务或对象存储直传方案。",
                "recommended_endpoint": "/api/v1/review/jobs",
                "object_storage": {"integration_status": "customer_integration_required", "write_effect": "none"},
            }) from exc
        raise HTTPException(status_code=status, detail=detail) from exc
    return {
        "ok": True,
        "review_task": task,
        "attachment": {
            "id": task["task_id"],
            "kind": "review_task",
            "review_task_id": task["task_id"],
            "name": task["file_name"],
            "mime_type": task["mime_type"],
            "size": task["size"],
            "status": task["status"],
            "scenario": task["scenario"],
            "boundary": task.get("boundary") or "",
            "review_result": task.get("result") or {},
            "reviewed_at": task.get("reviewed_at") or 0,
            "url": f"/api/v1/private-domain/review-tasks/{task['task_id']}",
        },
    }


@router.get("/review-tasks")
async def review_task_list(
    request: Request,
    user_id: str,
    session_id: str,
    order_id: str = "",
    client_case_id: str = "",
):
    user = _customer_user(request, user_id, session_id)
    tenant_id = user.get("tenant_id") or "mitako"
    tasks = [
        task for task in store.list_review_tasks(limit=100, tenant_id=tenant_id)
        if task.get("user_id") == user_id
        and task.get("session_id") == session_id
        and (task.get("tenant_id") or "mitako") == tenant_id
        and (not order_id or task.get("order_id") == order_id)
        and (not client_case_id or task.get("client_case_id") == client_case_id)
    ]
    return {
        "ok": True,
        "review_tasks": tasks,
        "data_mode": "demo",
        "source_system": "mitako_fixture",
        "integration_status": "not_connected",
    }


@router.get("/review-tasks/{task_id}", response_model=ReviewTaskDetailResponse)
async def review_task_detail(task_id: str, request: Request):
    task = store.get_review_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="review_task_not_found")
    _assert_review_task_access(request, task)
    return {"ok": True, "review_task": task}
