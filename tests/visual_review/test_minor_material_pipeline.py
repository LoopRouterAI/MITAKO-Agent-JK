# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import html
import threading
import time
import unittest
from unittest.mock import patch

from poc.visual_review_poc.minor_material_pipeline import (
    _normalize_consistency_checks,
    aggregate_minor_material_results,
    run_minor_material_pipeline,
)
from poc.visual_review_poc.review_model_prompt import build_selection_prompt
from poc.visual_review_poc.report_assessment_sections import render_minor_material_panel


def _image(index: int) -> dict:
    return {
        "image_index": index,
        "api_path": __file__,
        "api_mime_type": "image/jpeg",
        "width": 1600,
        "height": 1200,
        "has_exif": False,
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


def _consistency_result(check_id: str, status: str = "matched") -> dict:
    fields = {
        "identity_age": ["guardian_identity", "minor_identity", "age_eligibility"],
        "guardian_relationship": ["guardian_identity", "minor_identity", "relationship_link"],
        "commitment_signatures": ["guardian_signer", "minor_signer", "signature_presence"],
        "order_payment": ["order_reference", "payer_identity", "amount", "transaction_scope"],
        "mobile_realname": ["subscriber_identity", "account_mobile", "invoice_identity"],
    }[check_id]
    return {
        "status": "success",
        "parsed": {
            "coverage_ack": {"expected_image_indices": [1, 3], "observed_image_indices": [1, 3]},
            "consistency_check": {
                "check_id": check_id,
                "field_results": [{
                    "field_name": field_name,
                    "status": status,
                    "visibility": "complete",
                    "evidence_image_indices": [1, 3],
                } for field_name in fields],
                "tamper_risk": "low",
                "risk_reason_codes": [],
                "raw_value": "18012345678 320000200801011234",
            }
        },
        "usage": {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
        "cost": {"estimated_usd": 0.002},
        "latency_seconds": 0.2,
    }


class MinorMaterialPipelineTest(unittest.TestCase):
    def test_all_images_are_reviewed_in_batches_and_five_categories_are_present(self) -> None:
        case = _case()
        reviewed_image_indices = []
        consistency_checks = []

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
            elif mode == "minor_material_process_video":
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
            else:
                check_id = batch_case["structured_business_context"]["minor_consistency_check"]["check_id"]
                consistency_checks.append(check_id)
                result = _consistency_result(check_id)
                indices = [item["image_index"] for item in batch_case["supplemental_images"]]
                result["parsed"]["coverage_ack"] = {
                    "expected_image_indices": indices,
                    "observed_image_indices": indices,
                }
                for field in result["parsed"]["consistency_check"]["field_results"]:
                    field["evidence_image_indices"] = indices[:2]
                return result
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
        self.assertEqual(parsed["decision"], "visual_precheck_passed")
        self.assertEqual(parsed["system_yes_no"], "YES")
        self.assertTrue(assessment["coverage_complete"])
        self.assertEqual(assessment["visual_precheck_status"], "passed")
        self.assertEqual(assessment["processed_image_count"], 20)
        self.assertTrue(all(item["status"] == "present" for item in assessment["checklist"]))
        mobile = next(item for item in assessment["checklist"] if item["requirement_id"] == "mobile_realname")
        self.assertEqual(mobile["validation_status"], "visual_consistency_matched")
        self.assertEqual(result["chunking"]["channels"]["minor_material_inventory"]["model_calls"], 5)
        self.assertEqual(
            set(consistency_checks),
            {"identity_age", "guardian_relationship", "commitment_signatures", "order_payment", "mobile_realname"},
        )
        self.assertEqual(assessment["field_consistency"]["status"], "completed")
        self.assertEqual(len(assessment["field_consistency"]["checks"]), 5)
        self.assertEqual(assessment["authoritative_verification"]["status"], "not_configured_optional")
        self.assertEqual(assessment["authenticity_assessment"]["severity"], "warning")
        self.assertFalse(assessment["authenticity_assessment"]["blocks_visual_precheck"])
        self.assertEqual(result["chunking"]["channels"]["minor_field_consistency"]["model_calls"], 5)
        serialized = json.dumps(parsed, ensure_ascii=False)
        self.assertNotIn("18012345678", serialized)
        self.assertNotIn("320000200801011234", serialized)

    def test_explicit_authoritative_required_policy_keeps_minor_case_in_manual_review(self) -> None:
        case = _case(image_count=20, frame_count=0)
        case["structured_business_context"]["minor_refund_policy"] = {
            "authoritative_verification": "required",
            "review_mode": "strict",
        }
        rows = [(
            list(range(1, 21)),
            {"parsed": {"material_observations": [_observation(index) for index in range(1, 21)]}},
        )]
        checks = [
            _consistency_result(check_id)
            for check_id in ("identity_age", "guardian_relationship", "commitment_signatures", "order_payment", "mobile_realname")
        ]

        parsed = aggregate_minor_material_results(
            case, rows, [], [], [], consistency_results=checks, consistency_failures=[]
        )

        self.assertEqual(parsed["predicted_label"], "review")
        self.assertTrue(parsed["human_required"])
        self.assertEqual(parsed["minor_material_assessment"]["visual_precheck_status"], "needs_review")
        self.assertEqual(
            parsed["minor_material_assessment"]["authoritative_verification"]["status"],
            "customer_integration_required",
        )

    def test_single_suspected_editing_signal_is_warning_not_blocking(self) -> None:
        case = _case(image_count=20, frame_count=0)
        observations = [_observation(index) for index in range(1, 21)]
        observations[2]["quality_issues"] = ["suspected_editing"]
        rows = [(list(range(1, 21)), {"parsed": {"material_observations": observations}})]
        checks = [
            _consistency_result(check_id)
            for check_id in ("identity_age", "guardian_relationship", "commitment_signatures", "order_payment", "mobile_realname")
        ]

        parsed = aggregate_minor_material_results(
            case, rows, [], [], [], consistency_results=checks, consistency_failures=[]
        )
        authenticity = parsed["minor_material_assessment"]["authenticity_assessment"]

        self.assertEqual(authenticity["severity"], "warning")
        self.assertFalse(authenticity["blocks_visual_precheck"])
        self.assertIn(3, authenticity["evidence_image_indices"])

    def test_single_page_consistency_evidence_can_match(self) -> None:
        result = _consistency_result("order_payment")
        result["_expected_check_id"] = "order_payment"
        result["_expected_image_indices"] = [1]
        result["_required_image_indices"] = [1]
        result["parsed"]["coverage_ack"] = {
            "expected_image_indices": [1], "observed_image_indices": [1],
        }
        for field in result["parsed"]["consistency_check"]["field_results"]:
            field["evidence_image_indices"] = [1]

        normalized = _normalize_consistency_checks([result], [])

        row = next(item for item in normalized["checks"] if item["check_id"] == "order_payment")
        self.assertEqual(row["status"], "matched")

    def test_minor_pipeline_uses_bounded_dedicated_parallelism(self) -> None:
        case = _case(image_count=24, frame_count=0)
        active = 0
        peak = 0
        lock = threading.Lock()

        def invoke(batch_case: dict) -> dict:
            nonlocal active, peak
            mode = batch_case["structured_business_context"]["analysis_mode"]
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.02)
            with lock:
                active -= 1
            if mode == "minor_material_inventory":
                indices = [item["image_index"] for item in batch_case["supplemental_images"]]
                return {"status": "success", "parsed": {"material_observations": [_observation(i) for i in indices]}}
            check_id = batch_case["structured_business_context"]["minor_consistency_check"]["check_id"]
            result = _consistency_result(check_id)
            indices = [item["image_index"] for item in batch_case["supplemental_images"]]
            result["parsed"]["coverage_ack"] = {
                "expected_image_indices": indices,
                "observed_image_indices": indices,
            }
            for field in result["parsed"]["consistency_check"]["field_results"]:
                field["evidence_image_indices"] = indices[:2]
            return result

        with patch.dict("os.environ", {"REVIEW_MINOR_IMAGE_BATCH_SIZE": "4"}):
            result = run_minor_material_pipeline(case, invoke=invoke, workers=6)

        self.assertGreaterEqual(peak, 6)
        self.assertLessEqual(result["chunking"]["effective_workers"], 8)

    def test_observed_but_partially_readable_material_still_runs_all_consistency_checks(self) -> None:
        case = _case(image_count=20, frame_count=0)
        consistency_checks = []

        def invoke(batch_case: dict) -> dict:
            mode = batch_case["structured_business_context"]["analysis_mode"]
            indices = [item["image_index"] for item in batch_case["supplemental_images"]]
            if mode == "minor_material_inventory":
                observations = [_observation(index) for index in indices]
                for item in observations:
                    if item["image_index"] == 7:
                        item["readability"] = "partial"
                return {
                    "status": "success",
                    "parsed": {
                        "material_observations": observations,
                        "coverage_ack": {
                            "expected_image_indices": indices,
                            "observed_image_indices": indices,
                        },
                    },
                    "usage": {},
                    "cost": {},
                }

            check_id = batch_case["structured_business_context"]["minor_consistency_check"]["check_id"]
            consistency_checks.append(check_id)
            result = _consistency_result(check_id, "uncertain" if check_id == "commitment_signatures" else "matched")
            result["parsed"]["coverage_ack"] = {
                "expected_image_indices": indices,
                "observed_image_indices": indices,
            }
            for field in result["parsed"]["consistency_check"]["field_results"]:
                field["evidence_image_indices"] = indices[:2]
            return result

        result = run_minor_material_pipeline(case, invoke=invoke, workers=4)
        assessment = result["parsed"]["minor_material_assessment"]
        commitment = next(
            item for item in assessment["checklist"] if item["requirement_id"] == "commitment"
        )

        self.assertEqual(commitment["status"], "present")
        self.assertEqual(commitment["quality_status"], "needs_manual_confirmation")
        self.assertEqual(
            set(consistency_checks),
            {"identity_age", "guardian_relationship", "commitment_signatures", "order_payment", "mobile_realname"},
        )
        self.assertEqual(assessment["field_consistency"]["status"], "completed")
        self.assertTrue(all(item["status"] != "not_assessed" for item in assessment["field_consistency"]["checks"]))
        self.assertEqual(result["chunking"]["channels"]["minor_field_consistency"]["model_calls"], 5)

    def test_material_completeness_without_field_consistency_cannot_pass(self) -> None:
        case = _case(image_count=20, frame_count=0)
        rows = [
            (list(range(start, min(start + 4, 21))), {
                "parsed": {"material_observations": [_observation(index) for index in range(start, min(start + 4, 21))]}
            })
            for start in range(1, 21, 4)
        ]

        parsed = aggregate_minor_material_results(case, rows, [], [], [])

        self.assertEqual(parsed["predicted_label"], "review")
        self.assertEqual(parsed["decision"], "manual_consistency_review")
        self.assertEqual(parsed["minor_material_assessment"]["field_consistency"]["status"], "not_completed")
        self.assertIn("字段仍不清楚", parsed["overall_audit"]["conclusion"])

    def test_consistency_mismatch_forces_review_without_exposing_raw_values(self) -> None:
        case = _case(image_count=20, frame_count=0)
        rows = [
            (list(range(start, min(start + 4, 21))), {
                "parsed": {"material_observations": [_observation(index) for index in range(start, min(start + 4, 21))]}
            })
            for start in range(1, 21, 4)
        ]
        checks = [
            _consistency_result(check_id, "mismatched" if check_id == "guardian_relationship" else "matched")
            for check_id in ("identity_age", "guardian_relationship", "commitment_signatures", "order_payment", "mobile_realname")
        ]

        parsed = aggregate_minor_material_results(
            case,
            rows,
            [],
            [],
            [],
            consistency_results=checks,
            consistency_failures=[],
        )

        self.assertEqual(parsed["predicted_label"], "negative")
        self.assertEqual(parsed["minor_material_assessment"]["field_consistency"]["verdict"], "mismatched")
        serialized = json.dumps(parsed, ensure_ascii=False)
        self.assertNotIn("18012345678", serialized)
        self.assertNotIn("320000200801011234", serialized)
        self.assertIn("not_configured_optional", serialized)

    def test_masked_field_cannot_be_promoted_to_explicit_mismatch(self) -> None:
        case = _case(image_count=20, frame_count=0)
        rows = [
            (list(range(start, min(start + 4, 21))), {
                "parsed": {"material_observations": [_observation(index) for index in range(start, min(start + 4, 21))]}
            })
            for start in range(1, 21, 4)
        ]
        checks = [
            _consistency_result(check_id)
            for check_id in ("identity_age", "guardian_relationship", "commitment_signatures", "order_payment", "mobile_realname")
        ]
        mobile = checks[-1]["parsed"]["consistency_check"]
        mobile["field_results"][0].update({"status": "mismatched", "visibility": "masked"})
        mobile["risk_reason_codes"] = ["conflicting_fields"]

        parsed = aggregate_minor_material_results(
            case, rows, [], [], [], consistency_results=checks, consistency_failures=[]
        )
        mobile_check = next(
            item for item in parsed["minor_material_assessment"]["field_consistency"]["checks"]
            if item["check_id"] == "mobile_realname"
        )

        self.assertEqual(mobile_check["status"], "uncertain")
        self.assertEqual(parsed["predicted_label"], "review")

    def test_partial_but_sufficient_visible_fields_can_match(self) -> None:
        case = _case(image_count=20, frame_count=0)
        rows = [
            (list(range(start, min(start + 4, 21))), {
                "parsed": {"material_observations": [_observation(index) for index in range(start, min(start + 4, 21))]}
            })
            for start in range(1, 21, 4)
        ]
        checks = [
            _consistency_result(check_id)
            for check_id in ("identity_age", "guardian_relationship", "commitment_signatures", "order_payment", "mobile_realname")
        ]
        checks[0]["parsed"]["consistency_check"]["field_results"][0]["visibility"] = "partial"

        parsed = aggregate_minor_material_results(
            case, rows, [], [], [], consistency_results=checks, consistency_failures=[]
        )

        self.assertEqual(parsed["minor_material_assessment"]["field_consistency"]["verdict"], "matched")
        self.assertEqual(parsed["predicted_label"], "positive")
        self.assertEqual(parsed["minor_material_assessment"]["visual_precheck_status"], "passed")

    def test_consistency_jobs_cover_all_related_images_and_any_uncertain_segment_downgrades(self) -> None:
        case = _case(image_count=20, frame_count=0)
        consistency_segments = []

        def observation(index: int) -> dict:
            if index <= 8:
                return _observation(index)
            item = _observation(index)
            item.update({
                "document_types": ["carrier_invoice"],
                "subject_role": "guardian",
            })
            return item

        def invoke(batch_case: dict) -> dict:
            mode = batch_case["structured_business_context"]["analysis_mode"]
            indices = [item["image_index"] for item in batch_case["supplemental_images"]]
            if mode == "minor_material_inventory":
                return {
                    "status": "success",
                    "parsed": {
                        "material_observations": [observation(index) for index in indices],
                        "coverage_ack": {
                            "expected_image_indices": indices,
                            "observed_image_indices": indices,
                        },
                    },
                }
            check_id = batch_case["structured_business_context"]["minor_consistency_check"]["check_id"]
            consistency_segments.append((check_id, indices))
            result = _consistency_result(check_id)
            result["parsed"]["coverage_ack"] = {
                "expected_image_indices": indices,
                "observed_image_indices": indices,
            }
            status = "uncertain" if check_id == "mobile_realname" and 20 in indices else "matched"
            for field in result["parsed"]["consistency_check"]["field_results"]:
                field.update({
                    "status": status,
                    "visibility": "partial" if status == "uncertain" else "complete",
                    "evidence_image_indices": indices[:2],
                })
            return result

        with patch.dict("os.environ", {"REVIEW_MINOR_CONSISTENCY_IMAGE_LIMIT": "4"}):
            result = run_minor_material_pipeline(case, invoke=invoke, workers=4)

        mobile_segments = [indices for check_id, indices in consistency_segments if check_id == "mobile_realname"]
        covered = {index for indices in mobile_segments for index in indices}
        self.assertGreater(len(mobile_segments), 1)
        self.assertTrue(set(range(9, 21)).issubset(covered))
        mobile_check = next(
            item for item in result["parsed"]["minor_material_assessment"]["field_consistency"]["checks"]
            if item["check_id"] == "mobile_realname"
        )
        self.assertTrue(set(range(9, 21)).issubset(set(mobile_check["evidence_image_indices"])))
        self.assertEqual(mobile_check["status"], "uncertain")
        self.assertEqual(result["parsed"]["predicted_label"], "review")

    def test_partially_readable_related_image_is_covered_and_blocks_visual_precheck_pass(self) -> None:
        case = _case(image_count=20, frame_count=0)
        consistency_segments = []

        def invoke(batch_case: dict) -> dict:
            mode = batch_case["structured_business_context"]["analysis_mode"]
            indices = [item["image_index"] for item in batch_case["supplemental_images"]]
            if mode == "minor_material_inventory":
                observations = [_observation(index) for index in indices]
                for item in observations:
                    if item["image_index"] == 2:
                        item["readability"] = "partial"
                return {"status": "success", "parsed": {"material_observations": observations}}
            check_id = batch_case["structured_business_context"]["minor_consistency_check"]["check_id"]
            consistency_segments.append((check_id, indices))
            result = _consistency_result(check_id)
            result["parsed"]["coverage_ack"] = {
                "expected_image_indices": indices,
                "observed_image_indices": indices,
            }
            for field in result["parsed"]["consistency_check"]["field_results"]:
                field["evidence_image_indices"] = indices[:2]
            return result

        result = run_minor_material_pipeline(case, invoke=invoke, workers=4)

        related_coverage = {
            index
            for check_id, indices in consistency_segments
            if check_id in {"identity_age", "guardian_relationship", "commitment_signatures"}
            for index in indices
        }
        self.assertIn(2, related_coverage)
        assessment = result["parsed"]["minor_material_assessment"]
        self.assertEqual(assessment["field_consistency"]["verdict"], "uncertain")
        self.assertNotEqual(assessment["visual_precheck_status"], "passed")
        self.assertFalse(result["parsed"]["human_required"])

    def test_uncertain_visible_field_is_advisory_in_default_policy(self) -> None:
        case = _case(image_count=20, frame_count=0)
        rows = [
            (list(range(start, min(start + 4, 21))), {
                "parsed": {"material_observations": [_observation(index) for index in range(start, min(start + 4, 21))]}
            })
            for start in range(1, 21, 4)
        ]
        checks = [_consistency_result(check_id) for check_id in (
            "identity_age", "guardian_relationship", "commitment_signatures", "order_payment", "mobile_realname"
        )]
        checks[-1] = _consistency_result("mobile_realname", "uncertain")

        parsed = aggregate_minor_material_results(
            case, rows, [], [], [], consistency_results=checks, consistency_failures=[]
        )

        self.assertEqual(parsed["predicted_label"], "review")
        self.assertEqual(parsed["decision"], "continue_by_customer_policy")
        self.assertFalse(parsed["human_required"])

    def test_failed_consistency_call_is_included_in_usage_and_cost(self) -> None:
        case = _case(image_count=20, frame_count=0)

        def invoke(batch_case: dict) -> dict:
            mode = batch_case["structured_business_context"]["analysis_mode"]
            indices = [item["image_index"] for item in batch_case["supplemental_images"]]
            if mode == "minor_material_inventory":
                return {
                    "status": "success",
                    "parsed": {"material_observations": [_observation(index) for index in indices]},
                    "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                    "cost": {"estimated_usd": 0.001},
                }
            check_id = batch_case["structured_business_context"]["minor_consistency_check"]["check_id"]
            if check_id == "identity_age":
                return {
                    "status": "failed",
                    "error": "provider_timeout",
                    "usage": {"input_tokens": 17, "output_tokens": 3, "total_tokens": 20},
                    "cost": {"estimated_usd": 0.005},
                }
            result = _consistency_result(check_id)
            if check_id == "guardian_relationship":
                result.update({
                    "cost_status": "partial_unknown",
                    "unknown_cost_calls": 1,
                    "estimated_cost_calls": 1,
                })
            result["parsed"]["coverage_ack"] = {
                "expected_image_indices": indices,
                "observed_image_indices": indices,
            }
            for field in result["parsed"]["consistency_check"]["field_results"]:
                field["evidence_image_indices"] = indices[:2]
            return result

        result = run_minor_material_pipeline(case, invoke=invoke, workers=4)
        channel = result["chunking"]["channels"]["minor_field_consistency"]

        self.assertEqual(channel["model_calls"], 5)
        self.assertEqual(channel["total_tokens"], 140)
        self.assertEqual(channel["estimated_usd"], 0.013)
        self.assertEqual(result["usage"]["total_tokens"], 215)
        self.assertEqual(result["cost"]["estimated_usd"], 0.018)
        self.assertEqual(result["cost_status"], "partial_unknown")
        self.assertEqual(result["unknown_cost_calls"], 1)

    def test_unclassified_image_requests_system_retry_without_user_material_gap(self) -> None:
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
        self.assertEqual(parsed["processing_status"], "technical_processing_incomplete")
        self.assertEqual(parsed["system_action"], "system_retry")
        self.assertIsNone(parsed["confidence"])
        self.assertEqual(parsed["material_gaps"], [])
        self.assertFalse(parsed["human_required"])
        self.assertIn("受控重跑整案", parsed["next_step"])

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
                "cost_status": "partial_unknown" if attempts == 1 else "estimated",
                "unknown_cost_calls": 2 if attempts == 1 else 0,
                "estimated_cost_calls": 1,
                "latency_seconds": 0.1,
            }

        result = run_minor_material_pipeline(case, invoke=invoke, workers=1)

        self.assertEqual(attempts, 2)
        self.assertTrue(result["parsed"]["minor_material_assessment"]["coverage_complete"])
        self.assertEqual(result["chunking"]["channels"]["minor_material_inventory"]["model_calls"], 2)
        self.assertEqual(result["usage"]["total_tokens"], 30)
        self.assertEqual(result["cost"]["estimated_usd"], 0.002)
        self.assertEqual(result["cost_status"], "partial_unknown")
        self.assertEqual(result["unknown_cost_calls"], 2)
        self.assertEqual(result["estimated_cost_calls"], 2)

    def test_default_structural_retry_allows_two_repairs_before_system_retry(self) -> None:
        case = _case(image_count=4, frame_count=0)
        attempts = 0

        def invoke(batch_case: dict) -> dict:
            nonlocal attempts
            attempts += 1
            indices = [item["image_index"] for item in batch_case["supplemental_images"]]
            return {
                "status": "success",
                "parsed": {
                    "material_observations": (
                        [_observation(index) for index in indices] if attempts == 3 else []
                    )
                },
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                "cost": {"estimated_usd": 0.001},
            }

        result = run_minor_material_pipeline(case, invoke=invoke, workers=1)

        self.assertEqual(attempts, 3)
        self.assertTrue(result["parsed"]["minor_material_assessment"]["coverage_complete"])
        self.assertEqual(result["chunking"]["channels"]["minor_material_inventory"]["model_calls"], 3)

    def test_persistent_batch_omission_falls_back_to_single_image_recovery(self) -> None:
        case = _case(image_count=4, frame_count=0)
        batch_attempts = 0
        single_attempts = []

        def invoke(batch_case: dict) -> dict:
            nonlocal batch_attempts
            indices = [item["image_index"] for item in batch_case["supplemental_images"]]
            if len(indices) == 1:
                single_attempts.extend(indices)
                observations = [_observation(indices[0])]
            else:
                batch_attempts += 1
                observations = []
            return {
                "status": "success",
                "parsed": {"material_observations": observations},
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                "cost": {"estimated_usd": 0.001},
            }

        result = run_minor_material_pipeline(case, invoke=invoke, workers=1)

        self.assertEqual(batch_attempts, 3)
        self.assertEqual(single_attempts, [1, 2, 3, 4])
        self.assertTrue(result["parsed"]["minor_material_assessment"]["coverage_complete"])
        self.assertEqual(result["chunking"]["channels"]["minor_material_inventory"]["model_calls"], 7)

    def test_single_image_recovery_reuses_bounded_schema_retries(self) -> None:
        case = _case(image_count=1, frame_count=0)
        batch_attempts = 0
        recovery_attempts = 0

        def invoke(batch_case: dict) -> dict:
            nonlocal batch_attempts, recovery_attempts
            recovery = bool(
                batch_case["structured_business_context"]["minor_material_batch"].get(
                    "single_image_recovery"
                )
            )
            if recovery:
                recovery_attempts += 1
            else:
                batch_attempts += 1
            observations = [_observation(1)] if recovery and recovery_attempts == 2 else []
            return {
                "status": "success",
                "parsed": {"material_observations": observations},
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                "cost": {"estimated_usd": 0.001},
            }

        result = run_minor_material_pipeline(case, invoke=invoke, workers=1)

        self.assertEqual(batch_attempts, 3)
        self.assertEqual(recovery_attempts, 2)
        self.assertTrue(result["parsed"]["minor_material_assessment"]["coverage_complete"])
        self.assertEqual(result["chunking"]["channels"]["minor_material_inventory"]["model_calls"], 5)

    def test_recovery_exception_preserves_prior_usage_and_marks_processing_incomplete(self) -> None:
        case = _case(image_count=1, frame_count=0)
        attempts = 0

        def invoke(batch_case: dict) -> dict:
            nonlocal attempts
            attempts += 1
            if attempts > 1:
                raise RuntimeError("supplier timeout")
            return {
                "status": "success",
                "parsed": {"material_observations": []},
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                "cost": {"estimated_usd": 0.001},
            }

        result = run_minor_material_pipeline(case, invoke=invoke, workers=1)

        assessment = result["parsed"]["minor_material_assessment"]
        self.assertEqual(attempts, 6)
        self.assertEqual(assessment["processing_status"], "technical_processing_incomplete")
        self.assertEqual(result["usage"]["total_tokens"], 15)
        self.assertEqual(result["cost"]["estimated_usd"], 0.001)
        self.assertEqual(result["chunking"]["channels"]["minor_material_inventory"]["model_calls"], 6)

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

    def test_consistency_prompt_compares_fields_but_forbids_raw_pii_output(self) -> None:
        case = _case(image_count=4, frame_count=0)
        case["structured_business_context"].update({
            "analysis_mode": "minor_material_consistency",
            "minor_consistency_check": {
                "check_id": "guardian_relationship",
                "expected_image_indices": [1, 3, 4],
            },
        })
        prompt = build_selection_prompt(case)

        self.assertIn("监护关系", prompt)
        self.assertIn("比较图片中可见字段", prompt)
        self.assertIn("不得输出任何字段原值", prompt)
        self.assertIn("默认 disabled", prompt)
        self.assertNotIn('"authoritative_verification": "customer_integration_required"', prompt)
        self.assertNotIn("expected_predicted_label", prompt)

    def test_report_renders_consistency_matrix_and_authoritative_boundary(self) -> None:
        case = _case(image_count=20, frame_count=0)
        rows = [
            (list(range(start, min(start + 4, 21))), {
                "parsed": {"material_observations": [_observation(index) for index in range(start, min(start + 4, 21))]}
            })
            for start in range(1, 21, 4)
        ]
        checks = [
            _consistency_result(check_id)
            for check_id in ("identity_age", "guardian_relationship", "commitment_signatures", "order_payment", "mobile_realname")
        ]
        parsed = aggregate_minor_material_results(
            case, rows, [], [], [], consistency_results=checks, consistency_failures=[]
        )
        parsed["minor_material_assessment"]["process_evidence"] = [{
            "video_index": 1,
            "global_frame_index": 2,
            "timestamp": "00:08.00",
            "process_type": "invoice_generation",
            "evidence_quality": "clear",
        }]

        panel = render_minor_material_panel(parsed["minor_material_assessment"], lambda value: html.escape(str(value)))

        self.assertIn("视觉字段一致性初审", panel)
        self.assertIn("视觉初审结论", panel)
        self.assertIn("视觉初审通过", panel)
        self.assertIn("身份与年龄", panel)
        self.assertIn("监护关系", panel)
        self.assertIn("订单与支付", panel)
        self.assertIn("材料质量", panel)
        self.assertIn("在线验真默认关闭", panel)
        self.assertIn('href="#image-', panel)
        self.assertIn("图片真实性风险", panel)
        self.assertIn("发票或凭证生成过程", panel)
        self.assertIn("画面清晰", panel)
        self.assertNotIn("invoice_generation", panel)
        self.assertTrue(all(
            "matched" not in item["description"]
            for item in parsed["supporting_evidence"]
        ))
        self.assertIn("字段一致性未发现明显矛盾", parsed["overall_audit"]["core_reason"])
        self.assertNotIn("18012345678", panel)
        self.assertNotIn("320000200801011234", panel)


if __name__ == "__main__":
    unittest.main()
