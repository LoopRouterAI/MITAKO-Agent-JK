# -*- coding: utf-8 -*-
"""管理员后台业务编排"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import admin_store
import handoff_store as store
from handoff_service import (
    enqueue_handoff,
    transfer_to_colleague,
    _get_entry,
    _save,
    build_desk_brief,
    build_public_message,
    internal_event_type,
    public_business_events,
)
from handoff_routing import get_sla_config


def list_agents_public(tenant_id: Optional[str] = None) -> List[Dict[str, str]]:
    return [
        {k: a[k] for k in ("agent_id", "name", "title", "tier", "team", "skills") if k in a}
        for a in admin_store.list_agents(enabled_only=True, tenant_id=tenant_id)
    ]


def queue_snapshot(tenant_id: Optional[str] = None) -> Dict[str, Any]:
    sessions = store.list_active_sessions(tenant_id=tenant_id)
    sla = get_sla_config(tenant_id=tenant_id)
    now = time.time()
    first_sec = int(sla.get("first_response_seconds") or 180)
    queuing = connected = escalated = 0
    sla_alerts: List[Dict[str, Any]] = []
    wait_values: List[int] = []
    for index, s in enumerate(sessions, start=1):
        st = s.get("status")
        enqueued_at = s.get("enqueued_at") or s.get("created_at") or s.get("updated_at") or now
        wait_seconds = max(0, int(now - enqueued_at))
        s["wait_seconds"] = wait_seconds
        s["position"] = index
        s["ahead"] = max(0, index - 1)
        s["eta_minutes"] = max(1, int((s["ahead"] * 45 + 59) / 60))
        if st in {"queuing", "transferring", "escalated"}:
            wait_values.append(wait_seconds)
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
    avg_wait = int(sum(wait_values) / len(wait_values)) if wait_values else 0
    longest_wait = max(wait_values) if wait_values else 0
    return {
        "queuing": queuing,
        "connected": connected,
        "escalated": escalated,
        "transferring": len([s for s in sessions if s.get("status") == "transferring"]),
        "avg_wait_seconds": avg_wait,
        "longest_wait_seconds": longest_wait,
        "sla_alerts": sla_alerts,
        "sessions": sessions,
    }


def manual_reassign(session_id: str, to_agent_id: str, note: str = "", from_admin: str = "", tenant_id: Optional[str] = None) -> Dict[str, Any]:
    agent = admin_store.get_agent(to_agent_id, tenant_id=tenant_id)
    if not agent or not agent.get("enabled"):
        return {"ok": False, "error": "agent_not_found", "message": "请选择可接单的目标客服"}
    entry = _get_entry(session_id)
    if not entry:
        return {"ok": False, "error": "session_not_found", "message": "该会话已不存在，请刷新队列"}
    if tenant_id and (entry.get("tenant_id") or "mitako") != tenant_id:
        return {"ok": False, "error": "tenant_forbidden", "message": "不能转派其他租户的会话"}
    if entry.get("required_tier") == "supervisor" and agent.get("tier") != "supervisor":
        return {"ok": False, "error": "tier_mismatch", "message": "该会话需要高级客服或专项客服接管"}
    from_id = (entry.get("assigned_agent") or {}).get("agent_id", "")
    if entry.get("status") == "connected" and from_id:
        result = transfer_to_colleague(session_id, from_id, to_agent_id, note or f"管理员 {from_admin} 强制转交", tenant_id=tenant_id)
        if not result.get("ok"):
            return {**result, "message": result.get("message") or "转派失败，请刷新后重试"}
        return {"ok": True, "status": "transferring", "message": "已发起转派，等待目标客服确认接管"}
    entry["status"] = "transferring"
    entry["pending_agent"] = agent
    _save(entry)
    store.append_transfer_event(session_id, "manual_reassign", from_id, to_agent_id, note or from_admin)
    return {"ok": True, "status": entry["status"], "pending_agent": agent, "message": "已锁定该会话，等待目标客服接管"}


DEMO_SESSION_PREFIX = "demo_poc_"
LEGACY_POC_SESSION_PREFIXES = ("ent_cw_", "lab_cw_")
LEGACY_POC_SUMMARIES = {"chatwoot sync test", "partner lab handoff"}


def _is_demo_or_legacy_poc_session(session: Dict[str, Any]) -> bool:
    sid = str(session.get("session_id") or "")
    if sid.startswith(DEMO_SESSION_PREFIX) or sid.startswith(LEGACY_POC_SESSION_PREFIXES):
        return True
    brief = session.get("brief") or {}
    summary = str(brief.get("summary") or "").strip().lower()
    return summary in LEGACY_POC_SUMMARIES


def _clear_demo_visible_sessions(tid: str) -> int:
    session_ids: List[str] = []
    removed = 0
    for session in store.list_all_sessions(limit=1000, tenant_id=tid):
        if _is_demo_or_legacy_poc_session(session):
            sid = str(session.get("session_id"))
            session_ids.append(sid)
            store.delete_session(sid, tenant_id=tid)
            removed += 1
    if session_ids:
        admin_store.delete_approvals_for_sessions(session_ids, tenant_id=tid)
    return removed


def demo_status(tenant_id: Optional[str] = None) -> Dict[str, Any]:
    sessions = [
        s for s in store.list_all_sessions(limit=200, tenant_id=tenant_id)
        if str(s.get("session_id") or "").startswith(DEMO_SESSION_PREFIX)
    ]
    loaded_at = max([s.get("created_at") or 0 for s in sessions], default=0)
    return {
        "ok": True,
        "mode": "demo" if sessions else "empty",
        "loaded_at": loaded_at,
        "session_count": len(sessions),
        "scope": ["坐席", "转VIP客服队列", "服务记录", "报表指标"],
        "message": "当前展示演示数据，未连接甲方生产接口。" if sessions else "当前没有演示会话，可点击加载演示数据预览完整流程。",
    }


def load_demo_data(tenant_id: Optional[str] = None) -> Dict[str, Any]:
    tid = tenant_id or "mitako"
    demo_tid = "".join(ch if ch.isalnum() else "_" for ch in tid.lower())[:24] or "mitako"
    now = time.time()
    removed = _clear_demo_visible_sessions(tid)
    samples = [
        {
            "session_id": f"{DEMO_SESSION_PREFIX}{demo_tid}_shipping_delay",
            "user_id": "demo_user_shipping",
            "summary": "用户催促发货，担心仓库和清关太慢，情绪偏急。",
            "intent": "物流进度咨询",
            "true_intent": "希望客服说明发货、仓库、清关节点，并给出下一次更新时间。",
            "emotion_level": 4,
            "recommended_actions": ["先同步订单和物流节点", "解释清关预计时效", "承诺下一次跟进时间"],
            "orders": ["PT-DEMO-1001 / 盲盒挂件 / 待清关"],
        },
        {
            "session_id": f"{DEMO_SESSION_PREFIX}{demo_tid}_damage_claim",
            "user_id": "demo_user_damage",
            "summary": "用户反馈商品有伤，已上传图片，要求补发或退款。",
            "intent": "商品有伤售后",
            "true_intent": "需要判断图片证据是否支持售后，并安抚用户等待复核。",
            "emotion_level": 5,
            "required_tier": "supervisor",
            "recommended_actions": ["发起商品有伤视觉审核", "核对订单 SKU 和售后政策", "高风险措辞交由高级客服处理"],
            "orders": ["PT-DEMO-1002 / 手办摆件 / 已签收"],
        },
        {
            "session_id": f"{DEMO_SESSION_PREFIX}{demo_tid}_minor_refund",
            "user_id": "demo_user_minor",
            "summary": "家长反馈未成年人购买，要求客服协助退款。",
            "intent": "未成年人退款资料审核",
            "true_intent": "需要核对监护关系、购买记录和平台退款规则，避免自动承诺。",
            "emotion_level": 4,
            "required_tier": "supervisor",
            "recommended_actions": ["提示补充监护资料", "发起未成年人资料审核", "由高级客服确认退款边界"],
            "orders": ["PT-DEMO-1003 / 潮玩盲盒 / 已完成"],
        },
    ]
    for idx, sample in enumerate(samples):
        brief = {
            "user_id": sample["user_id"],
            "tenant_id": tid,
            "summary": sample["summary"],
            "intent": sample["intent"],
            "true_intent": sample["true_intent"],
            "emotion_level": sample["emotion_level"],
            "required_tier": sample.get("required_tier", "standard"),
            "recommended_actions": sample["recommended_actions"],
            "orders": sample["orders"],
            "conversation_snippet": [
                {"role": "user", "turn": 1, "content": sample["summary"]},
                {"role": "assistant", "turn": 2, "content": "我先帮您整理重点并转接VIP客服继续处理。"},
            ],
            "sop_state": {
                "sop_branch": sample["intent"],
                "checklist": [
                    {"label": "核对订单与用户诉求", "status": "matched", "note": "演示数据已提供基础订单线索"},
                    {"label": "判断是否需要视觉审核", "status": "ready_for_human_review", "note": "由客服确认后发起审核"},
                ],
            },
        }
        enqueue_handoff(sample["session_id"], brief, tenant_id=tid)
        entry = store.get_session(sample["session_id"])
        if entry:
            entry["required_tier"] = sample.get("required_tier", "standard")
            entry["enqueued_at"] = now - (idx + 2) * 180
            store.upsert_session(entry)
        store.append_message(sample["session_id"], "user", sample["summary"], meta={"demo": True})
        store.append_transfer_event(sample["session_id"], "demo_seed", "", "", "后台加载演示数据")
    return {
        **demo_status(tenant_id=tid),
        "ok": True,
        "removed": removed,
        "message": "演示数据已加载，历史联调数据已收起，可在队列和报表中预览完整流程。",
    }


def clear_demo_data(tenant_id: Optional[str] = None) -> Dict[str, Any]:
    tid = tenant_id or "mitako"
    removed = _clear_demo_visible_sessions(tid)
    return {"ok": True, "mode": "empty", "removed": removed, "message": "演示和历史联调数据已清空，真实接口数据未受影响。"}


def list_audit_events(
    *,
    session_id: str = "",
    event_type: str = "",
    tenant_id: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    if session_id:
        entry = _get_entry(session_id)
        if tenant_id and (not entry or (entry.get("tenant_id") or "mitako") != tenant_id):
            return []
        events = store.get_transfer_events(session_id)
    else:
        events = store.list_all_transfer_events(limit=limit, tenant_id=tenant_id)
    for e in events:
        e["audit_source"] = "handoff"
    business_filter = internal_event_type(event_type) if event_type else ""
    business = public_business_events(
        store.list_business_events(session_id=session_id, event_type=business_filter, tenant_id=tenant_id or "", limit=limit)
    )
    for e in business:
        e["audit_source"] = "business"
    if event_type:
        events = [e for e in events if e.get("event_type") == event_type]
    merged = events + business
    merged.sort(key=lambda e: e.get("created_at") or 0, reverse=True)
    return merged[:limit]


def session_transcript(session_id: str, tenant_id: Optional[str] = None) -> Dict[str, Any]:
    entry = _get_entry(session_id)
    if not entry:
        return {"ok": False, "error": "session_not_found"}
    if tenant_id and (entry.get("tenant_id") or "mitako") != tenant_id:
        return {"ok": False, "error": "tenant_forbidden"}
    messages = [build_public_message(m) for m in store.get_messages_since(session_id, 0)]
    events = store.get_transfer_events(session_id)
    business_events = public_business_events(store.list_business_events(session_id=session_id, tenant_id=tenant_id or "", limit=200))
    session = {
        "session_id": entry.get("session_id"),
        "status": entry.get("status"),
        "user_id": entry.get("user_id"),
        "tenant_id": entry.get("tenant_id"),
        "required_tier": entry.get("required_tier"),
        "brief": build_desk_brief(entry.get("brief")),
        "assigned_agent": entry.get("assigned_agent"),
        "pending_agent": entry.get("pending_agent"),
        "suggested_agent": entry.get("suggested_agent"),
        "accepted_at": entry.get("accepted_at"),
        "accepted_by": entry.get("accepted_by"),
        "created_at": entry.get("created_at"),
        "updated_at": entry.get("updated_at"),
    }
    return {"ok": True, "session": session, "messages": messages, "events": events, "business_events": business_events}


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
    entry = store.get_session(session_id)
    if not entry or (entry.get("tenant_id") or "mitako") != (tenant_id or "mitako"):
        return {"ok": False, "error": "session_not_found", "message": "请先选择一个当前租户下存在的服务单"}
    session_user = entry.get("user_id") or (entry.get("brief") or {}).get("user_id") or ""
    if user_id and session_user and user_id != session_user:
        return {"ok": False, "error": "user_mismatch", "message": "客户编号与服务单不一致"}
    brief = entry.get("brief") or {}
    business_events = store.list_business_events(session_id=session_id, tenant_id=tenant_id or "mitako", limit=5)
    service_context_ready = bool(
        business_events
        or brief.get("business_cards")
        or brief.get("orders")
        or (brief.get("sop_state") or {}).get("order_id")
    )
    if not service_context_ready:
        return {
            "ok": False,
            "error": "service_context_required",
            "message": "补偿申请必须关联已进入服务流程的工单、订单或业务审计记录",
        }
    row = admin_store.create_approval({
        "session_id": session_id,
        "user_id": user_id or session_user,
        "amount": amount,
        "reason": reason,
        "requester": requester,
        "tenant_id": tenant_id,
    })
    return {"ok": True, "approval": row}


def list_compensation_approvals(status: str = "", tenant_id: Optional[str] = None) -> Dict[str, Any]:
    return {"ok": True, "approvals": admin_store.list_approvals(status=status, tenant_id=tenant_id)}


def decide_compensation_approval(approval_id: int, decision: str, approver: str, tenant_id: Optional[str] = None) -> Dict[str, Any]:
    pending = admin_store.get_approval(approval_id, tenant_id=tenant_id)
    if not pending:
        return {"ok": False, "error": "not_found_or_done"}
    if pending and pending.get("requester") == approver:
        return {"ok": False, "error": "approver_must_differ_from_requester"}
    row = admin_store.decide_approval(approval_id, decision, approver, tenant_id=tenant_id)
    if not row:
        return {"ok": False, "error": "not_found_or_done"}
    return {"ok": True, "approval": row}


def reports_summary(days: int = 7, tenant_id: Optional[str] = None) -> Dict[str, Any]:
    now = time.time()
    since = now - max(1, days) * 86400
    recent = store.list_all_sessions(limit=500, since=since, tenant_id=tenant_id)
    events = store.list_all_transfer_events(limit=500, tenant_id=tenant_id)
    recent_events = [e for e in events if (e.get("created_at") or 0) >= since]
    business_events = [
        e for e in store.list_business_events(tenant_id=tenant_id or "", limit=500)
        if (e.get("created_at") or 0) >= since
    ]
    approvals = admin_store.list_approvals(status="", tenant_id=tenant_id)
    recent_approvals = [a for a in approvals if (a.get("created_at") or 0) >= since]
    queue = queue_snapshot(tenant_id=tenant_id)
    by_type: Dict[str, int] = {}
    for e in recent_events:
        et = e.get("event_type") or "unknown"
        by_type[et] = by_type.get(et, 0) + 1
    statuses: Dict[str, int] = {}
    for s in recent:
        st = s.get("status") or "unknown"
        statuses[st] = statuses.get(st, 0) + 1
    pending_approvals = len(admin_store.list_approvals(status="pending", tenant_id=tenant_id))
    closed = statuses.get("closed", 0)
    active = sum(v for k, v in statuses.items() if k != "closed")
    total = len(recent)
    transfer_statuses = {"queuing", "connected", "transferring", "escalated", "closed"}
    transfer_sessions = len([s for s in recent if s.get("status") in transfer_statuses])
    approval_done = len([a for a in recent_approvals if a.get("status") in {"approved", "rejected"}])
    approval_passed = len([a for a in recent_approvals if a.get("status") == "approved"])
    return {
        "period_days": days,
        "total_sessions": total,
        "closed_sessions": closed,
        "active_sessions": active,
        "agent_sessions": max(0, total - transfer_sessions),
        "human_sessions": transfer_sessions,
        "handoff_rate": round(transfer_sessions / total, 3) if total else 0,
        "close_rate": round(closed / total, 3) if total else 0,
        "status_breakdown": statuses,
        "transfer_events": len(recent_events),
        "transfer_by_type": by_type,
        "business_events": len(business_events),
        "approval_requests": len(recent_approvals),
        "approval_done": approval_done,
        "approval_pass_rate": round(approval_passed / approval_done, 3) if approval_done else 0,
        "pending_approvals": pending_approvals,
        "queue": {
            "queuing": queue.get("queuing", 0),
            "connected": queue.get("connected", 0),
            "escalated": queue.get("escalated", 0),
            "transferring": queue.get("transferring", 0),
            "avg_wait_seconds": queue.get("avg_wait_seconds", 0),
            "longest_wait_seconds": queue.get("longest_wait_seconds", 0),
            "sla_alerts": len(queue.get("sla_alerts") or []),
        },
        "generated_at": now,
    }


def reports_csv_rows(days: int = 7, tenant_id: Optional[str] = None) -> str:
    summary = reports_summary(days, tenant_id=tenant_id)
    lines = [
        "metric,value",
        f"period_days,{summary['period_days']}",
        f"total_sessions,{summary['total_sessions']}",
        f"closed_sessions,{summary['closed_sessions']}",
        f"human_sessions,{summary['human_sessions']}",
        f"handoff_rate,{summary['handoff_rate']}",
        f"transfer_events,{summary['transfer_events']}",
        f"business_events,{summary['business_events']}",
        f"pending_approvals,{summary['pending_approvals']}",
    ]
    for k, v in (summary.get("status_breakdown") or {}).items():
        lines.append(f"status_{k},{v}")
    for k, v in (summary.get("transfer_by_type") or {}).items():
        lines.append(f"event_{k},{v}")
    return "\n".join(lines) + "\n"
