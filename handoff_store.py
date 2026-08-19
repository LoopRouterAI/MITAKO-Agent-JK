# -*- coding: utf-8 -*-
"""转VIP客服 SQLite 持久层 — 会话 / 消息 / 转交审计"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, List, Optional
from uuid import uuid4

from runtime_paths import db_path

_HANDOFF_DB_PATH = db_path("MITAKO_HANDOFF_DB_PATH", "handoff.db")
_DB_DIR = str(_HANDOFF_DB_PATH.parent)
_DB_PATH = str(_HANDOFF_DB_PATH)
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
            CREATE TABLE IF NOT EXISTS handoff_offers (
                offer_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL DEFAULT 'mitako',
                reason TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'offered',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_handoff_offers_session
                ON handoff_offers(session_id, user_id, status, created_at);
            CREATE TABLE IF NOT EXISTS observer_audits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                tenant_id TEXT DEFAULT 'mitako',
                message_id INTEGER,
                content TEXT NOT NULL,
                flagged INTEGER DEFAULT 0,
                policy_hits_json TEXT,
                reviewer_status TEXT DEFAULT 'pending',
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_observer_audits_session
                ON observer_audits(session_id, created_at);
            CREATE TABLE IF NOT EXISTS business_audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                tenant_id TEXT DEFAULT 'mitako',
                user_id TEXT,
                order_id TEXT,
                event_type TEXT NOT NULL,
                idempotency_key TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                payload_json TEXT,
                result_json TEXT,
                created_at REAL NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_business_audit_idempotency
                ON business_audit_events(tenant_id, order_id, event_type, idempotency_key)
                WHERE idempotency_key != '';
            CREATE INDEX IF NOT EXISTS idx_business_audit_session
                ON business_audit_events(session_id, created_at);
            """
        )
        conn.commit()
        cols = {r[1] for r in conn.execute("PRAGMA table_info(handoff_sessions)").fetchall()}
        if "tenant_id" not in cols:
            conn.execute("ALTER TABLE handoff_sessions ADD COLUMN tenant_id TEXT DEFAULT 'mitako'")
            conn.commit()
        bcols = {r[1] for r in conn.execute("PRAGMA table_info(business_audit_events)").fetchall()}
        if bcols and "tenant_id" not in bcols:
            conn.execute("ALTER TABLE business_audit_events ADD COLUMN tenant_id TEXT DEFAULT 'mitako'")
            conn.commit()
        if bcols:
            conn.execute("DROP INDEX IF EXISTS idx_business_audit_idempotency")
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_business_audit_idempotency
                    ON business_audit_events(tenant_id, order_id, event_type, idempotency_key)
                    WHERE idempotency_key != ''
                """
            )
            conn.commit()
        ocols = {r[1] for r in conn.execute("PRAGMA table_info(observer_audits)").fetchall()}
        if ocols and "tenant_id" not in ocols:
            conn.execute("ALTER TABLE observer_audits ADD COLUMN tenant_id TEXT DEFAULT 'mitako'")
            conn.execute(
                """
                UPDATE observer_audits
                SET tenant_id = COALESCE(
                    (SELECT tenant_id FROM handoff_sessions WHERE handoff_sessions.session_id = observer_audits.session_id),
                    'mitako'
                )
                """
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


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _json_loads(raw: Optional[str], default: Any = None) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def create_handoff_offer(session_id: str, user_id: str, reason: str, tenant_id: str = "mitako") -> Dict[str, Any]:
    now = time.time()
    offer_id = f"HO-{uuid4().hex[:12].upper()}"
    with _lock, _connect() as conn:
        conn.execute(
            "UPDATE handoff_offers SET status='expired', updated_at=? WHERE tenant_id=? AND session_id=? AND user_id=? AND status='offered'",
            (now, tenant_id or "mitako", session_id, user_id),
        )
        conn.execute(
            """
            INSERT INTO handoff_offers(offer_id, session_id, user_id, tenant_id, reason, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'offered', ?, ?)
            """,
            (offer_id, session_id, user_id, tenant_id or "mitako", reason, now, now),
        )
    return {
        "offer_id": offer_id,
        "session_id": session_id,
        "user_id": user_id,
        "tenant_id": tenant_id or "mitako",
        "reason": reason,
        "status": "offered",
        "created_at": now,
    }


def get_active_handoff_offer(
    session_id: str,
    tenant_id: str,
    user_id: str = "",
    max_age_seconds: int = 900,
) -> Optional[Dict[str, Any]]:
    cutoff = time.time() - max(30, max_age_seconds)
    with _lock, _connect() as conn:
        if user_id:
            row = conn.execute(
                """
                SELECT * FROM handoff_offers
                WHERE tenant_id=? AND session_id=? AND user_id=? AND status='offered' AND created_at>=?
                ORDER BY created_at DESC LIMIT 1
                """,
                (tenant_id, session_id, user_id, cutoff),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT * FROM handoff_offers
                WHERE tenant_id=? AND session_id=? AND status='offered' AND created_at>=?
                ORDER BY created_at DESC LIMIT 1
                """,
                (tenant_id, session_id, cutoff),
            ).fetchone()
    return dict(row) if row else None


