import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from poc.visual_review_poc import workbench_server
from review_service.schemas import ReviewCaseMetadata
from review_service import service
from review_service.service import normalize_frame_strategy, postprocess_review


class ReviewPostprocessingParityTest(unittest.TestCase):
    def test_native_video_summary_does_not_describe_evidence_anchors_as_submitted_frames(self) -> None:
        review = {
            "frame_strategy": "2 个视频合并为同一证据包，送审 4 帧，补充图片 10 张。",
            "sampling": {"sampling_mode": "native_video", "fps": 1.0},
            "agent_report": {
                "media_gallery": {
                    "videos": [{"video_index": 1}, {"video_index": 2}],
                    "frames": [{}, {}, {}, {}],
                    "images": [{} for _ in range(10)],
                }
            },
            "media_preflight_execution": {
                "videos": [
                    {"video_index": 1, "preparation_status": "ready"},
                    {"video_index": 2, "preparation_status": "ready"},
                ],
                "images": {"prepared_count": 10},
                "frame_fallback": {"used": False, "frame_count": 0},
            },
        }

        result = normalize_frame_strategy(review)

        self.assertEqual(
            result["frame_strategy"],
            "2 个完整视频按 1 FPS 原生解析送审；报告保留 4 个可回看的视频锚点，另含 10 张补充图片。",
        )
        self.assertNotIn("送审 4 帧", result["frame_strategy"])

    def test_technical_processing_failure_remains_system_retry_after_postprocessing(self) -> None:
        review = {
            "summary": {"review_status": "completed", "predicted_label": "review"},
            "agent_brief": {},
            "agent_report": {
                "parsed": {
                    "predicted_label": "review",
                    "system_yes_no": "REVIEW",
                    "confidence": None,
                    "processing_status": "technical_processing_incomplete",
                    "system_action": "system_retry",
                    "overall_audit": {
                        "conclusion": "本轮媒体处理未完成，不能形成事实判断。",
                    },
                    "evidence_refs": [],
                    "material_gaps": [],
                }
            },
        }

        result = postprocess_review(
            {
                "tenant_id": "mitako",
                "scenario": "product_damage",
                "metadata": {"scenario": "product_damage"},
                "assets": [{"mime_type": "video/mp4"}],
            },
            review,
            readiness={
                "full_review_ready": True,
                "missing_required": [],
                "review_inventory": {"media_counts": {"video": 1, "image": 0}},
            },
            media_forensics={"status": "completed", "summary": {"risk_level": "low"}},
        )

        parsed = result["agent_report"]["parsed"]
        self.assertEqual(parsed["processing_status"], "technical_processing_incomplete")
        self.assertEqual(parsed["system_action"], "system_retry")
        self.assertEqual(
            result["advisory_assessment"]["workflow_recommendation"],
            "system_retry",
        )

    def test_legacy_public_projection_recovers_typed_opening_action_without_fake_score(self) -> None:
        fields = {
            "opening_action": True,
            "sealed_start": True,
            "waybill_visible": True,
            "continuous": True,
            "has_edit": False,
            "has_offscreen": False,
            "all_items_shown": True,
            "issue_visible": True,
        }
        parsed = {
            "predicted_label": "review",
            "confidence": 0.9,
            "sealed_start": True,
            "waybill_visible": True,
            "continuous": True,
            "has_edit": False,
            "has_offscreen": False,
            "all_items_shown": True,
            "issue_visible": True,
            "opening_video_evidence": {
                "present": False,
                "sop_compliant": False,
                "status": "yellow",
                "confidence": 1.0,
                "reason": "未直接观察到首次拆包动作。",
                "evidence_refs": [],
                "validated_requirements": [],
            },
            "video_audit_conclusion": {
                "speed_review_impact": {
                    "status": "uncertain",
                    "critical_evidence_observable": True,
                    "affected_review_items": [],
                },
                "opening_video_compliance": {
                    "opening_action_visible": True,
                    "sealed_start": True,
                    "waybill_visible": True,
                    "single_take_continuity": True,
                    "issue_visible_in_continuous_opening": True,
                    "result": "indeterminate",
                    "evidence_refs": [],
                    "validated_fields": [],
                },
            },
            "damage_causality_assessment": {
                "damage_presence": "confirmed",
                "claim_support": "insufficient",
                "evidence_source_summary": {
                    "primary_video": {
                        "damage_presence": "confirmed",
                        "claim_support": "insufficient",
                        "referenced_count": 0,
                        "evidence_refs": [],
                    },
                },
            },
            "damage_observability": {
                "status": "fully_observable",
                "same_item_linkage": True,
                "conflicting_evidence": False,
            },
            "evidence_refs": [
                {
                    "field": field,
                    "asset_ref": "native_video_1",
                    "timestamp": f"00:0{index}",
                    "fact": f"{field} 的原片事实",
                }
                for index, field in enumerate(fields, start=1)
            ],
        }
        review = {
            "summary": {"predicted_label": "review", "confidence": 0.9},
            "agent_brief": {},
            "agent_report": {"parsed": parsed},
        }

        result = postprocess_review(
            {
                "tenant_id": "mitako",
                "scenario": "product_damage",
                "metadata": {"scenario": "product_damage", "customer_claim": "商品存在划痕"},
                "assets": [{"mime_type": "video/mp4"}],
            },
            review,
            readiness={
                "full_review_ready": True,
                "missing_required": [],
                "review_inventory": {"media_counts": {"video": 1, "image": 0}},
            },
            media_forensics={"status": "completed", "summary": {"risk_level": "low"}},
        )

        normalized = result["agent_report"]["parsed"]
        opening = normalized["opening_video_evidence"]
        self.assertTrue(opening["present"])
        self.assertTrue(opening["sop_compliant"])
        self.assertIsNone(opening["confidence"])
        self.assertEqual(
            set(opening["validated_requirements"]),
            {
                "opening_action",
                "sealed_start",
                "waybill_visible",
                "continuous",
                "claimed_item_presentation",
                "issue_assessable",
            },
        )
        compliance = normalized["video_audit_conclusion"]["opening_video_compliance"]
        self.assertEqual(compliance["result"], "compliant")
        self.assertIn("opening_action_visible", compliance["validated_fields"])
        self.assertEqual(normalized["overall_video_result"], "compliant")
        self.assertEqual(
            normalized["damage_causality_assessment"]["claim_support"],
            "supported",
        )

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
                "material_readiness": {
                    "scenario": "product_damage",
                    "status": "incomplete",
                    "confidence": 0.91,
                    "reason": "缺少可确认初次拆包动作的证据。",
                    "checklist": [{
                        "requirement_id": "opening_action_evidence",
                        "label": "初次拆包动作",
                        "required": True,
                        "status": "missing",
                        "source": "model",
                        "confidence": 0.91,
                        "evidence_refs": [],
                        "reason": "未发现可回看的初次拆包动作。",
                    }],
                    "missing_items": ["初次拆包动作"],
                    "warnings": [],
                },
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
        self.assertEqual(response["material_readiness"], normalized["material_readiness"])
        self.assertEqual(
            response["agent_report"]["parsed"]["material_readiness"],
            normalized["material_readiness"],
        )
        self.assertNotIn("next_step", response["agent_report"]["public_brief"])

    def test_product_damage_negative_requires_true_opening_action_when_no_damage_is_visible(self) -> None:
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

        incomplete_result = postprocess_review(
            {
                "tenant_id": "mitako",
                "scenario": "product_damage",
                "metadata": metadata,
                "assets": [{"mime_type": "video/mp4"}],
            },
            review,
            media_forensics={"status": "not_available", "summary": {"risk_level": "unknown"}},
        )

        self.assertEqual(
            incomplete_result["agent_report"]["parsed"]["predicted_label"],
            "review",
        )

        opening = review["agent_report"]["parsed"]["video_audit_conclusion"]["opening_video_compliance"]
        opening["opening_action_visible"] = True
        opening["validated_fields"].append("opening_action_visible")
        opening["evidence_refs"].append({
            "field": "opening_action_visible",
            "video_index": 1,
            "global_frame_index": 5,
            "timestamp": "00:05.00",
        })
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
        self.assertEqual(parsed["decision"], "human_review")
        self.assertIsNone(parsed["confidence"])
        self.assertIn("order_item_baseline", guard.get("missing_required") or [])
        self.assertEqual(
            response["advisory_assessment"]["workflow_recommendation"],
            "human_review",
        )
        recommendation = response["advisory_assessment"]["human_review"]["recommendation"]
        self.assertIn("甲方订单", recommendation)
        self.assertIn("不要要求用户重复补交", recommendation)

    def test_workbench_requests_under_ten_payment_process_material_without_forcing_human_review(self) -> None:
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
                "predicted_label": "positive",
                "confidence": 0.82,
                "overall_audit": {"conclusion": "五类材料已齐全，继续按材料事实审核。"},
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
