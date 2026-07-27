# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest

from poc.visual_review_poc.damage_causality import (
    aggregate_damage_causality,
    apply_damage_causality_guard,
)
from poc.visual_review_poc.model_selection_e2e import build_selection_prompt


def assessment(**overrides):
    value = {
        "damage_presence": "confirmed",
        "damage_timing": "unknown",
        "pre_opening_state_visible": False,
        "opening_action_visible": False,
        "damage_change_observed": False,
        "most_likely_origin": "indeterminate",
        "origin_confidence": 0.8,
        "causal_evidence_level": "insufficient",
        "claim_support": "insufficient",
        "before_action_evidence": [],
        "action_evidence": [],
        "after_action_evidence": [],
    }
    value.update(overrides)
    return value


def action_chain():
    common = {"video_index": 1, "subject": "撕拉片", "location": "右上角", "chain_id": "chain-1"}
    return {
        "before_action_evidence": [{**common, "global_frame_index": 10, "timestamp": "00:09.00", "fact": "动作前完整"}],
        "action_evidence": [{**common, "global_frame_index": 11, "timestamp": "00:10.00", "fact": "用户撕拉"}],
        "after_action_evidence": [{**common, "global_frame_index": 12, "timestamp": "00:11.00", "fact": "动作后断裂"}],
    }


