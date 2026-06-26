# -*- coding: utf-8 -*-
"""Companion 独立 SQLite — 与 handoff.db 完全隔离"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

_DB_DIR = os.path.join(os.path.dirname(__file__), "data")
_DB_PATH = os.path.join(_DB_DIR, "companion.db")
_lock = threading.RLock()
_db_ready = False

_BAD_NAME_RE = re.compile(r"(傻逼|操你|去死|nigger|fuck)", re.I)

_PERSONALITIES = {
    "gentle": "温柔体贴，语速舒缓，多用关心语句",
    "genki": "元气活泼，适度 emoji 感但不用真 emoji，能量感强",
    "cool": "克制冷静，言简意赅，偶尔冷幽默",
    "onee": "成熟御姐风，可靠有主见",
}


def _ensure_db() -> None:
    global _db_ready
    if _db_ready:
        return
    os.makedirs(_DB_DIR, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS companion_personas (
                user_id TEXT PRIMARY KEY,
                agent_name TEXT NOT NULL,
                user_title TEXT NOT NULL DEFAULT '主人',
                personality TEXT NOT NULL DEFAULT 'gentle',
                onboarded INTEGER DEFAULT 0,
                created_at REAL,
                updated_at REAL
            );
            CREATE TABLE IF NOT EXISTS companion_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_companion_msg_user
                ON companion_messages(user_id, created_at);
            CREATE TABLE IF NOT EXISTS companion_watch_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                order_id TEXT NOT NULL,
                notify_on TEXT NOT NULL DEFAULT 'status_change',
                created_at REAL NOT NULL,
                UNIQUE(user_id, order_id)
            );
            CREATE TABLE IF NOT EXISTS companion_wishlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                product_id TEXT NOT NULL,
                note TEXT,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS companion_handoff_sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                reason TEXT,
                status TEXT NOT NULL DEFAULT 'queuing',
                assigned_operator TEXT,
                created_at REAL,
                updated_at REAL
            );
            CREATE TABLE IF NOT EXISTS companion_handoff_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS companion_turn_traces (
                turn_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL DEFAULT 'mitako',
                user_message TEXT,
                assistant_reply TEXT,
                emotion_level INTEGER DEFAULT 3,
                emotion_label TEXT,
                safety_status TEXT DEFAULT 'pass',
                safety_reason TEXT,
                agent_mode TEXT DEFAULT 'companion',
                duration_ms INTEGER DEFAULT 0,
                graph_trace_json TEXT,
                api_log_json TEXT,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_comp_trace_tenant_time
                ON companion_turn_traces(tenant_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_comp_trace_user
                ON companion_turn_traces(user_id, created_at DESC);
            CREATE TABLE IF NOT EXISTS companion_memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL DEFAULT 'mitako',
                category TEXT NOT NULL,
                memory_key TEXT NOT NULL,
                memory_value TEXT NOT NULL,
                source_message TEXT,
                confidence REAL DEFAULT 0.75,
                fingerprint TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE(user_id, tenant_id, fingerprint)
            );
            CREATE INDEX IF NOT EXISTS idx_comp_mem_user
                ON companion_memories(user_id, tenant_id, updated_at DESC);
            CREATE TABLE IF NOT EXISTS companion_adventure_sessions (
                user_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL DEFAULT 'mitako',
                active INTEGER NOT NULL DEFAULT 0,
                world_setting TEXT NOT NULL DEFAULT '',
                world_title TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (user_id, tenant_id)
            );
            CREATE TABLE IF NOT EXISTS companion_adventure_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL DEFAULT 'mitako',
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                choices_json TEXT,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_comp_adv_msg_user
                ON companion_adventure_messages(user_id, tenant_id, created_at);
            CREATE TABLE IF NOT EXISTS companion_adventure_bible (
                user_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL DEFAULT 'mitako',
                world_setting TEXT NOT NULL DEFAULT '',
                bible_json TEXT NOT NULL DEFAULT '{}',
                visual_style TEXT NOT NULL DEFAULT '',
                summary_text TEXT NOT NULL DEFAULT '',
                updated_at REAL NOT NULL,
                PRIMARY KEY (user_id, tenant_id)
            );
            CREATE TABLE IF NOT EXISTS companion_adventure_visual_assets (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL DEFAULT 'mitako',
                asset_type TEXT NOT NULL,
                entity_key TEXT NOT NULL,
                image_url TEXT NOT NULL DEFAULT '',
                prompt_text TEXT,
                prompt_hash TEXT,
                model_id TEXT,
                size TEXT,
                meta_json TEXT,
                status TEXT NOT NULL DEFAULT 'ready',
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_comp_adv_asset_user
                ON companion_adventure_visual_assets(user_id, tenant_id, entity_key);
            CREATE TABLE IF NOT EXISTS companion_adventure_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL DEFAULT 'mitako',
                from_turn INTEGER,
                to_turn INTEGER,
                summary_text TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            """
        )
        conn.commit()
        cols = {r[1] for r in conn.execute("PRAGMA table_info(companion_personas)").fetchall()}
        if "agent_mode" not in cols:
            conn.execute("ALTER TABLE companion_personas ADD COLUMN agent_mode TEXT DEFAULT 'companion'")
            conn.commit()
        if "phone" not in cols:
            conn.execute("ALTER TABLE companion_personas ADD COLUMN phone TEXT DEFAULT ''")
            conn.commit()
        if "relationship" not in cols:
            conn.execute("ALTER TABLE companion_personas ADD COLUMN relationship TEXT DEFAULT '搭档'")
            conn.commit()
        adv_cols = {r[1] for r in conn.execute("PRAGMA table_info(companion_adventure_messages)").fetchall()}
        if "inner_json" not in adv_cols:
            conn.execute("ALTER TABLE companion_adventure_messages ADD COLUMN inner_json TEXT")
            conn.commit()
        if "illust_asset_id" not in adv_cols:
            conn.execute("ALTER TABLE companion_adventure_messages ADD COLUMN illust_asset_id TEXT")
            conn.commit()
        if "illust_status" not in adv_cols:
            conn.execute("ALTER TABLE companion_adventure_messages ADD COLUMN illust_status TEXT DEFAULT 'none'")
            conn.commit()
        if "display_content" not in adv_cols:
            conn.execute("ALTER TABLE companion_adventure_messages ADD COLUMN display_content TEXT")
            conn.commit()
        for table in (
            "companion_personas",
            "companion_messages",
            "companion_watch_orders",
            "companion_wishlist",
            "companion_handoff_sessions",
        ):
            tcols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            if "tenant_id" not in tcols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN tenant_id TEXT DEFAULT 'mitako'")
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


