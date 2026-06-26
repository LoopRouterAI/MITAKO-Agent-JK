# -*- coding: utf-8 -*-
"""Companion C 端 API 鉴权辅助"""
from __future__ import annotations

from fastapi import HTTPException, Request

import companion_store as store
from auth.jwt_utils import companion_auth_required, decode_token
from auth.middleware import _extract_bearer
from auth.roles import Role


def _default_tenant() -> str:
    return "mitako"


def verify_companion_user(request: Request, user_id: str, *, allow_bootstrap: bool = False) -> dict:
    """Companion 用户鉴权 — 首次 onboarding 可在无 token 时 bootstrap"""
    tenant_id = _default_tenant()
    if not companion_auth_required():
        if allow_bootstrap and not store.get_persona(user_id, tenant_id):
            return {"sub": user_id, "role": Role.COMPANION_USER.value, "tenant_id": tenant_id}
        return {"sub": user_id, "role": Role.COMPANION_USER.value, "tenant_id": tenant_id}
    if allow_bootstrap and not _extract_bearer(request):
        if not store.get_persona(user_id, tenant_id):
            return {"sub": user_id, "role": Role.COMPANION_USER.value, "tenant_id": tenant_id}
    token = _extract_bearer(request)
    user = decode_token(token) if token else None
    if not user or user.get("role") != Role.COMPANION_USER.value:
        raise HTTPException(status_code=401, detail="companion_token_required")
    if user.get("sub") != user_id:
        raise HTTPException(status_code=403, detail="companion_user_mismatch")
    tenant_id = user.get("tenant_id") or _default_tenant()
    if not allow_bootstrap and not store.get_persona(user_id, tenant_id):
        raise HTTPException(status_code=404, detail="persona_not_found")
    return user


def verify_companion_session(request: Request) -> dict:
    if not companion_auth_required():
        return {"sub": "anonymous", "role": Role.COMPANION_USER.value, "tenant_id": _default_tenant()}
    token = _extract_bearer(request)
    user = decode_token(token) if token else None
    if not user or user.get("role") != Role.COMPANION_USER.value:
        raise HTTPException(status_code=401, detail="companion_token_required")
    return user
