# -*- coding: utf-8 -*-
"""FastAPI 鉴权依赖 — 后台/坐席默认保护，开发旁路需显式开启。"""
from __future__ import annotations

from typing import FrozenSet, Optional

from fastapi import Depends, HTTPException, Request, WebSocket
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from auth.jwt_utils import auth_required, decode_token, dev_auth_bypass_enabled, protected_api_auth_required
from auth.roles import Role


_bearer_scheme = HTTPBearer(auto_error=False)


def _extract_bearer(request: Request) -> Optional[str]:
    auth = request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def extract_bearer_token(request: Request) -> Optional[str]:
    return _extract_bearer(request)


def extract_ws_token(websocket: WebSocket) -> Optional[str]:
    protocol = websocket.headers.get("sec-websocket-protocol") or ""
    for part in protocol.split(","):
        part = part.strip()
        if part.startswith("handoff."):
            return part[len("handoff.") :].strip()
    import os

    if os.getenv("MITAKO_ALLOW_HANDOFF_QUERY_TOKEN", "0").strip().lower() in {"1", "true", "yes"}:
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


def require_roles(allowed: FrozenSet[str], *, require_tenant: bool = False):
    """返回 FastAPI Depends；后台/坐席 API 默认必须登录。"""

    def _dep(
        request: Request,
        _credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    ) -> dict:
        def authorize(user: dict) -> dict:
            if user.get("role") not in allowed:
                raise HTTPException(status_code=403, detail="权限不足")
            if require_tenant and not str(user.get("tenant_id") or "").strip():
                raise HTTPException(status_code=403, detail="tenant_claim_required")
            return user

        if not protected_api_auth_required():
            # 鉴权关闭时仍优先解析 Bearer，便于 E2E 验证职责分离等身份相关逻辑
            user = get_current_user_optional(request)
            if user:
                return authorize(user)
            if not dev_auth_bypass_enabled():
                raise HTTPException(status_code=401, detail="protected_api_token_required")
            return _synthetic_super_admin()
        user = get_current_user_optional(request)
        if not user:
            raise HTTPException(status_code=401, detail="未登录或 token 无效")
        return authorize(user)

    return Depends(_dep)


def tenant_allowed(user: dict, tenant_id: str) -> bool:
    if not protected_api_auth_required() and dev_auth_bypass_enabled():
        return True
    user_tenant = str(user.get("tenant_id") or "").strip()
    target_tenant = str(tenant_id or "").strip()
    return bool(user_tenant and target_tenant and user_tenant == target_tenant)


def assert_tenant_access(user: dict, tenant_id: str) -> None:
    if not tenant_allowed(user, tenant_id):
        raise HTTPException(status_code=403, detail="tenant_forbidden")


def resolve_handoff_ws_user(websocket: WebSocket, session_id: str, session_user_id: str, session_tenant: str) -> Optional[dict]:
    """WebSocket 连接鉴权 — 坐席 JWT 或当前客户会话 token。"""
    from auth.roles import DESK_ACCESS_ROLES

    if not protected_api_auth_required() and dev_auth_bypass_enabled():
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
    if role in {Role.CUSTOMER_USER.value, Role.HANDOFF_USER.value}:
        if user.get("sub") != session_user_id:
            return None
        if user.get("session_id") and user.get("session_id") != session_id:
            return None
        if not tenant_allowed(user, session_tenant):
            return None
        return user
    return None
