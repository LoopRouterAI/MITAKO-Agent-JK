# -*- coding: utf-8 -*-
"""审核案件 SQLite 状态存储。"""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

from runtime_paths import data_dir


DB_PATH = data_dir() / "review_service.db"
JSON_FIELDS = ("metadata", "assets", "result", "diagnostics")
MAX_JOB_ATTEMPTS = 3


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


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
              prior_total_tokens INTEGER NOT NULL DEFAULT 0,
              prior_estimated_usd REAL NOT NULL DEFAULT 0,
              attempts INTEGER NOT NULL DEFAULT 0,
              workbench_request_id TEXT NOT NULL DEFAULT '',
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
            CREATE TABLE IF NOT EXISTS review_job_attempts (
              job_id TEXT NOT NULL,
              attempt INTEGER NOT NULL,
              status TEXT NOT NULL,
              result TEXT NOT NULL DEFAULT '{}',
              diagnostics TEXT NOT NULL DEFAULT '{}',
              workbench_request_id TEXT NOT NULL DEFAULT '',
              started_at REAL NOT NULL DEFAULT 0,
              completed_at REAL NOT NULL,
              PRIMARY KEY(job_id, attempt)
            );
            CREATE INDEX IF NOT EXISTS idx_review_job_attempts_job
              ON review_job_attempts(job_id, attempt);
            """
        )
        cols = {row[1] for row in conn.execute("PRAGMA table_info(review_jobs)").fetchall()}
        if "lease_until" not in cols:
            conn.execute("ALTER TABLE review_jobs ADD COLUMN lease_until REAL NOT NULL DEFAULT 0")
        if "prior_total_tokens" not in cols:
            conn.execute("ALTER TABLE review_jobs ADD COLUMN prior_total_tokens INTEGER NOT NULL DEFAULT 0")
        if "prior_estimated_usd" not in cols:
            conn.execute("ALTER TABLE review_jobs ADD COLUMN prior_estimated_usd REAL NOT NULL DEFAULT 0")
        if "workbench_request_id" not in cols:
            conn.execute("ALTER TABLE review_jobs ADD COLUMN workbench_request_id TEXT NOT NULL DEFAULT ''")


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
            SET status='RUNNING',
                workbench_request_id=CASE
                    WHEN workbench_request_id='' THEN printf('%s-workbench-%d', job_id, attempts + 1)
                    ELSE workbench_request_id
                END,
                attempts=attempts+1, started_at=?, completed_at=0,
                diagnostics='{}', lease_until=?, updated_at=?
            WHERE job_id=? AND status IN ('QUEUED', 'RETRYING')
            """,
            (now, now + max(60, lease_seconds), now, job_id),
        )
    return cur.rowcount == 1


def finish_job(
    job_id: str,
    *,
    status: str,
    result: Dict[str, Any],
    diagnostics: Dict[str, Any],
    expected_attempts: int | None = None,
) -> Dict[str, Any]:
    now = time.time()
    with _connect() as conn:
        sql = """
            UPDATE review_jobs
            SET status=?, result=?, diagnostics=?, lease_until=0, completed_at=?, updated_at=?
            WHERE job_id=?
        """
        params: tuple[Any, ...] = (
            status,
            _json(result),
            _json(diagnostics),
            now,
            now,
            job_id,
        )
        if expected_attempts is not None:
            sql += " AND status='RUNNING' AND attempts=?"
            params = (*params, int(expected_attempts))
        cur = conn.execute(sql, params)
        if cur.rowcount:
            conn.execute(
                """
                INSERT INTO review_job_attempts(
                  job_id, attempt, status, result, diagnostics,
                  workbench_request_id, started_at, completed_at
                )
                SELECT job_id, attempts, ?, ?, ?, workbench_request_id, started_at, ?
                FROM review_jobs WHERE job_id=?
                ON CONFLICT(job_id, attempt) DO UPDATE SET
                  status=excluded.status,
                  result=excluded.result,
                  diagnostics=excluded.diagnostics,
                  workbench_request_id=excluded.workbench_request_id,
                  started_at=excluded.started_at,
                  completed_at=excluded.completed_at
                """,
                (status, _json(result), _json(diagnostics), now, job_id),
            )
    return get_job(job_id) or {}


def requeue_running_job(job_id: str, *, diagnostics: Dict[str, Any], expected_attempts: int) -> Dict[str, Any]:
    """把暂时资源繁忙的运行轮次退回队列，不把 429 误记成业务失败。"""
    now = time.time()
    with _connect() as conn:
        cur = conn.execute(
            """
            UPDATE review_jobs
            SET status='QUEUED', attempts=MAX(0, attempts-1), lease_until=0,
                started_at=0, completed_at=0, diagnostics=?, updated_at=?
            WHERE job_id=? AND status='RUNNING' AND attempts=?
            """,
            (_json(diagnostics), now, job_id, int(expected_attempts)),
        )
        if cur.rowcount:
            conn.execute(
                """
                INSERT OR REPLACE INTO review_job_attempts(
                  job_id, attempt, status, result, diagnostics,
                  workbench_request_id, started_at, completed_at
                )
                SELECT job_id, ?, 'RESOURCE_WAIT', '{}', ?,
                       workbench_request_id, started_at, ?
                FROM review_jobs WHERE job_id=?
                """,
                (int(expected_attempts), _json(diagnostics), now, job_id),
            )
    return get_job(job_id) or {}