def validate_agent_name(name: str) -> Optional[str]:
    n = (name or "").strip()
    if len(n) < 2 or len(n) > 16:
        return "name_length"
    if _BAD_NAME_RE.search(n):
        return "bad_word"
    return None


def validate_user_title(title: str) -> Optional[str]:
    t = (title or "").strip() or "主人"
    if len(t) < 1 or len(t) > 16:
        return "title_length"
    if _BAD_NAME_RE.search(t):
        return "bad_word"
    return None


def _validate_relationship_field(rel: str) -> Optional[str]:
    r = (rel or "搭档").strip()
    if len(r) < 1 or len(r) > 16:
        return "relationship_length"
    if _BAD_NAME_RE.search(r):
        return "bad_word"
    return None


def get_persona(user_id: str, tenant_id: str = "mitako") -> Optional[Dict[str, Any]]:
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM companion_personas WHERE user_id = ? AND tenant_id = ?",
            (user_id, tenant_id),
        ).fetchone()
        return dict(row) if row else None


def upsert_persona(user_id: str, data: Dict[str, Any], tenant_id: str = "mitako") -> Dict[str, Any]:
    err = validate_agent_name(data.get("agent_name", ""))
    if err:
        raise ValueError(err)
    terr = validate_user_title(data.get("user_title", "主人"))
    if terr:
        raise ValueError(terr)
    rel_err = _validate_relationship_field(data.get("relationship", "搭档"))
    if rel_err:
        raise ValueError(rel_err)
    now = time.time()
    with _lock, _connect() as conn:
        conn.execute(
            """
            INSERT INTO companion_personas
                (user_id, agent_name, user_title, personality, relationship, onboarded, phone, created_at, updated_at, tenant_id)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET
                agent_name=excluded.agent_name, user_title=excluded.user_title,
                personality=excluded.personality, relationship=excluded.relationship,
                onboarded=excluded.onboarded, phone=excluded.phone,
                updated_at=excluded.updated_at, tenant_id=excluded.tenant_id
            """,
            (
                user_id,
                data["agent_name"],
                data.get("user_title") or "主人",
                data.get("personality") or "gentle",
                (data.get("relationship") or "搭档").strip()[:16],
                1 if data.get("onboarded", True) else 0,
                (data.get("phone") or "").strip(),
                now,
                now,
                tenant_id,
            ),
        )
    return get_persona(user_id, tenant_id) or {}


def set_agent_mode(user_id: str, mode: str, tenant_id: str = "mitako") -> Optional[Dict[str, Any]]:
    if mode not in ("companion", "cs_parttime"):
        return None
    now = time.time()
    with _lock, _connect() as conn:
        cur = conn.execute(
            "UPDATE companion_personas SET agent_mode=?, updated_at=? WHERE user_id=? AND tenant_id=?",
            (mode, now, user_id, tenant_id),
        )
        if cur.rowcount == 0:
            return None
    return get_persona(user_id, tenant_id)


def append_message(user_id: str, role: str, content: str, tenant_id: str = "mitako") -> Dict[str, Any]:
    ts = time.time()
    with _lock, _connect() as conn:
        cur = conn.execute(
            "INSERT INTO companion_messages (user_id, role, content, created_at, tenant_id) VALUES (?,?,?,?,?)",
            (user_id, role, content, ts, tenant_id),
        )
        mid = cur.lastrowid
    return {"id": mid, "user_id": user_id, "role": role, "content": content, "created_at": ts, "tenant_id": tenant_id}


