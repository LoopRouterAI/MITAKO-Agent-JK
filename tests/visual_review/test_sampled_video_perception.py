from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

from poc.visual_review_poc import model_selection_e2e
from poc.visual_review_poc.sampled_video_perception import (
    prepare_sampled_batch_case,
    prepare_sampled_reduce_case,
)


def _compact_result() -> dict:
    refs = [
        {
            "field": field,
            "asset_ref": "video_1_frame_1" if index == 0 else "video_1_frame_6",
            "video_index": 1,
            "global_frame_index": 1 if index == 0 else 6,
            "timestamp": "00:00.00" if index == 0 else "00:05.00",
            "fact": f"{field} 的可见事实",
        }
        for field in (
            "opening_action",
            "sealed_start",
            "waybill_visible",
            "continuous",
            "has_edit",
            "has_offscreen",
            "has_speed_change",
            "all_items_shown",
            "issue_visible",
            "claimed_item",
        )
        for index in range(2)
    ]
    return {
        "sealed_start": True,
        "waybill_visible": True,
        "continuous": True,
        "has_edit": False,
        "has_offscreen": False,
        "has_speed_change": None,
        "all_items_shown": True,
        "issue_visible": True,
        "opening_action_assessment": {
            "present": True,
            "confidence": 0.93,
            "reason": "看见包裹从闭合状态被首次拆开。",
        },
        "field_confidences": [0.95, 0.9, 0.91, 0.92, 0.9, 0.4, 0.91, 0.89],
        "claimed_item_assessment": {
            "identity_description": "争议摆件",
            "identity_anchor_asset_ref": "video_1_frame_3",
            "identity_confidence": 0.9,
            "appeared": True,
            "first_visible_timestamp": "00:02.00",
            "last_visible_timestamp": "00:05.00",
            "presentation_complete": True,
            "offscreen_during_presentation": False,
            "reason": "目标在有效展示窗口内持续可见。",
        },
        "speed_assessment": {
            "value": "unknown",
            "confidence": 0.6,
            "evidence_basis": "motion_semantics_only",
            "affects_visual_judgement": False,
            "review_signal": "yellow",
            "reason": "1 FPS 帧序列没有可靠原速锚点。",
        },
        "damage_assessment": {
            "visible_in_continuous_opening": True,
            "same_item_linkage": True,
            "main_video_detail_sufficient": True,
            "severity_level": "moderate",
            "severity_confidence": 0.88,
            "severity_reason": "可见局部划痕。",
            "structural_failure": False,
            "business_defect_qualification": "not_qualified",
            "supplemental_damage_visible": None,
            "conflicting_evidence": False,
            "causal_chain_status": "indeterminate",
            "causal_evidence_level": "none",
            "causal_reason": "没有形成操作前中后三段直接证据。",
            "causal_evidence_refs": [],
            "reason": "主开箱链可见划痕。",
        },
        "evidence_refs": refs,
    }


