# -*- coding: utf-8 -*-
"""结构化日志 — 生产可观测"""
from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any, Dict

_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(logging.Formatter("%(message)s"))
logger = logging.getLogger("mitako")
logger.setLevel(logging.INFO)
if not logger.handlers:
    logger.addHandler(_handler)


def log_event(event: str, **fields: Any) -> None:
    payload: Dict[str, Any] = {"ts": time.time(), "event": event, **fields}
    logger.info(json.dumps(payload, ensure_ascii=False))
