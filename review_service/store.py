# -*- coding: utf-8 -*-
"""审核案件 SQLite 状态存储。"""
from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Dict, List, Optional

from runtime_paths import data_dir


DB_PATH = data_dir() / "review_service.db"
JSON_FIELDS = ("metadata", "assets", "result", "diagnostics")


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _row(row: sqlite3.Row | None) -> Optional[Dict[str, Any]]:
    if not row:
        return None
    data = dict(row)
    for key in JSON_FIELDS:
        try:
            data[key] = json.loads(data.get(key) or ("[]" if key == "assets" else "{}"))
        except json.JSONDecodeError:
            data[key] = [] if key == "assets" else {}
    return data


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS review_jobs (
              job_id TEXT PRIMARY KEY,
              tenant_id TEXT NOT NULL,
              client_case_id TEXT NOT NULL,
              idempotency_key TEXT NOT NULL DEFAULT '',
              request_hash TEXT NOT NULL,
              scenario TEXT NOT NULL,
              status TEXT NOT NULL,
              metadata TEXT NOT NULL,
              assets TEXT NOT NULL,
              result TEXT NOT NULL DEFAULT '{}',
              diagnostics TEXT NOT NULL DEFAULT '{}',
              attempts INTEGER NOT NULL DEFAULT 0,
              lease_until REAL NOT NULL DEFAULT 0,
              created_at REAL NOT NULL,
              started_at REAL NOT NULL DEFAULT 0,
              completed_at REAL NOT NULL DEFAULT 0,
              updated_at REAL NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_review_jobs_idempotency
              ON review_jobs(tenant_id, idempotency_key)
              WHERE idempotency_key <> '';
            CREATE INDEX IF NOT EXISTS idx_review_jobs_status_created
              ON review_jobs(status, created_at DESC);
            """
        )
        cols = {row[1] for row in conn.execute("PRAGMA table_info(review_jobs)").fetchall()}
        if "lease_until" not in cols:
            conn.execute("ALTER TABLE review_jobs ADD COLUMN lease_until REAL NOT NULL DEFAULT 0")


def create_job(job: Dict[str, Any], request_hash: str) -> Dict[str, Any]:
    init_db()
    now = time.time()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO review_jobs(
              job_id, tenant_id, client_case_id, idempotency_key, request_hash,
              scenario, status, metadata, assets, result, diagnostics,
              attempts, created_at, started_at, completed_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, 0, 0, ?)
            """,
            (
                job["job_id"],
                job["tenant_id"],
                job["client_case_id"],
                job.get("idempotency_key") or "",
                request_hash,
                job["scenario"],
                "QUEUED",
                _json(job["metadata"]),
                _json(job["assets"]),
                "{}",
                "{}",
                now,
                now,
            ),
        )
    return get_job(job["job_id"]) or job


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    init_db()
    with _connect() as conn:
        return _row(conn.execute("SELECT * FROM review_jobs WHERE job_id=?", (job_id,)).fetchone())


def get_by_idempotency(tenant_id: str, key: str) -> Optional[Dict[str, Any]]:
    if not key:
        return None
    init_db()
    with _connect() as conn:
        return _row(
            conn.execute(
                "SELECT * FROM review_jobs WHERE tenant_id=? AND idempotency_key=?",
                (tenant_id, key),
            ).fetchone()
        )


def request_hash(job_id: str) -> str:
    init_db()
    with _connect() as conn:
        row = conn.execute("SELECT request_hash FROM review_jobs WHERE job_id=?", (job_id,)).fetchone()
    return str(row[0]) if row else ""


def claim_job(job_id: str, lease_seconds: int) -> bool:
    init_db()
    now = time.time()
    with _connect() as conn:
        cur = conn.execute(
            """
            UPDATE review_jobs
            SET status='RUNNING', attempts=attempts+1, started_at=?, completed_at=0,
                diagnostics='{}', lease_until=?, updated_at=?
            WHERE job_id=? AND status IN ('QUEUED', 'RETRYING')
            """,
            (now, now + max(60, lease_seconds), now, job_id),
        )
    return cur.rowcount == 1


