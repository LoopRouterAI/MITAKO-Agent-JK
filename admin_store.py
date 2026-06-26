# -*- coding: utf-8 -*-
"""管理员后台数据层 — 坐席档案等"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

_DB_DIR = os.path.join(os.path.dirname(__file__), "data")
_DB_PATH = os.path.join(_DB_DIR, "admin.db")
_lock = threading.RLock()
_db_ready = False

_DEMO_AGENTS: List[Dict[str, Any]] = [
    {"agent_id": "CS-0816", "name": "岚星", "title": "一线客服专员", "tier": "standard", "team": "外包A组·华东", "skills": ["物流", "安抚"], "enabled": True},
    {"agent_id": "CS-0922", "name": "晓棠", "title": "一线客服专员", "tier": "standard", "team": "外包B组·华南", "skills": ["盲盒", "换货"], "enabled": True},
    {"agent_id": "CS-1024", "name": "阿禾", "title": "总部客诉主管", "tier": "supervisor", "team": "甲方官方·客诉中心", "skills": ["投诉", "退款授权"], "enabled": True},
    {"agent_id": "CS-1203", "name": "沐澄", "title": "高级安抚顾问", "tier": "supervisor", "team": "甲方官方·VIP组", "skills": ["VIP", "舆情"], "enabled": True},
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
            CREATE TABLE IF NOT EXISTS agent_profiles (
                agent_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                title TEXT,
                tier TEXT NOT NULL DEFAULT 'standard',
                team TEXT,
                skills_json TEXT,
                enabled INTEGER DEFAULT 1,
                created_at REAL,
                updated_at REAL
            );
            CREATE TABLE IF NOT EXISTS approval_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                user_id TEXT,
                amount REAL NOT NULL,
                currency TEXT DEFAULT 'CNY',
                reason TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                requester TEXT,
                approver TEXT,
                approval_level INTEGER DEFAULT 1,
                created_at REAL,
                updated_at REAL
            );
            CREATE INDEX IF NOT EXISTS idx_approval_status ON approval_requests(status, created_at);
            """
        )
        conn.commit()
        cols = {r[1] for r in conn.execute("PRAGMA table_info(agent_profiles)").fetchall()}
        if "tenant_id" not in cols:
            conn.execute("ALTER TABLE agent_profiles ADD COLUMN tenant_id TEXT DEFAULT 'mitako'")
            conn.commit()
        acols = {r[1] for r in conn.execute("PRAGMA table_info(approval_requests)").fetchall()}
        if "tenant_id" not in acols:
            conn.execute("ALTER TABLE approval_requests ADD COLUMN tenant_id TEXT DEFAULT 'mitako'")
            conn.commit()
        count = conn.execute("SELECT COUNT(*) FROM agent_profiles").fetchone()[0]
        if count == 0:
            now = time.time()
            for a in _DEMO_AGENTS:
                conn.execute(
                    """
                    INSERT INTO agent_profiles
                        (agent_id, name, title, tier, team, skills_json, enabled, created_at, updated_at, tenant_id)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        a["agent_id"], a["name"], a["title"], a["tier"], a["team"],
                        json.dumps(a.get("skills") or [], ensure_ascii=False),
                        1 if a.get("enabled", True) else 0, now, now, "mitako",
                    ),
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


def _row_to_agent(row: sqlite3.Row) -> Dict[str, Any]:
    skills = []
    try:
        skills = json.loads(row["skills_json"] or "[]")
    except json.JSONDecodeError:
        pass
    return {
        "agent_id": row["agent_id"],
        "name": row["name"],
        "title": row["title"] or "",
        "tier": row["tier"] or "standard",
        "team": row["team"] or "",
        "skills": skills,
        "enabled": bool(row["enabled"]),
        "tenant_id": row["tenant_id"] if "tenant_id" in row.keys() else "mitako",
    }


def list_agents(enabled_only: bool = False, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
    with _lock, _connect() as conn:
        q = "SELECT * FROM agent_profiles WHERE 1=1"
        params: list = []
        if tenant_id:
            q += " AND tenant_id = ?"
            params.append(tenant_id)
        if enabled_only:
            q += " AND enabled = 1"
        q += " ORDER BY agent_id"
        return [_row_to_agent(r) for r in conn.execute(q, params).fetchall()]


def get_agent(agent_id: str, tenant_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    with _lock, _connect() as conn:
        if tenant_id:
            row = conn.execute(
                "SELECT * FROM agent_profiles WHERE agent_id = ? AND tenant_id = ?",
                (agent_id, tenant_id),
            ).fetchone()
        else:
            row = conn.execute("SELECT * FROM agent_profiles WHERE agent_id = ?", (agent_id,)).fetchone()
        return _row_to_agent(row) if row else None


def upsert_agent(data: Dict[str, Any]) -> Dict[str, Any]:
    now = time.time()
    skills = json.dumps(data.get("skills") or [], ensure_ascii=False)
    with _lock, _connect() as conn:
        conn.execute(
            """
            INSERT INTO agent_profiles
                (agent_id, name, title, tier, team, skills_json, enabled, created_at, updated_at, tenant_id)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(agent_id) DO UPDATE SET
                name=excluded.name, title=excluded.title, tier=excluded.tier,
                team=excluded.team, skills_json=excluded.skills_json,
                enabled=excluded.enabled, updated_at=excluded.updated_at,
                tenant_id=excluded.tenant_id
            """,
            (
                data["agent_id"], data["name"], data.get("title", ""),
                data.get("tier", "standard"), data.get("team", ""),
                skills, 1 if data.get("enabled", True) else 0, now, now,
                data.get("tenant_id") or "mitako",
            ),
        )
    return get_agent(data["agent_id"]) or data


def delete_agent(agent_id: str) -> bool:
    with _lock, _connect() as conn:
        cur = conn.execute("DELETE FROM agent_profiles WHERE agent_id = ?", (agent_id,))
        return cur.rowcount > 0


def _row_to_approval(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "session_id": row["session_id"] or "",
        "user_id": row["user_id"] or "",
        "amount": row["amount"],
        "currency": row["currency"] or "CNY",
        "reason": row["reason"] or "",
        "status": row["status"],
        "requester": row["requester"] or "",
        "approver": row["approver"] or "",
        "approval_level": row["approval_level"] or 1,
        "tenant_id": row["tenant_id"] if "tenant_id" in row.keys() else "mitako",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def create_approval(data: Dict[str, Any]) -> Dict[str, Any]:
    amount = float(data.get("amount") or 0)
    level = 2 if amount > 100 else 1
    now = time.time()
    with _lock, _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO approval_requests
                (session_id, user_id, amount, currency, reason, status, requester, approval_level, created_at, updated_at, tenant_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                data.get("session_id", ""),
                data.get("user_id", ""),
                amount,
                data.get("currency", "CNY"),
                data.get("reason", ""),
                "pending",
                data.get("requester", ""),
                level,
                now,
                now,
                data.get("tenant_id") or "mitako",
            ),
        )
        rid = cur.lastrowid
    return get_approval(int(rid)) or {}


def get_approval(approval_id: int) -> Optional[Dict[str, Any]]:
    with _lock, _connect() as conn:
        row = conn.execute("SELECT * FROM approval_requests WHERE id = ?", (approval_id,)).fetchone()
        return _row_to_approval(row) if row else None


def list_approvals(status: str = "", limit: int = 100, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
    with _lock, _connect() as conn:
        q = "SELECT * FROM approval_requests WHERE 1=1"
        params: list = []
        if tenant_id:
            q += " AND tenant_id = ?"
            params.append(tenant_id)
        if status:
            q += " AND status = ?"
            params.append(status)
        q += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(q, params).fetchall()
        return [_row_to_approval(r) for r in rows]


def decide_approval(approval_id: int, decision: str, approver: str) -> Optional[Dict[str, Any]]:
    if decision not in ("approved", "rejected"):
        return None
    now = time.time()
    with _lock, _connect() as conn:
        row = conn.execute("SELECT * FROM approval_requests WHERE id = ?", (approval_id,)).fetchone()
        if not row or row["status"] != "pending":
            return None
        conn.execute(
            "UPDATE approval_requests SET status = ?, approver = ?, updated_at = ? WHERE id = ?",
            (decision, approver, now, approval_id),
        )
    return get_approval(approval_id)
