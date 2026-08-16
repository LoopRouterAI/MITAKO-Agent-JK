# -*- coding: utf-8 -*-
"""SLA 分布式锁 — 与 handoff_ws 一致：仅 REDIS_HOST 配置时使用 Redis"""
from __future__ import annotations

import os
import threading
from typing import Optional, Set

_local_locks: Set[str] = set()
_local_mutex = threading.Lock()


def _redis_client():
    host = os.getenv("REDIS_HOST", "").strip()
    if not host:
        return None
    try:
        import redis

        return redis.Redis(
            host=host,
            port=int(os.getenv("REDIS_PORT", "6379")),
            db=int(os.getenv("REDIS_DB", "0")),
            password=os.getenv("REDIS_PASSWORD") or None,
            decode_responses=True,
        )
    except Exception:
        return None


def try_acquire_sla_lock(session_id: str, ttl_seconds: int = 120) -> bool:
    key = f"handoff:sla:{session_id}"
    r = _redis_client()
    if r:
        try:
            return bool(r.set(key, "1", nx=True, ex=ttl_seconds))
        except Exception:
            pass
    with _local_mutex:
        if session_id in _local_locks:
            return False
        _local_locks.add(session_id)
    return True


def release_sla_lock(session_id: str) -> None:
    key = f"handoff:sla:{session_id}"
    r = _redis_client()
    if r:
        try:
            r.delete(key)
            return
        except Exception:
            pass
    with _local_mutex:
        _local_locks.discard(session_id)
