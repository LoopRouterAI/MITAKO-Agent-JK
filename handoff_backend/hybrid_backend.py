# -*- coding: utf-8 -*-
"""Hybrid HandoffBackend — SQLite 权威 + Chatwoot IM 同步（同步由 im_sync_service 触发）"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from handoff_backend.sqlite_backend import SqliteHandoffBackend


class HybridHandoffBackend:
    """与 SqliteHandoffBackend 行为一致；HANDOFF_BACKEND=hybrid|chatwoot 时选用。"""

    mode = "hybrid"

    def __init__(self) -> None:
        self._inner = SqliteHandoffBackend()

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        return self._inner.get_session(session_id)

    def list_active_sessions(self, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return self._inner.list_active_sessions(tenant_id=tenant_id)

    def append_message(self, session_id: str, role: str, content: str, **meta: Any) -> Dict[str, Any]:
        return self._inner.append_message(session_id, role, content, **meta)

    def append_transfer_event(
        self, session_id: str, event_type: str, from_agent: str = "", to_agent: str = "", note: str = "",
    ) -> None:
        self._inner.append_transfer_event(session_id, event_type, from_agent, to_agent, note)
