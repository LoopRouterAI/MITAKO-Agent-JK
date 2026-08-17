# -*- coding: utf-8 -*-
"""高级客服审核策略治理 API；仅公开业务策略字段。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from auth.middleware import require_roles
from auth.roles import PROMPT_GOVERNANCE_ROLES
from review_service import policy_governance


router = APIRouter(prefix="/api/v1/admin/review-policies", tags=["review-policy-governance"])


class PolicyBody(BaseModel):
    policy: dict
    reason: str = Field(min_length=6, max_length=500)
    expected_active_version: int = 0


class RollbackBody(BaseModel):
    target_version: int
    reason: str = Field(min_length=6, max_length=500)
    expected_active_version: int = 0


def _tenant(user: dict) -> str:
    tenant = str(user.get("tenant_id") or "").strip()
    if not tenant:
        raise HTTPException(status_code=403, detail="tenant_claim_required")
    return tenant


def _actor(user: dict) -> str:
    return str(user.get("sub") or user.get("agent_id") or "").strip()


@router.get("")
def get_policy(user: dict = require_roles(PROMPT_GOVERNANCE_ROLES, require_tenant=True)):
    tenant = _tenant(user)
    return {"ok": True, "policy": policy_governance.get_active_policy(tenant), "versions": policy_governance.list_versions(tenant)}


@router.post("/versions")
def publish(body: PolicyBody, user: dict = require_roles(PROMPT_GOVERNANCE_ROLES, require_tenant=True)):
    try:
        policy = policy_governance.publish_policy(
            tenant_id=_tenant(user), policy=body.policy, reason=body.reason,
            actor=_actor(user), actor_role=str(user.get("role") or ""),
            expected_active_version=body.expected_active_version,
        )
    except policy_governance.VersionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True, "policy": policy}


@router.post("/rollback")
def rollback(body: RollbackBody, user: dict = require_roles(PROMPT_GOVERNANCE_ROLES, require_tenant=True)):
    try:
        policy = policy_governance.rollback_policy(
            tenant_id=_tenant(user), target_version=body.target_version,
            reason=body.reason, actor=_actor(user), actor_role=str(user.get("role") or ""),
            expected_active_version=body.expected_active_version,
        )
    except policy_governance.VersionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "policy": policy}
