# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from review_service.input_readiness import assess_input_readiness
from review_service.schemas import ReviewCaseMetadata
from review_service.service import _public_media_urls, contract, sampling_plan
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

    def test_public_report_refreshes_signed_workbench_media_urls(self):
        with patch.dict("os.environ", {
            "VISUAL_REPORT_SIGNING_SECRET": "test-signing-secret",
            "VISUAL_WORKBENCH_PUBLIC_URL": "https://review.example.test",
        }):
            url = _public_media_urls("/media-item/opaque-id?expires=1&sig=expired")
        self.assertTrue(url.startswith("https://review.example.test/media-item/opaque-id?expires="))
        self.assertIn("&sig=", url)
        self.assertNotIn("expired", url)

    def test_wrong_item_accepts_unique_non_sku_baseline(self):
        result = assess_input_readiness(
            {
                "scenario": "wrong_item",
                "order_items": [{"name": "角色拍立得", "style": "A款", "quantity": 1}],
            }
        )
        self.assertTrue(result["full_review_ready"])
        self.assertNotIn("order_item_baseline", result["missing_required"])

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
        result = assess_input_readiness({"scenario": "product_damage"})
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

    def test_product_damage_adaptive_has_one_fps_quality_floor(self):
        plan = sampling_plan(
            452.5,
            543_351_335,
            1,
            {"preset": "adaptive", "frames_per_model_call": 24},
            "product_damage",
            {"force_dense_scan": False},
            {"force_action_scan": False},
        )
        self.assertEqual(plan["sampling_mode"], "dense")
        self.assertEqual(plan["fps"], 1.0)
        self.assertGreater(plan["estimated_channel_calls"]["object_continuity"], 0)
        self.assertGreater(plan["estimated_channel_calls"]["damage_causality"], 0)

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
        self.assertEqual(plan["main_review_frames"], 48)
        self.assertEqual(channels["main_review"], 2)
        self.assertGreater(channels["object_continuity"], 0)
        self.assertGreater(channels["damage_causality"], 0)
        self.assertEqual(plan["estimated_total_model_calls"], sum(channels.values()))

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
        self.assertEqual(plan["estimated_channel_calls"]["object_continuity"], 4)

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
        self.assertGreater(plan["estimated_channel_calls"]["object_continuity"], 0)
        self.assertGreater(plan["estimated_channel_calls"]["damage_causality"], 0)

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

    def test_chinese_human_annotation_is_rejected_from_runtime_input(self):
        with self.assertRaisesRegex(ValueError, "evaluation_label_not_allowed"):
            ensure_label_isolation({"annotation": {"正/负样本": "负样本"}})


if __name__ == "__main__":
    unittest.main()
