# -*- coding: utf-8 -*-
"""Companion API — /api/v2/companion/*"""
from __future__ import annotations

import json
import time
import asyncio

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

import companion_store as store
from auth.companion_guard import verify_companion_session, verify_companion_user
from auth.jwt_utils import companion_auth_required, create_companion_token
from auth.middleware import require_roles
from auth.roles import COMPANION_DESK_ROLES
from companion_graph import run_companion_turn, stream_companion_turn
from companion_mode import detect_cs_parttime_intent
from companion_obs_bus import publish_obs_event_sync, subscribe, unsubscribe
from companion_orders import list_companion_orders
from companion_tools import execute_tool
from companion_adventure import (
    is_exit_command,
    parse_enter_command,
    stream_adventure_turn,
)
from companion_adventure_context import generate_world_bible_llm, maybe_compress_history_summary
from companion_adventure_visual import (
    asset_captions_for_context,
    ensure_opening_visual_assets,
    generate_turn_illustration,
)
from companion_richtext import parse_adventure_content
from companion_adventure_reviewer import review_to_safety_status
from companion_persona_reviewer import review_persona_fields
from companion_share import list_share_catalog

companion_router = APIRouter(prefix="/api/v2/companion", tags=["companion"])


class PersonaBody(BaseModel):
    agent_name: str
    user_title: str = "主人"
    relationship: str = "搭档"
    personality: str = "gentle"
    onboarded: bool = True
    phone: str = ""
    model_id: Optional[str] = None


class ChatBody(BaseModel):
    user_id: str
    message: str
    model_id: str = "deepseek-v4-flash"


class WatchBody(BaseModel):
    user_id: str
    order_id: str
    notify_on: str = "status_change"


class WishlistBody(BaseModel):
    user_id: str
    product_id: str
    note: str = ""


class HandoffBody(BaseModel):
    user_id: str
    reason: str = ""


class HandoffReplyBody(BaseModel):
    content: str
    operator: str = "companion_ops"


class HandoffAcceptBody(BaseModel):
    operator: str = "companion_ops"


class ModeBody(BaseModel):
    mode: str = "companion"


class ToolActionBody(BaseModel):
    user_id: str
    action: str
    payload: dict = {}


class AdventureStartBody(BaseModel):
    user_id: str
    world_setting: str
    world_title: str = ""
    model_id: str = "deepseek-v4-flash"


class AdventureChatBody(BaseModel):
    user_id: str
    message: str
    model_id: str = "deepseek-v4-flash"


class AdventureResetBody(BaseModel):
    user_id: str
    mode: str = "messages"  # messages | chapter


def _tenant_id(user: dict) -> str:
    return user.get("tenant_id") or "mitako"


def _obs_emit(event: str, tenant_id: str, user_id: str, **extra) -> None:
    publish_obs_event_sync(event, {"tenant_id": tenant_id, "user_id": user_id, **extra})


def _adventure_stream_events(tid: str, user_id: str, evt: str, payload: dict):
    """冒险 SSE 中间事件 — 不含 message（由落库后统一推送）"""
    if evt == "safety":
        st = payload.get("status") or "pass"
        if st in ("flag", "block"):
            _obs_emit(
                "safety_alert",
                tid,
                user_id,
                safety_status=st,
                reason=payload.get("reason"),
                mode="adventure",
                review_code=(payload.get("review") or {}).get("code"),
            )
        return {"event": "safety", "data": json.dumps(payload, ensure_ascii=False)}
    if evt == "review":
        return {"event": "review", "data": json.dumps(payload, ensure_ascii=False)}
    if evt == "card":
        return {"event": "card", "data": json.dumps(payload, ensure_ascii=False)}
    if evt == "api_log":
        return {"event": "api_log", "data": json.dumps(payload, ensure_ascii=False)}
    if evt == "choices":
        return {"event": "choices", "data": json.dumps(payload, ensure_ascii=False)}
    if evt == "chunk":
        return {"event": "chunk", "data": json.dumps(payload, ensure_ascii=False)}
    visual_events = {
        "bible_ready", "visual_generating", "visual_asset_ready", "visual_asset_failed",
        "illust_queued", "illust_generating", "illust_ready", "illust_failed", "illust_skipped",
    }
    if evt in visual_events:
        return {"event": evt, "data": json.dumps(payload, ensure_ascii=False)}
    return None


