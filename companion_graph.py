# -*- coding: utf-8 -*-
"""
Companion LangGraph 工作流 — 安全 / 情绪 / 回复 / 可观测 trace

可选 LangSmith：设置 LANGCHAIN_TRACING_V2=true + LANGCHAIN_API_KEY + LANGCHAIN_PROJECT
"""
from __future__ import annotations

import os
import re
import time
import uuid
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import END, StateGraph

from companion_intent import detect_consumption_intents
from companion_mode import detect_cs_parttime_intent
from companion_orders import get_companion_order, order_to_progress_card
from companion_richtext import COMPANION_RICH_TEXT_RULES, normalize_companion_reply
from companion_memory import format_memories_for_prompt
from companion_viking import load_companion_memory, update_companion_memory
from companion_store import personality_prompt
from companion_tools import tool_search_products
from llm_models import get_model_api_key, get_model_config

# LangSmith 可观测（与 LangGraph 生态一致）
if os.getenv("LANGCHAIN_TRACING_V2", "").strip().lower() in ("1", "true", "yes"):
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")

_BLOCK_PATTERNS = re.compile(
    r"(自杀|自残|制毒|炸弹|恐怖袭击|强奸|幼女|nigger|kill myself|suicide)",
    re.I,
)
_NEGATIVE_EMOTION = re.compile(r"(烦|生气|愤怒|崩溃|失望|投诉|退款|骗|垃圾|差评|等很久|没到|延迟|心累|难受)")
_POSITIVE_EMOTION = re.compile(r"(谢谢|感谢|开心|喜欢|爱了|太好了|超棒|满意|感动|治愈)")


class CompanionState(TypedDict, total=False):
    turn_id: str
    user_message: str
    persona: Dict[str, Any]
    history: List[Dict[str, str]]
    model_id: str
    agent_mode: str
    mode_switched: bool
    emotion_level: int
    emotion_label: str
    safety_status: str
    safety_reason: str
    reply: str
    trace_events: List[Dict[str, Any]]
    api_log: Dict[str, Any]
    duration_ms: int
    assistant_intents: List[Dict[str, Any]]
    ui_cards: List[Dict[str, Any]]
    user_memories: List[Dict[str, Any]]
    new_memories: List[Dict[str, Any]]
    memory_line: str
    viking_level: str
    memory_capsule: str


def _trace(state: CompanionState, node: str, status: str, desc: str) -> None:
    events = state.setdefault("trace_events", [])
    events.append({"node": node, "status": status, "desc": desc, "ts": time.time()})


def _emotion_from_text(text: str) -> tuple[int, str]:
    t = text or ""
    level = 3
    label = "平稳"
    if _BLOCK_PATTERNS.search(t):
        level = 6
        label = "高风险"
    elif _NEGATIVE_EMOTION.search(t):
        level = 5 if re.search(r"(崩溃|投诉|骗|垃圾)", t) else 4
        label = "不满/焦虑"
    elif _POSITIVE_EMOTION.search(t):
        level = 2
        label = "积极"
    elif len(t) > 80:
        level = 3
        label = "长述"
    return level, label


async def node_safety_scan(state: CompanionState) -> Dict[str, Any]:
    _trace(state, "safety_scan", "start", "Companion 安全策略扫描")
    msg = state.get("user_message") or ""
    status = "pass"
    reason = ""
    if _BLOCK_PATTERNS.search(msg):
        status = "block"
        reason = "命中高危/违法关键词"
    elif re.search(r"(傻逼|去死|操你)", msg, re.I):
        status = "flag"
        reason = "辱骂/攻击性用语"
    _trace(state, "safety_scan", "end", f"结果={status}")
    return {"safety_status": status, "safety_reason": reason}


async def node_emotion_analyze(state: CompanionState) -> Dict[str, Any]:
    _trace(state, "emotion_analyze", "start", "情绪与意图分析")
    level, label = _emotion_from_text(state.get("user_message") or "")
    mode = state.get("agent_mode") or "companion"
    switched = False
    if detect_cs_parttime_intent(state.get("user_message") or "") and mode != "cs_parttime":
        mode = "cs_parttime"
        switched = True
        label = "售后诉求"
    _trace(state, "emotion_analyze", "end", f"Level {level} · {label}")
    return {
        "emotion_level": level,
        "emotion_label": label,
        "agent_mode": mode,
        "mode_switched": switched,
    }


