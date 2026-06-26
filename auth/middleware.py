# -*- coding: utf-8 -*-
"""FastAPI 鉴权依赖 — MITAKO_AUTH_REQUIRED=1 时生效"""
from __future__ import annotations

from typing import FrozenSet, Optional

from fastapi import Depends, HTTPException, Request, WebSocket

from auth.jwt_utils import auth_required, companion_auth_required, decode_token
from auth.roles import Role


def _extract_bearer(request: Request) -> Optional[str]:
    auth = request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def extract_bearer_token(request: Request) -> Optional[str]:
    return _extract_bearer(request)


def extract_ws_token(websocket: WebSocket) -> Optional[str]:
    token = websocket.query_params.get("token")
    if token:
        return token.strip()
    auth = websocket.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def get_current_user_optional(request: Request) -> Optional[dict]:
    token = _extract_bearer(request)
    if not token:
        return None
    return decode_token(token)


def _synthetic_super_admin() -> dict:
    return {
        "sub": "e2e",
        "role": Role.SUPER_ADMIN.value,
        "agent_id": "",
        "display_name": "E2E",
        "tenant_id": "mitako",
    }


def require_roles(allowed: FrozenSet[str]):
    """返回 FastAPI Depends；鉴权关闭时返回 synthetic super_admin"""

    def _dep(request: Request) -> dict:
        if not auth_required():
            # 鉴权关闭时仍优先解析 Bearer，便于 E2E 验证职责分离等身份相关逻辑
            user = get_current_user_optional(request)
            if user:
                return user
            return _synthetic_super_admin()
        user = get_current_user_optional(request)
        if not user:
            raise HTTPException(status_code=401, detail="未登录或 token 无效")
        if user.get("role") not in allowed:
            raise HTTPException(status_code=403, detail="权限不足")
        return user

    return Depends(_dep)


def require_companion_user(expected_user_id: str):
    """Companion C 端 API — token.sub 必须与 user_id 一致"""

    def _dep(request: Request) -> dict:
        if not companion_auth_required():
            return {"sub": expected_user_id, "role": Role.COMPANION_USER.value, "tenant_id": "mitako"}
        token = _extract_bearer(request)
        user = decode_token(token) if token else None
        if not user or user.get("role") != Role.COMPANION_USER.value:
            raise HTTPException(status_code=401, detail="companion_token_required")
        if user.get("sub") != expected_user_id:
            raise HTTPException(status_code=403, detail="companion_user_mismatch")
        return user

    return Depends(_dep)


def tenant_allowed(user: dict, tenant_id: str) -> bool:
    if not auth_required():
        return True
    return (user.get("tenant_id") or "mitako") == (tenant_id or "mitako")


def assert_tenant_access(user: dict, tenant_id: str) -> None:
    if not tenant_allowed(user, tenant_id):
        raise HTTPException(status_code=403, detail="tenant_forbidden")


def resolve_handoff_ws_user(websocket: WebSocket, session_id: str, session_user_id: str, session_tenant: str) -> Optional[dict]:
    """WebSocket 连接鉴权 — 坐席 JWT 或 handoff_user 会话 token"""
    from auth.roles import DESK_ACCESS_ROLES

    if not auth_required():
        return _synthetic_super_admin()
    token = extract_ws_token(websocket)
    user = decode_token(token) if token else None
    if not user:
        return None
    role = user.get("role")
    if role in DESK_ACCESS_ROLES:
        if not tenant_allowed(user, session_tenant):
            return None
        return user
    if role == Role.HANDOFF_USER.value:
        if user.get("sub") != session_user_id:
            return None
        if user.get("session_id") and user.get("session_id") != session_id:
            return None
        if not tenant_allowed(user, session_tenant):
            return None
        return user
    return None
