# -*- coding: utf-8 -*-
"""转人工排队与移交简报 — SQLite 持久化 + 可配置路由"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import handoff_store as store
from handoff_routing import load_routing_config, resolve_required_tier, save_routing_config
from handoff_observer import generate_observer_reply, is_observer_request
from handoff_ws import emit_session_event

try:
    import admin_store as _admin_store
except ImportError:
    _admin_store = None  # type: ignore

_DEMO_AGENTS: List[Dict[str, str]] = [
    {"agent_id": "CS-0816", "name": "岚星", "title": "一线客服专员", "tier": "standard", "team": "外包A组·华东", "skills": ["物流", "安抚"]},
    {"agent_id": "CS-0922", "name": "晓棠", "title": "一线客服专员", "tier": "standard", "team": "外包B组·华南", "skills": ["盲盒", "换货"]},
    {"agent_id": "CS-1024", "name": "阿禾", "title": "总部客诉主管", "tier": "supervisor", "team": "甲方官方·客诉中心", "skills": ["投诉", "退款授权"]},
    {"agent_id": "CS-1203", "name": "沐澄", "title": "高级安抚顾问", "tier": "supervisor", "team": "甲方官方·VIP组", "skills": ["VIP", "舆情"]},
]

_EMOTION_KEYWORDS: Dict[int, List[str]] = {
    5: ["起诉", "投诉", "黑猫", "律师", "举报", "骗子", "垃圾", "曝光", "消协"],
    4: ["愤怒", "不满", "凭什么", "太过分", "退现金", "欺骗", "忽悠"],
    3: ["着急", "多久", "还没", "延期", "催", "等不了", "什么时候"],
}

_INTENT_TRUE_MAP: Dict[str, str] = {
    "退款/退货": "核心诉求为退款或现金补偿，需核实订单状态与补偿政策边界",
    "物流查询": "真实意图是确认物流节点与预计到货，需优先给明确时间节点",
    "投诉": "真实意图为情绪宣泄与权益主张，需先承接情绪再谈方案",
    "greeting": "当前为寒暄或试探性进线，需引导至具体订单或诉求",
    "闲聊互动": "尚未形成明确售后诉求，需通过开放式提问锁定问题",
}


def _detect_emotion_triggers(messages: List[Dict[str, str]], emotion_level: int) -> List[Dict[str, Any]]:
    triggers: List[Dict[str, Any]] = []
    keywords: List[str] = []
    for level in range(5, max(2, emotion_level) - 1, -1):
        keywords.extend(_EMOTION_KEYWORDS.get(level, []))
    user_turn = 0
    seen_kw: set = set()
    for msg in messages:
        if msg.get("role") != "user":
            continue
        user_turn += 1
        content = msg.get("content") or ""
        for kw in keywords:
            if kw in content and kw not in seen_kw:
                seen_kw.add(kw)
                triggers.append({"keyword": kw, "turn": user_turn, "excerpt": content[:160]})
    return triggers


def _infer_true_intent(intent: str, user_msgs: List[str], orders: List[str]) -> str:
    base = _INTENT_TRUE_MAP.get(intent, f"表面意图为「{intent}」，需结合订单与对话进一步确认真实诉求")
    if any("退款" in m or "退现金" in m or "赔偿" in m for m in user_msgs):
        return "真实意图偏向退款/现金补偿，情绪背后是对处理进度与方案力度的不满"
    if orders and any("pending" in o or "refund" in o for o in orders):
        return f"{base}；关联订单存在在途/售后状态，用户更关注结果而非流程说明"
    return base


def _build_ai_dialogue_summary(messages: List[Dict[str, str]]) -> str:
    user_msgs = [m.get("content", "") for m in messages if m.get("role") == "user"]
    ai_msgs = [m.get("content", "") for m in messages if m.get("role") == "assistant"]
    if not ai_msgs:
        return "AI 尚未形成有效回复，用户诉求待人工首响承接。"
    points = [
        f"用户共 {len(user_msgs)} 轮发言，核心关注：{(user_msgs[-1][:100] if user_msgs else '—')}",
        f"AI 已回复 {len(ai_msgs)} 条，末条要点：{ai_msgs[-1][:120]}",
    ]
    if len(user_msgs) >= 3:
        points.append("多轮来回后用户仍未满意，说明话术/方案力度不足，需人工升级处理。")
    return " ".join(points)


def _build_user_profile(state: Dict[str, Any], emotion: int, triggers: List[Dict[str, Any]]) -> Dict[str, Any]:
    memory = state.get("user_memory") or {}
    psych = []
    if emotion >= 5:
        psych.append("处于高对抗状态，存在外诉/舆情风险，建议主管关注但可由一线先承接")
    elif emotion >= 4:
        psych.append("情绪明显激动，对平台信任度下降，需先确认被听见再谈规则")
    elif emotion >= 3:
        psych.append("焦虑/催促为主，对时间节点敏感，厌恶模糊答复")
    else:
        psych.append("情绪相对平稳，适合事实澄清与进度同步")
    if triggers:
        psych.append(f"敏感触发词已出现 {len(triggers)} 处，对「{triggers[0]['keyword']}」类表述反应强烈")
    return {
        "nickname": memory.get("nickname") or state.get("user_id") or "未知用户",
        "member_level": memory.get("member_level") or "普通会员",
        "favorite_ips": memory.get("favorite_ips") or [],
        "psychological_analysis": "；".join(psych),
        "risk_level": "high" if emotion >= 5 else ("medium" if emotion >= 4 else "low"),
    }


def _build_recommended_actions(intent: str, emotion: int, orders: List[str], comp_note: str) -> List[str]:
    actions = []
    if emotion >= 4:
        actions.append("首响 30 秒内承接情绪，避免继续解释规则条款")
    if "退款" in intent or any("refund" in o for o in orders):
        actions.append("核对是否已有补偿记录，避免重复承诺；必要时申请主管授权加码")
    if orders:
        actions.append("优先同步最相关订单的最新物流/售后节点，给明确日期而非「尽快」")
    if emotion >= 5:
        actions.append("一线若 10 分钟内无法给出用户认可方案，可手动升级总部客诉主管")
    elif emotion >= 4:
        actions.append("可尝试免邮券/小额关怀，但避免与用户预期差距过大引发二次爆发")
    if comp_note:
        actions.append(f"注意：{comp_note}，勿重复发放同类权益")
    if not actions:
        actions.append("以确认诉求、同步进度、给出下一步时间为先")
    return actions


def _build_professional_transfer_reason(
    emotion: int, triggers: List[Dict[str, Any]], transfer_reason: str, user_turn_count: int,
) -> str:
    parts: List[str] = []
    if emotion >= 4:
        parts.append(
            f"客户在会话中多次出现高强度情绪表达（当前系统评级 Level {emotion}，共 {user_turn_count} 轮用户发言）"
        )
    elif emotion >= 3:
        parts.append(f"客户情绪升至 Level {emotion}，对处理进度表达明显不满")
    if triggers:
        kw_str = "、".join(f"「{t['keyword']}」" for t in triggers[:6])
        refs = "；".join(f"第 {t['turn']} 轮原话摘录：{t['excerpt'][:48]}…" for t in triggers[:3])
        parts.append(f"触发关键词包括 {kw_str}（{refs}）")
    if transfer_reason:
        parts.append(f"移交背景：{transfer_reason}")
    parts.append(
        "为避免事态升级为正式投诉、监管举报或外诉曝光，已由 AI 虾饺发起人工接手；"
        "请人工客服确认阅读简报后再接入会话。"
    )
    return "。".join(parts)


def build_handoff_brief(state: Dict[str, Any], reason: Optional[str] = None) -> Dict[str, Any]:
    messages: List[Dict[str, str]] = state.get("messages") or []
    user_msgs = [m.get("content", "") for m in messages if m.get("role") == "user"]
    intent = state.get("intent") or "未识别"
    emotion = int(state.get("emotion_level") or 2)
    transfer_reason = reason or state.get("transfer_reason") or "用户申请人工协助"
    if not user_msgs:
        summary = transfer_reason or "客户主动申请人工协助，暂无有效对话摘录"
    elif len(user_msgs) == 1:
        summary = user_msgs[0][:400]
    else:
        summary = f"用户共 {len(user_msgs)} 轮诉求。最新：{user_msgs[-1][:200]}"
    orders: List[str] = []
    for o in (state.get("order_data") or {}).get("orders") or []:
        oid = o.get("order_id", "?")
        status = o.get("status", "?")
        name = (o.get("items") or [{}])[0].get("name", "") if o.get("items") else ""
        label = f"{oid}({status})"
        if name:
            label = f"{label} · {name}"
        orders.append(label)
    compensation = state.get("compensation_given") or []
    comp_note = f"本次 AI 已尝试补偿 {len(compensation)} 项" if compensation else ""
    triggers = _detect_emotion_triggers(messages, emotion)
    draft_brief = {
        "summary": summary,
        "true_intent": _infer_true_intent(intent, user_msgs, orders),
        "surface_intent": intent,
        "ai_dialogue_summary": _build_ai_dialogue_summary(messages),
        "user_profile": _build_user_profile(state, emotion, triggers),
        "recommended_actions": _build_recommended_actions(intent, emotion, orders, comp_note),
        "emotion_triggers": triggers,
        "orders": orders,
        "reason": transfer_reason,
        "emotion_level": emotion,
        "intent": intent,
        "compensation_note": comp_note,
        "conversation_snippet": [
            {"role": m.get("role"), "content": (m.get("content") or "")[:300], "turn": i + 1}
            for i, m in enumerate(messages[-14:])
        ],
        "user_id": state.get("user_id"),
        "session_id": state.get("session_id"),
    }
    required_tier = resolve_required_tier(draft_brief)
    why = _build_professional_transfer_reason(emotion, triggers, transfer_reason, len(user_msgs))
    draft_brief.update({
        "why_ai_cannot_handle": why,
        "transfer_reason_professional": why,
        "required_tier": required_tier,
    })
    return draft_brief


def _agent_pool(enabled_only: bool = True) -> List[Dict[str, Any]]:
    if _admin_store:
        return _admin_store.list_agents(enabled_only=enabled_only)
    return [dict(a) for a in _DEMO_AGENTS]


def _agent_public(a: Dict[str, Any]) -> Dict[str, str]:
    return {k: a[k] for k in ("agent_id", "name", "title", "tier", "team", "skills") if k in a}


def _find_agent(agent_id: str) -> Optional[Dict[str, str]]:
    if _admin_store:
        a = _admin_store.get_agent(agent_id)
        if a:
            if not a.get("enabled", True):
                return None
            return _agent_public(a)
    for ag in _DEMO_AGENTS:
        if ag["agent_id"] == agent_id:
            return dict(ag)
    return None


def _pick_suggested_agent(session_id: str, required_tier: str) -> Dict[str, str]:
    pool = [a for a in _agent_pool() if a.get("tier") == required_tier] or _agent_pool()
    idx = sum(ord(c) for c in session_id) % max(1, len(pool))
    return _agent_public(pool[idx])


def _pick_next_agent(session_id: str, exclude_ids: Optional[List[str]] = None) -> Dict[str, str]:
    exclude = set(exclude_ids or [])
    pool = [a for a in _agent_pool() if a.get("agent_id") not in exclude and a.get("tier") == "standard"]
    if not pool:
        pool = [a for a in _agent_pool() if a.get("agent_id") not in exclude]
    idx = (sum(ord(c) for c in session_id) + int(time.time())) % max(1, len(pool))
    return _agent_public(pool[idx])


def list_demo_agents() -> List[Dict[str, str]]:
    return [_agent_public(a) for a in _agent_pool()]


def build_human_welcome(agent: Dict[str, str], brief: Optional[Dict[str, Any]] = None) -> str:
    team = agent.get("team") or "客服中心"
    tier_label = "总部主管" if agent.get("tier") == "supervisor" else "一线专员"
    return (
        f"您好，我是{team}{tier_label}{agent.get('name', '')}，工号 {agent.get('agent_id', 'CS-0000')}。"
        f"已完整阅读虾饺移交简报，接下来由我接手为您处理，您可以直接说明最新诉求～"
    )


def _emit_msg(session_id: str, msg: Dict[str, Any]) -> None:
    emit_session_event(session_id, "message", {"message": msg})


def _emit_status(session_id: str, entry: Dict[str, Any]) -> None:
    emit_session_event(session_id, "status", {
        "status": entry.get("status"),
        "assigned_agent": entry.get("assigned_agent"),
        "pending_agent": entry.get("pending_agent"),
        "required_tier": entry.get("required_tier"),
    })


def _save(entry: Dict[str, Any]) -> Dict[str, Any]:
    store.upsert_session(entry)
    return entry


def _get_entry(session_id: str) -> Optional[Dict[str, Any]]:
    return store.get_session(session_id)


def enqueue_handoff(session_id: str, brief: Dict[str, Any], tenant_id: str = "mitako") -> Dict[str, Any]:
    active = store.list_active_sessions()
    waiting = [s for s in active if s.get("status") in ("queuing", "escalated", "transferring")]
    position = len(waiting) + 1
    ahead = max(0, position - 1)
    eta = max(1, ahead * 2)
    required_tier = brief.get("required_tier") or resolve_required_tier(brief)
    brief["required_tier"] = required_tier
    tid = brief.get("tenant_id") or tenant_id or "mitako"
    brief["tenant_id"] = tid
    agent = _pick_suggested_agent(session_id, required_tier)
    now = time.time()
    entry = {
        "session_id": session_id,
        "user_id": brief.get("user_id"),
        "tenant_id": tid,
        "status": "queuing",
        "required_tier": required_tier,
        "brief": brief,
        "suggested_agent": agent,
        "assigned_agent": None,
        "pending_agent": None,
        "position": position,
        "ahead": ahead,
        "eta_minutes": eta,
        "enqueued_at": now,
        "accepted_at": None,
        "accepted_by": None,
        "escalation_note": None,
        "observer_mode": True,
    }
    _save(entry)
    _emit_status(session_id, entry)
    try:
        from im_sync_service import sync_handoff_created
        sync_handoff_created(session_id, entry)
    except Exception:
        pass
    return {
        "position": position,
        "ahead": ahead,
        "eta": eta,
        "session_id": session_id,
        "required_tier": required_tier,
        "suggested_agent": agent,
    }


def get_queue_status(session_id: str) -> Optional[Dict[str, Any]]:
    entry = _get_entry(session_id)
    if not entry:
        return None
    payload = {**entry}
    agent = entry.get("assigned_agent") or entry.get("suggested_agent") or {}
    payload["agent"] = agent
    if entry.get("status") == "connected":
        payload["welcome"] = build_human_welcome(agent, entry.get("brief"))
    return payload


def _tier_allows(entry: Dict[str, Any], agent: Dict[str, str]) -> bool:
    if entry.get("required_tier") == "supervisor" and agent.get("tier") != "supervisor":
        return False
    return True


def accept_handoff(session_id: str, agent_id: str) -> Dict[str, Any]:
    entry = _get_entry(session_id)
    if not entry:
        return {"ok": False, "error": "session_not_found"}
    status = entry.get("status")
    if status not in ("queuing", "escalated", "transferring"):
        return {"ok": False, "error": "invalid_status", "status": status}

    agent = _find_agent(agent_id)
    if not agent:
        return {"ok": False, "error": "agent_not_found"}

    pending = entry.get("pending_agent")
    if status == "transferring" and pending and pending.get("agent_id") != agent_id:
        return {"ok": False, "error": "not_pending_agent", "message": "该会话待指定同事确认接管"}

    if not _tier_allows(entry, agent):
        return {
            "ok": False,
            "error": "need_supervisor",
            "message": "该会话路由规则要求总部/对口专员接单，请选择对应身份",
        }

    welcome = build_human_welcome(agent, entry.get("brief"))
    entry["assigned_agent"] = agent
    entry["accepted_by"] = agent_id
    entry["accepted_at"] = time.time()
    entry["status"] = "connected"
    entry["pending_agent"] = None
    _save(entry)
    store.append_transfer_event(session_id, "accept", to_agent_id=agent_id)
    welcome_msg = store.append_message(session_id, "human", welcome, agent_id=agent_id, meta={"kind": "welcome"})
    _emit_status(session_id, entry)
    _emit_msg(session_id, welcome_msg)
    return {"ok": True, "status": "connected", "agent": agent, "welcome": welcome, "brief": entry.get("brief")}


def transfer_to_colleague(session_id: str, from_agent_id: str, to_agent_id: str, note: str = "") -> Dict[str, Any]:
    entry = _get_entry(session_id)
    if not entry or entry.get("status") not in ("connected", "transferring"):
        return {"ok": False, "error": "invalid_status"}
    to_agent = _find_agent(to_agent_id)
    if not to_agent:
        return {"ok": False, "error": "agent_not_found"}
    entry["status"] = "transferring"
    entry["pending_agent"] = to_agent
    entry["assigned_agent"] = entry.get("assigned_agent")
    _save(entry)
    store.append_transfer_event(session_id, "colleague", from_agent_id, to_agent_id, note)
    from handoff_i18n import build_system_message

    sys_text, sys_meta = build_system_message(
        "transfer", from_agent=from_agent_id, to_agent=to_agent_id, note=note or "",
    )
    sys = store.append_message(session_id, "system", sys_text, meta=sys_meta)
    _emit_status(session_id, entry)
    _emit_msg(session_id, sys)
    return {"ok": True, "status": "transferring", "pending_agent": to_agent}


def escalate_to_supervisor(session_id: str, note: str = "") -> Dict[str, Any]:
    entry = _get_entry(session_id)
    if not entry:
        return {"ok": False, "error": "session_not_found"}
    from_id = (entry.get("assigned_agent") or {}).get("agent_id", "")
    note = note or "一线客服申请升级总部客诉主管"
    entry["status"] = "escalated"
    entry["required_tier"] = "supervisor"
    entry["escalation_note"] = note
    entry["pending_agent"] = None
    brief = entry.get("brief") or {}
    brief["escalation_note"] = note
    entry["brief"] = brief
    _save(entry)
    store.append_transfer_event(session_id, "escalate", from_id, note=note)
    from handoff_i18n import build_system_message

    esc_text, esc_meta = build_system_message("escalate", note=note)
    esc = store.append_message(session_id, "system", esc_text, meta=esc_meta)
    _emit_status(session_id, entry)
    _emit_msg(session_id, esc)
    return {"ok": True, "status": "escalated", "required_tier": "supervisor"}


async def post_user_message(session_id: str, content: str, user_id: str = "") -> Dict[str, Any]:
    entry = _get_entry(session_id)
    if not entry or entry.get("status") != "connected":
        return {"ok": False, "error": "not_connected"}
    added = [store.append_message(session_id, "user", content)]
    if entry.get("observer_mode") and is_observer_request(content):
        recent = store.get_messages_since(session_id, 0)[-12:]
        reply = await generate_observer_reply(content, entry.get("brief"), recent)
        obs_msg = store.append_message(session_id, "observer", reply, meta={"kind": "observer"})
        store.append_observer_audit(session_id, reply, obs_msg.get("id"))
        added.append(obs_msg)
    for msg in added:
        _emit_msg(session_id, msg)
    return {"ok": True, "messages": added}


def append_desk_message(session_id: str, role: str, content: str, meta: Optional[Dict[str, Any]] = None) -> bool:
    entry = _get_entry(session_id)
    if not entry or entry.get("status") != "connected":
        return False
    agent_id = (meta or {}).get("agent_id", "")
    msg = store.append_message(session_id, role, content, agent_id=agent_id, meta=meta)
    _emit_msg(session_id, msg)
    if role in ("user", "human"):
        try:
            from im_sync_service import sync_message
            sync_message(session_id, role, content)
        except Exception:
            pass
    return True


def get_messages_since(session_id: str, since: float = 0) -> List[Dict[str, Any]]:
    return store.get_messages_since(session_id, since)


def process_sla_timeouts() -> List[Dict[str, Any]]:
    results = []
    for cand in store.list_sla_candidates():
        sid = cand["session_id"]
        from sla_lock import try_acquire_sla_lock, release_sla_lock

        if not try_acquire_sla_lock(sid):
            continue
        try:
            from_id = (cand.get("assigned_agent") or {}).get("agent_id", "")
            next_agent = _pick_next_agent(sid, exclude_ids=[from_id] if from_id else [])
            entry = _get_entry(sid)
            if not entry:
                continue
            entry["status"] = "transferring"
            entry["pending_agent"] = next_agent
            _save(entry)
            reason = cand.get("sla_reason", "timeout")
            store.append_transfer_event(sid, "timeout", from_id, next_agent["agent_id"], reason)
            from handoff_i18n import build_system_message

            sla_text, sla_meta = build_system_message(
                "sla_timeout", reason=reason, to_agent=next_agent["agent_id"],
            )
            sys_msg = store.append_message(sid, "system", sla_text, meta=sla_meta)
            _emit_status(sid, entry)
            _emit_msg(sid, sys_msg)
            results.append({"session_id": sid, "to_agent": next_agent["agent_id"], "reason": reason})
        finally:
            release_sla_lock(sid)
    return results


def list_desk_sessions(tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
    rows = []
    for entry in store.list_active_sessions(tenant_id=tenant_id):
        brief = entry.get("brief") or {}
        rows.append({
            "session_id": entry["session_id"],
            "status": entry.get("status"),
            "user_id": brief.get("user_id") or entry.get("user_id"),
            "summary": (brief.get("summary") or "")[:120],
            "intent": brief.get("intent"),
            "true_intent": (brief.get("true_intent") or "")[:80],
            "emotion_level": brief.get("emotion_level"),
            "required_tier": entry.get("required_tier", "standard"),
            "agent": entry.get("assigned_agent") or entry.get("pending_agent") or entry.get("suggested_agent"),
            "accepted": entry.get("status") == "connected",
            "updated_at": entry.get("accepted_at") or entry.get("enqueued_at"),
            "message_count": len(store.get_messages_since(entry["session_id"], 0)),
        })
    return rows


def get_desk_session(session_id: str, tenant_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    entry = _get_entry(session_id)
    if not entry:
        return None
    if tenant_id and (entry.get("tenant_id") or "mitako") != tenant_id:
        return None
    status = entry.get("status")
    can_accept = status in ("queuing", "escalated", "transferring")
    can_chat = status == "connected"
    return {
        "session_id": session_id,
        "status": status,
        "brief": entry.get("brief"),
        "agent": entry.get("assigned_agent") or entry.get("pending_agent") or entry.get("suggested_agent"),
        "assigned_agent": entry.get("assigned_agent"),
        "pending_agent": entry.get("pending_agent"),
        "required_tier": entry.get("required_tier"),
        "accepted_at": entry.get("accepted_at"),
        "accepted_by": entry.get("accepted_by"),
        "escalation_note": entry.get("escalation_note"),
        "transfer_events": store.get_transfer_events(session_id),
        "messages": store.get_messages_since(session_id, 0),
        "can_accept": can_accept,
        "can_chat": can_chat,
        "observer_mode": entry.get("observer_mode", True),
    }


def reset_session_handoff(session_id: str) -> None:
    store.delete_session(session_id)


def close_handoff_session(session_id: str, note: str = "") -> Dict[str, Any]:
    entry = _get_entry(session_id)
    if not entry:
        return {"ok": False, "error": "session_not_found"}
    store.close_session_status(session_id)
    from handoff_i18n import build_system_message

    close_text, close_meta = build_system_message("closed", note=note or "会话已结束")
    msg = store.append_message(session_id, "system", close_text, meta=close_meta)
    _emit_msg(session_id, msg)
    return {"ok": True, "status": "closed"}


def get_routing_config() -> Dict[str, Any]:
    return load_routing_config()


def update_routing_config(config: Dict[str, Any]) -> Dict[str, Any]:
    return save_routing_config(config)
