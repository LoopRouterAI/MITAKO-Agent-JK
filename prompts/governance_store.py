# -*- coding: utf-8 -*-
"""高级客服业务规则的追加式版本库。"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional

from prompts.catalog import ensure_rule_key
from runtime_paths import db_path


_DB_PATH = str(db_path("MITAKO_ADMIN_DB_PATH", "admin.db"))
_lock = threading.RLock()
_db_ready = False
_VALID_MODES = frozenset({"supplement", "replace"})
_SQLITE_TIMEOUT_SECONDS = 0.5
_MAX_CONTENT_LENGTH = 6_000
_active_cache: Dict[tuple[str, str, str], Optional[Dict[str, Any]]] = {}


class VersionConflictError(RuntimeError):
    pass


def _iso_timestamp(value: float) -> str:
    return datetime.fromtimestamp(float(value), timezone.utc).astimezone().isoformat(timespec="seconds")


def _ensure_db() -> None:
    global _db_ready
    if _db_ready:
        return
    Path(_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, timeout=_SQLITE_TIMEOUT_SECONDS)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS business_rule_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL,
                prompt_key TEXT NOT NULL,
                version INTEGER NOT NULL,
                mode TEXT NOT NULL,
                content TEXT NOT NULL,
                reason TEXT NOT NULL,
                actor TEXT NOT NULL,
                actor_role TEXT NOT NULL,
                source_version INTEGER,
                is_active INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                UNIQUE (tenant_id, prompt_key, version)
            );
            CREATE TABLE IF NOT EXISTS business_rule_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL,
                prompt_key TEXT NOT NULL,
                action TEXT NOT NULL,
                from_version INTEGER,
                to_version INTEGER NOT NULL,
                reason TEXT NOT NULL,
                actor TEXT NOT NULL,
                actor_role TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            """
        )
        version_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(business_rule_versions)").fetchall()
        }
        if "actor_role" not in version_columns:
            conn.execute("ALTER TABLE business_rule_versions ADD COLUMN actor_role TEXT NOT NULL DEFAULT ''")
        if "source_version" not in version_columns:
            conn.execute("ALTER TABLE business_rule_versions ADD COLUMN source_version INTEGER")
        audit_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(business_rule_audit)").fetchall()
        }
        if "actor_role" not in audit_columns:
            conn.execute("ALTER TABLE business_rule_audit ADD COLUMN actor_role TEXT NOT NULL DEFAULT ''")
        conn.executescript(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_business_rule_version
                ON business_rule_versions(tenant_id, prompt_key, version);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_business_rule_active
                ON business_rule_versions(tenant_id, prompt_key) WHERE is_active = 1;
            CREATE INDEX IF NOT EXISTS idx_business_rule_history
                ON business_rule_versions(tenant_id, prompt_key, version DESC);
            CREATE INDEX IF NOT EXISTS idx_business_rule_audit
                ON business_rule_audit(tenant_id, prompt_key, id DESC);
            PRAGMA user_version = 1;
            """
        )
        conn.commit()
    finally:
        conn.close()
    _db_ready = True


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    _ensure_db()
    conn = sqlite3.connect(_DB_PATH, timeout=_SQLITE_TIMEOUT_SECONDS)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _validate(tenant_id: str, prompt_key: str, reason: str, actor: str) -> tuple[str, str, str, str]:
    tenant = str(tenant_id or "").strip()
    key = ensure_rule_key(prompt_key)
    why = str(reason or "").strip()
    who = str(actor or "").strip()
    if not tenant:
        raise ValueError("租户不能为空")
    if len(why) < 6 or len(why) > 500:
        raise ValueError("修改原因必须填写 6 至 500 个字符")
    if not who:
        raise ValueError("修改账号不能为空")
    return tenant, key, why, who


def _version_row(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    return {
        "id": int(row["id"]),
        "tenant_id": row["tenant_id"],
        "prompt_key": row["prompt_key"],
        "version": int(row["version"]),
        "mode": row["mode"],
        "content": row["content"],
        "reason": row["reason"],
        "actor": row["actor"],
        "actor_role": row["actor_role"],
        "source_version": row["source_version"],
        "is_active": bool(row["is_active"]),
        "created_at": _iso_timestamp(row["created_at"]),
    }


def get_active_version(tenant_id: str, prompt_key: str) -> Optional[Dict[str, Any]]:
    tenant, key = str(tenant_id or "").strip(), ensure_rule_key(prompt_key)
    if not tenant:
        raise ValueError("租户不能为空")
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM business_rule_versions WHERE tenant_id = ? AND prompt_key = ? AND is_active = 1",
            (tenant, key),
        ).fetchone()
        active = _version_row(row)
        _active_cache[(_DB_PATH, tenant, key)] = active
        return active


def get_cached_active_version(tenant_id: str, prompt_key: str) -> Optional[Dict[str, Any]]:
    tenant, key = str(tenant_id or "").strip(), ensure_rule_key(prompt_key)
    return _active_cache.get((_DB_PATH, tenant, key))


def list_versions(tenant_id: str, prompt_key: str, limit: int = 100) -> List[Dict[str, Any]]:
    tenant, key = str(tenant_id or "").strip(), ensure_rule_key(prompt_key)
    if not tenant:
        raise ValueError("租户不能为空")
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM business_rule_versions WHERE tenant_id = ? AND prompt_key = ? ORDER BY version DESC LIMIT ?",
            (tenant, key, max(1, min(int(limit), 500))),
        ).fetchall()
        return [_version_row(row) for row in rows if row is not None]


def publish_version(
    *, tenant_id: str, prompt_key: str, mode: str, content: str, reason: str,
    actor: str, actor_role: str, source_version: Optional[int] = None, action: str = "publish",
    expected_active_version: Optional[int] = None,
) -> Dict[str, Any]:
    tenant, key, why, who = _validate(tenant_id, prompt_key, reason, actor)
    normalized_mode = str(mode or "").strip()
    body = str(content or "").strip()
    if normalized_mode not in _VALID_MODES:
        raise ValueError("更新方式必须为 supplement 或 replace")
    if len(body) < 10 or len(body) > _MAX_CONTENT_LENGTH:
        raise ValueError("业务规则内容必须填写 10 至 6000 个字符")
    now = time.time()
    with _lock, _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute(
            "SELECT version FROM business_rule_versions WHERE tenant_id = ? AND prompt_key = ? AND is_active = 1",
            (tenant, key),
        ).fetchone()
        current_version = int(current[0]) if current else 0
        if expected_active_version is not None and int(expected_active_version) != current_version:
            raise VersionConflictError("当前规则已被其他主管更新，请刷新后重新确认")
        latest = conn.execute(
            "SELECT COALESCE(MAX(version), 0) FROM business_rule_versions WHERE tenant_id = ? AND prompt_key = ?",
            (tenant, key),
        ).fetchone()[0]
        version = int(latest) + 1
        conn.execute(
            "UPDATE business_rule_versions SET is_active = 0 WHERE tenant_id = ? AND prompt_key = ?",
            (tenant, key),
        )
        conn.execute(
            """INSERT INTO business_rule_versions
               (tenant_id, prompt_key, version, mode, content, reason, actor, actor_role, source_version, is_active, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
            (tenant, key, version, normalized_mode, body, why, who, actor_role, source_version, now),
        )
        conn.execute(
            """INSERT INTO business_rule_audit
               (tenant_id, prompt_key, action, from_version, to_version, reason, actor, actor_role, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (tenant, key, action, int(current[0]) if current else None, version, why, who, actor_role, now),
        )
    active = get_active_version(tenant, key)
    if active is None:
        raise RuntimeError("业务规则版本发布后未能读取")
    _active_cache[(_DB_PATH, tenant, key)] = active
    return active


def rollback_version(
    *, tenant_id: str, prompt_key: str, target_version: int, reason: str,
    actor: str, actor_role: str, expected_active_version: Optional[int] = None,
) -> Dict[str, Any]:
    tenant, key, why, who = _validate(tenant_id, prompt_key, reason, actor)
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM business_rule_versions WHERE tenant_id = ? AND prompt_key = ? AND version = ?",
            (tenant, key, int(target_version)),
        ).fetchone()
    if row is None:
        raise LookupError("目标历史版本不存在")
    return publish_version(
        tenant_id=tenant,
        prompt_key=key,
        mode=row["mode"],
        content=row["content"],
        reason=why,
        actor=who,
        actor_role=actor_role,
        source_version=int(target_version),
        action="rollback",
        expected_active_version=expected_active_version,
    )


def list_audit(tenant_id: str, prompt_key: str, limit: int = 200) -> List[Dict[str, Any]]:
    tenant, key = str(tenant_id or "").strip(), ensure_rule_key(prompt_key)
    if not tenant:
        raise ValueError("租户不能为空")
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM business_rule_audit WHERE tenant_id = ? AND prompt_key = ? ORDER BY id DESC LIMIT ?",
            (tenant, key, max(1, min(int(limit), 500))),
        ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "action": row["action"],
            "from_version": row["from_version"],
            "to_version": int(row["to_version"]),
            "reason": row["reason"],
            "actor": row["actor"],
            "actor_role": row["actor_role"],
            "created_at": _iso_timestamp(row["created_at"]),
        }
        for row in rows
    ]
