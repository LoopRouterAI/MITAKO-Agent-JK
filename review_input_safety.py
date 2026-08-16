# -*- coding: utf-8 -*-
"""审核输入与离线评测标签的隔离规则。"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


EVALUATION_LABEL_KEYS = {
    "annotation",
    "annotations",
    "labels",
    "label",
    "expected_predicted_label",
    "human_conclusion",
    "previous_human_conclusion",
    "ground_truth",
    "groundtruth",
    "ground_truth_label",
    "expected_label",
    "manual_label",
    "reference_label",
    "final_label",
    "final_decision",
    "final_outcome",
    "refund_result",
    "resolution",
    "approved",
    "gold_label",
    "人工结论",
    "人工标签",
    "正/负样本",
    "标准答案",
    "样本标签",
}
MODEL_EXCLUDED_KEYS = {"source_case", "source_record"}
SENSITIVE_KEY_MARKERS = (
    "phone",
    "mobile",
    "contact_number",
    "id_card",
    "identity_number",
    "identity_no",
    "bank_card",
    "address",
)
SENSITIVE_TEXT_PATTERNS = (
    re.compile(r"(?<!\d)\d{17}[0-9Xx](?!\d)"),
    re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    re.compile(r"(?<!\d)\d{16,19}(?!\d)"),
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
)


def is_evaluation_key(value: Any) -> bool:
    return str(value or "").strip().lower() in EVALUATION_LABEL_KEYS


def redact_review_personal_data(value: str) -> str:
    """遮盖送模文本中的常见个人号码，不改变金额、日期等短数字。"""
    output = str(value or "")
    for pattern in SENSITIVE_TEXT_PATTERNS:
        output = pattern.sub("[敏感信息已遮盖]", output)
    return output


def read_user_conversation_history(folder: Path, *, limit: int = 80) -> list[dict[str, str]]:
    """只读取用户原话；客服回复和人工结论不得进入模型输入。"""
    raw: Any = None
    for name in ("conversation_predecision.json", "reply.json"):
        path = folder / name
        if not path.is_file():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            raw = None
        if isinstance(raw, list):
            break
    if not isinstance(raw, list):
        return []
    messages = []
    for item in raw:
        if not isinstance(item, dict) or str(item.get("from") or "").lower() not in {"user", "customer"}:
            continue
        text = redact_review_personal_data(str(item.get("text") or "").strip()[:2000])
        if text:
            messages.append({
                "role": "user",
                "text": text,
                "created_at": str(item.get("created_at") or "")[:80],
            })
    return messages[-limit:]


def _is_sensitive_key(value: Any) -> bool:
    lowered = str(value or "").strip().lower()
    return any(marker in lowered for marker in SENSITIVE_KEY_MARKERS)


def assert_review_input_safe(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key or "").strip().lower() in MODEL_EXCLUDED_KEYS:
                continue
            if is_evaluation_key(key):
                raise ValueError("evaluation_label_not_allowed")
            assert_review_input_safe(item)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            assert_review_input_safe(item)
        return
def sanitize_review_input(value: Any) -> Any:
    """最终送模前再次删除评测字段，防止绕过 API 的本地调用泄题。"""
    if isinstance(value, dict):
        return {
            key: "[敏感字段已遮盖]" if _is_sensitive_key(key) and item not in (None, "") else sanitize_review_input(item)
            for key, item in value.items()
            if not is_evaluation_key(key) and str(key or "").strip().lower() not in MODEL_EXCLUDED_KEYS
        }
    if isinstance(value, list):
        return [sanitize_review_input(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_review_input(item) for item in value]
    if isinstance(value, str):
        return redact_review_personal_data(value)
    return value
