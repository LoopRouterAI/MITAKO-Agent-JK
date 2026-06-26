# -*- coding: utf-8 -*-
"""HandoffBackend 协议 — 生产 IM 适配入口"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol


class HandoffBackend(Protocol):
    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]: ...
    def list_active_sessions(self) -> List[Dict[str, Any]]: ...
    def append_message(self, session_id: str, role: str, content: str, **meta: Any) -> Dict[str, Any]: ...
    def append_transfer_event(
        self, session_id: str, event_type: str, from_agent: str = "", to_agent: str = "", note: str = "",
    ) -> None: ...