def _message_payload(
    saved_id: int,
    display: str,
    choices: list,
    parsed: dict,
    illust_status: str = "none",
) -> dict:
    payload = {
        "role": "assistant",
        "content": display,
        "id": saved_id,
        "choices": choices,
        "mode": "adventure",
    }
    if parsed.get("inner"):
        payload["inner"] = parsed["inner"]
    if parsed.get("dialogues"):
        payload["dialogues"] = parsed["dialogues"]
    if parsed.get("tts_plain"):
        payload["tts_plain"] = parsed["tts_plain"]
    if parsed.get("illust") or illust_status != "none":
        payload["illust"] = {"status": illust_status, **(parsed.get("illust") or {})}
    return payload


def _save_adventure_turn_trace(
    tid: str,
    user_id: str,
    result: dict,
    user_message: str,
    display: str,
    saved_id: int,
) -> None:
    """冒险回合写入观测 trace — 供双看板统计"""
    output_review = result.get("output_review") or {}
    input_review = result.get("input_review") or {}
    review = output_review or input_review or {}
    safety = review_to_safety_status(review)
    duration_ms = int(result.get("duration_ms") or 0)
    illust = (result.get("parsed") or {}).get("illust")
    turn_id = result.get("turn_id") or f"adv_msg_{saved_id}"
    api_log = {
        "mode": "adventure",
        "duration_ms": duration_ms,
        "has_illust": bool(illust),
        "cost_est_usd": round(0.002 + (0.04 if illust else 0.0), 4),
        "input_review": input_review,
        "output_review": output_review,
    }
    store.save_turn_trace(
        {
            "turn_id": turn_id,
            "user_id": user_id,
            "tenant_id": tid,
            "user_message": user_message or "",
            "assistant_reply": display,
            "emotion_level": 3,
            "emotion_label": "沉浸",
            "safety_status": safety,
            "safety_reason": review.get("reason") or "",
            "agent_mode": "adventure",
            "duration_ms": duration_ms,
            "graph_trace": [{"node": "adventure_narrative", "status": "ok"}],
            "api_log": api_log,
        }
    )
    _obs_emit("turn_complete", tid, user_id, turn_id=turn_id, agent_mode="adventure")


async def _run_turn_visuals(
    tid: str,
    user_id: str,
    tenant_id: str,
    persona: dict,
    bible: dict,
    saved_id: int,
    parsed: dict,
    *,
    is_opening: bool = False,
):
    """配图 SSE 事件生成器"""
    scene_key = parsed.get("scene_key") or ""
    if is_opening:
        async for evt, payload in ensure_opening_visual_assets(
            user_id, tenant_id, persona, bible, scene_key, scene_hint=bible.get("world_setting", "")
        ):
            if evt == "visual_asset_ready":
                _obs_emit("visual_asset_ready", tid, user_id, **payload)
            yield evt, payload

    illust = parsed.get("illust")
    if illust:
        async for evt, payload in generate_turn_illustration(
            user_id, tenant_id, saved_id, bible, scene_key, illust
        ):
            if evt.startswith("illust") or evt == "api_log":
                if evt == "api_log":
                    pass
            yield evt, {**payload, "message_id": payload.get("message_id", saved_id)}


def _maybe_token(user_id: str, tenant_id: str = "mitako") -> dict:
    if not companion_auth_required():
        return {}
    return {"companion_token": create_companion_token(user_id, tenant_id)}


@companion_router.get("/persona/{user_id}")
async def get_persona(user_id: str, request: Request):
    cu = verify_companion_user(request, user_id, allow_bootstrap=True)
    tid = _tenant_id(cu)
    p = store.get_persona(user_id, tid)
    if not p:
        return {"ok": True, "persona": None}
    return {"ok": True, "persona": p}


@companion_router.put("/persona/{user_id}")
async def put_persona(user_id: str, body: PersonaBody, request: Request):
    cu = verify_companion_user(request, user_id, allow_bootstrap=True)
    tid = _tenant_id(cu)
    payload = body.model_dump()
    review, err_msg = await review_persona_fields(payload, body.model_id)
    if err_msg:
        raise HTTPException(status_code=400, detail=err_msg)
    try:
        p = store.upsert_persona(user_id, payload, tenant_id=tid)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    resp = {"ok": True, "persona": p, "persona_review": review}
    if body.onboarded:
        resp.update(_maybe_token(user_id, tid))
    return resp


