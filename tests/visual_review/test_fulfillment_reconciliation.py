from __future__ import annotations

import unittest
import json
from unittest.mock import patch

from poc.visual_review_poc.fulfillment_reconciliation import (
    aggregate_fulfillment_reconciliation,
    apply_fulfillment_guard,
)
from poc.visual_review_poc.local_video_triage_demo import scenario_rules
from prompts.visual_review.review_model_prompt import build_fulfillment_observation_prompt


def tracking_no(package_ref: str) -> str:
    return f"TRACK-{package_ref.removeprefix('PKG-')}"


def waybill_match_fact(package_ref: str) -> str:
    return f"画面中可见面单编号 {tracking_no(package_ref)}，与受信包裹候选一致。"


def waybill_observed_identifier_fact(package_ref: str) -> str:
    return f"画面中独立转录的完整面单编号为 {tracking_no(package_ref)}"


def case(expected_quantity: int = 2, packages=None, coverage=None):
    packages = packages or [{"package_ref": "PKG-1", "tracking_no": "TRACK-1", "expected_item_refs": ["LINE-1"]}]
    packages = [
        {**item, "tracking_no": item.get("tracking_no") or tracking_no(item["package_ref"])}
        for item in packages
    ]
    coverage = coverage or {
        "submitted_package_refs": [item["package_ref"] for item in packages],
        "all_packages_uploaded": True,
        "all_items_displayed": True,
    }
    return {
        "videos": [{"video_index": 1, "asset_ref": "native_video_1"}],
        "supplemental_images": [
            {"image_index": index, "asset_ref": f"supplemental_image_{index}"}
            for index in range(1, 6)
        ],
        "structured_business_context": {
            "frontdesk_evidence_package": {
                "fulfillment_baseline": {
                    "baseline_version": "ORDER-1@V1",
                    "expected_items": [
                        {"item_ref": "LINE-1", "sku": "SKU-1", "product_name": "徽章", "expected_quantity": expected_quantity}
                    ],
                    "expected_package_count": len(packages),
                    "packages": packages,
                    "split_shipment": len(packages) > 1,
                    "benefit_rules_complete": True,
                    "selection_rules_complete": True,
                },
                "evidence_coverage": coverage,
            }
        }
    }


def warehouse_verification(status: str, shipped_quantity: int, reference: str) -> dict:
    return {
        "status": status,
        "source": "customer_warehouse",
        "verification_ref": reference,
        "baseline_version": "ORDER-1@V1",
        "verified_at": "2026-08-13T10:00:00+08:00",
        "snapshot_ref": f"SNAP-{reference}",
        "packages": [{
            "package_ref": "PKG-1",
            "tracking_no": "TRACK-1",
            "actual_shipped_items": [{"item_ref": "LINE-1", "shipped_quantity": shipped_quantity}],
        }],
    }


def row(quantity: int, package_ref: str = "PKG-1", complete: bool = True):
    package_refs = [
        {
            "asset_ref": "native_video_1",
            "timestamp": "00:10.00",
            "field": field,
            "fact": (
                waybill_match_fact(package_ref)
                if field == "waybill_matches_order"
                else "该字段可由同一条开箱视频回看。"
            ),
        }
        for field in (
            "sealed_start",
            "waybill_visible",
            "waybill_matches_order",
            "single_take_continuity",
            "opening_complete",
            "all_contents_laid_out",
        )
    ]
    package_refs.append({
        "asset_ref": "native_video_1",
        "timestamp": "00:10.00",
        "field": "waybill_observed_identifier",
        "fact": waybill_observed_identifier_fact(package_ref),
        "observed_identifier": tracking_no(package_ref),
    })
    return {
        "fulfillment_reconciliation": {
            "observed_items": [
                {
                    "item_ref": "LINE-1",
                    "sku": "SKU-1",
                    "product_name": "徽章",
                    "specification": "",
                    "item_role": "ordered_item",
                    "series": "",
                    "edition": "",
                    "physical_form": "badge",
                    "included_parts": [],
                    "visible_identifiers": ["徽章"],
                    "descriptive_dimensions": [],
                    "observed_quantity": quantity,
                    "package_ref": package_ref,
                    "evidence_refs": [{
                        "asset_ref": "native_video_1",
                        "timestamp": "00:10.00",
                        "field": "observed_item",
                        "fact": "该包裹内可见该商品。",
                    }],
                }
            ],
            "unconfirmed_items": [],
            "package_observations": [
                {
                    "package_ref": package_ref,
                    "sealed_start": complete,
                    "waybill_visible": complete,
                    "observed_waybill_identifier": tracking_no(package_ref) if complete else None,
                    "waybill_matches_order": complete,
                    "single_take_continuity": complete,
                    "opening_complete": complete,
                    "all_contents_laid_out": complete,
                    "received_group_photo_complete": None,
                    "green_bag_visible": None,
                    "evidence_refs": package_refs,
                }
            ],
            "confidence": 0.88,
            "observation_reason": "按该包裹内的可见商品和开箱过程记录事实。",
        }
    }


