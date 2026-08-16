# -*- coding: utf-8 -*-
from __future__ import annotations

from unittest.mock import patch

from scripts.reprocess_review_artifacts import reprocess_job


def test_reprocess_job_is_immutable_and_records_only_deterministic_changes() -> None:
    job = {
        "job_id": "RJ-REPROCESS-1",
        "status": "SUCCEEDED",
        "result": {
            "input_readiness": {"full_review_ready": True},
            "media_forensics": {"status": "completed"},
            "review": {"summary": {"predicted_label": "review", "confidence": 0.6}},
        },
    }
    source_review = job["result"]["review"]
    normalized = {
        "summary": {"predicted_label": "review", "confidence": 0.6},
        "material_readiness": {"status": "incomplete"},
        "advisory_assessment": {
            "workflow_recommendation": "human_review",
            "assessment": {"conclusion": "请查询甲方内部数据。"},
            "human_review": {
                "level": "required",
                "reason_codes": ["trusted_system_data_required"],
                "recommendation": "请查询甲方订单。",
            },
        },
    }

    with patch(
        "scripts.reprocess_review_artifacts.postprocess_review",
        return_value=normalized,
    ), patch(
        "scripts.reprocess_review_artifacts._sync_final_advisory_brief",
        side_effect=lambda value: value,
    ):
        derived, changes = reprocess_job(job)

    assert job["result"]["review"] is source_review
    assert "material_readiness" not in job["result"]
    assert derived["result"]["review"] == normalized
    assert changes["changed_fields"] == [
        "material_status", "workflow", "human_review", "reason_codes", "conclusion", "next_step",
    ]


def test_reprocess_rejects_non_success_job() -> None:
    try:
        reprocess_job({"status": "FAILED"})
    except ValueError as exc:
        assert str(exc) == "only_succeeded_jobs_can_be_reprocessed"
    else:
        raise AssertionError("FAILED 工单不得生成规则重处理报告")
