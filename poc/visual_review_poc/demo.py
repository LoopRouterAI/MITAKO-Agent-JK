# -*- coding: utf-8 -*-
"""三类视觉审核独立 POC：视频审核、商品有伤、未成年人资料审核。"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from fixtures import VISUAL_REVIEW_CASES
from review_engine import review_case, summarize_reviews


def build_report() -> Dict[str, Any]:
    reviews = [review_case(case) for case in VISUAL_REVIEW_CASES]
    return {
        "goal": "独立验证视频审核、商品有伤、未成年人资料审核三类高人力视觉场景",
        "scope": "仅使用本地 fixture，不接入甲方真实系统，不代表真实视觉模型准确率",
        "business_priority": {
            "visual_review_workload": "约 60% 客服人力，约 6 人",
            "customer_service_agent_workload": "约 40% 客服人力，约 4 人",
            "burst_order_impact": "爆单时主链路客服会被临时调去处理视觉审核，因此视觉审核应独立优先验证",
        },
        "reviews": reviews,
        "summary": summarize_reviews(reviews),
        "handoff_contract": {
            "to_customer_service_agent": "视觉 POC 输出结构化结论，客服 Agent 只消费 decision/issues/next_step 生成售后或人工复核任务。",
            "replaceable_later": "真实图片/视频模型上线时，只替换 model_signals 生成层，不改三场景验收和客服 SOP 主流程。",
        },
    }


def self_check(report: Dict[str, Any]) -> None:
    decisions = {item["case_id"]: item["decision"] for item in report["reviews"]}
    assert decisions["video_unboxing_pass"] == "pass", decisions
    assert decisions["video_unboxing_cut"] == "suspect", decisions
    assert decisions["video_unboxing_invalid"] == "fail", decisions
    assert decisions["video_unboxing_low_confidence"] == "manual_review", decisions
    assert decisions["product_damage_pass"] == "pass", decisions
    assert decisions["product_damage_severe"] == "pass", decisions
    assert decisions["product_damage_unclear"] == "manual_review", decisions
    assert decisions["minor_material_complete"] == "pass", decisions
    assert decisions["minor_material_missing"] == "request_more_material", decisions
    assert decisions["minor_material_tampered"] == "manual_review", decisions
    assert all(item["mock_only"] is True for item in report["reviews"]), report
    assert all(item.get("sensitive_info_safe", True) is True for item in report["reviews"]), report
    assert set(report["summary"]["coverage"]) == {"video_unboxing", "product_damage", "minor_material"}, report


def main() -> int:
    report = build_report()
    self_check(report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("视觉审核 POC self-check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