@companion_router.get("/messages/{user_id}")
async def get_messages(user_id: str, request: Request, limit: int = 50, before_id: int = 0):
    cu = verify_companion_user(request, user_id)
    tid = _tenant_id(cu)
    msgs = store.list_messages(user_id, limit=min(limit, 100), before_id=before_id, tenant_id=tid)
    return {"ok": True, "messages": msgs}


@companion_router.delete("/messages/{user_id}")
async def clear_messages(user_id: str, request: Request):
    """清空用户聊天记录（保留 trace / 记忆）"""
    cu = verify_companion_user(request, user_id)
    tid = _tenant_id(cu)
    deleted = store.clear_messages(user_id, tenant_id=tid)
    store.clear_live_session(user_id, tenant_id=tid)
    return {"ok": True, "deleted": deleted}


@companion_router.get("/memory/{user_id}")
async def get_memory(user_id: str, request: Request, limit: int = 30):
    cu = verify_companion_user(request, user_id)
    tid = _tenant_id(cu)
    summary = store.memory_summary(user_id, tenant_id=tid)
    return {"ok": True, **summary}


@companion_router.put("/persona/{user_id}/mode")
async def put_persona_mode(user_id: str, body: ModeBody, request: Request):
    cu = verify_companion_user(request, user_id)
    tid = _tenant_id(cu)
    p = store.set_agent_mode(user_id, body.mode, tenant_id=tid)
    if not p:
        raise HTTPException(status_code=404, detail="persona_not_found")
    return {"ok": True, "persona": p}


@companion_router.post("/chat")
async def companion_chat(body: ChatBody, request: Request):
    cu = verify_companion_user(request, body.user_id)
    tid = _tenant_id(cu)
    persona = store.get_persona(body.user_id, tid)
    if not persona or not persona.get("onboarded"):
        raise HTTPException(status_code=400, detail="onboarding_required")

    user_msg = (body.message or "").strip()
    if not user_msg:
        raise HTTPException(status_code=400, detail="empty_message")

    store.append_message(body.user_id, "user", user_msg, tenant_id=tid)
    history_rows = store.list_messages(body.user_id, limit=20, tenant_id=tid)
    history = [{"role": m["role"], "content": m["content"]} for m in history_rows[:-1]]
    persona_ctx = {**persona, "user_id": body.user_id, "tenant_id": tid}
    msg_count = store.count_messages(body.user_id, tenant_id=tid)
    turn_count = store.count_turns(body.user_id, tenant_id=tid) + 1

    store.touch_live_session(
        body.user_id,
        tid,
        {
            "status": "streaming",
            "last_user_snippet": user_msg[:80],
            "message_count": msg_count,
            "turn_count": turn_count,
            "emotion_level": 3,
            "emotion_label": "分析中",
            "agent_name": persona.get("agent_name") or "",
            "phone": persona.get("phone") or "",
        },
    )
    _obs_emit("live_update", tid, body.user_id, status="streaming")

    async def gen():
        result = None
        async for evt, payload in stream_companion_turn(user_msg, persona_ctx, history, body.model_id):
            if evt == "thinking":
                yield {"event": "thinking", "data": json.dumps(payload, ensure_ascii=False)}
            elif evt == "memory":
                if payload.get("status") == "saved":
                    _obs_emit(
                        "memory_update",
                        tid,
                        body.user_id,
                        total=payload.get("total"),
                        new_count=len(payload.get("new_items") or []),
                    )
                yield {"event": "memory", "data": json.dumps(payload, ensure_ascii=False)}
            elif evt == "mode_switch":
                store.set_agent_mode(body.user_id, "cs_parttime", tenant_id=tid)
                yield {"event": "mode_switch", "data": json.dumps(payload, ensure_ascii=False)}
            elif evt == "emotion":
                level = int(payload.get("level") or 3)
                store.touch_live_session(
                    body.user_id,
                    tid,
                    {
                        "emotion_level": level,
                        "emotion_label": payload.get("label") or "平稳",
                        "status": "streaming",
                    },
                )
                if level >= 4:
                    _obs_emit(
                        "live_update",
                        tid,
                        body.user_id,
                        emotion_level=level,
                        emotion_label=payload.get("label"),
                        important=True,
                    )
                else:
                    _obs_emit("live_update", tid, body.user_id, emotion_level=level)
                yield {"event": "emotion", "data": json.dumps(payload, ensure_ascii=False)}
            elif evt == "card":
                yield {"event": "card", "data": json.dumps(payload, ensure_ascii=False)}
            elif evt == "safety":
                st = payload.get("status") or "pass"
                if st in ("flag", "block"):
                    _obs_emit("safety_alert", tid, body.user_id, safety_status=st, reason=payload.get("reason"))
                yield {"event": "safety", "data": json.dumps(payload, ensure_ascii=False)}
            elif evt == "api_log":
                yield {"event": "api_log", "data": json.dumps(payload, ensure_ascii=False)}
            elif evt == "state":
                result = payload

        if not result:
            return

        emotion_level = int(result.get("emotion_level") or 3)
        emotion_label = result.get("emotion_label") or "平稳"
        safety_status = result.get("safety_status") or "pass"
        reply = (result.get("reply") or "").strip()
        saved = store.append_message(body.user_id, "assistant", reply, tenant_id=tid)
        store.save_turn_trace(
            {
                "turn_id": result.get("turn_id") or saved["id"],
                "user_id": body.user_id,
                "tenant_id": tid,
                "user_message": user_msg,
                "assistant_reply": reply,
                "emotion_level": emotion_level,
                "emotion_label": emotion_label,
                "safety_status": safety_status,
                "safety_reason": result.get("safety_reason") or "",
                "agent_mode": result.get("agent_mode") or persona.get("agent_mode") or "companion",
                "duration_ms": result.get("duration_ms") or 0,
                "graph_trace": result.get("trace_events") or [],
                "api_log": result.get("api_log") or {},
            }
        )

        yield {
            "event": "message",
            "data": json.dumps({"role": "assistant", "content": reply, "id": saved["id"]}, ensure_ascii=False),
        }
        yield {"event": "done", "data": json.dumps({"turn_id": result.get("turn_id")}, ensure_ascii=False)}

        store.touch_live_session(
            body.user_id,
            tid,
            {
                "status": "idle",
                "last_assistant_snippet": (reply or "")[:80],
                "message_count": store.count_messages(body.user_id, tenant_id=tid),
                "turn_count": turn_count,
                "emotion_level": emotion_level,
                "emotion_label": emotion_label,
            },
        )
        _obs_emit(
            "turn_complete",
            tid,
            body.user_id,
            turn_id=result.get("turn_id"),
            emotion_level=emotion_level,
            emotion_label=emotion_label,
            safety_status=safety_status,
        )
        if safety_status in ("flag", "block") or emotion_level >= 4:
            _obs_emit(
                "safety_alert",
                tid,
                body.user_id,
                turn_id=result.get("turn_id"),
                emotion_level=emotion_level,
                safety_status=safety_status,
            )

    return EventSourceResponse(gen())


