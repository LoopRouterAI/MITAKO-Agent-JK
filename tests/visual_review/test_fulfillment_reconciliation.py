from __future__ import annotations

import unittest

from poc.visual_review_poc.fulfillment_reconciliation import (
    aggregate_fulfillment_reconciliation,
    apply_fulfillment_guard,
)
from poc.visual_review_poc.local_video_triage_demo import scenario_rules


def case(expected_quantity: int = 2, packages=None, coverage=None):
    packages = packages or [{"package_ref": "PKG-1", "expected_item_refs": ["LINE-1"]}]
    coverage = coverage or {
        "submitted_package_refs": [item["package_ref"] for item in packages],
        "all_packages_uploaded": True,
        "all_items_displayed": True,
    }
    return {
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


def row(quantity: int, package_ref: str = "PKG-1", complete: bool = True):
    return {
        "fulfillment_reconciliation": {
            "observed_items": [
                {"sku": "SKU-1", "product_name": "徽章", "observed_quantity": quantity, "package_ref": package_ref}
            ],
            "unconfirmed_items": [],
            "package_observations": [
                {
                    "package_ref": package_ref,
                    "opening_complete": complete,
                    "all_contents_laid_out": complete,
                    "evidence_timestamps": ["00:10.00"],
                }
            ],
            "confidence": 0.88,
        }
    }


class FulfillmentReconciliationTest(unittest.TestCase):
    def test_missing_item_prompt_does_not_use_ticket_suffix_as_review_gate(self):
        prompt = scenario_rules("missing_item")

        self.assertNotIn("_1 尾号", prompt)
        self.assertNotIn("二次处理单必须转人工", prompt)

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

    def test_traceable_warehouse_confirmation_overrides_pending_visual_coverage(self):
        current = case()
        baseline = current["structured_business_context"]["frontdesk_evidence_package"]["fulfillment_baseline"]
        baseline["warehouse_verification"] = {
            "status": "confirmed_not_missing",
            "source": "customer_warehouse",
            "verification_ref": "WH-CHECK-1",
        }

        result = aggregate_fulfillment_reconciliation([row(1, complete=False)], current, "missing_item")
        guarded = apply_fulfillment_guard({"confidence": 0.91, "fulfillment_reconciliation": result}, "missing_item")

        self.assertEqual(result["verdict"], "matched")
        self.assertEqual(result["evidence_sufficiency"], "sufficient")
        self.assertEqual(result["resolution_basis"], "warehouse_verification")
        self.assertEqual(result["warehouse_verification"]["status"], "confirmed_not_missing")
        self.assertEqual(guarded["predicted_label"], "negative")
        self.assertIn("仓库终核", guarded["fulfillment_guard_reason"])

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

    def test_traceable_warehouse_missing_confirmation_is_positive(self):
        current = case(expected_quantity=1)
        baseline = current["structured_business_context"]["frontdesk_evidence_package"]["fulfillment_baseline"]
        baseline["warehouse_verification"] = {
            "status": "confirmed_missing",
            "source": "customer_warehouse",
            "verification_ref": "WH-CHECK-3",
        }

        result = aggregate_fulfillment_reconciliation([row(1)], current, "missing_item")
        guarded = apply_fulfillment_guard({"confidence": 0.91, "fulfillment_reconciliation": result}, "missing_item")

        self.assertEqual(result["verdict"], "mismatched")
        self.assertEqual(guarded["predicted_label"], "positive")

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

    def test_complete_flags_without_submitted_package_refs_force_review(self):
        result = aggregate_fulfillment_reconciliation(
            [row(1)],
            case(coverage={"all_packages_uploaded": True, "all_items_displayed": True}),
            "missing_item",
        )
        self.assertEqual(result["verdict"], "indeterminate")
        self.assertFalse(result["submitted_package_mapping_complete"])

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

    def test_wrong_item_requires_missing_expected_and_unexpected_received(self):
        result = aggregate_fulfillment_reconciliation([row(1)], case(expected_quantity=2), "wrong_item")
        guarded = apply_fulfillment_guard({"confidence": 0.88, "fulfillment_reconciliation": result}, "wrong_item")

        self.assertEqual(result["verdict"], "matched")
        self.assertEqual(guarded["predicted_label"], "negative")

    def test_missing_item_ignores_extra_item_when_expected_quantity_is_complete(self):
        observed = row(2)
        observed["fulfillment_reconciliation"]["observed_items"].append({
            "sku": "SKU-X", "product_name": "额外赠品", "observed_quantity": 1, "package_ref": "PKG-1"
        })

        result = aggregate_fulfillment_reconciliation([observed], case(), "missing_item")
        guarded = apply_fulfillment_guard({"confidence": 0.88, "fulfillment_reconciliation": result}, "missing_item")

        self.assertEqual(result["verdict"], "matched")
        self.assertEqual(guarded["predicted_label"], "negative")

    def test_missing_expected_and_unexpected_received_does_not_confirm_missing_item(self):
        observed = row(1)
        observed["fulfillment_reconciliation"]["observed_items"].append({
            "sku": "SKU-X", "product_name": "未购商品", "observed_quantity": 1, "package_ref": "PKG-1"
        })

        result = aggregate_fulfillment_reconciliation(
            [observed], case(expected_quantity=2), "missing_item"
        )
        guarded = apply_fulfillment_guard(
            {"confidence": 0.88, "fulfillment_reconciliation": result}, "missing_item"
        )

        self.assertEqual(result["verdict"], "indeterminate")
        self.assertEqual(guarded["predicted_label"], "review")
        self.assertIn("错发", result["decision_boundary"])

    def test_wrong_item_can_use_complete_photo_chain_without_opening_video(self):
        observed = row(0, complete=False)
        observed["fulfillment_reconciliation"]["observed_items"] = [{
            "sku": "SKU-X", "product_name": "未购商品", "observed_quantity": 1, "package_ref": "PKG-1"
        }]

        result = aggregate_fulfillment_reconciliation(
            [observed], case(expected_quantity=1), "wrong_item"
        )
        guarded = apply_fulfillment_guard(
            {"confidence": 0.88, "fulfillment_reconciliation": result}, "wrong_item"
        )

        self.assertEqual(result["verdict"], "mismatched")
        self.assertEqual(result["evidence_sufficiency"], "sufficient")
        self.assertEqual(guarded["predicted_label"], "positive")


if __name__ == "__main__":
    unittest.main()
