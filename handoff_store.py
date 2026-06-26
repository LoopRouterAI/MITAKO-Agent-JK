# -*- coding: utf-8 -*-
"""转人工 SQLite 持久层 — 会话 / 消息 / 转交审计"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

_DB_DIR = os.path.join(os.path.dirname(__file__), "data")
_DB_PATH = os.path.join(_DB_DIR, "handoff.db")
_lock = threading.RLock()
_db_ready = False


def _ensure_db() -> None:
    global _db_ready
    if _db_ready:
        return
    os.makedirs(_DB_DIR, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS handoff_sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT,
                status TEXT NOT NULL DEFAULT 'queuing',
                required_tier TEXT NOT NULL DEFAULT 'standard',
                brief_json TEXT,
                assigned_agent_json TEXT,
                pending_agent_json TEXT,
                suggested_agent_json TEXT,
                queue_position INTEGER DEFAULT 1,
                queue_ahead INTEGER DEFAULT 0,
                queue_eta_minutes INTEGER DEFAULT 1,
                enqueued_at REAL,
                accepted_at REAL,
                accepted_by TEXT,
                last_agent_reply_at REAL,
                last_user_message_at REAL,
                escalation_note TEXT,
                observer_mode INTEGER DEFAULT 1,
                created_at REAL,
                updated_at REAL
            );
            CREATE TABLE IF NOT EXISTS handoff_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                agent_id TEXT,
                meta_json TEXT,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_handoff_messages_session_ts
                ON handoff_messages(session_id, created_at);
            CREATE TABLE IF NOT EXISTS handoff_transfer_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                from_agent_id TEXT,
                to_agent_id TEXT,
                note TEXT,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS observer_audits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                message_id INTEGER,
                content TEXT NOT NULL,
                flagged INTEGER DEFAULT 0,
                policy_hits_json TEXT,
                reviewer_status TEXT DEFAULT 'pending',
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_observer_audits_session
                ON observer_audits(session_id, created_at);
            """
        )
        conn.commit()
        cols = {r[1] for r in conn.execute("PRAGMA table_info(handoff_sessions)").fetchall()}
        if "tenant_id" not in cols:
            conn.execute("ALTER TABLE handoff_sessions ADD COLUMN tenant_id TEXT DEFAULT 'mitako'")
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


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _json_loads(raw: Optional[str], default: Any = None) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def _row_to_session(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "session_id": row["session_id"],
        "user_id": row["user_id"],
        "status": row["status"],
        "required_tier": row["required_tier"],
        "brief": _json_loads(row["brief_json"], {}),
        "assigned_agent": _json_loads(row["assigned_agent_json"]),
        "pending_agent": _json_loads(row["pending_agent_json"]),
        "suggested_agent": _json_loads(row["suggested_agent_json"]),
        "position": row["queue_position"],
        "ahead": row["queue_ahead"],
        "eta_minutes": row["queue_eta_minutes"],
        "enqueued_at": row["enqueued_at"],
        "accepted_at": row["accepted_at"],
        "accepted_by": row["accepted_by"],
        "last_agent_reply_at": row["last_agent_reply_at"],
        "last_user_message_at": row["last_user_message_at"],
        "escalation_note": row["escalation_note"],
        "observer_mode": bool(row["observer_mode"]),
        "tenant_id": row["tenant_id"] if "tenant_id" in row.keys() else "mitako",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def upsert_session(entry: Dict[str, Any]) -> None:
    now = time.time()
    with _lock, _connect() as conn:
        conn.execute(
            """
            INSERT INTO handoff_sessions (
                session_id, user_id, status, required_tier, brief_json,
                assigned_agent_json, pending_agent_json, suggested_agent_json,
                queue_position, queue_ahead, queue_eta_minutes,
                enqueued_at, accepted_at, accepted_by,
                last_agent_reply_at, last_user_message_at, escalation_note,
                observer_mode, tenant_id, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(session_id) DO UPDATE SET
                user_id=excluded.user_id, status=excluded.status,
                required_tier=excluded.required_tier, brief_json=excluded.brief_json,
                assigned_agent_json=excluded.assigned_agent_json,
                pending_agent_json=excluded.pending_agent_json,
                suggested_agent_json=excluded.suggested_agent_json,
                queue_position=excluded.queue_position, queue_ahead=excluded.queue_ahead,
                queue_eta_minutes=excluded.queue_eta_minutes,
                enqueued_at=excluded.enqueued_at, accepted_at=excluded.accepted_at,
                accepted_by=excluded.accepted_by,
                last_agent_reply_at=excluded.last_agent_reply_at,
                last_user_message_at=excluded.last_user_message_at,
                escalation_note=excluded.escalation_note,
                observer_mode=excluded.observer_mode,
                tenant_id=excluded.tenant_id,
                updated_at=excluded.updated_at
            """,
            (
                entry["session_id"],
                entry.get("user_id"),
                entry.get("status", "queuing"),
                entry.get("required_tier", "standard"),
                _json_dumps(entry.get("brief") or {}),
                _json_dumps(entry.get("assigned_agent")) if entry.get("assigned_agent") else None,
                _json_dumps(entry.get("pending_agent")) if entry.get("pending_agent") else None,
                _json_dumps(entry.get("suggested_agent")) if entry.get("suggested_agent") else None,
                entry.get("position", 1),
                entry.get("ahead", 0),
                entry.get("eta_minutes", 1),
                entry.get("enqueued_at", now),
                entry.get("accepted_at"),
                entry.get("accepted_by"),
                entry.get("last_agent_reply_at"),
                entry.get("last_user_message_at"),
                entry.get("escalation_note"),
                1 if entry.get("observer_mode", True) else 0,
                entry.get("tenant_id") or "mitako",
                entry.get("created_at", now),
                now,
            ),
        )


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM handoff_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        return _row_to_session(row) if row else None


def delete_session(session_id: str) -> None:
    with _lock, _connect() as conn:
        conn.execute("DELETE FROM handoff_messages WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM handoff_transfer_events WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM handoff_sessions WHERE session_id = ?", (session_id,))


def patch_brief(session_id: str, patch: Dict[str, Any]) -> None:
    """合并写入 brief_json — 用于 IM external id 等扩展字段"""
    entry = get_session(session_id)
    if not entry:
        return
    brief = dict(entry.get("brief") or {})
    brief.update(patch)
    entry["brief"] = brief
    upsert_session(entry)


def list_active_sessions(tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
    with _lock, _connect() as conn:
        if tenant_id:
            rows = conn.execute(
                """
                SELECT * FROM handoff_sessions
                WHERE status IN ('queuing', 'transferring', 'escalated', 'connected')
                  AND tenant_id = ?
                ORDER BY
                    CASE status WHEN 'escalated' THEN 0 WHEN 'transferring' THEN 1 WHEN 'queuing' THEN 2 ELSE 3 END,
                    updated_at DESC
                """,
                (tenant_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM handoff_sessions
                WHERE status IN ('queuing', 'transferring', 'escalated', 'connected')
                ORDER BY
                    CASE status WHEN 'escalated' THEN 0 WHEN 'transferring' THEN 1 WHEN 'queuing' THEN 2 ELSE 3 END,
                    updated_at DESC
                """
            ).fetchall()
        return [_row_to_session(r) for r in rows]


def list_all_sessions(limit: int = 500, since: float = 0, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
    with _lock, _connect() as conn:
        if since and tenant_id:
            rows = conn.execute(
                """
                SELECT * FROM handoff_sessions
                WHERE created_at >= ? AND tenant_id = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (since, tenant_id, limit),
            ).fetchall()
        elif since:
            rows = conn.execute(
                """
                SELECT * FROM handoff_sessions
                WHERE created_at >= ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (since, limit),
            ).fetchall()
        elif tenant_id:
            rows = conn.execute(
                "SELECT * FROM handoff_sessions WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ?",
                (tenant_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM handoff_sessions ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_row_to_session(r) for r in rows]


def append_message(
    session_id: str,
    role: str,
    content: str,
    agent_id: str = "",
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    ts = time.time()
    with _lock, _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO handoff_messages (session_id, role, content, agent_id, meta_json, created_at)
            VALUES (?,?,?,?,?,?)
            """,
            (session_id, role, content, agent_id or None, _json_dumps(meta or {}), ts),
        )
        msg_id = cur.lastrowid
        if role == "human":
            conn.execute(
                "UPDATE handoff_sessions SET last_agent_reply_at=?, updated_at=? WHERE session_id=?",
                (ts, ts, session_id),
            )
        elif role == "user":
            conn.execute(
                "UPDATE handoff_sessions SET last_user_message_at=?, updated_at=? WHERE session_id=?",
                (ts, ts, session_id),
            )
        else:
            conn.execute(
                "UPDATE handoff_sessions SET updated_at=? WHERE session_id=?",
                (ts, session_id),
            )
    return {
        "id": msg_id,
        "session_id": session_id,
        "role": role,
        "content": content,
        "agent_id": agent_id or None,
        "meta": meta or {},
        "created_at": ts,
    }


def get_messages_since(session_id: str, since: float = 0) -> List[Dict[str, Any]]:
    with _lock, _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, session_id, role, content, agent_id, meta_json, created_at
            FROM handoff_messages
            WHERE session_id = ? AND created_at > ?
            ORDER BY created_at ASC, id ASC
            """,
            (session_id, since),
        ).fetchall()
        return [
            {
                "id": r["id"],
                "session_id": r["session_id"],
                "role": r["role"],
                "content": r["content"],
                "agent_id": r["agent_id"],
                "meta": _json_loads(r["meta_json"], {}),
                "created_at": r["created_at"],
            }
            for r in rows
        ]


def append_transfer_event(
    session_id: str,
    event_type: str,
    from_agent_id: str = "",
    to_agent_id: str = "",
    note: str = "",
) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            """
            INSERT INTO handoff_transfer_events
                (session_id, event_type, from_agent_id, to_agent_id, note, created_at)
            VALUES (?,?,?,?,?,?)
            """,
            (session_id, event_type, from_agent_id or None, to_agent_id or None, note, time.time()),
        )


def get_transfer_events(session_id: str) -> List[Dict[str, Any]]:
    with _lock, _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, event_type, from_agent_id, to_agent_id, note, created_at
            FROM handoff_transfer_events WHERE session_id = ? ORDER BY created_at ASC
            """,
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def list_all_transfer_events(limit: int = 100) -> List[Dict[str, Any]]:
    with _lock, _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, session_id, event_type, from_agent_id, to_agent_id, note, created_at
            FROM handoff_transfer_events ORDER BY created_at DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def list_sla_candidates(now: Optional[float] = None) -> List[Dict[str, Any]]:
    from handoff_routing import get_sla_config

    now = now or time.time()
    sla = get_sla_config()
    if not sla.get("auto_transfer_enabled"):
        return []
    first_sec = int(sla.get("first_response_seconds") or 180)
    reply_sec = int(sla.get("reply_timeout_seconds") or 300)

    out: List[Dict[str, Any]] = []
    for sess in list_active_sessions():
        if sess.get("status") != "connected":
            continue
        accepted = sess.get("accepted_at") or 0
        last_agent = sess.get("last_agent_reply_at")
        last_user = sess.get("last_user_message_at") or accepted
        if not last_agent and accepted and (now - accepted) > first_sec:
            out.append({**sess, "sla_reason": "first_response"})
        elif last_user and (now - last_user) > reply_sec and (not last_agent or last_agent < last_user):
            out.append({**sess, "sla_reason": "reply_timeout"})
    return out


_OBSERVER_FLAG_WORDS = ["退现金", "全额退款", "必赔", "起诉赔偿", "十倍赔偿"]


def append_observer_audit(
    session_id: str,
    content: str,
    message_id: Optional[int] = None,
) -> Dict[str, Any]:
    hits = [w for w in _OBSERVER_FLAG_WORDS if w in content]
    flagged = 1 if hits else 0
    ts = time.time()
    with _lock, _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO observer_audits
                (session_id, message_id, content, flagged, policy_hits_json, reviewer_status, created_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            (session_id, message_id, content, flagged, _json_dumps(hits), "pending", ts),
        )
        audit_id = cur.lastrowid
    return {
        "id": audit_id,
        "session_id": session_id,
        "flagged": bool(flagged),
        "policy_hits": hits,
    }


def list_observer_audits(flagged_only: bool = False, limit: int = 50) -> List[Dict[str, Any]]:
    with _lock, _connect() as conn:
        q = "SELECT * FROM observer_audits"
        if flagged_only:
            q += " WHERE flagged = 1"
        q += " ORDER BY created_at DESC LIMIT ?"
        rows = conn.execute(q, (limit,)).fetchall()
        return [
            {
                "id": r["id"],
                "session_id": r["session_id"],
                "message_id": r["message_id"],
                "content": r["content"],
                "flagged": bool(r["flagged"]),
                "policy_hits": _json_loads(r["policy_hits_json"], []),
                "reviewer_status": r["reviewer_status"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]


def close_session_status(session_id: str) -> bool:
    with _lock, _connect() as conn:
        cur = conn.execute(
            "UPDATE handoff_sessions SET status='closed', updated_at=? WHERE session_id=?",
            (time.time(), session_id),
        )
        return cur.rowcount > 0

