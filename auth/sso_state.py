# -*- coding: utf-8 -*-
"""SSO OAuth state — Redis 优先，进程内回退（单实例开发）"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, Optional

_lock = threading.RLock()
_local_states: Dict[str, Dict[str, Any]] = {}
_STATE_TTL = 600


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


def _purge_local_expired() -> None:
    now = time.time()
    expired = [k for k, v in _local_states.items() if now - float(v.get("ts", 0)) > _STATE_TTL]
    for k in expired:
        _local_states.pop(k, None)


def save_state(state: str, payload: Dict[str, Any]) -> None:
    payload = {**payload, "ts": time.time()}
    r = _redis_client()
    if r:
        try:
            r.setex(f"mitako:sso:state:{state}", _STATE_TTL, json.dumps(payload, ensure_ascii=False))
            return
        except Exception:
            pass
    with _lock:
        _purge_local_expired()
        _local_states[state] = payload


def pop_state(state: str) -> Optional[Dict[str, Any]]:
    r = _redis_client()
    if r:
        try:
            key = f"mitako:sso:state:{state}"
            raw = r.get(key)
            if raw:
                r.delete(key)
                return json.loads(raw)
        except Exception:
            pass
    with _lock:
        _purge_local_expired()
        return _local_states.pop(state, None)
