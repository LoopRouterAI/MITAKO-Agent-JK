# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import unittest

from poc.visual_review_poc.minor_material_pipeline import (
    aggregate_minor_material_results,
    run_minor_material_pipeline,
)
from poc.visual_review_poc.review_model_prompt import build_selection_prompt


def _image(index: int) -> dict:
    return {
        "image_index": index,
        "api_path": __file__,
        "api_mime_type": "image/jpeg",
        "width": 1600,
        "height": 1200,
    }


def _frame(index: int) -> dict:
    return {
        "video_index": 1,
        "global_frame_index": index,
        "timestamp": f"00:{index:02d}.00",
        "api_path": __file__,
        "api_mime_type": "image/jpeg",
    }


def _case(image_count: int = 20, frame_count: int = 3) -> dict:
    return {
        "case_id": "blind-case",
        "scenario": "minor_material",
        "scenario_label": "未成年人退款资料审核",
        "customer_claim": "申请退款",
        "order_context": {},
        "evidence_assets": [
            {"file": f"asset_{index:03d}.jpg", "status": "downloaded"}
            for index in range(1, image_count + 1)
        ],
        "structured_business_context": {"business_scenario": "minor_refund"},
        "supplemental_images": [_image(index) for index in range(1, image_count + 1)],
        "frames": [_frame(index) for index in range(1, frame_count + 1)],
        "videos": [{"video_index": 1, "duration_seconds": 3}],
        "model_frames_per_call": 24,
    }


def _observation(index: int) -> dict:
    mapping = {
        1: ("identity_card", "guardian", "front"),
        2: ("identity_card", "guardian", "back"),
        3: ("identity_card", "minor", "front"),
        4: ("identity_card", "minor", "back"),
        5: ("household_register", "not_applicable", "page"),
        7: ("signed_commitment", "not_applicable", "page"),
        8: ("order_payment_proof", "not_applicable", "page"),
        16: ("carrier_invoice", "guardian", "page"),
        18: ("birth_certificate", "not_applicable", "page"),
    }
    document_type, role, side = mapping.get(index, ("other", "not_applicable", "page"))
    return {
        "image_index": index,
        "asset_ref": f"supplemental_image_{index}",
        "document_types": [document_type],
        "subject_role": role,
        "document_side": side,
        "readability": "clear",
        "quality_issues": [],
        "ocr_text": "不应进入聚合结果的个人信息 18012345678 320000200801011234",
    }


