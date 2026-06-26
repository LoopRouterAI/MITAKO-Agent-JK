# -*- coding: utf-8 -*-
from __future__ import annotations

from logging_utils import log_event
from sla_worker.celery_app import celery_app


@celery_app.task(name="sla_worker.tasks.process_sla_timeouts_task")
def process_sla_timeouts_task() -> int:
    from handoff_service import process_sla_timeouts

    results = process_sla_timeouts()
    if results:
        log_event("sla_timeout_batch", count=len(results), sessions=[r.get("session_id") for r in results])
    return len(results)
