# -*- coding: utf-8 -*-
"""视觉审核结构化日志；只记录运行元数据，不记录凭证、Prompt 或媒体正文。"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict
from urllib.parse import urlsplit

from poc.visual_review_poc.model_auth import endpoint_vendor_hint


BLOCKED_FIELDS = {"headers", "authorization", "api_key", "key", "prompt", "payload", "media", "response"}


def visual_event_payload(event: str, *, endpoint: str = "", **fields: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"event": str(event)}
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


def log_visual_event(logger: logging.Logger, event: str, *, endpoint: str = "", **fields: Any) -> None:
    logger.info(json.dumps(visual_event_payload(event, endpoint=endpoint, **fields), ensure_ascii=False, separators=(",", ":")))
