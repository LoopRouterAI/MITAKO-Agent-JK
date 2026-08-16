# -*- coding: utf-8 -*-
"""视觉审核公开报告的证据展示与媒体回链测试。"""

import unittest
from pathlib import Path

from poc.visual_review_poc.report_assets import LIGHTBOX_HTML, REPORT_CSS
from poc.visual_review_poc.report_renderer import (
    _decision_policy_panel,
    _evidence_items,
    _h,
    _public_status,
    _public_verdict,
    _safe_agent_reason,
    render_public_report,
    safe_agent_conclusion,
    safe_agent_next_step,
)
from poc.visual_review_poc.report_evidence import _gallery_items, _merge_evidence_items, _summary_evidence_items
from poc.visual_review_poc.workbench_server import _public_agent_report_payload


def _report_data():
    return {
        "review_label": "商品有伤审核",
        "agent_report": {
            "scenario_label": "商品有伤审核",
            "system_prompt": "不得出现在公开报告中的内部提示词",
            "runtime": {
                "latency_seconds": 1.25,
                "channel": "internal-provider-name",
                "api_key": "SECRET-KEY-MUST-NOT-LEAK",
            },
            "inference_estimate": {"total_tokens": 321, "estimated_usd": 0.01},
            "evidence_package": {
                "videos": [{"file_name": "audit.mp4"}],
                "frames_sent": 4,
                "supplemental_images_sent": 1,
            },
            "media_gallery": {
                "frames": [
                    {
                        "video_index": 1,
                        "frame_index": 11,
                        "timestamp": "00:04.00",
                        "file": "frame-index.jpg",
                        "url": "/media/frame-index.jpg",
                        "video_url": "/media/audit.mp4#t=4",
                    },
                    {
                        "video_index": 1,
                        "frame_index": 12,
                        "timestamp": "00:09.500",
                        "file": "timestamp.jpg",
                        "url": "/media/timestamp.jpg",
                    },
                    {
                        "video_index": 1,
                        "frame_index": 13,
                        "timestamp": "00:10.00",
                        "file_name": "Risk-Only.JPG",
                        "url": "/media/file-name.jpg",
                    },
                    {
                        "video_index": 1,
                        "frame_index": 14,
                        "timestamp": "00:12.00",
                        "file": "issue-time.jpg",
                        "url": "/media/issue-time.jpg",
                    },
                ],
                "images": [
                    {
                        "image_index": 5,
                        "file": "supplement.jpg",
                        "url": "/media/image-index.jpg",
                    }
                ],
            },
            "parsed": {
                "predicted_label": "review",
                "confidence": 0.68,
                "confidence_reason": "支持证据清晰，但关键开箱阶段缺失，因此保持中等置信度。",
                "video_audit_conclusion": {
                    "sampling_boundary_status": "covered",
                    "technical_timeline_status": "requires_media_forensics",
                    "opening_integrity": "complete",
                    "evidence_continuity_status": "long_absence",
                    "continuity_reason": "视频首尾抽帧已覆盖，但商品曾离镜。",
                    "swap_risk_level": "medium",
                    "edit_or_cut_risk": "媒体取证低风险",
                },
                "confidence_components": {
                    "main_segment_mean": 0.84,
                    "damage_origin": 0.42,
                    "continuity_visibility_coverage": 0.56,
                    "final_decision": 0.68,
                    "calibration_status": "uncalibrated_model_score",
                    "interpretation": "这些分数不是正确率。",
                },
                "overall_audit": {
                    "core_reason": "当前证据显示商品表面存在疑似压痕。",
                    "confidence": 0.68,
                },
                "decision_policy_audit": {
                    "mode": "classification_recommendation",
                    "policy_ref": "MITAKO-PD-20260720@2",
                    "applied": False,
                    "reason": "当前门槛未全部满足，保持人工复核。",
                    "failed_conditions": ["claimed_item_absence_within_limit", "supplemental_evidence_resolved"],
                    "evidence_gate": {
                        "claimed_item_longest_out_of_frame_seconds": 10.0,
                        "media_forensics_status": "completed",
                    },
                },
                "adopted_evidence": [
                    {
                        "source_type": "video_frame",
                        "frame_index": 11,
                        "fact": "第 11 帧可见表面压痕。",
                        "why_it_matters": "该画面直接支持商品有伤诉求。",
                        "confidence": 0.91,
                    },
                    {
                        "source_type": "supplementary_image",
                        "image_index": 5,
                        "file": "supplement.jpg",
                        "fact": "补充图从另一角度显示相同压痕。",
                        "confidence": 0.88,
                    },
                ],
                "challenging_evidence": [
                    {
                        "source_type": "video_frame",
                        "timestamp": "9.5s",
                        "description": "该时间点反光较强，可能放大表面纹理。",
                    }
                ],
                "frame_findings": [
                    {
                        "source_type": "video_frame",
                        "file_name": "folder/risk-only.jpg",
                        "visible_facts": "画面出现短暂遮挡。",
                        "risk": "high",
                    },
                    {
                        "frame_index": 11,
                        "visible_facts": "画面正常。",
                        "risk": "none",
                    },
                ],
                "issue_timestamps": [
                    {
                        "timestamp": 12,
                        "description": "商品离开镜头，需要复核前后连续性。",
                    }
                ],
                "material_gaps": "缺少未拆封包装的连续开箱画面。",
                "damage_causality_assessment": {
                    "damage_presence": "confirmed",
                    "damage_type_and_location": "包装右下角可见压痕。",
                    "first_visible_evidence": {
                        "source_type": "video_frame",
                        "frame_index": 11,
                        "fact": "第 11 帧首次清晰看到压痕。",
                    },
                    "pre_opening_state_visible": False,
                    "opening_action_visible": True,
                    "damage_change_observed": False,
                    "damage_timing": "post_opening_only",
                    "most_likely_origin": "indeterminate",
                    "origin_confidence": 0.42,
                    "causal_evidence_level": "insufficient",
                    "claim_support": "insufficient",
                    "before_action_evidence": [{"video_index": 1, "global_frame_index": 11, "frame_index": 11, "timestamp": "00:04.00", "subject": "包装", "location": "右下角", "chain_id": "chain-1", "fact": "动作前争议部位被包装遮挡。"}],
                    "action_evidence": [{"video_index": 1, "global_frame_index": 12, "frame_index": 12, "timestamp": "00:09.500", "subject": "包装", "location": "右下角", "chain_id": "chain-1", "fact": "用户正常打开外包装。"}],
                    "after_action_evidence": [{"video_index": 1, "global_frame_index": 14, "frame_index": 14, "timestamp": "00:12.00", "subject": "包装", "location": "右下角", "chain_id": "chain-1", "fact": "动作后压痕首次可见，但无法确认何时形成。"}],
                    "possible_origins": [
                        {
                            "origin": "logistics_transport",
                            "confidence": 0.42,
                            "supporting_evidence": ["包装存在受压痕迹"],
                            "challenging_evidence": ["没有拆封前画面"],
                        }
                    ],
                    "alternative_explanations": ["拆封后摆放造成"],
                    "cannot_conclude_reason": "缺少损伤形成前后的连续对比。",
                    "evidence_source_summary": {
                        "primary_video": {"scope": "sampled_opening_video", "damage_presence": "not_visible"},
                        "supplemental_images": {
                            "provided_count": 1,
                            "referenced_count": 1,
                            "linkage_status": "unresolved",
                            "evidence_findings": [{
                                "source_type": "supplementary_image",
                                "image_index": 5,
                                "fact": "补充特写可见疑似压痕，但与开箱商品同物关系未解决。",
                                "why_it_matters": "该图片不能被静默忽略，需继续核对同物与过程关联。",
                            }],
                        },
                        "decision_boundary": "补充特写图未建立同物、同部位和过程关联时，不能单独推翻主视频结论。",
                    },
                    "key_evidence": [{
                        "source_type": "video_frame",
                        "video_index": 1,
                        "global_frame_index": 11,
                        "timestamp": "00:04.00",
                        "fact": "关键审查帧未见主诉折痕。",
                        "why_it_matters": "用于复核主视频是否支持用户所述损伤。",
                    }],
                },
                "object_continuity_assessment": {
                    "continuity_verdict": "long_absence",
                    "longest_out_of_frame_seconds": 3.5,
                    "total_unobserved_seconds": 3.5,
                    "policy": {"effect": "按必要展示窗口判断，不使用统一秒数阈值"},
                    "tracked_subjects": [
                        {
                            "subject_id": "claimed_item",
                            "description": "争议商品",
                            "tracking_start": "00:04.00",
                            "tracking_end": "00:12.00",
                            "visibility_coverage": 0.56,
                            "longest_out_of_frame_seconds": 3.5,
                            "out_of_frame_events": [
                                {
                                    "start_timestamp": "00:06.00",
                                    "end_timestamp": "00:09.50",
                                    "duration_seconds": 3.5,
                                    "visibility": "out_of_frame",
                                    "before_evidence": {"global_frame_index": 11, "timestamp_label": "00:04.00"},
                                    "out_of_frame_evidence": {"global_frame_index": 12, "timestamp_label": "00:09.500"},
                                    "after_evidence": {"global_frame_index": 14, "timestamp_label": "00:12.00"},
                                    "identity_reestablished": False,
                                }
                            ],
                        }
                    ],
                },
                "fulfillment_reconciliation": {
                    "baseline_version": "ORDER-1@V1",
                    "expected_items": [{"sku": "SKU-1", "product_name": "徽章", "expected_quantity": 2}],
                    "observed_items": [{"sku": "SKU-1", "product_name": "徽章", "observed_quantity": 1, "evidence_timestamp": "00:10.00"}],
                    "suspected_missing_items": [{"sku": "SKU-1", "product_name": "徽章", "expected_quantity": 2, "observed_quantity": 1}],
                    "unconfirmed_items": [],
                    "package_coverage": "1/1 个包裹完成开箱并铺开展示",
                    "all_packages_uploaded": True,
                    "all_items_displayed": True,
                    "confidence": 0.81,
                    "decision_boundary": "仅作为结构化清点结果。",
                },
                "model_limitations": [
                    "抽帧不能替代对原视频连续播放的最终人工复核。",
                    {"limitation": "反光可能影响细微划痕判断。"},
                ],
            },
        },
    }


