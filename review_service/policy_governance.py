# -*- coding: utf-8 -*-
"""客服主管可配置的审核策略与媒体质量预算；不暴露 Prompt 或渠道密钥。"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Sequence

from runtime_paths import db_path


_DB_PATH = str(db_path("MITAKO_ADMIN_DB_PATH", "admin.db"))
_lock = threading.RLock()
_ready = False
_VALID_INTENSITIES = frozenset({"standard", "strong", "forensic"})
_DEFAULT_POLICY: Dict[str, Any] = {
    "review_intensity": "strong",
    "native_sampling_fps": 1.0,
    "max_frames": 24,
    "api_frame_limit": 24,
    "probe_seconds": 12,
    "opening_role_preflight": False,
    "one_fps_frame_fallback": False,
    "video_max_source_mb": 100,
    "video_max_long_edge": 2560,
    "video_max_fps": 24.0,
    "video_max_bitrate_mbps": 6.0,
    "video_min_short_edge": 1080,
    "image_resize_trigger_edge": 3840,
    "image_max_long_edge": 2560,
    "image_lossy_quality": 90,
    "preferred_video_codec": "vp9_webm",
}


class VersionConflictError(RuntimeError):
    pass


def _tenant(value: str) -> str:
    tenant = str(value or "").strip()
    if not tenant:
        raise ValueError("租户不能为空")
    return tenant


def _stamp(value: float | None) -> str | None:
    return datetime.fromtimestamp(float(value), timezone.utc).astimezone().isoformat(timespec="seconds") if value else None


def _ensure_db() -> None:
    global _ready
    if _ready:
        return
    Path(_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(_DB_PATH, timeout=0.5) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS review_policy_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                policy_json TEXT NOT NULL,
                action TEXT NOT NULL,
                reason TEXT NOT NULL,
                actor TEXT NOT NULL,
                actor_role TEXT NOT NULL,
                source_version INTEGER,
                is_active INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                UNIQUE (tenant_id, version)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_review_policy_active
                ON review_policy_versions(tenant_id) WHERE is_active = 1;
            CREATE INDEX IF NOT EXISTS idx_review_policy_history
                ON review_policy_versions(tenant_id, version DESC);
            """
        )
    _ready = True


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    _ensure_db()
    conn = sqlite3.connect(_DB_PATH, timeout=0.5)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _validate_reason(reason: str) -> str:
    value = str(reason or "").strip()
    if len(value) < 6 or len(value) > 500:
        raise ValueError("修改原因必须填写 6 至 500 个字符")
    return value


def _int(value: Any, name: str, low: int, high: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name}必须是数字") from None
    if not low <= parsed <= high:
        raise ValueError(f"{name}必须在 {low} 至 {high} 之间")
    return parsed


def _float(value: Any, name: str, low: float, high: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name}必须是数字") from None
    if not low <= parsed <= high:
        raise ValueError(f"{name}必须在 {low} 至 {high} 之间")
    return parsed


def normalize_policy(value: Dict[str, Any] | None) -> Dict[str, Any]:
    raw = {**_DEFAULT_POLICY, **(value if isinstance(value, dict) else {})}
    intensity = str(raw["review_intensity"]).strip()
    if intensity not in _VALID_INTENSITIES:
        raise ValueError("审核强度只能是 standard、strong 或 forensic")
    codec = str(raw["preferred_video_codec"]).strip()
    if codec not in {"vp9_webm", "hevc_mp4"}:
        raise ValueError("视频优先编码只能是 VP9 WebM 或 HEVC MP4")
    output = {
        "review_intensity": intensity,
        "native_sampling_fps": _float(raw["native_sampling_fps"], "原生视频抽样频率", 0.5, 2.0),
        "max_frames": _int(raw["max_frames"], "最大抽帧数", 1, 1800),
        "api_frame_limit": _int(raw["api_frame_limit"], "单次图片上限", 1, 24),
        "probe_seconds": _int(raw["probe_seconds"], "开箱预检秒数", 5, 60),
        "opening_role_preflight": bool(raw["opening_role_preflight"]),
        "one_fps_frame_fallback": bool(raw["one_fps_frame_fallback"]),
        "video_max_source_mb": _int(raw["video_max_source_mb"], "视频体积阈值", 50, 500),
        "video_max_long_edge": _int(raw["video_max_long_edge"], "视频最长边", 1080, 2560),
        "video_max_fps": _float(raw["video_max_fps"], "视频帧率阈值", 12, 60),
        "video_max_bitrate_mbps": _float(raw["video_max_bitrate_mbps"], "视频码率阈值", 1, 20),
        "video_min_short_edge": _int(raw["video_min_short_edge"], "视频最短边", 720, 1080),
        "image_resize_trigger_edge": _int(raw["image_resize_trigger_edge"], "图片触发缩放边", 2560, 8000),
        "image_max_long_edge": _int(raw["image_max_long_edge"], "图片最长边", 1080, 2560),
        "image_lossy_quality": _int(raw["image_lossy_quality"], "图片有损质量", 80, 100),
        "preferred_video_codec": codec,
    }
    if output["video_min_short_edge"] > output["video_max_long_edge"]:
        raise ValueError("视频最短边不能大于最长边")
    return output


