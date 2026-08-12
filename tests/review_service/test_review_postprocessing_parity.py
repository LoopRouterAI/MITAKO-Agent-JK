import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from poc.visual_review_poc import workbench_server
from review_service.schemas import ReviewCaseMetadata
from review_service import service
from review_service.service import postprocess_review


class ReviewPostprocessingParityTest(unittest.TestCase):
    def test_formal_api_requests_raw_workbench_result_for_single_postprocess(self) -> None:
        fields = service._review_fields({
            "job_id": "RJ-RAW",
            "client_case_id": "CASE-RAW",
            "scenario": "product_damage",
            "metadata": {"output_options": {"include_html_report": True}},
            "assets": [],
        })

        self.assertEqual(fields["defer_postprocess"], "true")
        self.assertEqual(fields["include_html_report"], "false")

    def test_internal_workbench_options_require_shared_service_token(self) -> None:
        with patch.dict("os.environ", {"VISUAL_REPORT_SIGNING_SECRET": "test-shared-token"}):
            self.assertFalse(workbench_server._internal_request_authorized(""))
            self.assertFalse(workbench_server._internal_request_authorized("forged"))
            self.assertTrue(workbench_server._internal_request_authorized("test-shared-token"))

    def test_deferred_workbench_result_does_not_apply_policy_before_formal_api(self) -> None:
        case = {
            "case_id": "CASE-DEFER",
            "scenario": "product_damage",
            "scenario_label": "商品有伤审核",
            "customer_claim": "商品存在折痕",
            "videos": [],
            "frames": [],
            "supplemental_images": [],
            "structured_business_context": {"business_scenario": "product_damage"},
        }
        model_result = {
            "status": "success",
            "parsed": {
                "predicted_label": "review",
                "confidence": 0.91,
                "overall_audit": {"conclusion": "模型原始结论"},
            },
        }

        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            workbench_server, "score_result", return_value={}
        ), patch.object(workbench_server, "postprocess_review") as postprocess:
            response = workbench_server._agent_report_response(
                case,
                Path(temp_dir),
                model_result,
                "deferred",
                include_html_report=False,
                defer_postprocess=True,
            )

        postprocess.assert_not_called()
        self.assertEqual(response["agent_report"]["parsed"]["predicted_label"], "review")
        self.assertNotIn("advisory_assessment", response)

    def test_direct_workbench_runs_media_forensics_once_before_shared_postprocess(self) -> None:
        case = {
            "case_id": "CASE-FORENSICS",
            "scenario": "product_damage",
            "scenario_label": "商品有伤审核",
            "customer_claim": "商品存在折痕",
            "videos": [{"video_index": 1, "file": "evidence.mp4"}],
            "frames": [],
            "supplemental_images": [],
            "structured_business_context": {"business_scenario": "product_damage"},
        }
        model_result = {
            "status": "success",
            "parsed": {
                "predicted_label": "review",
                "confidence": 0.72,
                "overall_audit": {"conclusion": "模型原始结论"},
            },
        }
        forensics = {"status": "completed", "summary": {"risk_level": "low"}, "assets": []}

        with tempfile.TemporaryDirectory() as temp_dir:
            sample_dir = Path(temp_dir)
            (sample_dir / "evidence.mp4").write_bytes(b"video")
            normalized = {
                "summary": {"review_status": "completed", "predicted_label": "review", "confidence": 0.72},
                "agent_report": {"parsed": model_result["parsed"]},
                "advisory_assessment": {},
                "agent_brief": {"conclusion": "模型原始结论"},
            }
            with patch.object(workbench_server, "score_result", return_value={}), patch.object(
                workbench_server, "inspect_job_media", return_value=forensics
            ) as inspect, patch.object(
                workbench_server, "postprocess_review", return_value=normalized
            ) as postprocess:
                response = workbench_server._agent_report_response(
                    case,
                    sample_dir,
                    model_result,
                    "forensics",
                    include_html_report=False,
                )

        inspect.assert_called_once()
        inspected_assets = inspect.call_args.args[1]
        self.assertEqual(inspected_assets[0]["stored_name"], "evidence.mp4")
        self.assertEqual(postprocess.call_args.kwargs["media_forensics"], forensics)
        self.assertEqual(response["media_forensics"], forensics)

    def test_product_damage_default_can_recommend_negative_when_full_evidence_sees_no_damage(self) -> None:
        metadata = ReviewCaseMetadata(
            client_case_id="CASE-NO-DAMAGE",
            scenario="product_damage",
            customer_claim="商品正面存在折痕",
            claim_scope={
                "split_status": "single_legacy",
                "claim_text": "商品正面存在折痕",
                "issue_types": ["visible_damage"],
            },
        ).model_dump(mode="json")
        review = {
            "summary": {"predicted_label": "review", "confidence": 0.91},
            "agent_brief": {},
            "agent_report": {"parsed": {
                "predicted_label": "review",
                "confidence": 0.91,
                "pass_integrity_status": "complete",
                "video_audit_conclusion": {
                    "opening_integrity": "complete",
                    "opening_integrity_source": "full_timeline_continuity",
                    "sampling_boundary_status": "covered",
                    "opening_video_compliance": {
                        "sealed_start": True,
                        "waybill_visible": True,
                        "single_take_continuity": True,
                        "issue_visible_in_continuous_opening": False,
                        "result": "noncompliant",
                        "source": "native_video_perception",
                        "validated_fields": [
                            "sealed_start",
                            "waybill_visible",
                            "single_take_continuity",
                            "issue_visible_in_continuous_opening",
                        ],
                        "evidence_refs": [
                            {
                                "field": field,
                                "video_index": 1,
                                "global_frame_index": index,
                                "timestamp": f"00:0{index}.00",
                            }
                            for index, field in enumerate(
                                (
                                    "sealed_start",
                                    "waybill_visible",
                                    "single_take_continuity",
                                    "issue_visible_in_continuous_opening",
                                ),
                                start=1,
                            )
                        ],
                    },
                },
                "object_continuity_assessment": {
                    "continuity_verdict": "continuous",
                    "tracked_subjects": [{
                        "subject_id": "claimed_item",
                        "visibility_coverage": 0.9,
                        "longest_out_of_frame_seconds": 2.0,
                    }],
                },
                "damage_causality_assessment": {
                    "damage_presence": "not_visible",
                    "claim_support": "not_supported",
                    "evidence_source_summary": {
                        "supplemental_images": {
                            "provided_count": 0,
                            "referenced_count": 0,
                            "linkage_status": "not_provided",
                        },
                    },
                },
                "damage_observability": {
                    "status": "fully_observable",
                    "same_item_linkage": True,
                    "claimed_region_closeup": True,
                    "required_view_coverage": 0.85,
                    "conflicting_evidence": False,
                },
            }},
        }

        result = postprocess_review(
            {
                "tenant_id": "mitako",
                "scenario": "product_damage",
                "metadata": metadata,
                "assets": [{"mime_type": "video/mp4"}],
            },
            review,
            media_forensics={"status": "not_available", "summary": {"risk_level": "unknown"}},
        )

        parsed = result["agent_report"]["parsed"]
        self.assertEqual(metadata["decision_policy"]["mode"], "classification_recommendation")
        self.assertEqual(parsed["predicted_label"], "negative")
        self.assertFalse(parsed["human_required"])
        self.assertTrue(parsed["human_required_for_business_action"])

    def test_workbench_applies_same_input_readiness_guard_as_formal_api(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            sample_dir = Path(temp_dir)
            case = {
                "case_id": "CASE-WRONG-ITEM-NO-BASELINE",
                "scenario": "video_unboxing",
                "scenario_label": "发错货审核",
                "customer_claim": "收到的商品款式与订单不一致",
                "videos": [],
                "frames": [],
                "supplemental_images": [],
                "structured_business_context": {
                    "business_scenario": "wrong_item",
                    "frontdesk_evidence_package": {},
                },
            }
            model_result = {
                "status": "success",
                "parsed": {
                    "predicted_label": "positive",
                    "system_yes_no": "YES",
                    "confidence": 0.96,
                    "overall_audit": {"conclusion": "视觉上疑似发错货"},
                },
            }

            with patch.object(workbench_server, "score_result", return_value={}):
                response = workbench_server._agent_report_response(
                    case,
                    sample_dir,
                    model_result,
                    "parity",
                    include_html_report=False,
                )

        parsed = response["agent_report"]["parsed"]
        guard = parsed.get("input_readiness_guard") or {}
        self.assertTrue(guard.get("applied"), parsed)
        self.assertEqual(parsed["predicted_label"], "review")
        self.assertEqual(parsed["decision"], "request_more_material")
        self.assertLessEqual(parsed["confidence"], 0.69)
        self.assertIn("order_item_baseline", guard.get("missing_required") or [])
        self.assertEqual(
            response["advisory_assessment"]["workflow_recommendation"],
            "request_more_material",
        )

    def test_workbench_preserves_minor_required_materials_and_payment_risk_before_postprocess(self) -> None:
        case = {
            "case_id": "CASE-MINOR-RISK",
            "scenario": "minor_material",
            "scenario_label": "未成年人资料审核",
            "customer_claim": "监护人申请未成年人退款",
            "videos": [],
            "frames": [],
            "supplemental_images": [],
            "structured_business_context": {
                "business_scenario": "minor_refund",
                "minor_refund_policy": {"authoritative_verification": "disabled"},
            },
        }
        model_result = {
            "status": "success",
            "parsed": {
                "predicted_label": "review",
                "confidence": 0.82,
                "overall_audit": {"conclusion": "低龄支付过程需要重点核验。"},
                "minor_material_assessment": {
                    "declared_image_count": 5,
                    "accepted_image_count": 5,
                    "processed_image_count": 5,
                    "required_materials": ["请补充说明未成年人如何获得或得知支付密码。"],
                    "payment_capability_risk": {
                        "level": "high",
                        "effect": "需补充支付过程说明，不自动决定退款。",
                        "evidence_image_indices": [1],
                        "low_age": True,
                        "process_evidence_status": "missing",
                        "requires_review": False,
                        "requires_more_material": True,
                    },
                },
            },
        }

        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            workbench_server, "score_result", return_value={}
        ):
            response = workbench_server._agent_report_response(
                case,
                Path(temp_dir),
                model_result,
                "minor-risk",
                include_html_report=False,
            )

        advisory = response["advisory_assessment"]
        self.assertEqual(advisory["human_review"]["level"], "not_required")
        self.assertEqual(advisory["workflow_recommendation"], "request_more_material")
        self.assertEqual(advisory["evidence_attention"]["level"], "orange")
        self.assertIn(
            "请补充说明未成年人如何获得或得知支付密码。",
            advisory["evidence_attention"]["missing_evidence"],
        )

    def test_failed_review_is_not_reclassified_by_business_policy(self) -> None:
        metadata = ReviewCaseMetadata(
            client_case_id="CASE-SERVICE-FAILURE",
            scenario="product_damage",
            customer_claim="商品存在划痕",
        ).model_dump(mode="json")
        review = {
            "summary": {"review_status": "failed", "predicted_label": "review"},
            "agent_brief": {"conclusion": "审核未完成，系统复核服务繁忙。"},
            "agent_report": {"parsed": {"predicted_label": "review"}},
            "diagnostics": {"failure_stage": "系统复核"},
        }

        result = postprocess_review(
            {
                "tenant_id": "mitako",
                "scenario": "product_damage",
                "metadata": metadata,
                "assets": [{"mime_type": "image/jpeg"}],
            },
            review,
            succeeded=False,
        )

        self.assertEqual(result["summary"]["predicted_label"], "review")
        self.assertNotIn("decision_policy_audit", result)
        self.assertNotIn("input_readiness_guard", result)
        self.assertIn("审核未完成", result["agent_brief"]["conclusion"])
        self.assertIn(
            "review_service_failure",
            result["advisory_assessment"]["human_review"]["reason_codes"],
        )


if __name__ == "__main__":
    unittest.main()
