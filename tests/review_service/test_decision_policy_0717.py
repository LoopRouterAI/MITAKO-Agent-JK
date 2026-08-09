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
    def _default_visible_damage_case(
        self,
        damage_overrides=None,
        continuity_overrides=None,
        video_overrides=None,
        fact_overrides=None,
        active_claim_ids=None,
        confidence=0.88,
    ):
        active_claim_ids = active_claim_ids or ["CLM-1"]
        metadata = ReviewCaseMetadata.model_validate(
            {
                "client_case_id": "case-visible-damage-sop-order",
                "scenario": "product_damage",
                "customer_claim": "商品拆封后发现断裂",
                "claim_scope": {
                    "split_status": "resolved",
                    "active_claim_ids": active_claim_ids,
                    "claims": [
                        {"claim_id": claim_id, "issue_type": "visible_damage"}
                        for claim_id in active_claim_ids
                    ],
                },
                "decision_policy": {
                    "mode": "classification_recommendation",
                    "policy_ref": DEFAULT_PRODUCT_DAMAGE_POLICY_REF,
                },
            }
        ).model_dump(mode="json")
        damage = {
            "damage_presence": "confirmed",
            "claim_support": "supported",
            "damage_timing": "pre_opening_visible",
            "damage_change_observed": False,
            "first_visible_evidence": {
                "video_index": 1,
                "global_frame_index": 18,
                "damage_visible": True,
            },
            "evidence_source_summary": {
                "primary_video": {
                    "damage_presence": "confirmed",
                    "claim_support": "supported",
                },
                "supplemental_images": {
                    "provided_count": 1,
                    "referenced_count": 1,
                    "linkage_status": "unresolved",
                },
            },
        }
        damage.update(damage_overrides or {})
        continuity = {
            "continuity_verdict": "continuous",
            "claimed_item_timeline_complete": True,
            "claimed_item_reference_status": "available",
            "tracked_subjects": [{
                "subject_id": "claimed_item",
                "visibility_coverage": 0.95,
                "longest_out_of_frame_seconds": 0.0,
            }],
        }
        continuity.update(continuity_overrides or {})
        video_audit = {
            "opening_integrity": "complete",
            "opening_integrity_source": "full_timeline_continuity",
            "sampling_boundary_status": "covered",
        }
        video_audit.update(video_overrides or {})
        parsed = {
            "predicted_label": "review",
            "confidence": confidence,
            "damage_causality_assessment": damage,
            "object_continuity_assessment": continuity,
            "video_audit_conclusion": video_audit,
            "claim_fact_assessment": fact_overrides or {},
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
        return result

    def test_explicit_order_package_linkage_failure_blocks_damage_attribution(self):
        result = self._default_visible_damage_case(
            fact_overrides={
                "order_linkage": {
                    "status": "failed",
                    "reason": "目标订单包裹与送审视频中的承运商标识明确不一致。",
                }
            }
        )

        self.assertEqual(result["summary"]["predicted_label"], "review")
        self.assertEqual(result["decision_policy_audit"]["rule_id"], "PD-R-ORDER-LINKAGE-FAILED")

    def test_packaging_provenance_claim_does_not_enter_physical_damage_rule(self):
        result = self._default_visible_damage_case(
            fact_overrides={
                "scene_match": {
                    "status": "mismatched",
                    "claimed_scene": "packaging_provenance",
                    "observed_scene": "product_physical_damage",
                    "reason": "本次诉求关注包装来源，不能按商品实体损伤规则归类。",
                }
            }
        )

        self.assertEqual(result["summary"]["predicted_label"], "review")
        self.assertEqual(result["decision_policy_audit"]["rule_id"], "PD-R-CLAIM-SCENE-MISMATCH")

    def test_successfully_resolved_assembly_issue_is_not_permanent_damage(self):
        result = self._default_visible_damage_case(
            fact_overrides={
                "assembly": {
                    "state": "resolved_assembly_issue",
                    "reassembly_result": "successful",
                    "permanent_damage": "not_supported",
                    "evidence_refs": [{"video_index": 1, "global_frame_index": 24}],
                }
            }
        )

        self.assertEqual(result["summary"]["predicted_label"], "negative")
        self.assertEqual(result["decision_policy_audit"]["rule_id"], "PD-N-RESOLVED-ASSEMBLY-ISSUE")

    def test_multi_claim_case_cannot_aggregate_when_an_atomic_result_is_missing(self):
        result = self._default_visible_damage_case(
            active_claim_ids=["CLM-1", "CLM-2"],
            fact_overrides={
                "atomic_claim_results": [{
                    "claim_id": "CLM-1",
                    "subject_ref": "SKU-1",
                    "support_status": "supported",
                    "evidence_refs": [{"video_index": 1, "global_frame_index": 18}],
                }]
            },
        )

        self.assertEqual(result["summary"]["predicted_label"], "review")
        self.assertEqual(result["decision_policy_audit"]["rule_id"], "PD-R-ATOMIC-CLAIM-INCOMPLETE")

    def test_multi_claim_case_can_aggregate_after_every_atomic_result_is_anchored(self):
        result = self._default_visible_damage_case(
            active_claim_ids=["CLM-1", "CLM-2"],
            fact_overrides={
                "atomic_claim_results": [
                    {
                        "claim_id": claim_id,
                        "subject_ref": f"SKU-{index + 1}",
                        "support_status": "supported",
                        "evidence_refs": [{"video_index": 1, "global_frame_index": 18 + index}],
                    }
                    for index, claim_id in enumerate(("CLM-1", "CLM-2"))
                ]
            },
        )

        self.assertEqual(result["summary"]["predicted_label"], "positive")
        self.assertNotEqual(result["decision_policy_audit"]["rule_id"], "PD-R-ATOMIC-CLAIM-INCOMPLETE")

    def test_long_out_of_frame_sop_rule_precedes_later_visible_damage(self):
        result = self._default_visible_damage_case(
            continuity_overrides={
                "continuity_verdict": "long_absence",
                "tracked_subjects": [{
                    "subject_id": "claimed_item",
                    "visibility_coverage": 0.58,
                    "longest_out_of_frame_seconds": 9.97,
                }],
            }
        )

        self.assertEqual(result["summary"]["predicted_label"], "negative")
        self.assertEqual(result["decision_policy_audit"]["rule_id"], "PD-N-NONCOMPLIANT-OPENING-VIDEO")
        self.assertEqual(
            result["decision_policy_audit"]["evidence_verdict_before_policy"]["predicted_label"],
            "review",
        )
        self.assertEqual(
            result["agent_report"]["parsed"]["damage_causality_assessment"]["damage_presence"],
            "confirmed",
        )

    def test_damage_first_visible_after_opening_without_observed_change_remains_supported(self):
        result = self._default_visible_damage_case(
            damage_overrides={"damage_timing": "post_opening_only"},
            continuity_overrides={"continuity_verdict": "indeterminate"},
        )

        self.assertEqual(result["summary"]["predicted_label"], "positive")
        self.assertEqual(result["decision_policy_audit"]["rule_id"], "PD-P-CONFIRMED-VISIBLE-DAMAGE")

    def test_direct_customer_damage_chain_is_negative(self):
        result = self._default_visible_damage_case(
            damage_overrides={
                "damage_timing": "appears_during_opening",
                "damage_change_observed": True,
                "opening_action_visible": True,
                "most_likely_origin": "customer_opening_or_handling",
                "origin_confidence": 0.92,
                "causal_evidence_level": "direct",
                "claim_support": "not_supported",
            },
        )

        self.assertEqual(result["summary"]["predicted_label"], "negative")
        self.assertEqual(result["decision_policy_audit"]["rule_id"], "PD-N-DIRECT-CUSTOMER-DAMAGE")
        parsed = result["agent_report"]["parsed"]
        self.assertNotIn("补齐", parsed["overall_audit"]["business_follow_up_suggestion"])
        self.assertNotIn("重新提交", result["agent_brief"]["next_step"])
        self.assertIn("SOP", result["agent_brief"]["next_step"])

    def test_pre_opening_visible_damage_remains_supported(self):
        result = self._default_visible_damage_case()

        self.assertEqual(result["summary"]["predicted_label"], "positive")
        self.assertEqual(result["decision_policy_audit"]["rule_id"], "PD-P-CONFIRMED-VISIBLE-DAMAGE")

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
        self.assertIn("最低档", result["decision_policy_audit"]["supplemental_evidence_note"])

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

    def test_no_damage_timestamp_anchor_is_not_treated_as_damage_evidence(self):
        result = self._complete_no_damage_case(
            parsed_overrides={
                "damage_causality_assessment": {
                    "first_visible_evidence": {
                        "video_index": 1,
                        "timestamp": "02:15",
                        "fact": "商品外观完好，未见所诉损伤",
                    },
                },
            },
        )

        self.assertEqual(result["summary"]["predicted_label"], "negative")
        self.assertEqual(
            result["decision_policy_audit"]["rule_id"],
            "PD-N-COMPLETE-NO-CLAIMED-DAMAGE",
        )

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

    def test_full_timeline_indeterminate_opening_without_verified_hard_failure_stays_review(self):
        metadata = ReviewCaseMetadata.model_validate(
            {
                "client_case_id": "case-indeterminate-opening",
                "scenario": "product_damage",
                "customer_claim": "商品表面有划痕",
                "decision_policy": {
                    "mode": "classification_recommendation",
                    "policy_ref": DEFAULT_PRODUCT_DAMAGE_POLICY_REF,
                },
            }
        ).model_dump(mode="json")
        parsed = {
            "predicted_label": "review",
            "confidence": 0.5,
            "damage_causality_assessment": {
                "damage_presence": "uncertain",
                "claim_support": "insufficient",
                "evidence_source_summary": {
                    "supplemental_images": {
                        "provided_count": 24,
                        "referenced_count": 21,
                        "linkage_status": "unresolved",
                    }
                },
            },
            "damage_observability": {
                "status": "partial",
                "same_item_linkage": False,
                "claimed_region_closeup": False,
                "required_view_coverage": 0.0,
                "conflicting_evidence": False,
            },
            "object_continuity_assessment": {
                "continuity_verdict": "indeterminate",
                "claimed_item_timeline_complete": True,
                "claimed_item_reference_status": "not_provided",
                "tracked_subjects": [{
                    "subject_id": "claimed_item",
                    "visibility_coverage": 0.15,
                    "longest_out_of_frame_seconds": 0.0,
                }],
            },
            "video_audit_conclusion": {
                "opening_integrity": "indeterminate",
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
        )

        self.assertEqual(result["summary"]["predicted_label"], "review")
        self.assertFalse(result["decision_policy_audit"]["applied"])

    def test_confirmed_visible_damage_forms_positive_sop_recommendation_without_business_action(self):
        metadata = ReviewCaseMetadata.model_validate(
            {
                "client_case_id": "case-visible-damage",
                "scenario": "product_damage",
                "customer_claim": "商品部件断裂",
                "decision_policy": {
                    "mode": "classification_recommendation",
                    "policy_ref": DEFAULT_PRODUCT_DAMAGE_POLICY_REF,
                },
            }
        ).model_dump(mode="json")
        parsed = {
            "predicted_label": "review",
            "confidence": 0.65,
            "damage_causality_assessment": {
                "damage_presence": "confirmed",
                "claim_support": "insufficient",
                "first_visible_evidence": {
                    "video_index": 1,
                    "global_frame_index": 1,
                    "timestamp": "00:00.00",
                    "damage_visible": True,
                },
            },
            "video_audit_conclusion": {"opening_integrity": "unknown"},
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

        self.assertEqual(result["summary"]["predicted_label"], "positive")
        self.assertEqual(result["decision_policy_audit"]["rule_id"], "PD-P-CONFIRMED-VISIBLE-DAMAGE")
        self.assertIn(
            "已确认所诉损伤",
            result["agent_report"]["parsed"]["overall_audit"]["core_reason"],
        )
        self.assertFalse(result["agent_report"]["parsed"]["business_action_allowed"])

    def test_policy_without_visible_damage_rule_keeps_existing_review_result(self):
        metadata = {
            "customer_claim": "商品部件断裂",
            "decision_policy": {
                "mode": "classification_recommendation",
                "policy_ref": "LEGACY-POLICY",
            },
        }
        parsed = {
            "predicted_label": "review",
            "confidence": 0.65,
            "damage_causality_assessment": {
                "damage_presence": "confirmed",
                "claim_support": "supported",
                "first_visible_evidence": {"damage_visible": True},
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
            approved_policies={
                ("mitako", "LEGACY-POLICY"): {
                    "mode": "classification_recommendation",
                    "require_claim_scope": False,
                }
            },
        )

        self.assertEqual(result["summary"]["predicted_label"], "review")
        self.assertFalse(result["decision_policy_audit"]["applied"])

    def test_verified_supplemental_damage_can_form_positive_tendency_without_opening_video(self):
        metadata = ReviewCaseMetadata.model_validate(
            {
                "client_case_id": "case-photo-only-damage",
                "scenario": "product_damage",
                "customer_claim": "商品部件断裂",
                "decision_policy": {
                    "mode": "classification_recommendation",
                    "policy_ref": DEFAULT_PRODUCT_DAMAGE_POLICY_REF,
                },
            }
        ).model_dump(mode="json")
        parsed = {
            "predicted_label": "review",
            "confidence": 0.82,
            "damage_causality_assessment": {
                "damage_presence": "uncertain",
                "supplemental_damage_presence": "confirmed",
                "claim_support": "insufficient",
                "evidence_source_summary": {
                    "supplemental_images": {
                        "provided_count": 2,
                        "referenced_count": 2,
                        "linkage_status": "verified",
                    }
                },
            },
        }

        result = apply_review_decision_policy(
            {
                "tenant_id": "mitako",
                "scenario": "product_damage",
                "metadata": metadata,
                "assets": [{"mime_type": "image/jpeg"}],
            },
            review(parsed),
        )

        self.assertEqual(result["summary"]["predicted_label"], "positive")
        self.assertEqual(
            result["decision_policy_audit"]["rule_id"],
            "PD-P-VERIFIED-SUPPLEMENTAL-DAMAGE",
        )

    def test_missing_video_without_visible_damage_forms_negative_sop_tendency(self):
        metadata = ReviewCaseMetadata.model_validate(
            {
                "client_case_id": "case-no-video-no-damage",
                "scenario": "product_damage",
                "customer_claim": "商品存在划痕",
                "decision_policy": {
                    "mode": "classification_recommendation",
                    "policy_ref": DEFAULT_PRODUCT_DAMAGE_POLICY_REF,
                },
            }
        ).model_dump(mode="json")
        parsed = {
            "predicted_label": "review",
            "confidence": 0.76,
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
        }

        result = apply_review_decision_policy(
            {
                "tenant_id": "mitako",
                "scenario": "product_damage",
                "metadata": metadata,
                "assets": [{"mime_type": "image/jpeg"}],
            },
            review(parsed),
        )

        self.assertEqual(result["summary"]["predicted_label"], "negative")
        self.assertEqual(
            result["decision_policy_audit"]["rule_id"],
            "PD-N-NO-VIDEO-NO-VISIBLE-DAMAGE",
        )

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
                    "sampling_fps": 1.0,
                    "speed_review_impact": {
                        "status": "none",
                        "critical_evidence_observable": True,
                        "affected_review_items": [],
                    },
                },
            },
        )
        self.assertNotEqual(result["decision_policy_audit"].get("rule_id"), "PD-N-NONCOMPLIANT-OPENING-VIDEO")

    def test_accelerated_video_uncertain_at_one_fps_stays_review(self):
        result = self._default_visible_damage_case(video_overrides={
            "playback_speed": "accelerated",
            "sampling_fps": 1.0,
            "speed_review_impact": {
                "status": "uncertain",
                "critical_evidence_observable": False,
                "affected_review_items": ["opening_action"],
            },
        })

        self.assertEqual(result["summary"]["predicted_label"], "review")
        self.assertEqual(result["decision_policy_audit"]["rule_id"], "PD-R-SPEED-REVIEW-NEEDS-DENSE-SCAN")
        self.assertEqual(result["decision_policy_audit"]["sampling_upgrade"]["target_fps"], 2.0)

    def test_speed_review_preserves_zero_confidence(self):
        result = self._default_visible_damage_case(
            confidence=0.0,
            video_overrides={
                "playback_speed": "accelerated",
                "sampling_fps": 1.0,
                "speed_review_impact": {"status": "uncertain"},
            },
        )

        self.assertEqual(result["summary"]["confidence"], 0.0)

    def test_accelerated_video_materially_unreviewable_at_two_fps_is_noncompliant(self):
        result = self._default_visible_damage_case(video_overrides={
            "playback_speed": "accelerated",
            "sampling_fps": 2.0,
            "speed_review_impact": {
                "status": "material",
                "critical_evidence_observable": False,
                "affected_review_items": ["opening_action", "issue_first_visible"],
                "evidence_refs": [{"video_index": 1, "global_frame_index": 18, "timestamp": "00:17.00"}],
            },
        })

        self.assertEqual(result["summary"]["predicted_label"], "negative")
        self.assertEqual(result["decision_policy_audit"]["rule_id"], "PD-N-SPEED-MATERIAL-IMPACT")

    def test_missing_sealed_start_precedes_visible_damage_positive_rule(self):
        result = self._default_visible_damage_case(video_overrides={
            "source": "global_timeline_aggregation",
            "sampling_boundary_status": "covered",
            "opening_video_compliance": {
                "sealed_start": False,
                "waybill_visible": True,
                "single_take_continuity": True,
                "issue_visible_in_continuous_opening": True,
                "source": "global_timeline_aggregation",
                "validated_fields": ["sealed_start"],
                "evidence_refs": {
                    "sealed_start": [{"video_index": 1, "global_frame_index": 1, "timestamp": "00:00.00"}],
                },
            },
        })

        self.assertEqual(result["summary"]["predicted_label"], "negative")
        self.assertEqual(result["decision_policy_audit"]["rule_id"], "PD-N-NONCOMPLIANT-OPENING-VIDEO")

    def test_issue_not_visible_in_continuous_opening_is_a_verified_hard_failure(self):
        result = self._default_visible_damage_case(video_overrides={
            "source": "global_timeline_aggregation",
            "sampling_boundary_status": "covered",
            "opening_video_compliance": {
                "sealed_start": True,
                "waybill_visible": True,
                "single_take_continuity": True,
                "issue_visible_in_continuous_opening": False,
                "source": "global_timeline_aggregation",
                "validated_fields": ["issue_visible_in_continuous_opening"],
                "evidence_refs": {
                    "issue_visible_in_continuous_opening": [{
                        "video_index": 1,
                        "global_frame_index": 18,
                        "timestamp": "00:17.00",
                    }],
                },
            },
        })

        self.assertEqual(result["summary"]["predicted_label"], "negative")
        self.assertEqual(result["decision_policy_audit"]["rule_id"], "PD-N-NONCOMPLIANT-OPENING-VIDEO")

    def test_unverified_noncompliant_opening_review_cannot_keep_positive_follow_up(self):
        result = self._default_visible_damage_case(
            damage_overrides={
                "damage_presence": "uncertain",
                "claim_support": "supported",
                "first_visible_evidence": {},
                "evidence_source_summary": {
                    "primary_video": {
                        "damage_presence": "uncertain",
                        "claim_support": "supported",
                    },
                    "supplemental_images": {
                        "provided_count": 1,
                        "referenced_count": 1,
                        "linkage_status": "unresolved",
                    },
                },
            },
            video_overrides={
                "opening_video_compliance": {
                    "sealed_start": True,
                    "waybill_visible": True,
                    "single_take_continuity": True,
                    "issue_visible_in_continuous_opening": False,
                    "source": "hybrid_native_video_with_opening_start_verification",
                    "validated_fields": ["sealed_start"],
                    "result": "noncompliant",
                },
            },
        )

        parsed = result["agent_report"]["parsed"]
        self.assertEqual(result["summary"]["predicted_label"], "review")
        self.assertIn("保留复核信号", parsed["business_follow_up_reason"])
        self.assertEqual(
            parsed["damage_causality_assessment"]["evidence_source_summary"]["primary_video"]["claim_support"],
            "insufficient",
        )

    def test_full_timeline_absence_can_verify_issue_not_shown_without_single_frame_anchor(self):
        result = self._default_visible_damage_case(video_overrides={
            "source": "global_timeline_aggregation",
            "sampling_boundary_status": "covered",
            "opening_video_compliance": {
                "sealed_start": True,
                "waybill_visible": True,
                "single_take_continuity": True,
                "issue_visible_in_continuous_opening": False,
                "source": "global_timeline_aggregation",
                "result": "noncompliant",
                "validated_fields": [],
                "evidence_refs": {
                    "single_take_continuity": [{
                        "video_index": 1,
                        "global_frame_index": 2,
                        "timestamp": "00:16.90",
                    }],
                    "issue_visible_in_continuous_opening": [],
                },
            },
        })

        self.assertEqual(result["summary"]["predicted_label"], "negative")
        self.assertEqual(result["decision_policy_audit"]["rule_id"], "PD-N-NONCOMPLIANT-OPENING-VIDEO")
        facts = [item.get("fact") for item in result["agent_report"]["parsed"]["adopted_evidence"]]
        self.assertTrue(any("伤点在连续开箱中清晰展示" in str(fact) and "不符合" in str(fact) for fact in facts))

    def test_opening_compliance_verification_can_trigger_hard_failure(self):
        fields = (
            "sealed_start", "waybill_visible", "single_take_continuity",
            "issue_visible_in_continuous_opening",
        )
        result = self._default_visible_damage_case(
            damage_overrides={
                "damage_presence": "uncertain",
                "claim_support": "supported",
                "evidence_source_summary": {
                    "primary_video": {
                        "damage_presence": "uncertain",
                        "claim_support": "supported",
                    },
                    "supplemental_images": {
                        "provided_count": 2,
                        "referenced_count": 2,
                        "linkage_status": "unresolved",
                    },
                },
            },
            video_overrides={
                "source": "global_timeline_aggregation",
                "sampling_boundary_status": "covered",
                "opening_video_compliance": {
                    "sealed_start": True,
                    "waybill_visible": False,
                    "single_take_continuity": True,
                    "issue_visible_in_continuous_opening": False,
                    "source": "opening_compliance_verification",
                    "validated_fields": list(fields),
                    "evidence_refs": [
                        {
                            "field": field,
                            "video_index": 9,
                            "global_frame_index": 35,
                            "timestamp": "00:00.00",
                        }
                        for field in fields
                    ],
                },
            },
        )

        self.assertEqual(result["summary"]["predicted_label"], "negative")
        self.assertEqual(
            result["decision_policy_audit"]["rule_id"],
            "PD-N-NONCOMPLIANT-OPENING-VIDEO",
        )
        reason = result["decision_policy_audit"]["reason"]
        self.assertIn("面单可核验", reason)
        self.assertIn("伤点在连续开箱中清晰展示", reason)
        self.assertNotIn("封箱起始", reason)
        self.assertNotIn("一镜到底连续拆封", reason)
        parsed = result["agent_report"]["parsed"]
        self.assertNotIn("支持用户", parsed["next_step"])
        self.assertNotIn("支持用户", parsed["business_follow_up_reason"])
        self.assertIn("开箱材料不合规", parsed["business_follow_up_reason"])
        damage = parsed["damage_causality_assessment"]
        self.assertEqual(damage["claim_support"], "insufficient")
        self.assertEqual(
            damage["evidence_source_summary"]["primary_video"]["claim_support"],
            "insufficient",
        )
        self.assertEqual(
            damage["evidence_source_summary"]["supplemental_images"]["provided_count"],
            2,
        )

    def test_verified_opening_evidence_replaces_conflicting_model_anchor(self):
        result = self._default_visible_damage_case(
            video_overrides={
                "source": "global_timeline_aggregation",
                "sampling_boundary_status": "covered",
                "opening_video_compliance": {
                    "sealed_start": True,
                    "waybill_visible": False,
                    "single_take_continuity": True,
                    "issue_visible_in_continuous_opening": False,
                    "source": "opening_compliance_verification",
                    "validated_fields": [
                        "sealed_start", "waybill_visible", "single_take_continuity",
                        "issue_visible_in_continuous_opening",
                    ],
                    "evidence_refs": [
                        {"field": "sealed_start", "video_index": 1, "global_frame_index": 1, "timestamp": "00:00.00"},
                        {"field": "waybill_visible", "video_index": 1, "global_frame_index": 1, "timestamp": "00:00.00"},
                        {"field": "single_take_continuity", "video_index": 1, "global_frame_index": 2, "timestamp": "00:01.00"},
                        {"field": "issue_visible_in_continuous_opening", "video_index": 1, "global_frame_index": 3, "timestamp": "00:02.00"},
                    ],
                },
            },
        )
        parsed = result["agent_report"]["parsed"]
        parsed["adopted_evidence"] = [
            {
                "source_type": "video",
                "video_index": 1,
                "global_frame_index": 1,
                "timestamp": "00:00.00",
                "fact": "面单及封箱完好。",
            },
            {
                "source_type": "video",
                "video_index": 2,
                "global_frame_index": 9,
                "timestamp": "00:08.00",
                "fact": "争议部位可见划痕。",
            },
        ]

        reapplied = apply_review_decision_policy(
            {
                "tenant_id": "mitako",
                "scenario": "product_damage",
                "metadata": {
                    "client_case_id": "verified-opening-evidence",
                    "scenario": "product_damage",
                    "customer_claim": "商品有划痕",
                    "claim_scope": {
                        "split_status": "single_legacy",
                        "claim_text": "商品有划痕",
                        "issue_types": ["product_damage"],
                    },
                    "decision_policy": {
                        "mode": "classification_recommendation",
                        "policy_ref": DEFAULT_PRODUCT_DAMAGE_POLICY_REF,
                    },
                },
                "assets": [{"mime_type": "video/mp4"}],
            },
            result,
        )
        evidence = reapplied["agent_report"]["parsed"]["adopted_evidence"]
        facts = [item.get("fact") for item in evidence]
        self.assertNotIn("面单及封箱完好。", facts)
        self.assertIn("争议部位可见划痕。", facts)
        self.assertTrue(any("面单" in fact and "不符合" in fact for fact in facts))

    def test_verified_opening_start_anchor_can_prove_missing_sealed_start(self):
        result = self._default_visible_damage_case(video_overrides={
            "opening_video_compliance": {
                "sealed_start": False,
                "waybill_visible": True,
                "single_take_continuity": True,
                "issue_visible_in_continuous_opening": True,
                "source": "hybrid_native_video_with_opening_start_verification",
                "field_sources": {"sealed_start": "opening_start_verification"},
                "validated_fields": ["sealed_start"],
                "evidence_refs": [{
                    "field": "sealed_start",
                    "video_index": 1,
                    "global_frame_index": 1,
                    "timestamp": "00:00.00",
                }],
            },
        })

        self.assertEqual(result["summary"]["predicted_label"], "negative")
        self.assertEqual(result["decision_policy_audit"]["rule_id"], "PD-N-NONCOMPLIANT-OPENING-VIDEO")

    def test_unverified_segment_opening_false_cannot_trigger_hard_negative(self):
        result = self._default_visible_damage_case(video_overrides={
            "opening_video_compliance": {"sealed_start": False},
        })

        self.assertNotEqual(result["decision_policy_audit"]["rule_id"], "PD-N-NONCOMPLIANT-OPENING-VIDEO")

    def test_opening_hard_failure_precedes_speed_resampling(self):
        result = self._default_visible_damage_case(video_overrides={
            "source": "global_timeline_aggregation",
            "sampling_boundary_status": "covered",
            "playback_speed": "accelerated",
            "sampling_fps": 1.0,
            "speed_review_impact": {"status": "uncertain"},
            "opening_video_compliance": {
                "sealed_start": False,
                "source": "global_timeline_aggregation",
                "validated_fields": ["sealed_start"],
                "evidence_refs": {
                    "sealed_start": [{"video_index": 1, "global_frame_index": 1, "timestamp": "00:00.00"}],
                },
            },
        })

        self.assertEqual(result["decision_policy_audit"]["rule_id"], "PD-N-NONCOMPLIANT-OPENING-VIDEO")

    def test_supplemental_later_state_does_not_become_main_video_positive(self):
        result = self._default_visible_damage_case(
            damage_overrides={
                "damage_presence": "confirmed",
                "claim_support": "insufficient",
                "first_visible_evidence": {
                    "source_type": "supplementary_image",
                    "image_index": 1,
                    "damage_visible": True,
                    "temporal_linkage": None,
                },
                "evidence_source_summary": {
                    "primary_video": {"damage_presence": "not_visible", "claim_support": "insufficient"},
                    "supplemental_images": {
                        "provided_count": 1,
                        "referenced_count": 1,
                        "linkage_status": "unresolved",
                    },
                },
            },
        )

        self.assertEqual(result["summary"]["predicted_label"], "review")
        self.assertEqual(result["decision_policy_audit"]["rule_id"], "PD-R-SUPPLEMENTAL-TEMPORAL-LINKAGE-UNRESOLVED")

    def test_special_product_appearance_difference_requires_business_standard(self):
        result = self._default_visible_damage_case(damage_overrides={
            "damage_presence": "confirmed",
            "claim_support": "insufficient",
            "appearance_difference": "visible",
            "business_defect_qualification": "indeterminate",
            "special_product_rule": "required_but_not_quantified",
        })

        self.assertEqual(result["summary"]["predicted_label"], "review")
        self.assertEqual(result["decision_policy_audit"]["rule_id"], "PD-R-SPECIAL-PRODUCT-DEFECT-UNRESOLVED")

    def test_special_product_not_qualified_cannot_become_visible_damage_positive(self):
        result = self._default_visible_damage_case(damage_overrides={
            "appearance_difference": "visible",
            "business_defect_qualification": "not_qualified",
            "special_product_rule": "satisfied",
        })

        self.assertEqual(result["summary"]["predicted_label"], "negative")
        self.assertEqual(result["decision_policy_audit"]["rule_id"], "PD-N-SPECIAL-PRODUCT-NOT-QUALIFIED")

    def test_special_product_indeterminate_qualification_never_becomes_positive(self):
        result = self._default_visible_damage_case(damage_overrides={
            "appearance_difference": "visible",
            "business_defect_qualification": "indeterminate",
            "special_product_rule": "satisfied",
        })

        self.assertEqual(result["summary"]["predicted_label"], "review")
        self.assertEqual(result["decision_policy_audit"]["rule_id"], "PD-R-SPECIAL-PRODUCT-DEFECT-UNRESOLVED")

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

    def test_confirmed_damage_fact_is_preserved_but_long_absence_fails_opening_sop(self):
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
        self.assertEqual(
            result["agent_report"]["parsed"]["damage_causality_assessment"]["damage_presence"],
            "confirmed",
        )
        self.assertEqual(
            audit["evidence_gate"]["claimed_item_longest_out_of_frame_seconds"],
            8.0,
        )

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

    def test_missing_closeup_does_not_erase_clear_no_damage_sop_recommendation(self):
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
                    "recommendation_gate_mode": "core_sop",
                    "policy_ref": "MITAKO-PD-COMPLETE-NO-DAMAGE@TEST",
                    "complete_video_no_claimed_damage": "negative",
                },
            }
        ).model_dump(mode="json")
        parsed = {
            "predicted_label": "review",
            "confidence": 0.6,
            "damage_causality_assessment": {"damage_presence": "not_visible", "claim_support": "not_supported"},
            "damage_observability": {
                "status": "partial",
                "same_item_linkage": True,
                "claimed_region_closeup": False,
                "required_view_coverage": 0.5,
                "conflicting_evidence": True,
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
        self.assertEqual(result["summary"]["predicted_label"], "negative")
        self.assertTrue(result["decision_policy_audit"]["applied"])
        self.assertIn("damage_observability", result["agent_report"]["parsed"]["decision_policy_audit"]["failed_conditions"])

    def test_unresolved_supplemental_image_linkage_does_not_erase_sop_recommendation(self):
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
                    "recommendation_gate_mode": "core_sop",
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
                "damage_presence": "uncertain",
                "claim_support": "insufficient",
                "evidence_source_summary": {
                    "supplemental_images": {"provided_count": 1, "linkage_status": "unresolved"},
                },
            },
            "damage_observability": {
                "status": "partial",
                "same_item_linkage": True,
                "claimed_region_closeup": False,
                "required_view_coverage": 0.5,
                "conflicting_evidence": True,
            },
            "object_continuity_assessment": {
                "continuity_verdict": "indeterminate",
                "tracked_subjects": [{
                    "subject_id": "claimed_item",
                    "visibility_coverage": 0.5,
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
        self.assertEqual(result["summary"]["predicted_label"], "negative")
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

    def test_partial_supplemental_review_remains_audit_signal_without_erasing_sop_recommendation(self):
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
                    "recommendation_gate_mode": "core_sop",
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
        self.assertEqual(result["summary"]["predicted_label"], "negative")
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