class SampledVideoPerceptionRuntimeTest(unittest.TestCase):
    def test_sampled_batch_only_carries_the_trusted_identity_anchor(self):
        case = {
            "frames": [{"video_index": 1, "global_frame_index": 1}],
            "supplemental_images": [
                {"image_index": 1, "file": "unrelated.webp"},
                {"image_index": 2, "file": "trusted-anchor.webp"},
            ],
            "official_reference_images": [
                {"reference_index": 1, "file": "official.webp"}
            ],
            "structured_business_context": {
                "continuity_claim_identity": {
                    "identity_anchor_asset_ref": "supplemental_image_2"
                }
            },
        }

        prepared = prepare_sampled_batch_case(
            case,
            case["frames"],
            batch_index=1,
            total_batches=1,
            overlap=0,
        )

        self.assertEqual(
            [item["image_index"] for item in prepared["supplemental_images"]],
            [2],
        )
        self.assertEqual(prepared["official_reference_images"], [])
        self.assertEqual(
            prepared["structured_business_context"]["sampled_frame_batch"][
                "identity_anchor_role"
            ],
            "identity_only",
        )

    def test_reduce_visually_rechecks_compatible_claimed_item_field_names(self):
        case = {
            "frames": [
                {
                    "video_index": 1,
                    "global_frame_index": 38,
                    "timestamp": "00:36.97",
                }
            ],
            "supplemental_images": [],
            "official_reference_images": [
                {"reference_index": 2, "api_path": "target.webp"}
            ],
            "structured_business_context": {
                "continuity_claim_identity": {
                    "identity_anchor_asset_ref": "official_product_reference_2"
                }
            },
        }
        prepared = prepare_sampled_reduce_case(case, [{
            "batch_index": 2,
            "parsed": {
                "evidence_refs": [{
                    "field": "claimed_item_assessment.appeared",
                    "asset_ref": "video_1_frame_38",
                }],
            },
        }])

        self.assertEqual(
            [item["global_frame_index"] for item in prepared["frames"]],
            [38],
        )
        self.assertEqual(
            [item["reference_index"] for item in prepared["official_reference_images"]],
            [2],
        )

    def test_compact_frame_pipeline_is_provider_independent(self):
        case = {
            "case_id": "PD-PROVIDER-PARITY",
            "scenario": "product_damage",
            "frames": [
                {
                    "video_index": 1,
                    "global_frame_index": index,
                    "timestamp": f"00:0{index - 1}.00",
                }
                for index in range(1, 3)
            ],
            "videos": [{"video_index": 1, "duration_seconds": 2.0}],
            "supplemental_images": [],
            "official_reference_images": [],
            "structured_business_context": {"business_scenario": "product_damage"},
            "model_frames_per_call": 2,
        }

        for provider in ("gemini_native", "openai_compatible"):
            modes: list[str] = []

            def fake_call(_cfg, current, timeout, retries, deadline_at=None):
                del timeout, retries, deadline_at
                modes.append(current["structured_business_context"]["analysis_mode"])
                return {
                    "status": "success",
                    "parsed": copy.deepcopy(_compact_result()),
                    "cost_status": "estimated",
                    "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                    "cost": {"estimated_usd": 0.001},
                    "model_http_request_count": 1,
                }

            with self.subTest(provider=provider), patch.object(
                model_selection_e2e, "call_model", side_effect=fake_call
            ):
                result = model_selection_e2e.call_model_chunked(
                    {"provider": provider}, copy.deepcopy(case), timeout=30, retries=0
                )

                self.assertEqual(
                    modes,
                    ["sampled_video_batch_observation", "sampled_video_perception_reduce"],
                )
                self.assertEqual(result["status"], "success")
                self.assertEqual(
                    result["chunking"]["pipeline_mode"],
                    "parallel_overlapping_1fps_facts",
                )

    def test_all_batches_skipped_without_api_key_stays_not_incurred(self):
        case = {
            "case_id": "PD-NO-KEY",
            "scenario": "product_damage",
            "frames": [
                {"video_index": 1, "global_frame_index": index}
                for index in range(1, 4)
            ],
            "supplemental_images": [],
            "official_reference_images": [],
            "structured_business_context": {"business_scenario": "product_damage"},
            "model_frames_per_call": 2,
        }
        skipped = {
            "status": "skipped",
            "error": "missing_api_key",
            "cost_status": "not_incurred",
        }

        with patch.object(model_selection_e2e, "call_model", return_value=skipped):
            result = model_selection_e2e.call_model_chunked(
                {}, case, timeout=30, retries=0
            )

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["error"], "missing_api_key")
        self.assertEqual(result["cost_status"], "not_incurred")
        self.assertEqual(result["chunking"]["total_model_calls"], 0)
        self.assertEqual(result["unknown_cost_calls"], 0)

    def test_failed_batches_preserve_every_channel_attempt_and_unknown_cost(self):
        case = {
            "case_id": "PD-FAILED-AUDIT",
            "scenario": "product_damage",
            "frames": [
                {"video_index": 1, "global_frame_index": index}
                for index in range(1, 4)
            ],
            "supplemental_images": [],
            "official_reference_images": [],
            "structured_business_context": {"business_scenario": "product_damage"},
            "model_frames_per_call": 2,
        }
        failed = {
            "status": "failed",
            "status_code": 503,
            "error_type": "soft",
            "cost_status": "unknown",
            "_channel_route_attempts": [
                {"channel": "primary", "status_code": 503, "decision": "exhausted"}
            ],
        }

        with patch.object(model_selection_e2e, "call_model", return_value=failed):
            result = model_selection_e2e.call_model_chunked(
                {}, case, timeout=30, retries=0
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["unknown_cost_calls"], 2)
        self.assertEqual(len(result["_channel_route_attempts"]), 2)
        self.assertEqual(result["chunking"]["segment_count"], 2)

    def test_product_damage_frame_fallback_uses_compact_parallel_fact_pipeline(self):
        case = {
            "case_id": "PD-FRAME-FALLBACK",
            "scenario": "product_damage",
            "scenario_label": "商品有伤",
            "customer_claim": "摆件表面有划痕",
            "frames": [
                {
                    "video_index": 1,
                    "global_frame_index": index,
                    "timestamp": f"00:{index - 1:02d}.00",
                    "api_path": f"frame-{index}.webp",
                    "api_mime_type": "image/webp",
                }
                for index in range(1, 8)
            ],
            "videos": [{"video_index": 1, "duration_seconds": 7.0}],
            "supplemental_images": [],
            "official_reference_images": [],
            "structured_business_context": {"business_scenario": "product_damage"},
            "model_frames_per_call": 4,
        }
        modes: list[str] = []

        def fake_call_model(_cfg, current, timeout, retries, deadline_at=None):
            del timeout, retries, deadline_at
            mode = current["structured_business_context"]["analysis_mode"]
            modes.append(mode)
            parsed = _compact_result()
            return {
                "status": "success",
                "parsed": copy.deepcopy(parsed),
                "parsed_before_boundary": copy.deepcopy(parsed),
                "latency_seconds": 1.0,
                "model_http_request_count": 1,
                "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
                "cost": {"estimated_usd": 0.01},
                "cost_status": "estimated",
            }

        with patch.object(model_selection_e2e, "call_model", side_effect=fake_call_model):
            result = model_selection_e2e.call_model_chunked(
                {"provider": "gemini_native"},
                case,
                timeout=30,
                retries=0,
            )

        self.assertEqual(modes.count("sampled_video_batch_observation"), 3)
        self.assertEqual(modes.count("sampled_video_perception_reduce"), 1)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["chunking"]["pipeline_mode"], "parallel_overlapping_1fps_facts")
        self.assertEqual(result["chunking"]["total_model_calls"], 4)
        opening = result["parsed"]["video_audit_conclusion"]["opening_video_compliance"]
        self.assertEqual(opening["result"], "compliant")
        self.assertEqual(opening["source"], "sampled_frame_perception")
        self.assertEqual(result["parsed"]["predicted_label"], "positive")
        self.assertEqual(
            result["parsed"]["damage_causality_assessment"]
            ["causal_chain_assessment"]["status"],
            "indeterminate",
        )

    def test_product_damage_frame_fallback_does_not_pass_without_opening_action(self):
        compact = _compact_result()
        compact["opening_action_assessment"] = {
            "present": False,
            "confidence": 0.93,
            "reason": "只看到闭合包裹，没有看到初次拆包动作。",
        }
        compact["evidence_refs"] = [
            item for item in compact["evidence_refs"]
            if item["field"] != "opening_action"
        ]
        case = {
            "scenario": "product_damage",
            "frames": [
                {
                    "video_index": 1,
                    "global_frame_index": index,
                    "timestamp": f"00:{index - 1:02d}.00",
                }
                for index in range(1, 8)
            ],
            "videos": [{"video_index": 1, "duration_seconds": 7.0}],
            "supplemental_images": [],
            "official_reference_images": [],
            "structured_business_context": {"business_scenario": "product_damage"},
        }

        from poc.visual_review_poc.native_video_perception import expand_native_video_perception

        parsed = expand_native_video_perception(compact, case, sampling_fps=1.0)

        opening = parsed["video_audit_conclusion"]["opening_video_compliance"]
        self.assertNotEqual(opening["result"], "compliant")
        self.assertNotEqual(parsed["predicted_label"], "positive")


if __name__ == "__main__":
    unittest.main()
