# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest

from pydantic import ValidationError

from review_service.advisory_assessment import attach_advisory_assessment, html_report_requested
from review_service.schemas import ReviewAdvisoryAssessment, ReviewCaseMetadata
from review_service.service import _apply_input_readiness_guard


def review_result(
    label: str = "positive",
    confidence: float = 0.9,
    *,
    continuity: dict | None = None,
    parsed_extra: dict | None = None,
) -> dict:
    parsed = {
        "predicted_label": label,
        "confidence": confidence,
        "overall_audit": {"conclusion": "当前视觉证据支持用户所述事实。"},
    }
    if continuity is not None:
        parsed["object_continuity_assessment"] = continuity
    parsed.update(parsed_extra or {})
    return {
        "summary": {"predicted_label": label, "confidence": confidence},
        "agent_brief": {"conclusion": "当前视觉证据支持用户所述事实。"},
        "agent_report": {"parsed": parsed},
    }


class AdvisoryAssessmentTest(unittest.TestCase):
    def test_missing_item_trusted_system_gap_routes_to_internal_query_not_customer_resubmission(self):
        review = review_result(label="review", confidence=0.69, parsed_extra={
            "fulfillment_reconciliation": {
                "evidence_route": "insufficient",
                "evidence_sufficiency": "insufficient",
                "verdict": "indeterminate",
                "warehouse_check": {"state": "not_available", "outcome": None},
            },
        })
        review["material_readiness"] = {
            "scenario": "missing_item",
            "status": "incomplete",
            "confidence": 0.0,
            "reason": "仍缺少甲方系统侧的分包与签收事实。",
            "checklist": [
                {
                    "requirement_id": "missing_item_user_evidence_route",
                    "label": "合规开箱视频或静态三类材料路径",
                    "required": True,
                    "status": "invalid",
                    "source": "model",
                    "confidence": 0.0,
                    "evidence_refs": [],
                    "reason": "用户证据尚未形成完整路线。",
                },
                {
                    "requirement_id": "all_expected_packages_delivered",
                    "label": "全部应到包裹已有可核验签收状态",
                    "required": True,
                    "status": "missing",
                    "source": "trusted_system",
                    "confidence": 1.0,
                    "evidence_refs": [],
                    "reason": "甲方物流快照尚未覆盖全部应发包裹。",
                },
            ],
            "missing_items": [
                "合规开箱视频或静态三类材料路径",
                "全部应到包裹已有可核验签收状态",
            ],
            "warnings": [],
        }

        result = attach_advisory_assessment(
            review,
            {"scenario": "missing_item"},
            readiness={"full_review_ready": True, "missing_required": []},
        )

        advisory = result["advisory_assessment"]
        self.assertEqual(advisory["workflow_recommendation"], "human_review")
        self.assertEqual(advisory["human_review"]["level"], "required")
        self.assertIn("trusted_system_data_required", advisory["human_review"]["reason_codes"])
        self.assertIn("物流", advisory["human_review"]["recommendation"])
        self.assertIn("甲方内部", advisory["assessment"]["conclusion"])
        self.assertNotIn("补充所列材料", advisory["assessment"]["conclusion"])
        self.assertIn("仓库", result["agent_brief"]["next_step"])
        self.assertNotIn("用户补充", result["agent_brief"]["next_step"])

    def test_missing_item_visual_shortage_does_not_stay_positive_without_delivery_snapshot(self):
        review = review_result(label="positive", confidence=1.0, parsed_extra={
            "fulfillment_reconciliation": {
                "evidence_route": "compliant_opening_video",
                "evidence_sufficiency": "sufficient",
                "verdict": "mismatched",
                "resolution_basis": "visual_reconciliation",
                "warehouse_check": {"state": "not_available", "outcome": None},
            },
        })
        review["material_readiness"] = {
            "scenario": "missing_item",
            "status": "complete",
            "confidence": 1.0,
            "reason": "用户开箱证据已完成视觉对账。",
            "checklist": [
                {
                    "requirement_id": "all_expected_packages_delivered",
                    "label": "全部应到包裹已有可核验签收状态",
                    "required": False,
                    "status": "missing",
                    "source": "trusted_system",
                    "confidence": 1.0,
                    "evidence_refs": [],
                    "reason": "甲方物流快照尚未覆盖全部应发包裹。",
                },
            ],
            "missing_items": [],
            "warnings": [],
        }

        result = attach_advisory_assessment(
            review,
            {"scenario": "missing_item"},
            readiness={"full_review_ready": True, "missing_required": []},
        )

        parsed = result["agent_report"]["parsed"]
        advisory = result["advisory_assessment"]
        self.assertEqual(parsed["predicted_label"], "review")
        self.assertEqual(parsed["system_yes_no"], "REVIEW")
        self.assertEqual(result["summary"]["predicted_label"], "review")
        self.assertEqual(result["summary"]["system_yes_no"], "REVIEW")
        self.assertEqual(result["agent_brief"]["system_yes_no"], "REVIEW")
        self.assertIsNone(parsed["confidence"])
        self.assertIsNone(result["summary"]["confidence"])
        self.assertIsNone(advisory["assessment"]["confidence"])
        self.assertEqual(advisory["assessment"]["confidence_level"], "unavailable")
        self.assertEqual(advisory["assessment"]["conclusion_code"], "evidence_inconclusive")
        self.assertEqual(advisory["sop_recommendation"]["code"], "further_assessment")
        self.assertIn("暂不形成漏发", advisory["assessment"]["conclusion"])

    def test_missing_item_static_material_route_requires_warehouse_detail_review(self):
        review = review_result(label="review", confidence=0.68, parsed_extra={
            "fulfillment_reconciliation": {
                "evidence_route": "static_three_images",
                "warehouse_check": {"state": "pending", "outcome": None},
                "user_materials_complete": True,
                "evidence_sufficiency": "insufficient",
                "verdict": "indeterminate",
                "decision_boundary": "用户静态三类材料已齐全，下一步应读取仓库实发明细。",
            },
        })

        result = attach_advisory_assessment(
            review,
            {"scenario": "missing_item"},
            readiness={"full_review_ready": True, "missing_required": []},
        )

        advisory = result["advisory_assessment"]
        self.assertEqual(advisory["workflow_recommendation"], "human_review")
        self.assertEqual(advisory["human_review"]["level"], "required")
        self.assertIn(
            "warehouse_fulfillment_detail_required",
            advisory["human_review"]["reason_codes"],
        )
        self.assertIn("仓库实发明细", advisory["human_review"]["recommendation"])
        self.assertIn("仓库实发明细", result["agent_brief"]["next_step"])
        self.assertNotIn("不要求逐单人工", advisory["human_review"]["recommendation"])

    def test_wrong_item_static_material_route_requires_warehouse_detail_review(self):
        review = review_result(label="review", confidence=0.68, parsed_extra={
            "fulfillment_reconciliation": {
                "evidence_route": "static_three_images",
                "warehouse_check": {"state": "pending", "outcome": None},
                "user_materials_complete": True,
                "evidence_sufficiency": "insufficient",
                "verdict": "indeterminate",
            },
        })

        result = attach_advisory_assessment(
            review,
            {"scenario": "wrong_item"},
            readiness={"full_review_ready": True, "missing_required": []},
        )

        advisory = result["advisory_assessment"]
        self.assertEqual(advisory["workflow_recommendation"], "human_review")
        self.assertEqual(advisory["human_review"]["level"], "required")
        self.assertIn("warehouse_fulfillment_detail_required", advisory["human_review"]["reason_codes"])
        self.assertIn("仓库实发明细", advisory["human_review"]["recommendation"])
        self.assertIn("发错", advisory["assessment"]["conclusion"])

    def test_trusted_warehouse_conclusion_replaces_the_earlier_visual_brief(self):
        review = review_result(label="negative", confidence=1.0, parsed_extra={
            "overall_audit": {
                "conclusion": "甲方可追溯仓库终核确认实收商品与应发商品一致，本案确定未漏发。",
                "confidence": 1.0,
            },
            "fulfillment_reconciliation": {
                "resolution_basis": "warehouse_verification",
                "warehouse_verification": {
                    "status": "confirmed_not_missing",
                    "source": "customer_warehouse",
                    "verification_ref": "WH-CHECK-1",
                },
            },
        })

        result = attach_advisory_assessment(review, {"scenario": "missing_item"})

        self.assertIn("确定未漏发", result["advisory_assessment"]["assessment"]["conclusion"])
        self.assertIn("确定未漏发", result["agent_brief"]["conclusion"])
        focus = "。".join(result["advisory_assessment"]["evidence_attention"]["customer_focus"])
        self.assertIn("仓库终核", focus)
        self.assertNotIn("补证", focus)
        self.assertNotIn("视频覆盖不全", focus)
        self.assertEqual(result["agent_report"]["parsed"]["predicted_label"], "negative")
        self.assertEqual(result["agent_report"]["parsed"]["system_yes_no"], "NO")

    def test_four_scenarios_expose_customer_evidence_attention(self):
        scenarios = (
            (
                "product_damage",
                review_result(label="positive", confidence=0.91, parsed_extra={
                    "damage_causality_assessment": {"damage_presence": "confirmed"},
                }),
                "green",
                "主视频",
            ),
            (
                "wrong_item",
                review_result(label="review", confidence=0.72, parsed_extra={
                    "material_gaps": ["缺少订单 SKU 与规格基准。"],
                }),
                "orange",
                "订单 SKU",
            ),
            (
                "missing_item",
                review_result(label="review", confidence=0.71, parsed_extra={
                    "material_gaps": ["缺少包裹与 SKU 的对应关系。"],
                }),
                "orange",
                "应发清单",
            ),
            (
                "minor_refund",
                review_result(label="negative", confidence=0.86, parsed_extra={
                    "evidence_conflicts": ["监护关系材料中的申请人角色与出生证明不一致。"],
                    "minor_material_assessment": {"required_materials": ["补充合法监护关系证明。"]},
                }),
                "red",
                "五类材料",
            ),
        )

        for scenario, review, level, focus_text in scenarios:
            with self.subTest(scenario=scenario):
                result = attach_advisory_assessment(
                    review,
                    {"scenario": scenario},
                    readiness={"full_review_ready": True, "missing_required": []},
                )
                attention = result["advisory_assessment"]["evidence_attention"]
                self.assertEqual(attention["level"], level)
                self.assertTrue(attention["headline"])
                self.assertIn(focus_text, "；".join(attention["customer_focus"]))
                self.assertIsInstance(attention["disagreements"], list)
                self.assertIsInstance(attention["missing_evidence"], list)

    def test_fragmented_material_gap_text_is_not_shown_as_user_request(self):
        result = attach_advisory_assessment(
            {
                "summary": {"predicted_label": "review", "confidence": 0.74},
                "agent_report": {
                    "parsed": {
                        "predicted_label": "review",
                        "confidence": 0.74,
                        "material_gaps": ["缺", "少", "视"],
                    }
                },
            },
            {"scenario": "product_damage"},
        )

        parsed = result["agent_report"]["parsed"]
        self.assertEqual(parsed["material_gaps"], [])
        self.assertFalse(any(
            signal["code"] == "material_gap"
            for signal in result["advisory_assessment"]["signals"]
        ))

    def test_high_confidence_complete_evidence_does_not_require_human_review(self):
        result = attach_advisory_assessment(
            review_result(),
            {"scenario": "product_damage"},
            readiness={"full_review_ready": True, "missing_required": []},
        )

        advisory = result["advisory_assessment"]
        self.assertEqual(advisory["human_review"]["level"], "not_required")
        self.assertEqual(advisory["workflow_recommendation"], "continue_by_customer_policy")
        self.assertFalse(advisory["policy"]["business_action_allowed"])
        self.assertIn("是否需要人工复核由单独的复核等级决定", advisory["policy"]["boundary"])
        self.assertEqual(advisory["assessment"]["calibration_status"], "uncalibrated_evidence_score")
        self.assertEqual(advisory["sop_recommendation"]["code"], "support_claim")
        self.assertNotIn("next_step", result["agent_brief"])

    def test_negative_evidence_never_invents_compensation_action(self):
        result = attach_advisory_assessment(
            review_result(
                label="negative",
                confidence=0.82,
                parsed_extra={
                    "decision_policy_audit": {
                        "rule_id": "PD-N-NONCOMPLIANT-OPENING-VIDEO",
                        "reason": "开箱视频不合规，当前证据不支持用户诉求。",
                        "supplemental_evidence_note": "补充图片只能证明后态损伤，不能替代开箱时态。",
                    }
                },
            ),
            {"scenario": "product_damage"},
            readiness={"full_review_ready": True, "missing_required": []},
        )

        advisory = result["advisory_assessment"]
        self.assertEqual(advisory["assessment"]["conclusion_code"], "evidence_does_not_support_claim")
        self.assertEqual(advisory["sop_recommendation"]["code"], "not_support_claim")
        self.assertNotIn("补偿", advisory["sop_recommendation"]["recommendation"])
        self.assertFalse(advisory["policy"]["business_action_allowed"])
        ReviewAdvisoryAssessment.model_validate(advisory)

    def test_minor_sop_basis_ignores_product_damage_policy_placeholder(self):
        result = attach_advisory_assessment(
            review_result(
                label="negative",
                confidence=0.84,
                parsed_extra={
                    "overall_audit": {"conclusion": "申请人与监护关系字段存在明确冲突。"},
                    "minor_material_assessment": {"decision": "negative"},
                    "decision_policy_audit": {
                        "applied": False,
                        "reason": "未启用商品有伤规则分类建议。",
                    },
                },
            ),
            {"scenario": "minor_refund"},
            readiness={"full_review_ready": True, "missing_required": []},
        )

        advisory = result["advisory_assessment"]
        self.assertNotIn("商品有伤", advisory["sop_recommendation"]["basis"])
        self.assertEqual(
            advisory["sop_recommendation"]["basis"],
            advisory["assessment"]["conclusion"],
        )

    def test_complete_minor_materials_do_not_emit_noop_manual_review_copy(self):
        review = review_result(
            label="positive",
            confidence=0.92,
            parsed_extra={
                "minor_material_assessment": {
                    "processing_status": "completed",
                    "coverage_complete": True,
                },
                "material_readiness": {
                    "scenario": "minor_refund",
                    "status": "complete",
                    "confidence": 0.92,
                },
                "next_step": "旧逻辑要求进入人工审核。",
            },
        )
        review["material_readiness"] = {
            "scenario": "minor_refund",
            "status": "complete",
            "confidence": 0.92,
        }
        review["agent_brief"]["next_step"] = "旧逻辑要求进入人工审核。"
        review["agent_report"]["public_brief"] = {
            "next_step": "旧逻辑要求进入人工审核。",
        }

        result = attach_advisory_assessment(
            review,
            {"scenario": "minor_refund"},
            readiness={"full_review_ready": True, "missing_required": []},
        )

        self.assertEqual(result["advisory_assessment"]["human_review"]["level"], "not_required")
        self.assertEqual(result["advisory_assessment"]["human_review"]["recommendation"], "")
        self.assertNotIn("next_step", result["agent_brief"])
        self.assertNotIn("next_step", result["agent_report"]["parsed"])
        self.assertNotIn("next_step", result["agent_report"]["public_brief"])
        self.assertNotIn("材料已齐全", result["agent_brief"]["conclusion"])

    def test_unapplied_policy_reason_cannot_contradict_final_recommendation(self):
        result = attach_advisory_assessment(
            review_result(
                label="positive",
                confidence=0.91,
                parsed_extra={
                    "decision_policy_audit": {
                        "applied": False,
                        "reason": "主视频条件不足，保持人工复核。",
                    },
                },
            ),
            {"scenario": "product_damage"},
            readiness={"full_review_ready": True, "missing_required": []},
        )

        advisory = result["advisory_assessment"]
        self.assertEqual(advisory["sop_recommendation"]["code"], "support_claim")
        self.assertEqual(
            advisory["sop_recommendation"]["basis"],
            advisory["assessment"]["conclusion"],
        )

    def test_legacy_advisory_without_sop_recommendation_remains_readable(self):
        advisory = attach_advisory_assessment(
            review_result(),
            {"scenario": "product_damage"},
            readiness={"full_review_ready": True, "missing_required": []},
        )["advisory_assessment"]
        advisory.pop("sop_recommendation")

        parsed = ReviewAdvisoryAssessment.model_validate(advisory)
        self.assertIsNone(parsed.sop_recommendation)

    def test_short_out_of_frame_is_optional_signal_not_mandatory_review(self):
        result = attach_advisory_assessment(
            review_result(
                continuity={
                    "continuity_verdict": "brief_occlusion",
                    "longest_out_of_frame_seconds": 1.4,
                    "tracked_subjects": [{
                        "subject_id": "claimed_item",
                        "out_of_frame_events": [{
                            "duration_seconds": 1.4,
                            "within_required_display_window": True,
                            "identity_reestablished": True,
                        }],
                    }],
                }
            ),
            {"scenario": "product_damage"},
            readiness={"full_review_ready": True, "missing_required": []},
        )

        advisory = result["advisory_assessment"]
        self.assertEqual(advisory["human_review"]["level"], "optional")
        self.assertEqual(advisory["workflow_recommendation"], "continue_by_customer_policy")
        self.assertIn("offscreen_review_signal", [item["code"] for item in advisory["signals"]])
        self.assertIn("不要求每单", result["agent_brief"]["next_step"])
        self.assertNotIn("VIP客服复核", result["agent_brief"]["next_step"])
        self.assertIn("建议按风险偏好抽检", advisory["evidence_attention"]["headline"])
        self.assertNotIn("需先处理", advisory["evidence_attention"]["headline"])

    def test_confirmed_fact_with_unresolved_continuity_is_optional_not_forced_review(self):
        result = attach_advisory_assessment(
            review_result(
                label="positive",
                confidence=0.91,
                parsed_extra={
                    "object_continuity_assessment": {"continuity_verdict": "indeterminate"},
                    "continuity_recommendation": "continue_with_warning",
                },
            ),
            {"scenario": "product_damage"},
            readiness={"full_review_ready": True, "missing_required": []},
        )

        advisory = result["advisory_assessment"]
        self.assertEqual(advisory["assessment"]["conclusion_code"], "evidence_supports_claim")
        self.assertEqual(advisory["human_review"]["level"], "optional")
        self.assertIn("continuity_unresolved", [item["code"] for item in advisory["signals"]])

    def test_long_out_of_frame_is_a_review_signal_not_an_automatic_material_gap(self):
        result = attach_advisory_assessment(
            review_result(
                label="review",
                continuity={
                    "continuity_verdict": "long_absence",
                    "longest_out_of_frame_seconds": 3.2,
                    "tracked_subjects": [{
                        "subject_id": "claimed_item",
                        "out_of_frame_events": [{
                            "duration_seconds": 3.2,
                            "within_required_display_window": True,
                            "identity_reestablished": False,
                        }],
                    }],
                }
            ),
            {"scenario": "product_damage"},
            readiness={"full_review_ready": True, "missing_required": []},
        )

        advisory = result["advisory_assessment"]
        self.assertEqual(advisory["workflow_recommendation"], "human_review")
        self.assertEqual(result["agent_report"]["parsed"]["material_gaps"], [])
        self.assertNotIn("补充连续原视频", advisory["assessment"]["conclusion"])
        self.assertIn("offscreen_review_signal", [item["code"] for item in advisory["signals"]])

    def test_shipping_package_absence_after_item_exposure_does_not_request_new_video(self):
        result = attach_advisory_assessment(
            review_result(
                label="positive",
                confidence=0.91,
                continuity={
                    "continuity_verdict": "long_absence",
                    "longest_out_of_frame_seconds": 31.8,
                    "tracked_subjects": [
                        {
                            "subject_id": "shipping_package",
                            "longest_out_of_frame_seconds": 31.8,
                            "out_of_frame_events": [{
                                "duration_seconds": 31.8,
                                "identity_reestablished": True,
                            }],
                        },
                        {
                            "subject_id": "claimed_item",
                            "visibility_coverage": 1.0,
                            "longest_out_of_frame_seconds": 0.0,
                            "out_of_frame_events": [],
                        },
                    ],
                },
            ),
            {"scenario": "product_damage"},
            readiness={"full_review_ready": True, "missing_required": []},
        )

        parsed = result["agent_report"]["parsed"]
        signal_codes = [item["code"] for item in result["advisory_assessment"]["signals"]]
        self.assertEqual(parsed["material_gaps"], [])
        self.assertNotIn("out_of_frame_over_threshold", signal_codes)
        self.assertEqual(result["advisory_assessment"]["workflow_recommendation"], "continue_by_customer_policy")

    def test_decisive_fact_keeps_material_gaps_as_optional_risk(self):
        result = attach_advisory_assessment(
            review_result(
                label="positive",
                confidence=0.91,
                continuity={
                    "continuity_verdict": "indeterminate",
                    "longest_out_of_frame_seconds": 4.0,
                    "tracked_subjects": [{"subject_id": "claimed_item"}],
                },
                parsed_extra={"material_gaps": ["缺少损伤成因证据"]},
            ),
            {"scenario": "product_damage"},
            readiness={"full_review_ready": True, "missing_required": []},
        )

        advisory = result["advisory_assessment"]
        self.assertEqual(advisory["assessment"]["conclusion_code"], "evidence_supports_claim")
        self.assertEqual(advisory["human_review"]["level"], "optional")
        self.assertEqual(advisory["workflow_recommendation"], "continue_by_customer_policy")

    def test_missing_business_defect_standard_is_not_requested_from_customer(self):
        result = attach_advisory_assessment(
            review_result(
                label="review",
                confidence=0.5,
                parsed_extra={
                    "material_gaps": ["缺少可执行的商品缺陷标准或合理公差边界。"],
                    "decision_policy_audit": {
                        "applied": True,
                        "rule_id": "PD-R-SPECIAL-PRODUCT-DEFECT-UNRESOLVED",
                        "reason": "已观察到特殊商品外观差异，但缺少可执行的商品缺陷标准。",
                    },
                },
            ),
            {"scenario": "product_damage"},
            readiness={"full_review_ready": True, "missing_required": []},
        )

        parsed = result["agent_report"]["parsed"]
        advisory = result["advisory_assessment"]
        self.assertEqual(parsed["material_gaps"], [])
        self.assertEqual(advisory["workflow_recommendation"], "continue_by_customer_policy")
        self.assertEqual(advisory["human_review"]["level"], "optional")
        self.assertNotEqual(advisory["sop_recommendation"]["code"], "request_more_material")

    def test_conflicting_evidence_requires_human_review(self):
        result = attach_advisory_assessment(
            review_result(parsed_extra={"evidence_conflicts": ["主视频与补充图片结论冲突"]}),
            {"scenario": "product_damage"},
            readiness={"full_review_ready": True, "missing_required": []},
        )

        advisory = result["advisory_assessment"]
        self.assertEqual(advisory["human_review"]["level"], "required")

    def test_minor_nested_field_conflict_requires_human_review_after_public_projection(self):
        result = attach_advisory_assessment(
            review_result(
                label="negative",
                confidence=0.84,
                parsed_extra={"minor_material_assessment": {
                    "declared_image_count": 62,
                    "accepted_image_count": 62,
                    "processed_image_count": 62,
                    "field_consistency": {
                        "verdict": "mismatched",
                        "checks": [{
                            "check_id": "commitment_signatures",
                            "status": "mismatched",
                            "message": "退款承诺书中的监护人签字互相对不上。",
                        }],
                    },
                }},
            ),
            {"scenario": "minor_refund"},
            readiness={"full_review_ready": True, "missing_required": []},
        )

        advisory = result["advisory_assessment"]
        self.assertEqual(advisory["human_review"]["level"], "required")
        self.assertIn("evidence_conflict", advisory["human_review"]["reason_codes"])
        self.assertEqual(advisory["workflow_recommendation"], "human_review")
        self.assertEqual(advisory["workflow_recommendation"], "human_review")
        self.assertIn("evidence_conflict", advisory["human_review"]["reason_codes"])

    def test_input_readiness_guard_overrides_stale_positive_summary(self):
        guarded = review_result(label="positive", confidence=0.93)
        guarded.update(
            {
                "predicted_label": "review",
                "confidence": 0.41,
                "input_readiness_guard": {
                    "applied": True,
                    "missing_required": ["订单SKU基准"],
                },
            }
        )

        result = attach_advisory_assessment(
            guarded,
            {"scenario": "wrong_item"},
            readiness={"full_review_ready": False, "missing_required": ["订单SKU基准"]},
        )

        advisory = result["advisory_assessment"]
        self.assertEqual(advisory["assessment"]["conclusion_code"], "evidence_inconclusive")
        self.assertEqual(advisory["assessment"]["confidence"], 0.41)
        self.assertEqual(advisory["workflow_recommendation"], "request_more_material")
        self.assertEqual(result["summary"]["predicted_label"], "review")
        self.assertIn("补充", advisory["assessment"]["conclusion"])
        self.assertNotIn("VIP客服复核", advisory["assessment"]["conclusion"])
        self.assertNotIn("支持用户所述事实", advisory["assessment"]["conclusion"])

    def test_real_guard_nesting_overrides_stale_positive_conclusion(self):
        guarded = _apply_input_readiness_guard(
            review_result(label="positive", confidence=0.93),
            {"full_review_ready": False, "missing_required": ["package_item_mapping"]},
        )
        result = attach_advisory_assessment(
            guarded,
            {"scenario": "wrong_item"},
            readiness={"full_review_ready": False, "missing_required": ["package_item_mapping"]},
        )

        advisory = result["advisory_assessment"]
        self.assertEqual(advisory["assessment"]["conclusion_code"], "evidence_inconclusive")
        self.assertNotIn("支持用户所述事实", advisory["assessment"]["conclusion"])
        self.assertEqual(result["agent_brief"]["conclusion"], advisory["assessment"]["conclusion"])

    def test_readiness_codes_are_rendered_as_actionable_material_requests(self):
        result = attach_advisory_assessment(
            review_result(label="review", confidence=0.65),
            {"scenario": "wrong_item"},
            readiness={
                "full_review_ready": False,
                "missing_required": [
                    "package_item_mapping",
                    "submitted_package_mapping",
                    "fulfillment_baseline.selection_rules_complete",
                ],
            },
        )

        self.assertEqual(
            result["agent_report"]["parsed"]["material_gaps"],
            [
                "请补充订单应发商品与包裹的对应关系。",
                "请补充本次提交的包裹与订单或物流单号的对应关系。",
                "请补充随机款、赠品或替代规格等选款规则；如不适用，请明确声明不适用。",
            ],
        )

    def test_scene_material_readiness_gaps_drive_the_final_customer_action(self):
        review = review_result(label="positive", confidence=0.74)
        review["material_readiness"] = {
            "scenario": "product_damage",
            "status": "incomplete",
            "confidence": 0.91,
            "reason": "当前商品有伤场景仍缺少必要材料或已有材料不满足审核要求。",
            "checklist": [],
            "missing_items": ["开箱视频满足封箱起始、面单、连续性、商品展示与伤点可判断要求"],
            "warnings": [],
        }

        result = attach_advisory_assessment(
            review,
            {"scenario": "product_damage"},
            readiness={"full_review_ready": True, "missing_required": []},
        )

        advisory = result["advisory_assessment"]
        self.assertEqual(advisory["workflow_recommendation"], "request_more_material")
        self.assertEqual(advisory["human_review"]["level"], "not_required")
        self.assertIn(
            "开箱视频满足封箱起始、面单、连续性、商品展示与伤点可判断要求",
            result["agent_report"]["parsed"]["material_gaps"],
        )
        self.assertNotIn(
            "inconclusive_product_damage_gate",
            advisory["human_review"]["reason_codes"],
        )

    def test_confirmed_damage_is_not_hidden_by_opening_material_gap(self):
        review = review_result(
            label="review",
            confidence=0.63,
            parsed_extra={
                "damage_causality_assessment": {
                    "damage_presence": "confirmed",
                    "reason": "主视频中已看到商品表面存在可见伤点。",
                },
            },
        )
        review["material_readiness"] = {
            "scenario": "product_damage",
            "status": "incomplete",
            "confidence": 1.0,
            "reason": "开箱证据链仍未闭环。",
            "checklist": [],
            "missing_items": ["开箱视频中的商品关联与连续展示证据"],
            "warnings": [],
        }

        result = attach_advisory_assessment(
            review,
            {"scenario": "product_damage"},
            readiness={"full_review_ready": True, "missing_required": []},
        )

        advisory = result["advisory_assessment"]
        self.assertEqual(advisory["workflow_recommendation"], "request_more_material")
        self.assertEqual(advisory["assessment"]["conclusion_code"], "evidence_inconclusive")
        self.assertIn("已确认商品存在可见伤点", advisory["assessment"]["conclusion"])
        self.assertIn("暂不能判断责任归属", advisory["assessment"]["conclusion"])
        self.assertNotIn("现有证据不足以形成明确事实判断", advisory["assessment"]["conclusion"])

    def test_severe_structural_damage_is_not_hidden_by_missing_opening_material(self):
        review = review_result(
            label="positive",
            confidence=0.94,
            parsed_extra={
                "decision_policy_audit": {
                    "applied": True,
                    "severe_alert_eligible": True,
                    "rule_id": "PD-P-SEVERE-STRUCTURAL-DAMAGE",
                    "reason": "高置信严重结构问题已确认，建议重点跟进。",
                },
            },
        )
        review["material_readiness"] = {
            "scenario": "product_damage",
            "status": "incomplete",
            "confidence": 0.92,
            "reason": "缺少开箱视频。",
            "checklist": [],
            "missing_items": ["包含初次拆开包裹动作的开箱视频"],
            "warnings": [],
        }

        result = attach_advisory_assessment(
            review,
            {"scenario": "product_damage"},
            readiness={"full_review_ready": True, "missing_required": []},
        )

        advisory = result["advisory_assessment"]
        self.assertEqual(advisory["workflow_recommendation"], "continue_by_customer_policy")
        self.assertNotEqual(advisory["human_review"]["level"], "required")
        self.assertEqual(
            advisory["assessment"]["conclusion_code"],
            "severe_structural_damage_follow_up",
        )
        self.assertIn("交易归属", advisory["assessment"]["conclusion"])
        self.assertNotIn("支持用户诉求", advisory["assessment"]["conclusion"])
        self.assertEqual(advisory["sop_recommendation"]["code"], "further_assessment")

    def test_no_action_continuation_does_not_emit_process_filler(self):
        result = attach_advisory_assessment(
            review_result(),
            {"scenario": "product_damage"},
            readiness={"full_review_ready": True, "missing_required": []},
        )

        self.assertEqual(
            result["advisory_assessment"]["workflow_recommendation"],
            "continue_by_customer_policy",
        )
        self.assertEqual(result["advisory_assessment"]["human_review"]["level"], "not_required")
        self.assertNotIn("next_step", result["agent_brief"])

    def test_output_options_and_server_managed_routing_policy_are_explicit(self):
        metadata = ReviewCaseMetadata.model_validate(
            {
                "client_case_id": "CASE-OUTPUT-1",
                "scenario": "product_damage",
                "output_options": {"include_html_report": False},
                "review_routing_policy": {"policy_ref": "MITAKO-ROUTING@20260815.1"},
            }
        )

        self.assertFalse(metadata.output_options.include_html_report)
        self.assertFalse(html_report_requested(metadata.model_dump(mode="json")))
        self.assertEqual(metadata.review_routing_policy.policy_ref, "MITAKO-ROUTING@20260815.1")

    def test_legacy_fields_follow_primary_advisory_contract(self):
        stale = review_result(confidence=0.92)
        stale["agent_report"]["parsed"].update(
            {"human_required": True, "decision": "manual_review", "system_yes_no": "REVIEW"}
        )
        stale["agent_brief"]["system_yes_no"] = "REVIEW"

        result = attach_advisory_assessment(
            stale,
            {"scenario": "product_damage"},
            readiness={"full_review_ready": True, "missing_required": []},
        )

        parsed = result["agent_report"]["parsed"]
        self.assertFalse(parsed["human_required"])
        self.assertEqual(parsed["decision"], "continue_by_customer_policy")
        self.assertEqual(parsed["system_yes_no"], "YES")
        self.assertEqual(result["summary"]["system_yes_no"], "YES")
        self.assertEqual(result["agent_brief"]["system_yes_no"], "YES")

    def test_minor_authoritative_verification_pending_requires_human_review(self):
        result = attach_advisory_assessment(
            review_result(
                confidence=0.88,
                parsed_extra={
                    "authoritative_verification": {
                        "status": "customer_integration_required",
                        "pending_checks": ["guardian_identity", "payment_ownership"],
                    }
                },
            ),
            {
                "scenario": "minor_refund",
                "minor_refund_policy": {"authoritative_verification": "required"},
            },
            readiness={"full_review_ready": True, "missing_required": []},
        )

        advisory = result["advisory_assessment"]
        self.assertEqual(advisory["human_review"]["level"], "required")
        self.assertIn("authoritative_verification_pending", advisory["human_review"]["reason_codes"])

    def test_minor_missing_authoritative_integration_is_non_blocking_by_default(self):
        result = attach_advisory_assessment(
            review_result(
                confidence=0.88,
                parsed_extra={
                    "authoritative_verification": {
                        "status": "not_configured_optional",
                        "pending_checks": ["guardian_identity", "payment_ownership"],
                    }
                },
            ),
            {"scenario": "minor_refund"},
            readiness={"full_review_ready": True, "missing_required": []},
        )

        advisory = result["advisory_assessment"]
        self.assertEqual(advisory["human_review"]["level"], "not_required")
        self.assertEqual(advisory["workflow_recommendation"], "continue_by_customer_policy")
        self.assertNotIn("authoritative_verification_pending", advisory["human_review"]["reason_codes"])

    def test_minor_optional_review_does_not_claim_every_case_needs_vip(self):
        result = attach_advisory_assessment(
            review_result(
                label="review",
                confidence=0.69,
                parsed_extra={"minor_material_assessment": {
                    "declared_image_count": 20,
                    "accepted_image_count": 20,
                    "processed_image_count": 20,
                }},
            ),
            {"scenario": "minor_refund"},
            readiness={"full_review_ready": True, "missing_required": []},
        )

        advisory = result["advisory_assessment"]
        self.assertEqual(advisory["human_review"]["level"], "optional")
        self.assertNotIn("VIP客服", advisory["assessment"]["conclusion"])
        self.assertIn("不要求每单人工复审", advisory["human_review"]["recommendation"])

    def test_under_ten_payment_gap_requests_only_the_missing_process_explanation(self):
        result = attach_advisory_assessment(
            review_result(
                label="positive",
                confidence=0.82,
                parsed_extra={"minor_material_assessment": {
                    "declared_image_count": 20,
                    "accepted_image_count": 20,
                    "processed_image_count": 20,
                    "conclusion": "五类材料已齐全，继续按材料事实审核。",
                    "required_materials": [
                        "请补充说明未成年人如何获得或得知支付密码。",
                        "请补充说明监护人如何、何时发现消费。",
                    ],
                    "payment_capability_risk": {
                        "level": "high",
                        "low_age": True,
                        "process_evidence_status": "unresolved",
                        "requires_review": False,
                        "requires_more_material": True,
                        "effect": "低龄支付过程说明尚未闭环",
                        "evidence_image_indices": [3, 5],
                    },
                }},
            ),
            {"scenario": "minor_refund"},
            readiness={"full_review_ready": True, "missing_required": []},
        )

        advisory = result["advisory_assessment"]
        self.assertEqual(advisory["human_review"]["level"], "not_required")
        self.assertEqual(advisory["workflow_recommendation"], "request_more_material")
        self.assertIn("material_resubmission_available", advisory["human_review"]["reason_codes"])
        self.assertFalse(result["agent_report"]["parsed"]["human_required"])
        self.assertIn("支付密码", "；".join(result["agent_report"]["parsed"]["material_gaps"]))
        self.assertIn("监护人如何、何时发现消费", "；".join(result["agent_report"]["parsed"]["material_gaps"]))

    def test_inconclusive_sop_recommendation_uses_scene_specific_customer_language(self):
        cases = (
            ("product_damage", ("伤点", "商品身份", "开箱证据")),
            ("wrong_item", ("是否发错", "应收商品", "实收商品", "同包裹证据")),
            ("missing_item", ("是否漏发", "应发商品", "实收商品", "分包", "物流", "仓库")),
        )

        for scenario, expected_markers in cases:
            with self.subTest(scenario=scenario):
                result = attach_advisory_assessment(
                    review_result(label="review", confidence=0.86),
                    {"scenario": scenario},
                    readiness={"full_review_ready": True, "missing_required": []},
                )

                recommendation = result["advisory_assessment"]["sop_recommendation"]["recommendation"]
                self.assertNotIn("支持或不支持用户诉求", recommendation)
                for marker in expected_markers:
                    self.assertIn(marker, recommendation)

    def test_minor_advisory_uses_material_language_instead_of_refund_support_language(self):
        for label, expected in (
            ("positive", "五类材料与可见字段初审齐全"),
            ("negative", "五类材料存在明确缺口或冲突"),
            ("review", "五类材料或可见字段仍待确认"),
        ):
            with self.subTest(label=label):
                result = attach_advisory_assessment(
                    review_result(
                        label=label,
                        confidence=0.86,
                        parsed_extra={
                            "minor_material_assessment": {
                                "declared_image_count": 5,
                                "accepted_image_count": 5,
                                "processed_image_count": 5,
                            },
                        },
                    ),
                    {"scenario": "minor_refund"},
                    readiness={"full_review_ready": True, "missing_required": []},
                )

                advisory = result["advisory_assessment"]
                public_text = " ".join((
                    advisory["assessment"]["conclusion"],
                    advisory["sop_recommendation"]["recommendation"],
                    result["agent_brief"]["conclusion"],
                ))
                self.assertIn(expected, public_text)
                self.assertNotIn("支持用户诉求", public_text)
                self.assertNotIn("不支持用户诉求", public_text)
                self.assertEqual(advisory["sop_recommendation"]["code"], "further_assessment")

    def test_minor_low_age_with_verified_payment_process_is_silent(self):
        result = attach_advisory_assessment(
            review_result(
                label="positive",
                confidence=0.88,
                parsed_extra={"minor_material_assessment": {
                    "declared_image_count": 20,
                    "accepted_image_count": 20,
                    "processed_image_count": 20,
                    "payment_capability_risk": {
                        "level": "none",
                        "low_age": True,
                        "process_evidence_status": "matched",
                        "requires_review": False,
                        "effect": "低龄支付过程说明已核对",
                        "evidence_image_indices": [3, 5],
                    },
                }},
            ),
            {"scenario": "minor_refund"},
            readiness={"full_review_ready": True, "missing_required": []},
        )

        advisory = result["advisory_assessment"]
        self.assertEqual(advisory["human_review"]["level"], "not_required")
        self.assertNotIn("minor_low_age_process_verified", advisory["human_review"]["reason_codes"])
        self.assertNotIn("minor_payment_capability_risk", advisory["human_review"]["reason_codes"])

    def test_minor_under_nine_high_confidence_requires_human_payment_review(self):
        result = attach_advisory_assessment(
            review_result(
                label="positive",
                confidence=0.9,
                parsed_extra={"minor_material_assessment": {
                    "declared_image_count": 20,
                    "accepted_image_count": 20,
                    "processed_image_count": 20,
                    "payment_capability_risk": {
                        "level": "none",
                        "low_age": True,
                        "under_nine": True,
                        "age_confidence": "high",
                        "process_evidence_status": "matched",
                        "requires_review": True,
                        "requires_more_material": False,
                        "evidence_image_indices": [1, 3],
                    },
                }},
            ),
            {"scenario": "minor_refund"},
            readiness={"full_review_ready": True, "missing_required": []},
        )

        advisory = result["advisory_assessment"]
        self.assertEqual(advisory["human_review"]["level"], "required")
        self.assertEqual(advisory["workflow_recommendation"], "human_review")
        self.assertIn("minor_under_nine_high_confidence", advisory["human_review"]["reason_codes"])
        signal = next(
            item for item in advisory["signals"]
            if item["code"] == "minor_under_nine_high_confidence"
        )
        self.assertEqual(signal["severity"], "warning")
        self.assertIn("独立支付能力", signal["effect"])
        self.assertEqual(result["agent_report"]["parsed"]["predicted_label"], "positive")

    def test_product_damage_inconclusive_gate_requires_human_review(self):
        result = attach_advisory_assessment(
            review_result(label="review", confidence=0.64),
            {"scenario": "product_damage"},
            readiness={"full_review_ready": True, "missing_required": []},
        )

        advisory = result["advisory_assessment"]
        self.assertEqual(advisory["human_review"]["level"], "required")
        self.assertEqual(advisory["workflow_recommendation"], "human_review")
        self.assertIn(
            "inconclusive_product_damage_gate",
            advisory["human_review"]["reason_codes"],
        )

    def test_failed_review_does_not_ask_user_for_business_materials(self):
        result = attach_advisory_assessment(
            review_result(label="review", confidence=0.4),
            {"scenario": "product_damage"},
            readiness={"full_review_ready": False, "missing_required": ["customer_claim_or_claim_scope"]},
            succeeded=False,
        )

        advisory = result["advisory_assessment"]
        self.assertEqual(advisory["evidence_attention"]["level"], "gray")
        self.assertEqual(advisory["evidence_attention"]["missing_evidence"], [])
        self.assertEqual(result["agent_report"]["parsed"]["material_gaps"], [])
        self.assertFalse(any(item["code"] == "material_gap" for item in advisory["signals"]))

    def test_minor_high_risk_without_confirmed_low_age_does_not_request_process_material(self):
        result = attach_advisory_assessment(
            review_result(
                label="review",
                confidence=0.82,
                parsed_extra={"minor_material_assessment": {
                    "declared_image_count": 20,
                    "accepted_image_count": 20,
                    "processed_image_count": 20,
                    "payment_capability_risk": {
                        "level": "high",
                        "low_age": None,
                        "process_evidence_status": "unresolved",
                        "requires_review": False,
                        "requires_more_material": False,
                    },
                }},
            ),
            {"scenario": "minor_refund"},
            readiness={"full_review_ready": True, "missing_required": []},
        )

        advisory = result["advisory_assessment"]
        self.assertEqual(advisory["workflow_recommendation"], "continue_by_customer_policy")
        self.assertNotIn("minor_payment_process_evidence_gap", [item["code"] for item in advisory["signals"]])

    def test_minor_refund_policy_defaults_to_visual_review_without_external_verification(self):
        metadata = ReviewCaseMetadata.model_validate({
            "client_case_id": "MINOR-DEFAULT",
            "scenario": "minor_refund",
        })

        self.assertEqual(metadata.minor_refund_policy.authoritative_verification, "disabled")
        self.assertEqual(metadata.minor_refund_policy.review_mode, "standard")

    def test_minor_internal_processing_gap_retries_system_without_asking_user_for_material(self):
        result = attach_advisory_assessment(
            review_result(
                label="review",
                confidence=0.5,
                parsed_extra={
                    "material_gaps": ["本轮未完成全部图片的可靠识别，缺件结论已被门禁阻断。"],
                    "minor_material_assessment": {
                        "declared_image_count": 62,
                        "accepted_image_count": 62,
                        "processed_image_count": 40,
                        "ingestion_complete": True,
                        "coverage_complete": False,
                        "image_batch_failures": [{"batch_index": 11, "error": "provider_timeout"}],
                    },
                },
            ),
            {"scenario": "minor_refund"},
            readiness={"full_review_ready": True, "missing_required": []},
        )

        advisory = result["advisory_assessment"]
        self.assertEqual(advisory["assessment"]["conclusion_code"], "technical_processing_incomplete")
        self.assertIsNone(advisory["assessment"]["confidence"])
        self.assertEqual(advisory["workflow_recommendation"], "system_retry")
        self.assertEqual(advisory["human_review"]["level"], "not_required")
        self.assertIn("technical_processing_incomplete", [item["code"] for item in advisory["signals"]])
        self.assertNotIn("material_gap", [item["code"] for item in advisory["signals"]])
        self.assertNotIn("补充收集材料", advisory["human_review"]["recommendation"])

        public_contract = ReviewAdvisoryAssessment.model_validate(advisory)
        self.assertEqual(public_contract.assessment.conclusion_code, "technical_processing_incomplete")
        self.assertEqual(public_contract.assessment.calibration_status, "not_applicable_processing_incomplete")
        self.assertEqual(public_contract.workflow_recommendation, "system_retry")

    def test_video_transport_failure_is_a_system_retry_for_every_scene(self):
        result = attach_advisory_assessment(
            review_result(
                label="review",
                confidence=0.0,
                parsed_extra={
                    "processing_status": "technical_processing_incomplete",
                    "system_action": "system_retry",
                    "material_gaps": ["视频无法送审"],
                },
            ),
            {"scenario": "product_damage"},
            readiness={"full_review_ready": True, "missing_required": []},
        )

        advisory = result["advisory_assessment"]
        self.assertEqual(advisory["workflow_recommendation"], "system_retry")
        self.assertEqual(advisory["human_review"]["level"], "not_required")
        self.assertEqual(advisory["evidence_attention"]["missing_evidence"], [])
        self.assertNotIn("material_gap", [item["code"] for item in advisory["signals"]])

    def test_case_caller_cannot_override_server_managed_routing_thresholds(self):
        with self.assertRaises(ValidationError):
            ReviewCaseMetadata.model_validate(
                {
                    "client_case_id": "CASE-BAD-THRESHOLDS",
                    "scenario": "product_damage",
                    "review_routing_policy": {"required_below_confidence": 0.9},
                }
            )

    def test_customer_risk_only_changes_sampling_advice_not_fact_conclusion(self):
        result = attach_advisory_assessment(
            review_result(label="positive", confidence=0.92),
            {
                "scenario": "wrong_item",
                "customer_risk_context": {
                    "risk_level": "high",
                    "reason_codes": ["repeat_after_sales"],
                },
            },
            readiness={"full_review_ready": True, "missing_required": []},
        )

        advisory = result["advisory_assessment"]
        self.assertEqual(advisory["assessment"]["conclusion_code"], "evidence_supports_claim")
        self.assertEqual(advisory["human_review"]["level"], "optional")
        self.assertIn("customer_risk_context", [item["code"] for item in advisory["signals"]])
        self.assertFalse(advisory["policy"]["business_action_allowed"])


if __name__ == "__main__":
    unittest.main()
