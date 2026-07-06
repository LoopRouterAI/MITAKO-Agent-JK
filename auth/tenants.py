# -*- coding: utf-8 -*-
"""多租户配置 — auth.db"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

from runtime_paths import db_path

_AUTH_DB_PATH = db_path("MITAKO_AUTH_DB_PATH", "auth.db")
_DB_DIR = str(_AUTH_DB_PATH.parent)
_DB_PATH = str(_AUTH_DB_PATH)
_lock = threading.RLock()
_db_ready = False

_DEFAULT_ROLE_MAPPING = {
    "super_admin": ["mitako-admin", "admin"],
    "supervisor": ["mitako-supervisor"],
    "bpo_manager": ["mitako-bpo"],
    "desk_agent": ["mitako-desk"],
    "qc_viewer": ["mitako-qc"],
}

_DEMO_TENANTS = [
    {
        "tenant_id": "mitako",
        "name": "MITAKO 官方",
        "sso_enabled": 0,
        "oidc_issuer": "",
        "oidc_client_id": "",
        "oidc_redirect_uri": "http://127.0.0.1:8000/admin?sso=1",
    },
    {
        "tenant_id": "bpo-east",
        "name": "客服中心·华东组",
        "sso_enabled": 1,
        "oidc_issuer": "https://demo-idp.local",
        "oidc_client_id": "mitako-bpo-east",
        "oidc_redirect_uri": "http://127.0.0.1:8000/admin?sso=1",
    },
]


def _ensure_db() -> None:
    global _db_ready
    if _db_ready:
        return
    os.makedirs(_DB_DIR, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tenants (
                tenant_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                sso_enabled INTEGER DEFAULT 0,
                oidc_issuer TEXT,
                oidc_client_id TEXT,
                oidc_client_secret TEXT,
                oidc_redirect_uri TEXT,
                enabled INTEGER DEFAULT 1,
                created_at REAL,
                updated_at REAL
            );
            """
        )
        conn.commit()
        cols = {r[1] for r in conn.execute("PRAGMA table_info(tenants)").fetchall()}
        if "oidc_role_mapping_json" not in cols:
            conn.execute("ALTER TABLE tenants ADD COLUMN oidc_role_mapping_json TEXT")
            conn.commit()
        if "oidc_scopes" not in cols:
            conn.execute("ALTER TABLE tenants ADD COLUMN oidc_scopes TEXT DEFAULT 'openid profile email'")
            conn.commit()
        if "oidc_token_url" not in cols:
            conn.execute("ALTER TABLE tenants ADD COLUMN oidc_token_url TEXT")
            conn.commit()
        if "oidc_userinfo_url" not in cols:
            conn.execute("ALTER TABLE tenants ADD COLUMN oidc_userinfo_url TEXT")
            conn.commit()
        user_cols = {r[1] for r in conn.execute("PRAGMA table_info(auth_users)").fetchall()}
        if user_cols and "tenant_id" not in user_cols:
            conn.execute("ALTER TABLE auth_users ADD COLUMN tenant_id TEXT DEFAULT 'mitako'")
            conn.commit()
        count = conn.execute("SELECT COUNT(*) FROM tenants").fetchone()[0]
        if count == 0:
            now = time.time()
            for t in _DEMO_TENANTS:
                conn.execute(
                    """
                    INSERT INTO tenants
                        (tenant_id, name, sso_enabled, oidc_issuer, oidc_client_id,
                         oidc_client_secret, oidc_redirect_uri, enabled, created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,1,?,?)
                    """,
                    (
                        t["tenant_id"], t["name"], t["sso_enabled"], t["oidc_issuer"],
                        t["oidc_client_id"], "demo-secret", t["oidc_redirect_uri"], now, now,
                    ),
                )
            conn.commit()
        else:
            now = time.time()
            conn.execute(
                "UPDATE tenants SET name = ?, updated_at = ? WHERE tenant_id = ? AND name LIKE ?",
                ("客服中心·华东组", now, "bpo-east", "%外包%"),
            )
            conn.commit()
    finally:
        conn.close()
    _db_ready = True


@contextmanager
def _connect():
    _ensure_db()
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _row(row: sqlite3.Row) -> Dict[str, Any]:
    mapping_raw = row["oidc_role_mapping_json"] if "oidc_role_mapping_json" in row.keys() else None
    try:
        role_mapping = json.loads(mapping_raw) if mapping_raw else _DEFAULT_ROLE_MAPPING
    except json.JSONDecodeError:
        role_mapping = _DEFAULT_ROLE_MAPPING
    return {
        "tenant_id": row["tenant_id"],
        "name": row["name"],
        "sso_enabled": bool(row["sso_enabled"]),
        "oidc_issuer": row["oidc_issuer"] or "",
        "oidc_client_id": row["oidc_client_id"] or "",
        "oidc_redirect_uri": row["oidc_redirect_uri"] or "",
        "oidc_scopes": (row["oidc_scopes"] if "oidc_scopes" in row.keys() else None) or "openid profile email",
        "oidc_token_url": (row["oidc_token_url"] if "oidc_token_url" in row.keys() else None) or "",
        "oidc_userinfo_url": (row["oidc_userinfo_url"] if "oidc_userinfo_url" in row.keys() else None) or "",
        "role_mapping": role_mapping,
        "enabled": bool(row["enabled"]),
    }


def list_tenants(enabled_only: bool = True) -> List[Dict[str, Any]]:
    with _lock, _connect() as conn:
        q = """SELECT tenant_id, name, sso_enabled, oidc_issuer, oidc_client_id, oidc_redirect_uri,
                      oidc_scopes, oidc_token_url, oidc_userinfo_url, oidc_role_mapping_json, enabled
               FROM tenants"""
        if enabled_only:
            q += " WHERE enabled = 1"
        q += " ORDER BY tenant_id"
        return [_row(r) for r in conn.execute(q).fetchall()]


def get_tenant(tenant_id: str) -> Optional[Dict[str, Any]]:
    with _lock, _connect() as conn:
        row = conn.execute(
            """SELECT tenant_id, name, sso_enabled, oidc_issuer, oidc_client_id, oidc_redirect_uri,
                      oidc_scopes, oidc_token_url, oidc_userinfo_url, oidc_role_mapping_json, enabled
               FROM tenants WHERE tenant_id = ?""",
            (tenant_id,),
        ).fetchone()
        return _row(row) if row else None


def get_tenant_secret(tenant_id: str) -> str:
    with _lock, _connect() as conn:
        row = conn.execute("SELECT oidc_client_secret FROM tenants WHERE tenant_id = ?", (tenant_id,)).fetchone()
        return (row["oidc_client_secret"] or "") if row else ""


def get_role_mapping(tenant_id: str) -> Dict[str, List[str]]:
    tenant = get_tenant(tenant_id)
    if not tenant:
        return _DEFAULT_ROLE_MAPPING
    mapping = tenant.get("role_mapping") or _DEFAULT_ROLE_MAPPING
    return {str(k): list(v) if isinstance(v, list) else [str(v)] for k, v in mapping.items()}
