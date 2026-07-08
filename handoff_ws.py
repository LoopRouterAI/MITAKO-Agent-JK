# -*- coding: utf-8 -*-
"""转VIP客服 WebSocket 推送 — 会话级订阅 + Redis 多实例广播"""
from __future__ import annotations

import asyncio
import json
import os
import threading
from typing import Any, Dict, Optional, Set

from fastapi import WebSocket

_REDIS_CHANNEL = "mitako:handoff:events"


class HandoffHub:
    def __init__(self) -> None:
        self._rooms: Dict[str, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()
        self._redis = None
        self._redis_pub = None
        self._listener_thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._connection_count = 0

    def _init_redis(self) -> None:
        if self._redis is not None:
            return
        host = os.getenv("REDIS_HOST", "").strip()
        if not host:
            return
        try:
            import redis

            port = int(os.getenv("REDIS_PORT", "6379"))
            db = int(os.getenv("REDIS_DB", "0"))
            self._redis = redis.Redis(host=host, port=port, db=db, decode_responses=True)
            self._redis_pub = redis.Redis(host=host, port=port, db=db, decode_responses=True)
            self._redis.ping()
        except Exception:
            self._redis = None
            self._redis_pub = None

    def connection_count(self) -> int:
        return self._connection_count

    async def start_redis_listener(self) -> None:
        self._init_redis()
        if not self._redis or self._listener_thread:
            return
        self._loop = asyncio.get_running_loop()
        self._listener_thread = threading.Thread(target=self._redis_subscribe_loop, daemon=True)
        self._listener_thread.start()

    def _redis_subscribe_loop(self) -> None:
        if not self._redis or not self._loop:
            return
        pubsub = self._redis.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe(_REDIS_CHANNEL)
        for raw in pubsub.listen():
            if raw.get("type") != "message":
                continue
            try:
                envelope = json.loads(raw.get("data") or "{}")
                sid = envelope.get("session_id", "")
                payload = envelope.get("payload") or {}
                if sid and self._loop:
                    asyncio.run_coroutine_threadsafe(self._local_broadcast(sid, payload), self._loop)
            except Exception:
                continue

    async def connect(self, session_id: str, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._rooms.setdefault(session_id, set()).add(ws)
            self._connection_count += 1

    async def disconnect(self, session_id: str, ws: WebSocket) -> None:
        async with self._lock:
            room = self._rooms.get(session_id)
            if not room:
                return
            if ws in room:
                room.discard(ws)
                self._connection_count = max(0, self._connection_count - 1)
            if not room:
                self._rooms.pop(session_id, None)

    async def _local_broadcast(self, session_id: str, payload: Dict[str, Any]) -> None:
        async with self._lock:
            sockets = list(self._rooms.get(session_id, set()))
        if not sockets:
            return
        raw = json.dumps(payload, ensure_ascii=False)
        dead: list = []
        for ws in sockets:
            try:
                await ws.send_text(raw)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(session_id, ws)

    async def broadcast(self, session_id: str, payload: Dict[str, Any]) -> None:
        await self._local_broadcast(session_id, payload)
        if self._redis_pub:
            try:
                self._redis_pub.publish(
                    _REDIS_CHANNEL,
                    json.dumps({"session_id": session_id, "payload": payload}, ensure_ascii=False),
                )
            except Exception:
                pass


hub = HandoffHub()


def emit_session_event(session_id: str, event_type: str, payload: Dict[str, Any]) -> None:
    """从同步业务层安全触发 WS 广播"""
    data = {"type": event_type, **payload}
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(hub.broadcast(session_id, data))
    except RuntimeError:
        pass