def update_handoff_offer(
    offer_id: str,
    status: str,
    session_id: str,
    user_id: str,
    *,
    tenant_id: str,
) -> Optional[Dict[str, Any]]:
    allowed = {"consented", "declined", "expired", "failed", "queued"}
    if status not in allowed:
        raise ValueError("invalid_handoff_offer_status")
    now = time.time()
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM handoff_offers WHERE offer_id=? AND tenant_id=?",
            (offer_id, tenant_id),
        ).fetchone()
        if not row:
            return None
        current = dict(row)
        if session_id and current.get("session_id") != session_id:
            return None
        if user_id and current.get("user_id") != user_id:
            return None
        conn.execute(
            "UPDATE handoff_offers SET status=?, updated_at=? WHERE offer_id=? AND tenant_id=?",
            (status, now, offer_id, tenant_id),
        )
        current.update({"status": status, "updated_at": now})
        return current


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
    tenant_id = entry.get("tenant_id") or "mitako"
    with _lock, _connect() as conn:
        existing = conn.execute(
            "SELECT tenant_id FROM handoff_sessions WHERE session_id = ?",
            (entry["session_id"],),
        ).fetchone()
        if existing and (existing["tenant_id"] or "mitako") != tenant_id:
            raise PermissionError("handoff session belongs to another tenant")
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
                tenant_id,
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


def _tenant_forbidden(entry: Dict[str, Any], tenant_id: Optional[str]) -> bool:
    return bool(tenant_id) and (entry.get("tenant_id") or "mitako") != (tenant_id or "mitako")


def _reload_session(conn: sqlite3.Connection, session_id: str) -> Dict[str, Any]:
    row = conn.execute("SELECT * FROM handoff_sessions WHERE session_id = ?", (session_id,)).fetchone()
    return _row_to_session(row) if row else {}


def try_accept_session(session_id: str, agent: Dict[str, Any], tenant_id: Optional[str] = None) -> Dict[str, Any]:
    now = time.time()
    agent_id = agent.get("agent_id") or ""
    with _lock, _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        entry = _reload_session(conn, session_id)
        if not entry:
            return {"ok": False, "error": "session_not_found"}
        if _tenant_forbidden(entry, tenant_id):
            return {"ok": False, "error": "tenant_forbidden"}
        status = entry.get("status")
        if status not in {"queuing", "escalated", "transferring"}:
            return {"ok": False, "error": "invalid_status", "status": status}
        pending = entry.get("pending_agent")
        if status == "transferring" and pending and pending.get("agent_id") != agent_id:
            return {"ok": False, "error": "not_pending_agent", "message": "该会话待指定同事确认接管"}
        if entry.get("required_tier") == "supervisor" and agent.get("tier") != "supervisor":
            return {"ok": False, "error": "need_supervisor", "message": "该会话路由规则要求升级处理专员接单，请选择对应身份"}
        conn.execute(
            """
            UPDATE handoff_sessions
            SET status='connected',
                assigned_agent_json=?,
                pending_agent_json=NULL,
                accepted_by=?,
                accepted_at=?,
                updated_at=?
            WHERE session_id=?
            """,
            (_json_dumps(agent), agent_id, now, now, session_id),
        )
        return {"ok": True, "entry": _reload_session(conn, session_id)}


