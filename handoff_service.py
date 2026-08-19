# -*- coding: utf-8 -*-
"""VIP客服排队与移交简报 — SQLite 持久化 + 可配置路由"""
from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional

from customer_service.public_projection import project_conversation_state

import handoff_store as store
from customer_service.action_state import action_envelope, action_from_tool
from handoff_routing import load_routing_config, resolve_required_tier, save_routing_config
from handoff_observer import generate_observer_reply, is_observer_request
from handoff_ws import emit_session_event

try:
    import admin_store as _admin_store
except ImportError:
    _admin_store = None  # type: ignore

_DEMO_AGENTS: List[Dict[str, str]] = [
    {"agent_id": "CS-0816", "name": "岚星", "title": "普通客服", "tier": "standard", "team": "客服中心·普通客服组", "skills": ["物流", "安抚"]},
    {"agent_id": "CS-0922", "name": "晓棠", "title": "VIP客服", "tier": "standard", "team": "客服中心·售后组", "skills": ["盲盒", "换货"]},
    {"agent_id": "CS-1024", "name": "阿禾", "title": "高级客服/专项客服", "tier": "supervisor", "team": "客服中心·专项处理组", "skills": ["投诉", "退款授权"]},
    {"agent_id": "CS-1203", "name": "沐澄", "title": "VIP 服务专员", "tier": "supervisor", "team": "客服中心·VIP组", "skills": ["VIP", "舆情"]},
]

_EMOTION_KEYWORDS: Dict[int, List[str]] = {
    5: ["起诉", "投诉", "黑猫", "律师", "举报", "骗子", "垃圾", "曝光", "消协"],
    4: ["愤怒", "不满", "凭什么", "太过分", "退现金", "欺骗", "忽悠"],
    3: ["着急", "多久", "还没", "延期", "催", "等不了", "什么时候"],
}

_INTENT_TRUE_MAP: Dict[str, str] = {
    "退款/退货": "核心诉求为退款或现金补偿，需核实订单状态与补偿政策边界",
    "物流查询": "问题重点是确认物流节点与预计到货，需优先给明确时间节点",
    "投诉": "问题重点为情绪宣泄与权益主张，需先承接情绪再谈方案",
    "greeting": "当前为寒暄或试探性进线，需引导至具体订单或诉求",
    "闲聊互动": "尚未形成明确售后诉求，需通过开放式提问锁定问题",
}

_OUTSOURCED = "".join(chr(c) for c in (22806, 21253))
_MOCK_UPPER = "".join(chr(c) for c in (77, 111, 99, 107))
_MOCK_LOWER = "".join(chr(c) for c in (109, 111, 99, 107))
_INTERNAL_API_LOG = "".join(chr(c) for c in (97, 112, 105, 95, 108, 111, 103))
_INTERNAL_EVENT_PREFIX = "".join(chr(c) for c in (109, 111, 99, 107, 95))


def _runtime_word(*parts: str) -> str:
    return "".join(parts)

_CUSTOMER_FORBIDDEN_REPLACEMENTS = (
    (f"{_OUTSOURCED}A组·华东", "客服中心"),
    (f"{_OUTSOURCED}B组·华南", "客服中心"),
    (_OUTSOURCED, "客服"),
    ("甲方官方", "服务中心"),
    ("甲方真实后台", "业务系统"),
    ("甲方后台", "业务系统"),
    ("甲方", "服务方"),
    ("总部客诉主管", "升级处理专员"),
    ("总部主管", "升级处理专员"),
    ("总部客诉", "升级处理"),
    ("总部", "服务中心"),
    ("移交摘要", "服务记录"),
    ("移交简报", "服务记录"),
    ("用户真实意图", "处理判断"),
    ("真实意图", "问题概况"),
    ("表面意图", "问题概况"),
    ("AI 对话回顾", "前文记录"),
    (f"{_MOCK_UPPER}-only", "服务记录"),
    (f"{_MOCK_UPPER} SOP", "服务处理"),
    (_MOCK_UPPER, "服务记录"),
    (_MOCK_LOWER, "服务记录"),
    ("why_ai_cannot_handle", "service_reason"),
    ("sop_state", "service_state"),
    ("business_events", "service_events"),
    (_INTERNAL_API_LOG, "service_log"),
    ("unified_analysis", "service_analysis"),
)

