# -*- coding: utf-8 -*-
import unittest

from review_service.decision_policy import (
    DEFAULT_PRODUCT_DAMAGE_POLICY_REF,
    apply_review_decision_policy,
)
from review_service.schemas import ReviewCaseMetadata


def review(parsed=None):
    parsed = parsed or {"predicted_label": "review", "confidence": 0.69}
    return {"agent_report": {"parsed": parsed}, "summary": {"predicted_label": "review", "confidence": 0.69}}


class ReviewDecisionPolicy0717Test(unittest.TestCase):
    def test_default_policy_gives_sop_tendency_without_optional_hard_gates(self):
        metadata = ReviewCaseMetadata.model_validate(
            {
                "client_case_id": "case-default-sop",
                "scenario": "product_damage",
                "customer_claim": "商品表面有划痕",
                "claim_scope": {
                    "split_status": "resolved",
                    "active_claim_ids": ["CLM-1"],
                    "claims": [{"claim_id": "CLM-1", "issue_type": "visible_damage"}],
                },
                "decision_policy": {
                    "mode": "classification_recommendation",
                    "policy_ref": DEFAULT_PRODUCT_DAMAGE_POLICY_REF,
                },
            }
        ).model_dump(mode="json")
        parsed = {
            "predicted_label": "review",
            "confidence": 0.69,
            "damage_causality_assessment": {
                "damage_presence": "not_visible",
                "claim_support": "not_supported",
                "evidence_source_summary": {
                    "supplemental_images": {
                        "provided_count": 1,
                        "referenced_count": 1,
                        "linkage_status": "verified",
                    }
                },
            },
            "damage_observability": {
                "status": "partial",
                "same_item_linkage": False,
                "claimed_region_closeup": False,
                "required_view_coverage": 0.7,
                "conflicting_evidence": False,
            },
            "object_continuity_assessment": {
                "continuity_verdict": "continuous",
                "tracked_subjects": [{
                    "subject_id": "claimed_item",
                    "visibility_coverage": 0.75,
                    "longest_out_of_frame_seconds": 0.0,
                }],
            },
            "video_audit_conclusion": {
                "opening_integrity": "complete",
                "opening_integrity_source": "full_timeline_continuity",
                "sampling_boundary_status": "covered",
            },
            "pass_integrity_status": "partial_specialized",
        }

        result = apply_review_decision_policy(
            {
                "tenant_id": "mitako",
                "scenario": "product_damage",
                "metadata": metadata,
                "assets": [{"mime_type": "video/mp4"}],
            },
            review(parsed),
            media_forensics={"status": "unavailable", "summary": {"risk_level": "unknown"}},
        )

        self.assertEqual(result["summary"]["predicted_label"], "negative")
        self.assertEqual(result["decision_policy_audit"]["rule_id"], "PD-N-COMPLETE-NO-CLAIMED-DAMAGE")

    def _complete_no_damage_case(
        self,
        policy_overrides=None,
        parsed_overrides=None,
        requested_overrides=None,
        media_forensics=None,
    ):
        policy = {
            "mode": "classification_recommendation",
            "policy_ref": "MITAKO-PD-COMPLETE-NO-DAMAGE@CONFIG-TEST",
            "complete_video_no_claimed_damage": "negative",
            "require_claim_scope": True,
            "minimum_visibility_coverage": 0.95,
            "minimum_required_view_coverage": 1.0,
            "minimum_confidence": 0.8,
            "require_continuity_complete": True,
            "require_fully_observable": True,
            "require_claimed_region_closeup": True,
            "require_same_item_linkage": True,
            "require_media_forensics": True,
            "maximum_forensic_risk": "low",
            "max_unobserved_seconds": 0.0,
        }
        policy.update(policy_overrides or {})
        metadata = ReviewCaseMetadata.model_validate(
            {
                "client_case_id": "case-configurable-policy",
                "scenario": "product_damage",
                "customer_claim": "商品存在可见损伤",
                "claim_scope": {
                    "split_status": "resolved",
                    "active_claim_ids": ["CLM-1"],
                    "claims": [{"claim_id": "CLM-1", "issue_type": "visible_damage"}],
                },
                "decision_policy": {
                    "mode": "classification_recommendation",
                    "policy_ref": policy["policy_ref"],
                    **(requested_overrides or {}),
                },
            }
        ).model_dump(mode="json")
        parsed = {
            "predicted_label": "review",
            "confidence": 0.9,
            "damage_causality_assessment": {
                "damage_presence": "not_visible",
                "claim_support": "not_supported",
                "evidence_source_summary": {
                    "supplemental_images": {
                        "provided_count": 0,
                        "referenced_count": 0,
                        "linkage_status": "not_provided",
                    }
                },
            },
            "damage_observability": {
                "status": "fully_observable",
                "same_item_linkage": True,
                "claimed_region_closeup": True,
                "required_view_coverage": 1.0,
                "conflicting_evidence": False,
            },
            "object_continuity_assessment": {
                "continuity_verdict": "continuous",
                "tracked_subjects": [{
                    "subject_id": "claimed_item",
                    "visibility_coverage": 1.0,
                    "longest_out_of_frame_seconds": 0.0,
                }],
            },
            "video_audit_conclusion": {
                "opening_integrity": "complete",
                "opening_integrity_source": "full_timeline_continuity",
                "sampling_boundary_status": "covered",
            },
        }
        for key, value in (parsed_overrides or {}).items():
            if isinstance(value, dict) and isinstance(parsed.get(key), dict):
                parsed[key].update(value)
            else:
                parsed[key] = value
        result = apply_review_decision_policy(
            {
                "tenant_id": "mitako",
                "scenario": "product_damage",
                "metadata": metadata,
                "assets": [{"mime_type": "video/mp4"}],
            },
            review(parsed),
            media_forensics=(
                {"status": "completed", "summary": {"risk_level": "low"}}
                if media_forensics is None
                else media_forensics
            ),
            approved_policies={
                ("mitako", policy["policy_ref"]): policy,
            },
        )
        return result

    def test_complete_no_damage_uses_each_server_approved_evidence_threshold(self):
        cases = [
            (
                "minimum_visibility_coverage",
                {"minimum_visibility_coverage": 0.85},
                {"object_continuity_assessment": {"tracked_subjects": [{
                    "subject_id": "claimed_item",
                    "visibility_coverage": 0.9,
                    "longest_out_of_frame_seconds": 0.0,
                }]}},
            ),
            (
                "minimum_required_view_coverage",
                {"minimum_required_view_coverage": 0.8},
                {"damage_observability": {"required_view_coverage": 0.85}},
            ),
            (
                "require_continuity_complete",
                {"require_continuity_complete": False},
                {"object_continuity_assessment": {"continuity_verdict": "indeterminate"}},
            ),
            (
                "require_fully_observable",
                {"require_fully_observable": False},
                {"damage_observability": {"status": "partial"}},
            ),
            (
                "require_claimed_region_closeup",
                {"require_claimed_region_closeup": False},
                {"damage_observability": {"claimed_region_closeup": False}},
            ),
            (
                "require_same_item_linkage",
                {"require_same_item_linkage": False},
                {"damage_observability": {"same_item_linkage": False}},
            ),
            (
                "max_unobserved_seconds",
                {"max_unobserved_seconds": 3.0},
                {"object_continuity_assessment": {"tracked_subjects": [{
                    "subject_id": "claimed_item",
                    "visibility_coverage": 1.0,
                    "longest_out_of_frame_seconds": 2.5,
                }]}},
            ),
            (
                "require_media_forensics",
                {"require_media_forensics": False},
                {},
                {},
            ),
        ]
        for case in cases:
            field, policy_overrides, parsed_overrides, *optional = case
            with self.subTest(field=field):
                result = self._complete_no_damage_case(
                    policy_overrides,
                    parsed_overrides,
                    media_forensics=optional[0] if optional else None,
                )
                self.assertEqual(result["summary"]["predicted_label"], "negative")
                self.assertTrue(result["decision_policy_audit"]["applied"])

    def test_request_overrides_cannot_weaken_server_approved_snapshot(self):
        strict_policy = {
            "mode": "classification_recommendation",
            "policy_ref": "MITAKO-PD-COMPLETE-NO-DAMAGE@STRICT",
            "complete_video_no_claimed_damage": "negative",
            "require_claim_scope": True,
            "minimum_visibility_coverage": 0.95,
            "minimum_required_view_coverage": 1.0,
            "minimum_confidence": 0.8,
            "require_continuity_complete": True,
            "require_fully_observable": True,
            "require_claimed_region_closeup": True,
            "require_same_item_linkage": True,
            "require_media_forensics": True,
            "maximum_forensic_risk": "low",
            "max_unobserved_seconds": 0.0,
        }
        result = self._complete_no_damage_case(
            strict_policy,
            {
                "damage_observability": {
                    "status": "partial",
                    "same_item_linkage": False,
                    "claimed_region_closeup": False,
                    "required_view_coverage": 0.5,
                },
                "object_continuity_assessment": {
                    "continuity_verdict": "indeterminate",
                    "tracked_subjects": [{
                        "subject_id": "claimed_item",
                        "visibility_coverage": 0.5,
                        "longest_out_of_frame_seconds": 10.0,
                    }],
                },
            },
            requested_overrides={
                "minimum_visibility_coverage": 0.5,
                "minimum_required_view_coverage": 0.5,
                "require_continuity_complete": False,
                "require_fully_observable": False,
                "require_claimed_region_closeup": False,
                "require_same_item_linkage": False,
                "require_media_forensics": False,
                "max_unobserved_seconds": 30.0,
            },
        )
        self.assertEqual(result["summary"]["predicted_label"], "review")
        self.assertFalse(result["decision_policy_audit"]["applied"])
        self.assertIn(
            "minimum_visibility_coverage",
            result["decision_policy_audit"]["requested_overrides_ignored"],
        )

    def test_default_policy_without_claim_text_never_turns_missing_video_into_negative(self):
        metadata = ReviewCaseMetadata(
            client_case_id="case-default",
            scenario="product_damage",
            customer_claim="",
        ).model_dump(mode="json")
        result = apply_review_decision_policy(
            {"tenant_id": "mitako", "scenario": "product_damage", "metadata": metadata, "assets": []},
            review(),
        )
        self.assertEqual(result["summary"]["predicted_label"], "review")
        self.assertFalse(result["decision_policy_audit"]["applied"])
        audit = result["agent_report"]["parsed"]["decision_policy_audit"]
        self.assertFalse(audit["claim_scope"]["ready"])

    def test_default_policy_uses_typed_scenario_instead_of_claim_keywords(self):
        metadata = ReviewCaseMetadata(
            client_case_id="case-single-damage",
            scenario="product_damage",
            customer_claim="请审查当前材料",
        ).model_dump(mode="json")
        result = apply_review_decision_policy(
            {"tenant_id": "mitako", "scenario": "product_damage", "metadata": metadata, "assets": []},
            review(),
        )
        audit = result["agent_report"]["parsed"]["decision_policy_audit"]
        self.assertTrue(audit["claim_scope"]["ready"])
        self.assertEqual(audit["claim_scope"]["split_status"], "single_legacy")
        self.assertEqual(audit["claim_scope"]["issue_types"], ["product_damage"])

    def test_typed_product_damage_task_does_not_parse_mixed_claim_keywords(self):
        metadata = ReviewCaseMetadata(
            client_case_id="case-mixed-claim",
            scenario="product_damage",
            customer_claim="商品有伤并且漏发特典",
        ).model_dump(mode="json")
        result = apply_review_decision_policy(
            {"tenant_id": "mitako", "scenario": "product_damage", "metadata": metadata, "assets": []},
            review(),
        )
        audit = result["decision_policy_audit"]["claim_scope"]
        self.assertTrue(audit["ready"])
        self.assertEqual(audit["issue_types"], ["product_damage"])

    def test_noncompliant_opening_video_recommends_negative_but_keeps_supplemental_reference(self):
        metadata = ReviewCaseMetadata.model_validate(
            {
                "client_case_id": "case-615437",
                "scenario": "product_damage",
                "customer_claim": "商品表面有胶痕",
                "decision_policy": {
                    "mode": "classification_recommendation",
                    "policy_ref": DEFAULT_PRODUCT_DAMAGE_POLICY_REF,
                },
            }
        ).model_dump(mode="json")
        parsed = {
            "predicted_label": "positive",
            "confidence": 0.82,
            "damage_causality_assessment": {
                "damage_presence": "not_visible",
                "claim_support": "not_supported",
                "evidence_source_summary": {
                    "supplemental_images": {
                        "provided_count": 3,
                        "referenced_count": 3,
                        "linkage_status": "verified",
                    }
                },
            },
            "object_continuity_assessment": {
                "continuity_verdict": "long_absence",
                "tracked_subjects": [{
                    "subject_id": "claimed_item",
                    "visibility_coverage": 0.55,
                    "longest_out_of_frame_seconds": 8.2,
                }],
            },
            "video_audit_conclusion": {
                "opening_integrity": "incomplete",
                "opening_integrity_source": "full_timeline_continuity",
                "sampling_boundary_status": "covered",
                "playback_speed": "normal",
            },
        }
        result = apply_review_decision_policy(
            {
                "tenant_id": "mitako",
                "scenario": "product_damage",
                "metadata": metadata,
                "assets": [{"mime_type": "video/mp4"}],
            },
            review(parsed),
            media_forensics={"status": "completed", "summary": {"risk_level": "low"}},
        )
        audit = result["decision_policy_audit"]
        self.assertEqual(result["summary"]["predicted_label"], "negative")
        self.assertEqual(audit["rule_id"], "PD-N-NONCOMPLIANT-OPENING-VIDEO")
        self.assertIn("最低档补偿", audit["supplemental_evidence_note"])
        self.assertTrue(result["agent_report"]["parsed"]["human_required_for_business_action"])

    def test_acceleration_alone_never_makes_opening_video_noncompliant(self):
        result = self._complete_no_damage_case(
            policy_overrides={"noncompliant_opening_video": "negative"},
            parsed_overrides={
                "predicted_label": "positive",
                "damage_causality_assessment": {
                    "damage_presence": "confirmed",
                    "claim_support": "supported",
                },
                "video_audit_conclusion": {
                    "opening_integrity": "complete",
                    "opening_integrity_source": "full_timeline_continuity",
                    "sampling_boundary_status": "covered",
                    "playback_speed": "accelerated",
                },
            },
        )
        self.assertNotEqual(result["decision_policy_audit"].get("rule_id"), "PD-N-NONCOMPLIANT-OPENING-VIDEO")

    def test_previous_policy_snapshot_keeps_its_original_noncompliant_video_behavior(self):
        metadata = ReviewCaseMetadata.model_validate(
            {
                "client_case_id": "case-policy-history",
                "scenario": "product_damage",
                "customer_claim": "商品表面有划痕",
                "decision_policy": {
                    "mode": "classification_recommendation",
                    "policy_ref": "MITAKO-PD-ADVISORY@20260728.1",
                },
            }
        ).model_dump(mode="json")
        parsed = {
            "predicted_label": "review",
            "confidence": 0.7,
            "damage_causality_assessment": {
                "damage_presence": "not_visible",
                "claim_support": "not_supported",
            },
            "video_audit_conclusion": {
                "opening_integrity": "incomplete",
                "opening_integrity_source": "full_timeline_continuity",
                "sampling_boundary_status": "covered",
            },
        }
        result = apply_review_decision_policy(
            {
                "tenant_id": "mitako",
                "scenario": "product_damage",
                "metadata": metadata,
                "assets": [{"mime_type": "video/mp4"}],
            },
            review(parsed),
        )

        self.assertEqual(result["summary"]["predicted_label"], "review")
        self.assertFalse(result["decision_policy_audit"]["applied"])

    def test_noncompliant_long_absence_precedes_visible_damage_fact(self):
        result = self._complete_no_damage_case(
            policy_overrides={"noncompliant_opening_video": "negative"},
            parsed_overrides={
                "predicted_label": "positive",
                "damage_causality_assessment": {
                    "damage_presence": "confirmed",
                    "claim_support": "supported",
                },
                "object_continuity_assessment": {
                    "continuity_verdict": "long_absence",
                    "claimed_item_timeline_complete": True,
                    "claimed_item_reference_status": "available",
                    "tracked_subjects": [{
                        "subject_id": "claimed_item",
                        "visibility_coverage": 0.6,
                        "longest_out_of_frame_seconds": 8.0,
                    }],
                },
                "video_audit_conclusion": {
                    "opening_integrity": "incomplete",
                    "opening_integrity_source": "full_timeline_continuity",
                    "sampling_boundary_status": "covered",
                },
            },
        )
        audit = result["decision_policy_audit"]
        self.assertEqual(audit.get("rule_id"), "PD-N-NONCOMPLIANT-OPENING-VIDEO")
        self.assertEqual(result["summary"]["predicted_label"], "negative")
        self.assertEqual(audit["evidence_verdict_before_policy"]["predicted_label"], "positive")

    def test_complete_reference_anchored_timeline_without_claimed_item_recommends_negative(self):
        result = self._complete_no_damage_case(
            policy_overrides={"noncompliant_opening_video": "negative"},
            parsed_overrides={
                "predicted_label": "review",
                "damage_causality_assessment": {
                    "damage_presence": "uncertain",
                    "claim_support": "insufficient",
                },
                "object_continuity_assessment": {
                    "continuity_verdict": "indeterminate",
                    "tracked_subjects": [],
                    "claimed_item_never_exposed": True,
                    "claimed_item_timeline_complete": True,
                    "claimed_item_reference_status": "available",
                },
                "video_audit_conclusion": {
                    "opening_integrity": "indeterminate",
                    "opening_integrity_source": "full_timeline_continuity",
                    "sampling_boundary_status": "covered",
                },
            },
        )

        self.assertEqual(result["summary"]["predicted_label"], "negative")
        self.assertEqual(result["decision_policy_audit"]["rule_id"], "PD-N-CLAIMED-ITEM-NOT-SHOWN")

    def test_unresolved_long_absence_on_complete_reference_timeline_is_noncompliant(self):
        result = self._complete_no_damage_case(
            policy_overrides={"noncompliant_opening_video": "negative"},
            parsed_overrides={
                "predicted_label": "review",
                "damage_causality_assessment": {
                    "damage_presence": "uncertain",
                    "claim_support": "insufficient",
                },
                "object_continuity_assessment": {
                    "continuity_verdict": "indeterminate",
                    "claimed_item_timeline_complete": True,
                    "claimed_item_reference_status": "available",
                    "tracked_subjects": [{
                        "subject_id": "claimed_item",
                        "visibility_coverage": 0.16,
                        "longest_out_of_frame_seconds": 93.86,
                    }],
                },
                "video_audit_conclusion": {
                    "opening_integrity": "indeterminate",
                    "opening_integrity_source": "full_timeline_continuity",
                    "sampling_boundary_status": "covered",
                },
            },
        )

        self.assertEqual(result["summary"]["predicted_label"], "negative")
        self.assertEqual(result["decision_policy_audit"]["rule_id"], "PD-N-NONCOMPLIANT-OPENING-VIDEO")

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
                    "policy_ref": "MITAKO-PD-MISSING-OPENING@20260717.1",
                    "opening_video_required": True,
                    "missing_required_opening_video": "negative",
                },
            }
        ).model_dump(mode="json")
        result = apply_review_decision_policy(
            {"tenant_id": "mitako", "scenario": "product_damage", "metadata": metadata, "assets": []},
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
                    "policy_ref": "MITAKO-PD-COMPLETE-NO-DAMAGE@TEST",
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
            approved_policies={
                "MITAKO-PD-COMPLETE-NO-DAMAGE@TEST": metadata["decision_policy"],
            },
        )
        self.assertEqual(result["summary"]["predicted_label"], "review")
        self.assertFalse(result["decision_policy_audit"]["applied"])
        self.assertIn("damage_observability", result["agent_report"]["parsed"]["decision_policy_audit"]["failed_conditions"])

    def test_unresolved_supplemental_image_linkage_blocks_negative_recommendation(self):
        metadata = ReviewCaseMetadata.model_validate(
            {
                "client_case_id": "case-supplement-unresolved",
                "scenario": "product_damage",
                "customer_claim": "商品有明显折痕",
                "claim_scope": {
                    "split_status": "resolved",
                    "active_claim_ids": ["CLM-1"],
                    "claims": [{"claim_id": "CLM-1", "issue_type": "visible_damage", "location": "商品本体"}],
                },
                "decision_policy": {
                    "mode": "classification_recommendation",
                    "policy_ref": "MITAKO-PD-COMPLETE-NO-DAMAGE@TEST",
                    "complete_video_no_claimed_damage": "negative",
                    "require_continuity_complete": False,
                    "require_fully_observable": False,
                    "require_claimed_region_closeup": False,
                    "minimum_required_view_coverage": 0.8,
                    "max_unobserved_seconds": 12.0,
                },
            }
        ).model_dump(mode="json")
        parsed = {
            "predicted_label": "review",
            "confidence": 0.9,
            "damage_causality_assessment": {
                "damage_presence": "not_visible",
                "claim_support": "not_supported",
                "evidence_source_summary": {
                    "supplemental_images": {"provided_count": 1, "linkage_status": "unresolved"},
                },
            },
            "damage_observability": {
                "status": "partial",
                "same_item_linkage": True,
                "claimed_region_closeup": False,
                "required_view_coverage": 0.8,
                "conflicting_evidence": False,
            },
            "object_continuity_assessment": {
                "continuity_verdict": "indeterminate",
                "tracked_subjects": [{
                    "subject_id": "claimed_item",
                    "visibility_coverage": 0.9,
                    "longest_out_of_frame_seconds": 1.0,
                }],
            },
            "video_audit_conclusion": {
                "opening_integrity": "complete",
                "sampling_boundary_status": "covered",
            },
        }
        result = apply_review_decision_policy(
            {"scenario": "product_damage", "metadata": metadata, "assets": [{"mime_type": "video/mp4"}]},
            review(parsed),
            media_forensics={"status": "completed", "summary": {"risk_level": "low"}},
            approved_policies={
                "MITAKO-PD-COMPLETE-NO-DAMAGE@TEST": metadata["decision_policy"],
            },
        )
        self.assertEqual(result["summary"]["predicted_label"], "review")
        self.assertIn(
            "supplemental_evidence_resolved",
            result["agent_report"]["parsed"]["decision_policy_audit"]["failed_conditions"],
        )

    def test_617911_only_strict_full_timeline_policy_can_recommend_negative(self):
        metadata = ReviewCaseMetadata.model_validate(
            {
                "client_case_id": "case-617911-policy-v2",
                "scenario": "product_damage",
                "customer_claim": "商品有明显折痕",
                "claim_scope": {
                    "split_status": "resolved",
                    "active_claim_ids": ["CLM-1"],
                    "claims": [{"claim_id": "CLM-1", "issue_type": "visible_damage", "location": "商品本体"}],
                },
                "decision_policy": {
                    "mode": "classification_recommendation",
                    "policy_ref": "MITAKO-PD-COMPLETE-NO-DAMAGE@TEST",
                    "complete_video_no_claimed_damage": "negative",
                    "minimum_visibility_coverage": 0.85,
                    "minimum_required_view_coverage": 1.0,
                    "minimum_confidence": 0.8,
                    "require_continuity_complete": True,
                    "require_fully_observable": True,
                    "require_claimed_region_closeup": True,
                    "max_unobserved_seconds": 0.0,
                    "require_media_forensics": True,
                },
            }
        ).model_dump(mode="json")
        parsed = {
            "predicted_label": "review",
            "confidence": 0.9,
            "damage_causality_assessment": {
                "damage_presence": "not_visible",
                "claim_support": "not_supported",
                "evidence_source_summary": {
                    "supplemental_images": {
                        "provided_count": 5,
                        "referenced_count": 5,
                        "linkage_status": "not_linked",
                    },
                },
            },
            "damage_observability": {
                "status": "fully_observable",
                "same_item_linkage": True,
                "claimed_region_closeup": True,
                "required_view_coverage": 1.0,
                "conflicting_evidence": False,
            },
            "object_continuity_assessment": {
                "continuity_verdict": "continuous",
                "tracked_subjects": [{
                    "subject_id": "claimed_item",
                    "visibility_coverage": 1.0,
                    "longest_out_of_frame_seconds": 0.0,
                }],
            },
            "video_audit_conclusion": {
                "opening_integrity": "complete",
                "opening_integrity_source": "full_timeline_continuity",
                "sampling_boundary_status": "covered",
            },
        }
        forensics = {"status": "completed", "summary": {"risk_level": "low"}}

        result = apply_review_decision_policy(
            {"scenario": "product_damage", "metadata": metadata, "assets": [{"mime_type": "video/mp4"}]},
            review(parsed),
            media_forensics=forensics,
            approved_policies={
                "MITAKO-PD-COMPLETE-NO-DAMAGE@TEST": metadata["decision_policy"],
            },
        )

        self.assertEqual(result["summary"]["predicted_label"], "negative")
        self.assertEqual(result["decision_policy_audit"]["rule_id"], "PD-N-COMPLETE-NO-CLAIMED-DAMAGE")
        self.assertEqual(result["decision_policy_audit"]["evidence_gate"]["media_forensics_status"], "completed")
        self.assertFalse(result["agent_report"]["parsed"]["business_action_allowed"])

    def test_partial_pass_or_aggregation_warning_blocks_negative(self):
        metadata = ReviewCaseMetadata.model_validate(
            {
                "client_case_id": "case-degraded-policy",
                "scenario": "product_damage",
                "customer_claim": "商品有明显折痕",
                "claim_scope": {
                    "split_status": "resolved",
                    "active_claim_ids": ["CLM-1"],
                    "claims": [{"claim_id": "CLM-1", "issue_type": "visible_damage"}],
                },
                "decision_policy": {
                    "mode": "classification_recommendation",
                    "policy_ref": "MITAKO-PD-COMPLETE-NO-DAMAGE@TEST",
                    "complete_video_no_claimed_damage": "negative",
                },
            }
        ).model_dump(mode="json")
        parsed = {
            "predicted_label": "review",
            "confidence": 0.9,
            "specialized_pass_guard_reason": "主审核存在失败",
            "aggregation_warnings": [{"code": "chunk_conflict"}],
            "damage_causality_assessment": {"damage_presence": "not_visible", "claim_support": "not_supported"},
            "damage_observability": {
                "status": "fully_observable",
                "same_item_linkage": True,
                "claimed_region_closeup": True,
                "required_view_coverage": 1.0,
                "conflicting_evidence": False,
            },
            "object_continuity_assessment": {
                "continuity_verdict": "continuous",
                "tracked_subjects": [{"subject_id": "claimed_item", "visibility_coverage": 1.0, "longest_out_of_frame_seconds": 0.0}],
            },
            "video_audit_conclusion": {
                "opening_integrity": "complete",
                "opening_integrity_source": "full_timeline_continuity",
                "sampling_boundary_status": "covered",
            },
        }
        result = apply_review_decision_policy(
            {"scenario": "product_damage", "metadata": metadata, "assets": [{"mime_type": "video/mp4"}]},
            review(parsed),
            media_forensics={"status": "completed", "summary": {"risk_level": "low"}},
            approved_policies={"MITAKO-PD-COMPLETE-NO-DAMAGE@TEST": metadata["decision_policy"]},
        )

        self.assertEqual(result["summary"]["predicted_label"], "review")
        self.assertIn("pass_integrity", result["decision_policy_audit"]["failed_conditions"])

    def test_partial_supplemental_review_cannot_be_treated_as_all_not_linked(self):
        metadata = ReviewCaseMetadata.model_validate(
            {
                "client_case_id": "case-partial-supplement",
                "scenario": "product_damage",
                "customer_claim": "商品有明显折痕",
                "claim_scope": {
                    "split_status": "resolved",
                    "active_claim_ids": ["CLM-1"],
                    "claims": [{"claim_id": "CLM-1", "issue_type": "visible_damage"}],
                },
                "decision_policy": {
                    "mode": "classification_recommendation",
                    "policy_ref": "MITAKO-PD-COMPLETE-NO-DAMAGE@TEST",
                    "complete_video_no_claimed_damage": "negative",
                    "require_continuity_complete": False,
                    "require_fully_observable": False,
                    "require_claimed_region_closeup": False,
                    "minimum_required_view_coverage": 0.8,
                    "max_unobserved_seconds": 12.0,
                },
            }
        ).model_dump(mode="json")
        parsed = {
            "predicted_label": "review",
            "confidence": 0.9,
            "damage_causality_assessment": {
                "damage_presence": "not_visible",
                "claim_support": "not_supported",
                "evidence_source_summary": {
                    "supplemental_images": {
                        "provided_count": 5,
                        "referenced_count": 2,
                        "linkage_status": "not_linked",
                    }
                },
            },
            "damage_observability": {
                "status": "partial",
                "same_item_linkage": True,
                "claimed_region_closeup": False,
                "required_view_coverage": 0.8,
                "conflicting_evidence": False,
            },
            "object_continuity_assessment": {
                "continuity_verdict": "indeterminate",
                "tracked_subjects": [{
                    "subject_id": "claimed_item",
                    "visibility_coverage": 0.9,
                    "longest_out_of_frame_seconds": 1.0,
                }],
            },
            "video_audit_conclusion": {
                "opening_integrity": "complete",
                "sampling_boundary_status": "covered",
            },
        }
        result = apply_review_decision_policy(
            {
                "tenant_id": "mitako",
                "scenario": "product_damage",
                "metadata": metadata,
                "assets": [{"mime_type": "video/mp4"}],
            },
            review(parsed),
            media_forensics={"status": "completed", "summary": {"risk_level": "low"}},
            approved_policies={
                "MITAKO-PD-COMPLETE-NO-DAMAGE@TEST": metadata["decision_policy"],
            },
        )
        self.assertEqual(result["summary"]["predicted_label"], "review")
        self.assertIn("supplemental_evidence_resolved", result["decision_policy_audit"]["failed_conditions"])

    def test_production_policy_is_tenant_scoped(self):
        metadata = ReviewCaseMetadata.model_validate(
            {
                "client_case_id": "case-tenant-policy",
                "scenario": "product_damage",
                "customer_claim": "商品有明显折痕",
                "claim_scope": {
                    "split_status": "resolved",
                    "active_claim_ids": ["CLM-1"],
                    "claims": [{"claim_id": "CLM-1", "issue_type": "visible_damage"}],
                },
                "decision_policy": {
                    "mode": "classification_recommendation",
                    "policy_ref": "MITAKO-PD-COMPLETE-NO-DAMAGE@20260720.1",
                },
            }
        ).model_dump(mode="json")
        result = apply_review_decision_policy(
            {"tenant_id": "other-tenant", "scenario": "product_damage", "metadata": metadata, "assets": []},
            review(),
        )
        self.assertEqual(result["decision_policy_audit"]["policy_source"], "not_approved")

    def test_resolved_claim_scope_is_required_for_rule_classification(self):
        metadata = ReviewCaseMetadata.model_validate(
            {
                "client_case_id": "case-614176",
                "scenario": "product_damage",
                "customer_claim": "鼓包、撞角、缝线和后续撕拉片争议",
                "claim_scope": {"split_status": "ambiguous"},
                "decision_policy": {
                    "mode": "classification_recommendation",
                    "policy_ref": "MITAKO-PD-MISSING-OPENING@20260717.1",
                    "opening_video_required": True,
                    "missing_required_opening_video": "negative",
                },
            }
        ).model_dump(mode="json")
        result = apply_review_decision_policy(
            {"tenant_id": "mitako", "scenario": "product_damage", "metadata": metadata, "assets": []},
            review(),
        )
        self.assertEqual(result["summary"]["predicted_label"], "review")
        self.assertIn("诉求范围", result["decision_policy_audit"]["reason"])

    def test_request_cannot_activate_unapproved_or_weakened_policy(self):
        metadata = ReviewCaseMetadata.model_validate(
            {
                "client_case_id": "case-attacker-policy",
                "scenario": "product_damage",
                "customer_claim": "商品有伤",
                "claim_scope": {
                    "split_status": "resolved",
                    "active_claim_ids": ["CLM-1"],
                    "claims": [{"claim_id": "CLM-1", "issue_type": "visible_damage"}],
                },
                "decision_policy": {
                    "mode": "classification_recommendation",
                    "policy_ref": "ATTACKER-SUPPLIED",
                    "complete_video_no_claimed_damage": "negative",
                    "require_continuity_complete": False,
                    "require_media_forensics": False,
                },
            }
        ).model_dump(mode="json")
        result = apply_review_decision_policy(
            {"scenario": "product_damage", "metadata": metadata, "assets": [{"mime_type": "video/mp4"}]},
            review({"predicted_label": "review", "confidence": 0.99}),
        )
        self.assertEqual(result["summary"]["predicted_label"], "review")
        self.assertEqual(result["decision_policy_audit"]["policy_source"], "not_approved")
        self.assertIn("未在服务端批准", result["decision_policy_audit"]["reason"])


if __name__ == "__main__":
    unittest.main()