class MinorMaterialPipelineTest(unittest.TestCase):
    def test_all_images_are_reviewed_in_batches_and_five_categories_are_present(self) -> None:
        case = _case()
        reviewed_image_indices = []

        def invoke(batch_case: dict) -> dict:
            mode = batch_case["structured_business_context"]["analysis_mode"]
            if mode == "minor_material_inventory":
                indices = [item["image_index"] for item in batch_case["supplemental_images"]]
                reviewed_image_indices.extend(indices)
                parsed = {
                    "material_observations": [_observation(index) for index in indices],
                    "coverage_ack": {
                        "expected_image_indices": indices,
                        "observed_image_indices": indices,
                    },
                }
            else:
                frame = batch_case["frames"][0]
                parsed = {
                    "process_observations": [{
                        "video_index": frame["video_index"],
                        "global_frame_index": frame["global_frame_index"],
                        "timestamp": frame["timestamp"],
                        "asset_ref": "video_1_frame_1",
                        "process_type": "invoice_generation",
                        "evidence_quality": "clear",
                    }]
                }
            return {
                "status": "success",
                "parsed": parsed,
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                "cost": {"estimated_usd": 0.001},
                "latency_seconds": 0.1,
            }

        result = run_minor_material_pipeline(case, invoke=invoke, workers=4)
        parsed = result["parsed"]
        assessment = parsed["minor_material_assessment"]

        self.assertEqual(sorted(reviewed_image_indices), list(range(1, 21)))
        self.assertEqual(parsed["predicted_label"], "positive")
        self.assertEqual(parsed["decision"], "pass")
        self.assertTrue(assessment["coverage_complete"])
        self.assertEqual(assessment["processed_image_count"], 20)
        self.assertTrue(all(item["status"] == "present" for item in assessment["checklist"]))
        mobile = next(item for item in assessment["checklist"] if item["requirement_id"] == "mobile_realname")
        self.assertEqual(mobile["validation_status"], "needs_manual_consistency_check")
        self.assertEqual(result["chunking"]["channels"]["minor_material_inventory"]["model_calls"], 5)
        serialized = json.dumps(parsed, ensure_ascii=False)
        self.assertNotIn("18012345678", serialized)
        self.assertNotIn("320000200801011234", serialized)

    def test_unclassified_image_blocks_missing_material_claim(self) -> None:
        case = _case(image_count=5, frame_count=0)
        rows = [
            (
                [1, 2, 3, 4, 5],
                {
                    "parsed": {"material_observations": [_observation(index) for index in range(1, 5)]},
                },
            )
        ]
        parsed = aggregate_minor_material_results(case, rows, [], [], [])
        assessment = parsed["minor_material_assessment"]

        self.assertFalse(assessment["coverage_complete"])
        self.assertEqual(assessment["unclassified_image_indices"], [5])
        self.assertEqual(parsed["predicted_label"], "review")
        self.assertIn("缺件结论已被门禁阻断", parsed["material_gaps"][0])
        self.assertNotIn("用户未提交", "".join(parsed["material_gaps"]))

    def test_structural_retry_recovers_omitted_image_indices_and_counts_cost(self) -> None:
        case = _case(image_count=4, frame_count=0)
        attempts = 0

        def invoke(batch_case: dict) -> dict:
            nonlocal attempts
            attempts += 1
            indices = [item["image_index"] for item in batch_case["supplemental_images"]]
            observations = [] if attempts == 1 else [_observation(index) for index in indices]
            return {
                "status": "success",
                "parsed": {"material_observations": observations},
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                "cost": {"estimated_usd": 0.001},
                "latency_seconds": 0.1,
            }

        result = run_minor_material_pipeline(case, invoke=invoke, workers=1)

        self.assertEqual(attempts, 2)
        self.assertTrue(result["parsed"]["minor_material_assessment"]["coverage_complete"])
        self.assertEqual(result["chunking"]["channels"]["minor_material_inventory"]["model_calls"], 2)
        self.assertEqual(result["usage"]["total_tokens"], 30)
        self.assertEqual(result["cost"]["estimated_usd"], 0.002)

    def test_household_register_or_birth_certificate_satisfies_relationship_rule(self) -> None:
        case = _case(image_count=8, frame_count=0)
        rows = [([1, 2, 3, 4, 5, 6, 7, 8], {"parsed": {"material_observations": [_observation(index) for index in range(1, 9)]}})]
        parsed = aggregate_minor_material_results(case, rows, [], [], [])
        relationship = next(
            item for item in parsed["minor_material_assessment"]["checklist"]
            if item["requirement_id"] == "relationship"
        )

        self.assertEqual(relationship["status"], "present")
        self.assertIn("二选一", relationship["rule_note"])

    def test_declared_images_exceeding_accepted_images_blocks_full_coverage(self) -> None:
        case = _case(image_count=4, frame_count=0)
        case["structured_business_context"]["frontdesk_evidence_package"] = {
            "asset_manifest": {
                "assets": [
                    {"mime_type": "image/jpeg"} for _ in range(5)
                ]
            }
        }
        rows = [([1, 2, 3, 4], {"parsed": {"material_observations": [_observation(index) for index in range(1, 5)]}})]
        parsed = aggregate_minor_material_results(case, rows, [], [], [])
        assessment = parsed["minor_material_assessment"]

        self.assertFalse(assessment["ingestion_complete"])
        self.assertFalse(assessment["coverage_complete"])
        self.assertEqual(assessment["coverage_ratio"], 0.8)

    def test_inventory_prompt_forbids_pii_and_does_not_include_evaluation_labels(self) -> None:
        case = _case(image_count=2, frame_count=0)
        case["customer_claim"] = "contact 18012345678 identity 320000200801011234"
        case["structured_business_context"].update({
            "analysis_mode": "minor_material_inventory",
            "minor_material_batch": {
                "index": 1,
                "total": 1,
                "expected_image_indices": [1, 2],
                "global_image_count": 2,
            },
        })
        prompt = build_selection_prompt(case)

        self.assertIn("必须逐张返回", prompt)
        self.assertIn("户口本相关页或出生证明二选一", prompt)
        self.assertIn("不得输出姓名、手机号、证件号", prompt)
        self.assertNotIn("18012345678", prompt)
        self.assertNotIn("320000200801011234", prompt)
        self.assertNotIn("expected_predicted_label", prompt)
        self.assertNotIn("人工认可", prompt)


if __name__ == "__main__":
    unittest.main()