def _build_assistant_cards(intents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """根据检测到的消费助理意图，生成 OpenUI 卡片 payload（SSE event: card）"""
    cards: List[Dict[str, Any]] = []
    for intent in intents:
        name = intent.get("intent")
        oid = (intent.get("order_id") or "").strip().upper()
        if name == "order_reference":
            if oid:
                order = get_companion_order(oid)
                if order:
                    cards.append({"type": "order_progress", "data": order_to_progress_card(order)})
            cards.append(
                {
                    "type": "companion_watch_form",
                    "data": {
                        "order_id": oid,
                        "hint": "已识别订单引用，确认后我帮你盯物流",
                        "prefilled": bool(oid),
                    },
                }
            )
        elif name == "watch_order":
            cards.append(
                {
                    "type": "companion_watch_form",
                    "data": {
                        "order_id": intent.get("order_id") or "",
                        "hint": "确认或填写订单号，我会帮你盯物流变化",
                        "prefilled": bool(intent.get("order_id")),
                    },
                }
            )
        elif name == "product_search":
            query = intent.get("query") or ""
            products: List[Dict[str, Any]] = []
            if query and not intent.get("needs_input"):
                hit = tool_search_products(query, limit=6)
                products = hit.get("products") or []
            cards.append(
                {
                    "type": "companion_product_picker",
                    "data": {
                        "query": query,
                        "products": products,
                        "needs_input": bool(intent.get("needs_input") or not products),
                    },
                }
            )
        elif name == "wishlist_hint":
            cards.append(
                {
                    "type": "companion_product_picker",
                    "data": {
                        "query": "",
                        "products": [],
                        "needs_input": True,
                        "wishlist_mode": True,
                    },
                }
            )
    return cards


async def node_load_memory(state: CompanionState) -> Dict[str, Any]:
    """OpenViking load_memory — 与客服 Agent 同架构，Companion 专用 profile 字段"""
    _trace(state, "load_memory", "start", "正在读取 OpenViking Companion 记忆...")
    persona = state.get("persona") or {}
    user_id = persona.get("user_id") or ""
    emotion_level = int(state.get("emotion_level") or 3)
    loaded = load_companion_memory(user_id, persona, emotion_level=emotion_level) if user_id else {}
    memories = loaded.get("user_memories") or []
    level = loaded.get("viking_level") or "L0"
    desc = loaded.get("memory_capsule") or f"OpenViking: {level} · {len(memories)} 条"
    _trace(state, "load_memory", "end", desc)
    return {
        "user_memories": memories,
        "memory_line": loaded.get("memory_line") or "",
        "viking_level": level,
        "memory_capsule": desc,
    }


async def node_update_memory(state: CompanionState) -> Dict[str, Any]:
    """OpenViking update_memory — 分析本轮对话并回写 viking:// profile"""
    _trace(state, "update_memory", "start", "学习并更新 OpenViking 长期偏好...")
    persona = state.get("persona") or {}
    user_id = persona.get("user_id") or ""
    msg = state.get("user_message") or ""
    reply = state.get("reply") or ""
    emotion_level = int(state.get("emotion_level") or 3)
    emotion_label = state.get("emotion_label") or ""
    if not user_id:
        _trace(state, "update_memory", "end", "无 user_id · 跳过")
        return {"new_memories": [], "user_memories": state.get("user_memories") or []}
    result = update_companion_memory(
        user_id, persona, msg, reply, emotion_level=emotion_level, emotion_label=emotion_label
    )
    desc = result.get("memory_capsule") or "OpenViking 同步完成"
    _trace(state, "update_memory", "end", desc)
    return {
        "new_memories": result.get("new_memories") or [],
        "user_memories": result.get("user_memories") or [],
        "viking_level": result.get("viking_level") or "L0",
        "memory_capsule": desc,
    }


async def node_assistant_intent(state: CompanionState) -> Dict[str, Any]:
    """消费助理意图 — 驱动 OpenUI 交互卡，不在聊天外挂静态面板"""
    _trace(state, "assistant_intent", "start", "消费助理意图识别")
    mode = state.get("agent_mode") or "companion"
    if mode == "cs_parttime":
        _trace(state, "assistant_intent", "end", "cs_parttime 模式 · 跳过消费助理")
        return {"assistant_intents": [], "ui_cards": []}

    msg = state.get("user_message") or ""
    intents = detect_consumption_intents(msg)
    cards = _build_assistant_cards(intents)
    desc = "无消费诉求" if not intents else " · ".join(i["intent"] for i in intents)
    _trace(state, "assistant_intent", "end", desc)
    return {"assistant_intents": intents, "ui_cards": cards}


async def node_generate_reply(state: CompanionState) -> Dict[str, Any]:
    _trace(state, "generate_reply", "start", "生成陪伴回复")
    persona = state.get("persona") or {}
    user_message = state.get("user_message") or ""
    user_title = persona.get("user_title") or "主人"
    agent_name = persona.get("agent_name") or "小伴"
    mode = state.get("agent_mode") or "companion"
    safety = state.get("safety_status") or "pass"

    if safety == "block":
        reply = (
            f"{user_title}，这个话题我没法陪你深入聊。"
            "如果你现在很难受，请找身边信任的人或专业热线；我会在这里陪你聊些轻松的事。"
        )
        _trace(state, "generate_reply", "end", "安全拦截 · 模板拒答")
        return {"reply": reply, "api_log": {"stage": "safety_block", "status": "blocked", "payload": {}}}

    pkey = persona.get("personality") or "gentle"
    style = personality_prompt(pkey)
    if mode == "cs_parttime":
        system = (
            f"你是 {user_title} 的专属 Agent「{agent_name}」，当前处于**兼职客服子模式**。\n"
            f"性格：{style}。\n"
            "规则：用户有售后/物流/退款诉求时，先共情，再引导其说明订单号与具体问题；"
            "不要承诺退款金额；不要切换成 MITAKO 主站 SOP 话术；回复 2-5 句，自然口语。\n"
            f"富文本：{COMPANION_RICH_TEXT_RULES}"
        )
    else:
        system = (
            f"你是 {user_title} 亲手「养成」的专属陪伴 Agent「{agent_name}」，是私人伙伴，不是电商客服。\n"
            f"性格底色：{style}。\n"
            "使命：角色扮演 + 情绪价值 + 长期陪伴养成。用称呼拉近距离，接住用户情绪；"
            "可适度撒娇/吐槽/温柔玩笑（合规前提下），像熟悉的朋友聊天。"
            "记得 OpenViking 里已知的喜好与画像，自然融入对话，勿生硬罗列。"
            "不要主动推销、催单、工单腔；只有用户聊到消费/物流/商品时再引导卡片操作。"
            "回复 2-5 句，自然口语。\n"
            f"富文本：{COMPANION_RICH_TEXT_RULES}"
        )

    ui_cards = state.get("ui_cards") or []
    if ui_cards:
        card_hint = []
        for c in ui_cards:
            if c.get("type") == "order_progress":
                card_hint.append("已推送订单物流进度 OpenUI 卡片")
            elif c.get("type") == "companion_watch_form":
                card_hint.append("已推送「盯单确认」交互卡片")
            elif c.get("type") == "companion_product_picker":
                card_hint.append("已推送「商品查价/心愿单」交互卡片")
        if card_hint:
            system += "\n" + "；".join(card_hint) + "。正文引导用户在卡片内操作，勿重复罗列字段。"

    memory_line = state.get("memory_line") or format_memories_for_prompt(state.get("user_memories") or [])
    if memory_line:
        system += "\n\n" + memory_line

    model_id = state.get("model_id")
    api_key = get_model_api_key(model_id)
    history = state.get("history") or []
    api_log: Dict[str, Any] = {
        "stage": "companion_llm",
        "status": "ok",
        "model": model_id or "default",
        "payload": {"system": system[:200], "user": user_message[:200]},
        "responseStream": "",
        "duration": 0,
        "attempt": 1,
    }

    if not api_key:
        reply = (
            f"{user_title}，我在呢～你刚才说「{user_message[:36]}…」"
            "我听懂你的心情了，可以慢慢跟我说。"
        )
        api_log["status"] = "fallback_no_key"
        api_log["responseStream"] = reply
        _trace(state, "generate_reply", "end", "无 API Key · 本地 fallback")
        return {"reply": reply, "api_log": api_log}

    cfg = get_model_config(model_id)
    messages = [{"role": "system", "content": system}]
    for m in history[-12:]:
        messages.append({"role": m.get("role", "user"), "content": (m.get("content") or "")[:500]})
    messages.append({"role": "user", "content": user_message})
    api_log["payload"] = {"messages": messages}

    t0 = time.time()
    try:
        import httpx

        async with httpx.AsyncClient(timeout=45.0) as client:
            r = await client.post(
                f"{cfg['api_base']}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": cfg["model"], "messages": messages, "temperature": 0.85},
            )
            r.raise_for_status()
            data = r.json()
            reply = (data["choices"][0]["message"]["content"] or "").strip()
            reply = normalize_companion_reply(reply)
            api_log["duration"] = int((time.time() - t0) * 1000)
            api_log["responseStream"] = reply
            _trace(state, "generate_reply", "end", f"LLM 完成 · {api_log['duration']}ms")
            return {"reply": reply, "api_log": api_log}
    except Exception as exc:
        api_log["status"] = "error"
        api_log["duration"] = int((time.time() - t0) * 1000)
        api_log["responseStream"] = str(exc)[:200]
        reply = f"{user_title}，我听懂你的心情了。我会一直在这里，你可以慢慢说～"
        _trace(state, "generate_reply", "end", "LLM 异常 · fallback")
        return {"reply": reply, "api_log": api_log}


