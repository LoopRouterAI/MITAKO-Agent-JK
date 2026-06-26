# -*- coding: utf-8 -*-
"""默认 HandoffBackend — 委托 handoff_store"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import handoff_store as store


class SqliteHandoffBackend:
    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        return store.get_session(session_id)

    def list_active_sessions(self, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return store.list_active_sessions(tenant_id=tenant_id)

    def append_message(self, session_id: str, role: str, content: str, **meta: Any) -> Dict[str, Any]:
        return store.append_message(session_id, role, content, agent_id=meta.get("agent_id", ""), meta=meta.get("meta"))

    def append_transfer_event(
        self, session_id: str, event_type: str, from_agent: str = "", to_agent: str = "", note: str = "",
    ) -> None:
        store.append_transfer_event(session_id, event_type, from_agent, to_agent, note)


def get_backend() -> SqliteHandoffBackend:
    from handoff_backend.factory import get_backend as _factory_get

    return _factory_get()  # type: ignore[return-value]
