# -*- coding: utf-8 -*-
"""视觉审核结构化日志；只记录运行元数据，不记录凭证、Prompt 或媒体正文。"""
from __future__ import annotations

import json
import logging
import re
import sys
import threading
import time
from typing import Any, Dict
from urllib.parse import urlsplit

from poc.visual_review_poc.model_auth import endpoint_vendor_hint


BLOCKED_FIELDS = {"headers", "authorization", "api_key", "key", "prompt", "payload", "media", "response"}
_STDERR_LOCK = threading.Lock()
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


def visual_event_payload(event: str, *, endpoint: str = "", **fields: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"ts": time.time(), "event": str(event)}
    if endpoint:
        parsed = urlsplit(endpoint)
        payload.update({
            "endpoint_scheme": parsed.scheme,
            "endpoint_host": parsed.hostname or "",
            "endpoint_vendor_hint": endpoint_vendor_hint(endpoint),
        })
    for key, value in fields.items():
        if key.lower() in BLOCKED_FIELDS or value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            payload[key] = value
    return payload


def log_visual_event(_logger: logging.Logger, event: str, *, endpoint: str = "", **fields: Any) -> None:
    line = json.dumps(
        visual_event_payload(event, endpoint=endpoint, **fields),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    with _STDERR_LOCK:
        sys.stderr.write(line + "\n")
        sys.stderr.flush()