# —— 对话式冒险模式（独立记忆，不与日常 companion 互通）——

@companion_router.get("/adventure/session/{user_id}")
async def get_adventure_session(user_id: str, request: Request):
    cu = verify_companion_user(request, user_id)
    tid = _tenant_id(cu)
    sess = store.get_adventure_session(user_id, tenant_id=tid)
    return {"ok": True, "session": sess}


@companion_router.get("/adventure/messages/{user_id}")
async def get_adventure_messages(user_id: str, request: Request, limit: int = 80):
    cu = verify_companion_user(request, user_id)
    tid = _tenant_id(cu)
    msgs = store.list_adventure_messages(user_id, tenant_id=tid, limit=min(limit, 100))
    return {"ok": True, "messages": msgs}


@companion_router.delete("/adventure/messages/{user_id}")
async def clear_adventure_messages(user_id: str, request: Request):
    """清空冒险模式聊天记录（不影响日常陪伴消息与 OpenViking 记忆）"""
    cu = verify_companion_user(request, user_id)
    tid = _tenant_id(cu)
    deleted = store.clear_adventure_messages(user_id, tenant_id=tid)
    return {"ok": True, "deleted": deleted}


@companion_router.post("/adventure/reset-context")
async def reset_adventure_context(body: AdventureResetBody, request: Request):
    """
    Talkie 式分档清除冒险上下文。
    mode=messages — 仅清对话；mode=chapter — 清对话 + 前情摘要（保留世界观 Bible）。
    """
    cu = verify_companion_user(request, body.user_id)
    tid = _tenant_id(cu)
    mode = (body.mode or "messages").strip().lower()
    if mode not in ("messages", "chapter", "memory", "summary"):
        raise HTTPException(status_code=400, detail="invalid_reset_mode")
    result = store.reset_adventure_context(body.user_id, mode=mode, tenant_id=tid)
    return {"ok": True, **result}