def try_transfer_session(
    session_id: str,
    from_agent_id: str,
    to_agent: Dict[str, Any],
    tenant_id: Optional[str] = None,
) -> Dict[str, Any]:
    now = time.time()
    with _lock, _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        entry = _reload_session(conn, session_id)
        if not entry or entry.get("status") not in {"connected", "transferring"}:
            return {"ok": False, "error": "invalid_status"}
        if _tenant_forbidden(entry, tenant_id):
            return {"ok": False, "error": "tenant_forbidden"}
        assigned = (entry.get("assigned_agent") or {}).get("agent_id") or ""
        if assigned and from_agent_id and assigned != from_agent_id:
            return {"ok": False, "error": "agent_id_mismatch"}
        if entry.get("required_tier") == "supervisor" and to_agent.get("tier") != "supervisor":
            return {"ok": False, "error": "need_supervisor", "message": "该会话需要高级客服或专项客服接管，请选择对应客服。"}
        conn.execute(
            """
            UPDATE handoff_sessions
            SET status='transferring',
                pending_agent_json=?,
                updated_at=?
            WHERE session_id=?
            """,
            (_json_dumps(to_agent), now, session_id),
        )
        return {"ok": True, "entry": _reload_session(conn, session_id)}


def try_escalate_session(
    session_id: str,
    note: str,
    tenant_id: Optional[str] = None,
    from_agent_id: str = "",
) -> Dict[str, Any]:
    now = time.time()
    with _lock, _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        entry = _reload_session(conn, session_id)
        if not entry:
            return {"ok": False, "error": "session_not_found"}
        if _tenant_forbidden(entry, tenant_id):
            return {"ok": False, "error": "tenant_forbidden"}
        if entry.get("status") != "connected":
            return {"ok": False, "error": "invalid_status", "status": entry.get("status")}
        assigned = (entry.get("assigned_agent") or {}).get("agent_id") or ""
        if not assigned:
            return {"ok": False, "error": "agent_not_assigned"}
        if from_agent_id and assigned != from_agent_id:
            return {"ok": False, "error": "agent_id_mismatch", "message": "只能由当前接单客服发起升级处理"}
        brief = dict(entry.get("brief") or {})
        brief["escalation_note"] = note
        conn.execute(
            """
            UPDATE handoff_sessions
            SET status='escalated',
                required_tier='supervisor',
                escalation_note=?,
                pending_agent_json=NULL,
                brief_json=?,
                updated_at=?
            WHERE session_id=?
            """,
            (note, _json_dumps(brief), now, session_id),
        )
        return {"ok": True, "entry": _reload_session(conn, session_id)}


def delete_session(session_id: str, tenant_id: Optional[str] = None) -> None:
    with _lock, _connect() as conn:
        if tenant_id:
            exists = conn.execute(
                "SELECT 1 FROM handoff_sessions WHERE session_id = ? AND tenant_id = ?",
                (session_id, tenant_id),
            ).fetchone()
            if not exists:
                return
        conn.execute("DELETE FROM handoff_messages WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM handoff_transfer_events WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM business_audit_events WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM observer_audits WHERE session_id = ?", (session_id,))
        if tenant_id:
            conn.execute("DELETE FROM handoff_sessions WHERE session_id = ? AND tenant_id = ?", (session_id, tenant_id))
        else:
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
                    COALESCE(enqueued_at, created_at, updated_at) ASC
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
                    COALESCE(enqueued_at, created_at, updated_at) ASC
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
        if role == "human" and (meta or {}).get("kind") != "welcome":
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


def delete_message(session_id: str, message_id: int, tenant_id: str) -> bool:
    """仅删除指定租户、会话中的单条消息。"""
    with _lock, _connect() as conn:
        cur = conn.execute(
            """
            DELETE FROM handoff_messages
            WHERE id = ? AND session_id = ?
              AND EXISTS (
                SELECT 1 FROM handoff_sessions
                WHERE session_id = ? AND tenant_id = ?
              )
            """,
            (message_id, session_id, session_id, tenant_id or "mitako"),
        )
        return cur.rowcount == 1


