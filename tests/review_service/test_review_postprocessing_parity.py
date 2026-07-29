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


if __name__ == "__main__":
    unittest.main()
