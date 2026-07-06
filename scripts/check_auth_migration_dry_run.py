# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import hashlib
import shutil
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _hash_password(password: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()


def _seed_old_auth_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE auth_users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                role TEXT NOT NULL,
                agent_id TEXT,
                display_name TEXT,
                enabled INTEGER DEFAULT 1,
                created_at REAL,
                updated_at REAL
            );
            INSERT INTO auth_users
                (username, password_hash, salt, role, agent_id, display_name, enabled, created_at, updated_at)
            VALUES
                ('legacy_admin', '""" + _hash_password("legacy-pass", "legacy_salt") + """', 'legacy_salt', 'super_admin', '', 'Legacy Admin', 1, 1, 1);
            """
        )


def _fingerprint(path: Path) -> tuple[int, int, str]:
    if not path.exists():
        return (0, 0, "")
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    stat = path.stat()
    return (stat.st_size, stat.st_mtime_ns, h.hexdigest())


def _integrity_check(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        row = conn.execute("PRAGMA integrity_check").fetchone()
    assert row and row[0] == "ok", f"sqlite integrity failed: {path}"


def _auth_rows(path: Path) -> list[tuple]:
    with sqlite3.connect(path) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(auth_users)").fetchall()}
        tenant_expr = "COALESCE(tenant_id, 'mitako')" if "tenant_id" in cols else "'mitako'"
        return conn.execute(
            f"""
            SELECT username, {tenant_expr}, password_hash, salt, role,
                   COALESCE(agent_id, ''), COALESCE(display_name, ''), COALESCE(enabled, 1)
            FROM auth_users
            ORDER BY 1, 2
            """
        ).fetchall()


def main() -> int:
    work_dir = Path(os.environ["MITAKO_DATA_DIR"]).resolve()
    assert ROOT in work_dir.parents, f"dry-run dir must stay under project: {work_dir}"
    work_dir.mkdir(parents=True, exist_ok=True)

    source = ROOT / "data" / "auth.db"
    target = work_dir / "auth.dry-run.db"
    backup = work_dir / f"auth.dry-run.backup.{int(time.time())}.db"
    source_before = _fingerprint(source)

    if source.exists():
        shutil.copy2(source, target)
    else:
        _seed_old_auth_db(target)
    shutil.copy2(target, backup)
    before_rows = _auth_rows(target)
    _integrity_check(backup)

    os.environ["MITAKO_AUTH_DB_PATH"] = str(target)

    import auth.store as auth_store

    auth_store.list_users()
    auto_backups = list(work_dir.glob("auth.dry-run.pre-tenant-migration.*.db"))
    for auto_backup in auto_backups:
        _integrity_check(auto_backup)
    auth_store.upsert_user("same_name", "tenant-a-pass", "desk_agent", tenant_id="tenant_a")
    auth_store.upsert_user("same_name", "tenant-b-pass", "super_admin", tenant_id="tenant_b")

    assert _fingerprint(source) == source_before, "source auth.db changed during dry-run"
    assert backup.exists(), "backup was not created"
    assert _auth_rows(backup) == before_rows, "manual backup does not match pre-migration rows"
    after_rows = _auth_rows(target)
    assert all(row in after_rows for row in before_rows), "legacy auth rows not preserved"
    if any(row[0] == "legacy_admin" for row in before_rows):
        assert auth_store.verify_user("legacy_admin", "legacy-pass", tenant_id="mitako"), "legacy password no longer verifies"
    assert auth_store.verify_user("same_name", "tenant-a-pass", tenant_id="tenant_a")
    assert auth_store.verify_user("same_name", "tenant-b-pass", tenant_id="tenant_b")
    assert not auth_store.verify_user("same_name", "tenant-a-pass", tenant_id="tenant_b")

    with sqlite3.connect(target) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        pk_cols = [r[1] for r in conn.execute("PRAGMA table_info(auth_users)").fetchall() if r[5]]
    assert pk_cols == ["username", "tenant_id"] or pk_cols == ["tenant_id", "username"], pk_cols
    print(f"auth migration dry-run ok: {target}")
    print(f"backup ok: {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
