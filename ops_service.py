# -*- coding: utf-8 -*-
"""7×24 运维快照 — 客户可见业务化状态"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

import admin_service
from auth.jwt_utils import auth_required
from handoff_ws import hub

_START_TS = time.time()
_ROOT = Path(__file__).resolve().parent
_VISUAL_REPORT_DIR = _ROOT / "poc" / "visual_review_poc" / "reports"
_PUBLIC_SUMMARY_DIR = _VISUAL_REPORT_DIR / "public_summaries"
_PUBLIC_FORBIDDEN_KEYS = {
    "model",
    "model_key",
    "model_name",
    "provider",
    "channel",
    "usage",
    "cost",
    "raw_response",
    "raw_text",
    "system_prompt",
    "user_prompt",
    "thoughtSignature",
    "thoughtsTokenCount",
}


def _check_redis() -> Dict[str, Any]:
    host = os.getenv("REDIS_HOST", "").strip()
    if not host:
        return {"ok": False, "status": "未启用"}
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
        return {"ok": True, "status": "正常", "latency_level": "正常" if int((time.time() - t0) * 1000) < 500 else "需关注"}
    except Exception:
        return {"ok": False, "status": "需关注"}


def _check_celery() -> Dict[str, Any]:
    mode = os.getenv("SLA_WORKER_MODE", "inline")
    if mode != "celery":
        return {"ok": True, "status": "正常"}
    try:
        from sla_worker.celery_app import celery_app

        insp = celery_app.control.inspect(timeout=2.0)
        active = insp.active() or {}
        workers = len(active)
        return {"ok": workers > 0, "status": "正常" if workers > 0 else "需关注"}
    except Exception:
        return {"ok": False, "status": "需关注"}


def _public_integration_status(raw: Dict[str, Any]) -> Dict[str, Any]:
    ok = bool(raw.get("ok"))
    if raw.get("mode") == "disabled":
        return {"ok": True, "status": "待接入"}
    return {"ok": ok, "status": "正常" if ok else "需关注"}


def _contains_forbidden_public_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key) in _PUBLIC_FORBIDDEN_KEYS or _contains_forbidden_public_key(item):
                return True
    if isinstance(value, list):
        return any(_contains_forbidden_public_key(item) for item in value)
    return False


def _public_report_safety() -> Dict[str, Any]:
    files = sorted(_PUBLIC_SUMMARY_DIR.glob("*.json")) if _PUBLIC_SUMMARY_DIR.exists() else []
    unsafe = 0
    for path in files:
        try:
            if _contains_forbidden_public_key(json.loads(path.read_text(encoding="utf-8"))):
                unsafe += 1
        except Exception:
            unsafe += 1
    return {
        "ok": unsafe == 0,
        "status": "正常" if unsafe == 0 else "需关注",
        "checked_files": len(files),
        "unsafe_files": unsafe,
    }


def _visual_review_metrics() -> Dict[str, Any]:
    reports = sorted(_VISUAL_REPORT_DIR.glob("visual_model_selection_e2e_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not reports:
        return {
            "ok": True,
            "status": "待接入",
            "source": "未发现模型选型报告",
            "total_reviews": 0,
            "success_rate": None,
            "structured_success_rate": None,
            "avg_latency_seconds": None,
            "scenario_coverage": [],
        }
    latest = reports[0]
    try:
        data = json.loads(latest.read_text(encoding="utf-8"))
    except Exception:
        return {"ok": False, "status": "需关注", "source": latest.name, "error": "report_unreadable"}
    items = data.get("results") or []
    total = len(items)
    successes = 0
    structured = 0
    latencies = []
    attempts = []
    scenarios = set()
    for item in items:
        scenarios.add(item.get("scenario") or "")
        result = item.get("result") or {}
        if result.get("status") == "success":
            successes += 1
        if result.get("parsed"):
            structured += 1
        if result.get("latency_seconds") is not None:
            latencies.append(float(result.get("latency_seconds") or 0))
        if result.get("attempt") is not None:
            attempts.append(int(result.get("attempt") or 1))
    success_rate = round(successes / total, 3) if total else None
    structured_rate = round(structured / total, 3) if total else None
    return {
        "ok": bool(total) and success_rate is not None and success_rate >= 0.8,
        "status": "正常" if total and success_rate is not None and success_rate >= 0.8 else "需关注",
        "source": latest.name,
        "total_reviews": total,
        "successful_reviews": successes,
        "success_rate": success_rate,
        "structured_success_rate": structured_rate,
        "avg_latency_seconds": round(sum(latencies) / len(latencies), 2) if latencies else None,
        "retry_rate": round(sum(1 for item in attempts if item > 1) / len(attempts), 3) if attempts else None,
        "scenario_coverage": sorted(s for s in scenarios if s),
    }


async def ops_snapshot(tenant_id: Optional[str] = None) -> Dict[str, Any]:
    from handoff_backend import chatwoot_client

    snap = admin_service.queue_snapshot(tenant_id=tenant_id)
    cw = await chatwoot_client.health_check()
    longest_wait = int(snap.get("longest_wait_seconds") or 0)
    sla_alert_count = len(snap.get("sla_alerts") or [])
    dependency_risk = cw.get("mode") not in {"disabled", "mock"} and not cw.get("ok")
    status = "healthy"
    if snap.get("queuing", 0) >= 50 or longest_wait >= 900 or sla_alert_count:
        status = "degraded"
    if dependency_risk:
        status = "degraded"
    visual_review = _visual_review_metrics()
    public_report_safety = _public_report_safety()
    if visual_review.get("status") == "需关注" or not public_report_safety.get("ok"):
        status = "degraded"
    return {
        "generated_at": time.time(),
        "uptime_seconds": int(time.time() - _START_TS),
        "auth_required": auth_required(),
        "service_timeliness": {
            "ok": not sla_alert_count and longest_wait < 900,
            "status": "正常" if not sla_alert_count and longest_wait < 900 else "需关注",
            "longest_wait_seconds": longest_wait,
            "avg_wait_seconds": int(snap.get("avg_wait_seconds") or 0),
        },
        "message_sync": _public_integration_status(cw),
        "message_sync_mode": cw.get("mode") or "unknown",
        "message_sync_latency_ms": cw.get("latency_ms"),
        "handoff_queuing": snap.get("queuing", 0),
        "handoff_connected": snap.get("connected", 0),
        "handoff_escalated": snap.get("escalated", 0),
        "handoff_transferring": snap.get("transferring", 0),
        "sla_alerts": len(snap.get("sla_alerts") or []),
        "ws_connections": hub.connection_count(),
        "cache_service": _check_redis(),
        "task_service": _check_celery(),
        "visual_review": visual_review,
        "model_calls": {
            "status": visual_review.get("status"),
            "total_reviews": visual_review.get("total_reviews"),
            "success_rate": visual_review.get("success_rate"),
            "structured_success_rate": visual_review.get("structured_success_rate"),
            "avg_latency_seconds": visual_review.get("avg_latency_seconds"),
            "retry_rate": visual_review.get("retry_rate"),
        },
        "visual_queue": {
            "status": "待接入",
            "pending": 0,
            "processing": 0,
            "retryable_failed": 0,
            "manual_reviewing": 0,
        },
        "public_report_safety": public_report_safety,
        "status": status,
    }
