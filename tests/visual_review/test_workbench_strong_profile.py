# -*- coding: utf-8 -*-
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from poc.visual_review_poc import workbench_server


class WorkbenchStrongProfileTest(unittest.TestCase):
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

            def load_bundle(sample_dir, args, run_dir):
                observed.update(
                    {
                        "sample_dir": sample_dir,
                        "sampling_mode": args.sampling_mode,
                        "fps": args.fps,
                        "max_frames": args.max_frames_per_video,
                        "api_frame_limit": args.api_frame_limit,
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
        self.assertEqual(model.call_count, 1)
        self.assertTrue(result["ok"])
        self.assertEqual(result["sampling"]["sampled_frames"], 905)
        self.assertEqual(result["sampling"]["model_segments"], 38)

    def test_standard_profile_enforces_full_timeline_one_fps(self) -> None:
        observed = {}
        with tempfile.TemporaryDirectory() as temp_dir:
            video = Path(temp_dir) / "evidence.mp4"
            video.write_bytes(b"video")

            def load_bundle(sample_dir, args, run_dir):
                observed.update({"sampling_mode": args.sampling_mode, "fps": args.fps, "max_frames": args.max_frames_per_video})
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

        self.assertEqual(observed, {"sampling_mode": "dense", "fps": 1.0, "max_frames": 1200})


if __name__ == "__main__":
    unittest.main()
