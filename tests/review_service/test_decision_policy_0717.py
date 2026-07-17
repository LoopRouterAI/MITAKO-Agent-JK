# -*- coding: utf-8 -*-
import unittest

from review_service.decision_policy import apply_review_decision_policy
from review_service.schemas import ReviewCaseMetadata


def review(parsed=None):
    parsed = parsed or {"predicted_label": "review", "confidence": 0.69}
    return {"agent_report": {"parsed": parsed}, "summary": {"predicted_label": "review", "confidence": 0.69}}


class ReviewDecisionPolicy0717Test(unittest.TestCase):
    def test_default_policy_never_turns_missing_video_into_negative(self):
        metadata = ReviewCaseMetadata(
            client_case_id="case-default",
            scenario="product_damage",
            customer_claim="商品弯曲",
        ).model_dump(mode="json")
        result = apply_review_decision_policy(
            {"scenario": "product_damage", "metadata": metadata, "assets": []},
            review(),
        )
        self.assertEqual(result["summary"]["predicted_label"], "review")
        self.assertFalse(result["decision_policy_audit"]["applied"])

    def test_617341_explicit_versioned_policy_can_recommend_negative(self):
        metadata = ReviewCaseMetadata.model_validate(
            {
                "client_case_id": "case-617341",
                "scenario": "product_damage",
                "customer_claim": "商品弯曲",
                "claim_scope": {
                    "split_status": "resolved",
                    "active_claim_ids": ["CLM-1"],
                    "claims": [{"claim_id": "CLM-1", "issue_type": "bending", "location": "商品本体"}],
                },
                "decision_policy": {
                    "mode": "classification_recommendation",
                    "policy_ref": "MITAKO-PD-20260717@1",
                    "opening_video_required": True,
                    "missing_required_opening_video": "negative",
                },
            }
        ).model_dump(mode="json")
        result = apply_review_decision_policy(
            {"scenario": "product_damage", "metadata": metadata, "assets": []},
            review(),
        )
        parsed = result["agent_report"]["parsed"]
        self.assertEqual(parsed["predicted_label"], "negative")
        self.assertEqual(parsed["decision_policy_audit"]["rule_id"], "PD-N-OPENING-VIDEO-REQUIRED")
        self.assertFalse(parsed["business_action_allowed"])
        self.assertTrue(parsed["human_required_for_business_action"])
        self.assertIn("必须提交开箱视频", parsed["overall_audit"]["conclusion"])
        self.assertIn("视觉证明商品无损", parsed["overall_audit"]["core_reason"])
        self.assertIn("必须提交开箱视频", result["agent_brief"]["conclusion"])

    def test_617911_missing_closeup_stays_review(self):
        metadata = ReviewCaseMetadata.model_validate(
            {
                "client_case_id": "case-617911",
                "scenario": "product_damage",
                "customer_claim": "商品有伤",
                "claim_scope": {
                    "split_status": "resolved",
                    "active_claim_ids": ["CLM-1"],
                    "claims": [{"claim_id": "CLM-1", "issue_type": "visible_damage", "location": "未明确"}],
                },
                "decision_policy": {
                    "mode": "classification_recommendation",
                    "policy_ref": "MITAKO-PD-20260717@1",
                    "complete_video_no_claimed_damage": "negative",
                },
            }
        ).model_dump(mode="json")
        parsed = {
            "predicted_label": "review",
            "confidence": 0.9,
            "damage_causality_assessment": {"damage_presence": "not_visible", "claim_support": "not_supported"},
            "damage_observability": {
                "status": "partial",
                "same_item_linkage": True,
                "claimed_region_closeup": False,
                "required_view_coverage": 0.8,
                "conflicting_evidence": False,
            },
            "object_continuity_assessment": {
                "continuity_verdict": "continuous",
                "longest_out_of_frame_seconds": 0,
                "tracked_subjects": [{"subject_id": "claimed_item", "visibility_coverage": 0.95}],
            },
            "video_audit_conclusion": {"opening_integrity": "complete"},
        }
        result = apply_review_decision_policy(
            {
                "scenario": "product_damage",
                "metadata": metadata,
                "assets": [{"mime_type": "video/mp4"}],
            },
            review(parsed),
        )
        self.assertEqual(result["summary"]["predicted_label"], "review")
        self.assertFalse(result["decision_policy_audit"]["applied"])

    def test_resolved_claim_scope_is_required_for_rule_classification(self):
        metadata = ReviewCaseMetadata.model_validate(
            {
                "client_case_id": "case-614176",
                "scenario": "product_damage",
                "customer_claim": "鼓包、撞角、缝线和后续撕拉片争议",
                "claim_scope": {"split_status": "ambiguous"},
                "decision_policy": {
                    "mode": "classification_recommendation",
                    "policy_ref": "MITAKO-PD-20260717@1",
                    "opening_video_required": True,
                    "missing_required_opening_video": "negative",
                },
            }
        ).model_dump(mode="json")
        result = apply_review_decision_policy(
            {"scenario": "product_damage", "metadata": metadata, "assets": []},
            review(),
        )
        self.assertEqual(result["summary"]["predicted_label"], "review")
        self.assertIn("诉求范围", result["decision_policy_audit"]["reason"])


if __name__ == "__main__":
    unittest.main()
