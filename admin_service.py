# -*- coding: utf-8 -*-
"""管理员后台业务编排"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import admin_store
import handoff_store as store
from handoff_service import transfer_to_colleague, _get_entry, _save
from handoff_routing import get_sla_config


def list_agents_public(tenant_id: Optional[str] = None) -> List[Dict[str, str]]:
    return [
        {k: a[k] for k in ("agent_id", "name", "title", "tier", "team", "skills") if k in a}
        for a in admin_store.list_agents(enabled_only=True, tenant_id=tenant_id)
    ]


def queue_snapshot(tenant_id: Optional[str] = None) -> Dict[str, Any]:
    sessions = store.list_active_sessions(tenant_id=tenant_id)
    sla = get_sla_config()
    now = time.time()
    first_sec = int(sla.get("first_response_seconds") or 180)
    queuing = connected = escalated = 0
    sla_alerts: List[Dict[str, Any]] = []
    for s in sessions:
        st = s.get("status")
        if st == "queuing":
            queuing += 1
        elif st == "connected":
            connected += 1
        elif st == "escalated":
            escalated += 1
        if st != "connected":
            continue
        accepted = s.get("accepted_at") or 0
        last_agent = s.get("last_agent_reply_at")
        if accepted and not last_agent and (now - accepted) > first_sec:
            sla_alerts.append({**s, "sla_reason": "first_response", "wait_seconds": int(now - accepted)})
    return {
        "queuing": queuing,
        "connected": connected,
        "escalated": escalated,
        "sla_alerts": sla_alerts,
        "sessions": sessions,
    }


def manual_reassign(session_id: str, to_agent_id: str, note: str = "", from_admin: str = "", tenant_id: Optional[str] = None) -> Dict[str, Any]:
    agent = admin_store.get_agent(to_agent_id, tenant_id=tenant_id)
    if not agent or not agent.get("enabled"):
        return {"ok": False, "error": "agent_not_found"}
    entry = _get_entry(session_id)
    if not entry:
        return {"ok": False, "error": "session_not_found"}
    if tenant_id and (entry.get("tenant_id") or "mitako") != tenant_id:
        return {"ok": False, "error": "tenant_forbidden"}
    from_id = (entry.get("assigned_agent") or {}).get("agent_id", "")
    if entry.get("status") == "connected" and from_id:
        transfer_to_colleague(session_id, from_id, to_agent_id, note or f"管理员 {from_admin} 强制转交")
        return {"ok": True, "status": "transferring"}
    entry["status"] = "transferring" if entry.get("status") == "connected" else entry.get("status", "queuing")
    entry["pending_agent"] = agent
    _save(entry)
    store.append_transfer_event(session_id, "manual_reassign", from_id, to_agent_id, note or from_admin)
    return {"ok": True, "status": entry["status"], "pending_agent": agent}


def list_audit_events(
    *,
    session_id: str = "",
    event_type: str = "",
    limit: int = 100,
) -> List[Dict[str, Any]]:
    if session_id:
        events = store.get_transfer_events(session_id)
    else:
        events = store.list_all_transfer_events(limit=limit)
    if event_type:
        events = [e for e in events if e.get("event_type") == event_type]
    return events[:limit]


def session_transcript(session_id: str) -> Dict[str, Any]:
    entry = _get_entry(session_id)
    if not entry:
        return {"ok": False, "error": "session_not_found"}
    messages = store.get_messages_since(session_id, 0)
    events = store.get_transfer_events(session_id)
    return {"ok": True, "session": entry, "messages": messages, "events": events}


def create_compensation_approval(
    *,
    session_id: str,
    user_id: str,
    amount: float,
    reason: str,
    requester: str,
    tenant_id: str = "mitako",
) -> Dict[str, Any]:
    if amount <= 0:
        return {"ok": False, "error": "invalid_amount"}
    row = admin_store.create_approval({
        "session_id": session_id,
        "user_id": user_id,
        "amount": amount,
        "reason": reason,
        "requester": requester,
        "tenant_id": tenant_id,
    })
    return {"ok": True, "approval": row}


def list_compensation_approvals(status: str = "", tenant_id: Optional[str] = None) -> Dict[str, Any]:
    return {"ok": True, "approvals": admin_store.list_approvals(status=status, tenant_id=tenant_id)}


def decide_compensation_approval(approval_id: int, decision: str, approver: str, tenant_id: Optional[str] = None) -> Dict[str, Any]:
    pending = admin_store.get_approval(approval_id)
    if not pending:
        return {"ok": False, "error": "not_found_or_done"}
    if tenant_id and pending.get("tenant_id") != tenant_id:
        return {"ok": False, "error": "tenant_forbidden"}
    if pending and pending.get("requester") == approver:
        return {"ok": False, "error": "approver_must_differ_from_requester"}
    row = admin_store.decide_approval(approval_id, decision, approver)
    if not row:
        return {"ok": False, "error": "not_found_or_done"}
    return {"ok": True, "approval": row}


def reports_summary(days: int = 7, tenant_id: Optional[str] = None) -> Dict[str, Any]:
    now = time.time()
    since = now - max(1, days) * 86400
    recent = store.list_all_sessions(limit=500, since=since, tenant_id=tenant_id)
    events = store.list_all_transfer_events(limit=500)
    recent_events = [e for e in events if (e.get("created_at") or 0) >= since]
    by_type: Dict[str, int] = {}
    for e in recent_events:
        et = e.get("event_type") or "unknown"
        by_type[et] = by_type.get(et, 0) + 1
    statuses: Dict[str, int] = {}
    for s in recent:
        st = s.get("status") or "unknown"
        statuses[st] = statuses.get(st, 0) + 1
    pending_approvals = len(admin_store.list_approvals(status="pending", tenant_id=tenant_id))
    return {
        "period_days": days,
        "total_sessions": len(recent),
        "status_breakdown": statuses,
        "transfer_events": len(recent_events),
        "transfer_by_type": by_type,
        "pending_approvals": pending_approvals,
        "generated_at": now,
    }


def reports_csv_rows(days: int = 7, tenant_id: Optional[str] = None) -> str:
    summary = reports_summary(days, tenant_id=tenant_id)
    lines = [
        "metric,value",
        f"period_days,{summary['period_days']}",
        f"total_sessions,{summary['total_sessions']}",
        f"transfer_events,{summary['transfer_events']}",
        f"pending_approvals,{summary['pending_approvals']}",
    ]
    for k, v in (summary.get("status_breakdown") or {}).items():
        lines.append(f"status_{k},{v}")
    for k, v in (summary.get("transfer_by_type") or {}).items():
        lines.append(f"event_{k},{v}")
    return "\n".join(lines) + "\n"