def list_messages(user_id: str, limit: int = 50, before_id: int = 0, tenant_id: str = "mitako") -> List[Dict[str, Any]]:
    with _lock, _connect() as conn:
        if before_id:
            rows = conn.execute(
                """
                SELECT id, user_id, role, content, created_at FROM companion_messages
                WHERE user_id = ? AND tenant_id = ? AND id < ? ORDER BY id DESC LIMIT ?
                """,
                (user_id, tenant_id, before_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, user_id, role, content, created_at FROM companion_messages
                WHERE user_id = ? AND tenant_id = ? ORDER BY id DESC LIMIT ?
                """,
                (user_id, tenant_id, limit),
            ).fetchall()
        return [dict(r) for r in reversed(rows)]


def personality_prompt(key: str) -> str:
    return _PERSONALITIES.get(key, _PERSONALITIES["gentle"])


# —— Phase C：盯单 / 心愿单 / 商品检索 ——

_MOCK_PRODUCTS = [
    {"product_id": "P001", "name": "排球少年 登校系列 吧唧", "price": 28.0, "stock": "现货"},
    {"product_id": "P002", "name": "原神 魈 比例手办", "price": 899.0, "stock": "预售"},
    {"product_id": "P003", "name": "咒术回战 盲盒 整盒", "price": 168.0, "stock": "少量"},
    {"product_id": "P004", "name": "初音未来 2024 限定", "price": 520.0, "stock": "缺货"},
]


def search_products(q: str = "", limit: int = 10) -> List[Dict[str, Any]]:
    needle = (q or "").strip().lower()
    hits = []
    for p in _MOCK_PRODUCTS:
        if not needle or needle in p["name"].lower() or needle in p["product_id"].lower():
            hits.append(p)
    return hits[:limit]


def add_watch_order(user_id: str, order_id: str, notify_on: str = "status_change", tenant_id: str = "mitako") -> Dict[str, Any]:
    ts = time.time()
    with _lock, _connect() as conn:
        conn.execute(
            """
            INSERT INTO companion_watch_orders (user_id, order_id, notify_on, created_at, tenant_id)
            VALUES (?,?,?,?,?)
            ON CONFLICT(user_id, order_id) DO UPDATE SET notify_on=excluded.notify_on, tenant_id=excluded.tenant_id
            """,
            (user_id, order_id, notify_on, ts, tenant_id),
        )
    return {"user_id": user_id, "order_id": order_id, "notify_on": notify_on, "created_at": ts, "tenant_id": tenant_id}


def list_watch_orders(user_id: str, tenant_id: str = "mitako") -> List[Dict[str, Any]]:
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT id, user_id, order_id, notify_on, created_at FROM companion_watch_orders WHERE user_id = ? AND tenant_id = ? ORDER BY created_at DESC",
            (user_id, tenant_id),
        ).fetchall()
        return [dict(r) for r in rows]


def add_wishlist(user_id: str, product_id: str, note: str = "", tenant_id: str = "mitako") -> Dict[str, Any]:
    ts = time.time()
    with _lock, _connect() as conn:
        cur = conn.execute(
            "INSERT INTO companion_wishlist (user_id, product_id, note, created_at, tenant_id) VALUES (?,?,?,?,?)",
            (user_id, product_id, note, ts, tenant_id),
        )
        wid = cur.lastrowid
    return {"id": wid, "user_id": user_id, "product_id": product_id, "note": note, "created_at": ts, "tenant_id": tenant_id}


def list_wishlist(user_id: str, tenant_id: str = "mitako") -> List[Dict[str, Any]]:
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT id, user_id, product_id, note, created_at FROM companion_wishlist WHERE user_id = ? AND tenant_id = ? ORDER BY created_at DESC",
            (user_id, tenant_id),
        ).fetchall()
        return [dict(r) for r in rows]


# —— Phase D：Companion 独立人工台 ——

def create_handoff_session(user_id: str, reason: str = "", tenant_id: str = "mitako") -> Dict[str, Any]:
    sid = f"cmp_{user_id}_{int(time.time())}"
    now = time.time()
    with _lock, _connect() as conn:
        conn.execute(
            """
            INSERT INTO companion_handoff_sessions (session_id, user_id, reason, status, created_at, updated_at, tenant_id)
            VALUES (?,?,?,?,?,?,?)
            """,
            (sid, user_id, reason, "queuing", now, now, tenant_id),
        )
    return get_handoff_session(sid, tenant_id) or {}


def get_handoff_session(session_id: str, tenant_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    with _lock, _connect() as conn:
        if tenant_id:
            row = conn.execute(
                "SELECT * FROM companion_handoff_sessions WHERE session_id = ? AND tenant_id = ?",
                (session_id, tenant_id),
            ).fetchone()
        else:
            row = conn.execute("SELECT * FROM companion_handoff_sessions WHERE session_id = ?", (session_id,)).fetchone()
        return dict(row) if row else None


def list_handoff_sessions(active_only: bool = True, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
    with _lock, _connect() as conn:
        q = "SELECT * FROM companion_handoff_sessions WHERE 1=1"
        params: list = []
        if tenant_id:
            q += " AND tenant_id = ?"
            params.append(tenant_id)
        if active_only:
            q += " AND status IN ('queuing','connected')"
        q += " ORDER BY updated_at DESC"
        if not active_only:
            q += " LIMIT 100"
        rows = conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]


def accept_handoff_session(session_id: str, operator: str, tenant_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    now = time.time()
    with _lock, _connect() as conn:
        if tenant_id:
            row = conn.execute(
                "SELECT * FROM companion_handoff_sessions WHERE session_id = ? AND tenant_id = ?",
                (session_id, tenant_id),
            ).fetchone()
        else:
            row = conn.execute("SELECT * FROM companion_handoff_sessions WHERE session_id = ?", (session_id,)).fetchone()
        if not row or row["status"] not in ("queuing",):
            return None
        conn.execute(
            "UPDATE companion_handoff_sessions SET status='connected', assigned_operator=?, updated_at=? WHERE session_id=?",
            (operator, now, session_id),
        )
    return get_handoff_session(session_id, tenant_id)


def append_handoff_message(session_id: str, role: str, content: str) -> Dict[str, Any]:
    ts = time.time()
    with _lock, _connect() as conn:
        cur = conn.execute(
            "INSERT INTO companion_handoff_messages (session_id, role, content, created_at) VALUES (?,?,?,?)",
            (session_id, role, content, ts),
        )
        mid = cur.lastrowid
        conn.execute("UPDATE companion_handoff_sessions SET updated_at=? WHERE session_id=?", (ts, session_id))
    return {"id": mid, "session_id": session_id, "role": role, "content": content, "created_at": ts}


def list_handoff_messages(session_id: str) -> List[Dict[str, Any]]:
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT id, session_id, role, content, created_at FROM companion_handoff_messages WHERE session_id=? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]


# —— 可观测 / LangGraph trace ——

def save_turn_trace(data: Dict[str, Any]) -> Dict[str, Any]:
    now = time.time()
    with _lock, _connect() as conn:
        conn.execute(
            """
            INSERT INTO companion_turn_traces (
                turn_id, user_id, tenant_id, user_message, assistant_reply,
                emotion_level, emotion_label, safety_status, safety_reason,
                agent_mode, duration_ms, graph_trace_json, api_log_json, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                data["turn_id"],
                data["user_id"],
                data.get("tenant_id") or "mitako",
                data.get("user_message") or "",
                data.get("assistant_reply") or "",
                int(data.get("emotion_level") or 3),
                data.get("emotion_label") or "",
                data.get("safety_status") or "pass",
                data.get("safety_reason") or "",
                data.get("agent_mode") or "companion",
                int(data.get("duration_ms") or 0),
                json.dumps(data.get("graph_trace") or [], ensure_ascii=False),
                json.dumps(data.get("api_log") or {}, ensure_ascii=False),
                now,
            ),
        )
    return get_turn_trace(data["turn_id"]) or {}


def get_turn_trace(turn_id: str, tenant_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    with _lock, _connect() as conn:
        if tenant_id:
            row = conn.execute(
                "SELECT * FROM companion_turn_traces WHERE turn_id = ? AND tenant_id = ?",
                (turn_id, tenant_id),
            ).fetchone()
        else:
            row = conn.execute("SELECT * FROM companion_turn_traces WHERE turn_id = ?", (turn_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["graph_trace"] = json.loads(d.pop("graph_trace_json") or "[]")
        d["api_log"] = json.loads(d.pop("api_log_json") or "{}")
        return d


def list_turn_traces(
    tenant_id: str = "mitako",
    limit: int = 50,
    filter_type: str = "",
    user_id: str = "",
    search_q: str = "",
    agent_mode: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """filter_type: safety | negative | positive | long；agent_mode: companion | adventure"""
    with _lock, _connect() as conn:
        needle = (search_q or "").strip()
        if needle or user_id:
            q = """
                SELECT t.*, p.agent_name, p.phone, p.user_title
                FROM companion_turn_traces t
                LEFT JOIN companion_personas p
                    ON t.user_id = p.user_id AND t.tenant_id = p.tenant_id
                WHERE t.tenant_id = ?
            """
        else:
            q = """
                SELECT t.*, p.agent_name, p.phone, p.user_title
                FROM companion_turn_traces t
                LEFT JOIN companion_personas p
                    ON t.user_id = p.user_id AND t.tenant_id = p.tenant_id
                WHERE t.tenant_id = ?
            """
        params: list = [tenant_id]
        if user_id:
            q += " AND t.user_id = ?"
            params.append(user_id)
        if needle:
            like = f"%{needle}%"
            q += " AND (t.user_id LIKE ? OR p.phone LIKE ? OR p.agent_name LIKE ? OR p.user_title LIKE ?)"
            params.extend([like, like, like, like])
        if agent_mode:
            q += " AND t.agent_mode = ?"
            params.append(agent_mode)
        if filter_type == "safety":
            q += " AND t.safety_status IN ('flag','block')"
        elif filter_type == "negative":
            q += " AND t.emotion_level >= 4"
        elif filter_type == "positive":
            q += " AND t.emotion_level <= 2"
        elif filter_type == "long":
            q += " AND length(t.user_message) >= 40"
        q += " ORDER BY t.created_at DESC LIMIT ?"
        params.append(min(limit, 200))
        rows = conn.execute(q, params).fetchall()
        out = []
        for row in rows:
            d = dict(row)
            d["graph_trace"] = json.loads(d.pop("graph_trace_json") or "[]")
            d["api_log"] = json.loads(d.pop("api_log_json") or "{}")
            out.append(d)
        return out


def observability_summary(tenant_id: str = "mitako", agent_mode: str = "companion") -> Dict[str, Any]:
    with _lock, _connect() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM companion_turn_traces WHERE tenant_id = ? AND agent_mode = ?",
            (tenant_id, agent_mode),
        ).fetchone()[0]
        safety = conn.execute(
            "SELECT COUNT(*) FROM companion_turn_traces WHERE tenant_id = ? AND agent_mode = ? AND safety_status IN ('flag','block')",
            (tenant_id, agent_mode),
        ).fetchone()[0]
        negative = conn.execute(
            "SELECT COUNT(*) FROM companion_turn_traces WHERE tenant_id = ? AND agent_mode = ? AND emotion_level >= 4",
            (tenant_id, agent_mode),
        ).fetchone()[0]
        positive = conn.execute(
            "SELECT COUNT(*) FROM companion_turn_traces WHERE tenant_id = ? AND agent_mode = ? AND emotion_level <= 2",
            (tenant_id, agent_mode),
        ).fetchone()[0]
        long_chat = conn.execute(
            "SELECT COUNT(*) FROM companion_turn_traces WHERE tenant_id = ? AND agent_mode = ? AND length(user_message) >= 40",
            (tenant_id, agent_mode),
        ).fetchone()[0]
        users = conn.execute(
            "SELECT COUNT(DISTINCT user_id) FROM companion_turn_traces WHERE tenant_id = ? AND agent_mode = ?",
            (tenant_id, agent_mode),
        ).fetchone()[0]
    return {
        "total_turns": total,
        "safety_flags": safety,
        "negative_emotion": negative,
        "positive_emotion": positive,
        "long_conversations": long_chat,
        "active_users": users,
        "agent_mode": agent_mode,
    }


def observability_adventure_summary(tenant_id: str = "mitako") -> Dict[str, Any]:
    """冒险模式专用 KPI — 使用率、稳定性、时长、估算成本"""
    base = observability_summary(tenant_id, agent_mode="adventure")
    companion_total = observability_summary(tenant_id, agent_mode="companion").get("total_turns") or 0
    adv_total = base.get("total_turns") or 0
    usage_rate = round(adv_total / max(companion_total + adv_total, 1) * 100, 1)
    stability = round(max(0.0, 100.0 - (base.get("safety_flags") or 0) / max(adv_total, 1) * 100), 1)
    with _lock, _connect() as conn:
        row = conn.execute(
            """
            SELECT
                COALESCE(SUM(duration_ms), 0) AS total_ms,
                COALESCE(AVG(duration_ms), 0) AS avg_ms,
                COALESCE(SUM(CASE WHEN json_extract(api_log_json, '$.has_illust') = 1 THEN 1 ELSE 0 END), 0) AS illust_turns
            FROM companion_turn_traces
            WHERE tenant_id = ? AND agent_mode = 'adventure'
            """,
            (tenant_id,),
        ).fetchone()
    total_ms = int(row[0] or 0)
    avg_ms = int(row[1] or 0)
    illust_turns = int(row[2] or 0)
    cost_est = round(adv_total * 0.002 + illust_turns * 0.04, 3)
    satisfaction_proxy = round(min(100.0, stability * 0.6 + (100 - usage_rate * 0.1)), 1)
    return {
        **base,
        "usage_rate_pct": usage_rate,
        "stability_score": stability,
        "satisfaction_proxy": satisfaction_proxy,
        "total_duration_min": round(total_ms / 60000, 1),
        "avg_turn_ms": avg_ms,
        "illust_turns": illust_turns,
        "cost_est_usd": cost_est,
    }


def list_observability_users(
    tenant_id: str = "mitako",
    search_q: str = "",
    limit: int = 80,
) -> List[Dict[str, Any]]:
    """全局用户总览 — 支持手机号 / user_id / Agent 名搜索"""
    needle = (search_q or "").strip()
    with _lock, _connect() as conn:
        q = """
            SELECT
                p.user_id,
                p.agent_name,
                p.user_title,
                p.phone,
                p.personality,
                p.onboarded,
                p.created_at,
                COUNT(t.turn_id) AS turn_count,
                MAX(t.created_at) AS last_turn_at,
                SUM(CASE WHEN t.safety_status IN ('flag','block') THEN 1 ELSE 0 END) AS safety_count,
                (
                    SELECT emotion_level FROM companion_turn_traces t2
                    WHERE t2.user_id = p.user_id AND t2.tenant_id = p.tenant_id
                    ORDER BY t2.created_at DESC LIMIT 1
                ) AS last_emotion_level,
                (
                    SELECT emotion_label FROM companion_turn_traces t2
                    WHERE t2.user_id = p.user_id AND t2.tenant_id = p.tenant_id
                    ORDER BY t2.created_at DESC LIMIT 1
                ) AS last_emotion_label
            FROM companion_personas p
            LEFT JOIN companion_turn_traces t
                ON p.user_id = t.user_id AND p.tenant_id = t.tenant_id
            WHERE p.tenant_id = ?
        """
        params: list = [tenant_id]
        if needle:
            like = f"%{needle}%"
            q += " AND (p.user_id LIKE ? OR p.phone LIKE ? OR p.agent_name LIKE ? OR p.user_title LIKE ?)"
            params.extend([like, like, like, like])
        q += """
            GROUP BY p.user_id
            ORDER BY COALESCE(last_turn_at, p.updated_at, p.created_at) DESC
            LIMIT ?
        """
        params.append(min(limit, 200))
        rows = conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]


# —— 实时会话态（观测台轮询）——

_live_sessions: Dict[str, Dict[str, Any]] = {}


def touch_live_session(user_id: str, tenant_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    """更新 Companion 实时会话快照（单进程内存 + 线程安全）"""
    now = time.time()
    key = f"{tenant_id}:{user_id}"
    with _lock:
        base = _live_sessions.get(key) or {
            "user_id": user_id,
            "tenant_id": tenant_id,
            "status": "idle",
            "emotion_level": 3,
            "emotion_label": "平稳",
            "message_count": 0,
            "turn_count": 0,
            "last_user_snippet": "",
            "last_assistant_snippet": "",
            "agent_name": "",
            "phone": "",
            "started_at": now,
        }
        base.update(patch)
        base["updated_at"] = now
        _live_sessions[key] = base
        return dict(base)


def clear_live_session(user_id: str, tenant_id: str = "mitako") -> None:
    key = f"{tenant_id}:{user_id}"
    with _lock:
        _live_sessions.pop(key, None)


def list_live_sessions(tenant_id: str = "mitako", max_age_sec: int = 300) -> List[Dict[str, Any]]:
    """返回最近活跃或正在流式回复的会话"""
    cutoff = time.time() - max(30, max_age_sec)
    persona_cache: Dict[str, Dict[str, Any]] = {}
    out: List[Dict[str, Any]] = []
    with _lock:
        items = list(_live_sessions.values())
    for item in items:
        if item.get("tenant_id") != tenant_id:
            continue
        updated = float(item.get("updated_at") or 0)
        status = item.get("status") or "idle"
        if status != "streaming" and updated < cutoff:
            continue
        uid = item.get("user_id") or ""
        if uid and uid not in persona_cache:
            persona_cache[uid] = get_persona(uid, tenant_id) or {}
        persona = persona_cache.get(uid) or {}
        row = dict(item)
        row["agent_name"] = row.get("agent_name") or persona.get("agent_name") or ""
        row["phone"] = row.get("phone") or persona.get("phone") or ""
        out.append(row)
    out.sort(key=lambda x: (0 if x.get("status") == "streaming" else 1, -(x.get("updated_at") or 0)))
    return out


def clear_messages(user_id: str, tenant_id: str = "mitako") -> int:
    """清空用户聊天记录，返回删除条数"""
    with _lock, _connect() as conn:
        cur = conn.execute(
            "DELETE FROM companion_messages WHERE user_id = ? AND tenant_id = ?",
            (user_id, tenant_id),
        )
        return int(cur.rowcount or 0)


def count_messages(user_id: str, tenant_id: str = "mitako") -> int:
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM companion_messages WHERE user_id = ? AND tenant_id = ?",
            (user_id, tenant_id),
        ).fetchone()
        return int(row[0] if row else 0)


def count_turns(user_id: str, tenant_id: str = "mitako") -> int:
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM companion_turn_traces WHERE user_id = ? AND tenant_id = ?",
            (user_id, tenant_id),
        ).fetchone()
        return int(row[0] if row else 0)


# —— 记忆系统（OpenViking 为主存储，SQLite 表保留兼容）——

def list_memories(user_id: str, tenant_id: str = "mitako", limit: int = 30) -> List[Dict[str, Any]]:
    from companion_viking import list_companion_memories

    return list_companion_memories(user_id, limit=limit)


def memory_summary(user_id: str, tenant_id: str = "mitako") -> Dict[str, Any]:
    from companion_viking import memory_summary as viking_summary

    return viking_summary(user_id)


def upsert_memories(user_id: str, items: List[Dict[str, Any]], tenant_id: str = "mitako") -> List[Dict[str, Any]]:
    """兼容旧调用 — 实际写入由 LangGraph update_memory → OpenViking 完成"""
    return list_memories(user_id, tenant_id=tenant_id, limit=40)


# —— 冒险模式（独立会话与消息，不与日常记忆互通）——

def get_adventure_session(user_id: str, tenant_id: str = "mitako") -> Optional[Dict[str, Any]]:
    _ensure_db()
    with _lock, _connect() as conn:
        row = conn.execute(
            """
            SELECT user_id, tenant_id, active, world_setting, world_title, created_at, updated_at
            FROM companion_adventure_sessions
            WHERE user_id = ? AND tenant_id = ?
            """,
            (user_id, tenant_id),
        ).fetchone()
    if not row:
        return None
    return {
        "user_id": row[0],
        "tenant_id": row[1],
        "active": bool(row[2]),
        "world_setting": row[3] or "",
        "world_title": row[4] or "",
        "created_at": row[5],
        "updated_at": row[6],
    }


def start_adventure_session(
    user_id: str,
    world_setting: str,
    world_title: str = "",
    tenant_id: str = "mitako",
) -> Dict[str, Any]:
    _ensure_db()
    now = time.time()
    title = (world_title or world_setting or "未知世界")[:80]
    with _lock, _connect() as conn:
        conn.execute(
            "DELETE FROM companion_adventure_messages WHERE user_id = ? AND tenant_id = ?",
            (user_id, tenant_id),
        )
        conn.execute(
            "DELETE FROM companion_adventure_visual_assets WHERE user_id = ? AND tenant_id = ?",
            (user_id, tenant_id),
        )
        conn.execute(
            "DELETE FROM companion_adventure_summaries WHERE user_id = ? AND tenant_id = ?",
            (user_id, tenant_id),
        )
        conn.execute(
            """
            INSERT INTO companion_adventure_sessions
                (user_id, tenant_id, active, world_setting, world_title, created_at, updated_at)
            VALUES (?, ?, 1, ?, ?, ?, ?)
            ON CONFLICT(user_id, tenant_id) DO UPDATE SET
                active = 1,
                world_setting = excluded.world_setting,
                world_title = excluded.world_title,
                updated_at = excluded.updated_at
            """,
            (user_id, tenant_id, world_setting[:2000], title, now, now),
        )
    return get_adventure_session(user_id, tenant_id) or {}


def end_adventure_session(user_id: str, tenant_id: str = "mitako") -> bool:
    _ensure_db()
    now = time.time()
    with _lock, _connect() as conn:
        cur = conn.execute(
            """
            UPDATE companion_adventure_sessions
            SET active = 0, updated_at = ?
            WHERE user_id = ? AND tenant_id = ? AND active = 1
            """,
            (now, user_id, tenant_id),
        )
    return cur.rowcount > 0


def append_adventure_message(
    user_id: str,
    role: str,
    content: str,
    tenant_id: str = "mitako",
    choices: Optional[List[Dict[str, Any]]] = None,
    *,
    display_content: Optional[str] = None,
    inner_json: Optional[str] = None,
    illust_status: str = "none",
    illust_asset_id: Optional[str] = None,
) -> int:
    _ensure_db()
    now = time.time()
    choices_json = json.dumps(choices or [], ensure_ascii=False) if choices else None
    display = display_content if display_content is not None else content
    with _lock, _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO companion_adventure_messages
                (user_id, tenant_id, role, content, display_content, choices_json,
                 inner_json, illust_status, illust_asset_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id, tenant_id, role, content, display, choices_json,
                inner_json, illust_status, illust_asset_id, now,
            ),
        )
        return int(cur.lastrowid or 0)


def list_adventure_messages(
    user_id: str,
    tenant_id: str = "mitako",
    limit: int = 80,
) -> List[Dict[str, Any]]:
    _ensure_db()
    with _lock, _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, role, content, display_content, choices_json, inner_json,
                   illust_status, illust_asset_id, created_at
            FROM companion_adventure_messages
            WHERE user_id = ? AND tenant_id = ?
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (user_id, tenant_id, limit),
        ).fetchall()
    out: List[Dict[str, Any]] = []
    for row in rows:
        choices: List[Dict[str, Any]] = []
        if row[4]:
            try:
                choices = json.loads(row[4])
            except json.JSONDecodeError:
                choices = []
        inner = None
        if row[5]:
            try:
                inner = json.loads(row[5])
            except json.JSONDecodeError:
                inner = None
        illust = None
        illust_status = row[6] or "none"
        asset_id = row[7]
        if asset_id and illust_status == "ready":
            asset = get_visual_asset_by_id(asset_id)
            if asset:
                illust = {
                    "status": "ready",
                    "url": asset.get("image_url"),
                    "aspect": "16:9" if "1536" in (asset.get("size") or "") and "2752" in (asset.get("size") or "") else "3:4",
                    "asset_id": asset_id,
                }
        elif illust_status in ("queued", "generating"):
            illust = {"status": illust_status}
        display = row[3] or row[2]
        out.append(
            {
                "id": row[0],
                "role": row[1],
                "content": display,
                "choices": choices,
                "inner": inner,
                "illust": illust,
                "created_at": row[8],
                "mode": "adventure",
            }
        )
    return out


