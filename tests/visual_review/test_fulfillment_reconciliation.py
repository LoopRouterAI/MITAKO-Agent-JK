from __future__ import annotations

import unittest

from poc.visual_review_poc.fulfillment_reconciliation import (
    aggregate_fulfillment_reconciliation,
    apply_fulfillment_guard,
)


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

    def test_incomplete_visual_coverage_forces_review(self):
        result = aggregate_fulfillment_reconciliation([row(1, complete=False)], case(), "missing_item")
        guarded = apply_fulfillment_guard({"confidence": 0.91, "fulfillment_reconciliation": result}, "missing_item")
        self.assertEqual(result["evidence_sufficiency"], "insufficient")
        self.assertEqual(result["confidence"], 0.0)
        self.assertEqual(result["observation_confidence"], 0.88)
        self.assertEqual(guarded["predicted_label"], "review")
        self.assertLessEqual(guarded["confidence"], 0.69)

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


if __name__ == "__main__":
    unittest.main()