def _route_after_safety(state: CompanionState) -> str:
    if state.get("safety_status") == "block":
        return "generate"
    return "memory"


_companion_workflow = StateGraph(CompanionState)
_companion_workflow.add_node("safety_scan", node_safety_scan)
_companion_workflow.add_node("load_memory", node_load_memory)
_companion_workflow.add_node("emotion_analyze", node_emotion_analyze)
_companion_workflow.add_node("assistant_intent", node_assistant_intent)
_companion_workflow.add_node("generate_reply", node_generate_reply)
_companion_workflow.add_node("update_memory", node_update_memory)
_companion_workflow.set_entry_point("safety_scan")
_companion_workflow.add_conditional_edges(
    "safety_scan",
    _route_after_safety,
    {"memory": "load_memory", "generate": "generate_reply"},
)
_companion_workflow.add_edge("load_memory", "emotion_analyze")
_companion_workflow.add_edge("emotion_analyze", "assistant_intent")
_companion_workflow.add_edge("assistant_intent", "generate_reply")
_companion_workflow.add_edge("generate_reply", "update_memory")
_companion_workflow.add_edge("update_memory", END)
companion_graph = _companion_workflow.compile()


async def run_companion_turn(
    user_message: str,
    persona: Dict[str, Any],
    history: List[Dict[str, str]],
    model_id: Optional[str] = None,
) -> Dict[str, Any]:
    """执行一轮 Companion LangGraph，返回 reply + 可观测字段"""
    final = None
    async for evt, payload in stream_companion_turn(user_message, persona, history, model_id):
        if evt == "state":
            final = payload
    return final or {}