def clear_adventure_messages(user_id: str, tenant_id: str = "mitako") -> int:
    """清空冒险模式聊天记录（不影响日常 companion_messages）"""
    _ensure_db()
    with _lock, _connect() as conn:
        cur = conn.execute(
            "DELETE FROM companion_adventure_messages WHERE user_id = ? AND tenant_id = ?",
            (user_id, tenant_id),
        )
        return int(cur.rowcount or 0)


def clear_adventure_summary(user_id: str, tenant_id: str = "mitako") -> bool:
    """清空冒险前情摘要（保留 World Bible 与世界观设定）"""
    _ensure_db()
    now = time.time()
    with _lock, _connect() as conn:
        cur = conn.execute(
            """
            UPDATE companion_adventure_bible SET summary_text = '', updated_at = ?
            WHERE user_id = ? AND tenant_id = ?
            """,
            (now, user_id, tenant_id),
        )
        return bool(cur.rowcount)


def reset_adventure_context(
    user_id: str,
    mode: str = "messages",
    tenant_id: str = "mitako",
) -> Dict[str, Any]:
    """
    Talkie 式分档清除冒险上下文。
    - messages: 仅清可见对话（保留前情摘要 + Bible）
    - chapter: 清对话 + 前情摘要（保留 Bible / 世界观）
    """
    mode = (mode or "messages").strip().lower()
    deleted_messages = clear_adventure_messages(user_id, tenant_id=tenant_id)
    summary_cleared = False
    if mode in ("chapter", "memory", "summary"):
        summary_cleared = clear_adventure_summary(user_id, tenant_id=tenant_id)
    return {
        "mode": mode,
        "deleted_messages": deleted_messages,
        "summary_cleared": summary_cleared,
    }


