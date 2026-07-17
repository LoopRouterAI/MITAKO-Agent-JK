# -*- coding: utf-8 -*-
"""审核输入与离线评测标签的隔离规则。"""
from __future__ import annotations

import re
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
    "gold_label",
    "人工结论",
    "人工标签",
    "正/负样本",
    "标准答案",
    "样本标签",
}
EVALUATION_LABEL_MARKERS = (
    "expected_predicted_label",
    "human_conclusion",
    "ground_truth",
    "标准答案：",
    "标准答案=",
    "正确答案：",
    "正确答案=",
    "正向样本",
    "负向样本",
    "正样本",
    "负样本",
    "人工拒绝",
    "审核不通过",
)


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


def contains_evaluation_marker(value: Any) -> bool:
    lowered = str(value or "").lower()
    return any(marker in lowered for marker in EVALUATION_LABEL_MARKERS)


def redact_review_personal_data(value: str) -> str:
    """遮盖送模文本中的常见个人号码，不改变金额、日期等短数字。"""
    output = str(value or "")
    for pattern in SENSITIVE_TEXT_PATTERNS:
        output = pattern.sub("[敏感信息已遮盖]", output)
    return output


def _is_sensitive_key(value: Any) -> bool:
    lowered = str(value or "").strip().lower()
    return any(marker in lowered for marker in SENSITIVE_KEY_MARKERS)


def assert_review_input_safe(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if is_evaluation_key(key):
                raise ValueError("evaluation_label_not_allowed")
            assert_review_input_safe(item)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            assert_review_input_safe(item)
        return
    if isinstance(value, str) and contains_evaluation_marker(value):
        raise ValueError("evaluation_label_not_allowed")


def sanitize_review_input(value: Any) -> Any:
    """最终送模前再次删除评测字段，防止绕过 API 的本地调用泄题。"""
    if isinstance(value, dict):
        return {
            key: "[敏感字段已遮盖]" if _is_sensitive_key(key) and item not in (None, "") else sanitize_review_input(item)
            for key, item in value.items()
            if not is_evaluation_key(key)
        }
    if isinstance(value, list):
        return [sanitize_review_input(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_review_input(item) for item in value]
    if isinstance(value, str) and contains_evaluation_marker(value):
        return "[评测标签已隔离]"
    if isinstance(value, str):
        return redact_review_personal_data(value)
    return value
