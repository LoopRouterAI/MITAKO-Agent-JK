# -*- coding: utf-8 -*-
"""HandoffBackend 工厂 — sqlite | hybrid | chatwoot"""
from __future__ import annotations

import os
from typing import Union

from handoff_backend.hybrid_backend import HybridHandoffBackend
from handoff_backend.sqlite_backend import SqliteHandoffBackend

BackendType = Union[SqliteHandoffBackend, HybridHandoffBackend]

_cached: BackendType | None = None


def backend_mode() -> str:
    return os.getenv("HANDOFF_BACKEND", "sqlite").strip().lower()


def get_backend() -> BackendType:
    """按 HANDOFF_BACKEND 返回后端实例（进程内单例）。"""
    global _cached
    if _cached is not None:
        return _cached
    mode = backend_mode()
    if mode in ("hybrid", "chatwoot"):
        _cached = HybridHandoffBackend()
    else:
        _cached = SqliteHandoffBackend()
    return _cached
