# -*- coding: utf-8 -*-
"""私域 Agent POC 存储：SQLite 本地可追踪，生产可替换为 PostgreSQL。"""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from runtime_paths import data_dir


DB_PATH = data_dir() / "private_domain.db"


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _json(data: Any) -> str:
    return json.dumps(data if data is not None else {}, ensure_ascii=False)


def _row(row: sqlite3.Row | None) -> Optional[Dict[str, Any]]:
    if not row:
        return None
    data = dict(row)
    for key in ("tags", "metrics", "payload", "result", "context", "evidence_messages"):
        if key in data:
            try:
                data[key] = json.loads(data[key] or "{}")
            except Exception:
                data[key] = {} if key != "evidence_messages" else []
    return data


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS private_groups (
              group_id TEXT PRIMARY KEY,
              group_name TEXT NOT NULL,
              owner_id TEXT NOT NULL DEFAULT '',
              member_count INTEGER NOT NULL DEFAULT 0,
              status TEXT NOT NULL DEFAULT 'normal',
              risk_level INTEGER NOT NULL DEFAULT 0,
              fatigue_score INTEGER NOT NULL DEFAULT 0,
              health_score INTEGER NOT NULL DEFAULT 100,
              marketing_disabled_until REAL NOT NULL DEFAULT 0,
              tags TEXT NOT NULL DEFAULT '{}',
              metrics TEXT NOT NULL DEFAULT '{}',
              updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS private_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              event_type TEXT NOT NULL,
              group_id TEXT NOT NULL DEFAULT '',
              user_id TEXT NOT NULL DEFAULT '',
              payload TEXT NOT NULL,
              result TEXT NOT NULL,
              created_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS product_events (
              event_id TEXT PRIMARY KEY,
              event_type TEXT NOT NULL,
              item_id TEXT NOT NULL,
              ip_name TEXT NOT NULL,
              character_name TEXT NOT NULL DEFAULT '',
              category TEXT NOT NULL DEFAULT '',
              stock INTEGER NOT NULL DEFAULT 0,
              risk_flag TEXT NOT NULL DEFAULT '',
              payload TEXT NOT NULL,
              created_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS private_campaign_candidates (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              event_id TEXT NOT NULL,
              group_id TEXT NOT NULL,
              match_score INTEGER NOT NULL,
              decision TEXT NOT NULL,
              reason TEXT NOT NULL,
              created_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS customer_service_tasks (
              task_id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              external_user_id TEXT NOT NULL DEFAULT '',
              group_id TEXT NOT NULL,
              risk_level INTEGER NOT NULL,
              issue_type TEXT NOT NULL,
              message_summary TEXT NOT NULL,
              evidence_messages TEXT NOT NULL,
              priority TEXT NOT NULL,
              required_action TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'pending',
              created_at REAL NOT NULL,
              updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS review_tasks (
              task_id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              session_id TEXT NOT NULL,
              tenant_id TEXT NOT NULL DEFAULT 'mitako',
              source TEXT NOT NULL DEFAULT 'customer_upload',
              client_case_id TEXT NOT NULL DEFAULT '',
              order_id TEXT NOT NULL DEFAULT '',
              scenario TEXT NOT NULL,
              file_name TEXT NOT NULL,
              stored_name TEXT NOT NULL,
              mime_type TEXT NOT NULL,
              size INTEGER NOT NULL,
              status TEXT NOT NULL,
              boundary TEXT NOT NULL,
              context TEXT NOT NULL DEFAULT '{}',
              result TEXT NOT NULL DEFAULT '{}',
              reviewed_at REAL NOT NULL DEFAULT 0,
              created_at REAL NOT NULL,
              updated_at REAL NOT NULL
            );
            """
        )
        cols = {row[1] for row in conn.execute("PRAGMA table_info(review_tasks)").fetchall()}
        if "result" not in cols:
            conn.execute("ALTER TABLE review_tasks ADD COLUMN result TEXT NOT NULL DEFAULT '{}'")
        if "reviewed_at" not in cols:
            conn.execute("ALTER TABLE review_tasks ADD COLUMN reviewed_at REAL NOT NULL DEFAULT 0")
        if "client_case_id" not in cols:
            conn.execute("ALTER TABLE review_tasks ADD COLUMN client_case_id TEXT NOT NULL DEFAULT ''")
        if "order_id" not in cols:
            conn.execute("ALTER TABLE review_tasks ADD COLUMN order_id TEXT NOT NULL DEFAULT ''")
        if "context" not in cols:
            conn.execute("ALTER TABLE review_tasks ADD COLUMN context TEXT NOT NULL DEFAULT '{}'")


def upsert_group(group: Dict[str, Any]) -> Dict[str, Any]:
    init_db()
    now = time.time()
    current = get_group(group["group_id"]) or {}
    merged_tags = {**(current.get("tags") or {}), **(group.get("tags") or {})}
    merged_metrics = {**(current.get("metrics") or {}), **(group.get("metrics") or {})}
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO private_groups (
              group_id, group_name, owner_id, member_count, status, risk_level,
              fatigue_score, health_score, marketing_disabled_until, tags, metrics, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(group_id) DO UPDATE SET
              group_name=excluded.group_name,
              owner_id=excluded.owner_id,
              member_count=excluded.member_count,
              status=excluded.status,
              risk_level=excluded.risk_level,
              fatigue_score=excluded.fatigue_score,
              health_score=excluded.health_score,
              marketing_disabled_until=excluded.marketing_disabled_until,
              tags=excluded.tags,
              metrics=excluded.metrics,
              updated_at=excluded.updated_at
            """,
            (
                group["group_id"],
                group.get("group_name") or current.get("group_name") or group["group_id"],
                group.get("owner_id") or current.get("owner_id") or "",
                int(group.get("member_count") or current.get("member_count") or 0),
                group.get("status") or current.get("status") or "normal",
                int(group.get("risk_level") if group.get("risk_level") is not None else current.get("risk_level") or 0),
                int(group.get("fatigue_score") if group.get("fatigue_score") is not None else current.get("fatigue_score") or 0),
                int(group.get("health_score") if group.get("health_score") is not None else current.get("health_score") or 100),
                float(group.get("marketing_disabled_until") or current.get("marketing_disabled_until") or 0),
                _json(merged_tags),
                _json(merged_metrics),
                now,
            ),
        )
    return get_group(group["group_id"]) or {}


def get_group(group_id: str) -> Optional[Dict[str, Any]]:
    init_db()
    with _connect() as conn:
        return _row(conn.execute("SELECT * FROM private_groups WHERE group_id=?", (group_id,)).fetchone())


def list_groups(limit: int = 50) -> List[Dict[str, Any]]:
    init_db()
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM private_groups ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
    return [_row(row) or {} for row in rows]


def add_event(event_type: str, payload: Dict[str, Any], result: Dict[str, Any], group_id: str = "", user_id: str = "") -> Dict[str, Any]:
    init_db()
    now = time.time()
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO private_events(event_type, group_id, user_id, payload, result, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (event_type, group_id, user_id, _json(payload), _json(result), now),
        )
        event_id = cur.lastrowid
    return {"id": event_id, "event_type": event_type, "group_id": group_id, "user_id": user_id, "payload": payload, "result": result, "created_at": now}


def list_events(limit: int = 30) -> List[Dict[str, Any]]:
    init_db()
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM private_events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [_row(row) or {} for row in rows]


def save_product_event(event: Dict[str, Any]) -> Dict[str, Any]:
    init_db()
    now = time.time()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO product_events(event_id, event_type, item_id, ip_name, character_name, category, stock, risk_flag, payload, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_id) DO UPDATE SET
              event_type=excluded.event_type,
              item_id=excluded.item_id,
              ip_name=excluded.ip_name,
              character_name=excluded.character_name,
              category=excluded.category,
              stock=excluded.stock,
              risk_flag=excluded.risk_flag,
              payload=excluded.payload
            """,
            (
                event["event_id"],
                event.get("event_type") or "",
                event.get("item_id") or "",
                event.get("ip_name") or "",
                event.get("character_name") or "",
                event.get("category") or "",
                int(event.get("stock") or 0),
                event.get("risk_flag") or "",
                _json(event),
                now,
            ),
        )
    return event


def add_campaign_candidate(event_id: str, group_id: str, match_score: int, decision: str, reason: str) -> None:
    init_db()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO private_campaign_candidates(event_id, group_id, match_score, decision, reason, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (event_id, group_id, int(match_score), decision, reason, time.time()),
        )


def add_campaign_candidates(event_id: str, candidates: List[Dict[str, Any]]) -> None:
    if not candidates:
        return
    init_db()
    created_at = time.time()
    with _connect() as conn:
        conn.executemany(
            "INSERT INTO private_campaign_candidates(event_id, group_id, match_score, decision, reason, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (event_id, item["group_id"], int(item["match_score"]), item["decision"], item["reason"], created_at)
                for item in candidates
            ],
        )


def list_campaign_candidates(event_id: str = "", limit: int = 50) -> List[Dict[str, Any]]:
    init_db()
    sql = "SELECT * FROM private_campaign_candidates"
    params: tuple[Any, ...] = ()
    if event_id:
        sql += " WHERE event_id=?"
        params = (event_id,)
    sql += " ORDER BY id DESC LIMIT ?"
    params = (*params, limit)
    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def create_customer_service_task(task: Dict[str, Any]) -> Dict[str, Any]:
    init_db()
    now = time.time()
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO customer_service_tasks(
              task_id, user_id, external_user_id, group_id, risk_level, issue_type,
              message_summary, evidence_messages, priority, required_action, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task["task_id"],
                task.get("user_id") or "",
                task.get("external_user_id") or "",
                task.get("group_id") or "",
                int(task.get("risk_level") or 0),
                task.get("issue_type") or "",
                task.get("message_summary") or "",
                _json(task.get("evidence_messages") or []),
                task.get("priority") or "normal",
                task.get("required_action") or "",
                task.get("status") or "pending",
                task.get("created_at") or now,
                now,
            ),
        )
    return get_customer_service_task(task["task_id"]) or task


def get_customer_service_task(task_id: str) -> Optional[Dict[str, Any]]:
    init_db()
    with _connect() as conn:
        return _row(conn.execute("SELECT * FROM customer_service_tasks WHERE task_id=?", (task_id,)).fetchone())


def list_customer_service_tasks(limit: int = 30) -> List[Dict[str, Any]]:
    init_db()
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM customer_service_tasks ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [_row(row) or {} for row in rows]


def create_review_task(task: Dict[str, Any]) -> Dict[str, Any]:
    init_db()
    now = time.time()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO review_tasks(
              task_id, user_id, session_id, tenant_id, source, client_case_id, order_id, scenario, file_name,
              stored_name, mime_type, size, status, boundary, context, result, reviewed_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task["task_id"],
                task.get("user_id") or "",
                task.get("session_id") or "",
                task.get("tenant_id") or "mitako",
                task.get("source") or "customer_upload",
                task.get("client_case_id") or "",
                task.get("order_id") or "",
                task.get("scenario") or "",
                task.get("file_name") or "",
                task.get("stored_name") or "",
                task.get("mime_type") or "",
                int(task.get("size") or 0),
                task.get("status") or "MATERIAL_READY",
                task.get("boundary") or "",
                _json(task.get("context") or {}),
                _json(task.get("result") or {}),
                float(task.get("reviewed_at") or 0),
                now,
                now,
            ),
        )
    return get_review_task(task["task_id"]) or task


def update_review_task_result(task_id: str, *, status: str, result: Dict[str, Any], boundary: str = "") -> Dict[str, Any]:
    init_db()
    now = time.time()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE review_tasks
            SET status=?, result=?, boundary=COALESCE(NULLIF(?, ''), boundary), reviewed_at=?, updated_at=?
            WHERE task_id=?
            """,
            (status, _json(result), boundary or "", now, now, task_id),
        )
    return get_review_task(task_id) or {}


def get_review_task(task_id: str) -> Optional[Dict[str, Any]]:
    init_db()
    with _connect() as conn:
        return _row(conn.execute("SELECT * FROM review_tasks WHERE task_id=?", (task_id,)).fetchone())


def list_review_tasks(limit: int = 30) -> List[Dict[str, Any]]:
    init_db()
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM review_tasks ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [_row(row) or {} for row in rows]


def clear_all_private_domain_data() -> Dict[str, int]:
    init_db()
    tables = (
        "private_campaign_candidates",
        "customer_service_tasks",
        "review_tasks",
        "product_events",
        "private_events",
        "private_groups",
    )
    with _connect() as conn:
        counts = {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in tables
        }
        for table in tables:
            conn.execute(f"DELETE FROM {table}")
        conn.execute(
            "DELETE FROM sqlite_sequence WHERE name IN (?, ?, ?)",
            ("private_campaign_candidates", "private_events", "review_tasks"),
        )
    return counts


def snapshot() -> Dict[str, Any]:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM private_groups) AS group_count,
              (SELECT COUNT(*) FROM private_groups WHERE risk_level >= 2 OR status='marketing_disabled') AS risky_group_count,
              (SELECT COUNT(*) FROM customer_service_tasks WHERE status='pending') AS pending_task_count,
              (SELECT COUNT(*) FROM review_tasks) AS review_task_count,
              (SELECT COUNT(*) FROM private_events) AS event_count
            """
        ).fetchone()
    return dict(row)


def upload_dir() -> Path:
    path = data_dir() / "private_domain_uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path