@companion_router.post("/adventure/exit")
async def exit_adventure(body: ChatBody, request: Request):
    cu = verify_companion_user(request, body.user_id)
    tid = _tenant_id(cu)
    ended = store.end_adventure_session(body.user_id, tenant_id=tid)
    return {"ok": True, "ended": ended}


@companion_router.get("/share/catalog")
async def share_catalog(request: Request, limit: int = 20):
    verify_companion_session(request)
    return {"ok": True, **list_share_catalog(limit=min(limit, 30))}


@companion_router.get("/adventure/bible/{user_id}")
async def get_adventure_bible(user_id: str, request: Request):
    cu = verify_companion_user(request, user_id)
    tid = _tenant_id(cu)
    row = store.get_adventure_bible(user_id, tenant_id=tid)
    return {"ok": True, "bible": row}


@companion_router.get("/adventure/assets/{user_id}")
async def get_adventure_assets(user_id: str, request: Request, limit: int = 30):
    cu = verify_companion_user(request, user_id)
    tid = _tenant_id(cu)
    assets = store.list_visual_assets(user_id, tenant_id=tid, limit=min(limit, 50))
    return {"ok": True, "assets": assets}


@companion_router.post("/adventure/start")
async def start_adventure(body: AdventureStartBody, request: Request):
    cu = verify_companion_user(request, body.user_id)
    tid = _tenant_id(cu)
    persona = store.get_persona(body.user_id, tid)
    if not persona or not persona.get("onboarded"):
        raise HTTPException(status_code=400, detail="onboarding_required")

    world = (body.world_setting or "").strip() or "自由幻想世界"
    title = (body.world_title or world[:24]).strip()
    store.start_adventure_session(body.user_id, world, title, tenant_id=tid)
    persona_ctx = {**persona, "user_id": body.user_id, "tenant_id": tid}

    async def gen():
        sess = store.get_adventure_session(body.user_id, tenant_id=tid)
        yield {
            "event": "session",
            "data": json.dumps({"session": sess, "memory_isolated": True, "phase": "opening"}, ensure_ascii=False),
        }
        yield {
            "event": "loading",
            "data": json.dumps({"phase": "rift", "progress": 8, "world": world, "title": title}, ensure_ascii=False),
        }

        yield {
            "event": "loading",
            "data": json.dumps({"phase": "bible", "progress": 22, "world": world}, ensure_ascii=False),
        }
        bible_data = await generate_world_bible_llm(persona_ctx, world, title, body.model_id)
        store.upsert_adventure_bible(body.user_id, bible_data, world, tenant_id=tid)
        yield {
            "event": "loading",
            "data": json.dumps({"phase": "bible_done", "progress": 45, "world": world}, ensure_ascii=False),
        }
        yield {
            "event": "bible_ready",
            "data": json.dumps({"bible": bible_data, "world": world}, ensure_ascii=False),
        }

        yield {
            "event": "loading",
            "data": json.dumps({"phase": "narrative", "progress": 58, "world": world}, ensure_ascii=False),
        }

        result = None
        captions = asset_captions_for_context(body.user_id, tid)
        async for evt, payload in stream_adventure_turn(
            "",
            persona_ctx,
            [],
            world,
            title,
            body.model_id,
            is_opening=True,
            bible=bible_data,
            summary_text="",
            asset_captions=captions,
        ):
            if evt == "state":
                result = payload
                continue
            out = _adventure_stream_events(tid, body.user_id, evt, payload)
            if out:
                yield out

        if not result:
            return

        parsed = result.get("parsed") or parse_adventure_content(
            result.get("reply") or "",
            persona_ctx.get("agent_name", ""),
        )
        display = parsed.get("display") or result.get("reply") or ""
        choices = result.get("choices") or []
        inner_json = json.dumps(parsed.get("inner"), ensure_ascii=False) if parsed.get("inner") else None
        illust_status = "queued" if parsed.get("illust") else "none"
        saved_id = store.append_adventure_message(
            body.user_id,
            "assistant",
            result.get("raw_reply") or display,
            tenant_id=tid,
            choices=choices,
            display_content=display,
            inner_json=inner_json,
            illust_status=illust_status,
        )
        sess = store.get_adventure_session(body.user_id, tenant_id=tid)
        yield {
            "event": "session",
            "data": json.dumps({"session": sess, "memory_isolated": True}, ensure_ascii=False),
        }
        yield {
            "event": "message",
            "data": json.dumps(
                _message_payload(saved_id, display, choices, parsed, illust_status),
                ensure_ascii=False,
            ),
        }

        yield {
            "event": "loading",
            "data": json.dumps({"phase": "ready", "progress": 100, "world": world}, ensure_ascii=False),
        }
        yield {"event": "done", "data": json.dumps({"turn_id": result.get("turn_id"), "mode": "adventure"}, ensure_ascii=False)}

        _save_adventure_turn_trace(tid, body.user_id, result, "", display, saved_id)

        async for evt, payload in _run_turn_visuals(
            tid, body.user_id, tid, persona_ctx, bible_data, saved_id, parsed, is_opening=True
        ):
            out = _adventure_stream_events(tid, body.user_id, evt, payload)
            if out:
                yield out

    return EventSourceResponse(gen())


