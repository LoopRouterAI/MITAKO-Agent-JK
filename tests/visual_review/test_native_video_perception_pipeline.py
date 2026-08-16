from __future__ import annotations

import unittest
import os
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from poc.visual_review_poc.native_video_perception import (
    build_candidate_detail_case,
    build_claim_identity_case,
    candidate_detail_timestamps,
    expand_native_video_perception,
    requires_claimed_item_detail,
    run_native_perception_pipeline,
)
from poc.visual_review_poc.unified_model_pass import (
    claimed_item_evidence_times,
    native_dimension_gaps,
)


class NativeVideoPerceptionPipelineTest(unittest.TestCase):
    def _complete_perception(self) -> dict:
        return {
            "sealed_start": True,
            "waybill_visible": True,
            "continuous": True,
            "has_edit": False,
            "has_offscreen": False,
            "has_speed_change": False,
            "all_items_shown": True,
            "issue_visible": True,
            "overall_video_result": "compliant",
            "opening_action_assessment": {
                "present": True,
                "confidence": 0.93,
                "reason": "画面连续记录了包裹从闭合到拆开的动作。",
            },
            "claimed_item_assessment": {
                "identity_description": "争议文件夹",
                "appeared": True,
                "first_visible_timestamp": "01:51.000",
                "last_visible_timestamp": "02:30.750",
                "presentation_complete": True,
                "offscreen_during_presentation": False,
                "reason": "争议商品已完整展示。",
            },
            "speed_assessment": {
                "value": "normal",
                "confidence": 0.95,
                "evidence_basis": "natural_audio_cadence",
                "affects_visual_judgement": False,
                "reason": "声音与动作节奏自然。",
            },
            "damage_assessment": {
                "visible_in_continuous_opening": True,
                "main_video_detail_sufficient": True,
                "supplemental_damage_visible": None,
                "same_item_linkage": True,
                "timestamp": "02:15.500",
                "location": "文件夹正面",
                "severity_level": "severe",
                "structural_failure": True,
                "severity_confidence": 0.94,
                "business_defect_qualification": "confirmed",
                "conflicting_evidence": False,
                "severity_reason": "主体断裂，已影响正常展示。",
                "causal_chain_status": "direct_customer_action",
                "causal_evidence_level": "direct",
                "causal_reason": "同一部位在刀具接触后出现断裂。",
                "causal_evidence_refs": [
                    {
                        "stage": "before_action", "asset_ref": "native_video_1",
                        "video_index": 1,
                        "timestamp": "02:14.000", "subject": "争议文件夹", "location": "正面左上角",
                        "chain_id": "damage-chain-1", "damage_visible": False,
                        "fact": "动作前同部位未见断裂。",
                    },
                    {
                        "stage": "action", "asset_ref": "native_video_1",
                        "video_index": 1,
                        "timestamp": "02:15.000", "subject": "争议文件夹", "location": "正面左上角",
                        "chain_id": "damage-chain-1", "damage_visible": None,
                        "action_relation": "direct_contact",
                        "fact": "刀具接触该部位。",
                    },
                    {
                        "stage": "after_action", "asset_ref": "native_video_1",
                        "video_index": 1,
                        "timestamp": "02:15.500", "subject": "争议文件夹", "location": "正面左上角",
                        "chain_id": "damage-chain-1", "damage_visible": True,
                        "fact": "动作后同部位出现断裂。",
                    },
                ],
                "reason": "连续开箱中可见划痕。",
            },
            "field_confidences": {
                "sealed_start": 0.9,
                "waybill_visible": 0.9,
                "continuous": 0.9,
                "has_edit": 0.9,
                "has_offscreen": 0.9,
                "has_speed_change": 0.9,
                "all_items_shown": 0.9,
                "issue_visible": 0.9,
            },
            "evidence_refs": [
                {
                    "field": "opening_action",
                    "asset_ref": "native_video_1",
                    "video_index": 1,
                    "timestamp": "00:05.000",
                    "fact": "包裹从闭合状态被拆开",
                },
                {
                    "field": "sealed_start",
                    "asset_ref": "native_video_1",
                    "video_index": 1,
                    "timestamp": "00:00.000",
                    "fact": "完整未拆封外箱可见",
                },
                {
                    "field": "waybill_visible",
                    "asset_ref": "native_video_1",
                    "video_index": 1,
                    "timestamp": "00:02.000",
                    "fact": "面单已清晰入镜",
                },
                {
                    "field": "continuous",
                    "asset_ref": "native_video_1",
                    "video_index": 1,
                    "timestamp": "02:30.750",
                    "fact": "从封箱到商品展示未见剪辑或中断",
                },
                {
                    "field": "issue_visible",
                    "asset_ref": "native_video_1",
                    "video_index": 1,
                    "timestamp": "02:15.500",
                    "fact": "划痕清晰可见",
                },
                {
                    "field": "claimed_item",
                    "asset_ref": "native_video_1",
                    "video_index": 1,
                    "timestamp": "01:51.000",
                    "fact": "争议商品首次出现",
                },
                {
                    "field": "claimed_item",
                    "asset_ref": "native_video_1",
                    "video_index": 1,
                    "timestamp": "02:30.750",
                    "fact": "同一争议商品完成必要展示",
                },
                {
                    "field": "has_edit", "asset_ref": "native_video_1",
                    "video_index": 1,
                    "timestamp": "02:30.750", "fact": "全片未见跳切或拼接。",
                },
                {
                    "field": "has_offscreen", "asset_ref": "native_video_1",
                    "video_index": 1,
                    "timestamp": "02:20.000", "fact": "必要展示窗口内商品未发生有意义离镜。",
                },
                {
                    "field": "has_speed_change", "asset_ref": "native_video_1",
                    "video_index": 1,
                    "timestamp": "01:00.000", "fact": "画面与声音节奏未见明显速度变化。",
                },
                {
                    "field": "all_items_shown", "asset_ref": "native_video_1",
                    "video_index": 1,
                    "timestamp": "02:30.000", "fact": "争议商品所需表面已展示完成。",
                },
            ],
        }

    def test_pipeline_uses_one_complete_video_call_with_identity_references(self) -> None:
        calls = []

        def invoke(current: dict) -> dict:
            calls.append(current)
            return {
                "status": "success",
                "parsed": self._complete_perception(),
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                "cost": {"estimated_usd": 0.01, "currency": "USD", "amount": 0.01},
            }

        case = {
            "scenario": "product_damage",
            "customer_claim": "目标摆件有划痕",
            "native_video": {"api_path": "video.mp4"},
            "frames": [{"api_path": "sampled.jpg"}],
            "supplemental_images": [{"api_path": "claim.jpg", "image_index": 1}],
            "official_reference_images": [
                {"api_path": "official.jpg", "reference_index": 1, "item_ref": "LINE-1"}
            ],
            "structured_business_context": {},
        }

        with TemporaryDirectory() as temp_dir:
            result, _ = run_native_perception_pipeline(
                case,
                Path("video.mp4"),
                Path(temp_dir),
                invoke,
            )

        self.assertEqual(len(calls), 1)
        self.assertEqual(
            calls[0]["structured_business_context"]["analysis_mode"],
            "native_video_perception",
        )
        self.assertEqual(calls[0]["frames"], case["frames"])
        self.assertEqual(calls[0]["supplemental_images"], case["supplemental_images"])
        self.assertEqual(calls[0]["official_reference_images"], case["official_reference_images"])
        self.assertEqual(calls[0]["native_video"]["sampling_fps"], 1.0)
        self.assertEqual(result["perception_pipeline"]["model_calls"], 1)
        self.assertEqual(
            set(result["perception_pipeline"]["channels"]),
            {"native_video"},
        )

    def test_pipeline_applies_one_fps_to_every_native_video_entry(self) -> None:
        calls = []

        def invoke(current: dict) -> dict:
            calls.append(current)
            return {
                "status": "success",
                "parsed": self._complete_perception(),
            }

        case = {
            "scenario": "product_damage",
            "customer_claim": "商品表面存在划痕",
            "native_video": {"api_path": "video-primary.mp4"},
            "native_videos": [
                {"api_path": "video-primary.mp4"},
                {"api_path": "video-secondary.mp4", "sampling_fps": 4.0},
            ],
            "structured_business_context": {},
        }

        with TemporaryDirectory() as temp_dir:
            run_native_perception_pipeline(
                case,
                Path("video-primary.mp4"),
                Path(temp_dir),
                invoke,
            )

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["native_video"]["sampling_fps"], 1.0)
        self.assertEqual(
            [item["sampling_fps"] for item in calls[0]["native_videos"]],
            [1.0, 1.0],
        )

    def test_compact_perception_expands_to_existing_report_contract(self) -> None:
        perception = self._complete_perception()
        perception.pop("overall_video_result", None)
        parsed = expand_native_video_perception(
            perception,
            {"scenario": "product_damage", "customer_claim": "文件夹有划痕"},
            sampling_fps=4.0,
        )

        self.assertEqual(parsed["predicted_label"], "positive")
        self.assertEqual(parsed["system_yes_no"], "YES")
        self.assertEqual(parsed["confidence"], 0.9)
        self.assertEqual(parsed["overall_audit"]["confidence"], 0.9)
        atomic_facts = {
            item["field"]: item
            for item in parsed["atomic_facts"]
        }
        self.assertEqual(
            set(atomic_facts),
            {
                "opening_action",
                "sealed_start",
                "waybill_visible",
                "continuous",
                "has_edit",
                "has_offscreen",
                "has_speed_change",
                "all_items_shown",
                "issue_visible",
            },
        )
        self.assertTrue(atomic_facts["opening_action"]["value"])
        self.assertEqual(atomic_facts["opening_action"]["confidence"], 0.93)
        self.assertIn("闭合到拆开", atomic_facts["opening_action"]["reason"])
        self.assertEqual(
            atomic_facts["opening_action"]["evidence_refs"][0]["asset_ref"],
            "native_video_1",
        )
        self.assertEqual(atomic_facts["issue_visible"]["confidence"], 0.9)
        self.assertIn("划痕", atomic_facts["issue_visible"]["reason"])
        self.assertIn("同一连续开箱", parsed["overall_audit"]["conclusion"])
        self.assertTrue(parsed["frame_findings"])
        self.assertEqual(
            parsed["object_continuity_assessment"]["continuity_verdict"],
            "continuous",
        )
        opening = parsed["video_audit_conclusion"]["opening_video_compliance"]
        self.assertEqual(opening["result"], "compliant")
        self.assertEqual(
            set(opening["validated_fields"]),
            {
                "opening_action_visible",
                "sealed_start",
                "waybill_visible",
                "single_take_continuity",
                "issue_visible_in_continuous_opening",
            },
        )
        opening_evidence = parsed["opening_video_evidence"]
        self.assertTrue(opening_evidence["present"])
        self.assertTrue(opening_evidence["sop_compliant"])
        self.assertEqual(opening_evidence["status"], "pass")
        self.assertEqual(opening_evidence["confidence"], 0.93)
        self.assertIn("初次拆开包裹", opening_evidence["reason"])
        self.assertEqual(parsed["video_audit_conclusion"]["sampling_fps"], 4.0)
        self.assertEqual(
            parsed["damage_causality_assessment"]["damage_presence"],
            "confirmed",
        )
        self.assertEqual(
            parsed["damage_causality_assessment"]["severity_assessment"]["level"],
            "severe",
        )
        self.assertEqual(
            parsed["damage_causality_assessment"]["severity_assessment"]["confidence"],
            0.94,
        )
        self.assertEqual(
            parsed["damage_causality_assessment"]["business_defect_qualification"],
            "confirmed",
        )
        self.assertFalse(parsed["damage_observability"]["conflicting_evidence"])
        self.assertEqual(
            parsed["damage_causality_assessment"]["most_likely_origin"],
            "customer_opening_or_handling",
        )
        self.assertTrue(parsed["damage_causality_assessment"]["damage_change_observed"])
        self.assertTrue(parsed["damage_causality_assessment"]["opening_action_visible"])
        self.assertEqual(
            parsed["damage_causality_assessment"]["causal_evidence_level"],
            "direct",
        )
        self.assertEqual(
            [item["timestamp"] for item in parsed["damage_causality_assessment"]["before_action_evidence"]],
            ["02:14.000"],
        )
        self.assertEqual(
            [item["timestamp"] for item in parsed["damage_causality_assessment"]["action_evidence"]],
            ["02:15.000"],
        )
        self.assertEqual(
            [item["timestamp"] for item in parsed["damage_causality_assessment"]["after_action_evidence"]],
            ["02:15.500"],
        )
        for stage in ("before_action_evidence", "action_evidence", "after_action_evidence"):
            reference = parsed["damage_causality_assessment"][stage][0]
            self.assertEqual(reference["asset_ref"], "native_video_1")
            self.assertEqual(reference["video_index"], 1)
            self.assertNotIn("global_frame_index", reference)
        self.assertEqual(
            native_dimension_gaps(parsed, "product_damage"),
            [],
        )

    def test_multi_video_claimed_item_evidence_accepts_non_primary_video(self) -> None:
        self.assertEqual(
            claimed_item_evidence_times({"evidence_refs": [
                {"field": "claimed_item", "asset_ref": "native_video_2", "timestamp": "00:37.000"},
                {"field": "claimed_item", "asset_ref": "native_video_2", "timestamp": "00:42.000"},
            ]}),
            [37.0, 42.0],
        )

    def test_out_of_range_video_timestamp_is_not_exposed_as_report_evidence(self) -> None:
        parsed = expand_native_video_perception(
            self._complete_perception(),
            {
                "scenario": "product_damage",
                "videos": [
                    {"video_index": 1, "duration_seconds": 10.0},
                    {"video_index": 2, "duration_seconds": 300.0},
                ],
            },
            sampling_fps=1.0,
        )

        impossible = [
            item
            for item in parsed["supporting_evidence"]
            if item.get("video_index") == 1
            and item.get("timestamp") in {"01:51.000", "02:15.500", "02:30.750"}
        ]
        self.assertEqual(impossible, [])
        self.assertIsNone(parsed["claimed_item_assessment"]["presentation_complete"])
        self.assertEqual(parsed["predicted_label"], "review")

    def test_missing_initial_opening_video_is_yellow_with_derived_confidence(self) -> None:
        perception = self._complete_perception()
        perception["opening_action_assessment"] = {
            "present": False,
            "confidence": 0.94,
            "reason": "只拍到闭合包裹，没有看到拆包动作。",
        }
        perception["evidence_refs"] = [
            item for item in perception["evidence_refs"]
            if item.get("field") != "opening_action"
        ]

        parsed = expand_native_video_perception(
            perception,
            {"scenario": "product_damage"},
            sampling_fps=1.0,
        )

        opening_evidence = parsed["opening_video_evidence"]
        self.assertFalse(opening_evidence["present"])
        self.assertEqual(opening_evidence["status"], "yellow")
        self.assertEqual(opening_evidence["confidence"], 0.94)
        self.assertIn("没有形成可信的初次开箱证据", opening_evidence["reason"])
        self.assertEqual(parsed["overall_video_result"], "indeterminate")
        self.assertEqual(
            parsed["video_audit_conclusion"]["opening_video_compliance"]["result"],
            "indeterminate",
        )
        self.assertEqual(parsed["predicted_label"], "review")

    def test_unreferenced_opening_action_is_reported_as_missing_anchor_not_unseen(self) -> None:
        perception = self._complete_perception()
        perception["evidence_refs"] = [
            item for item in perception["evidence_refs"]
            if item.get("field") != "opening_action"
        ]

        parsed = expand_native_video_perception(
            perception,
            {"scenario": "product_damage"},
            sampling_fps=1.0,
        )

        opening = parsed["opening_video_evidence"]
        self.assertFalse(opening["present"])
        self.assertIn("没有返回可回看的时间点", opening["reason"])
        self.assertNotIn("未直接观察到", opening["reason"])

    def test_opening_action_structured_anchor_is_normalized_to_evidence_reference(self) -> None:
        perception = self._complete_perception()
        perception["evidence_refs"] = [
            item for item in perception["evidence_refs"]
            if item.get("field") != "opening_action"
        ]
        perception["opening_action_assessment"].update({
            "asset_ref": "native_video_1",
            "timestamp": "00:05.000",
            "fact": "包裹从闭合状态被首次拆开。",
        })

        parsed = expand_native_video_perception(
            perception,
            {"scenario": "product_damage"},
            sampling_fps=1.0,
        )

        opening = parsed["opening_video_evidence"]
        self.assertTrue(opening["present"])
        action_ref = next(
            item for item in opening["evidence_refs"]
            if item.get("field") == "opening_action"
        )
        self.assertEqual(action_ref["asset_ref"], "native_video_1")
        self.assertEqual(action_ref["timestamp"], "00:05.000")

    def test_static_sealed_continuous_video_does_not_prove_opening_action(self) -> None:
        perception = self._complete_perception()
        perception["opening_action_assessment"] = {
            "present": False,
            "confidence": 0.92,
            "reason": "画面连续但只展示闭合包裹，未出现拆封动作。",
        }
        perception["evidence_refs"] = [
            item for item in perception["evidence_refs"]
            if item.get("field") != "opening_action"
        ]

        parsed = expand_native_video_perception(
            perception,
            {"scenario": "product_damage"},
            sampling_fps=1.0,
        )

        opening = parsed["opening_video_evidence"]
        self.assertFalse(opening["present"])
        self.assertFalse(opening["sop_compliant"])
        self.assertNotIn("opening_action", opening["validated_requirements"])
        self.assertEqual(parsed["overall_video_result"], "indeterminate")

    def test_low_confidence_edit_signal_is_yellow_not_noncompliant(self) -> None:
        perception = self._complete_perception()
        perception["has_edit"] = True
        perception["field_confidences"]["has_edit"] = 0.05

        parsed = expand_native_video_perception(
            perception,
            {"scenario": "product_damage"},
            sampling_fps=1.0,
        )

        self.assertIsNone(parsed["has_edit"])
        self.assertEqual(parsed["overall_video_result"], "indeterminate")
        self.assertEqual(parsed["predicted_label"], "review")
        self.assertEqual(
            parsed["video_audit_conclusion"]["edit_review_signal"],
            "yellow",
        )

    def test_native_reference_uses_explicit_video_index_without_frame_index(self) -> None:
        perception = self._complete_perception()

        parsed = expand_native_video_perception(
            perception,
            {"scenario": "product_damage"},
            sampling_fps=1.0,
        )

        opening_refs = parsed["video_audit_conclusion"]["opening_video_compliance"]["evidence_refs"]
        self.assertEqual(parsed["overall_video_result"], "compliant")
        self.assertTrue(opening_refs)
        self.assertTrue(all(reference["video_index"] == 1 for reference in opening_refs))
        self.assertTrue(all("global_frame_index" not in reference for reference in opening_refs))

    def test_native_schema_reference_derives_video_index_from_asset_ref(self) -> None:
        perception = self._complete_perception()
        for reference in perception["evidence_refs"]:
            reference.pop("video_index", None)

        parsed = expand_native_video_perception(
            perception,
            {"scenario": "product_damage"},
            sampling_fps=1.0,
        )

        self.assertEqual(parsed["overall_video_result"], "compliant")
        self.assertTrue(parsed["opening_video_evidence"]["present"])
        opening_refs = parsed["video_audit_conclusion"]["opening_video_compliance"]["evidence_refs"]
        self.assertTrue(opening_refs)
        self.assertTrue(all(reference["video_index"] == 1 for reference in opening_refs))

    def test_sampled_reference_requires_explicit_global_frame_index(self) -> None:
        perception = self._complete_perception()
        opening_reference = next(
            reference
            for reference in perception["evidence_refs"]
            if reference.get("field") == "opening_action"
        )
        opening_reference.update({
            "asset_ref": "video_1_frame_5",
            "video_index": 1,
        })
        opening_reference.pop("global_frame_index", None)

        parsed = expand_native_video_perception(
            perception,
            {"scenario": "product_damage"},
            sampling_fps=1.0,
        )

        opening = parsed["video_audit_conclusion"]["opening_video_compliance"]
        self.assertEqual(parsed["overall_video_result"], "indeterminate")
        self.assertNotIn("opening_action_visible", opening["validated_fields"])

    def test_high_confidence_edit_in_critical_opening_chain_is_noncompliant(self) -> None:
        perception = self._complete_perception()
        perception["has_edit"] = True
        perception["field_confidences"]["has_edit"] = 0.95
        perception["evidence_refs"].append({
            "field": "has_edit",
            "asset_ref": "native_video_1",
            "video_index": 1,
            "timestamp": "01:12.000",
            "fact": "关键开箱动作发生跳切后的画面。",
        })

        parsed = expand_native_video_perception(
            perception,
            {"scenario": "product_damage"},
            sampling_fps=1.0,
        )

        self.assertTrue(parsed["has_edit"])
        self.assertEqual(parsed["overall_video_result"], "noncompliant")
        self.assertEqual(parsed["predicted_label"], "negative")

    def test_opening_action_presence_is_separate_from_full_sop_compliance(self) -> None:
        perception = self._complete_perception()
        perception["waybill_visible"] = False
        perception["field_confidences"]["waybill_visible"] = 0.93

        parsed = expand_native_video_perception(
            perception,
            {"scenario": "product_damage"},
            sampling_fps=1.0,
        )

        opening = parsed["opening_video_evidence"]
        self.assertTrue(opening["present"])
        self.assertFalse(opening["sop_compliant"])
        self.assertEqual(opening["status"], "pass")
        self.assertIn("已确认初次拆开包裹动作", opening["reason"])

    def test_native_multi_claim_results_reach_decision_contract_with_real_refs(self) -> None:
        perception = self._complete_perception()
        for field in (
            "visible_in_continuous_opening", "main_video_detail_sufficient",
            "supplemental_damage_visible", "same_item_linkage", "timestamp",
            "location", "severity_level", "structural_failure",
            "severity_confidence", "business_defect_qualification",
            "conflicting_evidence", "severity_reason",
        ):
            perception["damage_assessment"].pop(field, None)
        perception["atomic_claim_results"] = [
            {
                "claim_id": "CLM-SCRATCH",
                "subject_ref": "SKU-1",
                "location": "面具正面",
                "damage_type": "划痕",
                "main_video_visibility": "visible",
                "supplemental_visibility": "not_assessed",
                "same_item_linkage": True,
                "damage_presence": "confirmed",
                "condition_at_unboxing": "supported",
                "support_status": "supported",
                "severity_level": "moderate",
                "severity_confidence": 0.91,
                "structural_failure": False,
                "conflicting_evidence": False,
                "evidence_refs": [{
                    "asset_ref": "native_video_1",
                    "timestamp": "02:15.500",
                    "fact": "正面划痕在两个角度持续可见。",
                }],
                "reason": "主视频直接支持该划痕主张。",
            },
            {
                "claim_id": "CLM-BASE",
                "subject_ref": "SKU-1",
                "location": "底座",
                "damage_type": "断裂",
                "main_video_visibility": "clearly_not_visible",
                "supplemental_visibility": "not_assessed",
                "same_item_linkage": True,
                "damage_presence": "not_found_after_clear_coverage",
                "condition_at_unboxing": "not_supported",
                "support_status": "not_supported",
                "severity_level": "none",
                "severity_confidence": 0.89,
                "structural_failure": False,
                "conflicting_evidence": False,
                "evidence_refs": [{
                    "asset_ref": "native_video_1",
                    "timestamp": "02:30.750",
                    "fact": "底座完整展示，未见断裂。",
                }],
                "reason": "清晰展示不支持底座断裂主张。",
            },
        ]
        perception["evidence_refs"].extend([
            {"field": "issue_visible", **reference}
            for claim in perception["atomic_claim_results"]
            for reference in claim["evidence_refs"]
        ])
        case = {
            "scenario": "product_damage",
            "structured_business_context": {
                "claim_scope": {
                    "active_claim_ids": ["CLM-SCRATCH", "CLM-BASE"],
                },
            },
        }

        parsed = expand_native_video_perception(perception, case, sampling_fps=1.0)

        results = parsed["claim_fact_assessment"]["atomic_claim_results"]
        self.assertEqual([item["claim_id"] for item in results], ["CLM-SCRATCH", "CLM-BASE"])
        self.assertTrue(all(item["evidence_refs"] for item in results))
        self.assertEqual(results[0]["location"], "面具正面")
        self.assertEqual(results[0]["condition_at_unboxing"], "supported")
        self.assertEqual(results[1]["damage_presence"], "not_found_after_clear_coverage")
        self.assertEqual(
            parsed["damage_causality_assessment"]["severity_assessment"]["level"],
            "moderate",
        )
        self.assertEqual(
            parsed["damage_causality_assessment"]["business_defect_qualification"],
            "not_qualified",
        )
        self.assertTrue(parsed["damage_observability"]["same_item_linkage"])
        self.assertEqual(parsed["damage_observability"]["status"], "fully_observable")

    def test_atomic_claim_refs_bind_to_submitted_assets_without_duplicate_fact_text(self) -> None:
        perception = self._complete_perception()
        perception["atomic_claim_results"] = [{
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
            "severity_confidence": 0.9,
            "structural_failure": False,
            "conflicting_evidence": False,
            "evidence_refs": [
                {
                    "asset_ref": "native_video_1",
                    "timestamp": "00:12",
                    "fact": "划痕在商品正面持续可见。",
                },
                {
                    "asset_ref": "supplemental_image_1",
                    "timestamp": None,
                    "fact": "近照显示同一位置划痕。",
                },
                {
                    "asset_ref": "supplemental_image_999",
                    "timestamp": None,
                    "fact": "伪造素材不得进入结果。",
                },
            ],
            "reason": "视频与近照共同支持伤点事实。",
        }]
        perception["evidence_refs"] = [
            item for item in perception["evidence_refs"]
            if item.get("field") != "issue_visible"
        ] + [{
            "field": "issue_visible",
            "asset_ref": "native_video_1",
            "timestamp": "00:12",
            "fact": "同一时点的规范化描述与伤点字段措辞不同。",
        }]
        case = {
            "scenario": "product_damage",
            "videos": [{"video_index": 1, "duration_seconds": 60}],
            "supplemental_images": [{"image_index": 1}],
            "structured_business_context": {
                "claim_scope": {"active_claim_ids": ["CLM-1"]},
            },
        }

        parsed = expand_native_video_perception(perception, case, sampling_fps=1.0)
        refs = parsed["claim_fact_assessment"]["atomic_claim_results"][0]["evidence_refs"]

        self.assertEqual(
            {item["asset_ref"] for item in refs},
            {"native_video_1", "supplemental_image_1"},
        )

    def test_linked_supplemental_damage_confirms_damage_without_claiming_opening_responsibility(self) -> None:
        perception = self._complete_perception()
        perception["issue_visible"] = None
        perception["damage_assessment"]["visible_in_continuous_opening"] = None
        perception["damage_assessment"]["main_video_detail_sufficient"] = False
        perception["atomic_claim_results"] = [{
            "claim_id": "CLM-1",
            "subject_ref": "SKU-1",
            "location": "商品表面",
            "damage_type": "划痕",
            "main_video_visibility": "uncertain",
            "supplemental_visibility": "visible",
            "same_item_linkage": True,
            "damage_presence": "confirmed",
            "condition_at_unboxing": "supported",
            "support_status": "supported",
            "severity_level": "minor",
            "severity_confidence": 0.9,
            "structural_failure": False,
            "conflicting_evidence": False,
            "evidence_refs": [{
                "asset_ref": "supplemental_image_1",
                "timestamp": None,
                "fact": "同一商品近照可见表面划痕。",
            }],
            "reason": "补充近照确认伤损存在，主视频细节不足。",
        }]
        perception["evidence_refs"] = [
            item for item in perception["evidence_refs"]
            if item.get("field") != "issue_visible"
        ] + [{
            "field": "issue_visible",
            "asset_ref": "supplemental_image_1",
            "timestamp": None,
            "fact": "同一商品近照可见表面划痕。",
        }]
        case = {
            "scenario": "product_damage",
            "videos": [{"video_index": 1, "duration_seconds": 180}],
            "supplemental_images": [{"image_index": 1}],
            "structured_business_context": {
                "claim_scope": {"active_claim_ids": ["CLM-1"]},
            },
        }

        parsed = expand_native_video_perception(perception, case, sampling_fps=1.0)
        damage = parsed["damage_causality_assessment"]

        self.assertEqual(damage["damage_presence"], "confirmed")
        self.assertEqual(damage["claim_support"], "insufficient")
        self.assertEqual(
            damage["evidence_source_summary"]["primary_video"]["damage_presence"],
            "uncertain",
        )
        self.assertEqual(
            damage["evidence_source_summary"]["supplemental_images"]["damage_presence"],
            "confirmed",
        )
        self.assertEqual(parsed["video_audit_conclusion"]["opening_video_compliance"]["result"], "indeterminate")

    def test_single_traceable_video_anchor_does_not_hide_visible_minor_damage(self) -> None:
        perception = self._complete_perception()
        perception["atomic_claim_results"] = [{
            "claim_id": "CLM-1",
            "subject_ref": "SKU-1",
            "location": "正面",
            "damage_type": "轻微划痕",
            "main_video_visibility": "visible",
            "supplemental_visibility": "visible",
            "same_item_linkage": True,
            "damage_presence": "confirmed",
            "condition_at_unboxing": "supported",
            "support_status": "supported",
            "severity_level": "minor",
            "severity_confidence": 0.9,
            "structural_failure": False,
            "conflicting_evidence": False,
            "evidence_refs": [
                {
                    "asset_ref": "native_video_1",
                    "timestamp": "00:43",
                    "fact": "连续开箱中清楚看见同一位置的轻微划痕。",
                },
                {
                    "asset_ref": "supplemental_image_1",
                    "timestamp": None,
                    "fact": "近照用于核对同一伤点的形态。",
                },
            ],
            "reason": "主视频直接支持伤点在开箱时已经存在。",
        }]
        perception["evidence_refs"] = [
            item for item in perception["evidence_refs"]
            if item.get("field") != "issue_visible"
        ]
        case = {
            "scenario": "product_damage",
            "videos": [{"video_index": 1, "duration_seconds": 600}],
            "supplemental_images": [{"image_index": 1}],
            "structured_business_context": {
                "claim_scope": {"active_claim_ids": ["CLM-1"]},
            },
        }

        parsed = expand_native_video_perception(perception, case, sampling_fps=1.0)

        self.assertTrue(parsed["issue_visible"])
        self.assertEqual(parsed["overall_video_result"], "compliant")
        self.assertEqual(parsed["damage_observability"]["status"], "fully_observable")
        self.assertEqual(
            [
                item["timestamp"]
                for item in parsed["evidence_refs"]
                if item.get("field") == "issue_visible"
            ],
            ["00:43"],
        )

    def test_single_claimed_item_anchor_cannot_prove_complete_no_offscreen_window(self) -> None:
        perception = self._complete_perception()
        perception["evidence_refs"] = [
            item
            for item in perception["evidence_refs"]
            if item.get("field") != "claimed_item"
        ] + [
            {
                "field": "claimed_item",
                "asset_ref": "native_video_1",
                "timestamp": "00:37.000",
                "fact": "争议商品只在这个时点得到确认",
            }
        ]

        parsed = expand_native_video_perception(
            perception,
            {"scenario": "product_damage"},
            sampling_fps=1.0,
        )

        self.assertIsNone(parsed["has_offscreen"])
        self.assertIsNone(
            parsed["object_continuity_assessment"]["claimed_item_timeline_complete"]
        )
        self.assertIn(
            "claimed_item_identity_window",
            native_dimension_gaps(parsed, "product_damage"),
        )

    def test_supplemental_damage_requires_a_real_image_reference(self) -> None:
        perception = self._complete_perception()
        perception["damage_assessment"]["supplemental_damage_visible"] = True
        case = {
            "scenario": "product_damage",
            "supplemental_images": [{"image_index": 1, "api_path": "claim.webp"}],
        }

        without_reference = expand_native_video_perception(
            perception,
            case,
            sampling_fps=1.0,
        )
        summary = without_reference["damage_causality_assessment"]["evidence_source_summary"]["supplemental_images"]
        self.assertEqual(summary["referenced_count"], 0)
        self.assertEqual(summary["damage_presence"], "not_assessed")
        self.assertEqual(summary["linkage_status"], "not_assessed")

        perception["evidence_refs"].append({
            "field": "supplemental_damage_visible",
            "asset_ref": "supplemental_image_1",
            "timestamp": None,
            "fact": "补充图可见与主视频同一文件夹表面划痕",
        })
        with_reference = expand_native_video_perception(
            perception,
            case,
            sampling_fps=1.0,
        )
        summary = with_reference["damage_causality_assessment"]["evidence_source_summary"]["supplemental_images"]
        self.assertEqual(summary["referenced_count"], 1)
        self.assertEqual(summary["damage_presence"], "confirmed")
        self.assertEqual(summary["linkage_status"], "verified")

    def test_supplemental_reference_cannot_validate_main_opening_issue(self) -> None:
        perception = self._complete_perception()
        issue_ref = next(
            item for item in perception["evidence_refs"] if item["field"] == "issue_visible"
        )
        issue_ref["asset_ref"] = "supplemental_image_1"

        parsed = expand_native_video_perception(
            perception,
            {
                "scenario": "product_damage",
                "supplemental_images": [{"image_index": 1, "api_path": "claim.webp"}],
            },
            sampling_fps=1.0,
        )

        opening = parsed["video_audit_conclusion"]["opening_video_compliance"]
        self.assertNotIn("issue_visible_in_continuous_opening", opening["validated_fields"])
        self.assertEqual(opening["result"], "indeterminate")
        self.assertEqual(parsed["overall_video_result"], "indeterminate")
        self.assertEqual(parsed["predicted_label"], "review")

    def test_minor_surface_trace_without_replayable_video_anchor_stays_uncertain(self) -> None:
        perception = self._complete_perception()
        perception["damage_assessment"].update({
            "severity_level": "minor",
            "structural_failure": False,
            "business_defect_qualification": "indeterminate",
            "severity_reason": "画面仅疑似存在轻微表面痕迹。",
        })
        perception["evidence_refs"] = [
            item for item in perception["evidence_refs"]
            if item.get("field") != "issue_visible"
        ]

        result = expand_native_video_perception(
            perception,
            {"scenario": "product_damage"},
            sampling_fps=1.0,
        )

        self.assertIsNone(result["issue_visible"])
        self.assertEqual(result["overall_video_result"], "indeterminate")
        assessment = result["damage_causality_assessment"]
        self.assertEqual(assessment["damage_presence"], "uncertain")
        self.assertFalse(assessment["main_video_detail_sufficient"])
        self.assertEqual(
            assessment["evidence_source_summary"]["primary_video"]["damage_presence"],
            "uncertain",
        )

    def test_unknown_evidence_field_is_removed_before_decision_and_report(self) -> None:
        perception = self._complete_perception()
        perception["evidence_refs"].append({
            "field": "model_invented_field",
            "asset_ref": "native_video_1",
            "timestamp": "01:20.000",
            "fact": "模型返回了契约外字段。",
        })

        parsed = expand_native_video_perception(
            perception,
            {"scenario": "product_damage"},
            sampling_fps=1.0,
        )

        self.assertNotIn(
            "model_invented_field",
            {item.get("field") for item in parsed["evidence_refs"]},
        )
        self.assertNotIn(
            "model_invented_field",
            {item.get("evidence_field") for item in parsed["frame_findings"]},
        )

    def test_program_derives_overall_result_and_ignores_model_supplied_value(self) -> None:
        perception = self._complete_perception()
        perception["overall_video_result"] = "noncompliant"
        perception["has_speed_change"] = True
        perception["speed_assessment"].update({
            "value": "accelerated",
            "affects_visual_judgement": False,
        })

        parsed = expand_native_video_perception(
            perception,
            {"scenario": "product_damage"},
            sampling_fps=4.0,
        )

        self.assertEqual(parsed["overall_video_result"], "compliant")
        self.assertEqual(parsed["predicted_label"], "positive")

        perception["speed_assessment"]["affects_visual_judgement"] = True
        parsed = expand_native_video_perception(
            perception,
            {"scenario": "product_damage"},
            sampling_fps=4.0,
        )
        self.assertEqual(parsed["overall_video_result"], "indeterminate")
        self.assertEqual(parsed["predicted_label"], "review")

        perception["issue_visible"] = False
        perception["damage_assessment"]["visible_in_continuous_opening"] = False
        parsed = expand_native_video_perception(
            perception,
            {"scenario": "product_damage"},
            sampling_fps=4.0,
        )
        self.assertEqual(parsed["overall_video_result"], "noncompliant")
        self.assertEqual(parsed["predicted_label"], "negative")

    def test_direct_customer_action_without_three_stage_evidence_is_downgraded(self) -> None:
        perception = self._complete_perception()
        perception["damage_assessment"]["causal_evidence_refs"] = [
            {"stage": "after_action", "timestamp": "02:15.500", "fact": "仅看到最终损伤。"},
        ]

        parsed = expand_native_video_perception(
            perception,
            {"scenario": "product_damage"},
            sampling_fps=1.0,
        )

        causal = parsed["damage_causality_assessment"]
        self.assertEqual(causal["most_likely_origin"], "indeterminate")
        self.assertEqual(causal["causal_evidence_level"], "none")
        self.assertFalse(causal["damage_change_observed"])

    def test_direct_customer_action_without_contact_is_downgraded(self) -> None:
        perception = self._complete_perception()
        action = next(
            item
            for item in perception["damage_assessment"]["causal_evidence_refs"]
            if item["stage"] == "action"
        )
        action["action_relation"] = "no_contact"
        action["fact"] = "手在争议部位旁边悬停，未接触商品。"

        parsed = expand_native_video_perception(
            perception,
            {"scenario": "product_damage"},
            sampling_fps=1.0,
        )

        causal = parsed["damage_causality_assessment"]
        self.assertFalse(causal["damage_change_observed"])
        self.assertEqual(causal["most_likely_origin"], "indeterminate")
        self.assertEqual(causal["causal_action_relation"], "no_contact")

    def test_direct_customer_action_requires_same_ordered_subject_location_chain(self) -> None:
        perception = self._complete_perception()
        perception["damage_assessment"]["causal_evidence_refs"] = [
            {
                "stage": "before_action", "asset_ref": "native_video_1",
                "timestamp": "00:03.000", "subject": "争议商品", "location": "顶部",
                "chain_id": "chain-a", "damage_visible": False, "fact": "顶部未见伤。",
            },
            {
                "stage": "action", "asset_ref": "native_video_1",
                "timestamp": "00:02.000", "subject": "争议商品", "location": "侧面",
                "chain_id": "chain-a", "damage_visible": None, "fact": "手接触侧面。",
            },
            {
                "stage": "after_action", "asset_ref": "native_video_1",
                "timestamp": "00:01.000", "subject": "争议商品", "location": "底部",
                "chain_id": "chain-b", "damage_visible": True, "fact": "底部可见伤。",
            },
        ]

        parsed = expand_native_video_perception(
            perception,
            {"scenario": "product_damage"},
            sampling_fps=1.0,
        )

        causal = parsed["damage_causality_assessment"]
        self.assertFalse(causal["damage_change_observed"])
        self.assertEqual(causal["most_likely_origin"], "indeterminate")
        self.assertEqual(causal["claim_support"], "supported")

    def test_all_atomic_video_fields_require_native_timestamp_evidence(self) -> None:
        perception = self._complete_perception()
        perception["damage_assessment"].update({
            "causal_chain_status": "indeterminate",
            "causal_evidence_level": "none",
            "causal_evidence_refs": [],
        })
        perception["evidence_refs"] = [
            item for item in perception["evidence_refs"] if item["field"] != "has_offscreen"
        ]

        parsed = expand_native_video_perception(
            perception,
            {"scenario": "product_damage"},
            sampling_fps=1.0,
        )

        self.assertEqual(parsed["overall_video_result"], "indeterminate")
        self.assertEqual(parsed["predicted_label"], "review")
        self.assertNotIn(
            "has_offscreen",
            parsed["video_audit_conclusion"]["validated_atomic_fields"],
        )
        self.assertEqual(
            parsed["damage_causality_assessment"]["claim_support"],
            "supported",
            "独立离镜字段缺少引用应保留黄标，但不能推翻已由四项开箱硬门槛确认的伤点",
        )

    def test_unknown_speed_is_yellow_but_not_blocking_when_visual_judgement_is_clear(self) -> None:
        perception = self._complete_perception()
        perception["has_speed_change"] = None
        perception["speed_assessment"].update({
            "value": "unknown",
            "confidence": 0.55,
            "evidence_basis": "insufficient_observable_anchor",
            "affects_visual_judgement": False,
            "reason": "无法可靠判断是否加速，但争议商品和伤点均已清楚展示。",
        })

        parsed = expand_native_video_perception(
            perception,
            {"scenario": "product_damage"},
            sampling_fps=4.0,
        )

        self.assertEqual(parsed["overall_video_result"], "compliant")
        self.assertEqual(parsed["predicted_label"], "positive")
        self.assertEqual(
            parsed["video_audit_conclusion"]["speed_review_impact"]["status"],
            "uncertain",
        )
        self.assertTrue(
            parsed["video_audit_conclusion"]["speed_review_impact"]["critical_evidence_observable"]
        )

    def test_uncertain_detail_stays_yellow_and_does_not_invent_offscreen(self) -> None:
        perception = self._complete_perception()
        perception.update({
            "has_offscreen": None,
            "issue_visible": None,
            "overall_video_result": "indeterminate",
        })
        perception["claimed_item_assessment"].update({
            "first_visible_timestamp": "00:37.000",
            "last_visible_timestamp": "00:41.000",
            "presentation_complete": None,
            "offscreen_during_presentation": None,
        })
        perception["speed_assessment"].update({
            "value": "unknown",
            "affects_visual_judgement": True,
            "review_signal": "yellow",
        })
        perception["damage_assessment"]["visible_in_continuous_opening"] = None

        parsed = expand_native_video_perception(
            perception,
            {"scenario": "product_damage", "customer_claim": "摆件面具有红痕"},
            sampling_fps=4.0,
        )

        self.assertEqual(parsed["predicted_label"], "review")
        self.assertLessEqual(parsed["confidence"], 0.69)
        self.assertEqual(
            parsed["object_continuity_assessment"]["continuity_verdict"],
            "indeterminate",
        )
        self.assertEqual(
            parsed["video_audit_conclusion"]["speed_review_impact"]["status"],
            "uncertain",
        )
        self.assertEqual(
            parsed["damage_causality_assessment"]["claim_support"],
            "insufficient",
        )

    def test_detail_review_is_conditional_and_uses_model_discovered_timestamps(self) -> None:
        perception = self._complete_perception()
        perception["issue_visible"] = False
        perception["evidence_refs"].extend([
            {"field": "claimed_item", "timestamp": "00:09.750"},
            {"field": "claimed_item", "timestamp": "00:37.000"},
            {"field": "claimed_item", "timestamp": "00:41.000"},
        ])

        self.assertTrue(requires_claimed_item_detail(perception, "product_damage"))
        self.assertEqual(
            candidate_detail_timestamps(perception),
            [135.5, 111.0, 150.75, 9.75, 37.0, 41.0],
        )
        perception["issue_visible"] = True
        self.assertTrue(requires_claimed_item_detail(perception, "product_damage"))
        perception["issue_visible"] = False
        self.assertFalse(requires_claimed_item_detail(perception, "missing_item"))
        perception["evidence_refs"] = []
        perception["damage_assessment"]["timestamp"] = None
        perception["claimed_item_assessment"]["first_visible_timestamp"] = None
        perception["claimed_item_assessment"]["last_visible_timestamp"] = None
        self.assertFalse(requires_claimed_item_detail(perception, "product_damage"))

    def test_identity_and_detail_cases_keep_business_labels_out_of_video_prompt(self) -> None:
        case = {
            "native_video": {"api_path": "video.mp4"},
            "frames": [{"global_frame_index": 99}],
            "supplemental_images": [{"api_path": "claim.jpg"}],
            "official_reference_images": [{"api_path": "official.jpg"}],
            "structured_business_context": {},
        }

        identity = build_claim_identity_case(case)
        self.assertNotIn("native_video", identity)
        self.assertEqual(identity["frames"], [])
        self.assertEqual(
            identity["structured_business_context"]["analysis_mode"],
            "claim_identity_only",
        )

        detail = build_candidate_detail_case(
            case,
            [{"frame_index": 7, "timestamp_seconds": 37.0, "path": Path("37.jpg")}],
        )
        self.assertNotIn("native_video", detail)
        self.assertEqual(len(detail["frames"]), 1)
        self.assertEqual(detail["frames"][0]["timestamp"], "00:37.00")
        self.assertEqual(
            detail["structured_business_context"]["analysis_mode"],
            "claimed_item_detail_only",
        )

    def test_pipeline_keeps_identity_assets_in_the_only_full_video_call(self) -> None:
        perception = self._complete_perception()
        perception.update({"issue_visible": False, "overall_video_result": "noncompliant"})
        perception["damage_assessment"]["visible_in_continuous_opening"] = False
        perception["evidence_refs"].extend([
            {"field": "claimed_item", "asset_ref": "native_video_1", "timestamp": "00:09.750", "fact": "相似商品候选"},
            {"field": "claimed_item", "asset_ref": "native_video_1", "timestamp": "00:37.000", "fact": "目标商品候选"},
        ])
        modes = []

        def invoke(current: dict) -> dict:
            mode = current["structured_business_context"]["analysis_mode"]
            modes.append(mode)
            if mode == "claim_identity_only":
                parsed = {
                    "match_status": "matched",
                    "confidence": 0.96,
                    "expected_order_item": {
                        "item_ref": "LINE-1",
                        "sku": "SKU-1",
                        "product_name": "目标摆件",
                        "specification": "",
                    },
                }
            elif mode == "claimed_item_detail_only":
                parsed = {
                    "identity_match": "matched",
                    "identity_confidence": 0.95,
                    "issue_visibility": "uncertain",
                    "issue_confidence": 0.8,
                    "issue_location": "面具",
                    "presentation_quality": "partial",
                    "evidence_refs": [
                        {
                            "global_frame_index": 1,
                            "timestamp": "00:37.00",
                            "identity_fact": "身份匹配",
                            "issue_fact": "红痕不清晰",
                        }
                    ],
                    "reason": "目标商品短暂出现，伤点仍不清晰。",
                }
            else:
                parsed = perception
                self.assertEqual(current["native_video"]["sampling_fps"], 4.0)
                self.assertEqual(current["supplemental_images"], case["supplemental_images"])
                self.assertEqual(
                    current["official_reference_images"],
                    case["official_reference_images"],
                )
            return {
                "status": "success",
                "parsed": parsed,
                "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
                "cost": {"estimated_usd": 0.01, "currency": "USD", "amount": 0.01},
            }

        case = {
            "scenario": "product_damage",
            "customer_claim": "目标摆件面具有红痕",
            "native_video": {"api_path": "video.mp4"},
            "frames": [],
            "supplemental_images": [{"api_path": "claim.jpg"}],
            "official_reference_images": [{"api_path": "official.jpg", "item_ref": "LINE-1"}],
            "structured_business_context": {},
        }
        with TemporaryDirectory() as temp_dir, patch(
            "poc.visual_review_poc.native_video_perception.extract_candidate_frames",
            return_value=[{"frame_index": 1, "timestamp_seconds": 37.0, "path": Path(temp_dir) / "37.jpg"}],
        ):
            result, prepared = run_native_perception_pipeline(
                case,
                Path("video.mp4"),
                Path(temp_dir),
                invoke,
                sampling_fps=4.0,
            )

        self.assertEqual(
            modes,
            ["native_video_perception"],
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["usage"]["total_tokens"], 2)
        self.assertEqual(result["perception_pipeline"]["model_calls"], 1)
        self.assertEqual(
            sum(
                item["total_tokens"]
                for item in result["perception_pipeline"]["channels"].values()
            ),
            2,
        )
        self.assertNotIn(
            "continuity_claim_identity",
            prepared["structured_business_context"],
        )

    def test_pipeline_never_invokes_a_second_recovery_model(self) -> None:
        wrong_candidate = self._complete_perception()
        wrong_candidate["claimed_item_assessment"].update({
            "identity_description": "相似摆件",
            "first_visible_timestamp": "00:10.000",
            "last_visible_timestamp": "00:12.000",
        })
        wrong_candidate["damage_assessment"]["timestamp"] = "00:10.000"
        wrong_candidate["evidence_refs"] = [
            {
                "field": "claimed_item",
                "asset_ref": "native_video_1",
                "timestamp": "00:10.000",
                "fact": "相似商品候选",
            }
        ]
        recovered_candidate = self._complete_perception()
        recovered_candidate["claimed_item_assessment"].update({
            "identity_description": "目标摆件",
            "first_visible_timestamp": "00:37.000",
            "last_visible_timestamp": "00:38.000",
        })
        recovered_candidate["damage_assessment"]["timestamp"] = "00:37.500"
        recovered_candidate["evidence_refs"] = [
            {
                "field": "claimed_item",
                "asset_ref": "native_video_1",
                "timestamp": "00:37.000",
                "fact": "目标商品候选",
            }
        ]
        primary_modes = []
        recovery_modes = []

        def primary_invoke(current: dict) -> dict:
            mode = current["structured_business_context"]["analysis_mode"]
            primary_modes.append(mode)
            if mode == "claim_identity_only":
                parsed = {
                    "match_status": "matched",
                    "confidence": 0.98,
                    "expected_order_item": {
                        "item_ref": "LINE-1",
                        "sku": "SKU-1",
                        "product_name": "目标摆件",
                        "specification": "45mm",
                    },
                }
            elif mode == "claimed_item_detail_only":
                parsed = {
                    "identity_match": "uncertain",
                    "identity_confidence": 0.99,
                    "issue_visibility": "uncertain",
                    "issue_confidence": 0.8,
                    "presentation_quality": "clear",
                    "evidence_refs": [{"timestamp": "00:10.00"}],
                    "reason": "候选帧是另一件相似商品。",
                }
            else:
                parsed = wrong_candidate
            return {
                "status": "success",
                "parsed": parsed,
                "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
                "cost": {"estimated_usd": 0.01, "currency": "USD", "amount": 0.01},
            }

        def recovery_invoke(current: dict) -> dict:
            mode = current["structured_business_context"]["analysis_mode"]
            recovery_modes.append(mode)
            if mode == "native_video_perception":
                self.assertEqual(
                    current["structured_business_context"]["identity_recovery"][
                        "rejected_candidate_timestamps"
                    ],
                    [10.0],
                )
                parsed = recovered_candidate
            else:
                parsed = {
                    "identity_match": "matched",
                    "identity_confidence": 0.99,
                    "issue_visibility": "visible",
                    "issue_confidence": 0.95,
                    "issue_location": "白色面具",
                    "presentation_quality": "clear",
                    "evidence_refs": [{"timestamp": "00:37.50"}],
                    "reason": "候选帧与目标商品一致，红痕清晰可见。",
                }
            return {
                "status": "success",
                "parsed": parsed,
                "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
                "cost": {"estimated_usd": 0.01, "currency": "USD", "amount": 0.01},
            }

        case = {
            "scenario": "product_damage",
            "customer_claim": "目标摆件面具有红痕",
            "native_video": {"api_path": "video.mp4"},
            "frames": [],
            "supplemental_images": [{"api_path": "claim.jpg"}],
            "official_reference_images": [{"api_path": "official.jpg", "item_ref": "LINE-1"}],
            "structured_business_context": {},
        }
        with TemporaryDirectory() as temp_dir, patch(
            "poc.visual_review_poc.native_video_perception.extract_candidate_frames",
            return_value=[{"frame_index": 1, "timestamp_seconds": 37.5, "path": Path(temp_dir) / "37.jpg"}],
        ):
            result, _ = run_native_perception_pipeline(
                case,
                Path("video.mp4"),
                Path(temp_dir),
                primary_invoke,
                sampling_fps=4.0,
            )

        self.assertEqual(
            primary_modes,
            ["native_video_perception"],
        )
        self.assertEqual(recovery_modes, [])
        self.assertEqual(
            result["parsed"]["claimed_item_assessment"]["first_visible_timestamp"],
            "00:10.000",
        )
        self.assertEqual(result["perception_pipeline"]["model_calls"], 1)
        self.assertNotIn("identity_recovery", result)

    def test_workbench_routes_selected_flash36_profile_through_compact_pipeline(self) -> None:
        from poc.visual_review_poc import workbench_server

        uncertain = self._complete_perception()
        expanded = expand_native_video_perception(
            uncertain,
            {"scenario": "product_damage"},
            sampling_fps=4.0,
        )

        with TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "evidence.mp4"
            video.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 64)

            def load_bundle(_sample_dir, _args, _run_dir, scenario_override="", native_video=None):
                return {
                    "case_id": "CASE-FLASH36-COMPACT",
                    "scenario": scenario_override,
                    "scenario_label": "商品有伤审核",
                    "customer_claim": "商品有划痕",
                    "videos": [{"file": video.name}],
                    "frames": [{"video_index": 1, "global_frame_index": 1, "timestamp": "00:00.00"}],
                    "supplemental_images": [],
                    "official_reference_images": [],
                    "native_video": dict(native_video or {}),
                    "structured_business_context": {},
                }

            pipeline_result = {
                "status": "success",
                "parsed": expanded,
                "parsed_before_boundary": expanded,
                "perception_pipeline": {"model_calls": 1, "channels": {}},
                "model_latency_seconds_sum": 6.0,
            }
            captured = {}

            def capture(_case, _sample_dir, model_result, *_args, **_kwargs):
                captured.update(model_result)
                return {"summary": {"review_status": "completed"}, "agent_report": {}}
            with patch.dict(
                os.environ,
                {"VISUAL_REVIEW_PRIMARY_MODEL": "gemini-3.5-flash-lite"},
                clear=False,
            ), patch.object(workbench_server, "load_visual_env"), patch.object(
                workbench_server, "discover_case_videos", return_value=([video], {})
            ), patch.object(
                workbench_server,
                "_native_video_source",
                return_value={"api_path": str(video), "api_mime_type": "video/mp4"},
            ), patch.object(
                workbench_server, "load_case_bundle", side_effect=load_bundle
            ), patch.object(
                workbench_server, "apply_frontdesk_context", side_effect=lambda current, *_: current
            ), patch.object(
                workbench_server, "prepare_official_reference_images", side_effect=lambda current: current
            ), patch.object(
                workbench_server,
                "run_native_perception_pipeline",
                create=True,
                return_value=(pipeline_result, load_bundle(video.parent, None, None, "product_damage", {"api_path": str(video)})),
            ) as pipeline, patch.object(
                workbench_server, "call_model", return_value=pipeline_result
            ) as legacy_model, patch.object(
                workbench_server,
                "native_dimension_gaps",
                return_value=[],
            ), patch.object(
                workbench_server,
                "call_opening_start_verification",
            ) as opening_model, patch.object(
                workbench_server, "call_opening_compliance_verification"
            ) as compliance_model, patch.object(
                workbench_server,
                "_agent_report_response",
                side_effect=capture,
            ):
                result = workbench_server._run_review(
                    video,
                    "product_damage",
                    1.0,
                    24,
                    24,
                    12,
                    "standard",
                    {},
                )

        self.assertTrue(result["ok"])
        self.assertEqual(pipeline.call_count, 1)
        self.assertEqual(legacy_model.call_count, 0)
        self.assertEqual(opening_model.call_count, 0)
        self.assertEqual(compliance_model.call_count, 0)
        self.assertEqual(captured["chunking"]["total_model_calls"], 1)
        self.assertEqual(captured["model_latency_seconds_sum"], 6.0)

    def test_successful_native_review_keeps_partial_facts_without_frame_fallback(self) -> None:
        from poc.visual_review_poc import workbench_server

        partial = expand_native_video_perception(
            self._complete_perception(),
            {"scenario": "product_damage"},
            sampling_fps=1.0,
        )
        partial["claim_fact_assessment"] = {}
        pipeline_result = {
            "status": "success",
            "parsed": partial,
            "parsed_before_boundary": partial,
            "perception_pipeline": {"model_calls": 1, "channels": {}},
            "model_latency_seconds_sum": 6.0,
        }

        with TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "evidence.mp4"
            video.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 64)

            def load_bundle(_sample_dir, _args, _run_dir, scenario_override="", native_video=None):
                return {
                    "case_id": "CASE-NATIVE-PARTIAL",
                    "scenario": scenario_override,
                    "scenario_label": "商品有伤审核",
                    "customer_claim": "商品有划痕",
                    "videos": [{"file": video.name}],
                    "frames": [{"video_index": 1, "global_frame_index": 1, "timestamp": "00:00.00"}],
                    "supplemental_images": [],
                    "official_reference_images": [],
                    "native_video": dict(native_video or {}),
                    "structured_business_context": {},
                }

            captured = {}

            def capture(_case, _sample_dir, model_result, *_args, **_kwargs):
                captured.update(model_result)
                return {"summary": {"review_status": "completed"}, "agent_report": {}}

            with patch.dict(
                os.environ,
                {"VISUAL_REVIEW_PRIMARY_MODEL": "gemini-3.5-flash-lite"},
                clear=False,
            ), patch.object(workbench_server, "load_visual_env"), patch.object(
                workbench_server, "discover_case_videos", return_value=([video], {})
            ), patch.object(
                workbench_server,
                "_native_video_source",
                return_value={"api_path": str(video), "api_mime_type": "video/mp4"},
            ), patch.object(
                workbench_server, "load_case_bundle", side_effect=load_bundle
            ), patch.object(
                workbench_server, "apply_frontdesk_context", side_effect=lambda current, *_: current
            ), patch.object(
                workbench_server, "prepare_official_reference_images", side_effect=lambda current: current
            ), patch.object(
                workbench_server,
                "run_native_perception_pipeline",
                return_value=(pipeline_result, load_bundle(video.parent, None, None, "product_damage", {"api_path": str(video)})),
            ), patch.object(
                workbench_server,
                "native_dimension_gaps",
                return_value=["claim_facts"],
            ), patch.object(
                workbench_server, "_call_model_chunked_with_fallback"
            ) as frame_fallback, patch.object(
                workbench_server,
                "_agent_report_response",
                side_effect=capture,
            ):
                result = workbench_server._run_review(
                    video,
                    "product_damage",
                    1.0,
                    24,
                    24,
                    12,
                    "standard",
                    {},
                )

        self.assertTrue(result["ok"])
        self.assertEqual(frame_fallback.call_count, 0)
        self.assertEqual(captured["parsed"], partial)
        self.assertEqual(
            captured["chunking"]["native_video"]["status"],
            "completed_with_review_gaps",
        )
        self.assertEqual(
            captured["chunking"]["native_video"]["dimension_gaps"],
            ["claim_facts"],
        )
        self.assertEqual(result["sampling"]["sampling_mode"], "native_video")

    def test_claimed_item_identity_window_gap_requires_one_fps_frame_fallback(self) -> None:
        from poc.visual_review_poc import workbench_server

        self.assertFalse(
            workbench_server._native_success_requires_frame_fallback(
                ["claimed_item_identity_window"]
            )
        )
        self.assertFalse(
            workbench_server._native_success_requires_frame_fallback(["claim_facts"])
        )

    def test_one_fps_frame_fallback_is_disabled_by_default(self) -> None:
        from poc.visual_review_poc import workbench_server

        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(workbench_server._one_fps_frame_fallback_enabled())

        with patch.dict(
            "os.environ", {"REVIEW_ENABLE_ONE_FPS_FRAME_FALLBACK": "true"}, clear=True
        ):
            self.assertTrue(workbench_server._one_fps_frame_fallback_enabled())

    def test_missing_item_single_unreferenced_true_opening_fact_requires_one_fps_fallback(self) -> None:
        from poc.visual_review_poc import workbench_server

        fields = (
            "sealed_start",
            "waybill_visible",
            "waybill_matches_order",
            "single_take_continuity",
            "opening_complete",
            "all_contents_laid_out",
        )
        parsed = {
            "fulfillment_reconciliation": {
                "evidence_route": "insufficient",
                "package_observations": [{
                    "package_ref": "ORDER-PACKAGE-001",
                    **{field: True for field in fields},
                    "evidence_refs": [
                        {
                            "asset_ref": "native_video_1",
                            "timestamp": "00:08.00",
                            "field": field,
                            "fact": "可从原视频回看。",
                        }
                        for field in fields
                        if field != "all_contents_laid_out"
                    ] + [{
                        "asset_ref": "supplemental_image_1",
                        "timestamp": None,
                        "field": "all_contents_laid_out",
                        "fact": "补图中可见全部实物。",
                    }],
                }],
            },
        }
        current_case = {
            "structured_business_context": {
                "frontdesk_evidence_package": {
                    "fulfillment_baseline": {
                        "packages": [{"package_ref": "ORDER-PACKAGE-001"}],
                    },
                },
            },
        }

        self.assertTrue(
            workbench_server._native_success_requires_frame_fallback(
                [], parsed, current_case, "missing_item"
            )
        )

        parsed["fulfillment_reconciliation"]["package_observations"][0]["waybill_visible"] = False
        self.assertFalse(
            workbench_server._native_success_requires_frame_fallback(
                [], parsed, current_case, "missing_item"
            )
        )
        parsed["fulfillment_reconciliation"]["package_observations"][0]["waybill_visible"] = True
        parsed["fulfillment_reconciliation"]["package_observations"][0]["evidence_refs"] = [
            ref
            for ref in parsed["fulfillment_reconciliation"]["package_observations"][0]["evidence_refs"]
            if ref["field"] != "opening_complete"
        ]
        self.assertFalse(
            workbench_server._native_success_requires_frame_fallback(
                [], parsed, current_case, "missing_item"
            )
        )

    def test_controlled_one_fps_fallback_profile_is_explicit_and_bounded(self) -> None:
        from poc.visual_review_poc import workbench_server

        source_args = SimpleNamespace(
            fps=0.25,
            sampling_mode="adaptive",
            max_frames_per_video=24,
            api_frame_limit=12,
            probe_seconds=12.0,
            frame_width=960,
            supplemental_image_limit=12,
        )
        fallback = workbench_server._complete_frame_fallback_args(source_args)

        self.assertEqual(fallback.fps, 1.0)
        self.assertEqual(fallback.sampling_mode, "dense")
        self.assertEqual(fallback.max_frames_per_video, 1800)
        self.assertEqual(fallback.api_frame_limit, 24)
        self.assertEqual(fallback.frame_width, 1920)
        self.assertEqual(fallback.probe_seconds, source_args.probe_seconds)
        self.assertEqual(
            fallback.supplemental_image_limit,
            source_args.supplemental_image_limit,
        )

    def test_compact_pipeline_is_scoped_to_product_damage(self) -> None:
        from poc.visual_review_poc import workbench_server

        config = {"native_perception_pipeline": True}
        self.assertTrue(workbench_server._native_perception_enabled(config, "product_damage"))
        for scenario in ("video_unboxing", "wrong_item", "missing_item"):
            with self.subTest(scenario=scenario):
                self.assertFalse(workbench_server._native_perception_enabled(config, scenario))

    def test_workbench_prefers_ephemeral_original_url_for_large_video(self) -> None:
        from poc.visual_review_poc import workbench_server

        lifecycle = []

        class Tunnel:
            url = "https://unit-test.trycloudflare.com/media/token"
            diagnostics = {"status": "ready", "media_bytes": 64}

        @contextmanager
        def fake_tunnel(_video, **_kwargs):
            lifecycle.append("opened")
            try:
                yield Tunnel()
            finally:
                lifecycle.append("closed")

        with TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "large.mp4"
            video.write_bytes(b"x" * 64)
            with patch.dict(
                os.environ,
                {
                    "VISUAL_WORKBENCH_PUBLIC_BASE_URL": "",
                    "VISUAL_REVIEW_EPHEMERAL_TUNNEL": "1",
                },
                clear=False,
            ), patch.object(
                workbench_server, "NATIVE_INLINE_MEDIA_MAX_BYTES", 1
            ), patch.object(
                workbench_server, "open_secure_media_tunnel", side_effect=fake_tunnel, create=True
            ), patch.object(
                workbench_server, "prepare_native_video_proxy"
            ) as proxy:
                with workbench_server._native_video_source_context(
                    video,
                    Path(temp_dir) / "proxy",
                ) as source:
                    self.assertEqual(lifecycle, ["opened"])
                    self.assertEqual(source["file_uri"], Tunnel.url)
                    self.assertEqual(source["transport"], "ephemeral_original_url")

        self.assertEqual(lifecycle, ["opened", "closed"])
        self.assertEqual(proxy.call_count, 0)

    def test_workbench_keeps_regular_video_inline_without_starting_tunnel(self) -> None:
        from poc.visual_review_poc import workbench_server

        lifecycle = []

        class Tunnel:
            url = "https://unit-test.trycloudflare.com/media/token"
            diagnostics = {"status": "ready", "media_bytes": 64}

        @contextmanager
        def fake_tunnel(_video, **_kwargs):
            lifecycle.append("opened")
            try:
                yield Tunnel()
            finally:
                lifecycle.append("closed")

        with TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "regular.mp4"
            video.write_bytes(b"x" * 64)
            with patch.dict(
                os.environ,
                {
                    "VISUAL_WORKBENCH_PUBLIC_BASE_URL": "",
                    "VISUAL_REVIEW_EPHEMERAL_TUNNEL": "1",
                },
                clear=False,
            ), patch.object(
                workbench_server, "NATIVE_INLINE_MEDIA_MAX_BYTES", 1024
            ), patch.object(
                workbench_server, "open_secure_media_tunnel", side_effect=fake_tunnel
            ), patch.object(
                workbench_server, "prepare_native_video_proxy"
            ) as proxy:
                with workbench_server._native_video_source_context(
                    video,
                    Path(temp_dir) / "proxy",
                ) as source:
                    self.assertEqual(lifecycle, [])
                    self.assertEqual(source["api_path"], str(video))
                    self.assertEqual(source["transport"], "raw_original_inline")

        self.assertEqual(lifecycle, [])
        self.assertEqual(proxy.call_count, 0)

    def test_workbench_falls_back_to_quality_proxy_when_tunnel_is_unavailable(self) -> None:
        from poc.visual_review_poc import workbench_server

        @contextmanager
        def failed_tunnel(_video, **_kwargs):
            raise RuntimeError("cloudflared unavailable")
            yield

        with TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "large.mp4"
            proxy_path = Path(temp_dir) / "proxy.webm"
            video.write_bytes(b"x" * 64)
            proxy_path.write_bytes(b"webm")
            with patch.dict(
                os.environ,
                {
                    "VISUAL_WORKBENCH_PUBLIC_BASE_URL": "",
                    "VISUAL_REVIEW_EPHEMERAL_TUNNEL": "1",
                },
                clear=False,
            ), patch.object(
                workbench_server, "NATIVE_INLINE_MEDIA_MAX_BYTES", 1
            ), patch.object(
                workbench_server, "open_secure_media_tunnel", side_effect=failed_tunnel, create=True
            ), patch.object(
                workbench_server,
                "prepare_native_video_proxy",
                return_value={
                    "status": "ready",
                    "path": str(proxy_path),
                    "mime_type": "video/webm",
                },
            ):
                with workbench_server._native_video_source_context(
                    video,
                    Path(temp_dir) / "proxy",
                ) as source:
                    self.assertEqual(source["api_path"], str(proxy_path))
                    self.assertEqual(source["api_mime_type"], "video/webm")
                    self.assertEqual(source["transport"], "full_duration_quality_proxy")
                    self.assertEqual(source["tunnel"]["status"], "unavailable")

    def test_quality_proxy_url_uses_url_budget_instead_of_inline_budget(self) -> None:
        from poc.visual_review_poc import workbench_server

        class Tunnel:
            url = "https://unit-test.trycloudflare.com/media/proxy"
            diagnostics = {"status": "ready"}

        @contextmanager
        def fake_tunnel(_video, **_kwargs):
            yield Tunnel()

        with TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "source.mp4"
            proxy = Path(temp_dir) / "proxy.mp4"
            video.write_bytes(b"x" * 128)
            proxy.write_bytes(b"y" * 64)
            with patch.object(
                workbench_server, "NATIVE_INLINE_MEDIA_MAX_BYTES", 32
            ), patch.object(
                workbench_server, "NATIVE_URL_MEDIA_MAX_BYTES", 96
            ), patch.object(
                workbench_server,
                "prepare_native_video_proxy",
                return_value={
                    "status": "ready",
                    "path": str(proxy),
                    "mime_type": "video/mp4",
                    "proxy_bytes": proxy.stat().st_size,
                },
            ) as prepare_proxy, patch.object(
                workbench_server, "open_secure_media_tunnel", side_effect=fake_tunnel
            ):
                with workbench_server._native_video_proxy_source_context(
                    video,
                    Path(temp_dir) / "prepared",
                ) as source:
                    self.assertEqual(source["file_uri"], Tunnel.url)

        self.assertEqual(prepare_proxy.call_args.args[2], 96)

    def test_quality_proxy_source_keeps_the_trigger_reasons_for_public_audit(self) -> None:
        from poc.visual_review_poc import workbench_server

        @contextmanager
        def fake_proxy_source(*_args, **_kwargs):
            yield {
                "video_index": 1,
                "api_path": "proxy.mp4",
                "api_mime_type": "video/mp4",
                "transport": "full_duration_quality_proxy",
                "proxy": {"status": "ready", "proxy_bytes": 70_000_000},
            }

        recommendation = {
            "recommended": True,
            "reasons": ["source_above_100mb", "resolution_above_2k"],
        }
        with TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "source.mp4"
            video.write_bytes(b"video")
            with patch.object(
                workbench_server,
                "video_proxy_recommendation",
                return_value=recommendation,
            ), patch.object(
                workbench_server,
                "_native_video_proxy_source_context",
                side_effect=fake_proxy_source,
            ):
                with workbench_server._native_video_source_context(
                    video,
                    Path(temp_dir) / "prepared",
                ) as source:
                    self.assertEqual(source["quality_recommendation"], recommendation)

    def test_workbench_retries_native_review_with_proxy_url_after_provider_decode_rejection(self) -> None:
        from poc.visual_review_poc import workbench_server

        @contextmanager
        def original_source(*_args, **_kwargs):
            yield {
                "video_index": 1,
                "file_uri": "https://unit-test.trycloudflare.com/media/original",
                "api_mime_type": "video/mp4",
                "transport": "ephemeral_original_url",
            }

        @contextmanager
        def proxy_source(*_args, **_kwargs):
            yield {
                "video_index": 1,
                "file_uri": "https://unit-test.trycloudflare.com/media/proxy",
                "api_mime_type": "video/webm",
                "transport": "ephemeral_proxy_url",
                "proxy": {"status": "ready", "codec_profile": "vp9_webm"},
            }

        def load_bundle(sample_dir, _args, _run_dir, scenario_override=None, native_video=None):
            return {
                "case_id": sample_dir.name,
                "scenario": scenario_override,
                "scenario_label": "商品有伤",
                "frames": [],
                "supplemental_images": [],
                "official_reference_images": [],
                "native_video": dict(native_video or {}),
                "structured_business_context": {},
            }

        failed = {
            "status": "failed",
            "status_code": 400,
            "error_type": "hard",
            "error": "Unable to decode video codec from supplied file URI",
        }
        succeeded = {
            "status": "success",
            "parsed": self._complete_perception(),
            "parsed_before_boundary": self._complete_perception(),
            "perception_pipeline": {"model_calls": 3, "channels": {}},
        }

        with TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "large.mp4"
            video.write_bytes(b"video")
            with patch.dict(
                os.environ,
                {"VISUAL_REVIEW_PRIMARY_MODEL": "gemini-3.5-flash-lite"},
                clear=False,
            ), patch.object(
                workbench_server, "load_visual_env"
            ), patch.object(
                workbench_server, "discover_case_videos", return_value=([video], {})
            ), patch.object(
                workbench_server, "_native_video_source_context", side_effect=original_source
            ), patch.object(
                workbench_server,
                "_native_video_proxy_source_context",
                side_effect=proxy_source,
                create=True,
            ) as proxy_context, patch.object(
                workbench_server, "load_case_bundle", side_effect=load_bundle
            ), patch.object(
                workbench_server, "apply_frontdesk_context", side_effect=lambda current, *_: current
            ), patch.object(
                workbench_server, "prepare_official_reference_images", side_effect=lambda current: current
            ), patch.object(
                workbench_server,
                "run_native_perception_pipeline",
                side_effect=lambda case, *_args, **_kwargs: (
                    failed if case["native_video"]["file_uri"].endswith("original") else succeeded,
                    case,
                ),
            ) as pipeline, patch.object(
                workbench_server, "native_dimension_gaps", return_value=[]
            ), patch.object(
                workbench_server, "call_opening_start_verification", return_value={"status": "skipped"}
            ), patch.object(
                workbench_server,
                "_agent_report_response",
                return_value={"summary": {"review_status": "completed"}, "agent_report": {}},
            ):
                result = workbench_server._run_review(
                    video,
                    "product_damage",
                    1.0,
                    24,
                    24,
                    12,
                    "standard",
                    {},
                )

        self.assertTrue(result["ok"])
        self.assertEqual(proxy_context.call_count, 1)
        self.assertEqual(pipeline.call_count, 2)

    def test_schema_failure_never_triggers_video_transcode_retry(self) -> None:
        from poc.visual_review_poc import workbench_server

        self.assertFalse(
            workbench_server._native_transport_requires_proxy_retry(
                {
                    "status": "failed",
                    "status_code": 400,
                    "error": "Invalid response_schema for file_uri input",
                }
            )
        )

    def test_original_video_read_timeout_retries_quality_proxy_before_frames(self) -> None:
        from poc.visual_review_poc import workbench_server

        self.assertTrue(
            workbench_server._native_transport_requires_proxy_retry(
                {
                    "status": "failed",
                    "error_type": "TimeoutError",
                    "error": "The read operation timed out while fetching file_uri",
                }
            )
        )

    def test_native_model_call_count_uses_compact_pipeline_aggregate(self) -> None:
        from poc.visual_review_poc import workbench_server

        self.assertEqual(
            workbench_server._native_model_call_count(
                {
                    "status": "failed",
                    "perception_pipeline": {"model_calls": 3},
                }
            ),
            3,
        )
        self.assertEqual(
            workbench_server._native_model_call_count({"status": "skipped"}),
            0,
        )

    def test_native_model_call_count_prefers_physical_http_requests(self) -> None:
        from poc.visual_review_poc import workbench_server

        self.assertEqual(
            workbench_server._native_model_call_count(
                {
                    "status": "success",
                    "model_http_request_count": 2,
                    "perception_pipeline": {"model_calls": 1},
                }
            ),
            2,
        )


if __name__ == "__main__":
    unittest.main()