# —— 冒险 Bible / 视觉资产 / 摘要 ——

def upsert_adventure_bible(
    user_id: str,
    bible: Dict[str, Any],
    world_setting: str = "",
    tenant_id: str = "mitako",
) -> Dict[str, Any]:
    _ensure_db()
    now = time.time()
    visual = bible.get("visual_style") or ""
    with _lock, _connect() as conn:
        conn.execute(
            """
            INSERT INTO companion_adventure_bible
                (user_id, tenant_id, world_setting, bible_json, visual_style, summary_text, updated_at)
            VALUES (?, ?, ?, ?, ?, '', ?)
            ON CONFLICT(user_id, tenant_id) DO UPDATE SET
                world_setting = excluded.world_setting,
                bible_json = excluded.bible_json,
                visual_style = excluded.visual_style,
                updated_at = excluded.updated_at
            """,
            (user_id, tenant_id, world_setting[:2000], json.dumps(bible, ensure_ascii=False), visual, now),
        )
    return get_adventure_bible(user_id, tenant_id) or {}


def get_adventure_bible(user_id: str, tenant_id: str = "mitako") -> Optional[Dict[str, Any]]:
    _ensure_db()
    with _lock, _connect() as conn:
        row = conn.execute(
            """
            SELECT world_setting, bible_json, visual_style, summary_text, updated_at
            FROM companion_adventure_bible WHERE user_id = ? AND tenant_id = ?
            """,
            (user_id, tenant_id),
        ).fetchone()
    if not row:
        return None
    try:
        bible = json.loads(row[1] or "{}")
    except json.JSONDecodeError:
        bible = {}
    return {
        "world_setting": row[0] or "",
        "bible": bible,
        "visual_style": row[2] or "",
        "summary_text": row[3] or "",
        "updated_at": row[4],
    }


