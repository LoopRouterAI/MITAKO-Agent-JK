# -*- coding: utf-8 -*-
"""JWT 签发与校验"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

import jwt

DEFAULT_SECRET = "mitako-dev-change-me-in-production"
ALGORITHM = "HS256"
DEFAULT_TTL_SECONDS = 86400 * 7
COMPANION_TTL_SECONDS = 86400 * 30
HANDOFF_USER_TTL_SECONDS = 86400


def _secret() -> str:
    return os.getenv("MITAKO_JWT_SECRET", DEFAULT_SECRET)


def auth_required() -> bool:
    return os.getenv("MITAKO_AUTH_REQUIRED", "0").strip().lower() in ("1", "true", "yes")


def companion_auth_required() -> bool:
    raw = os.getenv("MITAKO_COMPANION_AUTH_REQUIRED", "").strip().lower()
    if raw in ("1", "true", "yes"):
        return True
    if raw in ("0", "false", "no"):
        return False
    return auth_required()


def production_secret_ok() -> bool:
    """生产环境是否配置了非默认 JWT 密钥"""
    secret = _secret()
    return bool(secret) and secret != DEFAULT_SECRET


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


def create_companion_token(user_id: str, tenant_id: str = "mitako") -> str:
    from auth.roles import Role

    return create_token(
        sub=user_id,
        role=Role.COMPANION_USER.value,
        display_name=user_id,
        tenant_id=tenant_id,
        ttl_seconds=COMPANION_TTL_SECONDS,
    )


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
    try:
        return jwt.decode(token, _secret(), algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
