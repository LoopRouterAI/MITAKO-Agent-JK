# -*- coding: utf-8 -*-
"""租户级视觉审核模型配置；版本存储在现有管理数据库。"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Sequence

from configs.model_catalog import MODEL_CONFIGS
from runtime_paths import db_path


_DB_PATH = str(db_path("MITAKO_ADMIN_DB_PATH", "admin.db"))
_db_ready = False
_lock = threading.RLock()
_SQLITE_TIMEOUT_SECONDS = 0.5
_DEFAULT_MODEL = "gemini35lite"
_DEFAULT_ENABLED = ("gemini35lite", "gemini37")


class VersionConflictError(RuntimeError):
    pass


def _tenant(value: str) -> str:
    tenant_id = str(value or "").strip()
    if not tenant_id:
        raise ValueError("租户不能为空")
    return tenant_id


def _default_snapshot(tenant_id: str) -> Dict[str, Any]:
    return {
        "tenant_id": _tenant(tenant_id),
        "version": 0,
        "default_model": _DEFAULT_MODEL,
        "enabled_models": list(_DEFAULT_ENABLED),
        "action": "built_in",
        "reason": "系统内置初始配置",
        "actor": "system",
        "actor_role": "system",
        "source_version": None,
        "created_at": None,
    }


def _ensure_db() -> None:
    global _db_ready
    if _db_ready:
        return
    Path(_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(_DB_PATH, timeout=_SQLITE_TIMEOUT_SECONDS) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS review_model_config_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                config_json TEXT NOT NULL,
                action TEXT NOT NULL,
                reason TEXT NOT NULL,
                actor TEXT NOT NULL,
                actor_role TEXT NOT NULL,
                source_version INTEGER,
                is_active INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                UNIQUE (tenant_id, version)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_review_model_config_active
                ON review_model_config_versions(tenant_id) WHERE is_active = 1;
            CREATE INDEX IF NOT EXISTS idx_review_model_config_history
                ON review_model_config_versions(tenant_id, version DESC);
            """
        )
    _db_ready = True


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    _ensure_db()
    conn = sqlite3.connect(_DB_PATH, timeout=_SQLITE_TIMEOUT_SECONDS)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _normalize_config(default_model: str, enabled_models: Sequence[str]) -> Dict[str, Any]:
    default_key = str(default_model or "").strip()
    requested = {str(item or "").strip() for item in enabled_models if str(item or "").strip()}
    unknown = ({default_key} | requested) - set(MODEL_CONFIGS)
    if unknown:
        raise ValueError(f"未知审核模型：{sorted(unknown)[0]}")
    enabled = [key for key in MODEL_CONFIGS if key in requested]
    if not enabled:
        raise ValueError("至少启用一个审核模型")
    if default_key not in enabled:
        raise ValueError("默认模型必须处于启用状态")
    return {"default_model": default_key, "enabled_models": enabled}


def _iso_timestamp(value: float) -> str:
    return datetime.fromtimestamp(float(value), timezone.utc).astimezone().isoformat(timespec="seconds")


def _row_snapshot(row: sqlite3.Row) -> Dict[str, Any]:
    config = json.loads(row["config_json"])
    return {
        "id": int(row["id"]),
        "tenant_id": row["tenant_id"],
        "version": int(row["version"]),
        **_normalize_config(config.get("default_model"), config.get("enabled_models") or []),
        "action": row["action"],
        "reason": row["reason"],
        "actor": row["actor"],
        "actor_role": row["actor_role"],
        "source_version": row["source_version"],
        "created_at": _iso_timestamp(row["created_at"]),
    }


def get_active_config(tenant_id: str) -> Dict[str, Any]:
    tenant_id = _tenant(tenant_id)
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM review_model_config_versions WHERE tenant_id=? AND is_active=1",
            (tenant_id,),
        ).fetchone()
    return _row_snapshot(row) if row is not None else _default_snapshot(tenant_id)