def ensure_chat_session(session_id: str, user_id: str, tenant_id: str = "mitako") -> Dict[str, Any]:
    entry = get_session(session_id)
    if entry:
        existing_user = entry.get("user_id") or (entry.get("brief") or {}).get("user_id") or ""
        existing_tenant = entry.get("tenant_id") or (entry.get("brief") or {}).get("tenant_id") or "mitako"
        if existing_user and user_id and existing_user != user_id:
            raise ValueError("chat_session_user_mismatch")
        if (existing_tenant or "mitako") != (tenant_id or "mitako"):
            raise ValueError("chat_session_tenant_mismatch")
        return entry
    now = time.time()
    entry = {
        "session_id": session_id,
        "user_id": user_id,
        "tenant_id": tenant_id or "mitako",
        "status": "chatting",
        "required_tier": "standard",
        "brief": {"user_id": user_id, "tenant_id": tenant_id or "mitako"},
        "position": 0,
        "ahead": 0,
        "eta_minutes": 0,
        "enqueued_at": now,
        "observer_mode": True,
        "created_at": now,
    }
    upsert_session(entry)
    return entry


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


def recent_chat_history(session_id: str, limit: int = 20) -> List[Dict[str, str]]:
    messages = get_messages_since(session_id, 0)
    picked = []
    for msg in messages:
        role = msg.get("role")
        if role == "human":
            role = "assistant"
        if role in ("user", "assistant"):
            picked.append({"role": role, "content": msg.get("content", "")})
    return picked[-limit:]


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


