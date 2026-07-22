# -*- coding: utf-8 -*-
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from poc.visual_review_poc import workbench_server


class WorkbenchStrongProfileTest(unittest.TestCase):
    def test_folder_review_prepares_official_references_after_frontdesk_context_merge(self) -> None:
        observed = {}
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            case = {
                "case_id": "CASE-OFFICIAL-REF",
                "scenario": "video_unboxing",
                "scenario_label": "发错货审核",
                "videos": [],
                "frames": [],
                "supplemental_images": [],
            }

            def merge_context(current, *_):
                current["structured_business_context"] = {
                    "frontdesk_evidence_package": {
                        "fulfillment_baseline": {"expected_items": [{"item_ref": "LINE-1", "sku": "SKU-1"}]},
                    }
                }
                return current

            def prepare(current, *_):
                self.assertIn("frontdesk_evidence_package", current["structured_business_context"])
                current["official_reference_images"] = [{"reference_index": 1}]
                return current

            def model_result(_cfg, current, **_kwargs):
                observed["official_count"] = len(current.get("official_reference_images") or [])
                return {"status": "success", "parsed": {"predicted_label": "review", "confidence": 0.6}}

            with patch.object(workbench_server, "load_visual_env"), patch.object(
                workbench_server, "load_case_bundle", return_value=case
            ), patch.object(
                workbench_server, "apply_frontdesk_context", side_effect=merge_context
            ), patch.object(
                workbench_server, "prepare_official_reference_images", side_effect=prepare
            ), patch.object(
                workbench_server, "call_model_chunked", side_effect=model_result
            ), patch.object(
                workbench_server,
                "_agent_report_response",
                return_value={"summary": {"review_status": "completed"}},
            ):
                workbench_server._run_folder_agent_review(
                    folder, "video_unboxing", "gemini35", {}, "adaptive", 1.0, 24, 24, 12
                )

        self.assertEqual(observed["official_count"], 1)

    def test_auto_model_route_uses_configured_fallback_after_primary_transport_failure(self) -> None:
        failed = {
            "status": "failed",
            "error_type": "hard",
            "status_code": None,
            "latency_seconds": 10.0,
            "model_latency_seconds_sum": 20.0,
            "cost_status": "unknown",
            "unknown_cost_calls": 2,
            "chunking": {"total_model_calls": 2},
        }
        succeeded = {
            "status": "success",
            "latency_seconds": 30.0,
            "model_latency_seconds_sum": 50.0,
            "cost_status": "estimated",
            "unknown_cost_calls": 0,
            "chunking": {"total_model_calls": 5},
            "parsed": {"predicted_label": "review"},
        }
        with patch.dict(
            "os.environ",
            {
                "VISUAL_REVIEW_PRIMARY_MODEL": "gemini-3.5-flash",
                "VISUAL_REVIEW_FALLBACK_MODELS": "qwen3.5-flash",
            },
            clear=False,
        ), patch.object(
            workbench_server,
            "call_model_chunked",
            side_effect=[failed, succeeded],
        ) as model:
            result = workbench_server._call_model_chunked_with_fallback(
                "auto", {"case_id": "CASE-ROUTE"}, timeout=180, retries=0
            )

        self.assertEqual(model.call_count, 2)
        self.assertEqual(model.call_args_list[0].args[0]["model"], "gemini-3.5-flash")
        self.assertEqual(model.call_args_list[1].args[0]["model"], "qwen3.5-flash")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["route_fallback_count"], 1)
        self.assertEqual(result["cost_status"], "partial_unknown")
        self.assertEqual(result["unknown_cost_calls"], 2)
        self.assertEqual(result["chunking"]["total_model_calls"], 7)

    def test_folder_review_uses_configured_model_timeout_and_retries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            case = {
                "case_id": "CASE-FOLDER-CONFIG",
                "scenario": "product_damage",
                "scenario_label": "商品有伤审核",
                "videos": [],
                "frames": [],
                "supplemental_images": [],
            }
            with patch.dict(
                "os.environ",
                {"REVIEW_MODEL_TIMEOUT_SECONDS": "181", "REVIEW_MODEL_RETRIES": "1"},
                clear=False,
            ), patch.object(workbench_server, "load_visual_env"), patch.object(
                workbench_server, "load_case_bundle", return_value=case
            ), patch.object(
                workbench_server, "apply_frontdesk_context", side_effect=lambda current, *_: current
            ), patch.object(
                workbench_server, "call_model_chunked", return_value={"status": "failed"}
            ) as model, patch.object(
                workbench_server,
                "_agent_report_response",
                return_value={"summary": {"review_status": "failed"}},
            ):
                workbench_server._run_folder_agent_review(
                    folder,
                    "product_damage",
                    "gemini35",
                    {},
                    "dense",
                    1.0,
                    1200,
                    24,
                    12,
                )

        self.assertEqual(model.call_args.kwargs["timeout"], 181)
        self.assertEqual(model.call_args.kwargs["retries"], 1)

    def test_single_upload_uses_dense_chunked_engine_for_strong_profile(self) -> None:
        observed = {}
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "evidence.mp4"
            video.write_bytes(b"video")
            case = {
                "case_id": "CASE-STRONG",
                "scenario": "video_unboxing",
                "scenario_label": "开箱视频审核",
                "videos": [{"duration_seconds": 452}],
                "frames": [{} for _ in range(905)],
                "supplemental_images": [],
            }

            def load_bundle(sample_dir, args, run_dir, scenario_override=""):
                observed.update(
                    {
                        "sample_dir": sample_dir,
                        "sampling_mode": args.sampling_mode,
                        "fps": args.fps,
                        "max_frames": args.max_frames_per_video,
                        "api_frame_limit": args.api_frame_limit,
                        "scenario_override": scenario_override,
                    }
                )
                return case

            response = {
                "summary": {"review_status": "completed"},
                "agent_report": {"inference_estimate": {"segment_count": 38}},
            }
            with patch.object(workbench_server, "load_visual_env"), patch.object(
                workbench_server, "load_case_bundle", side_effect=load_bundle
            ), patch.object(
                workbench_server, "apply_frontdesk_context", side_effect=lambda current, *_: current
            ), patch.object(
                workbench_server, "call_model_chunked", return_value={"status": "success"}
            ) as model, patch.object(
                workbench_server, "_agent_report_response", return_value=response
            ):
                result = workbench_server._run_review(
                    video,
                    "video_unboxing",
                    fps=2.0,
                    max_frames=24,
                    api_frame_limit=24,
                    probe_seconds=12,
                    review_model="backup",
                    evidence_context={},
                )

        self.assertEqual(observed["sample_dir"], video.parent)
        self.assertEqual(observed["sampling_mode"], "dense")
        self.assertEqual(observed["fps"], 2.0)
        self.assertEqual(observed["max_frames"], 1800)
        self.assertEqual(observed["api_frame_limit"], 24)
        self.assertEqual(observed["scenario_override"], "video_unboxing")
        self.assertEqual(model.call_count, 1)
        self.assertTrue(result["ok"])
        self.assertEqual(result["sampling"]["sampled_frames"], 905)
        self.assertEqual(result["sampling"]["model_segments"], 38)

    def test_standard_profile_enforces_full_timeline_one_fps(self) -> None:
        observed = {}
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "evidence.mp4"
            video.write_bytes(b"video")

            def load_bundle(sample_dir, args, run_dir, scenario_override=""):
                observed.update({
                    "sampling_mode": args.sampling_mode,
                    "fps": args.fps,
                    "max_frames": args.max_frames_per_video,
                    "scenario_override": scenario_override,
                })
                return {
                    "case_id": "CASE-STANDARD",
                    "scenario": "product_damage",
                    "scenario_label": "商品有伤审核",
                    "videos": [{"duration_seconds": 72}],
                    "frames": [{} for _ in range(73)],
                    "supplemental_images": [],
                }

            with patch.object(workbench_server, "load_visual_env"), patch.object(
                workbench_server, "load_case_bundle", side_effect=load_bundle
            ), patch.object(
                workbench_server, "apply_frontdesk_context", side_effect=lambda current, *_: current
            ), patch.object(
                workbench_server, "call_model_chunked", return_value={"status": "success"}
            ), patch.object(
                workbench_server,
                "_agent_report_response",
                return_value={"summary": {"review_status": "completed"}, "agent_report": {"inference_estimate": {"segment_count": 4}}},
            ):
                workbench_server._run_review(video, "product_damage", 0.2, 24, 24, 12, "standard", {})

        self.assertEqual(observed, {
            "sampling_mode": "dense",
            "fps": 1.0,
            "max_frames": 1200,
            "scenario_override": "product_damage",
        })


if __name__ == "__main__":
    unittest.main()
