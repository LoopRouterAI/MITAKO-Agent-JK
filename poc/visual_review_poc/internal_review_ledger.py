# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator


class ReviewRequestLedger:
    """SQLite ledger that prevents duplicate paid reviews across processes."""

    def __init__(self, database: Path | str, *, completed_limit: int = 256) -> None:
        self._database = Path(database)
        self._completed_limit = max(1, int(completed_limit))
        self._database.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def claim(self, tenant_id: str, request_id: str) -> tuple[str, Dict[str, Any] | None]:
        now = time.time()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT state, response
                FROM internal_review_requests
                WHERE tenant_id=? AND request_id=?
                """,
                (tenant_id, request_id),
            ).fetchone()
            if row is not None:
                state = str(row[0])
                return state, self._decode(row[1]) if state == "completed" else None
            connection.execute(
                """
                INSERT INTO internal_review_requests(
                    tenant_id, request_id, state, response, created_at, updated_at
                ) VALUES (?, ?, 'running', '{}', ?, ?)
                """,
                (tenant_id, request_id, now, now),
            )
            self._prune_completed(connection)
        return "owner", None

    def lookup(self, tenant_id: str, request_id: str) -> tuple[str, Dict[str, Any] | None]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT state, response
                FROM internal_review_requests
                WHERE tenant_id=? AND request_id=?
                """,
                (tenant_id, request_id),
            ).fetchone()
        if row is None:
            return "missing", None
        state = str(row[0])
        return state, self._decode(row[1]) if state == "completed" else None

    def complete(self, tenant_id: str, request_id: str, response: Dict[str, Any]) -> None:
        now = time.time()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE internal_review_requests
                SET state='completed', response=?, updated_at=?
                WHERE tenant_id=? AND request_id=? AND state='running'
                """,
                (json.dumps(response, ensure_ascii=False), now, tenant_id, request_id),
            )

    def fail(self, tenant_id: str, request_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE internal_review_requests
                SET state='failed', updated_at=?
                WHERE tenant_id=? AND request_id=? AND state='running'
                """,
                (time.time(), tenant_id, request_id),
            )

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS internal_review_requests (
                    tenant_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    response TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(tenant_id, request_id)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS internal_review_requests_state_updated
                ON internal_review_requests(state, updated_at)
                """
            )

    def _prune_completed(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            DELETE FROM internal_review_requests
            WHERE state IN ('completed', 'failed')
              AND rowid NOT IN (
                SELECT rowid FROM internal_review_requests
                WHERE state IN ('completed', 'failed')
                ORDER BY updated_at DESC LIMIT ?
              )
            """,
            (self._completed_limit,),
        )

    @staticmethod
    def _decode(value: Any) -> Dict[str, Any]:
        try:
            decoded = json.loads(str(value or "{}"))
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._database, timeout=30.0)
        connection.execute("PRAGMA busy_timeout=30000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