class FulfillmentReconciliationTest(unittest.TestCase):
    def test_chunk_observations_are_aggregated_once_without_losing_confidence(self):
        from configs.model_catalog import MODEL_CONFIGS
        from poc.visual_review_poc.model_selection_e2e import call_model

        packages = [
            {"package_ref": "PKG-A", "expected_item_refs": ["LINE-1"]},
            {"package_ref": "PKG-B", "expected_item_refs": ["LINE-1"]},
        ]
        current = case(expected_quantity=2, packages=packages)
        current.update({
            "case_id": "fulfillment-chunks",
            "scenario": "missing_item",
            "frames": [],
            "supplemental_images": [],
            "official_reference_images": [],
        })
        current["structured_business_context"]["business_scenario"] = "missing_item"
        current["structured_business_context"]["review_chunk"] = {
            "index": 1,
            "total": 2,
        }

        observations = []
        for package_ref in ("PKG-A", "PKG-B"):
            payload = {
                "schema_version": "missing_item_observation_v2",
                "confidence": 0.88,
                "fulfillment_reconciliation": row(1, package_ref)["fulfillment_reconciliation"],
            }
            response = {
                "ok": True,
                "status_code": 200,
                "latency_seconds": 0.1,
                "attempt": 1,
                "data": {
                    "candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}],
                    "usageMetadata": {},
                },
            }
            with patch(
                "poc.visual_review_poc.model_selection_e2e.gemini_request_options",
                return_value=[{"endpoint": "https://example.invalid", "headers": {}}],
            ), patch(
                "poc.visual_review_poc.model_selection_e2e.post_with_retries",
                return_value=response,
            ):
                result = call_model(
                    dict(MODEL_CONFIGS["gemini35lite"]),
                    current,
                    timeout=1,
                    retries=0,
                )
            observation = result["parsed"]["fulfillment_reconciliation"]
            self.assertNotIn("evidence_sufficiency", observation)
            self.assertEqual(observation["confidence"], 0.88)
            observations.append(result["parsed"])

        final = aggregate_fulfillment_reconciliation(
            observations,
            current,
            "missing_item",
        )

        self.assertEqual(final["evidence_sufficiency"], "sufficient")
        self.assertEqual(final["verdict"], "matched")
        self.assertEqual(final["confidence"], 0.88)
        self.assertEqual(final["observation_confidence"], 0.88)

    def test_missing_item_prompt_does_not_use_ticket_suffix_as_review_gate(self):
        prompt = scenario_rules("missing_item")

        self.assertNotIn("_1 尾号", prompt)
        self.assertNotIn("二次处理单必须转人工", prompt)
        self.assertIn("仓库终核", prompt)
        self.assertIn("待核实备注本身不能下结论", prompt)

    def test_missing_item_prompt_uses_0813_video_and_static_evidence_routes(self):
        prompt = scenario_rules("missing_item")

        self.assertIn("视频内面单与订单物流一致", prompt)
        self.assertIn("一镜到底覆盖箱内全部商品", prompt)
        self.assertIn("全家福、绿色自封袋和清晰面单", prompt)
        self.assertIn("转人工客服读取仓库实发明细", prompt)
        self.assertIn("不能自行确认漏发或直接拒绝", prompt)
        self.assertNotIn("清晰照片已形成闭环，可以给出明确建议", prompt)

    def test_missing_item_prompt_keeps_paper_layer_check_as_follow_up_only(self):
        prompt = scenario_rules("missing_item")

        self.assertIn("确认漏发后的用户自查提醒", prompt)
        self.assertIn("不是 Agent 的漏发判定前置条件", prompt)
        self.assertNotIn("必须先确认透明包装已完全拆开并重新清点", prompt)

    def test_missing_item_prompt_does_not_expand_product_titles_into_expected_items(self):
        prompt = scenario_rules("missing_item")

        self.assertIn("系统订单商品行、SKU、数量和版本化活动规则", prompt)
        self.assertIn("商品标题、系列名或宣传组合效果", prompt)
        self.assertIn("不得自行扩充应发清单", prompt)

    def test_non_numeric_observation_confidence_degrades_to_zero(self):
        invalid = row(2)
        invalid["fulfillment_reconciliation"]["confidence"] = "high"

        result = aggregate_fulfillment_reconciliation([invalid], case(), "missing_item")

        self.assertEqual(result["observation_confidence"], 0.0)
        self.assertEqual(result["confidence"], 0.0)

    def test_same_package_repeated_across_chunks_uses_max_not_sum(self):
        result = aggregate_fulfillment_reconciliation([row(1), row(2)], case(), "missing_item")
        self.assertEqual(result["observed_items"][0]["observed_quantity"], 2)
        self.assertEqual(result["verdict"], "matched")
        guarded = apply_fulfillment_guard({"confidence": 0.88, "fulfillment_reconciliation": result}, "missing_item")
        self.assertEqual(guarded["predicted_label"], "negative")

    def test_observed_shortage_with_complete_package_is_mismatch(self):
        result = aggregate_fulfillment_reconciliation([row(1)], case(), "missing_item")
        self.assertEqual(result["verdict"], "mismatched")
        self.assertEqual(result["suspected_missing_items"][0]["observed_quantity"], 1)
        guarded = apply_fulfillment_guard({"confidence": 0.88, "fulfillment_reconciliation": result}, "missing_item")
        self.assertEqual(guarded["predicted_label"], "positive")

    def test_model_verified_package_route_does_not_require_frontend_self_reported_coverage(self):
        current = case(coverage={"all_packages_uploaded": False, "all_items_displayed": False})

        result = aggregate_fulfillment_reconciliation([row(1)], current, "missing_item")

        self.assertTrue(result["visual_coverage_verified"])
        self.assertTrue(result["user_materials_complete"])
        self.assertEqual(result["evidence_route"], "compliant_opening_video")
        self.assertEqual(result["evidence_sufficiency"], "sufficient")
        self.assertEqual(result["verdict"], "mismatched")

    def test_duplicate_sku_order_lines_are_summed_before_reconciliation(self):
        current = case(expected_quantity=1)
        baseline = current["structured_business_context"]["frontdesk_evidence_package"]["fulfillment_baseline"]
        baseline["expected_items"].append({
            "item_ref": "LINE-2",
            "sku": "SKU-1",
            "product_name": "徽章",
            "expected_quantity": 1,
        })
        baseline["packages"][0]["expected_item_refs"].append("LINE-2")

        result = aggregate_fulfillment_reconciliation([row(1)], current, "missing_item")

        self.assertEqual(result["verdict"], "mismatched")
        self.assertEqual(result["expected_items"][0]["expected_quantity"], 2)
        self.assertEqual(result["expected_items"][0]["item_refs"], ["LINE-1", "LINE-2"])
        self.assertEqual(result["suspected_missing_items"][0]["observed_quantity"], 1)

    def test_incomplete_visual_coverage_forces_review(self):
        result = aggregate_fulfillment_reconciliation([row(1, complete=False)], case(), "missing_item")
        guarded = apply_fulfillment_guard({"confidence": 0.91, "fulfillment_reconciliation": result}, "missing_item")
        self.assertEqual(result["evidence_sufficiency"], "insufficient")
        self.assertEqual(result["confidence"], 0.0)
        self.assertEqual(result["observation_confidence"], 0.88)
        self.assertEqual(guarded["predicted_label"], "review")
        self.assertLessEqual(guarded["confidence"], 0.69)

    def test_zero_media_references_cannot_form_a_certain_fulfillment_verdict(self):
        no_refs = row(2)
        no_refs["fulfillment_reconciliation"]["observed_items"][0]["evidence_refs"] = []
        no_refs["fulfillment_reconciliation"]["package_observations"][0]["evidence_refs"] = []

        result = aggregate_fulfillment_reconciliation([no_refs], case(), "missing_item")

        self.assertEqual(result["evidence_sufficiency"], "insufficient")
        self.assertEqual(result["verdict"], "indeterminate")
        self.assertTrue(result["unconfirmed_items"])

    def test_forged_asset_reference_cannot_form_a_certain_fulfillment_verdict(self):
        forged = row(2)
        for item in forged["fulfillment_reconciliation"]["observed_items"]:
            for ref in item["evidence_refs"]:
                ref["asset_ref"] = "native_video_999"
        for item in forged["fulfillment_reconciliation"]["package_observations"]:
            for ref in item["evidence_refs"]:
                ref["asset_ref"] = "native_video_999"

        result = aggregate_fulfillment_reconciliation([forged], case(), "missing_item")

        self.assertEqual(result["evidence_sufficiency"], "insufficient")
        self.assertEqual(result["verdict"], "indeterminate")

    def test_waybill_suffix_collision_remains_unconfirmed(self):
        packages = [
            {"package_ref": "PKG-1", "tracking_no": "YT001234", "expected_item_refs": ["LINE-1"]},
            {"package_ref": "PKG-2", "tracking_no": "SF991234", "expected_item_refs": ["LINE-2"]},
        ]
        observation = row(1)
        package = observation["fulfillment_reconciliation"]["package_observations"][0]
        identifier = next(ref for ref in package["evidence_refs"] if ref["field"] == "waybill_observed_identifier")
        identifier["fact"] = "画面中独立转录的面单编号末四位为 1234"
        identifier["observed_identifier"] = None
        package["observed_waybill_identifier"] = None

        result = aggregate_fulfillment_reconciliation([observation], case(packages=packages), "missing_item")

        self.assertIsNone(result["package_observations"][0]["waybill_matches_order"])
        self.assertEqual(result["evidence_sufficiency"], "insufficient")

    def test_unique_suffix_is_not_enough_to_verify_waybill(self):
        packages = [{"package_ref": "PKG-1", "tracking_no": "YT001234", "expected_item_refs": ["LINE-1"]}]
        observation = row(1)
        package = observation["fulfillment_reconciliation"]["package_observations"][0]
        identifier = next(ref for ref in package["evidence_refs"] if ref["field"] == "waybill_observed_identifier")
        identifier["fact"] = "画面中只能辨认面单编号末四位 1234"
        identifier["observed_identifier"] = None
        package["observed_waybill_identifier"] = None

        result = aggregate_fulfillment_reconciliation([observation], case(packages=packages), "missing_item")

        self.assertIsNone(result["package_observations"][0]["waybill_matches_order"])
        self.assertEqual(result["evidence_sufficiency"], "insufficient")

    def test_conflicting_package_coverage_flags_are_not_merged_with_boolean_or(self):
        incomplete = row(2, complete=False)
        complete = row(2, complete=True)

        result = aggregate_fulfillment_reconciliation([incomplete, complete], case(), "missing_item")

        package = result["package_observations"][0]
        self.assertIsNone(package["opening_complete"])
        self.assertIsNone(package["all_contents_laid_out"])
        self.assertEqual(result["evidence_sufficiency"], "insufficient")
        self.assertTrue(result["evidence_conflicts"])

    def test_video_route_requires_observed_waybill_identifier_to_match(self):
        observation = row(1)
        package = observation["fulfillment_reconciliation"]["package_observations"][0]
        observed_ref = next(
            ref for ref in package["evidence_refs"]
            if ref["field"] == "waybill_observed_identifier"
        )
        observed_ref["fact"] = "画面中独立转录的面单编号末四位为 ZZZZ"
        observed_ref["observed_identifier"] = "ZZZZ"

        result = aggregate_fulfillment_reconciliation([observation], case(), "missing_item")

        self.assertEqual(result["evidence_route"], "insufficient")
        self.assertFalse(result["user_materials_complete"])
        self.assertEqual(result["evidence_sufficiency"], "insufficient")
        self.assertEqual(result["verdict"], "indeterminate")

    def test_waybill_match_without_visible_identifier_is_not_trusted(self):
        observation = row(1)
        package = observation["fulfillment_reconciliation"]["package_observations"][0]
        match_ref = next(
            ref for ref in package["evidence_refs"]
            if ref["field"] == "waybill_matches_order"
        )
        match_ref["fact"] = "画面中的面单与受信包裹候选一致。"
        package["evidence_refs"] = [
            ref for ref in package["evidence_refs"]
            if ref["field"] != "waybill_observed_identifier"
        ]
        package["observed_waybill_identifier"] = None

        result = aggregate_fulfillment_reconciliation([observation], case(), "wrong_item")
        package_result = result["package_observations"][0]
        match_fact = next(
            fact for fact in package_result["atomic_facts"]
            if fact["field"] == "waybill_matches_order"
        )

        self.assertIsNone(package_result["waybill_matches_order"])
        self.assertIsNone(match_fact["value"])
        self.assertEqual(result["evidence_route"], "insufficient")
        self.assertEqual(result["verdict"], "indeterminate")

    def test_waybill_match_is_derived_only_from_independent_observed_identifier(self):
        observation = row(1)
        package = observation["fulfillment_reconciliation"]["package_observations"][0]
        package["waybill_matches_order"] = None

        result = aggregate_fulfillment_reconciliation([observation], case(), "wrong_item")
        self.assertTrue(result["package_observations"][0]["waybill_matches_order"])

        self_declared = row(1)
        package = self_declared["fulfillment_reconciliation"]["package_observations"][0]
        package["evidence_refs"] = [
            ref for ref in package["evidence_refs"]
            if ref["field"] != "waybill_observed_identifier"
        ]
        package["observed_waybill_identifier"] = None

        untrusted = aggregate_fulfillment_reconciliation([self_declared], case(), "wrong_item")
        self.assertIsNone(untrusted["package_observations"][0]["waybill_matches_order"])

    def test_package_identifier_field_completes_static_route_without_exposing_identifier(self):
        observation = row(1, complete=False)
        package = observation["fulfillment_reconciliation"]["package_observations"][0]
        package.update({
            "observed_waybill_identifier": tracking_no("PKG-1"),
            "received_group_photo_complete": True,
            "green_bag_visible": True,
            "waybill_visible": True,
            "waybill_matches_order": None,
            "evidence_refs": [
                {
                    "asset_ref": "supplemental_image_1",
                    "timestamp": None,
                    "field": field,
                    "fact": "静态降级路径材料可核验。",
                }
                for field in (
                    "received_group_photo_complete",
                    "green_bag_visible",
                    "waybill_visible",
                )
            ],
        })

        result = aggregate_fulfillment_reconciliation([observation], case(), "wrong_item")
        package_result = result["package_observations"][0]

        self.assertTrue(package_result["waybill_matches_order"])
        self.assertEqual(result["evidence_route"], "static_three_images")
        self.assertTrue(result["user_materials_complete"])
        self.assertNotIn(tracking_no("PKG-1"), json.dumps(result, ensure_ascii=False))

        package["evidence_refs"] = [
            ref for ref in package["evidence_refs"]
            if ref["field"] != "waybill_visible"
        ]
        untrusted = aggregate_fulfillment_reconciliation([observation], case(), "wrong_item")
        self.assertIsNone(untrusted["package_observations"][0]["waybill_matches_order"])
        self.assertEqual(untrusted["evidence_route"], "insufficient")

    def test_static_route_accepts_traceable_all_contents_laid_out_fact(self):
        observation = row(1, complete=False)
        package = observation["fulfillment_reconciliation"]["package_observations"][0]
        package.update({
            "observed_waybill_identifier": tracking_no("PKG-1"),
            "all_contents_laid_out": True,
            "received_group_photo_complete": True,
            "green_bag_visible": True,
            "waybill_visible": True,
            "waybill_matches_order": None,
            "evidence_refs": [
                {
                    "asset_ref": "supplemental_image_1",
                    "timestamp": None,
                    "field": field,
                    "fact": "静态降级路径材料可核验。",
                }
                for field in (
                    "all_contents_laid_out",
                    "green_bag_visible",
                    "waybill_visible",
                )
            ],
        })

        result = aggregate_fulfillment_reconciliation([observation], case(), "wrong_item")

        self.assertEqual(result["evidence_route"], "static_three_images")
        self.assertTrue(result["user_materials_complete"])

    def test_static_three_image_route_is_complete_for_user_but_waits_for_warehouse(self):
        observation = row(1, complete=False)
        package = observation["fulfillment_reconciliation"]["package_observations"][0]
        package.update({
            "received_group_photo_complete": True,
            "green_bag_visible": True,
            "waybill_visible": True,
            "waybill_matches_order": True,
            "evidence_refs": [
                {
                    "asset_ref": "supplemental_image_1",
                    "timestamp": None,
                    "field": field,
                    "fact": (
                        waybill_observed_identifier_fact("PKG-1")
                        if field == "waybill_observed_identifier"
                        else waybill_match_fact("PKG-1")
                        if field == "waybill_matches_order"
                        else "静态降级路径材料可核验。"
                    ),
                    "observed_identifier": tracking_no("PKG-1") if field == "waybill_observed_identifier" else None,
                }
                for field in (
                    "received_group_photo_complete",
                    "green_bag_visible",
                    "waybill_visible",
                    "waybill_matches_order",
                    "waybill_observed_identifier",
                )
            ],
        })

        result = aggregate_fulfillment_reconciliation([observation], case(), "missing_item")
        guarded = apply_fulfillment_guard(
            {"confidence": 0.88, "fulfillment_reconciliation": result},
            "missing_item",
        )

        self.assertEqual(result["evidence_route"], "static_three_images")
        self.assertNotIn("review_route", result)
        self.assertEqual(result["resolution_basis"], "none")
        self.assertEqual(result["warehouse_check"], {"state": "pending", "outcome": None})
        self.assertTrue(result["user_materials_complete"])
        self.assertEqual(result["evidence_sufficiency"], "insufficient")
        self.assertEqual(result["verdict"], "indeterminate")
        self.assertEqual(guarded["predicted_label"], "review")
        self.assertNotEqual(guarded["decision"], "request_more_material")
        self.assertIn("仓库实发明细", guarded["next_step"])

    def test_standalone_waybill_photo_cannot_complete_the_opening_video_route(self):
        observation = row(1)
        package = observation["fulfillment_reconciliation"]["package_observations"][0]
        package["evidence_refs"] = [
            ref for ref in package["evidence_refs"]
            if ref["field"] not in {"waybill_visible", "waybill_matches_order"}
        ] + [
            {
                "asset_ref": "supplemental_image_1",
                "timestamp": None,
                "field": field,
                "fact": "单独上传的面单照片。",
            }
            for field in ("waybill_visible", "waybill_matches_order")
        ]

        result = aggregate_fulfillment_reconciliation([observation], case(), "missing_item")

        self.assertEqual(result["evidence_route"], "insufficient")
        self.assertEqual(result["verdict"], "indeterminate")

    def test_mixed_video_and_static_package_coverage_uses_static_human_route(self):
        packages = [
            {"package_ref": "PKG-1", "expected_item_refs": ["LINE-1"]},
            {"package_ref": "PKG-2", "expected_item_refs": ["LINE-1"]},
        ]
        static = row(1, "PKG-2", complete=False)
        package = static["fulfillment_reconciliation"]["package_observations"][0]
        package.update({
            "received_group_photo_complete": True,
            "green_bag_visible": True,
            "waybill_visible": True,
            "waybill_matches_order": True,
            "evidence_refs": [
                {
                    "asset_ref": "supplemental_image_2",
                    "timestamp": None,
                    "field": field,
                    "fact": (
                        waybill_observed_identifier_fact("PKG-2")
                        if field == "waybill_observed_identifier"
                        else waybill_match_fact("PKG-2")
                        if field == "waybill_matches_order"
                        else "第二包裹静态材料可回看。"
                    ),
                    "observed_identifier": tracking_no("PKG-2") if field == "waybill_observed_identifier" else None,
                }
                for field in (
                    "received_group_photo_complete",
                    "green_bag_visible",
                    "waybill_visible",
                    "waybill_matches_order",
                    "waybill_observed_identifier",
                )
            ],
        })

        result = aggregate_fulfillment_reconciliation(
            [row(1, "PKG-1"), static],
            case(expected_quantity=2, packages=packages),
            "missing_item",
        )

        self.assertTrue(result["user_materials_complete"])
        self.assertEqual(result["evidence_route"], "static_three_images")
        self.assertEqual(result["warehouse_check"], {"state": "pending", "outcome": None})
        self.assertEqual(result["verdict"], "indeterminate")

    def test_trusted_expected_item_resolution_does_not_pretend_user_materials_are_complete(self):
        current = case(expected_quantity=1)
        baseline = current["structured_business_context"]["frontdesk_evidence_package"]["fulfillment_baseline"]
        baseline["expected_items"].append({
            "item_ref": "LINE-2",
            "sku": "SKU-2",
            "product_name": "同订单其他商品",
            "specification": "标准款",
            "expected_quantity": 1,
        })
        baseline["claim_expected_item_resolution"] = {
            "claimed_item": "纪念摆件配套赠品",
            "is_expected": False,
            "baseline_version": "ORDER-1@V1",
            "source": "product_master",
            "resolution_ref": "PRODUCT-COMPOSITION-GENERIC",
            "reason": "订单商品本体就是摆件，标题中的描述不是另一件独立应发商品。",
            "required_received_item_refs": ["LINE-1"],
        }

        result = aggregate_fulfillment_reconciliation(
            [row(1, complete=False)],
            current,
            "missing_item",
        )
        guarded = apply_fulfillment_guard(
            {"confidence": 0.88, "fulfillment_reconciliation": result},
            "missing_item",
        )

        self.assertEqual(result["evidence_route"], "not_required")
        self.assertNotIn("review_route", result)
        self.assertEqual(result["resolution_basis"], "trusted_expected_item_resolution")
        self.assertFalse(result["user_materials_complete"])
        self.assertEqual(result["warehouse_check"], {"state": "not_available", "outcome": None})
        self.assertEqual(result["evidence_sufficiency"], "sufficient")
        self.assertEqual(result["verdict"], "matched")
        self.assertEqual(guarded["predicted_label"], "negative")
        self.assertNotEqual(guarded.get("decision"), "request_more_material")
        self.assertIn("商品构成", result["decision_boundary"])

        prompt = build_fulfillment_observation_prompt({
            **current,
            "scenario": "missing_item",
            "scenario_label": "漏发货审核",
            "videos": [],
            "supplemental_images": [],
            "official_reference_images": [],
        })
        self.assertNotIn("PRODUCT-COMPOSITION-GENERIC", prompt)
        self.assertNotIn("标题中的描述不是另一件独立应发商品", prompt)
        self.assertIn("完整编号精确一致", prompt)
        self.assertIn("部分编号不得自动匹配", prompt)

    def test_fulfillment_facts_keep_confidence_reason_and_reviewable_evidence(self):
        result = aggregate_fulfillment_reconciliation([row(2)], case(), "missing_item")

        observed = result["observed_items"][0]
        self.assertEqual(observed["confidence"], 0.88)
        self.assertIn("可见商品", observed["reason"])
        self.assertEqual(observed["evidence_refs"][0]["field"], "observed_item")

        package = result["package_observations"][0]
        atomic_facts = {item["field"]: item for item in package["atomic_facts"]}
        self.assertEqual(set(atomic_facts), set((
            "sealed_start",
            "waybill_visible",
            "waybill_matches_order",
            "single_take_continuity",
            "opening_complete",
            "all_contents_laid_out",
            "received_group_photo_complete",
            "green_bag_visible",
        )))
        self.assertTrue(atomic_facts["opening_complete"]["value"])
        self.assertEqual(atomic_facts["opening_complete"]["confidence"], 0.88)
        self.assertTrue(atomic_facts["opening_complete"]["reason"])
        self.assertEqual(
            atomic_facts["opening_complete"]["evidence_refs"][0]["field"],
            "opening_complete",
        )

    def test_568689_includes_the_confirmed_warehouse_fact(self):
        current = case(expected_quantity=1)
        baseline = current["structured_business_context"]["frontdesk_evidence_package"]["fulfillment_baseline"]
        baseline["claim_expected_item_resolution"] = {
            "claimed_item": "纪念摆件配套赠品",
            "is_expected": False,
            "baseline_version": "ORDER-1@V1",
            "source": "product_master",
            "resolution_ref": "PRODUCT-COMPOSITION-568689",
            "reason": "商品主数据说明该描述不是另一件独立应发商品。",
            "required_received_item_refs": ["LINE-1"],
        }
        baseline["warehouse_verification"] = warehouse_verification(
            "confirmed_not_missing", 1, "WH-568689"
        )

        result = aggregate_fulfillment_reconciliation(
            [row(1, complete=False)], current, "missing_item"
        )

        self.assertEqual(result["evidence_route"], "not_required")
        self.assertEqual(result["resolution_basis"], "warehouse_verification")
        self.assertEqual(
            result["warehouse_check"],
            {"state": "verified", "outcome": "confirmed_not_missing"},
        )
        self.assertEqual(result["verdict"], "matched")

    def test_product_composition_resolution_overrides_noisy_visual_missing_or_wrong_item_signals(self):
        current = case(expected_quantity=1)
        baseline = current["structured_business_context"]["frontdesk_evidence_package"]["fulfillment_baseline"]
        baseline["claim_expected_item_resolution"] = {
            "claimed_item": "商品标题中的附属描述",
            "is_expected": False,
            "baseline_version": "ORDER-1@V1",
            "source": "product_master",
            "resolution_ref": "PRODUCT-COMPOSITION-NOISY",
            "reason": "该描述不是独立应发商品行。",
            "required_received_item_refs": ["LINE-1"],
        }
        noisy = row(1, complete=False)
        noisy["fulfillment_reconciliation"]["observed_items"].append({
            "item_ref": "",
            "sku": "",
            "product_name": "画面中的其他未确认实物",
            "specification": "",
            "observed_quantity": 1,
            "package_ref": "PKG-1",
            "evidence_refs": [{
                "asset_ref": "supplemental_image_1",
                "timestamp": None,
                "field": "observed_item",
                "fact": "补图中另见一件与当前商品构成争议无关的实物。",
            }],
        })

        result = aggregate_fulfillment_reconciliation([noisy], current, "missing_item")
        guarded = apply_fulfillment_guard(
            {"confidence": 0.88, "fulfillment_reconciliation": result},
            "missing_item",
        )

        self.assertEqual(result["evidence_route"], "not_required")
        self.assertEqual(result["resolution_basis"], "trusted_expected_item_resolution")
        self.assertEqual(result["verdict"], "matched")
        self.assertEqual(guarded["predicted_label"], "negative")

    def test_placeholder_spec_variants_do_not_split_the_same_order_item(self):
        current = case(expected_quantity=1)
        baseline = current["structured_business_context"]["frontdesk_evidence_package"]["fulfillment_baseline"]
        baseline["expected_items"][0]["specification"] = "-"
        baseline["claim_expected_item_resolution"] = {
            "claimed_item": "商品标题中的附属描述",
            "is_expected": False,
            "baseline_version": "ORDER-1@V1",
            "source": "product_master",
            "resolution_ref": "PRODUCT-COMPOSITION-PLACEHOLDER-SPEC",
            "reason": "该描述不是独立应发商品行。",
            "required_received_item_refs": ["LINE-1"],
        }
        observation = row(1, complete=False)
        observed = observation["fulfillment_reconciliation"]["observed_items"][0]
        observed["item_ref"] = "LINE-1"
        observed["specification"] = "--"

        result = aggregate_fulfillment_reconciliation(
            [observation],
            current,
            "missing_item",
        )

        self.assertEqual(result["observed_items"][0]["item_ref"], "LINE-1")
        self.assertEqual(result["suspected_missing_items"], [])
        self.assertEqual(result["unexpected_items"], [])
        self.assertEqual(result["evidence_route"], "not_required")
        self.assertEqual(result["resolution_basis"], "trusted_expected_item_resolution")
        self.assertEqual(result["verdict"], "matched")

    def test_untrusted_or_stale_product_composition_resolution_is_ignored(self):
        current = case(expected_quantity=1)
        baseline = current["structured_business_context"]["frontdesk_evidence_package"]["fulfillment_baseline"]
        baseline["claim_expected_item_resolution"] = {
            "claimed_item": "标题中疑似附属品",
            "is_expected": False,
            "baseline_version": "STALE-VERSION",
            "source": "customer_text",
            "resolution_ref": "FREE-TEXT-1",
            "reason": "用户文本自行解释。",
            "required_received_item_refs": ["LINE-1"],
        }

        result = aggregate_fulfillment_reconciliation(
            [row(1, complete=False)],
            current,
            "missing_item",
        )

        self.assertEqual(result["evidence_route"], "insufficient")
        self.assertEqual(result["verdict"], "indeterminate")

    def test_traceable_warehouse_confirmation_overrides_pending_visual_coverage(self):
        current = case()
        baseline = current["structured_business_context"]["frontdesk_evidence_package"]["fulfillment_baseline"]
        baseline["warehouse_verification"] = warehouse_verification("confirmed_not_missing", 2, "WH-CHECK-1")

        result = aggregate_fulfillment_reconciliation([row(1, complete=False)], current, "missing_item")
        guarded = apply_fulfillment_guard({
            "confidence": 0.2,
            "confidence_reason": "缺少开箱视频，需要人工复核。",
            "business_follow_up_reason": "缺少开箱视频，需要人工复核。",
            "next_step": "转人工并要求补开箱视频。",
            "claim_fact_assessment": {
                "atomic_claim_results": [{
                    "claim_id": "claim-missing-item",
                    "subject_ref": "LINE-1",
                    "support_status": "insufficient",
                    "reason": "仅有静态图片，证据不足。",
                    "evidence_refs": [{"asset_ref": "supplemental_image_1"}],
                }],
            },
            "fulfillment_reconciliation": result,
        }, "missing_item")

        self.assertEqual(result["verdict"], "matched")
        self.assertEqual(result["evidence_sufficiency"], "sufficient")
        self.assertEqual(result["resolution_basis"], "warehouse_verification")
        self.assertEqual(result["evidence_route"], "insufficient")
        self.assertEqual(
            result["warehouse_check"],
            {"state": "verified", "outcome": "confirmed_not_missing"},
        )
        self.assertEqual(result["warehouse_verification"]["status"], "confirmed_not_missing")
        self.assertTrue(result["warehouse_verification"]["traceability_complete"])
        self.assertNotIn("traceability_completeness", result["warehouse_verification"])
        self.assertNotIn("confidence_basis", result["warehouse_verification"])
        self.assertIn("仓库终核", result["package_coverage"])
        self.assertNotIn("0/1", result["package_coverage"])
        self.assertEqual(guarded["predicted_label"], "negative")
        self.assertEqual(guarded["confidence"], 0.88)
        self.assertEqual(guarded["fulfillment_reconciliation"]["observation_confidence"], 0.88)
        self.assertIn("仓库终核", guarded["fulfillment_guard_reason"])
        self.assertIn("仓库终核", guarded["confidence_reason"])
        self.assertIn("仓库终核", guarded["business_follow_up_reason"])
        self.assertNotIn("补开箱视频", guarded["next_step"])
        self.assertEqual(guarded["fulfillment_reconciliation"]["suspected_missing_items"], [])
        self.assertIn("仓库终核", guarded["overall_audit"]["core_reason"])
        self.assertEqual(guarded["adopted_evidence"][0]["source_type"], "warehouse_verification")
        atomic_claim = guarded["claim_fact_assessment"]["atomic_claim_results"][0]
        self.assertEqual(atomic_claim["support_status"], "not_supported")
        self.assertIn("确定未漏发", atomic_claim["reason"])
        self.assertEqual(atomic_claim["evidence_refs"][0]["asset_ref"], "WH-CHECK-1")

    def test_pending_warehouse_note_does_not_override_visual_evidence(self):
        current = case()
        baseline = current["structured_business_context"]["frontdesk_evidence_package"]["fulfillment_baseline"]
        baseline["warehouse_verification"] = {
            "status": "pending",
            "source": "customer_warehouse",
            "verification_ref": "WH-CHECK-2",
        }

        result = aggregate_fulfillment_reconciliation([row(1, complete=False)], current, "missing_item")

        self.assertEqual(result["verdict"], "indeterminate")
        self.assertNotEqual(result.get("resolution_basis"), "warehouse_verification")
        self.assertEqual(result["warehouse_check"], {"state": "pending", "outcome": None})

    def test_warehouse_terminal_rejects_items_assigned_to_the_wrong_package(self):
        packages = [
            {"package_ref": "PKG-1", "tracking_no": "TRACK-1", "expected_item_refs": ["LINE-1"]},
            {"package_ref": "PKG-2", "tracking_no": "TRACK-2", "expected_item_refs": ["LINE-2"]},
        ]
        current = case(expected_quantity=1, packages=packages)
        baseline = current["structured_business_context"]["frontdesk_evidence_package"]["fulfillment_baseline"]
        baseline["expected_items"].append({
            "item_ref": "LINE-2", "sku": "SKU-2", "product_name": "立牌", "expected_quantity": 1,
        })
        baseline["warehouse_verification"] = {
            "status": "confirmed_not_missing",
            "source": "customer_warehouse",
            "verification_ref": "WH-WRONG-PACKAGE",
            "baseline_version": "ORDER-1@V1",
            "verified_at": "2026-08-13T10:00:00+08:00",
            "snapshot_ref": "SNAP-WH-WRONG-PACKAGE",
            "packages": [
                {
                    "package_ref": "PKG-1",
                    "tracking_no": "TRACK-1",
                    "actual_shipped_items": [{"item_ref": "LINE-2", "shipped_quantity": 1}],
                },
                {
                    "package_ref": "PKG-2",
                    "tracking_no": "TRACK-2",
                    "actual_shipped_items": [{"item_ref": "LINE-1", "shipped_quantity": 1}],
                },
            ],
        }

        result = aggregate_fulfillment_reconciliation([], current, "missing_item")

        self.assertEqual(result["warehouse_verification"], {})
        self.assertEqual(result["warehouse_check"], {"state": "pending", "outcome": None})
        self.assertEqual(result["resolution_basis"], "none")

    def test_traceable_warehouse_missing_confirmation_is_positive(self):
        current = case(expected_quantity=1)
        baseline = current["structured_business_context"]["frontdesk_evidence_package"]["fulfillment_baseline"]
        baseline["warehouse_verification"] = warehouse_verification("confirmed_missing", 0, "WH-CHECK-3")

        result = aggregate_fulfillment_reconciliation([row(1)], current, "missing_item")
        guarded = apply_fulfillment_guard({"confidence": 0.91, "fulfillment_reconciliation": result}, "missing_item")

        self.assertEqual(result["verdict"], "mismatched")
        self.assertEqual(guarded["predicted_label"], "positive")

    def test_warehouse_status_that_conflicts_with_shipped_quantities_is_rejected(self):
        current = case(expected_quantity=1)
        baseline = current["structured_business_context"]["frontdesk_evidence_package"]["fulfillment_baseline"]
        baseline["warehouse_verification"] = warehouse_verification("confirmed_missing", 1, "WH-CONFLICT-1")

        result = aggregate_fulfillment_reconciliation([row(1, complete=False)], current, "missing_item")

        self.assertEqual(result["evidence_route"], "insufficient")
        self.assertEqual(result["warehouse_verification"], {})
        self.assertEqual(result["verdict"], "indeterminate")

    def test_untraceable_warehouse_claim_is_not_authoritative(self):
        current = case()
        baseline = current["structured_business_context"]["frontdesk_evidence_package"]["fulfillment_baseline"]
        baseline["warehouse_verification"] = {
            "status": "confirmed_not_missing",
            "source": "model_inference",
            "verification_ref": "",
        }

        result = aggregate_fulfillment_reconciliation([row(1, complete=False)], current, "missing_item")

        self.assertEqual(result["verdict"], "indeterminate")
        self.assertEqual(result.get("warehouse_verification"), {})

    def test_quantities_sum_across_distinct_packages(self):
        packages = [
            {"package_ref": "PKG-1", "expected_item_refs": ["LINE-1"]},
            {"package_ref": "PKG-2", "expected_item_refs": ["LINE-1"]},
        ]
        result = aggregate_fulfillment_reconciliation(
            [row(1, "PKG-1"), row(1, "PKG-2")],
            case(packages=packages),
            "missing_item",
        )
        self.assertEqual(result["observed_items"][0]["observed_quantity"], 2)
        self.assertEqual(result["verdict"], "matched")

    def test_items_swapped_between_packages_do_not_cancel_at_order_total(self):
        packages = [
            {"package_ref": "PKG-A", "expected_item_refs": ["LINE-1"]},
            {"package_ref": "PKG-B", "expected_item_refs": ["LINE-2"]},
        ]
        current = case(expected_quantity=1, packages=packages)
        baseline = current["structured_business_context"]["frontdesk_evidence_package"]["fulfillment_baseline"]
        baseline["expected_items"].append({
            "item_ref": "LINE-2",
            "sku": "SKU-2",
            "product_name": "立牌",
            "expected_quantity": 1,
        })
        package_a = row(1, "PKG-A")
        package_a["fulfillment_reconciliation"]["observed_items"][0].update({
            "item_ref": "LINE-2",
            "sku": "SKU-2",
            "product_name": "立牌",
        })
        package_b = row(1, "PKG-B")

        result = aggregate_fulfillment_reconciliation(
            [package_a, package_b], current, "wrong_item"
        )
        guarded = apply_fulfillment_guard(
            {"confidence": 0.88, "fulfillment_reconciliation": result}, "wrong_item"
        )

        self.assertEqual(result["verdict"], "mismatched")
        self.assertEqual(
            {item["package_ref"] for item in result["suspected_missing_items"]},
            {"PKG-A", "PKG-B"},
        )
        self.assertEqual(
            {item["package_ref"] for item in result["unexpected_items"]},
            {"PKG-A", "PKG-B"},
        )
        self.assertEqual(guarded["predicted_label"], "positive")

    def test_model_evidence_can_resolve_package_without_frontend_package_refs(self):
        result = aggregate_fulfillment_reconciliation(
            [row(1)],
            case(coverage={"all_packages_uploaded": True, "all_items_displayed": True}),
            "missing_item",
        )
        self.assertEqual(result["verdict"], "mismatched")
        self.assertFalse(result["submitted_package_mapping_complete"])
        self.assertTrue(result["visual_coverage_verified"])
        self.assertEqual(result["evidence_sufficiency"], "sufficient")

    def test_unknown_observed_package_forces_review(self):
        result = aggregate_fulfillment_reconciliation(
            [row(1), row(1, package_ref="PKG-X")],
            case(),
            "missing_item",
        )
        self.assertEqual(result["verdict"], "indeterminate")
        self.assertEqual(result["unknown_package_refs"], ["PKG-X"])

    def test_incomplete_applicable_selection_rules_force_review(self):
        current = case()
        baseline = current["structured_business_context"]["frontdesk_evidence_package"]["fulfillment_baseline"]
        baseline["selection_rules"] = [{"rule_ref": "LOTTERY-1", "item_refs": ["LINE-1"]}]
        baseline["selection_rules_complete"] = False
        result = aggregate_fulfillment_reconciliation([row(2)], current, "wrong_item")
        self.assertEqual(result["verdict"], "indeterminate")
        self.assertFalse(result["selection_rules_complete"])

    def test_same_sku_with_different_specification_is_wrong_item(self):
        current = case(expected_quantity=1)
        expected = current["structured_business_context"]["frontdesk_evidence_package"]["fulfillment_baseline"]["expected_items"][0]
        expected["specification"] = "L"
        observed = row(1)
        observed["fulfillment_reconciliation"]["observed_items"][0]["specification"] = "S"

        result = aggregate_fulfillment_reconciliation([observed], current, "wrong_item")
        guarded = apply_fulfillment_guard({"confidence": 0.88, "fulfillment_reconciliation": result}, "wrong_item")

        self.assertEqual(result["verdict"], "mismatched")
        self.assertEqual(guarded["predicted_label"], "positive")

    def test_identity_defining_edition_difference_is_wrong_item(self):
        current = case(expected_quantity=1)
        expected = current["structured_business_context"]["frontdesk_evidence_package"]["fulfillment_baseline"]["expected_items"][0]
        expected.update({"item_role": "main_product", "series": "星轨", "edition": "金色版"})
        observed = row(1)
        observed["fulfillment_reconciliation"]["observed_items"][0].update({
            "item_role": "main_product", "series": "星轨", "edition": "银色版",
        })

        result = aggregate_fulfillment_reconciliation([observed], current, "wrong_item")

        self.assertEqual(result["verdict"], "mismatched")
        self.assertEqual(len(result["suspected_missing_items"]), 1)
        self.assertEqual(len(result["unexpected_items"]), 1)

    def test_descriptive_dimension_difference_alone_is_not_wrong_item(self):
        current = case(expected_quantity=1)
        expected = current["structured_business_context"]["frontdesk_evidence_package"]["fulfillment_baseline"]["expected_items"][0]
        expected["descriptive_dimensions"] = ["约 15 cm"]
        observed = row(1)
        observed["fulfillment_reconciliation"]["observed_items"][0]["descriptive_dimensions"] = ["约 14.8 cm"]

        result = aggregate_fulfillment_reconciliation([observed], current, "wrong_item")

        self.assertEqual(result["verdict"], "matched")
        self.assertEqual(result["unexpected_items"], [])

    def test_missing_observed_specification_keeps_wrong_item_indeterminate(self):
        current = case(expected_quantity=1)
        expected = current["structured_business_context"]["frontdesk_evidence_package"]["fulfillment_baseline"]["expected_items"][0]
        expected["specification"] = "L"

        result = aggregate_fulfillment_reconciliation([row(1)], current, "wrong_item")

        self.assertEqual(result["verdict"], "indeterminate")
        self.assertEqual(result["evidence_sufficiency"], "insufficient")

    def test_non_numeric_observed_quantity_keeps_missing_item_indeterminate(self):
        invalid = row(1)
        invalid["fulfillment_reconciliation"]["observed_items"][0]["observed_quantity"] = "many"

        result = aggregate_fulfillment_reconciliation([invalid], case(), "missing_item")

        self.assertEqual(result["verdict"], "indeterminate")
        self.assertEqual(result["evidence_sufficiency"], "insufficient")

    def test_wrong_item_with_only_missing_expected_transitions_to_missing_item(self):
        result = aggregate_fulfillment_reconciliation([row(1)], case(expected_quantity=2), "wrong_item")
        guarded = apply_fulfillment_guard({"confidence": 0.88, "fulfillment_reconciliation": result}, "wrong_item")

        self.assertEqual(result["verdict"], "indeterminate")
        self.assertEqual(result["scenario_transition"], "missing_item")
        self.assertEqual(guarded["predicted_label"], "review")
        self.assertIn("漏发", result["decision_boundary"])

    def test_wrong_item_treats_surplus_of_an_expected_sku_as_received_difference(self):
        current = case(expected_quantity=1)
        baseline = current["structured_business_context"]["frontdesk_evidence_package"]["fulfillment_baseline"]
        baseline["expected_items"].append({
            "item_ref": "LINE-2",
            "sku": "SKU-2",
            "product_name": "standee",
            "expected_quantity": 1,
        })
        baseline["packages"][0]["expected_item_refs"].append("LINE-2")

        result = aggregate_fulfillment_reconciliation([row(2)], current, "wrong_item")
        guarded = apply_fulfillment_guard(
            {"confidence": 0.88, "fulfillment_reconciliation": result},
            "wrong_item",
        )

        self.assertEqual(result["verdict"], "mismatched")
        self.assertIsNone(result["scenario_transition"])
        self.assertEqual(result["unexpected_items"][0]["observed_quantity"], 1)
        self.assertEqual(result["unexpected_items"][0]["item_ref"], "LINE-1")
        self.assertEqual(guarded["predicted_label"], "positive")

    def test_missing_item_ignores_extra_item_when_expected_quantity_is_complete(self):
        observed = row(2)
        observed["fulfillment_reconciliation"]["observed_items"].append({
            "sku": "SKU-X", "product_name": "额外赠品", "observed_quantity": 1, "package_ref": "PKG-1",
            "evidence_refs": [{
                "asset_ref": "native_video_1", "timestamp": "00:11.00", "fact": "同包裹内另见一件赠品。",
            }],
        })

        result = aggregate_fulfillment_reconciliation([observed], case(), "missing_item")
        guarded = apply_fulfillment_guard({"confidence": 0.88, "fulfillment_reconciliation": result}, "missing_item")

        self.assertEqual(result["verdict"], "matched")
        self.assertEqual(guarded["predicted_label"], "negative")

    def test_missing_expected_and_unexpected_received_does_not_confirm_missing_item(self):
        observed = row(1)
        observed["fulfillment_reconciliation"]["observed_items"].append({
            "sku": "SKU-X", "product_name": "未购商品", "observed_quantity": 1, "package_ref": "PKG-1",
            "evidence_refs": [{
                "asset_ref": "native_video_1", "timestamp": "00:11.00", "fact": "同包裹内出现未购商品。",
            }],
        })

        result = aggregate_fulfillment_reconciliation(
            [observed], case(expected_quantity=2), "missing_item"
        )
        guarded = apply_fulfillment_guard(
            {"confidence": 0.88, "fulfillment_reconciliation": result}, "missing_item"
        )

        self.assertEqual(result["verdict"], "indeterminate")
        self.assertEqual(result["scenario_transition"], "wrong_item")
        self.assertEqual(guarded["predicted_label"], "review")
        self.assertIn("错发", result["decision_boundary"])

    def test_insufficient_missing_item_evidence_does_not_switch_to_wrong_item(self):
        observed = row(1, complete=False)
        observed["fulfillment_reconciliation"]["observed_items"].append({
            "sku": "SKU-X",
            "product_name": "身份尚未核准的额外商品",
            "observed_quantity": 1,
            "package_ref": "PKG-1",
            "evidence_refs": [{
                "asset_ref": "supplemental_image_1",
                "timestamp": None,
                "field": "observed_item",
                "fact": "静态图片中出现另一件商品，但尚未形成同包裹开箱链。",
            }],
        })

        result = aggregate_fulfillment_reconciliation(
            [observed], case(expected_quantity=2), "missing_item"
        )

        self.assertEqual(result["evidence_sufficiency"], "insufficient")
        self.assertIsNone(result["scenario_transition"])
        self.assertEqual(result["verdict"], "indeterminate")

    def test_missing_expected_with_only_unexpected_gift_stays_missing_item(self):
        observed = row(1)
        observed["fulfillment_reconciliation"]["observed_items"].append({
            "sku": "GIFT-1",
            "product_name": "活动赠品",
            "item_role": "promotion_gift",
            "observed_quantity": 1,
            "package_ref": "PKG-1",
            "evidence_refs": [{
                "asset_ref": "native_video_1",
                "timestamp": "00:11.00",
                "fact": "同包裹内可见活动赠品。",
            }],
        })

        result = aggregate_fulfillment_reconciliation(
            [observed], case(expected_quantity=2), "missing_item"
        )
        guarded = apply_fulfillment_guard(
            {"confidence": 0.88, "fulfillment_reconciliation": result}, "missing_item"
        )

        self.assertEqual(result["verdict"], "mismatched")
        self.assertIsNone(result["scenario_transition"])
        self.assertEqual(guarded["predicted_label"], "positive")

    def test_wrong_item_single_product_photo_cannot_replace_same_package_chain(self):
        observed = row(0, complete=False)
        observed["fulfillment_reconciliation"]["observed_items"] = [{
            "sku": "SKU-X", "product_name": "未购商品", "observed_quantity": 1, "package_ref": "PKG-1",
            "evidence_refs": [{
                "asset_ref": "supplemental_image_1", "timestamp": None, "fact": "同包裹证据图中可见未购商品。",
            }],
        }]

        result = aggregate_fulfillment_reconciliation(
            [observed], case(expected_quantity=1), "wrong_item"
        )
        guarded = apply_fulfillment_guard(
            {"confidence": 0.88, "fulfillment_reconciliation": result}, "wrong_item"
        )

        self.assertEqual(result["evidence_route"], "insufficient")
        self.assertEqual(result["verdict"], "indeterminate")
        self.assertEqual(result["evidence_sufficiency"], "insufficient")
        self.assertEqual(guarded["predicted_label"], "review")

    def test_wrong_item_static_same_package_chain_waits_for_manual_warehouse_check(self):
        observed = row(0, complete=False)
        observed["fulfillment_reconciliation"]["observed_items"] = [{
            "sku": "SKU-X", "product_name": "未购商品", "observed_quantity": 1,
            "package_ref": "PKG-1",
            "evidence_refs": [{
                "asset_ref": "supplemental_image_1", "timestamp": None,
                "field": "observed_item", "fact": "同包裹全家福中可见未购商品。",
            }],
        }]
        package = observed["fulfillment_reconciliation"]["package_observations"][0]
        package.update({
            "received_group_photo_complete": True,
            "green_bag_visible": True,
            "waybill_visible": True,
            "waybill_matches_order": True,
            "evidence_refs": [
                {
                    "asset_ref": f"supplemental_image_{index}",
                    "timestamp": None,
                    "field": field,
                    "fact": (
                        waybill_observed_identifier_fact("PKG-1")
                        if field == "waybill_observed_identifier"
                        else waybill_match_fact("PKG-1")
                        if field == "waybill_matches_order"
                        else "静态同包裹证据可回看。"
                    ),
                    "observed_identifier": tracking_no("PKG-1") if field == "waybill_observed_identifier" else None,
                }
                for index, field in enumerate((
                    "received_group_photo_complete",
                    "green_bag_visible",
                    "waybill_visible",
                    "waybill_matches_order",
                    "waybill_observed_identifier",
                ), start=1)
            ],
        })

        result = aggregate_fulfillment_reconciliation(
            [observed], case(expected_quantity=1), "wrong_item"
        )
        guarded = apply_fulfillment_guard(
            {"confidence": 0.88, "fulfillment_reconciliation": result}, "wrong_item"
        )

        self.assertEqual(result["evidence_route"], "static_three_images")
        self.assertEqual(result["verdict"], "indeterminate")
        self.assertEqual(result["evidence_sufficiency"], "insufficient")
        self.assertEqual(result["warehouse_check"], {"state": "pending", "outcome": None})
        self.assertEqual(guarded["predicted_label"], "review")
        self.assertEqual(guarded["decision"], "manual_review")

    def test_confirmed_missing_flat_paper_adds_non_blocking_self_check(self):
        current = case(expected_quantity=2)
        expected = current["structured_business_context"]["frontdesk_evidence_package"]["fulfillment_baseline"]["expected_items"][0]
        expected["item_form"] = "flat_paper"

        result = aggregate_fulfillment_reconciliation([row(1)], current, "missing_item")

        self.assertEqual(result["verdict"], "mismatched")
        self.assertEqual(len(result["post_decision_reminders"]), 1)
        reminder = result["post_decision_reminders"][0]
        self.assertEqual(reminder["type"], "flat_paper_self_check")
        self.assertFalse(reminder["affects_verdict"])
        self.assertIn("叠放", reminder["message"])
        self.assertIn("夹层", reminder["message"])

    def test_paper_self_check_never_appears_before_missing_is_confirmed(self):
        current = case(expected_quantity=2)
        expected = current["structured_business_context"]["frontdesk_evidence_package"]["fulfillment_baseline"]["expected_items"][0]
        expected["item_form"] = "flat_paper"
        incomplete = row(1, complete=False)

        result = aggregate_fulfillment_reconciliation([incomplete], current, "missing_item")

        self.assertEqual(result["verdict"], "indeterminate")
        self.assertEqual(result["post_decision_reminders"], [])


if __name__ == "__main__":
    unittest.main()