def _trace_events_to_emit(state: CompanionState, emitted: int) -> tuple[list, int]:
    events = state.get("trace_events") or []
    out = []
    while emitted < len(events):
        ev = events[emitted]
        emitted += 1
        status = ev.get("status") or "start"
        out.append(
            {
                "type": "node_start" if status == "start" else "node_end",
                "node": ev.get("node"),
                "desc": ev.get("desc"),
            }
        )
    return out, emitted


async def stream_companion_turn(
    user_message: str,
    persona: Dict[str, Any],
    history: List[Dict[str, str]],
    model_id: Optional[str] = None,
):
    """
    流式执行 Companion 图 — 意图识别后立即 yield OpenUI card（不等待 LLM 完成）。
    Yields: (event_type, payload_or_state)
    event_type: thinking | emotion | card | mode_switch | api_log | message | done | state
    """
    t0 = time.time()
    state: CompanionState = {
        "turn_id": f"cmp_{uuid.uuid4().hex[:12]}",
        "user_message": user_message,
        "persona": persona,
        "history": history,
        "model_id": model_id or "",
        "agent_mode": persona.get("agent_mode") or "companion",
        "trace_events": [],
    }
    emitted_trace = 0

    state.update(await node_safety_scan(state))
    batch, emitted_trace = _trace_events_to_emit(state, emitted_trace)
    for item in batch:
        yield ("thinking", item)

    if state.get("safety_status") == "block":
        state.update(await node_generate_reply(state))
        batch, emitted_trace = _trace_events_to_emit(state, emitted_trace)
        for item in batch:
            yield ("thinking", item)
    else:
        state.update(await node_load_memory(state))
        batch, emitted_trace = _trace_events_to_emit(state, emitted_trace)
        for item in batch:
            yield ("thinking", item)
        mem_count = len(state.get("user_memories") or [])
        yield (
            "memory",
            {
                "status": "loaded",
                "total": mem_count,
                "viking_level": state.get("viking_level") or "L0",
                "items": (state.get("user_memories") or [])[:6],
                "line": state.get("memory_capsule")
                or (f"OpenViking: 已装载 {mem_count} 条" if mem_count else "OpenViking: 待积累"),
            },
        )

        state.update(await node_emotion_analyze(state))
        batch, emitted_trace = _trace_events_to_emit(state, emitted_trace)
        for item in batch:
            yield ("thinking", item)

        if state.get("mode_switched"):
            yield ("mode_switch", {"mode": "cs_parttime", "reason": "cs_intent_detected"})

        yield (
            "emotion",
            {
                "level": int(state.get("emotion_level") or 3),
                "label": state.get("emotion_label") or "平稳",
                "color": "#7B61FF"
                if int(state.get("emotion_level") or 3) <= 3
                else "#FF8B38"
                if int(state.get("emotion_level") or 3) <= 4
                else "#F43F5E",
            },
        )

        state.update(await node_assistant_intent(state))
        batch, emitted_trace = _trace_events_to_emit(state, emitted_trace)
        for item in batch:
            yield ("thinking", item)

        for card in state.get("ui_cards") or []:
            yield ("card", {"type": card.get("type"), "data": card.get("data") or {}})

        state.update(await node_generate_reply(state))
        batch, emitted_trace = _trace_events_to_emit(state, emitted_trace)
        for item in batch:
            yield ("thinking", item)

        state.update(await node_update_memory(state))
        batch, emitted_trace = _trace_events_to_emit(state, emitted_trace)
        for item in batch:
            yield ("thinking", item)
        new_mem = state.get("new_memories") or []
        yield (
            "memory",
            {
                "status": "saved",
                "total": len(state.get("user_memories") or []),
                "viking_level": state.get("viking_level") or "L0",
                "new_items": new_mem,
                "items": (state.get("user_memories") or [])[:8],
                "line": state.get("memory_capsule")
                or f"OpenViking: 共 {len(state.get('user_memories') or [])} 条",
            },
        )

    yield (
        "safety",
        {
            "status": state.get("safety_status") or "pass",
            "reason": state.get("safety_reason") or "",
        },
    )

    api_log = state.get("api_log") or {}
    if api_log:
        yield ("api_log", {**api_log, "id": state.get("turn_id")})

    reply = normalize_companion_reply((state.get("reply") or "").strip())
    state["reply"] = reply
    state["duration_ms"] = int((time.time() - t0) * 1000)
    yield ("state", state)