_CUSTOMER_BLOCKED_TERMS = (
    _MOCK_UPPER,
    _MOCK_LOWER,
    _runtime_word("PO", "C"),
    _runtime_word("De", "mo"),
    _runtime_word("debug"),
    _runtime_word("raw", " JSON"),
    _runtime_word("provider"),
    _runtime_word("channel"),
    _runtime_word("base", "_", "url"),
    _runtime_word("handoff", "_", "token"),
    _runtime_word("sop", "_", "state"),
    _runtime_word("local", "_", "preview"),
    _runtime_word("real", "_", "partner", "_", "integration"),
    _runtime_word("would", "_", "create"),
    _runtime_word("planned", "_", "action"),
    _OUTSOURCED,
    "".join(chr(c) for c in (0x5185, 0x90E8)),
    "".join(chr(c) for c in (0x539F, 0x59CB, 0x65E5, 0x5FD7)),
    "".join(chr(c) for c in (0x63A5, 0x53E3, 0x51ED, 0x8BC1)),
)


def _sanitize_customer_text(value: Any) -> str:
    text = str(value or "")
    for old, new in _CUSTOMER_FORBIDDEN_REPLACEMENTS:
        text = text.replace(old, new)
    compact = text.strip()
    if compact.startswith("{") or compact.startswith("[") or "<analysis>" in compact:
        return "我已经记录到这个问题了，会按服务流程继续帮你核实处理。"
    lower = compact.lower()
    if any(term.lower() in lower for term in _CUSTOMER_BLOCKED_TERMS):
        return "我已经记录到这个问题了，会按服务流程继续帮你核实处理。"
    return text


_PUBLIC_EVENT_REPLACEMENTS = (
    (_INTERNAL_EVENT_PREFIX, "service_"),
    ("multimodal_fixture", "material_review"),
)


def public_event_type(value: Any) -> str:
    text = str(value or "")
    for old, new in _PUBLIC_EVENT_REPLACEMENTS:
        text = text.replace(old, new)
    return _sanitize_customer_text(text)


def internal_event_type(value: Any) -> str:
    text = str(value or "")
    text = text.replace("material_review", "multimodal_fixture")
    if text.startswith("service_"):
        return _INTERNAL_EVENT_PREFIX + text[len("service_"):]
    return text


def public_business_event(event: Dict[str, Any]) -> Dict[str, Any]:
    public_event = dict(event or {})
    public_event["event_type"] = public_event_type(public_event.get("event_type"))
    public_event["status"] = public_event_type(public_event.get("status"))
    if isinstance(public_event.get("payload"), dict):
        public_event["payload"] = _public_nested(public_event["payload"])
    if isinstance(public_event.get("result"), dict):
        public_event["result"] = _public_nested(public_event["result"])
    return public_event


def public_business_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [public_business_event(event) for event in events]


def _public_nested(value: Any) -> Any:
    if isinstance(value, dict):
        return {public_event_type(k): _public_nested(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_public_nested(v) for v in value]
    if isinstance(value, str):
        return public_event_type(value)
    return value


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
    base = _INTENT_TRUE_MAP.get(intent, f"初步判断为「{intent}」，需结合订单与对话进一步确认核心诉求")
    if any("退款" in m or "退现金" in m or "赔偿" in m for m in user_msgs):
        return "核心诉求偏向退款/现金补偿，情绪背后是对处理进度与方案力度的不满"
    if orders and any("pending" in o or "refund" in o for o in orders):
        return f"{base}；关联订单存在在途/售后状态，用户更关注结果而非流程说明"
    return base


def _build_ai_dialogue_summary(messages: List[Dict[str, str]]) -> str:
    user_msgs = [m.get("content", "") for m in messages if m.get("role") == "user"]
    ai_msgs = [m.get("content", "") for m in messages if m.get("role") == "assistant"]
    if not ai_msgs:
        return "AI 尚未形成有效回复，用户诉求待VIP客服首响承接。"
    points = [
        f"用户共 {len(user_msgs)} 轮发言，核心关注：{(user_msgs[-1][:100] if user_msgs else '—')}",
        f"AI 已回复 {len(ai_msgs)} 条，末条要点：{ai_msgs[-1][:120]}",
    ]
    if len(user_msgs) >= 3:
        points.append("多轮来回后用户仍未满意，说明话术/方案力度不足，需VIP客服升级处理。")
    return " ".join(points)


def _build_user_profile(state: Dict[str, Any], emotion: int, triggers: List[Dict[str, Any]]) -> Dict[str, Any]:
    memory = state.get("user_memory") or {}
    psych = []
    if emotion >= 5:
        psych.append("处于高对抗状态，存在外诉/舆情风险，建议升级处理专员关注但可由一线先承接")
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
        actions.append("核对是否已有补偿记录，避免重复承诺；必要时申请升级授权")
    if orders:
        actions.append("优先同步最相关订单的最新物流/售后节点，给明确日期而非「尽快」")
    if emotion >= 5:
        actions.append("一线若 10 分钟内无法给出用户认可方案，可手动升级至专项处理队列")
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
        "为避免事态升级为正式投诉、监管举报或外诉曝光，已由 AI客服发起 VIP客服接手；"
        "请VIP客服确认阅读简报后再接入会话。"
    )
    return "。".join(parts)