@companion_router.post("/adventure/chat")
async def adventure_chat(body: AdventureChatBody, request: Request):
    cu = verify_companion_user(request, body.user_id)
    tid = _tenant_id(cu)
    persona = store.get_persona(body.user_id, tid)
    if not persona or not persona.get("onboarded"):
        raise HTTPException(status_code=400, detail="onboarding_required")

    sess = store.get_adventure_session(body.user_id, tenant_id=tid)
    if not sess or not sess.get("active"):
        raise HTTPException(status_code=400, detail="adventure_not_active")

    user_msg = (body.message or "").strip()
    if not user_msg:
        raise HTTPException(status_code=400, detail="empty_message")

    if is_exit_command(user_msg):
        store.end_adventure_session(body.user_id, tenant_id=tid)

        async def exit_gen():
            yield {
                "event": "adventure_exit",
                "data": json.dumps({"ok": True, "message": "已退出冒险模式，回到日常陪伴。"}, ensure_ascii=False),
            }
            yield {"event": "done", "data": "{}"}

        return EventSourceResponse(exit_gen())

    store.append_adventure_message(body.user_id, "user", user_msg, tenant_id=tid)
    history_rows = store.list_adventure_messages(body.user_id, tenant_id=tid, limit=40)
    history = [{"role": m["role"], "content": m["content"]} for m in history_rows[:-1]]
    persona_ctx = {**persona, "user_id": body.user_id, "tenant_id": tid}
    world = sess.get("world_setting") or ""
    title = sess.get("world_title") or ""

    bible_row = store.get_adventure_bible(body.user_id, tenant_id=tid) or {}
    bible = bible_row.get("bible") or {}
    summary = bible_row.get("summary_text") or ""
    summary = await maybe_compress_history_summary(history, summary, persona_ctx, body.model_id)
    if summary != bible_row.get("summary_text"):
        store.update_adventure_summary(body.user_id, summary, tenant_id=tid)
    captions = asset_captions_for_context(body.user_id, tid)

    async def gen():
        result = None
        async for evt, payload in stream_adventure_turn(
            user_msg,
            persona_ctx,
            history,
            world,
            title,
            body.model_id,
            bible=bible,
            summary_text=summary,
            asset_captions=captions,
        ):
            if evt == "state":
                result = payload
                continue
            out = _adventure_stream_events(tid, body.user_id, evt, payload)
            if out:
                yield out

        if not result:
            return

        parsed = result.get("parsed") or parse_adventure_content(
            result.get("reply") or "",
            persona_ctx.get("agent_name", ""),
        )
        display = parsed.get("display") or result.get("reply") or ""
        choices = result.get("choices") or []
        inner_json = json.dumps(parsed.get("inner"), ensure_ascii=False) if parsed.get("inner") else None
        illust_status = "queued" if parsed.get("illust") else "none"
        saved_id = store.append_adventure_message(
            body.user_id,
            "assistant",
            result.get("raw_reply") or display,
            tenant_id=tid,
            choices=choices,
            display_content=display,
            inner_json=inner_json,
            illust_status=illust_status,
        )
        yield {
            "event": "message",
            "data": json.dumps(
                _message_payload(saved_id, display, choices, parsed, illust_status),
                ensure_ascii=False,
            ),
        }

        yield {"event": "done", "data": json.dumps({"turn_id": result.get("turn_id"), "mode": "adventure"}, ensure_ascii=False)}

        _save_adventure_turn_trace(tid, body.user_id, result, user_msg, display, saved_id)

        async for evt, payload in _run_turn_visuals(
            tid, body.user_id, tid, persona_ctx, bible, saved_id, parsed, is_opening=False
        ):
            out = _adventure_stream_events(tid, body.user_id, evt, payload)
            if out:
                yield out

    return EventSourceResponse(gen())