def _default_snapshot(tenant_id: str) -> Dict[str, Any]:
    return {
        "tenant_id": _tenant(tenant_id), "version": 0, **normalize_policy(None),
        "action": "built_in", "reason": "系统内置初始配置", "actor": "system",
        "actor_role": "system", "source_version": None, "created_at": None,
    }


def _row(row: sqlite3.Row | None) -> Dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": int(row["id"]), "tenant_id": row["tenant_id"], "version": int(row["version"]),
        **normalize_policy(json.loads(row["policy_json"])), "action": row["action"],
        "reason": row["reason"], "actor": row["actor"], "actor_role": row["actor_role"],
        "source_version": row["source_version"], "created_at": _stamp(row["created_at"]),
    }


def get_active_policy(tenant_id: str) -> Dict[str, Any]:
    tenant = _tenant(tenant_id)
    with _lock, _connect() as conn:
        row = conn.execute("SELECT * FROM review_policy_versions WHERE tenant_id=? AND is_active=1", (tenant,)).fetchone()
    return _row(row) or _default_snapshot(tenant)


def list_versions(tenant_id: str, limit: int = 100) -> list[Dict[str, Any]]:
    tenant = _tenant(tenant_id)
    with _lock, _connect() as conn:
        rows = conn.execute("SELECT * FROM review_policy_versions WHERE tenant_id=? ORDER BY version DESC LIMIT ?", (tenant, max(1, min(int(limit), 500)))).fetchall()
    return [_row(item) for item in rows]


def publish_policy(*, tenant_id: str, policy: Dict[str, Any], reason: str, actor: str, actor_role: str, expected_active_version: int | None = None, source_version: int | None = None, action: str = "publish") -> Dict[str, Any]:
    tenant = _tenant(tenant_id)
    normalized = normalize_policy(policy)
    why = _validate_reason(reason)
    who, role = str(actor or "").strip(), str(actor_role or "").strip()
    if not who or not role:
        raise ValueError("修改账号和角色不能为空")
    now = time.time()
    with _lock, _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute("SELECT version FROM review_policy_versions WHERE tenant_id=? AND is_active=1", (tenant,)).fetchone()
        current_version = int(current[0]) if current else 0
        if expected_active_version is not None and int(expected_active_version) != current_version:
            raise VersionConflictError("当前审核策略已被其他主管更新，请刷新后重试")
        latest = int(conn.execute("SELECT COALESCE(MAX(version),0) FROM review_policy_versions WHERE tenant_id=?", (tenant,)).fetchone()[0])
        version = latest + 1
        conn.execute("UPDATE review_policy_versions SET is_active=0 WHERE tenant_id=?", (tenant,))
        conn.execute("INSERT INTO review_policy_versions (tenant_id,version,policy_json,action,reason,actor,actor_role,source_version,is_active,created_at) VALUES (?,?,?,?,?,?,?,?,1,?)", (tenant, version, json.dumps(normalized, ensure_ascii=False, sort_keys=True), action, why, who, role, source_version, now))
    return get_active_policy(tenant)


def rollback_policy(*, tenant_id: str, target_version: int, reason: str, actor: str, actor_role: str, expected_active_version: int | None = None) -> Dict[str, Any]:
    tenant = _tenant(tenant_id)
    target = int(target_version)
    if target == 0:
        policy = _DEFAULT_POLICY
    else:
        with _lock, _connect() as conn:
            row = conn.execute("SELECT policy_json FROM review_policy_versions WHERE tenant_id=? AND version=?", (tenant, target)).fetchone()
        if row is None:
            raise LookupError("目标历史策略不存在")
        policy = json.loads(row[0])
    return publish_policy(tenant_id=tenant, policy=policy, reason=reason, actor=actor, actor_role=actor_role, expected_active_version=expected_active_version, source_version=target, action="rollback")


def public_policy(policy: Dict[str, Any]) -> Dict[str, Any]:
    """只返回客服策略字段，避免把内部模型/Prompt 配置带到前端。"""
    return {key: policy[key] for key in _DEFAULT_POLICY}
