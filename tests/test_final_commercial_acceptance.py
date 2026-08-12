# -*- coding: utf-8 -*-
from scripts.run_final_commercial_acceptance import CASES, build_commercial_checks, damage_follow_up_consistent


def test_damage_follow_up_consistency_rejects_stale_positive_explanation() -> None:
    assert damage_follow_up_consistent({
        "primary_claim_support": "insufficient",
        "business_follow_up_reason": "开箱合规项未闭环，保留复核信号。",
    })
    assert not damage_follow_up_consistent({
        "primary_claim_support": "supported",
        "business_follow_up_reason": "Evidence is clear and complete; no human intervention required.",
    })


def test_598089_uses_customer_supervisor_final_baseline() -> None:
    case = next(item for item in CASES if item["case_id"] == "598089")

    assert "合格" in case["manual_baseline"]
    assert "不离框" in case["manual_baseline"]


def test_commercial_gate_accepts_598089_final_nine_fields() -> None:
    positive = {
        "status": "SUCCEEDED",
        "predicted_label": "positive",
        "opening_result": "compliant",
        "issue_visible_in_continuous_opening": True,
        "has_offscreen": False,
        "material_gaps": [],
    }
    grouped = {
        "598089": [dict(positive), dict(positive)],
        "606669": [{
            "status": "SUCCEEDED",
            "predicted_label": "negative",
            "opening_result": "noncompliant",
            "primary_claim_support": "insufficient",
            "business_follow_up_reason": "开箱关键条件不完整。",
            "material_gaps": [],
        }],
        "568689": [{
            "status": "SUCCEEDED",
            "predicted_label": "negative",
            "human_review": "not_required",
            "overall_conclusion": "仓库终核确定未漏发",
            "material_gaps": [],
        }],
    }

    checks = build_commercial_checks(grouped)

    assert checks["598089_stable_manual_alignment"] is True
