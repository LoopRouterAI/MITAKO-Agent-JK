# -*- coding: utf-8 -*-
"""视觉审核结构化日志；只记录运行元数据，不记录凭证、Prompt 或媒体正文。"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Dict
from urllib.parse import urlsplit

from poc.visual_review_poc.model_auth import endpoint_vendor_hint
from observability_store import record_event


BLOCKED_FIELDS = {"headers", "authorization", "api_key", "key", "prompt", "payload", "media", "response"}
_STDERR_LOCK = threading.Lock()
_EVENT_CONTEXT: ContextVar[Dict[str, str]] = ContextVar("visual_event_context", default={})
_ERROR_SECRET_PATTERNS = (
    re.compile(r"(?i)([?&](?:key|api_key|access_token)=)[^&\s]+"),
    re.compile(r"(?i)(\b(?:api[_ -]?key|access[_ -]?token|authorization)\b\s*[:=]\s*)(?:bearer\s+)?[^\s,;}\]]+"),
    re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]{8,}"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{16,}\b"),
    re.compile(r"\bsk-[0-9A-Za-z_-]{12,}\b"),
)


def sanitize_error_text(value: Any, limit: int = 1600) -> str:
    text = str(value or "")[:max(limit * 2, 4096)]
    for pattern in _ERROR_SECRET_PATTERNS:
        text = pattern.sub(lambda match: f"{match.group(1)}[REDACTED]" if match.lastindex else "[REDACTED]", text)
    return text[:limit]


def event_visibility_mode() -> str:
    mode = os.getenv("MITAKO_VISUAL_LOG_MODE", "redacted").strip().lower()
    return "internal" if mode in {"internal", "full", "debug"} else "redacted"


@contextmanager
def visual_event_context(**values: str):
    current = dict(_EVENT_CONTEXT.get() or {})
    current.update({key: str(value) for key, value in values.items() if value not in (None, "")})
    token = _EVENT_CONTEXT.set(current)
    try:
        yield
    finally:
        _EVENT_CONTEXT.reset(token)


def _redacted_field(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in ("model", "provider", "vendor", "channel", "endpoint", "gateway"))


def visual_event_payload(event: str, *, endpoint: str = "", _mode: str | None = None, **fields: Any) -> Dict[str, Any]:
    mode = _mode or event_visibility_mode()
    payload: Dict[str, Any] = {
        "ts": time.time(),
        "event": str(event),
        "visibility": mode,
        **(_EVENT_CONTEXT.get() or {}),
    }
    if endpoint:
        if mode == "internal":
            parsed = urlsplit(endpoint)
            payload.update({
                "endpoint_scheme": parsed.scheme,
                "endpoint_host": parsed.hostname or "",
                "endpoint_vendor_hint": endpoint_vendor_hint(endpoint),
            })
        else:
            payload["request_target"] = "model_gateway"
    for key, value in fields.items():
        if key.lower() in BLOCKED_FIELDS or value is None:
            continue
        if mode == "redacted" and _redacted_field(key):
            continue
        if isinstance(value, (str, int, float, bool)):
            payload[key] = value
    return payload


def log_visual_event(_logger: logging.Logger, event: str, *, endpoint: str = "", **fields: Any) -> None:
    payload = visual_event_payload(event, endpoint=endpoint, **fields)
    line = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    record_event(payload, visibility=str(payload.get("visibility") or "redacted"))
    if payload.get("visibility") == "internal":
        redacted = visual_event_payload(event, endpoint=endpoint, _mode="redacted", **fields)
        record_event(redacted, visibility="redacted")
    with _STDERR_LOCK:
        sys.stderr.write(line + "\n")
        sys.stderr.flush()
