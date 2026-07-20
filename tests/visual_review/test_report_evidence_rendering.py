# -*- coding: utf-8 -*-
"""视觉审核公开报告的证据展示与媒体回链测试。"""

import unittest

from poc.visual_review_poc.report_renderer import _evidence_items, render_public_report


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
    def test_report_renders_evidence_boundaries_and_links_gallery_media(self):
        report_html = render_public_report(_report_data())

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
        self.assertIn("反光可能影响细微划痕判断", report_html)
        self.assertIn("尚未使用独立留出集校准", report_html)
        self.assertIn("这些分数不是正确率", report_html)
        self.assertIn("动作前争议部位被包装遮挡", report_html)
        self.assertIn("动作后压痕首次可见", report_html)
        self.assertIn("主视频与补充证据分层", report_html)
        self.assertIn("补充图片 1 张", report_html)
        self.assertIn("关键审查帧未见主诉折痕", report_html)
        self.assertIn("补充特写可见疑似压痕", report_html)
        self.assertIn("抽帧首尾覆盖", report_html)
        self.assertIn("开箱过程完整性", report_html)
        self.assertIn("商品证据连续性", report_html)
        self.assertIn("媒体技术取证", report_html)
        self.assertIn("版本化规则判定说明", report_html)
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
            self.assertEqual(report_html.count(f'src="{media_url}"'), expected_count, media_url)

        self.assertNotIn("画面正常", report_html)
        self.assertNotIn("internal-provider-name", report_html)
        self.assertNotIn("SECRET-KEY-MUST-NOT-LEAK", report_html)
        self.assertNotIn("不得出现在公开报告中的内部提示词", report_html)

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


if __name__ == "__main__":
    unittest.main()