def finish_job(job_id: str, *, status: str, result: Dict[str, Any], diagnostics: Dict[str, Any]) -> Dict[str, Any]:
    now = time.time()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE review_jobs
            SET status=?, result=?, diagnostics=?, lease_until=0, completed_at=?, updated_at=?
            WHERE job_id=?
            """,
            (status, _json(result), _json(diagnostics), now, now, job_id),
        )
    return get_job(job_id) or {}


def queue_retry(job_id: str) -> Optional[Dict[str, Any]]:
    now = time.time()
    with _connect() as conn:
        cur = conn.execute(
            """
            UPDATE review_jobs
            SET status='RETRYING', result='{}', diagnostics='{}', started_at=0,
                completed_at=0, lease_until=0, updated_at=?
            WHERE job_id=? AND status='FAILED'
            """,
            (now, job_id),
        )
    return get_job(job_id) if cur.rowcount else None


def recover_incomplete() -> List[str]:
    init_db()
    now = time.time()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE review_jobs
            SET status='QUEUED', lease_until=0, updated_at=?
            WHERE status='RUNNING' AND (lease_until=0 OR lease_until<=?)
            """,
            (now, now),
        )
        rows = conn.execute(
            "SELECT job_id FROM review_jobs WHERE status IN ('QUEUED', 'RETRYING') ORDER BY created_at"
        ).fetchall()
    return [str(row[0]) for row in rows]


def list_jobs(tenant_id: str, status: str = "", scenario: str = "", limit: int = 50) -> List[Dict[str, Any]]:
    init_db()
    clauses: List[str] = ["tenant_id=?"]
    params: List[Any] = [tenant_id]
    if status:
        clauses.append("status=?")
        params.append(status)
    if scenario:
        clauses.append("scenario=?")
        params.append(scenario)
    sql = "SELECT * FROM review_jobs"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(max(1, min(limit, 200)))
    with _connect() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [_row(row) or {} for row in rows]


def snapshot(tenant_id: str = "") -> Dict[str, Any]:
    init_db()
    now = time.time()
    where = " WHERE tenant_id=?" if tenant_id else ""
    params = (tenant_id,) if tenant_id else ()
    with _connect() as conn:
        counts = {
            row["status"].lower(): int(row["count"])
            for row in conn.execute(
                f"SELECT status, COUNT(*) AS count FROM review_jobs{where} GROUP BY status",
                params,
            ).fetchall()
        }
        latency = conn.execute(
            f"""
            SELECT AVG(completed_at - started_at) AS avg_seconds
            FROM review_jobs
            WHERE status='SUCCEEDED' AND completed_at > started_at AND started_at > 0
            {"AND tenant_id=?" if tenant_id else ""}
            """,
            params,
        ).fetchone()
        oldest = conn.execute(
            "SELECT MIN(created_at) FROM review_jobs WHERE status IN ('QUEUED', 'RETRYING')"
            + (" AND tenant_id=?" if tenant_id else ""),
            params,
        ).fetchone()[0]
        usage = conn.execute(
            f"""
            SELECT
                SUM(COALESCE(json_extract(result, '$.review.agent_report.inference_estimate.total_tokens'), 0)) AS total_tokens,
                SUM(COALESCE(json_extract(result, '$.review.agent_report.inference_estimate.estimated_usd'), 0)) AS estimated_usd
            FROM review_jobs
            WHERE status='SUCCEEDED'
            {"AND tenant_id=?" if tenant_id else ""}
            """,
            params,
        ).fetchone()
    return {
        "total": sum(counts.values()),
        "queued": counts.get("queued", 0) + counts.get("retrying", 0),
        "running": counts.get("running", 0),
        "succeeded": counts.get("succeeded", 0),
        "failed": counts.get("failed", 0),
        "average_latency_seconds": round(float(latency[0]), 3) if latency and latency[0] is not None else None,
        "oldest_queued_seconds": round(now - float(oldest), 3) if oldest else 0,
        "inference_total_tokens": int(usage[0] or 0),
        "inference_estimated_usd": round(float(usage[1] or 0), 6),
    }
