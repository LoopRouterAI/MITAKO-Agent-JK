# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest

from pydantic import ValidationError

from review_service.advisory_assessment import attach_advisory_assessment, html_report_requested
from review_service.schemas import ReviewCaseMetadata


def review_result(
    label: str = "positive",
    confidence: float = 0.9,
    *,
    continuity: dict | None = None,
    parsed_extra: dict | None = None,
) -> dict:
    parsed = {
        "predicted_label": label,
        "confidence": confidence,
        "overall_audit": {"conclusion": "当前视觉证据支持用户所述事实。"},
    }
    if continuity is not None:
        parsed["object_continuity_assessment"] = continuity
    parsed.update(parsed_extra or {})
    return {
        "summary": {"predicted_label": label, "confidence": confidence},
        "agent_brief": {"conclusion": "当前视觉证据支持用户所述事实。"},
        "agent_report": {"parsed": parsed},
    }


class AdvisoryAssessmentTest(unittest.TestCase):
    def test_high_confidence_complete_evidence_does_not_require_human_review(self):
        result = attach_advisory_assessment(
            review_result(),
            {"scenario": "product_damage"},
            readiness={"full_review_ready": True, "missing_required": []},
        )

        advisory = result["advisory_assessment"]
        self.assertEqual(advisory["human_review"]["level"], "not_required")
        self.assertEqual(advisory["workflow_recommendation"], "continue_by_customer_policy")
        self.assertFalse(advisory["policy"]["business_action_allowed"])
        self.assertEqual(advisory["assessment"]["calibration_status"], "uncalibrated_evidence_score")

    def test_short_out_of_frame_is_optional_signal_not_mandatory_review(self):
        result = attach_advisory_assessment(
            review_result(
                continuity={
                    "continuity_verdict": "brief_occlusion",
                    "longest_out_of_frame_seconds": 1.4,
                    "tracked_subjects": [{"subject_id": "claimed_item"}],
                }
            ),
            {
                "scenario": "product_damage",
                "review_routing_policy": {"out_of_frame_resubmit_seconds": 3.0},
            },
            readiness={"full_review_ready": True, "missing_required": []},
        )

        advisory = result["advisory_assessment"]
        self.assertEqual(advisory["human_review"]["level"], "optional")
        self.assertEqual(advisory["workflow_recommendation"], "continue_by_customer_policy")
        self.assertIn("short_out_of_frame", [item["code"] for item in advisory["signals"]])

    def test_three_second_out_of_frame_requests_material_without_forcing_human(self):
        result = attach_advisory_assessment(
            review_result(
                continuity={
                    "continuity_verdict": "long_absence",
                    "longest_out_of_frame_seconds": 3.2,
                    "tracked_subjects": [{"subject_id": "claimed_item"}],
                }
            ),
            {
                "scenario": "product_damage",
                "review_routing_policy": {"out_of_frame_resubmit_seconds": 3.0},
            },
            readiness={"full_review_ready": True, "missing_required": []},
        )

        advisory = result["advisory_assessment"]
        self.assertEqual(advisory["human_review"]["level"], "not_required")
        self.assertEqual(advisory["workflow_recommendation"], "request_more_material")
        self.assertIn("out_of_frame_over_threshold", [item["code"] for item in advisory["signals"]])

    def test_conflicting_evidence_requires_human_review(self):
        result = attach_advisory_assessment(
            review_result(parsed_extra={"evidence_conflicts": ["主视频与补充图片结论冲突"]}),
            {"scenario": "product_damage"},
            readiness={"full_review_ready": True, "missing_required": []},
        )

        advisory = result["advisory_assessment"]
        self.assertEqual(advisory["human_review"]["level"], "required")
        self.assertEqual(advisory["workflow_recommendation"], "human_review")
        self.assertIn("evidence_conflict", advisory["human_review"]["reason_codes"])

    def test_input_readiness_guard_overrides_stale_positive_summary(self):
        guarded = review_result(label="positive", confidence=0.93)
        guarded.update(
            {
                "predicted_label": "review",
                "confidence": 0.41,
                "input_readiness_guard": {
                    "applied": True,
                    "missing_required": ["订单SKU基准"],
                },
            }
        )

        result = attach_advisory_assessment(
            guarded,
            {"scenario": "wrong_item"},
            readiness={"full_review_ready": False, "missing_required": ["订单SKU基准"]},
        )

        advisory = result["advisory_assessment"]
        self.assertEqual(advisory["assessment"]["conclusion_code"], "evidence_inconclusive")
        self.assertEqual(advisory["assessment"]["confidence"], 0.41)
        self.assertEqual(advisory["workflow_recommendation"], "request_more_material")
        self.assertEqual(result["summary"]["predicted_label"], "review")
        self.assertNotIn("支持用户所述事实", advisory["assessment"]["conclusion"])

    def test_output_options_and_routing_thresholds_are_bounded(self):
        metadata = ReviewCaseMetadata.model_validate(
            {
                "client_case_id": "CASE-OUTPUT-1",
                "scenario": "product_damage",
                "output_options": {"include_html_report": False},
                "review_routing_policy": {
                    "required_below_confidence": 0.45,
                    "optional_below_confidence": 0.8,
                    "out_of_frame_resubmit_seconds": 3.0,
                },
            }
        )

        self.assertFalse(metadata.output_options.include_html_report)
        self.assertFalse(html_report_requested(metadata.model_dump(mode="json")))
        self.assertEqual(metadata.review_routing_policy.out_of_frame_resubmit_seconds, 3.0)

    def test_legacy_fields_follow_primary_advisory_contract(self):
        stale = review_result(confidence=0.92)
        stale["agent_report"]["parsed"].update(
            {"human_required": True, "decision": "manual_review", "system_yes_no": "REVIEW"}
        )

        result = attach_advisory_assessment(
            stale,
            {"scenario": "product_damage"},
            readiness={"full_review_ready": True, "missing_required": []},
        )

        parsed = result["agent_report"]["parsed"]
        self.assertFalse(parsed["human_required"])
        self.assertEqual(parsed["decision"], "continue_by_customer_policy")
        self.assertEqual(parsed["system_yes_no"], "YES")

    def test_minor_authoritative_verification_pending_requires_human_review(self):
        result = attach_advisory_assessment(
            review_result(
                confidence=0.88,
                parsed_extra={
                    "authoritative_verification": {
                        "status": "customer_integration_required",
                        "pending_checks": ["guardian_identity", "payment_ownership"],
                    }
                },
            ),
            {"scenario": "minor_refund"},
            readiness={"full_review_ready": True, "missing_required": []},
        )

        advisory = result["advisory_assessment"]
        self.assertEqual(advisory["human_review"]["level"], "required")
        self.assertIn("authoritative_verification_pending", advisory["human_review"]["reason_codes"])

    def test_reversed_routing_thresholds_are_rejected(self):
        with self.assertRaises(ValidationError):
            ReviewCaseMetadata.model_validate(
                {
                    "client_case_id": "CASE-BAD-THRESHOLDS",
                    "scenario": "product_damage",
                    "review_routing_policy": {
                        "required_below_confidence": 0.9,
                        "optional_below_confidence": 0.2,
                    },
                }
            )


if __name__ == "__main__":
    unittest.main()