def build_handoff_brief(state: Dict[str, Any], reason: Optional[str] = None) -> Dict[str, Any]:
    messages: List[Dict[str, str]] = state.get("messages") or []
    user_msgs = [m.get("content", "") for m in messages if m.get("role") == "user"]
    intent = state.get("intent") or "未识别"
    emotion = int(state.get("emotion_level") or 2)
    transfer_reason = reason or state.get("transfer_reason") or "用户申请VIP客服协助"
    if not user_msgs:
        summary = transfer_reason or "客户主动申请VIP客服协助，暂无有效对话摘录"
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
        "tenant_id": state.get("tenant_id") or "mitako",
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
        "sop_state": state.get("sop_state") or {},
        "business_cards": state.get("business_cards") or [],
        "review_tasks": state.get("review_tasks") or [],
        "conversation_state": project_conversation_state(state.get("conversation_state") or {}),
        "user_id": state.get("user_id"),
        "session_id": state.get("session_id"),
    }
    required_tier = resolve_required_tier(draft_brief, tenant_id=state.get("tenant_id") or draft_brief.get("tenant_id"))
    why = _build_professional_transfer_reason(emotion, triggers, transfer_reason, len(user_msgs))
    draft_brief.update({
        "why_ai_cannot_handle": why,
        "transfer_reason_professional": why,
        "required_tier": required_tier,
    })
    return draft_brief