class ReportEvidenceRenderingTest(unittest.TestCase):
    def test_public_report_uses_plain_customer_facing_title(self) -> None:
        data = _report_data()
        data["agent_report"]["scenario_label"] = "漏发货审核"
        html = render_public_report(data)

        self.assertIn("漏发货审核报告</title>", html)
        self.assertNotIn("漏发货审核审核报告", html)
        self.assertNotIn("Agent 报告", html)

    def test_public_report_uses_uniform_radius_and_safe_text_wrapping(self) -> None:
        self.assertNotIn("border-radius:999px", REPORT_CSS)
        self.assertNotIn("border-radius:6px", REPORT_CSS)
        self.assertNotIn("word-break:break-all", REPORT_CSS)
        self.assertIn("overflow-wrap:anywhere", REPORT_CSS)
        self.assertIn("max-width:100%", REPORT_CSS)
        self.assertIn("object-fit:contain", REPORT_CSS)
        self.assertIn("min-height:44px", REPORT_CSS)
        self.assertIn("font-size:clamp(30px,3.6vw,42px)", REPORT_CSS)
        self.assertNotIn("4.4vw,62px", REPORT_CSS)

    def test_media_preview_uses_native_dialog_and_restores_focus(self) -> None:
        self.assertIn('<dialog class="lightbox" id="mediaLightbox"', LIGHTBOX_HTML)
        self.assertIn("box.showModal()", LIGHTBOX_HTML)
        self.assertIn("box.close()", LIGHTBOX_HTML)
        self.assertIn("opener.focus()", LIGHTBOX_HTML)
        self.assertNotIn('role="dialog"', LIGHTBOX_HTML)

    def test_continuity_report_explains_effective_window_without_seconds_threshold(self) -> None:
        html = render_public_report(_report_data())

        self.assertIn("必要展示窗口", html)
        self.assertNotIn("复核阈值", html)

    def test_summary_evidence_prioritizes_issue_and_merges_same_video_moment(self):
        parsed = {
            "adopted_evidence": [
                {"video_index": 1, "timestamp": "00:00", "visible_facts": "封箱起拍"},
            ],
            "evidence_refs": [
                {"field": "sealed_start", "asset_ref": "native_video_1", "timestamp": "00:00", "fact": "封箱起拍"},
                {"field": "waybill_visible", "asset_ref": "native_video_1", "timestamp": "00:00", "fact": "面单可见"},
                {"field": "issue_visible", "asset_ref": "native_video_1", "timestamp": "01:55", "fact": "划痕清晰可见"},
                {"field": "claimed_item", "asset_ref": "native_video_1", "timestamp": "01:50", "fact": "争议商品出现"},
            ],
        }

        items = _summary_evidence_items(parsed)

        self.assertEqual(items[0]["field"], "issue_visible")
        self.assertEqual(items[0]["timestamp"], "01:55")
        self.assertEqual(items[1]["field"], "claimed_item")
        opening = next(item for item in items if item.get("timestamp") == "00:00")
        self.assertEqual(opening["fact"], "封箱起拍；面单可见")
        self.assertEqual(len([item for item in items if item.get("timestamp") == "00:00"]), 1)

    def test_detailed_evidence_merges_same_video_moment_without_double_punctuation(self):
        items = _merge_evidence_items([
            {"field": "sealed_start", "asset_ref": "native_video_1", "timestamp": "00:00", "fact": "封箱起拍。"},
            {"field": "waybill_visible", "asset_ref": "native_video_1", "timestamp": "00:00", "fact": "面单可见"},
        ])

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["fact"], "封箱起拍；面单可见")

    def test_report_renders_customer_nine_field_video_checklist(self):
        data = _report_data()
        parsed = data["agent_report"]["parsed"]
        parsed.update({
            "all_items_shown": True,
            "continuous": True,
            "has_edit": False,
            "has_offscreen": False,
            "has_speed_change": None,
            "issue_visible": True,
            "overall_video_result": "indeterminate",
            "sealed_start": True,
            "waybill_visible": True,
        })

        report_html = render_public_report(data)

        self.assertIn("开箱视频九项核对", report_html)
        for label in (
            "相关商品是否全部展示",
            "关键过程是否连续",
            "是否存在剪辑",
            "商品是否离开画面",
            "是否存在变速",
            "投诉问题是否清晰可见",
            "视频综合结论",
            "是否封箱起拍",
            "面单是否可见",
        ):
            self.assertIn(label, report_html)
        self.assertIn("<td>待确认</td>", report_html)
        self.assertIn("<td>否</td>", report_html)
        self.assertNotIn("<td>不符合</td>", report_html)

    def test_report_highlights_severe_quality_issue_and_field_evidence_confidence(self):
        data = _report_data()
        parsed = data["agent_report"]["parsed"]
        parsed.update({
            "all_items_shown": True,
            "continuous": True,
            "has_edit": False,
            "has_offscreen": False,
            "has_speed_change": None,
            "issue_visible": True,
            "overall_video_result": "compliant",
            "sealed_start": True,
            "waybill_visible": True,
            "field_confidences": {
                "all_items_shown": 0.88,
                "continuous": 0.9,
                "has_edit": 0.91,
                "has_offscreen": 0.89,
                "has_speed_change": 0.62,
                "issue_visible": 0.92,
                "sealed_start": 0.95,
                "waybill_visible": 0.94,
            },
            "evidence_refs": [
                {
                    "field": "issue_visible",
                    "asset_ref": "native_video_1",
                    "timestamp": "02:19.00",
                    "fact": "同一折痕在清晰近景中持续可见。",
                },
                {
                    "field": "issue_visible",
                    "asset_ref": "native_video_1",
                    "timestamp": "02:23.00",
                    "fact": "换角度后折痕仍然存在。",
                },
            ],
            "damage_causality_assessment": {
                "severity_assessment": {
                    "level": "severe",
                    "structural_failure": True,
                    "confidence": 0.92,
                    "reason": "主体结构断裂，影响正常展示。",
                }
            },
            "decision_policy_audit": {"severe_alert_eligible": True},
        })

        report_html = render_public_report(data)

        self.assertIn("严重商品质量问题", report_html)
        self.assertIn('class="severity-flag severity-yes"', report_html)
        self.assertIn("<b>是</b>", report_html)
        self.assertIn("<th>判断置信度</th>", report_html)
        self.assertIn("92%", report_html)
        self.assertIn("02:19.00、02:23.00", report_html)

    def test_video_continuity_uses_object_tracking_when_video_summary_omits_it(self):
        data = _report_data()
        parsed = data["agent_report"]["parsed"]
        parsed["video_audit_conclusion"].pop("evidence_continuity_status", None)
        parsed["object_continuity_assessment"]["continuity_verdict"] = "continuous"

        report_html = render_public_report(data)

        self.assertIn("商品证据连续性</small><b>连续</b>", report_html)
        self.assertNotIn("商品证据连续性</small><b>未知</b>", report_html)

    def test_image_only_report_omits_video_metrics_and_video_proof(self):
        data = _report_data()
        report = data["agent_report"]
        report["evidence_package"]["videos"] = []
        report["evidence_package"]["frames_sent"] = 0
        report["media_gallery"]["frames"] = []

        report_html = render_public_report(data)

        self.assertNotIn("商品连续性分数", report_html)
        self.assertNotIn("视频审核论证", report_html)
        self.assertNotIn("视频查看密度", report_html)

    def test_public_agent_report_preserves_timeline_coverage_metadata(self):
        report = _public_agent_report_payload(
            case={
                "case_id": "CASE-1",
                "scenario": "product_damage",
                "scenario_label": "商品有伤审核",
                "videos": [{
                    "video_index": 1,
                    "duration_seconds": 10.0,
                    "sampled_frames": 11,
                    "sampling_strategy": "full_timeline_dense",
                    "timeline_coverage_ratio": 1.0,
                }],
                "frames": [],
                "supplemental_images": [],
            },
            sample_dir=Path("."),
            parsed={"predicted_label": "review"},
            result={},
            quality={},
            public_conclusion="本轮未形成明确事实倾向。",
            public_next_step="请结合证据继续处理。",
        )

        video = report["evidence_package"]["videos"][0]
        self.assertEqual(video["sampling_strategy"], "full_timeline_dense")
        self.assertEqual(video["timeline_coverage_ratio"], 1.0)

    def test_report_escapes_but_does_not_rewrite_evidence_terms(self):
        self.assertEqual(_h("外包装破损 <可见>"), "外包装破损 &lt;可见&gt;")

    def test_review_fallback_does_not_invent_evidence_gap_or_required_handoff(self):
        conclusion = safe_agent_conclusion({"predicted_label": "review", "confidence": 0.76}, "商品有伤审核")

        self.assertIn("未形成明确事实倾向", conclusion)
        self.assertNotIn("证据不足", conclusion)
        self.assertNotIn("VIP客服", conclusion)

    def test_report_fallbacks_do_not_invent_handoff_or_delete_reason_sentences(self):
        self.assertEqual(
            _public_verdict({"predicted_label": "review"}, "商品有伤审核"),
            "本轮未形成明确事实倾向",
        )
        self.assertNotIn("VIP客服", safe_agent_next_step(""))
        self.assertEqual(
            _safe_agent_reason("SOP 不直接拒绝；外包装可见压痕。建议结合订单处理。"),
            "SOP 不直接拒绝。外包装可见压痕。建议结合订单处理。",
        )

    def test_non_product_damage_report_hides_product_damage_policy_panel(self):
        panel = _decision_policy_panel({
            "applied": False,
            "policy_ref": "MITAKO-PD-ADVISORY@20260728.1",
            "reason": "未启用商品有伤规则分类建议。",
        })

        self.assertEqual(panel, "")

    def test_minor_report_hides_product_damage_policy_placeholder_from_summary(self):
        data = _report_data()
        report = data["agent_report"]
        report["scenario_label"] = "未成年人退款材料审核"
        report["parsed"]["minor_material_assessment"] = {"decision": "negative"}
        report["parsed"]["decision_policy_audit"] = {
            "applied": False,
            "reason": "未启用商品有伤规则分类建议。",
        }
        report["advisory_assessment"] = {
            "assessment": {
                "conclusion_code": "evidence_does_not_support_claim",
                "conclusion": "申请人与监护关系字段存在明确冲突。",
                "confidence": 0.84,
            },
            "sop_recommendation": {
                "code": "not_support_claim",
                "recommendation": "按照 SOP，当前证据倾向不支持用户诉求。",
                "basis": "未启用商品有伤规则分类建议。",
            },
            "human_review": {"level": "required"},
            "workflow_recommendation": "human_review",
            "policy": {"business_action_allowed": False},
        }

        report_html = render_public_report(data)

        self.assertIn("申请人与监护关系字段存在明确冲突", report_html)
        self.assertNotIn("未启用商品有伤规则分类建议", report_html)

    def test_material_request_report_does_not_claim_vip_review(self):
        data = _report_data()
        data["agent_report"]["advisory_assessment"] = {
            "assessment": {
                "conclusion": "当前缺少连续开箱材料，暂不能形成明确事实判断。",
                "confidence": 0.69,
                "confidence_level": "medium",
                "calibration_status": "uncalibrated_evidence_score",
            },
            "human_review": {
                "level": "not_required",
                "reason_codes": ["material_resubmission_available"],
                "recommendation": "当前可直接向用户补充收集材料，无需先占用人工审核席位。",
            },
            "workflow_recommendation": "request_more_material",
            "signals": [
                {"code": "material_gap", "severity": "warning", "effect": "请补充连续原视频。"}
            ],
            "policy": {"business_action_allowed": False},
        }

        report_html = render_public_report(data)

        self.assertIn("当前缺少连续开箱材料", report_html)
        self.assertIn("无需先占用人工审核席位", report_html)
        self.assertIn("补充连续材料", report_html)
        self.assertNotIn("证据不足，需要VIP客服复核", report_html)

    def test_report_renders_advisory_assessment_and_business_boundary(self):
        data = _report_data()
        data["agent_report"].setdefault("public_brief", {})["next_step"] = "将视觉证据摘要提交VIP客服复核。"
        data["agent_report"]["advisory_assessment"] = {
            "assessment": {
                "conclusion_code": "evidence_supports_claim",
                "conclusion": "当前视觉证据支持商品存在可见损伤。",
                "confidence": 0.88,
                "confidence_level": "high",
                "calibration_status": "uncalibrated_evidence_score",
            },
            "sop_recommendation": {
                "code": "support_claim",
                "recommendation": "按照 SOP，当前材料倾向支持用户诉求。",
                "basis": "商品损伤在送审证据中清晰可见。",
            },
            "human_review": {
                "level": "optional",
                "reason_codes": ["non_blocking_risk_signal"],
                "recommendation": "存在非阻断风险信号，甲方可按风险偏好抽检。",
            },
            "workflow_recommendation": "continue_by_customer_policy",
            "signals": [
                {
                    "code": "short_out_of_frame",
                    "severity": "warning",
                    "duration_seconds": 1.4,
                    "effect": "短暂离镜仅降低证据强度，不单独强制人工复审。",
                }
            ],
            "policy": {
                "policy_ref": "MITAKO-ADVISORY-20260723@1",
                "advisory_only": True,
                "business_action_allowed": False,
                "boundary": "本服务负责输出明确的证据结论和SOP处理建议；业务动作由甲方系统执行，是否需要人工复核由单独的复核等级决定。",
            },
        }

        report_html = render_public_report(data)

        self.assertIn("先看结论、材料状态和下一步", report_html)
        self.assertIn("证据结论", report_html)
        self.assertIn("当前材料倾向支持用户诉求", report_html)
        self.assertIn("存在非阻断风险信号，甲方可按风险偏好抽检", report_html)
        self.assertNotIn("按 SOP 审核倾向继续处理", report_html)
        self.assertIn("短暂离镜仅降低证据强度", report_html)
        self.assertIn("不是客观正确率", report_html)
        self.assertIn("业务动作由甲方系统执行，是否需要人工复核由单独的复核等级决定", report_html)
        self.assertEqual(report_html.count("存在非阻断风险信号，甲方可按风险偏好抽检"), 1)
        self.assertNotIn("提交VIP客服复核", report_html)

    def test_severe_structural_follow_up_is_not_rendered_as_claim_support(self):
        data = _report_data()
        data["agent_report"]["advisory_assessment"] = {
            "assessment": {
                "conclusion_code": "severe_structural_damage_follow_up",
                "conclusion": "严重结构问题已确认，建议重点跟进；交易归属、成因和责任待确认。",
                "confidence": 0.93,
            },
            "sop_recommendation": {
                "code": "further_assessment",
                "recommendation": "严重结构问题已确认，应重点跟进；交易归属、成因和责任仍待确认。",
                "basis": "送审证据中可见严重结构损坏。",
            },
            "human_review": {"level": "optional", "recommendation": ""},
            "workflow_recommendation": "continue_by_customer_policy",
            "policy": {},
        }

        html = render_public_report(data)
        first_layer = html.split('<details class="summary-review-details">', 1)[0]

        self.assertIn("严重结构问题已确认", first_layer)
        self.assertIn("交易归属、成因和责任待确认", first_layer)
        self.assertNotIn("现有证据支持用户诉求", first_layer)

    def test_report_prioritizes_customer_evidence_attention(self):
        data = _report_data()
        data["agent_report"]["advisory_assessment"] = {
            "assessment": {
                "conclusion_code": "evidence_inconclusive",
                "conclusion": "当前证据仍有一项关键分歧。",
                "confidence": 0.72,
                "confidence_level": "medium",
                "calibration_status": "uncalibrated_evidence_score",
            },
            "human_review": {
                "level": "required",
                "reason_codes": ["evidence_conflict"],
                "recommendation": "请授权人员核对原始证据。",
            },
            "workflow_recommendation": "human_review",
            "signals": [],
            "evidence_attention": {
                "level": "red",
                "headline": "关键证据存在冲突，先核对分歧再处理。",
                "customer_focus": ["先看主视频损伤事实，再看开箱合规与动作前后链。"],
                "disagreements": ["主视频与补充图片对损伤存在性的结论不同。"],
                "missing_evidence": ["缺少同一商品同一部位的连续动作前后证据。"],
            },
            "policy": {"business_action_allowed": False},
        }

        report_html = render_public_report(data)

        self.assertIn("复核顺序", report_html)
        self.assertIn("优先核对", report_html)
        self.assertIn("证据分歧", report_html)
        self.assertIn("材料缺口", report_html)
        self.assertIn("关键证据存在冲突", report_html)
        self.assertIn("同一商品同一部位", report_html)
        details_start = report_html.index('<details class="summary-review-details">')
        details_end = report_html.index("</details>", details_start)
        self.assertGreater(report_html.index("复核顺序"), details_start)
        self.assertLess(report_html.index("复核顺序"), details_end)

    def test_retired_minor_payment_process_signal_is_not_rendered(self):
        data = _report_data()
        data["agent_report"]["advisory_assessment"] = {
            "assessment": {"conclusion": "需补充支付过程说明。", "confidence": 0.72},
            "human_review": {"level": "not_required", "reason_codes": ["material_resubmission_available"]},
            "workflow_recommendation": "request_more_material",
            "signals": [{
                "code": "minor_payment_process_evidence_gap",
                "severity": "warning",
                "effect": "请补充支付密码来源和监护人发现消费过程。",
            }],
            "policy": {"business_action_allowed": False},
        }

        report_html = render_public_report(data)

        self.assertNotIn("请补充支付密码来源和监护人发现消费过程", report_html)
        self.assertNotIn("minor_payment_process_evidence_gap", report_html)

    def test_report_renders_evidence_boundaries_and_links_gallery_media(self):
        report_html = render_public_report(_report_data())

        self.assertIn("客服审核摘要", report_html)
        self.assertIn("判断依据", report_html)
        self.assertIn("建议下一步", report_html)
        self.assertIn("关键证据", report_html)
        self.assertIn('<details class="panel technical-details">', report_html)

        for heading in ("审核Agent采信的证据", "反证与可疑帧", "问题时间点", "置信度分解与口径", "损伤来源与发生阶段", "主体连续性与离镜时间轴", "置信度理由", "材料缺口", "模型局限"):
            self.assertIn(heading, report_html)
        self.assertNotIn("应发与视频展示清单对账", report_html)

        self.assertIn("第 11 帧可见表面压痕", report_html)
        self.assertIn("该时间点反光较强", report_html)
        self.assertIn("画面出现短暂遮挡", report_html)
        self.assertIn("商品离开镜头", report_html)
        self.assertIn("支持证据清晰，但关键开箱阶段缺失", report_html)
        self.assertIn("缺少未拆封包装的连续开箱画面", report_html)
        self.assertIn("物流运输阶段", report_html)
        self.assertIn("缺少损伤形成前后的连续对比", report_html)
        self.assertIn("第 11 帧首次清晰看到压痕", report_html)
        self.assertIn("最长连续离镜", report_html)
        self.assertIn("3.5 秒", report_html)
        self.assertIn("未确认重新入镜同一性", report_html)
        self.assertIn("离镜前 / 离镜起点 / 重新入镜证据", report_html)
        self.assertIn("本报告只说明送审证据支持什么结论", report_html)
        self.assertNotIn("反光可能影响细微划痕判断", report_html)
        self.assertIn("尚未使用独立留出集校准", report_html)

    def test_report_renders_media_preflight_execution_as_readable_technical_text(self):
        data = _report_data()
        data["media_preflight_execution"] = {
            "status": "completed",
            "video": {
                "submitted_source": "quality_proxy",
                "delivery": "https_url",
                "native_sampling_fps": 1.0,
                "codec_profile": "vp9_webm",
                "source_width": 3840,
                "source_height": 2160,
                "submitted_width": 2560,
                "submitted_height": 1440,
            },
            "images": {
                "representation": "individual_webp",
                "attempted_count": 4,
                "prepared_count": 3,
                "failed_count": 1,
                "max_long_edge": 1920,
                "collage_used": False,
            },
            "frame_fallback": {"used": False},
        }

        report_html = render_public_report(data)

        self.assertIn("送审前媒体处理", report_html)
        self.assertIn("保真代理", report_html)
        self.assertIn("HTTPS 地址", report_html)
        self.assertIn("1 帧/秒", report_html)
        self.assertIn("逐张 WebP", report_html)
        self.assertIn("另有 1 张未能安全解码", report_html)
        self.assertNotIn("quality_proxy", report_html)
        self.assertNotIn("https_url", report_html)
        self.assertNotIn("vp9_webm", report_html)

    def test_report_renders_every_persisted_review_video_without_mislabeling_url_delivery(self):
        data = _report_data()
        data["media_preflight_execution"] = {
            "status": "completed",
            "videos": [
                {
                    "video_index": 1,
                    "submitted_source": "quality_proxy",
                    "delivery": "inline_data",
                    "source_width": 3840,
                    "source_height": 2160,
                    "submitted_width": 2560,
                    "submitted_height": 1440,
                },
                {
                    "video_index": 2,
                    "submitted_source": "quality_proxy",
                    "delivery": "file_uri",
                    "source_width": 1080,
                    "source_height": 1920,
                    "submitted_width": 1080,
                    "submitted_height": 1920,
                },
            ],
            "frame_fallback": {"used": False},
        }

        report_html = render_public_report(data)

        self.assertIn("视频 1：使用保真代理，通过内联上传送审", report_html)
        self.assertIn("视频 2：使用保真代理，通过HTTPS 地址送审", report_html)
        self.assertIn("3840×2160 保真处理为 2560×1440", report_html)
        self.assertIn("1080×1920 保真处理为 1080×1920", report_html)
        self.assertNotIn("file_uri", report_html)

    def test_report_identifies_traceable_warehouse_final_as_resolution_basis(self):
        data = _report_data()
        data["agent_report"]["scenario"] = "missing_item"
        data["agent_report"]["scenario_label"] = "漏发货审核"
        reconciliation = data["agent_report"]["parsed"]["fulfillment_reconciliation"]
        reconciliation.update(
            {
                "resolution_basis": "warehouse_verification",
                "warehouse_verification": {
                    "status": "confirmed_not_missing",
                    "source": "customer_warehouse",
                    "verification_ref": "WH-CHECK-1",
                },
                "decision_boundary": "甲方已提供可追溯的仓库终核，历史待核实备注不覆盖该终态。",
            }
        )

        report_html = render_public_report(data)

        self.assertIn("仓库终核", report_html)
        self.assertIn("确认未漏发", report_html)
        self.assertIn("WH-CHECK-1", report_html)
        self.assertIn("证据分数表示本轮证据充分程度，不是客观正确率", report_html)
        self.assertNotIn("损伤来源与发生阶段", report_html)
        self.assertIn("抽帧首尾覆盖", report_html)
        self.assertIn("包裹开启过程完整性", report_html)
        self.assertIn("包裹与实收展示连续性", report_html)
        self.assertIn("媒体技术取证", report_html)
        self.assertIn(
            '<p class="fine-print"><b>说明：</b>视频从头拍到尾，不代表应发与实收已经核对完成。',
            report_html,
        )
        self.assertIn("系统会分别检查包裹开启过程、实收展示、订单基线和文件异常", report_html)
        self.assertNotIn("抽帧覆盖、媒体技术取证、开箱过程和商品连续性是四个独立维度", report_html)
        self.assertNotIn("requires_media_forensics", report_html)
        self.assertIn("SOP 规则判定说明", report_html)
        self.assertNotIn("MITAKO-PD-20260720@2", report_html)
        self.assertIn("有效展示窗口内存在未解决的离镜", report_html)
        self.assertNotIn("争议商品离镜时间超过策略阈值", report_html)
        self.assertIn("补充证据关联尚未解决", report_html)

    def test_product_report_describes_continuity_without_accusing_customer(self):
        report_html = render_public_report(_report_data())

        self.assertIn("展示连续性风险", report_html)
        self.assertIn(">中<", report_html)
        self.assertNotIn("疑似调包风险", report_html)
        self.assertNotIn("剪辑/调包风险", report_html)
        self.assertNotIn(">medium<", report_html)

    def test_wrong_and_missing_reports_use_scene_specific_fulfillment_language(self):
        for scenario, scene_label, heading in (
            ("wrong_item", "发错货审核", "发错货应收与实收核对"),
            ("missing_item", "漏发货审核", "漏发货应发与实收核对"),
        ):
            with self.subTest(scenario=scenario):
                data = _report_data()
                data["agent_report"]["scenario"] = scenario
                data["agent_report"]["scenario_label"] = scene_label
                data["agent_report"]["parsed"].pop("damage_causality_assessment", None)
                data["agent_report"]["parsed"].pop("claim_fact_assessment", None)

                report_html = render_public_report(data)

                self.assertIn('class="fulfillment-report scene-' + scenario.replace("_", "-") + '"', report_html)
                self.assertIn(heading, report_html)
                self.assertNotIn("商品连续性分数", report_html)
                self.assertNotIn("疑似调包风险", report_html)
                self.assertNotIn("伤情首次出现", report_html)
                self.assertNotIn("损伤来源与发生阶段", report_html)

    def test_business_material_scenario_overrides_legacy_technical_scenario(self):
        data = _report_data()
        data["agent_report"]["scenario"] = "video_unboxing"
        data["agent_report"]["scenario_label"] = "发错货审核"
        data["material_readiness"] = {
            "scenario": "wrong_item",
            "status": "incomplete",
            "confidence": 0.9,
            "reason": "同包裹证据尚未闭环。",
            "checklist": [],
            "missing_items": ["同包裹证据"],
            "warnings": [],
        }

        report_html = render_public_report(data)

        self.assertIn('class="fulfillment-report scene-wrong-item"', report_html)
        self.assertIn("发错货应收与实收核对", report_html)
        self.assertIn("身份定义属性", report_html)

    def test_missing_item_transition_to_wrong_item_uses_wrong_item_public_report(self):
        data = _report_data()
        data["agent_report"]["scenario"] = "missing_item"
        data["agent_report"]["scenario_label"] = "漏发货审核"
        data["agent_report"]["parsed"].pop("damage_causality_assessment", None)
        data["agent_report"]["parsed"].pop("claim_fact_assessment", None)
        data["agent_report"]["parsed"]["fulfillment_reconciliation"]["scenario_transition"] = "wrong_item"

        report_html = render_public_report(data)

        self.assertIn('class="fulfillment-report scene-wrong-item"', report_html)
        self.assertIn("发错货应收与实收核对", report_html)
        self.assertNotIn("漏发货应发与实收核对", report_html)

    def test_fulfillment_observation_refs_are_visible_as_key_evidence(self):
        data = _report_data()
        data["agent_report"]["scenario"] = "wrong_item"
        data["agent_report"]["scenario_label"] = "发错货审核"
        parsed = data["agent_report"]["parsed"]
        parsed["adopted_evidence"] = []
        parsed["supporting_evidence"] = []
        parsed["fulfillment_reconciliation"]["observed_items"] = [{
            "product_name": "实收摆件",
            "evidence_refs": [{
                "asset_ref": "native_video_1",
                "timestamp": "01:41",
                "field": "observed_item",
                "fact": "开箱取出并展示第一件实收摆件。",
            }],
        }]

        report_html = render_public_report(data)

        self.assertIn("开箱取出并展示第一件实收摆件", report_html)
        self.assertNotIn("审核Agent没有给出可采信证据", report_html)

    def test_fulfillment_reports_show_package_evidence_from_reconciliation(self):
        for scenario, scene_label, evidence_heading in (
            ("wrong_item", "发错货审核", "同包裹证据"),
            ("missing_item", "漏发货审核", "分包与内容展示证据"),
        ):
            with self.subTest(scenario=scenario):
                data = _report_data()
                data["agent_report"]["scenario"] = scenario
                data["agent_report"]["scenario_label"] = scene_label
                reconciliation = data["agent_report"]["parsed"]["fulfillment_reconciliation"]
                reconciliation["package_observations"] = [{
                    "package_ref": "PKG-TRACE-UNIQUE-0813",
                    "opening_complete": True,
                    "all_contents_laid_out": True,
                    "evidence_refs": [{
                        "asset_ref": "native_video_1",
                        "timestamp": "00:42.00",
                        "fact": "该包裹已连续拆开，并完整铺开展示其中全部实收商品。",
                    }],
                }]

                report_html = render_public_report(data)

                self.assertIn(evidence_heading, report_html)
                self.assertIn("PKG-TRACE-UNIQUE-0813", report_html)
                self.assertIn("该包裹已连续拆开，并完整铺开展示其中全部实收商品", report_html)

    def test_wrong_item_report_separates_identity_and_descriptive_differences(self):
        data = _report_data()
        data["agent_report"]["scenario"] = "wrong_item"
        data["agent_report"]["scenario_label"] = "发错货审核"
        reconciliation = data["agent_report"]["parsed"]["fulfillment_reconciliation"]
        reconciliation["observed_items"] = [{
            "product_name": "角色圆卡",
            "item_role": "随商品附带圆卡",
            "series": "同系列",
            "edition": "首发版",
            "physical_form": "圆形卡片",
            "included_parts": ["圆卡"],
            "visible_identifiers": ["角色图案"],
            "descriptive_dimensions": ["页面标注尺寸与肉眼测量存在差异"],
            "package_ref": "PKG-1",
            "evidence_refs": [],
        }]

        report_html = render_public_report(data)

        self.assertIn("身份定义属性", report_html)
        self.assertIn("圆形卡片", report_html)
        self.assertIn("描述性差异", report_html)
        self.assertIn("页面标注尺寸与肉眼测量存在差异", report_html)
        self.assertNotIn("尺寸差异已确认发错", report_html)

    def test_missing_report_explains_static_three_image_route_without_claiming_missing(self):
        data = _report_data()
        data["agent_report"]["scenario"] = "missing_item"
        data["agent_report"]["scenario_label"] = "漏发货审核"
        reconciliation = data["agent_report"]["parsed"]["fulfillment_reconciliation"]
        reconciliation.update({
            "evidence_route": "static_three_images",
            "warehouse_check": {"state": "pending", "outcome": None},
            "user_materials_complete": True,
            "evidence_sufficiency": "insufficient",
            "verdict": "indeterminate",
            "decision_boundary": "用户静态三类材料已齐全，下一步应由人工客服读取仓库实发明细进行双重核验。",
        })

        report_html = render_public_report(data)

        self.assertIn("静态三类材料", report_html)
        self.assertIn("用户材料已齐全", report_html)
        self.assertIn("读取仓库实发明细", report_html)
        self.assertNotIn("静态三图已确认漏发", report_html)

    def test_missing_report_explains_trusted_product_composition_resolution(self):
        data = _report_data()
        data["agent_report"]["scenario"] = "missing_item"
        data["agent_report"]["scenario_label"] = "漏发货审核"
        reconciliation = data["agent_report"]["parsed"]["fulfillment_reconciliation"]
        reconciliation.update({
            "evidence_route": "not_required",
            "resolution_basis": "trusted_expected_item_resolution",
            "user_materials_complete": False,
            "evidence_sufficiency": "sufficient",
            "verdict": "matched",
            "product_composition_resolution": {
                "claimed_item": "标题中的非独立应发描述",
                "resolution_ref": "PRODUCT-COMPOSITION-568689",
                "reason": "订单商品本体就是摆件，该描述不是另一件独立商品。",
            },
            "decision_boundary": "可信订单和商品构成规则已消歧。",
        })

        report_html = render_public_report(data)

        self.assertIn("受信订单与商品规则", report_html)
        self.assertIn("该描述不是另一件独立商品", report_html)
        self.assertIn("PRODUCT-COMPOSITION-568689", report_html)
        self.assertNotIn("请补开箱视频", report_html)

    def test_missing_report_separates_user_evidence_route_from_resolution_basis(self):
        data = _report_data()
        data["agent_report"]["scenario"] = "missing_item"
        data["agent_report"]["scenario_label"] = "漏发货审核"
        data["agent_report"]["parsed"]["fulfillment_reconciliation"] = {
            "baseline_version": "ORDER-V1",
            "evidence_route": "static_three_images",
            "resolution_basis": "warehouse_verification",
            "user_materials_complete": True,
            "warehouse_verification": {
                "status": "confirmed_not_missing",
                "verification_ref": "WH-CHECK-1",
            },
            "expected_items": [],
            "observed_items": [],
            "suspected_missing_items": [],
            "unconfirmed_items": [],
        }

        html = render_public_report(data)

        self.assertIn("用户证据路线", html)
        self.assertIn("静态三类材料", html)
        self.assertIn("最终事实依据", html)
        self.assertIn("仓库终核", html)

    def test_missing_report_renders_paper_self_check_only_as_post_decision_reminder(self):
        data = _report_data()
        data["agent_report"]["scenario"] = "missing_item"
        data["agent_report"]["scenario_label"] = "漏发货审核"
        reconciliation = data["agent_report"]["parsed"]["fulfillment_reconciliation"]
        reconciliation["post_decision_reminders"] = [{
            "code": "paper_item_layer_self_check",
            "label": "纸类商品补充自查",
            "message": "请再检查纸类商品是否叠放、藏在背面或夹层中。",
            "affects_verdict": False,
        }]

        report_html = render_public_report(data)

        self.assertIn("确认漏发后的补充提醒", report_html)
        self.assertIn("叠放、藏在背面或夹层", report_html)
        self.assertIn("不改变本轮证据结论", report_html)

    def test_evidence_json_string_is_rendered_as_readable_fact(self):
        data = _report_data()
        parsed = data["agent_report"]["parsed"]
        parsed["adopted_evidence"] = [{
            "source_type": "video_frame",
            "video_index": 1,
            "timestamp": "00:08.00",
            "fact": '{"field":"issue_visible","fact":"摆件表面可见连续划痕","confidence":0.91}',
        }]

        report_html = render_public_report(data)

        self.assertIn("摆件表面可见连续划痕", report_html)
        self.assertNotIn('&quot;field&quot;:&quot;issue_visible&quot;', report_html)

    def test_minor_process_video_does_not_render_fulfillment_video_template(self):
        data = _report_data()
        data["agent_report"]["scenario"] = "minor_refund"
        data["agent_report"]["scenario_label"] = "未成年人退款资料审核"
        data["agent_report"]["parsed"]["minor_material_assessment"] = {
            "process_evidence": [{
                "video_index": 1,
                "global_frame_index": 11,
                "timestamp": "00:04.00",
                "process_type": "document_capture",
                "evidence_quality": "clear",
            }],
        }

        report_html = render_public_report(data)

        self.assertIn("过程视频证据", report_html)
        self.assertIn("资料拍摄过程", report_html)
        for forbidden in (
            "包裹开启过程完整性",
            "包裹与实收展示连续性",
            "应发与实收已经核对完成",
            "视频查看密度",
        ):
            self.assertNotIn(forbidden, report_html)

    def test_report_hides_source_breakdown_when_the_model_did_not_return_one(self):
        data = _report_data()
        damage = data["agent_report"]["parsed"]["damage_causality_assessment"]
        damage.pop("evidence_source_summary", None)

        report_html = render_public_report(data)

        self.assertNotIn("未完成主视频审查", report_html)
        self.assertNotIn("补充图片 0 张", report_html)
        self.assertNotIn("应发与视频展示清单对账", report_html)

        # 每个地址应分别出现在证据卡和完整画廊的预览属性、图片标签中。
        for media_url in (
            "/media/frame-index.jpg",
            "/media/image-index.jpg",
            "/media/timestamp.jpg",
            "/media/file-name.jpg",
            "/media/issue-time.jpg",
        ):
            expected_count = {
                "/media/frame-index.jpg": 12,
                "/media/image-index.jpg": 6,
                "/media/timestamp.jpg": 8,
                "/media/issue-time.jpg": 8,
            }.get(media_url, 4)
            self.assertGreaterEqual(report_html.count(f'src="{media_url}"'), expected_count, media_url)

        self.assertNotIn("画面正常", report_html)
        self.assertNotIn("internal-provider-name", report_html)
        self.assertNotIn("SECRET-KEY-MUST-NOT-LEAK", report_html)
        self.assertNotIn("不得出现在公开报告中的内部提示词", report_html)

    def test_report_marks_speed_unknown_and_out_of_frame_duration_as_sampled_estimate(self):
        data = _report_data()
        data["agent_report"]["parsed"]["video_audit_conclusion"]["playback_speed"] = "accelerated"
        continuity = data["agent_report"]["parsed"]["object_continuity_assessment"]
        continuity.update({
            "longest_out_of_frame_lower_bound_seconds": 3.0,
            "longest_out_of_frame_upper_bound_seconds": 6.0,
        })
        continuity["tracked_subjects"][0]["out_of_frame_events"][0].update({
            "duration_basis": "sampled_source_timestamps",
            "duration_is_exact": False,
            "duration_lower_bound_seconds": 3.0,
            "duration_upper_bound_seconds": 6.0,
            "sampling_resolution_seconds": 2.0,
        })
        data["media_forensics"] = {
            "assets": [{
                "file": "audit.mp4",
                "playback_speed_assessment": {
                    "status": "unknown",
                    "constant_speed_multiplier": None,
                    "reason_code": "source_clock_reference_unavailable",
                    "reason": "重编码视频缺少拍摄现场时钟或原始素材基准，不能可靠反推恒定加速倍数。",
                    "is_model_inference": False,
                },
            }]
        }

        report_html = render_public_report(data)

        self.assertIn("恒定倍速：未知", report_html)
        self.assertIn("画面节奏判断：疑似加速", report_html)
        self.assertIn("不能可靠反推恒定加速倍数", report_html)
        self.assertIn("非模型推断", report_html)
        self.assertIn("采样边界估计", report_html)
        self.assertIn("3.0 至 6.0 秒", report_html)
        self.assertIn("采样分辨率 2.0 秒", report_html)

    def test_report_explains_orange_speed_signal_without_dense_retry(self):
        data = _report_data()
        video = data["agent_report"]["parsed"]["video_audit_conclusion"]
        video.update({
            "playback_speed": "accelerated",
            "sampling_fps": 1.0,
            "speed_review_impact": {
                "status": "uncertain",
                "critical_evidence_observable": False,
                "affected_review_items": ["opening_action", "issue_first_visible"],
            },
        })
        report_html = render_public_report(data)

        self.assertIn("橙色风险", report_html)
        self.assertIn("请客服只回看对应原视频片段", report_html)
        self.assertNotIn("2 FPS", report_html)
        self.assertIn("拆封动作", report_html)
        self.assertIn("伤情首次出现", report_html)

    def test_report_keeps_unknown_speed_as_visible_yellow_signal(self):
        data = _report_data()
        video = data["agent_report"]["parsed"]["video_audit_conclusion"]
        video.update({
            "playback_speed": "unknown",
            "sampling_fps": 4.0,
            "speed_review_impact": {
                "status": "uncertain",
                "critical_evidence_observable": False,
                "affected_review_items": ["claimed_item_continuity"],
            },
        })

        report_html = render_public_report(data)

        self.assertIn("无法可靠判断视频是否加速", report_html)
        self.assertIn("请客服回看原视频", report_html)
        self.assertIn("按 4 FPS 通看全片", report_html)
        self.assertNotIn("按 1 FPS 通看全片", report_html)

    def test_unknown_internal_status_uses_safe_public_label(self):
        self.assertEqual(_public_status("vendor_internal_pending"), "待确认")

    def test_report_lists_each_opening_video_requirement(self):
        data = _report_data()
        data["agent_report"]["parsed"]["video_audit_conclusion"]["opening_video_compliance"] = {
            "sealed_start": True,
            "waybill_visible": False,
            "single_take_continuity": True,
            "issue_visible_in_continuous_opening": False,
        }

        report_html = render_public_report(data)

        self.assertIn("主开箱视频硬要求", report_html)
        self.assertIn("封箱起始：</b>符合", report_html)
        self.assertIn("面单可核验：</b>不符合", report_html)
        self.assertIn("一镜到底连续拆封：</b>符合", report_html)
        self.assertIn("伤点在连续开箱中清晰展示：</b>不符合", report_html)

    def test_report_highlights_initial_opening_video_evidence_without_fake_score(self):
        data = _report_data()
        data["agent_report"]["parsed"]["opening_video_evidence"] = {
            "present": False,
            "status": "yellow",
            "confidence": 0.88,
            "reason": "未从封箱状态连续记录到初次拆开包裹。",
        }

        report_html = render_public_report(data)

        self.assertIn("初次开箱视频证据", report_html)
        self.assertIn("黄标", report_html)
        self.assertIn("88%", report_html)
        self.assertIn("未从封箱状态连续记录到初次拆开包裹", report_html)
        self.assertNotIn("0.82", report_html)

    def test_report_renders_visible_facts_and_prioritizes_issue_evidence(self):
        data = _report_data()
        data["agent_report"]["parsed"]["adopted_evidence"] = [
            {
                "field": field,
                "video_index": 1,
                "timestamp": f"00:0{index}",
                "visible_facts": fact,
                "asset_ref": "native_video_1",
            }
            for index, (field, fact) in enumerate(
                (
                    ("sealed_start", "快递外箱封口未拆"),
                    ("waybill_visible", "快递面单清晰可见"),
                    ("continuous", "开箱过程一镜到底"),
                    ("has_edit", "未发现剪辑痕迹"),
                    ("has_offscreen", "商品展示期间未离镜"),
                    ("has_speed_change", "视频速度无法可靠确认"),
                    ("issue_visible", "02:25 可见文件夹表面划痕"),
                )
            )
        ]

        report_html = render_public_report(data)
        key_evidence_html = report_html.split("<h3>关键证据</h3>", 1)[1]

        self.assertIn("02:25 可见文件夹表面划痕", key_evidence_html)
        self.assertNotIn("{'field':", key_evidence_html)
        self.assertLess(
            key_evidence_html.index("02:25 可见文件夹表面划痕"),
            key_evidence_html.index("快递外箱封口未拆"),
        )

    def test_unknown_speed_uses_plain_small_print_limitation(self):
        data = _report_data()
        data["agent_report"]["parsed"]["video_audit_conclusion"].update({
            "playback_speed": "unknown",
            "sampling_fps": 1.0,
            "speed_review_impact": {"status": "uncertain"},
        })

        report_html = render_public_report(data)

        self.assertIn('class="fine-print speed-limit"', report_html)
        self.assertIn("目前没有稳定方法确认原视频是否加速", report_html)

    def test_report_hides_opening_requirements_when_every_field_is_unknown(self):
        data = _report_data()
        data["agent_report"]["parsed"]["video_audit_conclusion"]["opening_video_compliance"] = {
            "sealed_start": None,
            "waybill_visible": None,
            "single_take_continuity": None,
            "issue_visible_in_continuous_opening": None,
            "result": "indeterminate",
        }

        report_html = render_public_report(data)

        self.assertNotIn("主开箱视频硬要求", report_html)

    def test_report_does_not_require_two_fps_for_material_speed_signal(self):
        data = _report_data()
        data["agent_report"]["parsed"]["video_audit_conclusion"].update({
            "playback_speed": "accelerated",
            "sampling_fps": 1.0,
            "speed_review_impact": {"status": "material", "affected_review_items": ["opening_action"]},
        })

        report_html = render_public_report(data)

        self.assertIn("不把播放速度本身写成材料不合规", report_html)
        self.assertNotIn("2 FPS", report_html)

    def test_report_does_not_assume_observable_when_speed_impact_is_missing(self):
        data = _report_data()
        data["agent_report"]["parsed"]["video_audit_conclusion"].update({
            "playback_speed": "accelerated",
            "sampling_fps": 1.0,
        })
        data["agent_report"]["parsed"]["video_audit_conclusion"].pop("speed_review_impact", None)

        report_html = render_public_report(data)

        self.assertIn("尚未形成速度影响结论", report_html)
        self.assertNotIn("关键证据仍可判断", report_html)

    def test_report_discloses_partial_specialized_coverage_without_overriding_verdict(self):
        data = _report_data()
        data["agent_report"]["parsed"].update({
            "pass_integrity_status": "partial_specialized",
            "specialized_pass_warning": "连续性专项存在局部缺口；缺口只使对应证据维度保持未知。",
        })

        report_html = render_public_report(data)

        self.assertIn("缺口只使对应证据维度保持未知", report_html)
        self.assertIn("本轮未形成明确事实倾向", report_html)
        self.assertNotIn("证据不足，需要VIP客服复核", report_html)

    def test_multi_video_frame_mapping_uses_video_index_and_rejects_ambiguous_fallback(self):
        gallery = {
            "frames": [
                {"video_index": 1, "global_frame_index": 7, "timestamp": "00:07.00", "url": "/media/video-1-frame-7.jpg"},
                {"video_index": 2, "global_frame_index": 7, "timestamp": "00:07.00", "url": "/media/video-2-frame-7.jpg"},
            ]
        }
        html = _evidence_items(
            [{"source_type": "video_frame", "video_index": 2, "global_frame_index": 7, "fact": "第二段视频证据"}],
            gallery,
        )
        self.assertIn('/media/video-2-frame-7.jpg', html)
        self.assertNotIn('/media/video-1-frame-7.jpg', html)

        ambiguous = _evidence_items(
            [{"source_type": "video_frame", "global_frame_index": 7, "fact": "未声明视频编号"}],
            gallery,
        )
        self.assertNotIn('/media/video-1-frame-7.jpg', ambiguous)
        self.assertNotIn('/media/video-2-frame-7.jpg', ambiguous)

        ambiguous_timestamp = _evidence_items(
            [{"source_type": "video_frame", "timestamp": "00:07.00", "fact": "未声明视频编号"}],
            gallery,
        )
        self.assertNotIn('/media/video-1-frame-7.jpg', ambiguous_timestamp)
        self.assertNotIn('/media/video-2-frame-7.jpg', ambiguous_timestamp)

    def test_native_timestamp_evidence_links_to_original_video_without_raw_json(self):
        gallery = {
            "videos": [{"video_index": 1, "url": "/media/full-review.mp4"}],
            "frames": [],
        }
        html = _evidence_items(
            [{
                "source_type": "video_frame",
                "video_index": 1,
                "timestamp": "00:12.50",
                "visible_facts": [
                    {"subject": "争议商品", "fact": "面具表面的红痕清晰可见"},
                    {"subject": "快递外箱", "state": "封口完整"},
                ],
            }],
            gallery,
        )

        self.assertIn("面具表面的红痕清晰可见", html)
        self.assertIn("快递外箱：封口完整", html)
        self.assertNotIn("{'subject'", html)
        self.assertIn('data-preview-kind="video"', html)
        self.assertIn('data-preview-seconds="12.500"', html)
        self.assertIn('/media/full-review.mp4#t=12.500', html)

    def test_supplemental_image_preview_names_include_the_image_index(self):
        gallery = {
            "images": [
                {"image_index": 1, "url": "/media/material-1.jpg"},
                {"image_index": 2, "url": "/media/material-2.jpg"},
            ]
        }

        html = _evidence_items(
            [
                {"source_type": "supplemental_image", "image_index": 1, "fact": "身份证明正面"},
                {"source_type": "supplemental_image", "image_index": 2, "fact": "身份证明反面"},
            ],
            gallery,
        )

        self.assertIn('aria-label="预览查看补充图片 1"', html)
        self.assertIn('aria-label="预览查看补充图片 2"', html)

        gallery_html = _gallery_items(gallery["images"], "补充图片")
        self.assertIn('aria-label="预览补充图片：补充图片 1"', gallery_html)
        self.assertIn('aria-label="预览补充图片：补充图片 2"', gallery_html)

    def test_report_humanizes_nested_summary_values_without_raw_structures(self):
        data = _report_data()
        parsed = data["agent_report"]["parsed"]
        parsed["overall_audit"]["core_reason"] = {
            "subject": "争议商品",
            "fact": "表面划痕在近景中可见。",
            "debug": {"internal": True},
        }
        parsed["material_gaps"] = [{
            "subject": "开箱视频",
            "reason": "面单区域仍需回看。",
            "internal_code": "RAW-GAP-01",
        }]

        html = render_public_report(data)

        self.assertIn("争议商品：表面划痕在近景中可见。", html)
        self.assertIn("开箱视频：面单区域仍需回看。", html)
        self.assertNotIn("{'subject'", html)
        self.assertNotIn("RAW-GAP-01", html)
        self.assertNotIn("debug", html)

    def test_report_omits_empty_score_and_duplicate_sop_summary(self):
        data = _report_data()
        parsed = data["agent_report"]["parsed"]
        parsed["confidence"] = None
        parsed["overall_audit"]["confidence"] = None

        html = render_public_report(data)

        self.assertNotIn("证据分数 None", html)
        self.assertNotIn("<small>证据分数</small>", html)
        self.assertNotIn("<small>SOP 处理建议</small>", html)

    def test_report_omits_empty_optional_sections(self):
        data = _report_data()
        parsed = data["agent_report"]["parsed"]
        parsed["material_gaps"] = []
        parsed["challenging_evidence"] = []
        parsed["frame_findings"] = []
        parsed["issue_timestamps"] = []
        data["agent_report"]["evidence_attention"] = {}

        html = render_public_report(data)

        self.assertNotIn("<h3>需要补什么</h3>", html)
        self.assertNotIn("反证与可疑帧：未发现", html)
        self.assertNotIn("问题时间点：未发现", html)
        self.assertNotIn("查看其他风险信号", html)
        self.assertIn('class="fine-print summary-boundary"', html)

    def test_report_hides_empty_attention_columns_and_duplicate_reason(self):
        data = _report_data()
        report = data["agent_report"]
        parsed = report["parsed"]
        repeated_reason = "连续开箱画面已清楚展示伤点。"
        report["advisory_assessment"] = {
            "assessment": {
                "conclusion_code": "evidence_supports_claim",
                "conclusion": repeated_reason,
                "confidence": 0.88,
            },
            "human_review": {"level": "not_required"},
            "workflow_recommendation": "continue_by_customer_policy",
            "evidence_attention": {
                "level": "green",
                "headline": "证据链可直接复核。",
                "customer_focus": ["回看伤点首次清晰出现的时间点。"],
                "disagreements": [],
                "missing_evidence": [],
            },
            "policy": {},
        }
        parsed["overall_audit"]["core_reason"] = repeated_reason
        parsed["confidence_reason"] = repeated_reason

        html = render_public_report(data)

        self.assertIn("88%", html)
        self.assertNotIn("<small>证据分数</small><b>0.88</b>", html)
        self.assertNotIn("<h4>证据分歧</h4>", html)
        self.assertNotIn("<h4>材料缺口</h4>", html)
        self.assertNotIn("<h3>判断依据</h3>", html)

    def test_report_shows_scene_material_readiness_in_summary_and_details(self):
        labels = {
            "product_damage": "当前商品有伤场景下的用户材料是否齐全",
            "wrong_item": "当前发错货场景下的用户材料是否齐全",
            "missing_item": "当前漏发货场景下的用户材料是否齐全",
            "minor_refund": "当前未成年人退款场景下的用户材料是否齐全",
        }
        for scenario, title in labels.items():
            with self.subTest(scenario=scenario):
                data = _report_data()
                data["agent_report"]["scenario"] = scenario
                data["agent_report"]["scenario_label"] = title.removeprefix("当前").removesuffix("场景下的用户材料是否齐全") + "审核"
                data["material_readiness"] = {
                    "scenario": scenario,
                    "status": "complete",
                    "confidence": 0.93,
                    "reason": "本场景必要材料已形成可回看的审核证据。",
                    "checklist": [{
                        "label": "场景必要材料",
                        "required": True,
                        "status": "present",
                        "reason": "已核对。",
                    }],
                    "missing_items": [],
                    "warnings": ["材料齐全性不等于事实结论。"],
                }
                data["input_readiness"] = {
                    "review_inventory": {
                        "received_asset_count": 2,
                        "media_counts": {"video": 1, "image": 1, "document": 0},
                    }
                }

                html = render_public_report(data)

                self.assertIn(title, html)
                self.assertIn("<b>齐全</b>", html)
                self.assertIn("场景必要材料", html)
                self.assertIn("93%", html)
                self.assertIn("材料状态确定性 93%", html)
                self.assertIn("系统收到 2 份文件：视频 1、图片 1、文档 0", html)

    def test_first_layer_only_keeps_verdict_material_status_and_next_step(self):
        data = _report_data()
        data["material_readiness"] = {
            "scenario": "product_damage",
            "status": "incomplete",
            "confidence": 0.91,
            "reason": "开箱材料尚未满足普通商品有伤审核门槛。",
            "checklist": [],
            "missing_items": ["完整开箱视频"],
            "warnings": [],
        }
        data["agent_report"]["parsed"]["opening_video_evidence"] = {
            "status": "yellow",
            "confidence": 0.88,
            "reason": "已收到视频，但开箱链不完整。",
        }
        data["agent_report"]["advisory_assessment"] = {
            "assessment": {
                "conclusion_code": "evidence_inconclusive",
                "conclusion": "现有证据尚不足以判断。",
                "confidence": 0.82,
            },
            "sop_recommendation": {"recommendation": "补充完整开箱证据。"},
            "human_review": {
                "level": "not_required",
                "recommendation": "当前可直接向用户补充收集材料，无需先占用人工审核席位。",
            },
            "workflow_recommendation": "request_more_material",
        }

        html = render_public_report(data)
        first_layer = html.split('<details class="summary-review-details">', 1)[0]

        self.assertIn("当前商品有伤场景下的用户材料是否齐全", first_layer)
        self.assertIn("建议下一步", first_layer)
        self.assertNotIn("<small>证据结论</small>", first_layer)
        self.assertNotIn("<small>SOP 处理建议</small>", first_layer)
        self.assertNotIn("<small>证据分数</small>", first_layer)
        self.assertNotIn("<small>人工复审</small>", first_layer)
        self.assertNotIn("<small>流程</small>", first_layer)
        self.assertNotIn("复核重点：", first_layer)
        self.assertNotIn('<section class="opening-evidence-banner', first_layer)
        self.assertIn('<section class="opening-evidence-banner', html)

    def test_complete_minor_report_omits_noop_manual_and_flow_cards(self):
        data = _report_data()
        data["agent_report"]["scenario"] = "minor_refund"
        data["agent_report"]["scenario_label"] = "未成年人退款资料审核"
        data["agent_report"]["parsed"]["minor_material_assessment"] = {"checklist": []}
        data["agent_report"]["advisory_assessment"] = {
            "assessment": {
                "conclusion_code": "evidence_supports_claim",
                "conclusion": "五类材料与可见字段初审通过。",
                "confidence": 0.91,
            },
            "human_review": {"level": "not_required"},
            "workflow_recommendation": "continue_by_customer_policy",
            "policy": {},
        }
        data["material_readiness"] = {
            "scenario": "minor_refund",
            "status": "complete",
            "confidence": 0.91,
            "reason": "未成年人退款五类必交材料均已识别为可用。",
            "checklist": [],
            "missing_items": [],
            "warnings": [],
        }

        html = render_public_report(data)

        self.assertNotIn("<small>人工复审</small>", html)
        self.assertNotIn("<small>流程</small>", html)
        self.assertNotIn("本轮无需人工复审", html)

    def test_minor_report_header_uses_material_verdict_not_refund_support_verdict(self):
        data = _report_data()
        data["agent_report"]["scenario"] = "minor_refund"
        data["agent_report"]["scenario_label"] = "未成年人退款资料审核"
        data["agent_report"]["parsed"]["minor_material_assessment"] = {"checklist": []}
        data["agent_report"]["advisory_assessment"] = {
            "assessment": {
                "conclusion_code": "evidence_does_not_support_claim",
                "conclusion": "五类材料存在明确缺口或冲突。",
                "confidence": 0.91,
            },
            "human_review": {"level": "not_required"},
            "workflow_recommendation": "request_more_material",
            "policy": {},
        }
        data["material_readiness"] = {
            "scenario": "minor_refund",
            "status": "incomplete",
            "confidence": 0.91,
            "reason": "监护关系材料未闭环。",
            "checklist": [],
            "missing_items": ["法定监护关系证明"],
            "warnings": [],
        }

        html = render_public_report(data)
        first_layer = html.split('<details class="summary-review-details">', 1)[0]

        self.assertIn("<h1>材料需要补充或更正</h1>", first_layer)
        self.assertIn("<b>需补资料</b>", first_layer)
        self.assertNotIn("现有证据暂不支持用户诉求", first_layer)
        self.assertNotIn("<b>不支持</b>", first_layer)

    def test_minor_detail_is_five_category_checklist_without_product_video_modules(self):
        data = _report_data()
        data["agent_report"]["scenario"] = "minor_refund"
        data["agent_report"]["scenario_label"] = "未成年人退款资料审核"
        data["agent_report"]["parsed"]["minor_material_assessment"] = {
            "visual_precheck_status": "needs_review",
            "checklist": [
                {"requirement_id": "identity_documents", "label": "身份材料", "status": "present", "quality_status": "usable", "validation_status": "visual_consistency_matched"},
                {"requirement_id": "guardian_relationship", "label": "法定监护关系", "status": "present", "quality_status": "usable", "validation_status": "visual_relationship_link_unresolved"},
                {"requirement_id": "refund_commitment", "label": "退款承诺书", "status": "present", "quality_status": "usable", "validation_status": "visual_consistency_matched"},
                {"requirement_id": "order_payment", "label": "订单与支付", "status": "present", "quality_status": "usable", "validation_status": "visual_consistency_matched"},
                {"requirement_id": "mobile_realname", "label": "手机号实名", "status": "present", "quality_status": "usable", "validation_status": "visual_consistency_matched"},
            ],
            "field_consistency": {"checks": []},
            "payment_capability_risk": {
                "under_nine": True,
                "age_confidence": "high",
                "requires_review": True,
                "effect": "需重点核对支付过程。",
            },
        }

        html = render_public_report(data)

        for label in ("身份材料", "法定监护关系", "退款承诺书", "订单与支付", "手机号实名"):
            self.assertIn(label, html)
        self.assertIn("高置信未满 9 周岁", html)
        self.assertNotIn("视频审核论证", html)
        self.assertNotIn("商品证据连续性", html)
        self.assertNotIn("系统订单基线", html)
        self.assertNotIn("护照视觉识别", html)
        self.assertNotIn("外部在线验真", html)
        self.assertNotIn("申报图片", html)
        self.assertNotIn("图片处理完成度", html)

    def test_report_background_has_no_decorative_gradient_orbs(self):
        html = render_public_report(_report_data())

        self.assertNotIn("radial-gradient", html)

    def test_restricted_share_report_explains_where_to_preview_original_video(self):
        data = _report_data()
        gallery = data["agent_report"]["media_gallery"]
        gallery["restricted_original_evidence"] = True
        for group in ("videos", "frames", "images"):
            for item in gallery.get(group) or []:
                item.pop("url", None)
                item.pop("video_url", None)

        html = render_public_report(data)

        self.assertIn("脱敏分享页不包含原始素材", html)
        self.assertIn("登录后的正式工单报告", html)
        self.assertLess(html.index("脱敏分享页不包含原始素材"), html.index("展开完整技术分析"))

    def test_header_only_shows_high_confidence_severe_quality_flag(self):
        data = _report_data()
        parsed = data["agent_report"]["parsed"]
        parsed["damage_causality_assessment"]["severity_assessment"] = {
            "level": "severe",
            "structural_failure": True,
            "confidence": 0.62,
            "reason": "主体疑似断裂，但画面证据不足。",
        }
        parsed["field_confidences"] = {"issue_visible": 0.62}

        low_confidence_html = render_public_report(data)
        self.assertNotIn('class="severity-flag', low_confidence_html)

        parsed["issue_visible"] = True
        parsed["field_confidences"]["issue_visible"] = 0.91
        parsed["damage_causality_assessment"]["severity_assessment"]["confidence"] = 0.91
        parsed["decision_policy_audit"] = {"severe_alert_eligible": True}
        high_confidence_html = render_public_report(data)
        self.assertIn('class="severity-flag severity-yes"', high_confidence_html)

        parsed["issue_visible"] = False
        parsed["decision_policy_audit"] = {"severe_alert_eligible": False}
        contradictory_html = render_public_report(data)
        self.assertNotIn('class="severity-flag', contradictory_html)

        parsed["issue_visible"] = True
        parsed["damage_causality_assessment"]["severity_assessment"]["level"] = "minor"
        parsed["decision_policy_audit"] = {"severe_alert_eligible": False}
        non_severe_html = render_public_report(data)
        self.assertNotIn('class="severity-flag', non_severe_html)

    def test_header_never_recomputes_severe_alert_from_partial_model_fields(self):
        data = _report_data()
        parsed = data["agent_report"]["parsed"]
        parsed["issue_visible"] = True
        parsed["damage_causality_assessment"]["severity_assessment"] = {
            "level": "severe",
            "structural_failure": False,
            "confidence": 0.95,
            "reason": "局部表面痕迹，不是结构损坏。",
        }
        parsed["decision_policy_audit"] = {"severe_alert_eligible": False}

        html = render_public_report(data)

        self.assertNotIn('class="severity-flag', html)

    def test_header_uses_short_dynamic_verdict_instead_of_long_business_sentence(self):
        data = _report_data()
        assessment = {
            "conclusion_code": "evidence_inconclusive",
            "conclusion": "当前开箱视频中的目标部位过小，补充图片虽显示痕迹，但尚不能确认它与连续开箱中的同一商品和同一部位相对应。",
        }
        data["agent_report"]["advisory_assessment"] = {"assessment": assessment}

        html = render_public_report(data)

        self.assertIn("<h1>现有证据尚不足以判断</h1>", html)
        self.assertIn(assessment["conclusion"], html)
        self.assertNotIn(f'<h1>{assessment["conclusion"]}</h1>', html)

    def test_compact_video_confidence_array_renders_nine_field_table(self):
        data = _report_data()
        parsed = data["agent_report"]["parsed"]
        parsed.update({
            "all_items_shown": True,
            "continuous": True,
            "has_edit": False,
            "has_offscreen": None,
            "has_speed_change": None,
            "issue_visible": True,
            "overall_video_result": "indeterminate",
            "sealed_start": True,
            "waybill_visible": True,
            "field_confidences": [0.81, 0.82, 0.83, 0.84, 0.85, 0.86, 0.87, 0.88],
        })

        html = render_public_report(data)

        self.assertIn("相关商品是否全部展示", html)
        self.assertIn("81%", html)
        self.assertIn("投诉问题是否清晰可见", html)
        self.assertIn("88%", html)

    def test_report_separates_official_reference_images_from_customer_evidence(self):
        data = _report_data()
        data["agent_report"]["evidence_package"]["official_reference_images_sent"] = 1
        data["agent_report"]["evidence_package"]["order_baseline"] = {
            "baseline_version": "order_info_snapshot:abc123",
            "expected_items": [{
                "item_ref": "ORDER-LINE-001",
                "sku": "SKU-001",
                "product_name": "官方商品",
                "specification": "红色款",
                "expected_quantity": 2,
            }],
            "selection_rules_complete": False,
            "benefit_rules_complete": False,
            "package_mapping_status": "not_declared_in_snapshot",
        }
        data["agent_report"]["evidence_package"]["official_reference_status"] = {
            "status": "partial",
            "requested_count": 2,
            "available_count": 1,
            "failed_count": 1,
            "fallback": "text_order_baseline",
        }
        data["agent_report"]["media_gallery"]["official_references"] = [{
            "reference_index": 1,
            "reference_id": "ref-001",
            "item_ref": "ORDER-LINE-001",
            "sku": "SKU-001",
            "product_name": "官方商品",
            "url": "/media/official-reference.jpg",
        }]

        report_html = render_public_report(data)

        self.assertIn("官方商品参考图", report_html)
        self.assertIn("仅作为订单商品标准外观基准", report_html)
        self.assertIn("部分可用", report_html)
        self.assertIn("已回退到文字订单基线", report_html)
        self.assertIn('src="/media/official-reference.jpg"', report_html)
        self.assertIn("系统订单基线", report_html)
        self.assertIn("order_info_snapshot:abc123", report_html)
        self.assertIn("SKU-001", report_html)
        self.assertIn("不完整或待确认", report_html)

    def test_report_renders_atomic_claims_and_video_deduplication(self):
        data = _report_data()
        data["agent_report"]["evidence_package"]["video_deduplication"] = {
            "submitted_count": 2,
            "unique_count": 1,
            "duplicate_count": 1,
        }
        data["agent_report"]["parsed"]["claim_fact_assessment"] = {
            "atomic_claim_results": [
                {
                    "claim_id": "CLM-1",
                    "subject_ref": "SKU-1",
                    "location": "正面",
                    "damage_type": "划痕",
                    "main_video_visibility": "visible",
                    "supplemental_visibility": "visible",
                    "same_item_linkage": True,
                    "damage_presence": "confirmed",
                    "condition_at_unboxing": "supported",
                    "support_status": "supported",
                    "severity_level": "moderate",
                    "severity_confidence": 0.92,
                    "structural_failure": False,
                    "conflicting_evidence": False,
                    "reason": "划痕可见。",
                },
                {
                    "claim_id": "CLM-2",
                    "subject_ref": "SKU-2",
                    "location": "连接处",
                    "damage_type": "脱开",
                    "main_video_visibility": "visible",
                    "supplemental_visibility": "not_assessed",
                    "same_item_linkage": True,
                    "damage_presence": "not_found_after_clear_coverage",
                    "condition_at_unboxing": "not_supported",
                    "support_status": "not_supported",
                    "severity_level": "none",
                    "severity_confidence": 0.88,
                    "structural_failure": False,
                    "conflicting_evidence": False,
                    "reason": "复装后恢复正常。",
                },
            ],
            "order_linkage": {"status": "verified", "reason": "包裹归属一致。"},
            "scene_match": {"status": "matched", "reason": "属于商品有伤诉求。"},
            "assembly": {
                "state": "resolved_assembly_issue",
                "reassembly_result": "successful",
                "permanent_damage": "not_supported",
                "reason": "复装成功。",
            },
        }

        report_html = render_public_report(data)

        self.assertIn("原子诉求逐项核验", report_html)
        self.assertIn("CLM-1", report_html)
        self.assertIn("SKU-2", report_html)
        self.assertIn("正面", report_html)
        self.assertIn("开箱时已支持", report_html)
        self.assertIn("中度", report_html)
        self.assertIn("复装后恢复正常", report_html)
        self.assertIn("重复视频已跳过", report_html)
        self.assertIn(">1<", report_html)

    def test_report_exposes_original_and_model_submitted_video_for_comparison(self):
        data = _report_data()
        data["agent_report"]["media_gallery"]["videos"] = [{
            "video_index": 1,
            "url": "/media/review.webm",
            "review_url": "/media/review.webm",
            "original_url": "/media/original.mp4",
            "comparison_available": True,
            "review_derivative": {
                "source_bytes": 742_800_000,
                "review_bytes": 174_500_000,
                "transformation": {
                    "proxy_codec": "vp9",
                    "source_width": 3840,
                    "source_height": 2160,
                    "submitted_width": 2560,
                    "submitted_height": 1440,
                },
            },
        }]

        report_html = render_public_report(data)

        self.assertIn("模型实际送审版", report_html)
        self.assertIn("查看原片", report_html)
        self.assertIn("查看模型送审版", report_html)
        self.assertIn("3840×2160", report_html)
        self.assertIn("2560×1440", report_html)


if __name__ == "__main__":
    unittest.main()
