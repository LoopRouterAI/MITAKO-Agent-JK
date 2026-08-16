# -*- coding: utf-8 -*-
"""Gemini 视觉审核适配器 POC：先固定请求/响应契约，真实 API 后续替换。"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict

from fixtures import VISUAL_REVIEW_CASES
from review_engine import review_case
from prompts.visual_review.diagnostics import build_fixture_contract_prompt

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


GEMINI_MODEL = "gemini-3.5-flash-lite"


def build_gemini_prompt(case: Dict[str, Any]) -> str:
    return build_fixture_contract_prompt(case)


def run_gemini_fixture(case: Dict[str, Any]) -> Dict[str, Any]:
    # ponytail: 真实 Gemini 调用先不接入；当前固定契约，API Key 和样本确认后替换这里。
    result = review_case(case)
    result["provider"] = "gemini_fixture"
    result["model"] = GEMINI_MODEL
    result["prompt_preview"] = build_gemini_prompt(case)[:160]
    return result


def check_gemini_readiness() -> Dict[str, Any]:
    return {
        "provider": "gemini",
        "model": GEMINI_MODEL,
        "api_key_configured": bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")),
        "mode": "fixture_contract",
        "next_step": "配置 Gemini API Key 和甲方脱敏样本后，将 run_gemini_fixture 替换为真实 generateContent 调用。",
    }


def demo_payload() -> Dict[str, Any]:
    results = [run_gemini_fixture(case) for case in VISUAL_REVIEW_CASES[:3]]
    return {
        "goal": "验证 Gemini 3.5 Flash 视觉审核结构化输出契约",
        "readiness": check_gemini_readiness(),
        "results": results,
    }


def main() -> int:
    payload = demo_payload()
    assert payload["results"], payload
    assert all(item["model"] == GEMINI_MODEL for item in payload["results"]), payload
    assert all(item["mock_only"] is True for item in payload["results"]), payload
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print("Gemini 视觉适配器契约 self-check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
