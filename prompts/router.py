# -*- coding: utf-8 -*-
"""高级客服业务规则版本管理 API；不返回内部基础提示词。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from auth.middleware import require_roles
from auth.roles import PROMPT_GOVERNANCE_ROLES
from prompts import governance_store
from prompts.catalog import ensure_rule_key, list_rule_catalog


router = APIRouter(prefix="/api/v1/admin/business-rules", tags=["business-rule-governance"])


class PublishBody(BaseModel):
    mode: str
    content: str
    reason: str
    expected_active_version: int


class RollbackBody(BaseModel):
    target_version: int
    reason: str
    expected_active_version: int


def _tenant(user: dict) -> str:
    tenant_id = str(user.get("tenant_id") or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=403, detail="tenant_claim_required")
    return tenant_id


def _actor(user: dict) -> str:
    return str(user.get("sub") or user.get("agent_id") or "").strip()


@router.get("")
def list_rules(user: dict = require_roles(PROMPT_GOVERNANCE_ROLES)):
    tenant_id = _tenant(user)
    rules = []
    for item in list_rule_catalog():
        rules.append({**item, "active_version": governance_store.get_active_version(tenant_id, item["key"])})
    return {"ok": True, "rules": rules}


@router.get("/{prompt_key:path}/versions")
def get_versions(prompt_key: str, user: dict = require_roles(PROMPT_GOVERNANCE_ROLES)):
    try:
        key = ensure_rule_key(prompt_key)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    tenant_id = _tenant(user)
    return {
        "ok": True,
        "versions": governance_store.list_versions(tenant_id, key),
        "audit": governance_store.list_audit(tenant_id, key),
    }


@router.post("/{prompt_key:path}/versions")
def publish(prompt_key: str, body: PublishBody, user: dict = require_roles(PROMPT_GOVERNANCE_ROLES)):
    try:
        version = governance_store.publish_version(
            tenant_id=_tenant(user),
            prompt_key=prompt_key,
            mode=body.mode,
            content=body.content,
            reason=body.reason,
            actor=_actor(user),
            actor_role=str(user.get("role") or ""),
            expected_active_version=body.expected_active_version,
        )
    except governance_store.VersionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True, "version": version}


@router.post("/{prompt_key:path}/rollback")
def rollback(prompt_key: str, body: RollbackBody, user: dict = require_roles(PROMPT_GOVERNANCE_ROLES)):
    try:
        version = governance_store.rollback_version(
            tenant_id=_tenant(user),
            prompt_key=prompt_key,
            target_version=body.target_version,
            reason=body.reason,
            actor=_actor(user),
            actor_role=str(user.get("role") or ""),
            expected_active_version=body.expected_active_version,
        )
    except governance_store.VersionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "version": version}
