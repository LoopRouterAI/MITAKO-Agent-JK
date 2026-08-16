# -*- coding: utf-8 -*-
"""视觉审核可选模型与成本口径。"""
from __future__ import annotations

from typing import Any, Dict, List


PRICING_NOTE = "Gemini 3.5 Flash Lite 按官方标准价估算；Gemini 3.7 Flash 按官方 2026 年促销价估算；媒体模态按供应商 usage 中计入的输入 tokens 估算。"


def _positive_count(value: Any) -> int:
    try:
        return max(1, int(value or 1))
    except (TypeError, ValueError, OverflowError):
        return 1


def summarize_cost_observability(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    unknown = 0
    estimated = 0
    not_incurred = 0
    for item in items:
        explicit = str(item.get("cost_status") or "")
        if explicit == "not_incurred":
            not_incurred += 1
            continue
        if explicit == "partial_unknown":
            unknown += _positive_count(item.get("unknown_cost_calls"))
            estimated += _positive_count(item.get("estimated_cost_calls"))
            continue
        if explicit == "unknown":
            unknown += _positive_count(item.get("unknown_cost_calls"))
            continue
        usage = item.get("usage") if isinstance(item.get("usage"), dict) else {}
        cost = item.get("cost") if isinstance(item.get("cost"), dict) else {}
        usage_reported = any(value not in (None, "") for value in usage.values())
        if explicit == "estimated" or usage_reported or "estimated_usd" in cost:
            estimated += _positive_count(item.get("estimated_cost_calls"))
        else:
            unknown += 1
    status = (
        "partial_unknown" if unknown and estimated
        else "unknown" if unknown
        else "estimated" if estimated
        else "not_incurred"
    )
    return {
        "cost_status": status,
        "unknown_cost_calls": unknown,
        "estimated_cost_calls": estimated,
        "not_incurred_calls": not_incurred,
    }

MODEL_CONFIGS: Dict[str, Dict[str, Any]] = {
    "gemini35lite": {
        "label": "Gemini 3.5 Flash Lite",
        "provider": "gemini_native",
        "model": "gemini-3.5-flash-lite",
        "thinking_level": "high",
        "media_resolution": "high",
        "native_video_sampling_fps": 1.0,
        "native_perception_pipeline": True,
        "request_timeout_seconds": 420,
        "case_deadline_seconds": 600,
        "input_price": 0.30,
        "output_price": 2.50,
        "currency": "USD",
        "source": "https://ai.google.dev/gemini-api/docs/pricing",
    },
    "gemini37": {
        "label": "Gemini 3.7 Flash（高质量候选）",
        "provider": "gemini_native",
        "model": "gemini-3.7-flash",
        "explicit_only": True,
        "availability_status": "baidu_channel_smoke_passed",
        "admin_description": "视觉能力更强，成本高于默认 Lite；仅允许管理员显式启用，不进入自动兜底。",
        "thinking_level": "high",
        "media_resolution": "high",
        "native_video_sampling_fps": 1.0,
        "native_perception_pipeline": True,
        "request_timeout_seconds": 420,
        "case_deadline_seconds": 900,
        "input_price": 0.75,
        "output_price": 3.75,
        "currency": "USD",
        "pricing_valid_until": "2026-12-31",
        "source": "https://tcnxnzs113h4.feishu.cn/wiki/HAQ0w3HQFiFWdikY8prcJy5Hn7g",
    },
}