def update_adventure_summary(user_id: str, summary_text: str, tenant_id: str = "mitako") -> None:
    _ensure_db()
    now = time.time()
    with _lock, _connect() as conn:
        conn.execute(
            """
            UPDATE companion_adventure_bible SET summary_text = ?, updated_at = ?
            WHERE user_id = ? AND tenant_id = ?
            """,
            (summary_text, now, user_id, tenant_id),
        )
        conn.execute(
            """
            INSERT INTO companion_adventure_summaries
                (user_id, tenant_id, from_turn, to_turn, summary_text, created_at)
            VALUES (?, ?, 0, 0, ?, ?)
            """,
            (user_id, tenant_id, summary_text[:8000], now),
        )


def save_visual_asset(
    user_id: str,
    tenant_id: str,
    asset_type: str,
    entity_key: str,
    image_url: str,
    prompt_text: str,
    prompt_hash: str,
    model_id: str,
    size: str,
    meta: Optional[Dict[str, Any]] = None,
) -> str:
    _ensure_db()
    asset_id = f"asset_{uuid.uuid4().hex[:12]}"
    now = time.time()
    with _lock, _connect() as conn:
        conn.execute(
            """
            INSERT INTO companion_adventure_visual_assets
                (id, user_id, tenant_id, asset_type, entity_key, image_url,
                 prompt_text, prompt_hash, model_id, size, meta_json, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ready', ?)
            """,
            (
                asset_id, user_id, tenant_id, asset_type, entity_key, image_url,
                prompt_text[:8000], prompt_hash, model_id, size,
                json.dumps(meta or {}, ensure_ascii=False), now,
            ),
        )
    return asset_id


