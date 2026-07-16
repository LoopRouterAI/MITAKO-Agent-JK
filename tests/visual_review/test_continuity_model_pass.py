from __future__ import annotations

import unittest
from unittest.mock import patch

from poc.visual_review_poc.model_selection_e2e import call_model_chunked
from poc.visual_review_poc.review_model_prompt import build_selection_prompt
from poc.visual_review_poc.specialized_model_pass import run_specialized_frame_pass


def _visibility(index: int, subject_id: str) -> str:
    if subject_id == "product_package" and 3 <= index <= 5:
        return "out_of_frame"
    if subject_id == "claimed_item" and index < 6:
        return "not_yet_exposed"
    return "visible"


class ContinuityModelPassTest(unittest.TestCase):
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
                return {"status": "failed", "error": "injected_timeout"}
            return self._fake_call(cfg, current_case, timeout, retries)

        with patch("poc.visual_review_poc.model_selection_e2e.call_model", side_effect=partial_call):
            result = call_model_chunked({}, case, timeout=30, retries=0)
        self.assertEqual(result["chunking"]["damage_causality_pass"]["status"], "degraded")
        self.assertTrue(result["chunking"]["damage_causality_pass"]["failures"])
        self.assertEqual(result["parsed"]["predicted_label"], "review")
        self.assertIn("专项审核存在失败", result["parsed"]["specialized_pass_guard_reason"])

    def test_duplicate_or_missing_target_frames_fail_schema_validation(self):
        frames = self.frames[:4]

        def incomplete(_case):
            finding = {
                "global_frame_index": 1,
                "timestamp": "00:00.00",
                "visible_facts": "重复帧",
                "subject_visibility": [
                    {"subject_id": subject, "state": "visible"}
                    for subject in ("shipping_package", "product_package", "claimed_item")
                ],
            }
            return {"status": "success", "parsed": {"frame_findings": [finding, finding]}}

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


if __name__ == "__main__":
    unittest.main()
