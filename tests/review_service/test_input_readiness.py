# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from poc.visual_review_poc.local_video_triage_demo import apply_frontdesk_context
from review_service.input_readiness import assess_input_readiness
from review_service.schemas import ReviewCaseMetadata
from review_service.service import _public_media_urls, _recommended_escalation, contract, sampling_plan
from review_service.service import ensure_label_isolation
from review_service.service import _apply_input_readiness_guard
from review_service.service import _review_fields


class InputReadinessTest(unittest.TestCase):
    def test_contract_declares_supplier_neutral_inline_media_transport(self):
        media = contract()["media_processing"]

        self.assertEqual(media["model_request_transport"], "inline_base64_images")
        self.assertIs(media["supplier_file_uri_required"], False)
        self.assertEqual(media["detail_frame_format"], "image/jpeg")
        self.assertEqual(media["temporal_sheet_format"], "image/webp")
        self.assertEqual(media["official_product_references"]["mode"], "per_review_on_demand")
        self.assertFalse(media["official_product_references"]["bulk_download_enabled"])
        self.assertIn("fulfillment_baseline", contract()["business_fields"])
        self.assertIn("sampling_policy", contract()["business_fields"])
        self.assertIn("customer_risk_context", contract()["business_fields"])
        self.assertEqual(contract()["customer_risk_context_policy"]["model_input"], False)
        warehouse = contract()["warehouse_verification_policy"]
        self.assertEqual(warehouse["source"], "customer_warehouse")
        self.assertEqual(
            set(warehouse["terminal_statuses"]),
            {"confirmed_missing", "confirmed_not_missing"},
        )
        self.assertIn("可追溯", warehouse["trust_boundary"])
        self.assertIn("仓库终核", contract()["scenario_input_readiness"]["missing_item"])

    def test_public_report_refreshes_signed_workbench_media_urls(self):
        with patch.dict("os.environ", {
            "VISUAL_REPORT_SIGNING_SECRET": "test-signing-secret",
            "VISUAL_WORKBENCH_PUBLIC_URL": "https://review.example.test",
        }):
            url = _public_media_urls("/media-item/opaque-id?expires=1&sig=expired")
        self.assertTrue(url.startswith("https://review.example.test/media-item/opaque-id?expires="))
        self.assertIn("&sig=", url)
        self.assertNotIn("expired", url)

    def test_wrong_item_without_package_linkage_is_not_ready_for_definite_decision(self):
        result = assess_input_readiness(
            {
                "scenario": "wrong_item",
                "order_items": [{"name": "角色拍立得", "style": "A款", "quantity": 1}],
            }
        )
        self.assertFalse(result["full_review_ready"])
        self.assertNotIn("order_item_baseline", result["missing_required"])
        self.assertIn("fulfillment_baseline.baseline_version", result["missing_required"])
        self.assertIn("package_item_mapping", result["missing_required"])

    def test_missing_item_with_traceable_warehouse_final_is_ready_without_video_coverage(self):
        result = assess_input_readiness(
            {
                "scenario": "missing_item",
                "fulfillment_baseline": {
                    "baseline_version": "ORDER-1@V1",
                    "expected_items": [
                        {"item_ref": "LINE-1", "sku": "SKU-1", "expected_quantity": 1}
                    ],
                    "warehouse_verification": {
                        "status": "confirmed_not_missing",
                        "source": "customer_warehouse",
                        "verification_ref": "WH-CHECK-1",
                    },
                },
            }
        )

        self.assertTrue(result["full_review_ready"])
        self.assertTrue(result["capabilities"]["missing_item_decision"])
        self.assertEqual(result["missing_required"], [])
        self.assertEqual(result["missing_recommended"], [])
        self.assertFalse(any("视频未完整" in warning for warning in result["warnings"]))

    def test_wrong_item_is_ready_with_package_and_submitted_tracking_linkage(self):
        result = assess_input_readiness(
            {
                "scenario": "wrong_item",
                "fulfillment_baseline": {
                    "baseline_version": "ORDER-1@V1",
                    "expected_items": [
                        {"item_ref": "LINE-1", "sku": "SKU-1", "expected_quantity": 1}
                    ],
                    "expected_package_count": 1,
                    "packages": [
                        {
                            "package_ref": "PKG-1",
                            "tracking_no": "TRACK-REF-1",
                            "expected_item_refs": ["LINE-1"],
                        }
                    ],
                    "selection_rules_complete": True,
                },
                "evidence_coverage": {"submitted_tracking_nos": ["TRACK-REF-1"]},
            }
        )

        self.assertTrue(result["full_review_ready"])
        self.assertTrue(result["capabilities"]["wrong_item_decision"])

    def test_wrong_item_without_order_baseline_degrades_but_keeps_continuity(self):
        result = assess_input_readiness({"scenario": "wrong_item", "order_items": []})
        self.assertFalse(result["full_review_ready"])
        self.assertTrue(result["capabilities"]["opening_continuity"])
        self.assertFalse(result["capabilities"]["wrong_item_decision"])

    def test_wrong_item_requires_every_expected_line_to_be_identifiable(self):
        result = assess_input_readiness(
            {
                "scenario": "wrong_item",
                "order_items": [
                    {"sku": "SKU-1", "quantity": 1},
                    {"name": "无法唯一识别的商品", "quantity": 1},
                ],
            }
        )
        self.assertIn("order_item_baseline", result["missing_required"])

    def test_wrong_item_requires_expected_quantity(self):
        result = assess_input_readiness(
            {"scenario": "wrong_item", "order_items": [{"sku": "SKU-1", "name": "徽章"}]}
        )
        self.assertIn("all_expected_item_quantities", result["missing_required"])

    def test_product_damage_sku_is_recommended_not_required(self):
        result = assess_input_readiness({"scenario": "product_damage", "customer_claim": "商品边角有明显折痕"})
        self.assertTrue(result["full_review_ready"])
        self.assertIn("product_master_data", result["missing_recommended"])
        self.assertTrue(result["capabilities"]["visible_damage_detection"])

    def test_wrong_item_with_incomplete_lottery_rules_is_not_ready_for_definite_decision(self):
        result = assess_input_readiness({
            "scenario": "wrong_item",
            "fulfillment_baseline": {
                "baseline_version": "V1",
                "expected_items": [{"item_ref": "LINE-1", "sku": "SKU-1", "expected_quantity": 1}],
                "selection_rules": [{"rule_ref": "LOTTERY-1", "item_refs": ["LINE-1"]}],
                "selection_rules_complete": False,
            },
        })
        self.assertFalse(result["full_review_ready"])
        self.assertIn("fulfillment_baseline.selection_rules_complete", result["missing_required"])

    def test_missing_item_requires_order_quantity(self):
        result = assess_input_readiness(
            {"scenario": "missing_item", "order_items": [{"sku": "SKU-1", "name": "徽章"}]}
        )
        self.assertIn("all_expected_item_quantities", result["missing_required"])

    def test_missing_item_is_ready_with_versioned_fulfillment_and_complete_coverage(self):
        result = assess_input_readiness(
            {
                "scenario": "missing_item",
                "fulfillment_baseline": {
                    "baseline_version": "ORDER-1@2026-07-16T10:00:00+08:00",
                    "expected_items": [
                        {"item_ref": "LINE-1", "sku": "SKU-1", "expected_quantity": 2},
                        {"item_ref": "GIFT-1", "sku": "GIFT-1", "expected_quantity": 1, "item_type": "gift"},
                    ],
                    "expected_package_count": 1,
                    "packages": [{"package_ref": "PKG-1", "expected_item_refs": ["LINE-1", "GIFT-1"]}],
                    "benefit_rules_complete": True,
                    "selection_rules_complete": True,
                },
                "logistics": {
                    "snapshot_at": "2026-07-23T10:00:00+08:00",
                    "all_packages_delivered": True,
                    "packages": [{"package_ref": "PKG-1", "shipment_status": "delivered"}],
                },
                "evidence_coverage": {
                    "submitted_package_refs": ["PKG-1"],
                    "all_packages_uploaded": True,
                    "all_items_displayed": True,
                },
            }
        )
        self.assertTrue(result["full_review_ready"])
        self.assertTrue(result["capabilities"]["missing_item_decision"])

    def test_missing_item_in_transit_cannot_form_definite_conclusion(self):
        result = assess_input_readiness(
            {
                "scenario": "missing_item",
                "customer_claim": "少了一枚徽章",
                "fulfillment_baseline": {
                    "baseline_version": "ORDER-1@V1",
                    "expected_items": [{"item_ref": "LINE-1", "sku": "SKU-1", "expected_quantity": 1}],
                    "expected_package_count": 1,
                    "packages": [{"package_ref": "PKG-1", "expected_item_refs": ["LINE-1"]}],
                    "benefit_rules_complete": True,
                    "selection_rules_complete": True,
                },
                "logistics": {
                    "snapshot_at": "2026-07-23T10:00:00+08:00",
                    "all_packages_delivered": False,
                    "packages": [{"package_ref": "PKG-1", "shipment_status": "in_transit"}],
                },
                "evidence_coverage": {
                    "submitted_package_refs": ["PKG-1"],
                    "all_packages_uploaded": True,
                    "all_items_displayed": True,
                },
            }
        )

        self.assertFalse(result["full_review_ready"])
        self.assertIn("all_expected_packages_delivered", result["missing_required"])

    def test_selection_rules_must_be_explicitly_declared_even_when_not_applicable(self):
        result = assess_input_readiness(
            {
                "scenario": "wrong_item",
                "customer_claim": "收到的款式与订单不同",
                "fulfillment_baseline": {
                    "baseline_version": "ORDER-1@V1",
                    "expected_items": [{"item_ref": "LINE-1", "sku": "SKU-1", "expected_quantity": 1}],
                    "expected_package_count": 1,
                    "packages": [{"package_ref": "PKG-1", "expected_item_refs": ["LINE-1"]}],
                },
                "evidence_coverage": {"submitted_package_refs": ["PKG-1"]},
            }
        )

        self.assertIn("selection_rules_declaration", result["missing_required"])

    def test_product_damage_without_claim_or_resolved_scope_is_degraded(self):
        result = assess_input_readiness({"scenario": "product_damage"})

        self.assertFalse(result["full_review_ready"])
        self.assertIn("customer_claim_or_claim_scope", result["missing_required"])

    def test_missing_item_incomplete_video_coverage_must_review(self):
        result = assess_input_readiness(
            {
                "scenario": "missing_item",
                "fulfillment_baseline": {
                    "baseline_version": "V1",
                    "expected_items": [{"item_ref": "LINE-1", "sku": "SKU-1", "expected_quantity": 1}],
                    "expected_package_count": 1,
                    "packages": [{"package_ref": "PKG-1", "expected_item_refs": ["LINE-1"]}],
                    "benefit_rules_complete": True,
                },
                "evidence_coverage": {"all_packages_uploaded": False, "all_items_displayed": False},
            }
        )
        self.assertFalse(result["full_review_ready"])
        self.assertIn("complete_evidence_coverage", result["missing_required"])

    def test_missing_item_declared_complete_without_package_refs_is_not_ready(self):
        result = assess_input_readiness(
            {
                "scenario": "missing_item",
                "fulfillment_baseline": {
                    "baseline_version": "V1",
                    "expected_items": [{"item_ref": "LINE-1", "sku": "SKU-1", "expected_quantity": 1}],
                    "expected_package_count": 1,
                    "packages": [{"package_ref": "PKG-1", "expected_item_refs": ["LINE-1"]}],
                    "benefit_rules_complete": True,
                },
                "evidence_coverage": {"all_packages_uploaded": True, "all_items_displayed": True},
            }
        )
        self.assertFalse(result["full_review_ready"])
        self.assertIn("submitted_package_mapping", result["missing_required"])

    def test_missing_item_rejects_package_mapping_to_unknown_item(self):
        result = assess_input_readiness(
            {
                "scenario": "missing_item",
                "fulfillment_baseline": {
                    "baseline_version": "V1",
                    "expected_items": [{"item_ref": "LINE-1", "sku": "SKU-1", "expected_quantity": 1}],
                    "expected_package_count": 1,
                    "packages": [{"package_ref": "PKG-1", "expected_item_refs": ["UNKNOWN"]}],
                    "benefit_rules_complete": True,
                },
                "evidence_coverage": {
                    "submitted_package_refs": ["PKG-1"],
                    "all_packages_uploaded": True,
                    "all_items_displayed": True,
                },
            }
        )
        self.assertIn("package_item_mapping", result["missing_required"])

    def test_runtime_guard_overrides_definite_model_label_when_input_is_incomplete(self):
        guarded = _apply_input_readiness_guard(
            {
                "summary": {"predicted_label": "positive", "confidence": 0.93},
                "agent_report": {
                    "parsed": {
                        "predicted_label": "positive",
                        "system_yes_no": "YES",
                        "confidence": 0.93,
                        "material_gaps": [],
                    }
                },
            },
            {"full_review_ready": False, "missing_required": ["complete_evidence_coverage"]},
        )
        parsed = guarded["agent_report"]["parsed"]
        self.assertEqual(parsed["predicted_label"], "review")
        self.assertEqual(parsed["system_yes_no"], "REVIEW")
        self.assertEqual(parsed["decision"], "request_more_material")
        self.assertFalse(parsed["human_required"])
        self.assertFalse(parsed["business_action_allowed"])
        self.assertIn("complete_evidence_coverage", parsed["material_gaps"])

    def test_continuity_policy_is_bounded_in_openapi_model(self):
        metadata = ReviewCaseMetadata.model_validate(
            {
                "client_case_id": "CASE-1",
                "scenario": "product_damage",
                "continuity_policy": {"out_of_frame_warning_seconds": 3.5},
            }
        )
        self.assertEqual(metadata.continuity_policy.out_of_frame_warning_seconds, 3.5)
        self.assertFalse(metadata.continuity_policy.force_dense_scan)
        self.assertFalse(metadata.damage_causality_policy.force_action_scan)

    def test_api_accepts_typed_logistics_and_privacy_safe_risk_summary(self):
        metadata = ReviewCaseMetadata.model_validate(
            {
                "client_case_id": "CASE-MULTISOURCE-1",
                "scenario": "wrong_item",
                "logistics": {
                    "source": "customer_logistics_system",
                    "snapshot_at": "2026-07-23T10:00:00+08:00",
                    "packages": [
                        {
                            "package_ref": "PKG-1",
                            "tracking_ref": "sha256:tracking",
                            "shipment_status": "delivered",
                            "events": [{"status": "delivered", "occurred_at": "2026-07-22T18:00:00+08:00"}],
                        }
                    ],
                },
                "customer_risk_context": {
                    "source": "customer_risk_service",
                    "snapshot_at": "2026-07-23T10:00:00+08:00",
                    "lookback_days": 180,
                    "prior_after_sales_count": 3,
                    "prior_upheld_count": 2,
                    "prior_rejected_count": 1,
                    "same_scenario_count": 1,
                    "risk_level": "medium",
                    "reason_codes": ["repeat_after_sales"],
                },
            }
        )

        self.assertEqual(metadata.logistics.packages[0].shipment_status, "delivered")
        self.assertEqual(metadata.customer_risk_context.risk_level, "medium")

    def test_formal_api_rejects_final_customer_service_decision_in_conversation(self):
        with self.assertRaises(ValidationError):
            ReviewCaseMetadata.model_validate(
                {
                    "client_case_id": "CASE-CONVERSATION-FINAL",
                    "scenario": "product_damage",
                    "conversation_history": [
                        {"role": "customer_service", "message_type": "final_decision", "text": "人工最终同意退款"}
                    ],
                }
            )

    def test_formal_api_accepts_predecision_service_question(self):
        metadata = ReviewCaseMetadata.model_validate(
            {
                "client_case_id": "CASE-CONVERSATION-QUESTION",
                "scenario": "product_damage",
                "conversation_history": [
                    {"role": "customer_service", "message_type": "request_more_material", "text": "请补充连续开箱视频"},
                    {"role": "user", "text": "已经补充"},
                ],
            }
        )
        self.assertEqual(len(metadata.conversation_history), 2)

    def test_risk_reason_codes_reject_personal_data(self):
        with self.assertRaises(ValidationError):
            ReviewCaseMetadata.model_validate(
                {
                    "client_case_id": "CASE-RISK-PII",
                    "scenario": "wrong_item",
                    "customer_risk_context": {
                        "risk_level": "medium",
                        "reason_codes": ["phone_13800138000"],
                    },
                }
            )

    def test_risk_snapshot_timestamp_rejects_personal_data(self):
        with self.assertRaises(ValidationError):
            ReviewCaseMetadata.model_validate(
                {
                    "client_case_id": "CASE-RISK-TIMESTAMP-PII",
                    "scenario": "wrong_item",
                    "customer_risk_context": {
                        "snapshot_at": "13800138000",
                        "risk_level": "medium",
                    },
                }
            )

    def test_product_damage_adaptive_uses_bounded_single_pass_by_default(self):
        plan = sampling_plan(
            452.5,
            543_351_335,
            1,
            {"preset": "adaptive", "frames_per_model_call": 24},
            "product_damage",
            {"force_dense_scan": False},
            {"force_action_scan": False},
        )
        self.assertEqual(plan["sampling_mode"], "adaptive")
        self.assertEqual(plan["fps"], 1.0)
        self.assertLessEqual(plan["estimated_total_frames"], 24)
        self.assertEqual(plan["estimated_channel_calls"]["object_continuity"], 0)
        self.assertEqual(plan["estimated_channel_calls"]["damage_causality"], 0)
        self.assertEqual(plan["estimated_total_model_calls"], 1)

    def test_sampling_plan_uses_three_second_default_out_of_frame_policy(self):
        plan = sampling_plan(
            60,
            12_000_000,
            1,
            {"preset": "adaptive"},
            "product_damage",
            {},
            {},
        )

        self.assertEqual(
            plan["effective_review_policies"]["continuity_policy"]["out_of_frame_warning_seconds"],
            3.0,
        )

    def test_sampling_frequency_is_derived_from_out_of_frame_threshold(self):
        one_fps = sampling_plan(
            72,
            22_000_000,
            1,
            {"preset": "adaptive"},
            "product_damage",
            {"out_of_frame_warning_seconds": 2.0, "force_dense_scan": True},
        )
        two_fps = sampling_plan(
            72,
            22_000_000,
            1,
            {"preset": "adaptive"},
            "product_damage",
            {"out_of_frame_warning_seconds": 1.0, "force_dense_scan": True},
        )
        self.assertEqual(one_fps["sampling_mode"], "dense")
        self.assertEqual(one_fps["fps"], 1.0)
        self.assertEqual(two_fps["fps"], 2.0)

    def test_uncertain_speed_impact_recommends_bounded_two_fps_review(self):
        escalation = _recommended_escalation(
            {
                "scenario": "product_damage",
                "metadata": {"scenario": "product_damage", "sampling_policy": {"preset": "strict"}},
            },
            {
                "agent_report": {"parsed": {"video_audit_conclusion": {
                    "playback_speed": "accelerated",
                    "sampling_fps": 1.0,
                    "speed_review_impact": {"status": "uncertain"},
                }}},
                "advisory_assessment": {
                    "workflow_recommendation": "human_review",
                    "human_review": {"level": "required", "reason_codes": []},
                    "signals": [],
                },
            },
            {},
        )

        action = next(item for item in escalation["actions"] if item["type"] == "increase_sampling_strength")
        self.assertEqual(action["target_preset"], "forensic")
        self.assertEqual(action["target_fps"], 2.0)
        self.assertIn("疑似加速", action["description"])

    def test_sampling_plan_counts_all_enabled_review_channels(self):
        with patch.dict("os.environ", {"REVIEW_PRODUCT_DAMAGE_MAIN_MAX_FRAMES": "48"}, clear=False):
            plan = sampling_plan(
                452.5,
                543_351_335,
                1,
                {"preset": "adaptive", "frames_per_model_call": 24},
                "product_damage",
                {"out_of_frame_warning_seconds": 2.0, "force_dense_scan": True},
                {"force_action_scan": True, "dedicated_chunk_frames": 20},
            )
        channels = plan["estimated_channel_calls"]
        self.assertEqual(plan["estimated_total_frames"], 454)
        self.assertEqual(plan["main_review_frames"], 454)
        self.assertEqual(channels["main_review"], 19)
        self.assertEqual(channels["object_continuity"], 0)
        self.assertEqual(channels["damage_causality"], 0)
        self.assertEqual(plan["estimated_total_model_calls"], sum(channels.values()))
        self.assertTrue(plan["unified_multitask"]["enabled"])
        self.assertGreater(plan["unified_multitask"]["fallback_channel_calls"]["damage_causality"], 0)

    def test_sampling_plan_exposes_individual_frame_continuity_for_all_transports(self):
        with patch.dict("os.environ", {"REVIEW_CONTINUITY_FRAMES_PER_CALL": "48"}, clear=False):
            plan = sampling_plan(
                95,
                20_000_000,
                1,
                {"preset": "strict", "frames_per_model_call": 24},
                "product_damage",
                {"force_dense_scan": True},
                {"force_action_scan": False},
            )

        self.assertEqual(plan["estimated_total_frames"], 96)
        self.assertEqual(plan["continuity_frames_per_call"], 24)
        self.assertEqual(
            plan["continuity_frames_per_call_by_transport"],
            {"gemini_native_individual_frames": 24, "openai_compatible_individual_frames": 24},
        )
        self.assertEqual(plan["estimated_channel_calls"]["object_continuity"], 0)
        self.assertEqual(plan["unified_multitask"]["fallback_channel_calls"]["object_continuity"], 4)

    def test_strict_profile_automatically_enables_specialized_channels(self):
        plan = sampling_plan(
            72,
            22_000_000,
            1,
            {"preset": "strict", "frames_per_model_call": 24},
            "product_damage",
            {"force_dense_scan": False},
            {"force_action_scan": False},
        )
        self.assertTrue(plan["effective_review_policies"]["continuity_policy"]["force_dense_scan"])
        self.assertTrue(plan["effective_review_policies"]["damage_causality_policy"]["force_action_scan"])
        self.assertTrue(plan["unified_multitask"]["enabled"])
        self.assertEqual(plan["estimated_channel_calls"]["object_continuity"], 0)
        self.assertEqual(plan["estimated_channel_calls"]["damage_causality"], 0)

    def test_formal_job_propagates_fulfillment_and_causality_contract(self):
        metadata = ReviewCaseMetadata.model_validate(
            {
                "client_case_id": "CASE-PROPAGATION-1",
                "scenario": "product_damage",
                "sampling_policy": {"preset": "strict"},
                "fulfillment_baseline": {
                    "baseline_version": "ORDER-1@V1",
                    "expected_items": [
                        {
                            "item_ref": "LINE-1",
                            "sku": "SKU-1",
                            "expected_quantity": 1,
                            "master_image_urls": ["https://cdn-qiniu.danhaotuan.com/sku-1.png"],
                        }
                    ],
                    "packages": [{"package_ref": "PKG-1", "expected_item_refs": ["LINE-1"]}],
                },
                "evidence_coverage": {
                    "submitted_package_refs": ["PKG-1"],
                    "all_packages_uploaded": True,
                    "all_items_displayed": True,
                },
            }
        ).model_dump(mode="json")
        fields = _review_fields(
            {
                "scenario": "product_damage",
                "client_case_id": "CASE-PROPAGATION-1",
                "metadata": metadata,
                "assets": [{"asset_id": "ASSET-1", "fields": ["unboxing_video"]}],
            }
        )
        self.assertTrue(json.loads(fields["damage_causality_policy"])["force_action_scan"])
        self.assertEqual(
            json.loads(fields["fulfillment_baseline"])["expected_items"][0]["sku"],
            "SKU-1",
        )
        self.assertEqual(
            json.loads(fields["fulfillment_baseline"])["expected_items"][0]["master_image_urls"],
            ["https://cdn-qiniu.danhaotuan.com/sku-1.png"],
        )
        self.assertEqual(json.loads(fields["evidence_coverage"])["submitted_package_refs"], ["PKG-1"])

    def test_formal_job_propagates_output_and_review_routing_options(self):
        metadata = ReviewCaseMetadata.model_validate(
            {
                "client_case_id": "CASE-OUTPUT-PROPAGATION",
                "scenario": "product_damage",
                "output_options": {"include_html_report": False},
                "review_routing_policy": {
                    "required_below_confidence": 0.48,
                    "optional_below_confidence": 0.82,
                    "out_of_frame_resubmit_seconds": 3.0,
                },
            }
        ).model_dump(mode="json")

        fields = _review_fields(
            {
                "scenario": "product_damage",
                "client_case_id": "CASE-OUTPUT-PROPAGATION",
                "metadata": metadata,
                "assets": [],
            }
        )

        self.assertEqual(fields["include_html_report"], "false")
        self.assertEqual(json.loads(fields["review_routing_policy"])["optional_below_confidence"], 0.82)

    def test_formal_job_propagates_structured_logistics_to_model_evidence(self):
        metadata = ReviewCaseMetadata.model_validate(
            {
                "client_case_id": "CASE-LOGISTICS-PROPAGATION",
                "scenario": "missing_item",
                "logistics": {
                    "shipment_status": "delivered",
                    "packages": [
                        {
                            "package_ref": "PKG-1",
                            "expected_item_refs": ["LINE-1"],
                            "status": "delivered",
                        }
                    ],
                },
            }
        ).model_dump(mode="json")
        fields = _review_fields(
            {
                "scenario": "missing_item",
                "client_case_id": "CASE-LOGISTICS-PROPAGATION",
                "metadata": metadata,
                "assets": [],
            }
        )

        current = apply_frontdesk_context(
            {"structured_business_context": {}},
            fields["scenario"],
            json.dumps(fields, ensure_ascii=False),
        )
        logistics = current["structured_business_context"]["frontdesk_evidence_package"]["logistics"]

        self.assertEqual(json.loads(fields["logistics_context"])["shipment_status"], "delivered")
        self.assertEqual(logistics["packages"][0]["expected_item_refs"], ["LINE-1"])

    def test_chinese_human_annotation_is_rejected_from_runtime_input(self):
        with self.assertRaisesRegex(ValueError, "evaluation_label_not_allowed"):
            ensure_label_isolation({"annotation": {"正/负样本": "负样本"}})

    def test_source_record_preserves_audit_fields_without_treating_them_as_model_input(self):
        source_record = {
            "tag": "negative",
            "status": "closed",
            "admin_status": "rejected",
            "final_decision": "negative",
            "final_outcome": "refund_rejected",
        }
        metadata = ReviewCaseMetadata.model_validate({
            "client_case_id": "CASE-SOURCE-AUDIT",
            "scenario": "product_damage",
            "source_record": source_record,
        })

        ensure_label_isolation(metadata.model_dump(mode="json"))
        self.assertEqual(metadata.source_record, source_record)

    def test_source_record_is_stored_but_never_forwarded_to_model(self):
        metadata = ReviewCaseMetadata.model_validate({
            "client_case_id": "CASE-SOURCE-STORAGE",
            "scenario": "product_damage",
            "source_record": {"case_reference": "REF-1"},
        }).model_dump(mode="json")

        fields = _review_fields({
            "scenario": "product_damage",
            "client_case_id": "CASE-SOURCE-STORAGE",
            "metadata": metadata,
            "assets": [],
        })

        self.assertNotIn("source_case", fields)

    def test_customer_claim_and_conversation_have_total_size_limits(self):
        with self.assertRaises(ValidationError):
            ReviewCaseMetadata.model_validate({
                "client_case_id": "CASE-CLAIM-LIMIT",
                "scenario": "product_damage",
                "customer_claim": "x" * 4001,
            })
        with self.assertRaisesRegex(ValidationError, "conversation_history_too_large"):
            ReviewCaseMetadata.model_validate({
                "client_case_id": "CASE-HISTORY-LIMIT",
                "scenario": "product_damage",
                "conversation_history": [
                    {"role": "user", "text": "x" * 4000},
                    {"role": "user", "text": "y" * 4000},
                    {"role": "user", "text": "z" * 4000},
                    {"role": "user", "text": "w"},
                ],
            })

    def test_customer_can_quote_previous_review_result_without_being_treated_as_gold_label(self):
        ensure_label_isolation({"customer_claim": "之前审核不通过，我要补充证据申请复核"})


if __name__ == "__main__":
    unittest.main()