def get_visual_asset_by_id(asset_id: str) -> Optional[Dict[str, Any]]:
    _ensure_db()
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM companion_adventure_visual_assets WHERE id = ?",
            (asset_id,),
        ).fetchone()
    if not row:
        return None
    return _row_to_visual_asset(row)


def get_visual_asset_by_key(
    user_id: str,
    entity_key: str,
    tenant_id: str = "mitako",
) -> Optional[Dict[str, Any]]:
    _ensure_db()
    with _lock, _connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM companion_adventure_visual_assets
            WHERE user_id = ? AND tenant_id = ? AND entity_key = ? AND status = 'ready'
            ORDER BY created_at DESC LIMIT 1
            """,
            (user_id, tenant_id, entity_key),
        ).fetchone()
    if not row:
        return None
    return _row_to_visual_asset(row)


def _row_to_visual_asset(row) -> Dict[str, Any]:
    meta = {}
    if row["meta_json"]:
        try:
            meta = json.loads(row["meta_json"])
        except json.JSONDecodeError:
            meta = {}
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "asset_type": row["asset_type"],
        "entity_key": row["entity_key"],
        "image_url": row["image_url"],
        "model_id": row["model_id"],
        "size": row["size"],
        "meta": meta,
        "status": row["status"],
        "created_at": row["created_at"],
    }


def list_visual_assets(
    user_id: str,
    tenant_id: str = "mitako",
    status: str = "ready",
    limit: int = 30,
) -> List[Dict[str, Any]]:
    _ensure_db()
    with _lock, _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM companion_adventure_visual_assets
            WHERE user_id = ? AND tenant_id = ? AND status = ?
            ORDER BY created_at DESC LIMIT ?
            """,
            (user_id, tenant_id, status, limit),
        ).fetchall()
    return [_row_to_visual_asset(r) for r in rows]


