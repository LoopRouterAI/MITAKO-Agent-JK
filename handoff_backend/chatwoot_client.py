# -*- coding: utf-8 -*-
"""Chatwoot REST 客户端 — IM/工单对接"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

import httpx


def is_configured() -> bool:
    if os.getenv("CHATWOOT_MOCK", "0").strip().lower() in ("1", "true", "yes"):
        return True
    return bool(os.getenv("CHATWOOT_BASE_URL") and os.getenv("CHATWOOT_API_TOKEN"))


def is_mock() -> bool:
    return os.getenv("CHATWOOT_MOCK", "0").strip().lower() in ("1", "true", "yes")


def _base() -> str:
    return (os.getenv("CHATWOOT_BASE_URL") or "http://127.0.0.1:3000").rstrip("/")


def _headers() -> Dict[str, str]:
    token = os.getenv("CHATWOOT_API_TOKEN", "mock-token")
    return {"api_access_token": token, "Content-Type": "application/json"}


def _account_id() -> str:
    return os.getenv("CHATWOOT_ACCOUNT_ID", "1")


def _inbox_id() -> str:
    return os.getenv("CHATWOOT_INBOX_ID", "1")


async def health_check() -> Dict[str, Any]:
    if is_mock():
        return {"ok": True, "mode": "mock", "latency_ms": 0}
    if not is_configured():
        return {"ok": False, "mode": "disabled", "error": "not_configured"}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            t0 = __import__("time").time()
            r = await client.get(f"{_base()}/api/v1/accounts/{_account_id()}", headers=_headers())
            ms = int((__import__("time").time() - t0) * 1000)
            return {"ok": r.status_code < 400, "mode": "live", "status": r.status_code, "latency_ms": ms}
    except Exception as e:
        return {"ok": False, "mode": "live", "error": str(e)[:120]}


async def create_conversation(
    *,
    session_id: str,
    user_id: str,
    brief_summary: str = "",
) -> Dict[str, Any]:
    """创建 Chatwoot 会话并返回 external conversation id"""
    if is_mock():
        ext_id = f"cw_mock_{session_id}"
        return {"ok": True, "conversation_id": ext_id, "mode": "mock"}

    payload = {
        "source_id": session_id,
        "inbox_id": int(_inbox_id()),
        "contact": {"identifier": user_id, "name": user_id},
        "message": {"content": brief_summary or f"MITAKO handoff {session_id}"},
    }
    url = f"{_base()}/api/v1/accounts/{_account_id()}/conversations"
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(url, headers=_headers(), json=payload)
        if r.status_code >= 400:
            return {"ok": False, "status": r.status_code, "body": r.text[:200]}
        data = r.json()
        cid = data.get("id") or data.get("conversation_id")
        return {"ok": True, "conversation_id": str(cid), "mode": "live"}


async def post_message(conversation_id: str, content: str, message_type: str = "incoming") -> Dict[str, Any]:
    if is_mock():
        return {"ok": True, "mode": "mock"}
    url = f"{_base()}/api/v1/accounts/{_account_id()}/conversations/{conversation_id}/messages"
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(
            url,
            headers=_headers(),
            json={"content": content, "message_type": message_type},
        )
        return {"ok": r.status_code < 400, "status": r.status_code}
