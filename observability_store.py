# -*- coding: utf-8 -*-
"""审核观测事件持久化；仅保存已由观测层过滤后的标量元数据。"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from runtime_paths import data_dir


def _db_path() -> Path:
    configured = os.getenv("MITAKO_OBSERVABILITY_DB", "").strip()
    return Path(configured).resolve() if configured else (data_dir() / "visual_observability.db").resolve()


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS visual_observability_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL DEFAULT '',
                job_id TEXT NOT NULL DEFAULT '',
                request_id TEXT NOT NULL DEFAULT '',
                visibility TEXT NOT NULL DEFAULT 'redacted',
                event TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_visual_events_job
              ON visual_observability_events(tenant_id, job_id, id DESC);
            CREATE INDEX IF NOT EXISTS idx_visual_events_request
              ON visual_observability_events(tenant_id, request_id, id DESC);
            CREATE INDEX IF NOT EXISTS idx_visual_events_created
              ON visual_observability_events(tenant_id, created_at DESC);
            """
        )


def record_event(payload: Dict[str, Any], *, visibility: str = "redacted") -> Optional[int]:
    """持久化已脱敏事件；日志存储失败不得影响审核主链。"""
    try:
        init_db()
        event = str(payload.get("event") or "unknown")[:120]
        tenant_id = str(payload.get("tenant_id") or "")[:128]
        job_id = str(payload.get("job_id") or "")[:128]
        request_id = str(payload.get("request_id") or "")[:256]
        created_at = float(payload.get("ts") or time.time())
        safe_payload = {key: value for key, value in payload.items() if isinstance(value, (str, int, float, bool)) or value is None}
        raw = json.dumps(safe_payload, ensure_ascii=False, separators=(",", ":"))[:16000]
        with _connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO visual_observability_events(
                  tenant_id, job_id, request_id, visibility, event, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (tenant_id, job_id, request_id, visibility, event, raw, created_at),
            )
            return int(cursor.lastrowid)
    except Exception:
        return None


def list_events(
    tenant_id: str,
    *,
    job_id: str = "",
    request_id: str = "",
    visibility: str = "redacted",
    limit: int = 100,
    since_id: int = 0,
) -> List[Dict[str, Any]]:
    init_db()
    clauses = ["tenant_id=?", "visibility=?"]
    params: List[Any] = [tenant_id, visibility]
    if job_id:
        clauses.append("job_id=?")
        params.append(job_id)
    if request_id:
        clauses.append("request_id=?")
        params.append(request_id)
    if since_id:
        clauses.append("id>?")
        params.append(int(since_id))
    params.append(max(1, min(int(limit), 500)))
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT id, job_id, request_id, visibility, event, payload_json, created_at "
            f"FROM visual_observability_events WHERE {' AND '.join(clauses)} "
            "ORDER BY id ASC LIMIT ?",
            tuple(params),
        ).fetchall()
    output: List[Dict[str, Any]] = []
    for row in rows:
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, ValueError):
            payload = {}
        output.append({
            "id": int(row["id"]),
            "job_id": row["job_id"],
            "request_id": row["request_id"],
            "visibility": row["visibility"],
            "event": row["event"],
            "created_at": row["created_at"],
            "data": payload,
        })
    return output


def summarize_events(tenant_id: str, *, job_id: str = "") -> Dict[str, Any]:
    events = list_events(tenant_id, job_id=job_id, limit=500)
    counts: Dict[str, int] = {}
    for item in events:
        counts[item["event"]] = counts.get(item["event"], 0) + 1
    return {
        "event_count": len(events),
        "event_types": counts,
        "last_event_id": events[-1]["id"] if events else 0,
        "visibility": "redacted",
    }


def summarize_request(request_id: str, *, tenant_id: str = "") -> Dict[str, Any]:
    events = list_events(tenant_id, request_id=request_id, limit=500)
    counts: Dict[str, int] = {}
    for item in events:
        counts[item["event"]] = counts.get(item["event"], 0) + 1
    return {
        "request_id": request_id,
        "event_count": len(events),
        "event_types": counts,
        "events": events,
        "visibility": "redacted",
    }
