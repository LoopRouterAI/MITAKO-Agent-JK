# -*- coding: utf-8 -*-
"""管理员/坐席账号 SQLite 持久层"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

_DB_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
_DB_PATH = os.path.join(_DB_DIR, "auth.db")
_lock = threading.RLock()
_db_ready = False


def _hash_password(password: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()


def _ensure_db() -> None:
    global _db_ready
    if _db_ready:
        return
    os.makedirs(_DB_DIR, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS auth_users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                role TEXT NOT NULL,
                agent_id TEXT,
                display_name TEXT,
                enabled INTEGER DEFAULT 1,
                created_at REAL,
                updated_at REAL
            );
            """
        )
        conn.commit()
        cols = {r[1] for r in conn.execute("PRAGMA table_info(auth_users)").fetchall()}
        if "tenant_id" not in cols:
            conn.execute("ALTER TABLE auth_users ADD COLUMN tenant_id TEXT DEFAULT 'mitako'")
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


def upsert_user(
    username: str,
    password: str,
    role: str,
    *,
    agent_id: str = "",
    display_name: str = "",
    tenant_id: str = "mitako",
) -> None:
    salt = os.urandom(8).hex()
    now = time.time()
    with _lock, _connect() as conn:
        conn.execute(
            """
            INSERT INTO auth_users
                (username, password_hash, salt, role, agent_id, display_name, enabled, created_at, updated_at, tenant_id)
            VALUES (?,?,?,?,?,?,1,?,?,?)
            ON CONFLICT(username) DO UPDATE SET
                password_hash=excluded.password_hash,
                salt=excluded.salt,
                role=excluded.role,
                agent_id=excluded.agent_id,
                display_name=excluded.display_name,
                tenant_id=excluded.tenant_id,
                updated_at=excluded.updated_at
            """,
            (
                username,
                _hash_password(password, salt),
                salt,
                role,
                agent_id or None,
                display_name or username,
                now,
                now,
                tenant_id,
            ),
        )


def verify_user(username: str, password: str) -> Optional[Dict[str, Any]]:
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM auth_users WHERE username = ? AND enabled = 1",
            (username,),
        ).fetchone()
        if not row:
            return None
        if _hash_password(password, row["salt"]) != row["password_hash"]:
            return None
        return {
            "username": row["username"],
            "role": row["role"],
            "agent_id": row["agent_id"] or "",
            "display_name": row["display_name"] or row["username"],
            "tenant_id": row["tenant_id"] if "tenant_id" in row.keys() else "mitako",
        }


def list_users() -> List[Dict[str, Any]]:
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT username, role, agent_id, display_name, enabled FROM auth_users ORDER BY username"
        ).fetchall()
        return [dict(r) for r in rows]
