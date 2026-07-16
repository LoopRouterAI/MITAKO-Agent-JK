# -*- coding: utf-8 -*-
"""视觉审核可选模型与成本口径。"""
from __future__ import annotations

from typing import Any, Dict


PRICING_NOTE = "Gemini 3.1 Flash Lite 按用户成本表 0.25/1.50 USD 每百万 tokens 并按 7 元/USD 折算；Qwen3.5-Flash 与 Doubao Seed 2.0 Lite 按用户提供阶梯价依据输入 tokens 选择区间；本轮未使用音频输入。Gemini 3.5 Flash 仍按脚本内官方价格基准估算。"

MODEL_CONFIGS: Dict[str, Dict[str, Any]] = {
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