class DamageCausalityTest(unittest.TestCase):
    def test_visible_damage_supports_fact_even_when_origin_is_unresolved(self):
        result = apply_damage_causality_guard(
            {
                "predicted_label": "positive",
                "confidence": 0.95,
                "damage_causality_assessment": assessment(claim_support="supported"),
            },
            "product_damage",
        )
        self.assertEqual(result["predicted_label"], "positive")
        self.assertEqual(result["system_yes_no"], "YES")
        self.assertEqual(result["confidence"], 0.95)
        self.assertIn("伤情事实", result["causality_guard_reason"])

    def test_visible_damage_without_resolved_origin_stays_positive(self):
        result = apply_damage_causality_guard(
            {"predicted_label": "positive", "confidence": 0.95, "damage_causality_assessment": assessment()},
            "product_damage",
        )
        self.assertEqual(result["predicted_label"], "positive")
        self.assertIn("责任归属", result["causality_guard_reason"])

    def test_linked_high_confidence_supplemental_image_confirms_visible_damage(self):
        result = apply_damage_causality_guard(
            {
                "predicted_label": "review",
                "confidence": 0.72,
                "damage_causality_assessment": assessment(damage_presence="uncertain"),
                "adopted_evidence": [
                    {
                        "source_type": "supplemental_image",
                        "fact": "争议部位存在清晰可见的外观瑕疵。",
                        "confidence": 0.9,
                        "same_item_linkage": "与开箱视频中的同款商品一致",
                    }
                ],
            },
            "product_damage",
        )

        self.assertEqual(result["damage_causality_assessment"]["damage_presence"], "confirmed")
        self.assertEqual(result["predicted_label"], "positive")

    def test_transport_is_only_positive_with_direct_preopening_evidence(self):
        result = apply_damage_causality_guard(
            {
                "confidence": 0.92,
                "damage_causality_assessment": assessment(
                    damage_timing="pre_opening_visible",
                    pre_opening_state_visible=True,
                    most_likely_origin="logistics_transport",
                    causal_evidence_level="direct",
                    claim_support="supported",
                    origin_confidence=0.87,
                    first_visible_evidence={"video_index": 1, "global_frame_index": 2, "timestamp": "00:01.00"},
                ),
            },
            "product_damage",
        )
        self.assertEqual(result["predicted_label"], "positive")
        self.assertEqual(result["confidence"], 0.87)

    def test_customer_damage_requires_visible_action_and_observed_change(self):
        base = assessment(
            damage_timing="appears_during_opening",
            most_likely_origin="customer_opening_or_handling",
            causal_evidence_level="direct",
            claim_support="not_supported",
            origin_confidence=0.91,
        )
        without_change = apply_damage_causality_guard(
            {"confidence": 0.95, "damage_causality_assessment": base},
            "product_damage",
        )
        with_change = apply_damage_causality_guard(
            {
                "confidence": 0.95,
                "damage_causality_assessment": {
                    **base,
                    "opening_action_visible": True,
                    "damage_change_observed": True,
                    **action_chain(),
                },
            },
            "product_damage",
        )
        self.assertEqual(without_change["predicted_label"], "positive")
        self.assertEqual(with_change["predicted_label"], "negative")

    def test_customer_damage_without_structured_frame_chain_keeps_visible_fact_positive(self):
        result = apply_damage_causality_guard(
            {
                "confidence": 0.95,
                "damage_causality_assessment": assessment(
                    damage_timing="appears_during_opening",
                    most_likely_origin="customer_opening_or_handling",
                    causal_evidence_level="direct",
                    claim_support="not_supported",
                    opening_action_visible=True,
                    damage_change_observed=True,
                ),
            },
            "product_damage",
        )
        self.assertEqual(result["predicted_label"], "positive")

    def test_conflicting_direct_chunk_origins_are_not_forced(self):
        rows = [
            {"damage_causality_assessment": assessment(most_likely_origin="logistics_transport", causal_evidence_level="direct")},
            {"damage_causality_assessment": assessment(most_likely_origin="customer_opening_or_handling", causal_evidence_level="direct")},
        ]
        combined = aggregate_damage_causality(rows)
        self.assertEqual(combined["most_likely_origin"], "indeterminate")
        self.assertEqual(combined["causal_evidence_level"], "insufficient")

    def test_prompt_requests_causal_fields_without_evaluation_labels(self):
        prompt = build_selection_prompt(
            {
                "scenario_label": "商品有伤审核",
                "customer_claim": "商品到手有伤",
                "order_context": {},
                "structured_business_context": {},
                "evidence_assets": [],
                "videos": [],
                "frames": [],
                "supplemental_images": [],
            }
        )
        self.assertIn("damage_causality_assessment", prompt)
        self.assertIn("customer_opening_or_handling", prompt)
        self.assertNotIn("人工拒绝", prompt)
        self.assertNotIn("负样本", prompt)

    def test_prompt_sanitizes_nested_human_annotation(self):
        prompt = build_selection_prompt(
            {
                "scenario_label": "商品有伤审核",
                "customer_claim": "商品到手有伤",
                "order_context": {},
                "structured_business_context": {
                    "source_case": {
                        "annotation": {"正/负样本": "负样本", "具体问题": "人工拒绝"},
                        "order_no": "ORDER-1",
                    }
                },
                "evidence_assets": [],
                "videos": [],
                "frames": [],
                "supplemental_images": [],
            }
        )
        self.assertIn("ORDER-1", prompt)
        self.assertNotIn("负样本", prompt)
        self.assertNotIn("人工拒绝", prompt)

    def test_aggregate_does_not_join_direct_chain_across_segments(self):
        rows = [
            {
                "damage_causality_assessment": {
                    "damage_presence": "confirmed",
                    "damage_timing": "pre_opening_visible",
                    "pre_opening_state_visible": True,
                    "opening_action_visible": False,
                    "damage_change_observed": False,
                    "most_likely_origin": "customer_opening_or_handling",
                    "origin_confidence": 0.9,
                    "causal_evidence_level": "direct",
                    "claim_support": "not_supported",
                    "alternative_explanations": "另一种解释",
                }
            },
            {
                "damage_causality_assessment": {
                    "damage_presence": "confirmed",
                    "damage_timing": "unknown",
                    "pre_opening_state_visible": False,
                    "opening_action_visible": True,
                    "damage_change_observed": True,
                    "most_likely_origin": "indeterminate",
                    "origin_confidence": 0.4,
                    "causal_evidence_level": "insufficient",
                    "claim_support": "insufficient",
                }
            },
        ]
        combined = aggregate_damage_causality(rows)
        self.assertEqual(combined["causal_evidence_level"], "indirect")
        self.assertFalse(combined["opening_action_visible"])
        self.assertFalse(combined["damage_change_observed"])
        self.assertEqual(combined["alternative_explanations"], ["另一种解释"])


if __name__ == "__main__":
    unittest.main()
