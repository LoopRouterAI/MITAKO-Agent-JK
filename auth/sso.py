# -*- coding: utf-8 -*-
"""OIDC SSO — 多租户单点登录。"""
from __future__ import annotations

import json
import os
import secrets
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx

import auth.tenants as tenant_store
from auth import sso_state
from auth.roles import Role
from partner_guard import assert_local_or_allowed

# 仅 E2E/本地显式开启；生产默认关闭本地直连入口
_DEMO_CODE = "demo_ok"


def sso_demo_mode() -> bool:
    return os.getenv("MITAKO_SSO_DEMO", "0").strip().lower() in ("1", "true", "yes")


def build_authorize_url(tenant_id: str) -> Dict[str, Any]:
    tenant = tenant_store.get_tenant(tenant_id)
    if not tenant or not tenant.get("sso_enabled"):
        return {"ok": False, "error": "sso_not_enabled"}
    state = secrets.token_urlsafe(16)
    sso_state.save_state(state, {"tenant_id": tenant_id, "ts": time.time()})
    if sso_demo_mode():
        return {
            "ok": True,
            "mode": "local",
            "local_enabled": True,
            "local_callback_url": f"/api/v1/auth/sso/local/complete?tenant_id={tenant_id}&state={state}",
            "authorize_url": f"/api/v1/auth/sso/local/complete?tenant_id={tenant_id}&state={state}",
            "state": state,
        }
    params = {
        "client_id": tenant["oidc_client_id"],
        "response_type": "code",
        "scope": tenant.get("oidc_scopes") or "openid profile email",
        "redirect_uri": tenant["oidc_redirect_uri"],
        "state": state,
    }
    issuer = (tenant["oidc_issuer"] or "").rstrip("/")
    if not issuer or not tenant.get("oidc_client_id"):
        return {"ok": False, "error": "oidc_not_configured"}
    return {
        "ok": True,
        "mode": "oidc",
        "local_enabled": False,
        "authorize_url": f"{issuer}/oauth/authorize?{urlencode(params)}",
        "state": state,
    }


def _validate_state(tenant_id: str, state: str) -> Optional[Dict[str, Any]]:
    pending = sso_state.pop_state(state)
    if not pending or pending.get("tenant_id") != tenant_id:
        return None
    if time.time() - float(pending.get("ts", 0)) > 600:
        return None
    return pending


def exchange_code(tenant_id: str, code: str, state: str) -> Dict[str, Any]:
    if not _validate_state(tenant_id, state):
        return {"ok": False, "error": "invalid_state"}
    tenant = tenant_store.get_tenant(tenant_id)
    if not tenant:
        return {"ok": False, "error": "tenant_not_found"}
    if sso_demo_mode() and code == _DEMO_CODE:
        return {
            "ok": True,
            "profile": {
                "sub": f"sso_{tenant_id}_admin",
                "email": f"admin@{tenant_id}.local",
                "name": f"{tenant['name']} SSO 用户",
                "groups": ["mitako-admin"],
            },
        }
    if not sso_demo_mode() and code == _DEMO_CODE:
        return {"ok": False, "error": "demo_disabled"}
    return {"ok": False, "error": "oidc_exchange_requires_async"}


async def exchange_code_async(tenant_id: str, code: str, state: str) -> Dict[str, Any]:
    if not _validate_state(tenant_id, state):
        return {"ok": False, "error": "invalid_state"}
    tenant = tenant_store.get_tenant(tenant_id)
    if not tenant:
        return {"ok": False, "error": "tenant_not_found"}
    if sso_demo_mode() and code == _DEMO_CODE:
        return exchange_code(tenant_id, code, state)
    if not sso_demo_mode() and code == _DEMO_CODE:
        return {"ok": False, "error": "demo_disabled"}
    issuer = (tenant.get("oidc_issuer") or "").rstrip("/")
    token_url = tenant.get("oidc_token_url") or f"{issuer}/oauth/token"
    userinfo_url = tenant.get("oidc_userinfo_url") or f"{issuer}/oauth/userinfo"
    client_secret = tenant_store.get_tenant_secret(tenant_id)
    if not issuer or not tenant.get("oidc_client_id") or not client_secret:
        return {"ok": False, "error": "oidc_not_configured"}
    try:
        token_url = assert_local_or_allowed(token_url, "OIDC token URL")
        userinfo_url = assert_local_or_allowed(userinfo_url, "OIDC userinfo URL")
    except RuntimeError as e:
        print(f"[sso] blocked partner api: {e}")
        return {"ok": False, "error": "real_partner_api_blocked"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            tr = await client.post(
                token_url,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": tenant["oidc_redirect_uri"],
                    "client_id": tenant["oidc_client_id"],
                    "client_secret": client_secret,
                },
                headers={"Accept": "application/json"},
            )
            if tr.status_code >= 400:
                print(f"[sso] token exchange failed: status={tr.status_code} body={tr.text[:200]}")
                return {"ok": False, "error": "token_exchange_failed"}
            token_data = tr.json()
            access_token = token_data.get("access_token")
            if not access_token:
                return {"ok": False, "error": "no_access_token"}
            ur = await client.get(
                userinfo_url,
                headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            )
            if ur.status_code >= 400:
                print(f"[sso] userinfo failed: status={ur.status_code} body={ur.text[:200]}")
                return {"ok": False, "error": "userinfo_failed"}
            profile = ur.json()
            return {"ok": True, "profile": profile}
    except Exception as e:
        print(f"[sso] oidc exchange error: {e}")
        return {"ok": False, "error": "oidc_exchange_error"}


def _groups_from_profile(profile: Dict[str, Any]) -> List[str]:
    groups = profile.get("groups") or profile.get("roles") or []
    if isinstance(groups, str):
        return [groups]
    if isinstance(groups, list):
        return [str(g) for g in groups]
    return []


def map_sso_profile_to_user(profile: Dict[str, Any], tenant_id: str) -> Dict[str, Any]:
    mapping = tenant_store.get_role_mapping(tenant_id)
    groups = _groups_from_profile(profile)
    role = Role.DESK_AGENT.value
    for mapped_role, group_list in mapping.items():
        if any(g in groups for g in group_list):
            role = mapped_role
            break
    # 最高权限组优先
    priority = [
        Role.SUPER_ADMIN.value,
        Role.SUPERVISOR.value,
        Role.BPO_MANAGER.value,
        Role.QC_VIEWER.value,
        Role.DESK_AGENT.value,
    ]
    matched = [r for r in priority if r in {k for k, gs in mapping.items() if any(g in groups for g in gs)}]
    if matched:
        role = matched[0]
    username = profile.get("sub") or profile.get("email") or profile.get("preferred_username") or "sso_user"
    return {
        "username": str(username),
        "role": role,
        "agent_id": profile.get("agent_id") or "",
        "display_name": profile.get("name") or profile.get("email") or str(username),
        "tenant_id": tenant_id,
    }