@companion_router.get("/orders/{user_id}")
async def companion_orders(user_id: str, request: Request):
    verify_companion_user(request, user_id, allow_bootstrap=True)
    orders = list_companion_orders(user_id)
    return {"ok": True, "orders": orders, "total": len(orders)}


@companion_router.post("/tools/action")
async def companion_tool_action(body: ToolActionBody, request: Request):
    """OpenUI 卡片交互 → 服务端 Tool 执行（盯单 / 查价 / 心愿单）"""
    cu = verify_companion_user(request, body.user_id)
    tid = _tenant_id(cu)
    result = execute_tool(body.action, body.user_id, body.payload or {}, tenant_id=tid)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "tool_failed")
    return {"ok": True, "result": result}


@companion_router.get("/products/search")
async def search_products(request: Request, q: str = "", limit: int = 10):
    verify_companion_session(request)
    return {"ok": True, "products": store.search_products(q, limit=min(limit, 20))}


@companion_router.post("/watch/orders")
async def watch_order(body: WatchBody, request: Request):
    cu = verify_companion_user(request, body.user_id)
    tid = _tenant_id(cu)
    row = store.add_watch_order(body.user_id, body.order_id, body.notify_on, tenant_id=tid)
    return {"ok": True, "watch": row}


@companion_router.get("/watch/orders/{user_id}")
async def list_watch(user_id: str, request: Request):
    cu = verify_companion_user(request, user_id)
    tid = _tenant_id(cu)
    return {"ok": True, "orders": store.list_watch_orders(user_id, tenant_id=tid)}


@companion_router.post("/wishlist")
async def add_wishlist(body: WishlistBody, request: Request):
    cu = verify_companion_user(request, body.user_id)
    tid = _tenant_id(cu)
    row = store.add_wishlist(body.user_id, body.product_id, body.note, tenant_id=tid)
    return {"ok": True, "item": row}


@companion_router.get("/wishlist/{user_id}")
async def list_wishlist(user_id: str, request: Request):
    cu = verify_companion_user(request, user_id)
    tid = _tenant_id(cu)
    return {"ok": True, "items": store.list_wishlist(user_id, tenant_id=tid)}


@companion_router.post("/handoff/request")
async def companion_handoff_request(body: HandoffBody, request: Request):
    cu = verify_companion_user(request, body.user_id)
    tid = _tenant_id(cu)
    sess = store.create_handoff_session(body.user_id, body.reason, tenant_id=tid)
    return {"ok": True, "session": sess}


# —— 可观测后台（原 companion-desk 人工台已废弃，改为全局 Agent 观测）——

@companion_router.get("/observability/live")
async def companion_obs_live(user=require_roles(COMPANION_DESK_ROLES), max_age: int = 300):
    """实时活跃会话 — 供观测台按需拉取（主路径为 SSE 事件推送）"""
    tid = user.get("tenant_id") or "mitako"
    sessions = store.list_live_sessions(tenant_id=tid, max_age_sec=min(max_age, 600))
    return {"ok": True, "sessions": sessions, "server_time": time.time()}


@companion_router.get("/observability/stream")
async def companion_obs_stream(request: Request, user=require_roles(COMPANION_DESK_ROLES)):
    """观测台事件流 — 有重要数据变化时推送，非定时轮询"""
    tid = _tenant_id(user)

    async def gen():
        q = await subscribe()
        try:
            yield {"event": "connected", "data": json.dumps({"tenant_id": tid}, ensure_ascii=False)}
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=45.0)
                except asyncio.TimeoutError:
                    yield {"event": "heartbeat", "data": "{}"}
                    continue
                data = msg.get("data") or {}
                if data.get("tenant_id") not in (None, tid):
                    continue
                yield {
                    "event": msg.get("event") or "update",
                    "data": json.dumps(data, ensure_ascii=False),
                }
        finally:
            await unsubscribe(q)

    return EventSourceResponse(gen())


@companion_router.get("/observability/summary")
async def companion_obs_summary(user=require_roles(COMPANION_DESK_ROLES)):
    tid = user.get("tenant_id") or "mitako"
    return {"ok": True, "summary": store.observability_summary(tid, agent_mode="companion")}


