# -*- coding: utf-8 -*-
"""从用户陈述和受信服务记录生成可追溯事实。"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from .contracts import Fact, FactSource


_MATERIAL_TERMS = (
    "材料",
    "照片",
    "图片",
    "视频",
    "面单",
    "发票",
    "承诺书",
    "截图",
    "证件",
)
_CLAIM_PATTERN = re.compile(
    r"(?:已经|已|都)(?:准备(?:好|完)?|备齐|拍(?:好|完)?|上传|提交|提供)(?:了)?"
    r"|(?:准备(?:好|完)?了|备齐(?:了)?|拍(?:好|完)?了|上传了|提交了|提供了)"
    r"|(?:^|[，。！？\s]|我|这边|手里)(?<!没)有(?:了)?"
)
_PARSED_STATUSES = frozenset(
    {"parsed", "completed", "succeeded", "success", "review_completed", "review_succeeded"}
)
_FAILED_PARSE_STATUSES = frozenset(
    {"failed", "error", "parse_failed", "review_failed", "invalid", "cancelled", "canceled"}
)
_QUEUED_HANDOFF_STATUSES = frozenset(
    {"queued", "queuing", "escalated", "transferring", "connected"}
)


def _text(record: Mapping[str, Any] | None, *keys: str) -> str:
    if not record:
        return ""
    for key in keys:
        value = record.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _attachment_ref(record: Mapping[str, Any]) -> str:
    identifier = _text(record, "review_task_id", "id")
    if not identifier:
        return ""
    prefix = "review_task" if record.get("kind") == "review_task" else "attachment"
    return f"{prefix}:{identifier}"


def _claims_material(message: str) -> bool:
    text = str(message or "")
    return any(term in text for term in _MATERIAL_TERMS) and bool(_CLAIM_PATTERN.search(text))


def _parse_observation(record: Mapping[str, Any]) -> bool | None:
    status = _text(record, "status").lower()
    parse_status = _text(record, "parse_status").lower()
    if status in _FAILED_PARSE_STATUSES or parse_status in _FAILED_PARSE_STATUSES:
        return False
    parsed = record.get("parsed")
    if isinstance(parsed, bool):
        return parsed
    if parse_status in _PARSED_STATUSES:
        return True
    if record.get("kind") != "review_task":
        return None
    if status in _PARSED_STATUSES:
        return True
    return None


def resolve_facts(
    *,
    message: str,
    attachments: Sequence[Mapping[str, Any]],
    review_job: Mapping[str, Any] | None = None,
    selected_order: Mapping[str, Any] | None = None,
    resolved_product: Mapping[str, Any] | None = None,
    handoff: Mapping[str, Any] | None = None,
) -> list[Fact]:
    trusted_attachments = [item for item in attachments if _attachment_ref(item)]
    claimed = _claims_material(message)
    received_ref = _attachment_ref(trusted_attachments[0]) if trusted_attachments else ""

    parse_record: Mapping[str, Any] | None = None
    parsed_value = False
    for item in trusted_attachments:
        observation = _parse_observation(item)
        if observation is not None:
            parse_record = item
            parsed_value = observation
            if observation:
                break
    parsed_ref = _attachment_ref(parse_record) if parse_record else ""
    parsed_source = (
        FactSource.REVIEW_SERVICE
        if parse_record and parse_record.get("kind") == "review_task"
        else FactSource.ATTACHMENT_SERVICE
    )

    review_record = review_job or next(
        (item for item in trusted_attachments if item.get("kind") == "review_task"),
        None,
    )
    review_id = _text(review_record, "task_id", "review_task_id", "id")
    order_id = _text(selected_order, "order_id", "id")
    product_id = _text(resolved_product, "sku", "product_id", "id")
    product_status = _text(resolved_product, "status").lower()
    if product_status in {"ambiguous", "unresolved", "not_found", "failed"}:
        product_id = ""
    handoff_id = _text(handoff, "queue_id", "receipt_id", "session_id", "id")
    handoff_queued = bool(
        handoff_id and _text(handoff, "status").lower() in _QUEUED_HANDOFF_STATUSES
    )

    return [
        Fact(
            field="material.user_claimed",
            value=claimed,
            source=FactSource.USER_STATEMENT,
            source_ref="current_message" if claimed else "",
        ),
        Fact(
            field="material.received",
            value=bool(received_ref),
            source=FactSource.ATTACHMENT_SERVICE,
            source_ref=received_ref,
            verified=bool(received_ref),
        ),
        Fact(
            field="material.parsed",
            value=parsed_value,
            source=parsed_source,
            source_ref=parsed_ref,
            verified=bool(parsed_ref),
        ),
        Fact(
            field="review.job_created",
            value=bool(review_id),
            source=FactSource.REVIEW_SERVICE,
            source_ref=f"review_task:{review_id}" if review_id else "",
            verified=bool(review_id),
        ),
        Fact(
            field="order.selected",
            value=order_id or False,
            source=FactSource.ORDER_SERVICE,
            source_ref=f"order:{order_id}" if order_id else "",
            verified=bool(order_id),
        ),
        Fact(
            field="product.identity_resolved",
            value=product_id or False,
            source=FactSource.PRODUCT_SERVICE,
            source_ref=f"product:{product_id}" if product_id else "",
            verified=bool(product_id),
        ),
        Fact(
            field="handoff.queued",
            value=handoff_queued,
            source=FactSource.HANDOFF_SERVICE,
            source_ref=f"handoff_queue:{handoff_id}" if handoff_queued else "",
            verified=handoff_queued,
        ),
    ]
