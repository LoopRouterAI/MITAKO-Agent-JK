from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from PIL import Image

from poc.visual_review_poc.model_selection_e2e import call_model_chunked, gemini_payload, openai_messages, post_with_retries
from poc.visual_review_poc.review_model_prompt import build_selection_prompt
from poc.visual_review_poc.specialized_model_pass import run_specialized_frame_pass


def _visibility(index: int, subject_id: str) -> str:
    if subject_id == "product_package" and 3 <= index <= 5:
        return "out_of_frame"
    if subject_id == "claimed_item" and index < 6:
        return "not_yet_exposed"
    return "visible"


class ContinuityModelPassTest(unittest.TestCase):
    def test_provider_connect_timeout_is_bounded_separately_from_inference_timeout(self):
        client = MagicMock()
        client.__enter__.return_value.post.side_effect = TimeoutError("connect timeout")
        with patch("poc.visual_review_poc.model_selection_e2e.httpx.Client", return_value=client) as factory:
            result = post_with_retries("https://example.invalid", {}, {}, timeout=180, retries=0)

        configured_timeout = factory.call_args.kwargs["timeout"]
        self.assertEqual(configured_timeout.connect, 10.0)
        self.assertEqual(configured_timeout.read, 180.0)
        self.assertFalse(result["ok"])

    def test_openai_compatible_continuity_uses_24_individual_frames_per_call(self):
        case = dict(self.case)
        case["frames"] = [
            {
                "global_frame_index": index,
                "video_index": 1,
                "video_file": "sample.mp4",
                "timestamp": f"00:{index - 1:02d}.00",
                "file": f"frame_{index}.jpg",
            }
            for index in range(1, 50)
        ]
        structured = dict(self.case["structured_business_context"])
        structured["continuity_policy"] = {"force_dense_scan": True}
        structured["damage_causality_policy"] = {"force_action_scan": False}
        case["structured_business_context"] = structured
        observed = []

        def recording_call(cfg, current_case, timeout, retries):
            current_structured = current_case.get("structured_business_context") or {}
            if current_structured.get("analysis_mode") == "object_continuity_only":
                observed.append({
                    "targets": list(current_structured.get("continuity_target_frame_indices") or []),
                    "has_contact_sheet": bool(current_case.get("model_images_override")),
                })
            return self._fake_call(cfg, current_case, timeout, retries)

        with patch.dict("os.environ", {"REVIEW_CONTINUITY_FRAMES_PER_CALL": "48"}, clear=False), patch(
            "poc.visual_review_poc.model_selection_e2e.call_model", side_effect=recording_call
        ):
            result = call_model_chunked({"provider": "openai_compatible"}, case, timeout=30, retries=0)

        self.assertEqual([len(item["targets"]) for item in observed], [24, 24, 1])
        self.assertTrue(all(not item["has_contact_sheet"] for item in observed))
        self.assertEqual(result["chunking"]["continuity_pass"]["segment_count"], 3)

    def test_gemini_native_continuity_also_uses_24_individual_frames_per_call(self):
        case = dict(self.case)
        case["frames"] = [
            {
                "global_frame_index": index,
                "video_index": 1,
                "video_file": "sample.mp4",
                "timestamp": f"00:{index - 1:02d}.00",
                "file": f"frame_{index}.jpg",
            }
            for index in range(1, 50)
        ]
        structured = dict(self.case["structured_business_context"])
        structured["continuity_policy"] = {"force_dense_scan": True}
        structured["damage_causality_policy"] = {"force_action_scan": False}
        case["structured_business_context"] = structured
        observed = []

        def recording_call(cfg, current_case, timeout, retries):
            current_structured = current_case.get("structured_business_context") or {}
            if current_structured.get("analysis_mode") == "object_continuity_only":
                observed.append({
                    "targets": list(current_structured.get("continuity_target_frame_indices") or []),
                    "has_contact_sheet": bool(current_case.get("model_images_override")),
                })
            return self._fake_call(cfg, current_case, timeout, retries)

        with patch.dict("os.environ", {"REVIEW_CONTINUITY_FRAMES_PER_CALL": "48"}, clear=False), patch(
            "poc.visual_review_poc.model_selection_e2e.call_model", side_effect=recording_call
        ):
            result = call_model_chunked({"provider": "gemini_native"}, case, timeout=30, retries=0)

        self.assertEqual([len(item["targets"]) for item in observed], [24, 24, 1])
        self.assertTrue(all(not item["has_contact_sheet"] for item in observed))
        self.assertEqual(result["chunking"]["continuity_pass"]["segment_count"], 3)

    def test_missing_damage_assessment_preserves_frame_evidence_as_unknown_summary(self):
        frames = self.frames[:4]

        def findings_without_assessment(current_case):
            targets = (current_case.get("structured_business_context") or {}).get(
                "causality_target_frame_indices"
            ) or []
            return {
                "status": "success",
                "parsed": {
                    "frame_findings": [
                        {
                            "global_frame_index": index,
                            "timestamp": f"00:0{index - 1}.00",
                            "visible_facts": "逐帧可见事实",
                        }
                        for index in targets
                    ]
                },
                "usage": {},
                "cost": {},
                "cost_status": "estimated",
            }

        results, failures = run_specialized_frame_pass(
            {**self.case, "frames": frames},
            mode="damage_causality_only",
            target_index_key="causality_target_frame_indices",
            chunk_size=4,
            context_frame_count=1,
            workers=1,
            invoke=findings_without_assessment,
            preserve_partial_coverage=True,
        )

        self.assertEqual(failures, [])
        self.assertEqual(results[0]["coverage_status"], "partial_unknown")
        self.assertEqual(results[0]["assessment_status"], "model_output_missing")
        assessment = results[0]["parsed"]["damage_causality_assessment"]
        self.assertEqual(assessment["damage_presence"], "uncertain")
        self.assertEqual(assessment["claim_support"], "insufficient")

    def setUp(self) -> None:
        self.frames = [
            {
                "global_frame_index": index,
                "video_index": 1,
                "video_file": "sample.mp4",
                "timestamp": f"00:0{index - 1}.00",
                "file": f"frame_{index}.jpg",
            }
            for index in range(1, 9)
        ]
        self.case = {
            "case_id": "continuity-orchestration-test",
            "scenario": "product_damage",
            "scenario_label": "商品有伤",
            "customer_claim": "商品有伤",
            "frames": self.frames,
            "videos": [{"video_index": 1, "file": "sample.mp4"}],
            "supplemental_images": [],
            "model_frames_per_call": 24,
            "structured_business_context": {
                "business_scenario": "product_damage",
                "continuity_policy": {
                    "force_dense_scan": True,
                    "dedicated_chunk_frames": 12,
                    "out_of_frame_warning_seconds": 2.0,
                },
            },
        }

    def _fake_call(self, _cfg, case, _timeout, _retries):
        mode = (case.get("structured_business_context") or {}).get("analysis_mode")
        if mode == "object_continuity_only":
            findings = []
            for frame in case["frames"]:
                index = frame["global_frame_index"]
                findings.append(
                    {
                        "global_frame_index": index,
                        "video_index": 1,
                        "timestamp": frame["timestamp"],
                        "opening_stage": "contents_displayed",
                        "visible_facts": "主体状态",
                        "subject_visibility": [
                            {"subject_id": subject_id, "state": _visibility(index, subject_id)}
                            for subject_id in ("shipping_package", "product_package", "claimed_item")
                        ],
                    }
                )
            parsed = {"frame_findings": findings, "object_continuity_assessment": {"continuity_verdict": "long_absence"}}
        elif mode == "damage_causality_only":
            findings = [
                {
                    "global_frame_index": frame["global_frame_index"],
                    "video_index": 1,
                    "timestamp": frame["timestamp"],
                    "visible_facts": "逐帧动作事实",
                }
                for frame in case["frames"]
            ]
            common = {"video_index": 1, "subject": "撕拉片", "location": "右上角", "chain_id": "chain-1"}
            parsed = {
                "frame_findings": findings,
                "damage_causality_assessment": {
                    "damage_presence": "confirmed",
                    "damage_type_and_location": "撕拉片同一断裂位置",
                    "pre_opening_state_visible": False,
                    "opening_action_visible": True,
                    "damage_change_observed": True,
                    "damage_timing": "appears_during_opening",
                    "most_likely_origin": "customer_opening_or_handling",
                    "origin_confidence": 0.92,
                    "causal_evidence_level": "direct",
                    "claim_support": "not_supported",
                    "possible_origins": [],
                    "before_action_evidence": [{**common, "global_frame_index": 1, "timestamp": "00:00.00", "fact": "动作前完整"}],
                    "action_evidence": [{**common, "global_frame_index": 2, "timestamp": "00:01.00", "fact": "用户撕拉"}],
                    "after_action_evidence": [{**common, "global_frame_index": 3, "timestamp": "00:02.00", "fact": "动作后断裂"}],
                },
            }
        else:
            parsed = {
                "predicted_label": "positive",
                "system_yes_no": "YES",
                "confidence": 0.9,
                "overall_audit": {"conclusion": "主通道结论"},
                "frame_findings": [],
                "damage_causality_assessment": {},
                "damage_observability": {
                    "status": "fully_observable",
                    "same_item_linkage": True,
                    "claimed_region_closeup": True,
                    "required_view_coverage": 1.0,
                    "conflicting_evidence": False,
                    "missing_views": [],
                },
                "adopted_evidence": [
                    {
                        "source_type": "supplementary_image",
                        "image_index": image["image_index"],
                        "fact": "用户另行提交了损伤特写图。",
                    }
                    for image in case.get("supplemental_images") or []
                ],
                "object_continuity_assessment": {
                    "continuity_verdict": "continuous",
                    "tracked_subjects": [
                        {
                            "subject_id": "product_package",
                            "description": "商品包装",
                            "visibility_coverage": 1.0,
                            "out_of_frame_events": [],
                        }
                    ],
                },
            }
        return {
            "status": "success",
            "parsed": parsed,
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            "cost": {"estimated_usd": 0.001},
            "latency_seconds": 0.1,
        }

    def test_dedicated_pass_overrides_missing_main_timeline(self):
        with patch("poc.visual_review_poc.model_selection_e2e.call_model", side_effect=self._fake_call):
            result = call_model_chunked({}, self.case, timeout=30, retries=0)

        continuity = result["parsed"]["object_continuity_assessment"]
        product_package = next(
            item for item in continuity["tracked_subjects"] if item["subject_id"] == "product_package"
        )
        self.assertEqual(result["chunking"]["continuity_pass"]["status"], "completed")
        self.assertEqual(product_package["longest_out_of_frame_seconds"], 3.0)
        self.assertEqual(result["parsed"]["predicted_label"], "review")
        self.assertEqual(result["usage"]["total_tokens"], 30)
        confidence = result["parsed"]["confidence_components"]
        self.assertEqual(confidence["main_segment_mean"], 0.9)
        self.assertEqual(confidence["final_decision"], result["parsed"]["confidence"])
        self.assertEqual(confidence["calibration_status"], "uncalibrated_model_score")

    def test_product_damage_main_review_uses_representative_frames_but_specialized_passes_keep_full_timeline(self):
        case = dict(self.case)
        case["frames"] = [
            {
                "global_frame_index": index,
                "video_index": 1,
                "video_file": "sample.mp4",
                "timestamp": f"00:{index - 1:02d}.00",
                "file": f"frame_{index}.jpg",
            }
            for index in range(1, 214)
        ]
        structured = dict(self.case["structured_business_context"])
        structured["continuity_policy"] = {"force_dense_scan": True}
        structured["damage_causality_policy"] = {
            "force_action_scan": True,
            "dedicated_chunk_frames": 20,
            "context_frames": 6,
        }
        case["structured_business_context"] = structured
        observed = {"main": [], "continuity": [], "causality": []}

        def recording_call(cfg, current_case, timeout, retries):
            current_structured = current_case.get("structured_business_context") or {}
            mode = current_structured.get("analysis_mode")
            if mode == "object_continuity_only":
                observed["continuity"].extend(current_structured.get("continuity_target_frame_indices") or [])
            elif mode == "damage_causality_only":
                observed["causality"].extend(current_structured.get("causality_target_frame_indices") or [])
            else:
                observed["main"].extend(
                    frame["global_frame_index"] for frame in current_case.get("frames") or []
                )
            return self._fake_call(cfg, current_case, timeout, retries)

        with patch("poc.visual_review_poc.model_selection_e2e.call_model", side_effect=recording_call):
            result = call_model_chunked({}, case, timeout=30, retries=0)

        self.assertEqual(len(observed["main"]), 48)
        self.assertEqual(len(set(observed["main"])), 48)
        self.assertEqual(min(observed["main"]), 1)
        self.assertEqual(max(observed["main"]), 213)
        self.assertEqual(sorted(observed["continuity"]), list(range(1, 214)))
        self.assertEqual(sorted(observed["causality"]), list(range(1, 214)))
        self.assertEqual(result["chunking"]["total_frames"], 213)
        self.assertEqual(result["chunking"]["main_review_frames"], 48)
        self.assertEqual(result["chunking"]["channels"]["main_review"]["model_calls"], 2)

    def test_continuity_prompt_separates_context_and_target_frames(self):
        case = dict(self.case)
        structured = dict(self.case["structured_business_context"])
        structured.update(
            {
                "analysis_mode": "object_continuity_only",
                "continuity_target_frame_indices": [4, 5],
            }
        )
        case["structured_business_context"] = structured
        case["frames"] = self.frames[1:5]
        prompt = build_selection_prompt(case)
        self.assertIn('"role": "context_only"', prompt)
        self.assertIn('"role": "target"', prompt)
        self.assertIn("最内层商品包装", prompt)

    def test_damage_causality_prompt_separates_video_scope_and_observability(self):
        case = dict(self.case)
        structured = dict(self.case["structured_business_context"])
        structured.update({
            "analysis_mode": "damage_causality_only",
            "causality_target_frame_indices": [1, 2],
        })
        case["structured_business_context"] = structured
        case["frames"] = self.frames[:2]

        prompt = build_selection_prompt(case)

        self.assertIn("只判断主视频中的损伤", prompt)
        self.assertIn("补充图片由主审核通道独立记录", prompt)
        self.assertIn("damage_observability", prompt)

    def test_main_prompt_requires_supplemental_linkage_fields(self):
        prompt = build_selection_prompt(self.case)

        self.assertIn("same_item_linkage", prompt)
        self.assertIn("temporal_linkage", prompt)
        self.assertIn("仅补充图片证据填写", prompt)
        self.assertIn("视频文件/时间轴完整", prompt)

    def test_damage_causality_pass_can_override_main_positive(self):
        case = dict(self.case)
        structured = dict(self.case["structured_business_context"])
        structured["continuity_policy"] = {"force_dense_scan": False}
        structured["damage_causality_policy"] = {
            "force_action_scan": True,
            "dedicated_chunk_frames": 20,
            "context_frames": 6,
        }
        case["structured_business_context"] = structured
        with patch("poc.visual_review_poc.model_selection_e2e.call_model", side_effect=self._fake_call):
            result = call_model_chunked({}, case, timeout=30, retries=0)

        self.assertEqual(result["chunking"]["damage_causality_pass"]["status"], "completed")
        self.assertEqual(result["parsed"]["predicted_label"], "negative")
        self.assertEqual(
            result["parsed"]["damage_causality_assessment"]["most_likely_origin"],
            "customer_opening_or_handling",
        )
        self.assertEqual(result["parsed"]["confidence_components"]["damage_origin"], 0.92)

    def test_video_only_causality_pass_keeps_main_observability_and_supplemental_evidence(self):
        case = dict(self.case)
        case["supplemental_images"] = [{"image_index": 1, "file": "damage-closeup.jpg"}]
        structured = dict(self.case["structured_business_context"])
        structured["continuity_policy"] = {"force_dense_scan": False}
        structured["damage_causality_policy"] = {
            "force_action_scan": True,
            "dedicated_chunk_frames": 20,
            "context_frames": 6,
        }
        case["structured_business_context"] = structured

        with patch("poc.visual_review_poc.model_selection_e2e.call_model", side_effect=self._fake_call):
            result = call_model_chunked({}, case, timeout=30, retries=0)

        parsed = result["parsed"]
        self.assertEqual(parsed["damage_observability"]["status"], "fully_observable")
        source_summary = parsed["damage_causality_assessment"]["evidence_source_summary"]
        self.assertEqual(source_summary["primary_video"]["scope"], "sampled_opening_video")
        self.assertEqual(source_summary["supplemental_images"]["provided_count"], 1)
        self.assertEqual(source_summary["supplemental_images"]["referenced_count"], 1)
        self.assertIn("不能单独推翻", source_summary["decision_boundary"])

    def test_partial_specialized_failure_is_degraded_and_forces_review(self):
        case = dict(self.case)
        case["frames"] = [
            {
                "global_frame_index": index,
                "video_index": 1,
                "video_file": "sample.mp4",
                "timestamp": f"00:{index - 1:02d}.00",
                "file": f"frame_{index}.jpg",
            }
            for index in range(1, 17)
        ]
        structured = dict(self.case["structured_business_context"])
        structured["continuity_policy"] = {"force_dense_scan": False}
        structured["damage_causality_policy"] = {"force_action_scan": True, "dedicated_chunk_frames": 8, "context_frames": 2}
        case["structured_business_context"] = structured

        def partial_call(cfg, current_case, timeout, retries):
            mode = (current_case.get("structured_business_context") or {}).get("analysis_mode")
            targets = (current_case.get("structured_business_context") or {}).get("causality_target_frame_indices") or []
            if mode == "damage_causality_only" and max(targets, default=0) > 8:
                return {
                    "status": "failed",
                    "error": "injected_timeout",
                    "usage": {"input_tokens": 17, "output_tokens": 3, "total_tokens": 20},
                    "cost": {"estimated_usd": 0.005},
                    "latency_seconds": 0.2,
                }
            return self._fake_call(cfg, current_case, timeout, retries)

        with patch("poc.visual_review_poc.model_selection_e2e.call_model", side_effect=partial_call):
            result = call_model_chunked({}, case, timeout=30, retries=0)
        self.assertEqual(result["chunking"]["damage_causality_pass"]["status"], "degraded")
        self.assertTrue(result["chunking"]["damage_causality_pass"]["failures"])
        self.assertEqual(result["parsed"]["predicted_label"], "review")
        self.assertIn("专项审核存在失败", result["parsed"]["specialized_pass_guard_reason"])
        self.assertEqual(result["usage"]["total_tokens"], 50)
        self.assertEqual(result["cost"]["estimated_usd"], 0.007)
        self.assertEqual(result["chunking"]["damage_causality_pass"]["failures"][0]["usage"]["total_tokens"], 20)

    def test_main_chunk_failure_preserves_evidence_and_degrades_to_review(self):
        case = dict(self.case)
        case["model_frames_per_call"] = 4
        structured = dict(self.case["structured_business_context"])
        structured["continuity_policy"] = {"force_dense_scan": False}
        structured["damage_causality_policy"] = {"force_action_scan": False}
        case["structured_business_context"] = structured
        calls = 0

        def mixed_call(cfg, current_case, timeout, retries):
            nonlocal calls
            calls += 1
            if calls == 2:
                return {
                    "status": "failed",
                    "error": "provider_timeout",
                    "usage": {"input_tokens": 17, "output_tokens": 3, "total_tokens": 20},
                    "cost": {"estimated_usd": 0.005},
                    "latency_seconds": 0.2,
                }
            return self._fake_call(cfg, current_case, timeout, retries)

        with patch("poc.visual_review_poc.model_selection_e2e.call_model", side_effect=mixed_call):
            result = call_model_chunked({}, case, timeout=30, retries=0)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["parsed"]["predicted_label"], "review")
        self.assertEqual(result["chunking"]["main_review_pass"]["status"], "degraded")
        self.assertEqual(len(result["chunking"]["main_review_pass"]["failures"]), 1)
        self.assertEqual(result["usage"]["total_tokens"], 35)
        self.assertEqual(result["cost"]["estimated_usd"], 0.006)
        self.assertEqual(result["chunking"]["total_model_calls"], 2)
        self.assertEqual(result["cost_status"], "estimated")
        self.assertEqual(result["unknown_cost_calls"], 0)

    def test_unreported_provider_failure_marks_aggregate_cost_as_partially_unknown(self):
        case = dict(self.case)
        case["model_frames_per_call"] = 4
        structured = dict(self.case["structured_business_context"])
        structured["continuity_policy"] = {"force_dense_scan": False}
        structured["damage_causality_policy"] = {"force_action_scan": False}
        case["structured_business_context"] = structured
        calls = 0

        def mixed_call(cfg, current_case, timeout, retries):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise TimeoutError("provider did not return usage")
            return self._fake_call(cfg, current_case, timeout, retries)

        with patch("poc.visual_review_poc.model_selection_e2e.call_model", side_effect=mixed_call):
            result = call_model_chunked({}, case, timeout=30, retries=0)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["parsed"]["predicted_label"], "review")
        self.assertEqual(result["cost_status"], "partial_unknown")
        self.assertEqual(result["unknown_cost_calls"], 1)

    def test_all_main_chunks_failed_keeps_job_failed(self):
        case = dict(self.case)
        case["model_frames_per_call"] = 4
        structured = dict(self.case["structured_business_context"])
        structured["continuity_policy"] = {"force_dense_scan": False}
        structured["damage_causality_policy"] = {"force_action_scan": False}
        case["structured_business_context"] = structured

        with patch(
            "poc.visual_review_poc.model_selection_e2e.call_model",
            return_value={"status": "failed", "error": "provider_unavailable", "cost_status": "unknown"},
        ):
            result = call_model_chunked({}, case, timeout=30, retries=0)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["cost_status"], "unknown")
        self.assertEqual(result["unknown_cost_calls"], 2)

    def test_missing_provider_key_does_not_count_as_model_call(self):
        case = dict(self.case)
        structured = dict(self.case["structured_business_context"])
        structured["continuity_policy"] = {"force_dense_scan": False}
        structured["damage_causality_policy"] = {"force_action_scan": False}
        case["structured_business_context"] = structured

        with patch(
            "poc.visual_review_poc.model_selection_e2e.call_model",
            return_value={"status": "skipped", "error": "missing_api_key", "cost_status": "not_incurred"},
        ):
            result = call_model_chunked({}, case, timeout=30, retries=0)

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["cost_status"], "not_incurred")
        self.assertEqual(result["chunking"]["total_model_calls"], 0)
        self.assertEqual(result["chunking"]["channels"]["main_review"]["model_calls"], 0)

    def test_duplicate_or_missing_target_frames_fail_schema_validation(self):
        frames = self.frames[:4]

        def incomplete(_case):
            finding = {
                "global_frame_index": 1,
                "timestamp": "00:00.00",
                "opening_stage": "unknown",
                "visible_facts": "重复帧",
                "subject_visibility": [
                    {"subject_id": subject, "state": "visible"}
                    for subject in ("shipping_package", "product_package", "claimed_item")
                ],
            }
            return {
                "status": "success",
                "parsed": {"frame_findings": [finding, finding]},
                "usage": {"input_tokens": 99, "output_tokens": 1, "total_tokens": 100},
                "cost": {"estimated_usd": 0.5},
            }

        results, failures = run_specialized_frame_pass(
            {**self.case, "frames": frames},
            mode="object_continuity_only",
            target_index_key="continuity_target_frame_indices",
            chunk_size=4,
            context_frame_count=1,
            workers=1,
            invoke=incomplete,
        )
        self.assertEqual(results, [])
        self.assertEqual(failures[0]["error"], "target_frame_coverage_invalid")
        self.assertEqual(failures[0]["usage"]["total_tokens"], 100)
        self.assertEqual(failures[0]["cost"]["estimated_usd"], 0.5)

    def test_specialized_pass_repairs_only_missing_target_frames_once(self):
        frames = self.frames[:4]
        calls = []

        def finding(frame):
            return {
                "global_frame_index": frame["global_frame_index"],
                "timestamp": frame["timestamp"],
                "opening_stage": "contents_displayed",
                "visible_facts": "逐帧可见事实",
                "subject_visibility": [
                    {"subject_id": subject, "state": "visible"}
                    for subject in ("shipping_package", "product_package", "claimed_item")
                ],
            }

        def incomplete_then_repair(current_case):
            targets = (current_case.get("structured_business_context") or {}).get(
                "continuity_target_frame_indices"
            ) or []
            calls.append(list(targets))
            selected = [
                frame
                for frame in current_case["frames"]
                if frame["global_frame_index"] in targets
            ]
            if targets == [1, 2, 3, 4]:
                selected = selected[:-1]
            return {
                "status": "success",
                "parsed": {"frame_findings": [finding(frame) for frame in selected]},
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                "cost": {"estimated_usd": 0.001},
                "cost_status": "estimated",
                "latency_seconds": 0.1,
            }

        results, failures = run_specialized_frame_pass(
            {**self.case, "frames": frames},
            mode="object_continuity_only",
            target_index_key="continuity_target_frame_indices",
            chunk_size=4,
            context_frame_count=1,
            workers=1,
            invoke=incomplete_then_repair,
            repair_attempts=1,
        )

        self.assertEqual(calls, [[1, 2, 3, 4], [4]])
        self.assertEqual(failures, [])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["repair_calls"], 1)
        self.assertEqual(results[0]["usage"]["total_tokens"], 30)
        self.assertEqual(results[0]["cost"]["estimated_usd"], 0.002)
        self.assertEqual(
            [item["global_frame_index"] for item in results[0]["parsed"]["frame_findings"]],
            [1, 2, 3, 4],
        )

    def test_specialized_pass_normalizes_numeric_string_frame_indices(self):
        frames = self.frames[:4]

        def string_indices(current_case):
            targets = (current_case.get("structured_business_context") or {}).get(
                "continuity_target_frame_indices"
            ) or []
            return {
                "status": "success",
                "parsed": {
                    "frame_findings": [
                        {
                            "global_frame_index": str(index),
                            "timestamp": f"00:0{index - 1}.00",
                            "opening_stage": "contents_displayed",
                            "visible_facts": "逐帧可见事实",
                            "subject_visibility": [
                                {"subject_id": subject, "state": "visible"}
                                for subject in ("shipping_package", "product_package", "claimed_item")
                            ],
                        }
                        for index in targets
                    ]
                },
                "usage": {},
                "cost": {},
                "cost_status": "estimated",
            }

        results, failures = run_specialized_frame_pass(
            {**self.case, "frames": frames},
            mode="object_continuity_only",
            target_index_key="continuity_target_frame_indices",
            chunk_size=4,
            context_frame_count=1,
            workers=1,
            invoke=string_indices,
        )

        self.assertEqual(failures, [])
        self.assertEqual(
            [item["global_frame_index"] for item in results[0]["parsed"]["frame_findings"]],
            [1, 2, 3, 4],
        )

    def test_partial_specialized_output_preserves_valid_findings_and_marks_missing_unknown(self):
        frames = self.frames[:4]

        def always_omit_last(current_case):
            targets = (current_case.get("structured_business_context") or {}).get(
                "continuity_target_frame_indices"
            ) or []
            selected = [
                frame for frame in current_case["frames"]
                if frame["global_frame_index"] in targets and frame["global_frame_index"] != 4
            ]
            return {
                "status": "success",
                "parsed": {
                    "frame_findings": [
                        {
                            "global_frame_index": frame["global_frame_index"],
                            "timestamp": frame["timestamp"],
                            "opening_stage": "contents_displayed",
                            "visible_facts": "逐帧可见事实",
                            "subject_visibility": [
                                {"subject_id": subject, "state": "visible"}
                                for subject in ("shipping_package", "product_package", "claimed_item")
                            ],
                        }
                        for frame in selected
                    ]
                },
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                "cost": {"estimated_usd": 0.001},
                "cost_status": "estimated",
            }

        results, failures = run_specialized_frame_pass(
            {**self.case, "frames": frames},
            mode="object_continuity_only",
            target_index_key="continuity_target_frame_indices",
            chunk_size=4,
            context_frame_count=1,
            workers=1,
            invoke=always_omit_last,
            repair_attempts=1,
            preserve_partial_coverage=True,
        )

        self.assertEqual(failures, [])
        self.assertEqual(results[0]["coverage_status"], "partial_unknown")
        self.assertEqual(results[0]["missing_target_frame_indices"], [4])
        findings = results[0]["parsed"]["frame_findings"]
        self.assertEqual(len(findings), 4)
        self.assertEqual(findings[-1]["observation_status"], "model_output_missing")
        self.assertTrue(all(item["state"] == "unknown" for item in findings[-1]["subject_visibility"]))

    def test_repair_calls_are_included_in_channel_and_total_model_call_counts(self):
        case = dict(self.case)
        case["frames"] = self.frames[:4]
        structured = dict(self.case["structured_business_context"])
        structured["continuity_policy"] = {"force_dense_scan": True}
        structured["damage_causality_policy"] = {"force_action_scan": False}
        case["structured_business_context"] = structured

        def incomplete_then_repair(cfg, current_case, timeout, retries):
            current_structured = current_case.get("structured_business_context") or {}
            targets = current_structured.get("continuity_target_frame_indices") or []
            if current_structured.get("analysis_mode") != "object_continuity_only":
                return self._fake_call(cfg, current_case, timeout, retries)
            selected = [
                frame for frame in current_case["frames"]
                if frame["global_frame_index"] in targets
            ]
            if targets == [1, 2, 3, 4]:
                selected = selected[:-1]
            parsed = {
                "frame_findings": [
                    {
                        "global_frame_index": frame["global_frame_index"],
                        "video_index": 1,
                        "timestamp": frame["timestamp"],
                        "opening_stage": "contents_displayed",
                        "visible_facts": "逐帧可见事实",
                        "subject_visibility": [
                            {"subject_id": subject, "state": "visible"}
                            for subject in ("shipping_package", "product_package", "claimed_item")
                        ],
                    }
                    for frame in selected
                ]
            }
            return {
                "status": "success",
                "parsed": parsed,
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                "cost": {"estimated_usd": 0.001},
                "cost_status": "estimated",
                "latency_seconds": 0.1,
            }

        with patch("poc.visual_review_poc.model_selection_e2e.call_model", side_effect=incomplete_then_repair):
            result = call_model_chunked({}, case, timeout=30, retries=0)

        continuity = result["chunking"]["channels"]["object_continuity"]
        self.assertEqual(continuity["repair_calls"], 1)
        self.assertEqual(continuity["model_calls"], 2)
        self.assertEqual(result["chunking"]["total_model_calls"], 3)

    def test_chunked_review_keeps_partial_continuity_evidence_and_reports_exact_gaps(self):
        case = dict(self.case)
        case["frames"] = self.frames[:4]
        structured = dict(self.case["structured_business_context"])
        structured["continuity_policy"] = {"force_dense_scan": True}
        structured["damage_causality_policy"] = {"force_action_scan": False}
        case["structured_business_context"] = structured

        def incomplete_continuity(cfg, current_case, timeout, retries):
            current_structured = current_case.get("structured_business_context") or {}
            targets = current_structured.get("continuity_target_frame_indices") or []
            if current_structured.get("analysis_mode") != "object_continuity_only":
                return self._fake_call(cfg, current_case, timeout, retries)
            selected = [
                frame for frame in current_case["frames"]
                if frame["global_frame_index"] in targets and frame["global_frame_index"] != 4
            ]
            return {
                "status": "success",
                "parsed": {
                    "frame_findings": [
                        {
                            "global_frame_index": frame["global_frame_index"],
                            "timestamp": frame["timestamp"],
                            "opening_stage": "contents_displayed",
                            "visible_facts": "逐帧可见事实",
                            "subject_visibility": [
                                {"subject_id": subject, "state": "visible"}
                                for subject in ("shipping_package", "product_package", "claimed_item")
                            ],
                        }
                        for frame in selected
                    ]
                },
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                "cost": {"estimated_usd": 0.001},
                "cost_status": "estimated",
                "latency_seconds": 0.1,
            }

        with patch("poc.visual_review_poc.model_selection_e2e.call_model", side_effect=incomplete_continuity):
            result = call_model_chunked({}, case, timeout=30, retries=0)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["parsed"]["predicted_label"], "review")
        continuity_pass = result["chunking"]["continuity_pass"]
        self.assertEqual(continuity_pass["status"], "degraded")
        self.assertEqual(continuity_pass["coverage_gaps"][0]["missing_target_frame_indices"], [4])
        findings = result["parsed"]["continuity_frame_findings"]
        self.assertEqual(len(findings), 4)
        self.assertEqual(findings[-1]["observation_status"], "model_output_missing")

    def test_provider_payload_ignores_contact_sheet_override_and_keeps_individual_frames(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            frame_path = root / "frame.jpg"
            sheet_path = root / "sheet.webp"
            Image.new("RGB", (640, 360), (10, 20, 30)).save(frame_path)
            Image.new("RGB", (1280, 800), (20, 30, 40)).save(sheet_path, format="WEBP")
            case = {
                "frames": [{**self.frames[0], "api_path": str(frame_path), "api_mime_type": "image/jpeg"}],
                "supplemental_images": [],
                "model_images_override": [
                    {"api_path": str(sheet_path), "api_mime_type": "image/webp", "label": "时序拼图映射"}
                ],
            }

            gemini = gemini_payload("system", "user", case)
            openai = openai_messages("system", "user", case)

            gemini_parts = gemini["contents"][0]["parts"]
            self.assertEqual(sum("inline_data" in item for item in gemini_parts), 1)
            self.assertTrue(any((item.get("inline_data") or {}).get("mime_type") == "image/jpeg" for item in gemini_parts))
            openai_content = openai[1]["content"]
            self.assertEqual(sum(item.get("type") == "image_url" for item in openai_content), 1)
            self.assertFalse(any("时序拼图映射" in str(item.get("text") or "") for item in openai_content))
            self.assertFalse(any("file_data" in item or "file_uri" in str(item) for item in gemini_parts))
            image_urls = [item["image_url"]["url"] for item in openai_content if item.get("type") == "image_url"]
            self.assertTrue(all(url.startswith("data:image/") for url in image_urls))


if __name__ == "__main__":
    unittest.main()
