# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath, PureWindowsPath


_MEDIA_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")


class MediaRegistry:
    def __init__(self, database: Path | str, root: Path | str) -> None:
        self._database = Path(database)
        self._root = Path(root).resolve()
        self._database.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def register(
        self,
        media_id: str,
        relative_path: str,
        *,
        expires_at: float | None = None,
    ) -> None:
        if not _MEDIA_ID_PATTERN.fullmatch(media_id):
            raise ValueError("media_id 必须是 32 位小写十六进制字符串")
        normalized_path = self._normalize_relative_path(relative_path)
        registered_at = time.time()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO media_registry(media_id, relative_path, expires_at, registered_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(media_id) DO UPDATE SET
                    relative_path = excluded.relative_path,
                    expires_at = excluded.expires_at,
                    registered_at = excluded.registered_at
                """,
                (media_id, normalized_path, expires_at, registered_at),
            )

    def get(self, media_id: str, *, now: float | None = None) -> str | None:
        if not _MEDIA_ID_PATTERN.fullmatch(media_id):
            return None
        checked_at = time.time() if now is None else now
        with self._connect() as connection:
            row = connection.execute(
                "SELECT relative_path, expires_at FROM media_registry WHERE media_id = ?",
                (media_id,),
            ).fetchone()
        if row is None:
            return None

        relative_path, expires_at = str(row[0]), row[1]
        if self._is_available(relative_path, expires_at, checked_at):
            return relative_path

        with self._connect() as connection:
            connection.execute(
                """
                DELETE FROM media_registry
                WHERE media_id = ? AND relative_path = ?
                  AND (expires_at = ? OR (expires_at IS NULL AND ? IS NULL))
                """,
                (media_id, relative_path, expires_at, expires_at),
            )
        return None

    def prune(self, *, now: float | None = None) -> int:
        checked_at = time.time() if now is None else now
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT media_id, relative_path, expires_at FROM media_registry"
            ).fetchall()
            stale_ids = [
                str(media_id)
                for media_id, relative_path, expires_at in rows
                if not self._is_available(str(relative_path), expires_at, checked_at)
            ]
            if stale_ids:
                connection.executemany(
                    "DELETE FROM media_registry WHERE media_id = ?",
                    ((media_id,) for media_id in stale_ids),
                )
            return len(stale_ids)

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS media_registry (
                    media_id TEXT PRIMARY KEY,
                    relative_path TEXT NOT NULL,
                    expires_at REAL,
                    registered_at REAL NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS media_registry_expiry ON media_registry(expires_at)"
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._database, timeout=30.0)
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _normalize_relative_path(self, value: str) -> str:
        if not isinstance(value, str) or not value.strip() or "\x00" in value:
            raise ValueError("媒体路径必须是非空相对路径")
        windows_path = PureWindowsPath(value)
        posix_path = PurePosixPath(value.replace("\\", "/"))
        if windows_path.is_absolute() or windows_path.drive or posix_path.is_absolute():
            raise ValueError("媒体路径不能是绝对路径")
        if any(part in {"", ".", ".."} for part in posix_path.parts):
            raise ValueError("媒体路径不能包含目录穿越")
        normalized = posix_path.as_posix()
        self._resolve_inside_root(normalized)
        return normalized

    def _resolve_inside_root(self, relative_path: str) -> Path:
        try:
            resolved = (self._root / Path(*PurePosixPath(relative_path).parts)).resolve()
        except (OSError, RuntimeError) as exc:
            raise ValueError("媒体路径无效") from exc
        if resolved == self._root or self._root not in resolved.parents:
            raise ValueError("媒体路径超出允许目录")
        return resolved

    def _is_available(
        self,
        relative_path: str,
        expires_at: float | None,
        now: float,
    ) -> bool:
        if expires_at is not None and float(expires_at) <= now:
            return False
        try:
            return self._resolve_inside_root(relative_path).is_file()
        except ValueError:
            return False