def list_all_transfer_events(limit: int = 100, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
    with _lock, _connect() as conn:
        if tenant_id:
            rows = conn.execute(
                """
                SELECT e.id, e.session_id, e.event_type, e.from_agent_id, e.to_agent_id, e.note, e.created_at
                FROM handoff_transfer_events e
                JOIN handoff_sessions s ON s.session_id = e.session_id
                WHERE s.tenant_id = ?
                ORDER BY e.created_at DESC LIMIT ?
                """,
                (tenant_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, session_id, event_type, from_agent_id, to_agent_id, note, created_at
                FROM handoff_transfer_events ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]


def append_business_event(
    *,
    session_id: str,
    event_type: str,
    status: str,
    user_id: str = "",
    tenant_id: str = "mitako",
    order_id: str = "",
    idempotency_key: str = "",
    payload: Optional[Dict[str, Any]] = None,
    result: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    ts = time.time()
    payload_json = _json_dumps(payload or {})
    result_json = _json_dumps(result or {})
    with _lock, _connect() as conn:
        if idempotency_key and order_id:
            existing = conn.execute(
                """
                SELECT * FROM business_audit_events
                WHERE tenant_id = ? AND order_id = ? AND event_type = ? AND idempotency_key = ?
                """,
                (tenant_id or "mitako", order_id, event_type, idempotency_key),
            ).fetchone()
            if existing:
                row = _row_to_business_event(existing)
                row["deduped"] = True
                return row
        cur = conn.execute(
            """
            INSERT INTO business_audit_events
                (session_id, tenant_id, user_id, order_id, event_type, idempotency_key, status, payload_json, result_json, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                session_id,
                tenant_id or "mitako",
                user_id or None,
                order_id or None,
                event_type,
                idempotency_key or "",
                status,
                payload_json,
                result_json,
                ts,
            ),
        )
        row_id = cur.lastrowid
    return {
        "id": row_id,
        "session_id": session_id,
        "tenant_id": tenant_id or "mitako",
        "user_id": user_id,
        "order_id": order_id,
        "event_type": event_type,
        "idempotency_key": idempotency_key,
        "status": status,
        "payload": payload or {},
        "result": result or {},
        "created_at": ts,
        "deduped": False,
    }


def _row_to_business_event(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "tenant_id": row["tenant_id"] if "tenant_id" in row.keys() else "mitako",
        "user_id": row["user_id"] or "",
        "order_id": row["order_id"] or "",
        "event_type": row["event_type"],
        "idempotency_key": row["idempotency_key"] or "",
        "status": row["status"],
        "payload": _json_loads(row["payload_json"], {}),
        "result": _json_loads(row["result_json"], {}),
        "created_at": row["created_at"],
    }


def business_event_checkpoint(session_id: str, tenant_id: str) -> int:
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(id), 0) AS checkpoint FROM business_audit_events WHERE session_id=? AND tenant_id=?",
            (session_id, tenant_id),
        ).fetchone()
        return int(row["checkpoint"] or 0)


def rollback_business_events(session_id: str, tenant_id: str, checkpoint: int) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "DELETE FROM business_audit_events WHERE session_id=? AND tenant_id=? AND id>?",
            (session_id, tenant_id, checkpoint),
        )


def list_business_events(
    *,
    session_id: str = "",
    order_id: str = "",
    event_type: str = "",
    tenant_id: str = "",
    limit: int = 100,
) -> List[Dict[str, Any]]:
    with _lock, _connect() as conn:
        q = "SELECT * FROM business_audit_events WHERE 1=1"
        params: List[Any] = []
        if session_id:
            q += " AND session_id = ?"
            params.append(session_id)
        if order_id:
            q += " AND order_id = ?"
            params.append(order_id)
        if event_type:
            q += " AND event_type = ?"
            params.append(event_type)
        if tenant_id:
            q += " AND tenant_id = ?"
            params.append(tenant_id)
        q += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(limit)
        return [_row_to_business_event(r) for r in conn.execute(q, params).fetchall()]


def list_sla_candidates(now: Optional[float] = None) -> List[Dict[str, Any]]:
    from handoff_routing import get_sla_config

    now = now or time.time()
    out: List[Dict[str, Any]] = []
    for sess in list_active_sessions():
        sla = get_sla_config(sess.get("tenant_id") or "mitako")
        if not sla.get("auto_transfer_enabled"):
            continue
        if sess.get("status") in {"queuing", "escalated"}:
            queue_timeout = 30 if sess.get("required_tier") == "supervisor" else 60
            enqueued = sess.get("enqueued_at") or sess.get("created_at") or 0
            if enqueued and (now - enqueued) > queue_timeout:
                out.append({**sess, "sla_reason": "queue_wait_timeout"})
            continue
        if sess.get("status") != "connected":
            continue
        first_sec = int(sla.get("first_response_seconds") or 180)
        reply_sec = int(sla.get("reply_timeout_seconds") or 300)
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
    tenant_id: Optional[str] = None,
) -> Dict[str, Any]:
    hits = [w for w in _OBSERVER_FLAG_WORDS if w in content]
    flagged = 1 if hits else 0
    ts = time.time()
    with _lock, _connect() as conn:
        tid = tenant_id or "mitako"
        row = conn.execute("SELECT tenant_id FROM handoff_sessions WHERE session_id = ?", (session_id,)).fetchone()
        if row and row["tenant_id"]:
            tid = row["tenant_id"]
        cur = conn.execute(
            """
            INSERT INTO observer_audits
                (session_id, tenant_id, message_id, content, flagged, policy_hits_json, reviewer_status, created_at)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (session_id, tid, message_id, content, flagged, _json_dumps(hits), "pending", ts),
        )
        audit_id = cur.lastrowid
    return {
        "id": audit_id,
        "session_id": session_id,
        "tenant_id": tid,
        "flagged": bool(flagged),
        "policy_hits": hits,
    }


def list_observer_audits(flagged_only: bool = False, limit: int = 50, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
    with _lock, _connect() as conn:
        q = "SELECT * FROM observer_audits WHERE 1=1"
        params: List[Any] = []
        if tenant_id:
            q += " AND tenant_id = ?"
            params.append(tenant_id)
        if flagged_only:
            q += " AND flagged = 1"
        q += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(q, params).fetchall()
        return [
            {
                "id": r["id"],
                "session_id": r["session_id"],
                "tenant_id": r["tenant_id"] if "tenant_id" in r.keys() else "mitako",
                "message_id": r["message_id"],
                "content": r["content"],
                "flagged": bool(r["flagged"]),
                "policy_hits": _json_loads(r["policy_hits_json"], []),
                "reviewer_status": r["reviewer_status"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]


def close_session_status(session_id: str, tenant_id: Optional[str] = None) -> bool:
    with _lock, _connect() as conn:
        if tenant_id:
            cur = conn.execute(
                "UPDATE handoff_sessions SET status='closed', updated_at=? WHERE session_id=? AND tenant_id=?",
                (time.time(), session_id, tenant_id),
            )
        else:
            cur = conn.execute(
                "UPDATE handoff_sessions SET status='closed', updated_at=? WHERE session_id=?",
                (time.time(), session_id),
            )
        return cur.rowcount > 0
