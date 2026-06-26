# -*- coding: utf-8 -*-
"""Celery SLA Worker — 生产环境替代 main.py 内联定时器"""
from __future__ import annotations

import os

from celery import Celery

_broker = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")
_backend = os.getenv("CELERY_RESULT_BACKEND", _broker)

celery_app = Celery("mitako_sla", broker=_broker, backend=_backend)
celery_app.conf.beat_schedule = {
    "process-sla-timeouts-every-30s": {
        "task": "sla_worker.tasks.process_sla_timeouts_task",
        "schedule": 30.0,
    },
}
celery_app.conf.timezone = "Asia/Shanghai"
