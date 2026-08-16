# -*- coding: utf-8 -*-
"""超级管理员视觉审核模型治理 API。"""
from __future__ import annotations

import time

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from auth.middleware import require_roles
from auth.roles import Role
from configs import model_governance
from configs.model_catalog import MODEL_CONFIGS
from poc.visual_review_poc.model_auth import gemini_channel_options


router = APIRouter(prefix="/api/v1/admin/review-models", tags=["review-model-governance"])
_SUPER_ADMIN = frozenset({Role.SUPER_ADMIN.value})


class PublishBody(BaseModel):
    default_model: str
    enabled_models: list[str]
    reason: str
    expected_active_version: int


class RollbackBody(BaseModel):
    target_version: int
    reason: str
    expected_active_version: int


def _tenant(user: dict) -> str:
    return str(user.get("tenant_id") or "").strip()


def _actor(user: dict) -> str:
    return str(user.get("sub") or user.get("agent_id") or "").strip()


def _run_baidu_smoke(model_key: str) -> dict:
    config = MODEL_CONFIGS.get(model_key)
    if config is None:
        raise LookupError("未知审核模型")
    option = next(
        (
            item
            for item in gemini_channel_options(str(config["model"]))
            if item.get("channel") == "baidu"
        ),
        None,
    )
    if option is None:
        raise RuntimeError("百度云 Gemini 渠道尚未完成配置")

    started = time.monotonic()
    with httpx.Client(timeout=httpx.Timeout(45.0, connect=10.0), trust_env=False) as client:
        response = client.post(
            option["endpoint"],
            headers=option["headers"],
            json={"contents": [{"role": "user", "parts": [{"text": "仅回复 OK"}]}]},
        )
        response.raise_for_status()
    data = response.json()
    request_id = next(
        (
            str(response.headers.get(name) or "").strip()
            for name in ("x-bce-request-id", "x-request-id", "x-goog-request-id", "request-id")
            if str(response.headers.get(name) or "").strip()
        ),
        "",
    )
    return {
        "ok": True,
        "model": str(config["model"]),
        "status_code": int(response.status_code),
        "latency_seconds": round(time.monotonic() - started, 3),
        "request_id": request_id,
        "usage": data.get("usageMetadata") if isinstance(data.get("usageMetadata"), dict) else {},
    }


@router.get("")
def get_state(user: dict = require_roles(_SUPER_ADMIN, require_tenant=True)):
    tenant_id = _tenant(user)
    return {
        "ok": True,
        "state": model_governance.get_model_state(tenant_id),
        "versions": model_governance.list_versions(tenant_id),
    }


@router.post("/versions")
def publish(body: PublishBody, user: dict = require_roles(_SUPER_ADMIN, require_tenant=True)):
    try:
        state = model_governance.publish_config(
            tenant_id=_tenant(user),
            default_model=body.default_model,
            enabled_models=body.enabled_models,
            reason=body.reason,
            actor=_actor(user),
            actor_role=str(user.get("role") or ""),
            expected_active_version=body.expected_active_version,
        )
    except model_governance.VersionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True, "state": state}


@router.post("/rollback")
def rollback(body: RollbackBody, user: dict = require_roles(_SUPER_ADMIN, require_tenant=True)):
    try:
        state = model_governance.rollback_config(
            tenant_id=_tenant(user),
            target_version=body.target_version,
            reason=body.reason,
            actor=_actor(user),
            actor_role=str(user.get("role") or ""),
            expected_active_version=body.expected_active_version,
        )
    except model_governance.VersionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "state": state}


@router.post("/{model_key}/smoke")
def smoke(model_key: str, _user: dict = require_roles(_SUPER_ADMIN, require_tenant=True)):
    try:
        return _run_baidu_smoke(model_key)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RuntimeError, httpx.HTTPError, ValueError):
        raise HTTPException(status_code=503, detail="百度云模型冒烟失败，请检查渠道配置或稍后重试")