def update_adventure_message_illust(
    message_id: int,
    user_id: str,
    tenant_id: str,
    illust_status: str,
    illust_asset_id: Optional[str] = None,
) -> None:
    _ensure_db()
    with _lock, _connect() as conn:
        if illust_asset_id:
            conn.execute(
                """
                UPDATE companion_adventure_messages
                SET illust_status = ?, illust_asset_id = ?
                WHERE id = ? AND user_id = ? AND tenant_id = ?
                """,
                (illust_status, illust_asset_id, message_id, user_id, tenant_id),
            )
        else:
            conn.execute(
                """
                UPDATE companion_adventure_messages
                SET illust_status = ?
                WHERE id = ? AND user_id = ? AND tenant_id = ?
                """,
                (illust_status, message_id, user_id, tenant_id),
            )


def count_turn_illusts(user_id: str, tenant_id: str = "mitako") -> int:
    _ensure_db()
    with _lock, _connect() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) FROM companion_adventure_visual_assets
            WHERE user_id = ? AND tenant_id = ? AND asset_type = 'turn_illust'
            """,
            (user_id, tenant_id),
        ).fetchone()
    return int(row[0] or 0)


def turns_since_last_illust(user_id: str, tenant_id: str = "mitako") -> int:
    """自上次 turn_illust 以来 assistant 消息数"""
    _ensure_db()
    with _lock, _connect() as conn:
        last = conn.execute(
            """
            SELECT created_at FROM companion_adventure_visual_assets
            WHERE user_id = ? AND tenant_id = ? AND asset_type = 'turn_illust'
            ORDER BY created_at DESC LIMIT 1
            """,
            (user_id, tenant_id),
        ).fetchone()
        if not last:
            return 999
        row = conn.execute(
            """
            SELECT COUNT(*) FROM companion_adventure_messages
            WHERE user_id = ? AND tenant_id = ? AND role = 'assistant' AND created_at > ?
            """,
            (user_id, tenant_id, last[0]),
        ).fetchone()
    return int(row[0] or 0)


def get_user_observability(user_id: str, tenant_id: str = "mitako") -> Optional[Dict[str, Any]]:
    persona = get_persona(user_id, tenant_id)
    if not persona:
        return None
    traces = list_turn_traces(tenant_id=tenant_id, user_id=user_id, limit=40)
    messages = list_messages(user_id, limit=50, tenant_id=tenant_id)
    with _lock, _connect() as conn:
        turn_count = conn.execute(
            "SELECT COUNT(*) FROM companion_turn_traces WHERE user_id = ? AND tenant_id = ?",
            (user_id, tenant_id),
        ).fetchone()[0]
        safety_count = conn.execute(
            "SELECT COUNT(*) FROM companion_turn_traces WHERE user_id = ? AND tenant_id = ? AND safety_status IN ('flag','block')",
            (user_id, tenant_id),
        ).fetchone()[0]
    memories = list_memories(user_id, tenant_id=tenant_id, limit=20)
    return {
        "user_id": user_id,
        "persona": persona,
        "turn_count": turn_count,
        "safety_count": safety_count,
        "last_emotion_level": traces[0].get("emotion_level") if traces else None,
        "last_emotion_label": traces[0].get("emotion_label") if traces else None,
        "traces": traces,
        "messages": messages,
        "memories": memories,
    }
