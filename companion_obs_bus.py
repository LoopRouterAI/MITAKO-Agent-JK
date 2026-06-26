# -*- coding: utf-8 -*-
"""Companion 观测台事件总线 — 有重要数据变化时推送给 SSE 订阅端"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Set

_subscribers: Set[asyncio.Queue] = set()
_lock = asyncio.Lock()


async def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=64)
    async with _lock:
        _subscribers.add(q)
    return q


async def unsubscribe(q: asyncio.Queue) -> None:
    async with _lock:
        _subscribers.discard(q)


async def publish_obs_event(event: str, data: Dict[str, Any]) -> None:
    payload = {"event": event, "data": data, "ts": time.time()}
    async with _lock:
        subs = list(_subscribers)
    for q in subs:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            pass


def publish_obs_event_sync(event: str, data: Dict[str, Any]) -> None:
    """从同步上下文（如 SSE chat 生成器内）投递观测事件"""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(publish_obs_event(event, data))
    except RuntimeError:
        pass
