# -*- coding: utf-8 -*-
"""视觉审核可选模型与成本口径。"""
from __future__ import annotations

from typing import Any, Dict, List


PRICING_NOTE = "Gemini 3.5 Flash Lite 与 Gemini 3.5 Flash 按官方标准价估算；Gemini 3.1 Flash Lite 按用户成本表 0.25/1.50 USD 每百万 tokens 并按 7 元/USD 折算；Qwen3.5-Flash 与 Doubao Seed 2.0 Lite 按用户提供阶梯价依据输入 tokens 选择区间；本轮未使用音频输入。"


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
            unknown += max(1, int(item.get("unknown_cost_calls") or 1))
            estimated += max(1, int(item.get("estimated_cost_calls") or 1))
            continue
        if explicit == "unknown":
            unknown += max(1, int(item.get("unknown_cost_calls") or 1))
            continue
        usage = item.get("usage") if isinstance(item.get("usage"), dict) else {}
        cost = item.get("cost") if isinstance(item.get("cost"), dict) else {}
        usage_reported = any(value not in (None, "") for value in usage.values())
        if explicit == "estimated" or usage_reported or "estimated_usd" in cost:
            estimated += max(1, int(item.get("estimated_cost_calls") or 1))
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
        "input_price": 0.30,
        "output_price": 2.50,
        "currency": "USD",
        "source": "https://ai.google.dev/gemini-api/docs/pricing",
    },
    "gemini35": {
        "label": "Gemini 3.5 Flash",
        "provider": "gemini_native",
        "model": "gemini-3.5-flash",
        "input_price": 1.50,
        "output_price": 9.00,
        "currency": "USD",
        "source": "https://ai.google.dev/gemini-api/docs/pricing",
    },
    "gemini31lite": {
        "label": "Gemini 3.1 Flash Lite",
        "provider": "gemini_native",
        "model": "gemini-3.1-flash-lite",
        "input_price": 0.25,
        "output_price": 1.50,
        "currency": "USD",
        "source": "https://ai.google.dev/gemini-api/docs/pricing",
    },
    "qwen35flash": {
        "label": "Qwen3.5 Flash",
        "provider": "openai_compatible",
        "model": "qwen3.5-flash",
        "endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "key_env": "DASHSCOPE_API_KEY",
        "input_price": 0.20,
        "output_price": 2.00,
        "currency": "CNY",
        "source": "用户提供成本表：Qwen3.5-Flash 阶梯价",
        "pricing_tiers": [
            {"max_input_tokens": 128_000, "input_price": 0.20, "output_price": 2.00},
            {"max_input_tokens": 256_000, "input_price": 0.80, "output_price": 8.00},
            {"max_input_tokens": 1_000_000, "input_price": 1.20, "output_price": 12.00},
        ],
    },
    "doubao20lite": {
        "label": "Doubao Seed 2.0 Lite",
        "provider": "openai_compatible",
        "model": "doubao-seed-2-0-lite-260428",
        "display_model": "doubao-seed-2.0-lite",
        "endpoint": "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
        "key_env": "ARK_API_KEY",
        "input_price": 0.60,
        "output_price": 3.60,
        "currency": "CNY",
        "source": "用户提供成本表：Doubao-Seed-2.0-lite 阶梯价",
        "pricing_tiers": [
            {"max_input_tokens": 32_000, "input_price": 0.60, "output_price": 3.60},
            {"max_input_tokens": 128_000, "input_price": 0.90, "output_price": 5.40},
            {"max_input_tokens": 256_000, "input_price": 1.80, "output_price": 10.80},
        ],
    },
}
