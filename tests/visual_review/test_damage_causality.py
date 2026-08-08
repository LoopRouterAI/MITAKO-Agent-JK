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
    def test_evidence_guard_does_not_rewrite_case_classification(self):
        result = apply_damage_causality_guard(
            {
                "predicted_label": "review",
                "system_yes_no": "REVIEW",
                "confidence": 0.95,
                "damage_causality_assessment": assessment(claim_support="supported"),
            },
            "product_damage",
        )
        self.assertEqual(result["predicted_label"], "review")
        self.assertEqual(result["system_yes_no"], "REVIEW")
        self.assertEqual(result["confidence"], 0.95)
        self.assertEqual(result["damage_evidence_tendency"], "supports_claim")
        self.assertIn("证据层", result["causality_guard_reason"])

    def test_visible_damage_without_resolved_origin_stays_supporting_evidence(self):
        result = apply_damage_causality_guard(
            {"predicted_label": "positive", "confidence": 0.95, "damage_causality_assessment": assessment()},
            "product_damage",
        )
        self.assertEqual(result["predicted_label"], "positive")
        self.assertEqual(result["damage_evidence_tendency"], "supports_claim")
        self.assertIn("版本化 SOP", result["causality_guard_reason"])

    def test_linked_supplemental_image_does_not_overwrite_main_video_damage_presence(self):
        result = apply_damage_causality_guard(
            {
                "predicted_label": "review",
                "confidence": 0.72,
                "damage_causality_assessment": assessment(damage_presence="uncertain"),
                "adopted_evidence": [
                    {
                        "source_type": "supplemental_image",
                        "fact": "争议部位存在清晰可见的外观瑕疵。",
                        "damage_visible": True,
                        "confidence": 0.9,
                        "same_item_linkage": "same_item",
                        "temporal_linkage": "post_opening",
                    }
                ],
            },
            "product_damage",
        )

        resolved = result["damage_causality_assessment"]
        self.assertEqual(resolved["damage_presence"], "uncertain")
        self.assertEqual(resolved["supplemental_damage_presence"], "confirmed")
        self.assertEqual(result["predicted_label"], "review")

    def test_linked_supplemental_image_without_visible_damage_is_not_confirmed(self):
        result = apply_damage_causality_guard(
            {
                "predicted_label": "review",
                "confidence": 0.72,
                "damage_causality_assessment": assessment(damage_presence="uncertain"),
                "adopted_evidence": [
                    {
                        "source_type": "supplemental_image",
                        "fact": "争议部位未见清晰损伤。",
                        "damage_visible": False,
                        "confidence": 0.95,
                        "same_item_linkage": "same_item",
                        "temporal_linkage": "post_opening",
                    }
                ],
            },
            "product_damage",
        )

        self.assertNotIn("supplemental_damage_presence", result["damage_causality_assessment"])

    def test_uncertain_damage_keeps_evidence_score_for_later_sop_policy(self):
        result = apply_damage_causality_guard(
            {
                "predicted_label": "review",
                "confidence": 0.93,
                "damage_causality_assessment": assessment(damage_presence="not_visible", claim_support="not_supported"),
            },
            "product_damage",
        )

        self.assertEqual(result["predicted_label"], "review")
        self.assertEqual(result["confidence"], 0.93)

    def test_transport_direct_preopening_chain_supports_claim_without_rewriting_case(self):
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
        self.assertNotIn("predicted_label", result)
        self.assertEqual(result["damage_evidence_tendency"], "supports_claim")
        self.assertEqual(result["confidence"], 0.92)

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
        self.assertEqual(without_change["damage_evidence_tendency"], "supports_claim")
        self.assertEqual(with_change["damage_evidence_tendency"], "does_not_support_claim")
        self.assertNotIn("predicted_label", with_change)

    def test_customer_damage_without_structured_frame_chain_keeps_visible_fact_support(self):
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
        self.assertEqual(result["damage_evidence_tendency"], "supports_claim")
        self.assertNotIn("predicted_label", result)

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
        self.assertNotIn("ORDER-1", prompt)
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

    def test_aggregate_cannot_confirm_main_video_damage_without_a_replayable_frame(self):
        combined = aggregate_damage_causality([
            {
                "damage_causality_assessment": assessment(
                    damage_presence="confirmed",
                    claim_support="insufficient",
                    first_visible_evidence="none",
                    damage_type_and_location="补充图片可见折痕",
                )
            }
        ])

        self.assertEqual(combined["damage_presence"], "uncertain")
        self.assertEqual(combined["claim_support"], "insufficient")
        self.assertIn("可回链", combined["cannot_conclude_reason"])

    def test_aggregate_rejects_negated_damage_frame_as_visible_damage(self):
        combined = aggregate_damage_causality([
            {
                "damage_causality_assessment": assessment(
                    damage_presence="confirmed",
                    claim_support="insufficient",
                    first_visible_evidence={
                        "video_index": 1,
                        "global_frame_index": 60,
                        "timestamp": "03:55.63",
                        "damage_visible": False,
                        "fact": "视频未拍摄到明信片表面的损伤，无法识别用户所诉划痕。",
                    },
                )
            }
        ])

        self.assertEqual(combined["damage_presence"], "uncertain")
        self.assertIsNone(combined.get("first_visible_evidence"))

    def test_aggregate_rejects_uncertain_whether_damage_exists(self):
        combined = aggregate_damage_causality([
            {
                "damage_causality_assessment": assessment(
                    damage_presence="confirmed",
                    first_visible_evidence={
                        "video_index": 2,
                        "global_frame_index": 158,
                        "timestamp": "00:37.70",
                        "subject": "扭蛋公仔",
                        "location": "本体",
                        "fact": "取出商品后，受限于视频画质无法直接肉眼确认是否存在划痕或瑕疵。",
                    },
                )
            }
        ])

        self.assertEqual(combined["damage_presence"], "uncertain")
        self.assertIsNone(combined.get("first_visible_evidence"))

    def test_aggregate_requires_same_item_linkage_for_visible_damage(self):
        combined = aggregate_damage_causality([
            {
                "damage_causality_assessment": assessment(
                    damage_presence="confirmed",
                    claim_support="supported",
                    first_visible_evidence={
                        "video_index": 1,
                        "global_frame_index": 167,
                        "timestamp": "02:45.76",
                        "subject": "争议商品",
                        "location": "争议部位",
                        "damage_visible": True,
                        "fact": "该帧直接可见损伤。",
                    },
                ),
                "damage_observability": {"same_item_linkage": False},
            }
        ])

        self.assertEqual(combined["damage_presence"], "uncertain")
        self.assertIsNone(combined.get("first_visible_evidence"))

    def test_aggregate_accepts_structured_visible_damage_for_linked_item(self):
        combined = aggregate_damage_causality([
            {
                "damage_causality_assessment": assessment(
                    damage_presence="confirmed",
                    claim_support="supported",
                    first_visible_evidence={
                        "video_index": 1,
                        "global_frame_index": 20,
                        "timestamp": "00:19.00",
                        "subject": "争议商品",
                        "location": "争议部位",
                        "damage_visible": True,
                        "fact": "该帧直接可见损伤。",
                    },
                ),
                "damage_observability": {"same_item_linkage": True},
            }
        ])

        self.assertEqual(combined["damage_presence"], "confirmed")

    def test_aggregate_keeps_only_the_strongest_hypothesis_per_origin(self):
        rows = [
            {
                "damage_causality_assessment": assessment(
                    possible_origins=[
                        {"origin": "indeterminate", "confidence": 0.3, "supporting_evidence": "weak"},
                        {"origin": "logistics_transport", "confidence": 0.4, "supporting_evidence": "box"},
                    ]
                )
            },
            {
                "damage_causality_assessment": assessment(
                    possible_origins=[
                        {"origin": "indeterminate", "confidence": 0.8, "supporting_evidence": "strong"},
                    ]
                )
            },
        ]

        combined = aggregate_damage_causality(rows)

        self.assertEqual(len(combined["possible_origins"]), 2)
        hypotheses = {item["origin"]: item for item in combined["possible_origins"]}
        self.assertEqual(hypotheses["indeterminate"]["supporting_evidence"], "strong")
        self.assertEqual(hypotheses["logistics_transport"]["supporting_evidence"], "box")

    def test_uncovered_chunk_does_not_override_a_concrete_origin_hypothesis(self):
        rows = [
            {
                "damage_causality_assessment": assessment(
                    most_likely_origin="indeterminate",
                    origin_confidence=1.0,
                    causal_evidence_level="insufficient",
                )
            },
            {
                "damage_causality_assessment": assessment(
                    most_likely_origin="manufacturing_or_original_packaging",
                    origin_confidence=0.7,
                    causal_evidence_level="indirect",
                )
            },
        ]

        combined = aggregate_damage_causality(rows)

        self.assertEqual(combined["most_likely_origin"], "manufacturing_or_original_packaging")
        self.assertEqual(combined["origin_confidence"], 0.7)
        self.assertEqual(combined["causal_evidence_level"], "indirect")

    def test_supplemental_only_damage_does_not_promote_indirect_origin(self):
        rows = [
            {
                "damage_causality_assessment": assessment(
                    damage_presence="uncertain",
                    damage_timing="post_opening_only",
                    most_likely_origin="customer_opening_or_handling",
                    origin_confidence=0.8,
                    causal_evidence_level="indirect",
                ),
            },
            {
                "adopted_evidence": [{
                    "source_type": "supplementary_image",
                    "image_index": 1,
                    "fact": "同一商品的争议部位可见断裂。",
                    "damage_visible": True,
                    "confidence": 0.94,
                    "same_item_linkage": "same_item",
                    "temporal_linkage": "post_opening",
                }],
            },
        ]

        combined = aggregate_damage_causality(rows)

        self.assertEqual(combined["damage_presence"], "confirmed")
        self.assertEqual(combined["damage_timing"], "unknown")
        self.assertEqual(combined["most_likely_origin"], "indeterminate")
        self.assertEqual(combined["origin_confidence"], 0.0)
        self.assertEqual(combined["causal_evidence_level"], "insufficient")

    def test_special_product_risk_is_aggregated_conservatively_across_segments(self):
        rows = [
            {"damage_causality_assessment": assessment(
                origin_confidence=0.2,
                appearance_difference="visible",
                business_defect_qualification="indeterminate",
                special_product_rule="required_but_not_quantified",
            )},
            {"damage_causality_assessment": assessment(
                origin_confidence=0.9,
                appearance_difference="not_visible",
                business_defect_qualification="confirmed",
                special_product_rule="not_required",
            )},
        ]

        combined = aggregate_damage_causality(rows)

        self.assertEqual(combined["appearance_difference"], "visible")
        self.assertEqual(combined["business_defect_qualification"], "indeterminate")
        self.assertEqual(combined["special_product_rule"], "required_but_not_quantified")


if __name__ == "__main__":
    unittest.main()
