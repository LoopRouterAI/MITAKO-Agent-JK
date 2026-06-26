# -*- coding: utf-8 -*-
"""7×24 运维快照 — Redis / Celery / Chatwoot / 队列 / WS"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

import admin_service
from auth.jwt_utils import auth_required
from handoff_ws import hub

_START_TS = time.time()


def _check_redis() -> Dict[str, Any]:
    host = os.getenv("REDIS_HOST", "").strip()
    if not host:
        return {"ok": False, "mode": "disabled"}
    try:
        import redis

        t0 = time.time()
        r = redis.Redis(
            host=host,
            port=int(os.getenv("REDIS_PORT", "6379")),
            db=int(os.getenv("REDIS_DB", "0")),
            socket_connect_timeout=2,
        )
        r.ping()
        return {"ok": True, "mode": "live", "latency_ms": int((time.time() - t0) * 1000)}
    except Exception as e:
        return {"ok": False, "mode": "error", "error": str(e)[:80]}


def _check_celery() -> Dict[str, Any]:
    mode = os.getenv("SLA_WORKER_MODE", "inline")
    if mode != "celery":
        return {"ok": True, "mode": "inline", "workers": 0}
    try:
        from sla_worker.celery_app import celery_app

        insp = celery_app.control.inspect(timeout=2.0)
        active = insp.active() or {}
        workers = len(active)
        return {"ok": workers > 0, "mode": "celery", "workers": workers}
    except Exception as e:
        return {"ok": False, "mode": "celery", "error": str(e)[:80]}


async def ops_snapshot(tenant_id: Optional[str] = None) -> Dict[str, Any]:
    from handoff_backend import chatwoot_client

    snap = admin_service.queue_snapshot(tenant_id=tenant_id)
    cw = await chatwoot_client.health_check()
    return {
        "generated_at": time.time(),
        "uptime_seconds": int(time.time() - _START_TS),
        "auth_required": auth_required(),
        "sla_worker_mode": os.getenv("SLA_WORKER_MODE", "inline"),
        "handoff_backend": os.getenv("HANDOFF_BACKEND", "sqlite"),
        "handoff_queuing": snap.get("queuing", 0),
        "handoff_connected": snap.get("connected", 0),
        "handoff_escalated": snap.get("escalated", 0),
        "sla_alerts": len(snap.get("sla_alerts") or []),
        "ws_connections": hub.connection_count(),
        "redis": _check_redis(),
        "celery": _check_celery(),
        "chatwoot": cw,
        "status": "healthy" if snap.get("queuing", 0) < 50 else "degraded",
    }