@companion_router.get("/observability/adventure/summary")
async def companion_obs_adventure_summary(user=require_roles(COMPANION_DESK_ROLES)):
    tid = user.get("tenant_id") or "mitako"
    return {"ok": True, "summary": store.observability_adventure_summary(tid)}


@companion_router.get("/observability/traces")
async def companion_obs_traces(
    user=require_roles(COMPANION_DESK_ROLES),
    limit: int = 50,
    filter: str = "",
    user_id: str = "",
    q: str = "",
    agent_mode: str = "",
):
    tid = user.get("tenant_id") or "mitako"
    traces = store.list_turn_traces(
        tenant_id=tid,
        limit=limit,
        filter_type=filter,
        user_id=user_id,
        search_q=q,
        agent_mode=agent_mode or None,
    )
    return {"ok": True, "traces": traces}


@companion_router.get("/observability/users")
async def companion_obs_users(
    user=require_roles(COMPANION_DESK_ROLES),
    q: str = "",
    limit: int = 80,
):
    tid = user.get("tenant_id") or "mitako"
    users = store.list_observability_users(tenant_id=tid, search_q=q, limit=limit)
    return {"ok": True, "users": users}


@companion_router.get("/observability/users/{user_id}")
async def companion_obs_user_detail(user_id: str, user=require_roles(COMPANION_DESK_ROLES)):
    tid = user.get("tenant_id") or "mitako"
    detail = store.get_user_observability(user_id, tenant_id=tid)
    if not detail:
        raise HTTPException(status_code=404, detail="user_not_found")
    return {"ok": True, **detail}


@companion_router.get("/observability/traces/{turn_id}")
async def companion_obs_trace_detail(turn_id: str, user=require_roles(COMPANION_DESK_ROLES)):
    tid = user.get("tenant_id") or "mitako"
    trace = store.get_turn_trace(turn_id, tenant_id=tid)
    if not trace:
        raise HTTPException(status_code=404, detail="not_found")
    msgs = store.list_messages(trace["user_id"], limit=30, tenant_id=tid)
    return {"ok": True, "trace": trace, "messages": msgs}


@companion_router.get("/observability/users/{user_id}/messages")
async def companion_obs_user_messages(user_id: str, user=require_roles(COMPANION_DESK_ROLES), limit: int = 50):
    tid = user.get("tenant_id") or "mitako"
    return {"ok": True, "messages": store.list_messages(user_id, limit=min(limit, 100), tenant_id=tid)}


# 兼容旧 E2E 路径 — 返回 trace 列表而非人工队列
@companion_router.get("/desk/sessions")
async def companion_desk_sessions(user=require_roles(COMPANION_DESK_ROLES)):
    tid = user.get("tenant_id")
    traces = store.list_turn_traces(tenant_id=tid or "mitako", limit=30)
    sessions = [
        {
            "session_id": t["turn_id"],
            "user_id": t["user_id"],
            "status": "observed",
            "reason": t.get("emotion_label") or "",
            "safety_status": t.get("safety_status"),
            "created_at": t.get("created_at"),
        }
        for t in traces
    ]
    return {"ok": True, "sessions": sessions, "deprecated": True, "use": "/observability/traces"}


@companion_router.get("/desk/sessions/{session_id}")
async def companion_desk_session(session_id: str, user=require_roles(COMPANION_DESK_ROLES)):
    tid = user.get("tenant_id")
    trace = store.get_turn_trace(session_id, tenant_id=tid)
    if not trace:
        raise HTTPException(status_code=404, detail="not_found")
    return {"ok": True, "session": trace, "messages": store.list_messages(trace["user_id"], tenant_id=tid)}


@companion_router.post("/desk/sessions/{session_id}/accept")
async def companion_desk_accept(session_id: str, body: HandoffAcceptBody, user=require_roles(COMPANION_DESK_ROLES)):
    """已废弃：Companion 不提供人工接入"""
    raise HTTPException(status_code=410, detail="companion_human_desk_removed_use_observability")


@companion_router.post("/desk/sessions/{session_id}/reply")
async def companion_desk_reply(session_id: str, body: HandoffReplyBody, user=require_roles(COMPANION_DESK_ROLES)):
    raise HTTPException(status_code=410, detail="companion_human_desk_removed_use_observability")