def get_model_state(tenant_id: str) -> Dict[str, Any]:
    snapshot = get_active_config(tenant_id)
    enabled = set(snapshot["enabled_models"])
    models = []
    for key, config in MODEL_CONFIGS.items():
        models.append({
            "key": key,
            "model": config["model"],
            "label": config["label"],
            "description": config.get("admin_description") or "成本受控的默认审核模型。",
            "enabled": key in enabled,
            "is_default": key == snapshot["default_model"],
            "automatic_fallback": False,
            "input_price": config.get("input_price"),
            "output_price": config.get("output_price"),
            "currency": config.get("currency"),
            "pricing_valid_until": config.get("pricing_valid_until"),
        })
    return {**snapshot, "models": models}


def _model_key(identifier: str) -> str | None:
    normalized = str(identifier or "").strip().lower()
    for key, config in MODEL_CONFIGS.items():
        if normalized in {key.lower(), str(config.get("model") or "").lower()}:
            return key
    return None


def runtime_model_keys(tenant_id: str, requested_model: str = "auto") -> List[str]:
    """返回本租户本次审核允许使用的真实模型顺序。"""
    snapshot = get_active_config(tenant_id)
    enabled = set(snapshot["enabled_models"])
    if requested_model != "auto":
        key = _model_key(requested_model)
        return [key] if key in enabled else []

    default_key = snapshot["default_model"]
    keys = [default_key]
    keys.extend(
        key
        for key, config in MODEL_CONFIGS.items()
        if key in enabled
        and key != default_key
        and not config.get("explicit_only")
    )
    return keys


def list_versions(tenant_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    tenant_id = _tenant(tenant_id)
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM review_model_config_versions WHERE tenant_id=? ORDER BY version DESC LIMIT ?",
            (tenant_id, max(1, min(int(limit), 500))),
        ).fetchall()
    return [_row_snapshot(row) for row in rows]


def publish_config(
    *, tenant_id: str, default_model: str, enabled_models: Sequence[str], reason: str,
    actor: str, actor_role: str, expected_active_version: int | None = None,
    source_version: int | None = None, action: str = "publish",
) -> Dict[str, Any]:
    tenant_id = _tenant(tenant_id)
    why = str(reason or "").strip()
    who = str(actor or "").strip()
    role = str(actor_role or "").strip()
    if len(why) < 10 or len(why) > 500:
        raise ValueError("修改原因必须填写 10 至 500 个字符")
    if not who or not role:
        raise ValueError("修改账号和角色不能为空")
    config = _normalize_config(default_model, enabled_models)
    now = time.time()
    with _lock, _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute(
            "SELECT version FROM review_model_config_versions WHERE tenant_id=? AND is_active=1",
            (tenant_id,),
        ).fetchone()
        current_version = int(current[0]) if current else 0
        if expected_active_version is not None and int(expected_active_version) != current_version:
            raise VersionConflictError("当前模型配置已被其他管理员更新，请刷新后重试")
        latest = conn.execute(
            "SELECT COALESCE(MAX(version), 0) FROM review_model_config_versions WHERE tenant_id=?",
            (tenant_id,),
        ).fetchone()[0]
        version = int(latest) + 1
        conn.execute(
            "UPDATE review_model_config_versions SET is_active=0 WHERE tenant_id=?",
            (tenant_id,),
        )
        conn.execute(
            """INSERT INTO review_model_config_versions
               (tenant_id, version, config_json, action, reason, actor, actor_role, source_version, is_active, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
            (
                tenant_id, version, json.dumps(config, ensure_ascii=False, sort_keys=True), action,
                why, who, role, source_version, now,
            ),
        )
    return get_active_config(tenant_id)


def rollback_config(
    *, tenant_id: str, target_version: int, reason: str, actor: str, actor_role: str,
    expected_active_version: int | None = None,
) -> Dict[str, Any]:
    tenant_id = _tenant(tenant_id)
    target = int(target_version)
    if target == 0:
        config = _default_snapshot(tenant_id)
    else:
        with _lock, _connect() as conn:
            row = conn.execute(
                "SELECT * FROM review_model_config_versions WHERE tenant_id=? AND version=?",
                (tenant_id, target),
            ).fetchone()
        if row is None:
            raise LookupError("目标历史版本不存在")
        config = _row_snapshot(row)
    return publish_config(
        tenant_id=tenant_id,
        default_model=config["default_model"],
        enabled_models=config["enabled_models"],
        reason=reason,
        actor=actor,
        actor_role=actor_role,
        expected_active_version=expected_active_version,
        source_version=target,
        action="rollback",
    )
