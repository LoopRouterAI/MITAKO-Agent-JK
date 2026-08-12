from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from poc.visual_review_poc.model_selection_e2e import prepare_media
from prompts.visual_review.review_model_prompt import (
    build_sampled_video_batch_prompt,
    build_sampled_video_reduce_prompt,
)

from scripts.run_baidu_video_ab import (
    apply_perception_evidence_scope,
    bind_perception_identity,
    build_overlapping_frame_batches,
    build_candidate_detail_case,
    build_claim_identity_case,
    candidate_detail_timestamps,
    candidate_detail_window,
    resolved_claim_identity,
    needs_sampled_frame_case,
    perception_result_summary,
    prepare_sampled_batch_case,
    prepare_sampled_perception_case,
    prepare_sampled_reduce_case,
    prepare_benchmark_native_source,
    resolve_profiles,
    result_summary,
    run_sampled_perception_batched,
    signed_proxy_source,
    transcoded_url_max_bytes,
    validate_video_sampling_fps,
)


class BaiduVideoABTest(unittest.TestCase):
    def test_sampled_frames_are_individual_lossless_webp_at_1080p_budget(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "frame.png"
            image = np.zeros((1440, 2560, 3), dtype=np.uint8)
            image[:, :, 1] = 127
            ok, encoded = cv2.imencode(".png", image)
            self.assertTrue(ok)
            encoded.tofile(str(source))

            prepared = prepare_media(
                [{"path": source, "global_frame_index": 1}],
                root / "prepared",
                max_edge=1920,
                lossless_webp=True,
            )

            self.assertEqual(len(prepared), 1)
            output = Path(prepared[0]["api_path"])
            self.assertEqual(output.suffix, ".webp")
            self.assertEqual(prepared[0]["api_mime_type"], "image/webp")
            self.assertEqual(output.read_bytes()[:4], b"RIFF")
            decoded = cv2.imdecode(np.fromfile(str(output), dtype=np.uint8), cv2.IMREAD_COLOR)
            self.assertEqual(max(decoded.shape[:2]), 1920)
    def test_candidate_detail_window_only_uses_model_discovered_timestamps(self):
        parsed = {
            "claimed_item_assessment": {
                "first_visible_timestamp": "00:36.750",
                "last_visible_timestamp": "00:37.750",
            },
            "evidence_refs": [
                {"field": "claimed_item", "timestamp": "00:36.750"},
                {"field": "claimed_item", "timestamp": "00:37.250"},
                {"field": "issue_visible", "timestamp": "00:37.250"},
            ],
        }

        self.assertEqual(candidate_detail_window(parsed), (36.25, 38.25))
        self.assertIsNone(candidate_detail_window({"evidence_refs": []}))

    def test_candidate_detail_timestamps_keep_discrete_model_candidates(self):
        parsed = {
            "claimed_item_assessment": {
                "first_visible_timestamp": "00:09.000",
                "last_visible_timestamp": "00:12.500",
            },
            "evidence_refs": [
                {"field": "claimed_item", "timestamp": "00:09.750"},
                {"field": "claimed_item", "timestamp": "00:10.000"},
                {"field": "claimed_item", "timestamp": "00:23.000"},
                {"field": "claimed_item", "timestamp": "00:37.000"},
                {"field": "claimed_item", "timestamp": "00:41.000"},
                {"field": "claimed_item", "timestamp": "00:48.750"},
                {"field": "claimed_item", "timestamp": "00:54.250"},
                {"field": "issue_visible", "timestamp": "00:10.500"},
            ],
        }

        self.assertEqual(
            candidate_detail_timestamps(parsed),
            [9.75, 10.0, 23.0, 37.0, 41.0, 48.75, 54.25],
        )

    def test_candidate_detail_case_contains_only_extracted_frames_and_identity_reference(self):
        case = {
            "native_video": {"file_uri": "https://example.invalid/video"},
            "frames": [{"asset_ref": "opening_anchor"}],
            "supplemental_images": [{"asset_ref": "supplemental_image_1"}],
            "official_reference_images": [
                {"item_ref": "ORDER-LINE-001", "api_path": "one.jpg"},
                {"item_ref": "ORDER-LINE-002", "api_path": "two.jpg"},
            ],
            "structured_business_context": {
                "continuity_claim_identity": {"item_ref": "ORDER-LINE-002"},
            },
        }
        frames = [
            {
                "frame_index": 1,
                "timestamp_seconds": 36.75,
                "path": "frame.webp",
            },
        ]

        detail = build_candidate_detail_case(case, frames)

        self.assertNotIn("native_video", detail)
        self.assertEqual(detail["supplemental_images"], [])
        self.assertEqual(detail["official_reference_images"], [case["official_reference_images"][1]])
        self.assertEqual(detail["frames"][0]["timestamp"], "00:36.75")
        self.assertEqual(detail["frames"][0]["api_path"], "frame.webp")
        self.assertEqual(detail["frames"][0]["api_mime_type"], "image/webp")
        self.assertEqual(
            detail["structured_business_context"]["analysis_mode"],
            "claimed_item_detail_only",
        )

    def test_video_only_perception_does_not_mix_supplemental_or_reference_images(self):
        original = {
            "native_video": {"file_uri": "https://example.invalid/video"},
            "frames": [{"asset_ref": "opening_anchor"}],
            "supplemental_images": [{"asset_ref": "supplemental_image_1"}],
            "official_reference_images": [{"asset_ref": "official_product_reference_1"}],
        }

        scoped = apply_perception_evidence_scope(original, "video-only")

        self.assertEqual(scoped["supplemental_images"], [])
        self.assertEqual(scoped["official_reference_images"], [])
        self.assertEqual(scoped["frames"], [])
        self.assertEqual(len(original["supplemental_images"]), 1)

    def test_claim_identity_is_resolved_before_video_only_review(self):
        case = {
            "native_video": {"file_uri": "https://example.invalid/video"},
            "frames": [{"asset_ref": "opening_anchor"}],
            "supplemental_images": [{"asset_ref": "supplemental_image_1"}],
            "official_reference_images": [{"asset_ref": "official_product_reference_1"}],
            "structured_business_context": {"business_scenario": "product_damage"},
        }
        identity_case = build_claim_identity_case(case)
        self.assertNotIn("native_video", identity_case)
        self.assertEqual(identity_case["frames"], [])
        self.assertEqual(
            identity_case["structured_business_context"]["analysis_mode"],
            "claim_identity_only",
        )

        resolved = resolved_claim_identity({
            "status": "success",
            "parsed": {
                "match_status": "matched",
                "confidence": 0.92,
                "expected_order_item": {
                    "item_ref": "ORDER-LINE-003",
                    "sku": "SKU-003",
                    "product_name": "目标商品",
                    "specification": "45mm",
                },
            },
        })
        self.assertEqual(resolved["sku"], "SKU-003")
        self.assertEqual(resolved["product_name"], "目标商品")

        self.assertEqual(resolved_claim_identity({
            "status": "success",
            "parsed": {
                "match_status": "ambiguous",
                "confidence": 0.99,
                "expected_order_item": {},
            },
        }), {})

    def test_video_only_keeps_only_the_matched_official_identity_reference(self):
        case = {
            "frames": [],
            "supplemental_images": [{"asset_ref": "supplemental_image_1"}],
            "official_reference_images": [
                {"item_ref": "ORDER-LINE-001", "sku": "SKU-001"},
                {"item_ref": "ORDER-LINE-002", "sku": "SKU-002"},
            ],
            "structured_business_context": {
                "continuity_claim_identity": {
                    "item_ref": "ORDER-LINE-002",
                    "sku": "SKU-002",
                },
            },
        }

        scoped = apply_perception_evidence_scope(case, "video-only")

        self.assertEqual(scoped["supplemental_images"], [])
        self.assertEqual(
            scoped["official_reference_images"],
            [{"item_ref": "ORDER-LINE-002", "sku": "SKU-002"}],
        )

    def test_video_sampling_fps_is_bounded_for_full_video_review(self):
        self.assertEqual(validate_video_sampling_fps(2), 2.0)
        self.assertEqual(validate_video_sampling_fps(4.0), 4.0)
        with self.assertRaisesRegex(SystemExit, "0.1.*24"):
            validate_video_sampling_fps(0)
        with self.assertRaisesRegex(SystemExit, "0.1.*24"):
            validate_video_sampling_fps(25)

    def test_url_proxy_is_not_limited_by_inline_budget(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "case.mp4"
            video.write_bytes(b"x" * 100)

            self.assertEqual(transcoded_url_max_bytes(video, 4), 100)
            self.assertEqual(transcoded_url_max_bytes(video, 200), 200)

    def test_native_only_benchmark_skips_redundant_full_timeline_frame_case(self):
        self.assertFalse(needs_sampled_frame_case(["native"]))
        self.assertFalse(needs_sampled_frame_case(["perception"]))
        self.assertTrue(needs_sampled_frame_case(["sampled-perception"]))
        self.assertTrue(needs_sampled_frame_case(["native", "unified"]))

    def test_sampled_perception_preserves_the_full_frame_timeline_in_one_case(self):
        original = {
            "native_video": {"file_uri": "https://example.invalid/video.mp4"},
            "frames": [
                {"global_frame_index": 1, "timestamp": "00:00.00"},
                {"global_frame_index": 2, "timestamp": "00:01.00"},
            ],
            "structured_business_context": {"business_scenario": "product_damage"},
        }

        prepared = prepare_sampled_perception_case(original)

        self.assertNotIn("native_video", prepared)
        self.assertEqual(len(prepared["frames"]), 2)
        self.assertEqual(
            prepared["structured_business_context"]["analysis_mode"],
            "sampled_video_perception",
        )
        self.assertNotIn("analysis_mode", original["structured_business_context"])

    def test_sampled_frame_batches_overlap_without_losing_global_timeline(self):
        frames = [
            {
                "video_index": 1,
                "global_frame_index": index,
                "timestamp": f"00:{index - 1:02d}.00",
            }
            for index in range(1, 11)
        ]

        batches = build_overlapping_frame_batches(frames, batch_size=4, overlap=1)

        self.assertEqual(
            [[frame["global_frame_index"] for frame in batch] for batch in batches],
            [[1, 2, 3, 4], [4, 5, 6, 7], [7, 8, 9, 10]],
        )
        self.assertEqual(
            sorted({frame["global_frame_index"] for batch in batches for frame in batch}),
            list(range(1, 11)),
        )

    def test_sampled_batch_case_carries_sequence_metadata_and_individual_frames(self):
        original = {
            "native_video": {"file_uri": "https://example.invalid/video.mp4"},
            "frames": [
                {"video_index": 1, "global_frame_index": 10, "timestamp": "00:09.00"},
                {"video_index": 1, "global_frame_index": 11, "timestamp": "00:10.00"},
            ],
            "supplemental_images": [{"image_index": 1}],
            "official_reference_images": [{"reference_index": 1}],
            "structured_business_context": {"business_scenario": "product_damage"},
        }

        prepared = prepare_sampled_batch_case(
            original,
            original["frames"],
            batch_index=2,
            total_batches=5,
            overlap=2,
        )

        self.assertNotIn("native_video", prepared)
        self.assertEqual(
            [frame["global_frame_index"] for frame in prepared["frames"]],
            [10, 11],
        )
        metadata = prepared["structured_business_context"]["sampled_frame_batch"]
        self.assertEqual(metadata["index"], 2)
        self.assertEqual(metadata["total"], 5)
        self.assertEqual(metadata["start_timestamp"], "00:09.00")
        self.assertEqual(metadata["end_timestamp"], "00:10.00")
        self.assertEqual(metadata["overlap_frames"], 2)
        self.assertEqual(
            prepared["structured_business_context"]["analysis_mode"],
            "sampled_video_batch_observation",
        )

    def test_sampled_batch_reuses_only_one_labeled_identity_anchor(self):
        original = {
            "frames": [
                {"video_index": 1, "global_frame_index": 1, "timestamp": "00:00.00"},
            ],
            "supplemental_images": [
                {"image_index": 1, "api_path": "claim-1.webp"},
                {"image_index": 2, "api_path": "claim-2.webp"},
            ],
            "official_reference_images": [
                {"reference_index": 1, "api_path": "official-1.webp"},
                {"reference_index": 2, "api_path": "official-2.webp"},
            ],
            "structured_business_context": {
                "business_scenario": "product_damage",
                "continuity_claim_identity": {
                    "identity_anchor_asset_ref": "supplemental_image_2",
                },
            },
        }

        prepared = prepare_sampled_batch_case(
            original,
            original["frames"],
            batch_index=1,
            total_batches=1,
            overlap=0,
        )

        self.assertEqual(
            [item["image_index"] for item in prepared["supplemental_images"]],
            [2],
        )
        self.assertEqual(prepared["official_reference_images"], [])
        metadata = prepared["structured_business_context"]["sampled_frame_batch"]
        self.assertEqual(metadata["identity_anchor_asset_ref"], "supplemental_image_2")
        self.assertEqual(metadata["identity_anchor_role"], "identity_only")
        self.assertEqual(
            len(prepared["frames"])
            + len(prepared["supplemental_images"])
            + len(prepared["official_reference_images"]),
            2,
        )
        prompt = build_sampled_video_batch_prompt(prepared)
        self.assertIn("supplemental_image_2", prompt)
        self.assertIn("只用于商品身份比对", prompt)
        self.assertIn("不能证明伤点来自开箱过程", prompt)

    def test_sampled_batch_never_guesses_the_first_identity_anchor(self):
        original = {
            "frames": [
                {"video_index": 1, "global_frame_index": 1, "timestamp": "00:00.00"},
            ],
            "supplemental_images": [
                {"image_index": 1, "api_path": "other-item.webp"},
                {"image_index": 2, "api_path": "claimed-item.webp"},
            ],
            "official_reference_images": [{"reference_index": 1}],
            "structured_business_context": {"business_scenario": "product_damage"},
        }

        prepared = prepare_sampled_batch_case(
            original,
            original["frames"],
            batch_index=1,
            total_batches=1,
            overlap=0,
        )

        self.assertEqual(prepared["supplemental_images"], [])
        self.assertEqual(prepared["official_reference_images"], [])
        metadata = prepared["structured_business_context"]["sampled_frame_batch"]
        self.assertEqual(metadata["identity_anchor_asset_ref"], "")
        self.assertEqual(metadata["identity_anchor_role"], "none")

    def test_native_perception_identity_is_bound_before_sampled_fallback(self):
        case = {
            "structured_business_context": {
                "continuity_claim_identity": {"customer_claim": "透卡有划痕"},
            },
        }
        parsed = {
            "claimed_item_assessment": {
                "identity_description": "时透无一郎票根风透卡",
                "identity_anchor_asset_ref": "supplemental_image_2",
                "identity_confidence": 0.95,
                "appeared": True,
                "first_visible_timestamp": "01:04.00",
                "last_visible_timestamp": "01:18.00",
            },
        }

        bind_perception_identity(case, parsed)

        identity = case["structured_business_context"]["continuity_claim_identity"]
        self.assertEqual(identity["identity_anchor_asset_ref"], "supplemental_image_2")
        self.assertEqual(identity["identity_description"], "时透无一郎票根风透卡")
        self.assertEqual(identity["customer_claim"], "透卡有划痕")

    def test_sampled_reduce_case_contains_batch_facts_without_resending_media(self):
        original = {
            "frames": [{"global_frame_index": 1}],
            "supplemental_images": [{"image_index": 1}],
            "official_reference_images": [{"reference_index": 1}],
            "structured_business_context": {
                "business_scenario": "product_damage",
                "continuity_claim_identity": {
                    "identity_anchor_asset_ref": "supplemental_image_1",
                },
            },
        }
        rows = [
            {
                "batch_index": 1,
                "batch_total": 2,
                "start_timestamp": "00:00.00",
                "end_timestamp": "00:15.00",
                "parsed": {"sealed_start": True},
            },
            {
                "batch_index": 2,
                "batch_total": 2,
                "start_timestamp": "00:14.00",
                "end_timestamp": "00:29.00",
                "parsed": {"issue_visible": True},
            },
        ]

        prepared = prepare_sampled_reduce_case(original, rows)

        self.assertEqual(prepared["frames"], [])
        self.assertEqual(prepared["supplemental_images"], [])
        self.assertEqual(prepared["official_reference_images"], [])
        self.assertEqual(
            prepared["structured_business_context"]["analysis_mode"],
            "sampled_video_perception_reduce",
        )
        self.assertEqual(
            prepared["structured_business_context"]["sampled_batch_results"],
            rows,
        )

    def test_sampled_reduce_case_visually_rechecks_discovered_candidates_against_supplemental_anchor(self):
        original = {
            "frames": [
                {
                    "video_index": 1,
                    "global_frame_index": index,
                    "timestamp": f"00:{index:02d}.00",
                    "api_path": f"frame-{index}.webp",
                    "api_mime_type": "image/webp",
                }
                for index in range(1, 5)
            ],
            "supplemental_images": [
                {
                    "image_index": 1,
                    "api_path": "claim-anchor.webp",
                    "api_mime_type": "image/webp",
                }
            ],
            "official_reference_images": [{"reference_index": 1}],
            "structured_business_context": {
                "business_scenario": "product_damage",
                "continuity_claim_identity": {
                    "identity_anchor_asset_ref": "supplemental_image_1",
                },
            },
        }
        rows = [
            {
                "batch_index": 1,
                "parsed": {
                    "evidence_refs": [
                        {"field": "claimed_item", "asset_ref": "video_1_frame_1"},
                        {"field": "waybill_visible", "asset_ref": "video_1_frame_2"},
                    ]
                },
            },
            {
                "batch_index": 2,
                "parsed": {
                    "claimed_item_assessment": {
                        "identity_anchor_asset_ref": "video_1_frame_3"
                    },
                    "evidence_refs": [
                        {"field": "claimed_item", "asset_ref": "video_1_frame_4"},
                        {"field": "claimed_item", "asset_ref": "missing_frame"},
                    ],
                },
            },
        ]

        prepared = prepare_sampled_reduce_case(original, rows)

        self.assertEqual(
            [frame["global_frame_index"] for frame in prepared["frames"]],
            [1, 3, 4],
        )
        self.assertEqual(len(prepared["supplemental_images"]), 1)
        self.assertEqual(prepared["official_reference_images"], [])
        self.assertEqual(
            prepared["structured_business_context"][
                "sampled_reduce_candidate_frame_refs"
            ],
            ["video_1_frame_1", "video_1_frame_3", "video_1_frame_4"],
        )
        prompt = build_sampled_video_reduce_prompt(prepared)
        self.assertIn("必须直接查看候选帧与补充图片", prompt)
        self.assertIn("不能按最早出现或批次自报置信度", prompt)

    def test_sampled_batched_pipeline_runs_parallel_observations_then_one_reduce(self):
        case = {
            "case_id": "CASE-BATCHED",
            "scenario": "product_damage",
            "customer_claim": "摆件有划痕",
            "videos": [{"video_index": 1, "duration_seconds": 7.0}],
            "frames": [
                {
                    "video_index": 1,
                    "global_frame_index": index,
                    "timestamp": f"00:{index - 1:02d}.00",
                }
                for index in range(1, 8)
            ],
            "supplemental_images": [],
            "official_reference_images": [],
            "structured_business_context": {"business_scenario": "product_damage"},
        }
        atomic = {
            "sealed_start": True,
            "waybill_visible": True,
            "continuous": True,
            "has_edit": False,
            "has_offscreen": False,
            "has_speed_change": None,
            "all_items_shown": True,
            "issue_visible": True,
            "claimed_item_assessment": {},
            "speed_assessment": {},
            "damage_assessment": {},
            "evidence_refs": [],
        }
        calls = []

        def fake_call(_cfg, current, timeout, retries):
            mode = current["structured_business_context"]["analysis_mode"]
            calls.append(mode)
            parsed = dict(atomic)
            return {
                "status": "success",
                "parsed": parsed,
                "parsed_before_boundary": parsed,
                "latency_seconds": 1.0,
                "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
                "cost": {"estimated_usd": 0.01, "currency": "USD", "amount": 0.01},
            }

        with patch("scripts.run_baidu_video_ab.call_model", side_effect=fake_call):
            result = run_sampled_perception_batched(
                {"provider": "gemini_native"},
                case,
                timeout=60,
                retries=0,
                batch_size=4,
                overlap=1,
                workers=2,
            )

        self.assertEqual(calls.count("sampled_video_batch_observation"), 2)
        self.assertEqual(calls.count("sampled_video_perception_reduce"), 1)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["batching"]["segment_count"], 2)
        self.assertEqual(result["batching"]["total_model_calls"], 3)
        self.assertEqual(result["batching"]["input_representation"], "individual_1080p_frames")
        self.assertEqual(result["usage"]["total_tokens"], 360)
        self.assertEqual(len(result["batch_results"]), 2)

    def test_result_summary_keeps_business_facts_needed_for_effect_scoring(self):
        parsed = {
            "overall_audit": {"conclusion": "不支持", "core_reason": "伤点未在开箱链中看清"},
            "frame_findings": [{"timestamp": "00:35", "visible_facts": "争议商品出现"}],
            "object_continuity_assessment": {"continuity_verdict": "continuous"},
            "video_audit_conclusion": {"playback_speed": "accelerated"},
            "damage_causality_assessment": {"damage_presence": "confirmed"},
        }

        summary = result_summary({
            "status": "failed",
            "status_code": 400,
            "error_type": "hard",
            "error": "invalid generationConfig",
            "parsed_before_boundary": parsed,
            "parsed": parsed,
        })

        self.assertEqual(summary["model_output_before_guards"], parsed)
        self.assertEqual(summary["model_output_after_guards"], parsed)
        self.assertEqual(summary["status_code"], 400)
        self.assertEqual(summary["error"], "invalid generationConfig")

    def test_perception_summary_rejects_http_success_with_truncated_json(self):
        summary = perception_result_summary({
            "status": "success",
            "parsed": {"raw_text": "{\"sealed_start\": true"},
            "parsed_before_boundary": {"raw_text": "{\"sealed_start\": true"},
            "raw_response": {"candidates": [{"finishReason": "MAX_TOKENS"}]},
        })

        self.assertEqual(summary["status"], "invalid_output")
        self.assertEqual(summary["finish_reason"], "MAX_TOKENS")
        self.assertEqual(summary["complete_field_count"], 0)

    def test_perception_summary_counts_deterministic_overall_result(self):
        atomic = {
            "sealed_start": True,
            "waybill_visible": True,
            "continuous": True,
            "has_edit": False,
            "has_offscreen": False,
            "has_speed_change": False,
            "all_items_shown": True,
            "issue_visible": False,
            "claimed_item_assessment": {},
            "speed_assessment": {},
            "damage_assessment": {},
            "evidence_refs": [],
        }
        summary = perception_result_summary({
            "status": "success",
            "parsed_before_boundary": atomic,
            "parsed": {**atomic, "overall_video_result": "noncompliant"},
            "raw_response": {"candidates": [{"finishReason": "STOP"}]},
        })

        self.assertEqual(summary["status"], "success")
        self.assertTrue(summary["field_completeness"]["overall_video_result"])
        self.assertEqual(summary["complete_field_count"], 13)

    def test_profiles_compare_same_models_with_explicit_visual_settings(self):
        profiles = dict(resolve_profiles("lite-default,lite-high,flash36-medium,flash36-high"))

        self.assertNotIn("thinking_level", profiles["lite-default"])
        self.assertEqual(profiles["lite-high"]["thinking_level"], "high")
        self.assertEqual(profiles["lite-high"]["media_resolution"], "high")
        self.assertEqual(profiles["flash36-medium"]["model"], "gemini-3.6-flash")
        self.assertEqual(profiles["flash36-medium"]["thinking_level"], "medium")
        self.assertNotIn("max_output_tokens", profiles["flash36-medium"])
        self.assertEqual(profiles["flash36-high"]["thinking_level"], "high")
        self.assertNotIn("max_output_tokens", profiles["flash36-high"])

    def test_large_video_uses_full_duration_proxy_instead_of_known_time_window(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "case.mp4"
            video.write_bytes(b"large-video")
            proxy_path = root / "proxy.webm"
            proxy_path.write_bytes(b"full-duration-proxy")
            proxy_result = {
                "status": "ready",
                "path": str(proxy_path),
                "mime_type": "video/webm",
                "source_duration_seconds": 178.0,
                "proxy_duration_seconds": 178.0,
            }

            with patch(
                "scripts.run_baidu_video_ab.prepare_native_video_proxy",
                return_value=proxy_result,
            ) as mocked:
                source = prepare_benchmark_native_source(video, root / "output", max_bytes=4)

        mocked.assert_called_once_with(
            video,
            root / "output",
            4,
            profiles=("hevc_mp4", "vp9_webm"),
        )
        self.assertEqual(source["api_path"], str(proxy_path))
        self.assertEqual(source["api_mime_type"], "video/webm")
        self.assertEqual(source["transport"], "full_duration_transcoded_inline")
        self.assertNotIn("source_start_seconds", source)
        self.assertNotIn("source_end_seconds", source)

    def test_proxy_failure_reports_safe_error_type(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "case.mp4"
            video.write_bytes(b"large-video")
            with patch(
                "scripts.run_baidu_video_ab.prepare_native_video_proxy",
                return_value={"status": "unavailable", "error_type": "ffprobe_unavailable"},
            ):
                with self.assertRaisesRegex(SystemExit, "ffprobe_unavailable"):
                    prepare_benchmark_native_source(video, root / "output", max_bytes=4)

    def test_large_video_uses_original_signed_url_before_transcoding(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            video = root / "case.mp4"
            video.write_bytes(b"large-video")
            with patch(
                "scripts.run_baidu_video_ab.prepare_native_video_proxy"
            ) as prepare_proxy:
                source = prepare_benchmark_native_source(
                    video,
                    root / "output",
                    max_bytes=4,
                    file_uri="https://opaque.trycloudflare.com/media/token",
                )

        prepare_proxy.assert_not_called()
        self.assertEqual(source["transport"], "original_signed_url")
        self.assertEqual(
            source["file_uri"],
            "https://opaque.trycloudflare.com/media/token",
        )
        self.assertNotIn("api_path", source)

    def test_transcoded_proxy_is_sent_by_signed_url_without_persisting_local_path(self):
        source = signed_proxy_source(
            {
                "video_index": 1,
                "api_path": "D:/private/proxy.webm",
                "api_mime_type": "video/webm",
                "transport": "full_duration_transcoded_inline",
                "proxy": {"codec_profile": "vp9_webm", "proxy_bytes": 1234},
            },
            "https://opaque.trycloudflare.com/media/token",
        )

        self.assertEqual(source["transport"], "full_duration_transcoded_url")
        self.assertEqual(source["api_mime_type"], "video/webm")
        self.assertEqual(source["proxy"]["codec_profile"], "vp9_webm")
        self.assertNotIn("api_path", source)


if __name__ == "__main__":
    unittest.main()
