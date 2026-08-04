# -*- coding: utf-8 -*-
"""视觉审核公开报告的证据展示与媒体回链测试。"""

import unittest
from pathlib import Path

from poc.visual_review_poc.report_renderer import (
    _decision_policy_panel,
    _evidence_items,
    _h,
    _public_verdict,
    _safe_agent_reason,
    render_public_report,
    safe_agent_conclusion,
    safe_agent_next_step,
)
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
                        "max_unobserved_seconds": 2.0,
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
                    "policy": {"out_of_frame_warning_seconds": 2.0},
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
        self.assertIn("无需人工复审", report_html)
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

        self.assertIn("按照 SOP 的审核倾向", report_html)
        self.assertIn("证据结论", report_html)
        self.assertIn("当前材料倾向支持用户诉求", report_html)
        self.assertIn("建议进一步评估", report_html)
        self.assertIn("建议抽检", report_html)
        self.assertIn("按甲方规则继续", report_html)
        self.assertIn("短暂离镜仅降低证据强度", report_html)
        self.assertIn("不是客观正确率", report_html)
        self.assertIn("业务动作由甲方系统执行，是否需要人工复核由单独的复核等级决定", report_html)
        self.assertIn("不要求逐单", report_html)
        self.assertNotIn("提交VIP客服复核", report_html)

    def test_report_renders_evidence_boundaries_and_links_gallery_media(self):
        report_html = render_public_report(_report_data())

        self.assertIn("客服审核摘要", report_html)
        self.assertIn("为什么这样建议", report_html)
        self.assertIn("客服下一步", report_html)
        self.assertIn("关键证据", report_html)
        self.assertIn('<details class="panel technical-details">', report_html)

        for heading in ("审核Agent采信的证据", "反证与可疑帧", "问题时间点", "置信度分解与口径", "损伤来源与发生阶段", "主体连续性与离镜时间轴", "应发与视频展示清单对账", "置信度理由", "材料缺口", "模型局限"):
            self.assertIn(heading, report_html)

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
        self.assertIn("这些分数不是正确率", report_html)
        self.assertIn("动作前争议部位被包装遮挡", report_html)
        self.assertIn("动作后压痕首次可见", report_html)
        self.assertIn("主视频与补充证据分层", report_html)
        self.assertIn("主视频损伤存在性", report_html)
        self.assertNotIn("<small>损伤存在性</small><b>已确认可见损伤</b>", report_html)
        self.assertIn("补充图片 1 张", report_html)
        self.assertIn("关键审查帧未见主诉折痕", report_html)
        self.assertIn("补充特写可见疑似压痕", report_html)
        self.assertIn("抽帧首尾覆盖", report_html)
        self.assertIn("开箱过程完整性", report_html)
        self.assertIn("商品证据连续性", report_html)
        self.assertIn("媒体技术取证", report_html)
        self.assertIn("视频时间轴完整不等于争议商品全程连续可见", report_html)
        self.assertNotIn("requires_media_forensics", report_html)
        self.assertIn("SOP 规则判定说明", report_html)
        self.assertNotIn("MITAKO-PD-20260720@2", report_html)
        self.assertIn("争议商品离镜时间超过策略阈值", report_html)
        self.assertIn("补充证据关联尚未解决", report_html)
        self.assertIn("ORDER-1@V1", report_html)
        self.assertIn("应发 2 / 已识别 1", report_html)

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


if __name__ == "__main__":
    unittest.main()
