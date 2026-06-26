# -*- coding: utf-8
"""IM 同步 — handoff 事件推送到 Chatwoot"""
from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, Optional

import handoff_store as store
from handoff_backend import chatwoot_client
from logging_utils import log_event


def backend_mode() -> str:
    return os.getenv("HANDOFF_BACKEND", "sqlite").strip().lower()


def should_sync_im() -> bool:
    mode = backend_mode()
    return mode in ("chatwoot", "hybrid") and chatwoot_client.is_configured()


def _get_external_id(session_id: str) -> Optional[str]:
    sess = store.get_session(session_id)
    if not sess:
        return None
    brief = sess.get("brief") or {}
    return brief.get("chatwoot_conversation_id")


def _save_external_id(session_id: str, conversation_id: str) -> None:
    store.patch_brief(session_id, {"chatwoot_conversation_id": conversation_id})


def sync_handoff_created(session_id: str, entry: Dict[str, Any]) -> None:
    if not should_sync_im():
        return

    if chatwoot_client.is_mock():
        ext_id = f"cw_mock_{session_id}"
        store.patch_brief(session_id, {"chatwoot_conversation_id": ext_id})
        log_event("chatwoot_conversation_created", session_id=session_id, conversation_id=ext_id, mode="mock")
        return

    async def _run():
        brief = entry.get("brief") or {}
        summary = brief.get("summary") or entry.get("reason") or "handoff"
        result = await chatwoot_client.create_conversation(
            session_id=session_id,
            user_id=entry.get("user_id") or "",
            brief_summary=str(summary)[:500],
        )
        if result.get("ok") and result.get("conversation_id"):
            _save_external_id(session_id, result["conversation_id"])
            log_event("chatwoot_conversation_created", session_id=session_id, conversation_id=result["conversation_id"])
        else:
            log_event("chatwoot_sync_failed", session_id=session_id, detail=str(result)[:200])

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_run())
    except RuntimeError:
        asyncio.run(_run())


def sync_message(session_id: str, role: str, content: str) -> None:
    if not should_sync_im():
        return
    ext = _get_external_id(session_id)
    if not ext:
        return
    msg_type = "incoming" if role == "user" else "outgoing"

    async def _run():
        await chatwoot_client.post_message(ext, content, msg_type)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_run())
    except RuntimeError:
        asyncio.run(_run())