def queue_retry(job_id: str) -> Optional[Dict[str, Any]]:
    now = time.time()
    with _connect() as conn:
        # 兼容迁移前已完成、但尚未写入轮次表的工单。
        conn.execute(
            """
            INSERT OR IGNORE INTO review_job_attempts(
              job_id, attempt, status, result, diagnostics,
              workbench_request_id, started_at, completed_at
            )
            SELECT job_id, attempts, status, result, diagnostics,
                   workbench_request_id, started_at, completed_at
            FROM review_jobs
            WHERE job_id=? AND status IN ('FAILED', 'SUCCEEDED')
            """,
            (job_id,),
        )
        cur = conn.execute(
            """
            UPDATE review_jobs
            SET status='RETRYING',
                prior_total_tokens=prior_total_tokens + COALESCE(
                    CAST(json_extract(result, '$.review.agent_report.inference_estimate.total_tokens') AS INTEGER),
                    0
                ),
                prior_estimated_usd=prior_estimated_usd + COALESCE(
                    CAST(json_extract(result, '$.review.agent_report.inference_estimate.estimated_usd') AS REAL),
                    0
                ),
                result='{}', diagnostics='{}', started_at=0,
                completed_at=0, lease_until=0, workbench_request_id='', updated_at=?
            WHERE job_id=? AND attempts<? AND (
                status='FAILED'
                OR (
                    status='SUCCEEDED'
                    AND (
                        json_extract(result, '$.review.advisory_assessment.workflow_recommendation')='system_retry'
                        OR (
                            json_extract(result, '$.review.agent_report.inference_estimate.native_video.technical_status')='failed'
                            AND COALESCE(
                                CAST(json_extract(result, '$.review.agent_report.inference_estimate.total_tokens') AS INTEGER),
                                0
                            )=0
                        )
                    )
                )
            )
            """,
            (now, job_id, MAX_JOB_ATTEMPTS),
        )
    return get_job(job_id) if cur.rowcount else None


def recover_incomplete() -> List[str]:
    init_db()
    now = time.time()
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO review_job_attempts(
              job_id, attempt, status, result, diagnostics,
              workbench_request_id, started_at, completed_at
            )
            SELECT job_id, attempts, 'LEASE_EXPIRED', result, ?,
                   workbench_request_id, started_at, ?
            FROM review_jobs
            WHERE status='RUNNING' AND (lease_until=0 OR lease_until<=?)
            """,
            (_json({"error_type": "lease_expired"}), now, now),
        )
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


def list_queued_job_ids(limit: int = 200) -> List[str]:
    """返回最早的待执行案件，供有界调度器补位；不改变案件状态。"""
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT job_id FROM review_jobs
            WHERE status IN ('QUEUED', 'RETRYING')
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (max(1, min(int(limit or 1), 200)),),
        ).fetchall()
    return [str(row[0]) for row in rows]


def discard_queued_job(job_id: str) -> bool:
    """容量拒绝时清理刚创建且尚未执行的案件，避免留下孤立队列项。"""
    init_db()
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM review_jobs WHERE job_id=? AND status='QUEUED' AND attempts=0",
            (job_id,),
        )
    return cur.rowcount == 1


def list_attempts(job_id: str) -> List[Dict[str, Any]]:
    """返回内部执行轮次；公开 API 和甲方报告不得直接透传。"""
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT job_id, attempt, status, result, diagnostics,
                   workbench_request_id, started_at, completed_at
            FROM review_job_attempts
            WHERE job_id=? ORDER BY attempt
            """,
            (job_id,),
        ).fetchall()
    output: List[Dict[str, Any]] = []
    for raw in rows:
        item = dict(raw)
        for key in ("result", "diagnostics"):
            try:
                item[key] = json.loads(item.get(key) or "{}")
            except json.JSONDecodeError:
                item[key] = {}
        output.append(item)
    return output


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


def list_batch(tenant_id: str, batch_id: str, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM review_jobs
            WHERE tenant_id=? AND json_extract(metadata, '$.batch_id')=?
            ORDER BY created_at ASC LIMIT ? OFFSET ?
            """,
            (tenant_id, batch_id, max(1, min(limit, 200)), max(0, offset)),
        ).fetchall()
    return [_row(row) or {} for row in rows]


def batch_snapshot(tenant_id: str, batch_id: str) -> List[Dict[str, Any]]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT
              status,
              COUNT(*) AS count,
              COALESCE(SUM(prior_total_tokens + COALESCE(CAST(json_extract(result, '$.review.agent_report.inference_estimate.total_tokens') AS INTEGER), 0)), 0) AS total_tokens,
              COALESCE(SUM(prior_estimated_usd + COALESCE(CAST(json_extract(result, '$.review.agent_report.inference_estimate.estimated_usd') AS REAL), 0)), 0) AS estimated_usd
            FROM review_jobs
            WHERE tenant_id=? AND json_extract(metadata, '$.batch_id')=?
            GROUP BY status
            """,
            (tenant_id, batch_id),
        ).fetchall()
    return [dict(row) for row in rows]


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
                SUM(prior_total_tokens + COALESCE(json_extract(result, '$.review.agent_report.inference_estimate.total_tokens'), 0)) AS total_tokens,
                SUM(prior_estimated_usd + COALESCE(json_extract(result, '$.review.agent_report.inference_estimate.estimated_usd'), 0)) AS estimated_usd
            FROM review_jobs
            WHERE 1=1
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
