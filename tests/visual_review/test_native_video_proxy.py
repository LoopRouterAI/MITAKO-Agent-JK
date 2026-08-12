# -*- coding: utf-8 -*-
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from poc.visual_review_poc.native_video_proxy import (
    _video_metadata,
    build_video_proxy_command,
    prepare_native_video_proxy,
    video_proxy_recommendation,
)


class NativeVideoProxyTest(unittest.TestCase):
    def test_video_metadata_uses_ffprobe_when_opencv_cannot_decode_hevc(self) -> None:
        probe_payload = """{
          "streams": [{
            "codec_type": "video",
            "width": 1920,
            "height": 1080,
            "avg_frame_rate": "30000/1001",
            "nb_frames": "2396",
            "duration": "79.946533",
            "bit_rate": "8123456"
          }],
          "format": {"duration": "79.946533", "bit_rate": "8250000"}
        }"""
        completed = subprocess.CompletedProcess(
            ["ffprobe"], 0, probe_payload, ""
        )

        with patch(
            "poc.visual_review_poc.native_video_proxy._ffprobe_executable",
            return_value="ffprobe",
        ), patch(
            "poc.visual_review_poc.native_video_proxy.subprocess.run",
            return_value=completed,
        ), patch(
            "poc.visual_review_poc.native_video_proxy.cv2.VideoCapture"
        ) as capture:
            metadata = _video_metadata(Path("hevc.mp4"))

        capture.assert_not_called()
        self.assertEqual(metadata["width"], 1920.0)
        self.assertEqual(metadata["height"], 1080.0)
        self.assertAlmostEqual(metadata["fps"], 29.970, places=3)
        self.assertEqual(metadata["frame_count"], 2396.0)
        self.assertAlmostEqual(metadata["duration_seconds"], 79.946533, places=6)
        self.assertEqual(metadata["bit_rate_bps"], 8123456.0)

    def test_ffmpeg_command_uses_hevc_2k_24fps_without_audio_downmix(self) -> None:
        command = build_video_proxy_command(
            "ffmpeg",
            Path("source.mp4"),
            Path("proxy.mp4"),
            max_long_edge=2560,
            target_fps=24.0,
            codec_profile="hevc_mp4",
        )
        serialized = " ".join(command)

        self.assertIn("0:a?", command)
        self.assertIn("libx265", command)
        self.assertIn("fps=24", serialized)
        self.assertIn("min(iw\\,2560)", serialized)
        self.assertIn("-tag:v", command)
        self.assertIn("hvc1", command)
        self.assertIn("force_original_aspect_ratio=decrease", serialized)
        self.assertIn("-maxrate 5500k", serialized)
        self.assertIn("-bufsize 11M", serialized)
        self.assertNotIn("-ac", command)
        self.assertNotIn("960:1280", serialized)
        self.assertEqual(command[-1], "proxy.mp4")

    def test_vp9_proxy_reserves_audio_and_container_budget_below_six_mbps(self) -> None:
        command = build_video_proxy_command(
            "ffmpeg",
            Path("source.mp4"),
            Path("proxy.webm"),
            max_long_edge=2560,
            target_fps=24.0,
            codec_profile="vp9_webm",
        )

        serialized = " ".join(command)
        self.assertIn("libvpx-vp9", command)
        self.assertIn("-b:v 5500k", serialized)
        self.assertIn("-maxrate 5500k", serialized)
        self.assertIn("-bufsize 11M", serialized)

    def test_recommendation_includes_1080p_source_above_six_mbps(self) -> None:
        with patch(
            "poc.visual_review_poc.native_video_proxy._video_metadata",
            return_value={
                "duration_seconds": 60.0,
                "fps": 24.0,
                "frame_count": 1440.0,
                "width": 1920.0,
                "height": 1080.0,
                "bit_rate_bps": 8_000_000.0,
            },
        ):
            recommendation = video_proxy_recommendation(Path("source.mp4"))

        self.assertTrue(recommendation["recommended"])
        self.assertEqual(recommendation["reasons"], ["bitrate_above_6mbps"])

    def test_recommendation_keeps_normal_1080p_24fps_original(self) -> None:
        with patch(
            "poc.visual_review_poc.native_video_proxy._video_metadata",
            return_value={
                "duration_seconds": 60.0,
                "fps": 24.0,
                "frame_count": 1440.0,
                "width": 1920.0,
                "height": 1080.0,
                "bit_rate_bps": 5_500_000.0,
            },
        ):
            recommendation = video_proxy_recommendation(Path("source.mp4"))

        self.assertFalse(recommendation["recommended"])
        self.assertEqual(recommendation["reasons"], [])

    def test_recommendation_keeps_normal_bitrate_1080p_30fps_original(self) -> None:
        with patch(
            "poc.visual_review_poc.native_video_proxy._video_metadata",
            return_value={
                "duration_seconds": 150.0,
                "fps": 30.0,
                "frame_count": 4500.0,
                "width": 1920.0,
                "height": 1080.0,
                "bit_rate_bps": 2_900_000.0,
            },
        ):
            recommendation = video_proxy_recommendation(Path("source.mp4"))

        self.assertFalse(recommendation["recommended"])
        self.assertEqual(recommendation["reasons"], [])
        self.assertEqual(recommendation["observations"], ["fps_above_24"])

    def test_proxy_is_accepted_only_when_duration_and_size_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source.mp4"
            source.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 256)

            def fake_run(command, **_kwargs):
                Path(command[-1]).write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"1" * 128)
                return subprocess.CompletedProcess(command, 0, "", "")

            with patch(
                "poc.visual_review_poc.native_video_proxy._ffmpeg_executable",
                return_value="ffmpeg",
            ), patch(
                "poc.visual_review_poc.native_video_proxy._video_metadata",
                side_effect=[
                    {
                        "duration_seconds": 178.55,
                        "fps": 30.0,
                        "frame_count": 5356.5,
                        "width": 1920.0,
                        "height": 1080.0,
                    },
                    {
                        "duration_seconds": 178.5,
                        "fps": 24.0,
                        "frame_count": 4284.0,
                        "width": 1920.0,
                        "height": 1080.0,
                    },
                ],
            ), patch(
                "poc.visual_review_poc.native_video_proxy.subprocess.run",
                side_effect=fake_run,
            ):
                result = prepare_native_video_proxy(source, Path(temp_dir) / "proxy", 1024)

        self.assertEqual(result["status"], "ready")
        self.assertLessEqual(result["proxy_bytes"], 1024)
        self.assertEqual(result["codec_profile"], "hevc_mp4")
        self.assertEqual(result["mime_type"], "video/mp4")
        self.assertEqual(result["proxy_width"], 1920)
        self.assertEqual(result["proxy_height"], 1080)
        self.assertEqual(result["proxy_fps"], 24.0)

    def test_proxy_never_falls_below_1080p_when_quality_budget_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.mp4"
            source.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 256)

            def oversized_run(command, **_kwargs):
                target = Path(command[-1])
                if target.suffix == ".webm":
                    target.write_bytes(b"\x1aE\xdf\xa3" + b"1" * 4096)
                else:
                    target.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"1" * 4096)
                return subprocess.CompletedProcess(command, 0, "", "")

            with patch(
                "poc.visual_review_poc.native_video_proxy._ffmpeg_executable",
                return_value="ffmpeg",
            ), patch(
                "poc.visual_review_poc.native_video_proxy._video_metadata",
                return_value={
                    "duration_seconds": 10.0,
                    "fps": 24.0,
                    "frame_count": 240.0,
                    "width": 3840.0,
                    "height": 2160.0,
                },
            ), patch(
                "poc.visual_review_poc.native_video_proxy.subprocess.run",
                side_effect=oversized_run,
            ) as run:
                result = prepare_native_video_proxy(
                    source, root / "proxy", 1024, profiles=("hevc_mp4", "vp9_webm")
                )

        commands = [" ".join(call.args[0]) for call in run.call_args_list]
        self.assertTrue(any("min(iw\\,2560)" in command for command in commands))
        self.assertTrue(any("min(iw\\,1920)" in command for command in commands))
        self.assertFalse(any("min(iw\\,1280)" in command for command in commands))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_type"], "quality_budget_conflict")


if __name__ == "__main__":
    unittest.main()
