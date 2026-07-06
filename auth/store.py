# -*- coding: utf-8 -*-
"""管理员/坐席账号 SQLite 持久层"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from runtime_paths import db_path

_AUTH_DB_PATH = db_path("MITAKO_AUTH_DB_PATH", "auth.db")
_DB_DIR = str(_AUTH_DB_PATH.parent)
_DB_PATH = str(_AUTH_DB_PATH)
_lock = threading.RLock()
_db_ready = False


def _hash_password(password: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()


def _integrity_ok(conn: sqlite3.Connection) -> bool:
    row = conn.execute("PRAGMA integrity_check").fetchone()
    return bool(row and row[0] == "ok")


def _backup_auth_db(db_path: str) -> str:
    path = Path(db_path)
    backup = path.with_name(f"{path.stem}.pre-tenant-migration.{int(time.time())}{path.suffix}")
    with sqlite3.connect(db_path) as source, sqlite3.connect(str(backup)) as target:
        source.backup(target)
        assert _integrity_ok(target), f"auth backup integrity check failed: {backup}"
    return str(backup)


def _migrate_auth_users_to_tenant_pk(conn: sqlite3.Connection, has_tenant_id: bool) -> None:
    rows_before = conn.execute("SELECT COUNT(*) FROM auth_users").fetchone()[0]
    backup = _backup_auth_db(_DB_PATH)
    tenant_expr = "COALESCE(tenant_id, 'mitako')" if has_tenant_id else "'mitako'"
    conn.isolation_level = None
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DROP TABLE IF EXISTS auth_users_v2")
        conn.execute(
            """
            CREATE TABLE auth_users_v2 (
                username TEXT NOT NULL,
                tenant_id TEXT NOT NULL DEFAULT 'mitako',
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                role TEXT NOT NULL,
                agent_id TEXT,
                display_name TEXT,
                enabled INTEGER DEFAULT 1,
                created_at REAL,
                updated_at REAL,
                PRIMARY KEY (tenant_id, username)
            )
            """
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO auth_users_v2
                (username, tenant_id, password_hash, salt, role, agent_id, display_name, enabled, created_at, updated_at)
            SELECT username, {tenant_expr}, password_hash, salt, role, agent_id, display_name, enabled, created_at, updated_at
            FROM auth_users
            """.format(tenant_expr=tenant_expr)
        )
        rows_after = conn.execute("SELECT COUNT(*) FROM auth_users_v2").fetchone()[0]
        if rows_after != rows_before:
            raise RuntimeError(f"auth migration row mismatch: before={rows_before} after={rows_after} backup={backup}")
        conn.execute("DROP TABLE auth_users")
        conn.execute("ALTER TABLE auth_users_v2 RENAME TO auth_users")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_auth_users_tenant_username ON auth_users(tenant_id, username)")
        if not _integrity_ok(conn):
            raise RuntimeError(f"auth migration integrity check failed; backup={backup}")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.isolation_level = ""


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
                username TEXT NOT NULL,
                tenant_id TEXT NOT NULL DEFAULT 'mitako',
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                role TEXT NOT NULL,
                agent_id TEXT,
                display_name TEXT,
                enabled INTEGER DEFAULT 1,
                created_at REAL,
                updated_at REAL,
                PRIMARY KEY (tenant_id, username)
            );
            """
        )
        conn.commit()
        table_info = conn.execute("PRAGMA table_info(auth_users)").fetchall()
        cols = {r[1] for r in table_info}
        pk_cols = [r[1] for r in table_info if r[5]]
        if pk_cols == ["username"]:
            _migrate_auth_users_to_tenant_pk(conn, "tenant_id" in cols)
        elif "tenant_id" not in cols:
            conn.execute("ALTER TABLE auth_users ADD COLUMN tenant_id TEXT DEFAULT 'mitako'")
            conn.commit()
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_auth_users_tenant_username ON auth_users(tenant_id, username)")
        if not _integrity_ok(conn):
            raise RuntimeError(f"auth db integrity check failed: {_DB_PATH}")
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
            ON CONFLICT(tenant_id, username) DO UPDATE SET
                password_hash=excluded.password_hash,
                salt=excluded.salt,
                role=excluded.role,
                agent_id=excluded.agent_id,
                display_name=excluded.display_name,
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


def verify_user(username: str, password: str, tenant_id: str = "mitako") -> Optional[Dict[str, Any]]:
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM auth_users WHERE username = ? AND tenant_id = ? AND enabled = 1",
            (username, tenant_id or "mitako"),
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
            "SELECT username, tenant_id, role, agent_id, display_name, enabled FROM auth_users ORDER BY tenant_id, username"
        ).fetchall()
        return [dict(r) for r in rows]