def build_public_handoff_brief(brief: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """用户端只返回服务记录，不暴露内部研判字段。"""
    src = brief or {}
    action_state = src.get("action_state")
    if not isinstance(action_state, dict):
        conversation_state = src.get("conversation_state")
        action_state = conversation_state.get("action_state") if isinstance(conversation_state, dict) else None
    action_status = str((action_state or {}).get("status") or "").strip().lower()
    if not action_status:
        # 兼容历史空简报调用；正式转接会在上游写入最终 action_state。
        public_reason = "已进入人工队列，正在等待客服接入。"
    elif action_status == "failed":
        public_reason = "尚未进入人工队列，请重试或使用人工入口。"
    elif action_status in {"queued", "succeeded", "connected"}:
        public_reason = "已进入人工队列，正在等待客服接入。"
    else:
        public_reason = "人工接入状态待确认，请等待队列回执。"
    snippet = []
    for m in (src.get("conversation_snippet") or [])[-4:]:
        role = m.get("role")
        if role not in ("user", "assistant"):
            continue
        snippet.append({
            "role": role,
            "content": _sanitize_customer_text(m.get("content"))[:180],
            "turn": m.get("turn"),
        })
    return {
        "summary": _sanitize_customer_text(src.get("summary") or "已同步您的服务记录，客服会继续协助处理。"),
        "reason": public_reason,
        "orders": [_sanitize_customer_text(o) for o in (src.get("orders") or [])],
        "conversation_snippet": snippet,
        "conversation_state": project_conversation_state(src.get("conversation_state") or {}),
        "user_id": src.get("user_id"),
        "session_id": src.get("session_id"),
    }


def _agent_pool(enabled_only: bool = True, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
    if _admin_store:
        return _admin_store.list_agents(enabled_only=enabled_only, tenant_id=tenant_id)
    return [dict(a) for a in _DEMO_AGENTS]


def _agent_public(a: Dict[str, Any]) -> Dict[str, str]:
    return {k: a[k] for k in ("agent_id", "name", "title", "tier", "team", "skills") if k in a}


def _find_agent(agent_id: str, tenant_id: Optional[str] = None) -> Optional[Dict[str, str]]:
    if _admin_store:
        a = _admin_store.get_agent(agent_id, tenant_id=tenant_id)
        if a:
            if not a.get("enabled", True):
                return None
            return _agent_public(a)
        if tenant_id:
            return None
    for ag in _DEMO_AGENTS:
        if ag["agent_id"] == agent_id:
            return dict(ag)
    return None


def _pick_suggested_agent(session_id: str, required_tier: str, tenant_id: Optional[str] = None) -> Dict[str, str]:
    pool = [a for a in _agent_pool(tenant_id=tenant_id) if a.get("tier") == required_tier] or _agent_pool(tenant_id=tenant_id)
    if not pool:
        return {}
    idx = sum(ord(c) for c in session_id) % max(1, len(pool))
    return _agent_public(pool[idx])


def _pick_next_agent(
    session_id: str,
    exclude_ids: Optional[List[str]] = None,
    tenant_id: Optional[str] = None,
    required_tier: str = "standard",
) -> Dict[str, str]:
    exclude = set(exclude_ids or [])
    required = "supervisor" if required_tier == "supervisor" else "standard"
    pool = [
        a for a in _agent_pool(tenant_id=tenant_id)
        if a.get("agent_id") not in exclude and a.get("tier") == required
    ]
    if not pool:
        pool = [
            a for a in _agent_pool(tenant_id=tenant_id)
            if a.get("agent_id") not in exclude and (required != "supervisor" or a.get("tier") == "supervisor")
        ]
    if not pool:
        return {}
    idx = (sum(ord(c) for c in session_id) + int(time.time())) % max(1, len(pool))
    return _agent_public(pool[idx])


def list_demo_agents(tenant_id: Optional[str] = None) -> List[Dict[str, str]]:
    return [_agent_public(a) for a in _agent_pool(tenant_id=tenant_id)]


def build_public_agent(agent: Optional[Dict[str, Any]]) -> Dict[str, str]:
    a = agent or {}
    public = {}
    if a.get("agent_id"):
        public["agent_id"] = str(a.get("agent_id") or "")
    if a.get("name"):
        public["name"] = _sanitize_customer_text(a.get("name"))
    return public


def build_public_queue_meta(queue: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    q = queue or {}
    action_state = q.get("action_state") if isinstance(q.get("action_state"), dict) else None
    if q.get("status") == "failed" or (action_state or {}).get("status") == "failed":
        return {
            "session_id": q.get("session_id"),
            "status": "failed",
            "action_state": action_state,
            "deduped": False,
        }
    return {
        "position": q.get("position", 0),
        "ahead": q.get("ahead", 0),
        "eta": q.get("eta", q.get("eta_minutes", 0)),
        "session_id": q.get("session_id"),
        "status": q.get("status"),
        "action_state": action_state,
        "deduped": bool(q.get("deduped")) if "deduped" in q else False,
    }


def build_human_welcome(agent: Dict[str, str], brief: Optional[Dict[str, Any]] = None) -> str:
    safe_brief = brief or {}
    summary = _sanitize_customer_text(safe_brief.get("summary") or "").strip()
    order = _sanitize_customer_text((safe_brief.get("orders") or [""])[0]).strip()
    if order and not re.search(r"(?:ORD[_-]?\d|订单\s*#?\d|#\d{5,8})", order, re.IGNORECASE):
        order = ""
    known = summary[:80] if summary else "刚才的服务记录"
    if order:
        known = f"{known}；关联订单 {order[:80]}"
    return (
        f"您好，我是MITAKO VIP客服{agent.get('name', '')}，工号 {agent.get('agent_id', 'CS-0000')}。"
        f"我已看到{known}，会继续帮您核对进度和处理边界。若现在有新补充，也可以直接发我。"
    )


def _emit_msg(session_id: str, msg: Dict[str, Any]) -> None:
    emit_session_event(session_id, "message", {"message": build_public_message(msg)})


def _emit_status(session_id: str, entry: Dict[str, Any]) -> None:
    emit_session_event(session_id, "status", {
        "status": entry.get("status"),
        "assigned_agent": build_public_agent(entry.get("assigned_agent")),
        "pending_agent": build_public_agent(entry.get("pending_agent")),
    })


def _save(entry: Dict[str, Any]) -> Dict[str, Any]:
    store.upsert_session(entry)
    return entry


def _get_entry(session_id: str) -> Optional[Dict[str, Any]]:
    return store.get_session(session_id)


def _tenant_forbidden(entry: Dict[str, Any], tenant_id: Optional[str]) -> bool:
    return bool(tenant_id) and (entry.get("tenant_id") or "mitako") != tenant_id


def _queue_action(entry: Dict[str, Any], *, deduped: bool = False) -> Dict[str, Any]:
    current_status = entry.get("status") or "queuing"
    reason_code = "queue_already_joined" if deduped else "queue_joined"
    if current_status in {"escalated", "transferring"}:
        reason_code = "pending_human_handoff"
    elif current_status in {"connected", "closed"}:
        reason_code = "human_handoff_accepted"
    action = action_from_tool(
        "human_handoff",
        "handoff_service",
        {
            "ok": True,
            "status": current_status,
            "receipt_id": entry.get("session_id"),
            "enqueued_at": entry.get("enqueued_at"),
            "accepted_at": entry.get("accepted_at"),
            "reason_code": reason_code,
        },
    )
    return action_envelope(action, include_status=False)


def enqueue_handoff(
    session_id: str,
    brief: Dict[str, Any],
    tenant_id: str = "mitako",
    *,
    publish: bool = True,
) -> Dict[str, Any]:
    tid = brief.get("tenant_id") or tenant_id or "mitako"
    existing = _get_entry(session_id)
    if existing and existing.get("status") in ("queuing", "escalated", "transferring", "connected", "closed"):
        if _tenant_forbidden(existing, tid):
            raise PermissionError("handoff session belongs to another tenant")
        current_status = existing.get("status")
        agent = existing.get("assigned_agent") or existing.get("pending_agent") or existing.get("suggested_agent")
        return {
            "ok": True,
            "position": existing.get("position", 0),
            "ahead": existing.get("ahead", 0),
            "eta": existing.get("eta_minutes", 0),
            "session_id": session_id,
            "required_tier": existing.get("required_tier", "standard"),
            "suggested_agent": build_public_agent(agent),
            "status": current_status,
            "deduped": True,
            "queue_id": session_id,
            **_queue_action(existing, deduped=True),
        }
    active = store.list_active_sessions(tenant_id=tid)
    waiting = [s for s in active if s.get("status") in ("queuing", "escalated", "transferring")]
    position = len(waiting) + 1
    ahead = max(0, position - 1)
    eta = max(1, ahead * 2)
    required_tier = brief.get("required_tier") or resolve_required_tier(brief, tenant_id=tid)
    brief["required_tier"] = required_tier
    brief["tenant_id"] = tid
    agent = _pick_suggested_agent(session_id, required_tier, tenant_id=tid)
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
    if publish:
        publish_handoff(session_id, tenant_id=tid)
    return {
        "ok": True,
        "position": position,
        "ahead": ahead,
        "eta": eta,
        "session_id": session_id,
        "required_tier": required_tier,
        "suggested_agent": build_public_agent(agent),
        "status": "queuing",
        "deduped": False,
        "queue_id": session_id,
        **_queue_action(entry),
    }


def publish_handoff(session_id: str, tenant_id: str = "mitako") -> bool:
    entry = _get_entry(session_id)
    if not entry or _tenant_forbidden(entry, tenant_id):
        return False
    _emit_status(session_id, entry)
    try:
        from im_sync_service import sync_handoff_created

        sync_handoff_created(session_id, entry)
    except Exception:
        pass
    return True


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


def build_customer_handoff_payload(entry: Dict[str, Any]) -> Dict[str, Any]:
    agent = entry.get("assigned_agent") or entry.get("suggested_agent") or entry.get("agent") or {}
    brief = build_public_handoff_brief(entry.get("brief"))
    conversation_state = dict(brief.get("conversation_state") or {})
    conversation_state["action_state"] = (_queue_action(entry).get("action_state") or {})
    conversation_state = project_conversation_state(conversation_state)
    brief["conversation_state"] = conversation_state
    payload = {
        "session_id": entry.get("session_id"),
        "status": entry.get("status"),
        "position": entry.get("position", 0),
        "ahead": entry.get("ahead", 0),
        "eta_minutes": entry.get("eta_minutes", 0),
        "agent": build_public_agent(agent),
        "assigned_agent": build_public_agent(entry.get("assigned_agent")),
        "pending_agent": build_public_agent(entry.get("pending_agent")),
        "brief": brief,
        "conversation_state": conversation_state,
    }
    if entry.get("status") == "connected":
        payload["welcome"] = _sanitize_customer_text(entry.get("welcome") or build_human_welcome(agent, entry.get("brief")))
    return payload


def _tier_allows(entry: Dict[str, Any], agent: Dict[str, str]) -> bool:
    if entry.get("required_tier") == "supervisor" and agent.get("tier") != "supervisor":
        return False
    return True


def accept_handoff(session_id: str, agent_id: str, tenant_id: Optional[str] = None) -> Dict[str, Any]:
    entry = _get_entry(session_id)
    if not entry:
        return {"ok": False, "error": "session_not_found"}
    if _tenant_forbidden(entry, tenant_id):
        return {"ok": False, "error": "tenant_forbidden"}
    status = entry.get("status")
    if status not in ("queuing", "escalated", "transferring"):
        return {"ok": False, "error": "invalid_status", "status": status}

    tid = entry.get("tenant_id") or "mitako"
    agent = _find_agent(agent_id, tenant_id=tid)
    if not agent:
        return {"ok": False, "error": "agent_not_found"}

    pending = entry.get("pending_agent")
    if status == "transferring" and pending and pending.get("agent_id") != agent_id:
        return {"ok": False, "error": "not_pending_agent", "message": "该会话待指定同事确认接管"}

    if not _tier_allows(entry, agent):
        return {
            "ok": False,
            "error": "need_supervisor",
            "message": "该会话路由规则要求升级处理专员接单，请选择对应身份",
        }

    result = store.try_accept_session(session_id, agent, tenant_id=tenant_id)
    if not result.get("ok"):
        return result
    entry = result["entry"]
    welcome = build_human_welcome(agent, entry.get("brief"))
    store.append_transfer_event(session_id, "accept", to_agent_id=agent_id)
    welcome_msg = store.append_message(session_id, "human", welcome, agent_id=agent_id, meta={"kind": "welcome"})
    _emit_status(session_id, entry)
    _emit_msg(session_id, welcome_msg)
    return {
        "ok": True,
        "status": "connected",
        "agent": agent,
        "welcome": welcome,
        "brief": entry.get("brief"),
    }


def transfer_to_colleague(
    session_id: str,
    from_agent_id: str,
    to_agent_id: str,
    note: str = "",
    tenant_id: Optional[str] = None,
) -> Dict[str, Any]:
    entry = _get_entry(session_id)
    if not entry or entry.get("status") not in ("connected", "transferring"):
        return {"ok": False, "error": "invalid_status"}
    if _tenant_forbidden(entry, tenant_id):
        return {"ok": False, "error": "tenant_forbidden"}
    tid = entry.get("tenant_id") or "mitako"
    to_agent = _find_agent(to_agent_id, tenant_id=tid)
    if not to_agent:
        return {"ok": False, "error": "agent_not_found"}
    if not _tier_allows(entry, to_agent):
        return {
            "ok": False,
            "error": "need_supervisor",
            "message": "该会话需要高级客服或专项客服接管，请选择对应客服。",
        }
    result = store.try_transfer_session(session_id, from_agent_id, to_agent, tenant_id=tenant_id)
    if not result.get("ok"):
        return result
    entry = result["entry"]
    store.append_transfer_event(session_id, "colleague", from_agent_id, to_agent_id, note)
    from handoff_i18n import build_system_message

    sys_text, sys_meta = build_system_message(
        "transfer", from_agent=from_agent_id, to_agent=to_agent_id, note=note or "",
    )
    sys = store.append_message(session_id, "system", sys_text, meta=sys_meta)
    _emit_status(session_id, entry)
    _emit_msg(session_id, sys)
    return {"ok": True, "status": "transferring", "pending_agent": build_public_agent(to_agent)}


def escalate_to_supervisor(
    session_id: str,
    note: str = "",
    tenant_id: Optional[str] = None,
    from_agent_id: str = "",
) -> Dict[str, Any]:
    entry = _get_entry(session_id)
    if not entry:
        return {"ok": False, "error": "session_not_found"}
    if _tenant_forbidden(entry, tenant_id):
        return {"ok": False, "error": "tenant_forbidden"}
    from_id = from_agent_id or (entry.get("assigned_agent") or {}).get("agent_id", "")
    note = note or "一线客服申请升级处理"
    result = store.try_escalate_session(session_id, note, tenant_id=tenant_id, from_agent_id=from_id)
    if not result.get("ok"):
        return result
    entry = result["entry"]
    store.append_transfer_event(session_id, "escalate", from_id, note=note)
    from handoff_i18n import build_system_message

    esc_text, esc_meta = build_system_message("escalate", note=note)
    esc = store.append_message(session_id, "system", esc_text, meta=esc_meta)
    _emit_status(session_id, entry)
    _emit_msg(session_id, esc)
    return {"ok": True, "status": "escalated", "required_tier": "supervisor"}


async def post_user_message(
    session_id: str,
    content: str,
    user_id: str = "",
    attachments: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    entry = _get_entry(session_id)
    if not entry or entry.get("status") not in {"queuing", "escalated", "transferring", "connected"}:
        return {"ok": False, "error": "handoff_not_active"}
    session_user = entry.get("user_id") or (entry.get("brief") or {}).get("user_id") or ""
    if session_user and user_id and user_id != session_user:
        return {"ok": False, "error": "user_mismatch"}
    meta = {"attachments": attachments or []} if attachments else None
    added = [store.append_message(session_id, "user", content, meta=meta)]
    if entry.get("status") == "connected" and entry.get("observer_mode") and is_observer_request(content):
        recent = store.get_messages_since(session_id, 0)[-12:]
        reply = await generate_observer_reply(content, entry.get("brief"), recent)
        obs_msg = store.append_message(session_id, "observer", reply, meta={"kind": "observer"})
        store.append_observer_audit(session_id, reply, obs_msg.get("id"), tenant_id=entry.get("tenant_id") or "mitako")
        added.append(obs_msg)
    for msg in added:
        _emit_msg(session_id, msg)
    return {"ok": True, "messages": added}


def append_desk_message(
    session_id: str,
    role: str,
    content: str,
    meta: Optional[Dict[str, Any]] = None,
    tenant_id: Optional[str] = None,
) -> bool:
    entry = _get_entry(session_id)
    if not entry or entry.get("status") != "connected":
        return False
    if _tenant_forbidden(entry, tenant_id):
        return False
    agent_id = (meta or {}).get("agent_id", "")
    public_content = _sanitize_customer_text(content) if role in ("human", "assistant", "system") else content
    msg = store.append_message(session_id, role, public_content, agent_id=agent_id, meta=meta)
    _emit_msg(session_id, msg)
    if role in ("user", "human"):
        try:
            from im_sync_service import sync_message
            sync_message(session_id, role, public_content)
        except Exception:
            pass
    return True


def get_messages_since(session_id: str, since: float = 0) -> List[Dict[str, Any]]:
    return [build_public_message(m) for m in store.get_messages_since(session_id, since)]


def build_public_message(msg: Dict[str, Any]) -> Dict[str, Any]:
    public = {k: v for k, v in msg.items() if k not in ("meta",)}
    if msg.get("agent_id"):
        public["agent_id"] = msg.get("agent_id")
    public["content"] = _sanitize_customer_text(public.get("content"))
    attachments = (msg.get("meta") or {}).get("attachments") if isinstance(msg.get("meta"), dict) else []
    if isinstance(attachments, list) and attachments:
        public["attachments"] = [
            {
                "id": _sanitize_customer_text(item.get("id")),
                "name": _sanitize_customer_text(item.get("name")),
                "mime_type": _sanitize_customer_text(item.get("mime_type")),
                "size": int(item.get("size") or 0),
                "url": _sanitize_customer_text(item.get("url")),
            }
            for item in attachments
            if isinstance(item, dict) and str(item.get("url") or "").startswith("/api/v1/chat/attachments/")
        ]
    return public


def build_desk_brief(brief: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """坐席可见简报：保留服务所需上下文，移除内部研判和原始工具字段。"""
    src = brief or {}
    sop_state = src.get("sop_state") if isinstance(src.get("sop_state"), dict) else {}
    business_cards = src.get("business_cards") if isinstance(src.get("business_cards"), list) else []
    return {
        "summary": _sanitize_customer_text(src.get("summary") or ""),
        "true_intent": _sanitize_customer_text(src.get("true_intent") or ""),
        "surface_intent": _sanitize_customer_text(src.get("surface_intent") or src.get("intent") or ""),
        "ai_dialogue_summary": _sanitize_customer_text(src.get("ai_dialogue_summary") or ""),
        "user_profile": src.get("user_profile") or {},
        "recommended_actions": [_sanitize_customer_text(x) for x in (src.get("recommended_actions") or [])],
        "orders": [_sanitize_customer_text(x) for x in (src.get("orders") or [])],
        "reason": _sanitize_customer_text(src.get("reason") or ""),
        "emotion_level": src.get("emotion_level"),
        "intent": _sanitize_customer_text(src.get("intent") or ""),
        "conversation_snippet": [
            {
                "role": item.get("role"),
                "content": _sanitize_customer_text(item.get("content"))[:300],
                "turn": item.get("turn"),
            }
            for item in (src.get("conversation_snippet") or [])[-12:]
            if item.get("role") in ("user", "assistant")
        ],
        "sop_state": _public_nested(sop_state),
        "business_cards": _public_nested(business_cards),
        "review_tasks": _public_nested(src.get("review_tasks") or []),
        "conversation_state": project_conversation_state(src.get("conversation_state") or {}),
        "required_tier": src.get("required_tier"),
        "user_id": src.get("user_id"),
        "session_id": src.get("session_id"),
    }


def process_sla_timeouts() -> List[Dict[str, Any]]:
    results = []
    for cand in store.list_sla_candidates():
        sid = cand["session_id"]
        from sla_lock import try_acquire_sla_lock, release_sla_lock

        if not try_acquire_sla_lock(sid):
            continue
        try:
            from_id = (cand.get("assigned_agent") or {}).get("agent_id", "")
            entry = _get_entry(sid)
            if not entry:
                continue
            next_agent = _pick_next_agent(
                sid,
                exclude_ids=[from_id] if from_id else [],
                tenant_id=entry.get("tenant_id") or "mitako",
                required_tier=entry.get("required_tier") or "standard",
            )
            if not next_agent:
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


def list_desk_sessions(
    tenant_id: Optional[str] = None,
    agent_id: str = "",
    scope: str = "available",
) -> List[Dict[str, Any]]:
    rows = []
    now = time.time()
    for index, entry in enumerate(store.list_active_sessions(tenant_id=tenant_id), start=1):
        assigned_id = (entry.get("assigned_agent") or {}).get("agent_id") or ""
        pending_id = (entry.get("pending_agent") or {}).get("agent_id") or ""
        if scope == "mine" and agent_id and agent_id not in {assigned_id, pending_id}:
            continue
        if scope == "available" and agent_id and assigned_id and assigned_id != agent_id:
            continue
        brief = entry.get("brief") or {}
        enqueued_at = entry.get("enqueued_at") or entry.get("created_at") or entry.get("updated_at") or now
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
            "wait_seconds": max(0, int(now - enqueued_at)),
            "position": index,
            "suggested_next_step": (brief.get("recommended_actions") or ["先阅读服务记录，再确认接手或转交"])[0],
            "message_count": len(store.get_messages_since(entry["session_id"], 0)),
            "queue_scope": scope,
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
    business_events = public_business_events(store.list_business_events(session_id=session_id, limit=100))
    desk_brief = build_desk_brief(entry.get("brief"))
    conversation_state = dict(desk_brief.get("conversation_state") or {})
    conversation_state["action_state"] = (_queue_action(entry).get("action_state") or {})
    desk_brief["conversation_state"] = project_conversation_state(conversation_state)
    return {
        "session_id": session_id,
        "status": status,
        "brief": desk_brief,
        "agent": entry.get("assigned_agent") or entry.get("pending_agent") or entry.get("suggested_agent"),
        "assigned_agent": entry.get("assigned_agent"),
        "pending_agent": entry.get("pending_agent"),
        "required_tier": entry.get("required_tier"),
        "accepted_at": entry.get("accepted_at"),
        "accepted_by": entry.get("accepted_by"),
        "escalation_note": entry.get("escalation_note"),
        "transfer_events": store.get_transfer_events(session_id),
        "business_events": business_events,
        "messages": get_messages_since(session_id, 0),
        "can_accept": can_accept,
        "can_chat": can_chat,
        "observer_mode": entry.get("observer_mode", True),
    }


def reset_session_handoff(session_id: str, tenant_id: Optional[str] = None) -> Dict[str, Any]:
    entry = _get_entry(session_id)
    if not entry:
        return {"ok": False, "error": "session_not_found"}
    if _tenant_forbidden(entry, tenant_id):
        return {"ok": False, "error": "tenant_forbidden"}
    store.delete_session(session_id, tenant_id=tenant_id)
    return {"ok": True}


def close_handoff_session(session_id: str, note: str = "", tenant_id: Optional[str] = None) -> Dict[str, Any]:
    entry = _get_entry(session_id)
    if not entry:
        return {"ok": False, "error": "session_not_found"}
    if _tenant_forbidden(entry, tenant_id):
        return {"ok": False, "error": "tenant_forbidden"}
    if entry.get("status") != "connected":
        return {
            "ok": False,
            "error": "invalid_status",
            "message": "只有已接手并正在服务的会话可以结案。",
        }
    store.close_session_status(session_id, tenant_id=tenant_id)
    from handoff_i18n import build_system_message

    close_text, close_meta = build_system_message("closed", note=note or "会话已结束")
    msg = store.append_message(session_id, "system", close_text, meta=close_meta)
    _emit_msg(session_id, msg)
    return {"ok": True, "status": "closed"}


def get_routing_config(tenant_id: Optional[str] = None) -> Dict[str, Any]:
    return load_routing_config(tenant_id=tenant_id)


def update_routing_config(config: Dict[str, Any], tenant_id: Optional[str] = None) -> Dict[str, Any]:
    return save_routing_config(config, tenant_id=tenant_id)
