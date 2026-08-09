# -*- coding: utf-8 -*-
"""JWT 签发与校验"""
from __future__ import annotations

import os
import secrets
import time
from typing import Any, Dict, Optional

import jwt

def _secret_literal(*parts: str) -> str:
    return "-".join(parts)


FORBIDDEN_SECRET_VALUES = {
    _secret_literal("mitako", "dev", "change", "me", "in", "production"),
    _secret_literal("mitako", "local", "demo", "secret", "change", "before", "production"),
    _secret_literal("mitako", "local", "poc", "secret", "change", "before", "production"),
}
MIN_PRODUCTION_SECRET_LENGTH = 32
RUNTIME_SECRET = secrets.token_urlsafe(48)
ALGORITHM = "HS256"
DEFAULT_TTL_SECONDS = 86400 * 7
HANDOFF_USER_TTL_SECONDS = 1800


def _secret() -> str:
    configured = os.getenv("MITAKO_JWT_SECRET", "").strip()
    if configured:
        return configured
    return RUNTIME_SECRET


def auth_required() -> bool:
    return os.getenv("MITAKO_AUTH_REQUIRED", "0").strip().lower() in ("1", "true", "yes")


def protected_api_auth_required() -> bool:
    raw = os.getenv("MITAKO_PROTECTED_API_AUTH_REQUIRED", "1").strip().lower()
    return raw not in ("0", "false", "no")


def dev_auth_bypass_enabled() -> bool:
    return os.getenv("MITAKO_DEV_AUTH_BYPASS", "0").strip().lower() in ("1", "true", "yes")


def production_secret_ok() -> bool:
    """生产环境是否配置了非默认 JWT 密钥"""
    secret = os.getenv("MITAKO_JWT_SECRET", "").strip()
    return len(secret) >= MIN_PRODUCTION_SECRET_LENGTH and secret not in FORBIDDEN_SECRET_VALUES


def enforce_jwt_secret_boundary() -> None:
    """受保护 API 开启时禁止继续使用公开默认 JWT 密钥。"""
    if production_secret_ok():
        return
    if not os.getenv("MITAKO_JWT_SECRET", "").strip():
        return
    if not protected_api_auth_required() and dev_auth_bypass_enabled():
        return
    raise RuntimeError("MITAKO_JWT_SECRET 必须配置为非默认强密钥，或显式开启本地开发绕过模式")


def create_token(
    *,
    sub: str,
    role: str,
    agent_id: str = "",
    display_name: str = "",
    tenant_id: str = "mitako",
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    extra: Optional[Dict[str, Any]] = None,
) -> str:
    enforce_jwt_secret_boundary()
    now = int(time.time())
    payload: Dict[str, Any] = {
        "sub": sub,
        "role": role,
        "agent_id": agent_id,
        "display_name": display_name or sub,
        "tenant_id": tenant_id,
        "iat": now,
        "exp": now + ttl_seconds,
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, _secret(), algorithm=ALGORITHM)


def create_handoff_user_token(*, session_id: str, user_id: str, tenant_id: str = "mitako") -> str:
    from auth.roles import Role

    return create_token(
        sub=user_id,
        role=Role.HANDOFF_USER.value,
        tenant_id=tenant_id,
        ttl_seconds=HANDOFF_USER_TTL_SECONDS,
        extra={"session_id": session_id},
    )


def decode_token(token: str) -> Optional[Dict[str, Any]]:
    enforce_jwt_secret_boundary()
    try:
        return jwt.decode(token, _secret(), algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
