# -*- coding: utf-8 -*-
from __future__ import annotations

import subprocess
import hashlib
import inspect
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from poc.visual_review_poc.native_video_proxy import (
    _video_metadata,
    build_video_proxy_command,
    prepare_native_video_proxy,
    video_proxy_recommendation,
    video_proxy_recommendation_from_metadata,
)


class NativeVideoProxyTest(unittest.TestCase):
    def test_large_efficient_video_is_evaluated_without_retranscoding(self):
        result = video_proxy_recommendation_from_metadata({
            "width": 1920,
            "height": 1080,
            "fps": 24,
            "bit_rate_bps": 6_000_000,
            "source_bytes": 600 * 1024 * 1024,
            "codec_name": "vp9",
        })

        self.assertFalse(result["recommended"])
        self.assertIn("source_above_100mb_already_efficient", result["observations"])

    def test_default_proxy_uses_only_vp9_until_channel_compatibility_is_explicit(self) -> None:
        default = inspect.signature(prepare_native_video_proxy).parameters["profiles"].default

        self.assertEqual(default, ("vp9_webm",))

    def test_recommendation_uses_strict_media_contract_thresholds(self) -> None:
        base = {
            "width": 2560,
            "height": 1440,
            "fps": 24.0,
            "bit_rate_bps": 6_000_000,
            "source_bytes": 100 * 1024 * 1024 - 1,
        }
        self.assertFalse(video_proxy_recommendation_from_metadata(base)["recommended"])

        cases = {
            "source_above_100mb": {**base, "source_bytes": 100 * 1024 * 1024},
            "resolution_above_2k": {**base, "width": 2561},
            "bitrate_above_6mbps": {**base, "bit_rate_bps": 6_000_001},
        }
        for reason, metadata in cases.items():
            with self.subTest(reason=reason):
                recommendation = video_proxy_recommendation_from_metadata(metadata)
                self.assertTrue(recommendation["recommended"])
                self.assertEqual(recommendation["reasons"], [reason])

        fps_only = video_proxy_recommendation_from_metadata({**base, "fps": 30.0})
        self.assertFalse(fps_only["recommended"])
        self.assertIn("fps_above_24_without_size_quality_pressure", fps_only["observations"])

    def test_expensive_transcodes_respect_the_shared_concurrency_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sources = [root / f"source-{index}.mp4" for index in range(2)]
            for source in sources:
                source.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 256)

            active = 0
            maximum_active = 0
            active_lock = threading.Lock()

            def fake_run(command, **_kwargs):
                nonlocal active, maximum_active
                with active_lock:
                    active += 1
                    maximum_active = max(maximum_active, active)
                try:
                    time.sleep(0.05)
                    Path(command[-1]).write_bytes(
                        b"\x00\x00\x00\x18ftypmp42" + b"1" * 128
                    )
                    return subprocess.CompletedProcess(command, 0, "", "")
                finally:
                    with active_lock:
                        active -= 1

            metadata = {
                "duration_seconds": 60.0,
                "fps": 24.0,
                "frame_count": 1440.0,
                "width": 1920.0,
                "height": 1080.0,
                "bit_rate_bps": 5_000_000.0,
            }
            results = []

            def transcode(index: int) -> None:
                results.append(
                    prepare_native_video_proxy(
                        sources[index],
                        root / f"proxy-{index}",
                        1024,
                        profiles=("hevc_mp4",),
                    )
                )

            with patch(
                "poc.visual_review_poc.native_video_proxy._ffmpeg_executable",
                return_value="ffmpeg",
            ), patch(
                "poc.visual_review_poc.native_video_proxy._video_metadata",
                return_value=metadata,
            ), patch(
                "poc.visual_review_poc.native_video_proxy.subprocess.run",
                side_effect=fake_run,
            ), patch(
                "poc.visual_review_poc.native_video_proxy._TRANSCODE_SLOTS",
                threading.BoundedSemaphore(1),
            ):
                threads = [threading.Thread(target=transcode, args=(index,)) for index in range(2)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()

        self.assertEqual(maximum_active, 1)
        self.assertEqual([result["status"] for result in results], ["ready", "ready"])
        self.assertTrue(all(result["transcode_queue_seconds"] >= 0 for result in results))

    def test_verified_proxy_cache_reuses_transcode_by_source_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.mp4"
            source.write_bytes(b"source-video")

            def fake_prepare(current_source, output_dir, _max_bytes, **_kwargs):
                output_dir.mkdir(parents=True, exist_ok=True)
                proxy = output_dir / "native_video_proxy_vp9_webm_2560.webm"
                proxy.write_bytes(b"verified-proxy")
                return {
                    "status": "ready",
                    "path": str(proxy),
                    "mime_type": "video/webm",
                    "codec_profile": "vp9_webm",
                    "source_bytes": current_source.stat().st_size,
                    "proxy_bytes": proxy.stat().st_size,
                    "source_sha256": hashlib.sha256(current_source.read_bytes()).hexdigest(),
                    "proxy_sha256": hashlib.sha256(proxy.read_bytes()).hexdigest(),
                }

            with patch(
                "poc.visual_review_poc.native_video_proxy._prepare_native_video_proxy",
                side_effect=fake_prepare,
            ) as transcode, patch(
                "poc.visual_review_poc.native_video_proxy.valid_media_file",
                return_value=True,
            ):
                first = prepare_native_video_proxy(
                    source,
                    root / "attempt-1",
                    1024,
                    cache_dir=root / "cache",
                )
                second = prepare_native_video_proxy(
                    source,
                    root / "attempt-2",
                    1024,
                    cache_dir=root / "cache",
                )

        transcode.assert_called_once()
        self.assertFalse(first["cache_hit"])
        self.assertTrue(second["cache_hit"])
        self.assertEqual(first["proxy_sha256"], second["proxy_sha256"])
        self.assertEqual(first["path"], second["path"])

    def test_concurrent_jobs_share_one_cached_transcode_for_the_same_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.mp4"
            source.write_bytes(b"same-source-video")
            calls = 0
            calls_lock = threading.Lock()
            results = []

            def fake_prepare(current_source, output_dir, _max_bytes, **_kwargs):
                nonlocal calls
                with calls_lock:
                    calls += 1
                time.sleep(0.05)
                output_dir.mkdir(parents=True, exist_ok=True)
                proxy = output_dir / "native_video_proxy_vp9_webm_2560.webm"
                proxy.write_bytes(b"single-persisted-proxy")
                return {
                    "status": "ready",
                    "path": str(proxy),
                    "mime_type": "video/webm",
                    "codec_profile": "vp9_webm",
                    "source_bytes": current_source.stat().st_size,
                    "proxy_bytes": proxy.stat().st_size,
                    "source_sha256": hashlib.sha256(current_source.read_bytes()).hexdigest(),
                    "proxy_sha256": hashlib.sha256(proxy.read_bytes()).hexdigest(),
                }

            def prepare() -> None:
                results.append(
                    prepare_native_video_proxy(
                        source,
                        root / "unused-attempt",
                        1024,
                        cache_dir=root / "cache",
                    )
                )

            with patch(
                "poc.visual_review_poc.native_video_proxy._prepare_native_video_proxy",
                side_effect=fake_prepare,
            ), patch(
                "poc.visual_review_poc.native_video_proxy.valid_media_file",
                return_value=True,
            ):
                threads = [threading.Thread(target=prepare) for _ in range(2)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()

        self.assertEqual(calls, 1)
        self.assertEqual(len(results), 2)
        self.assertEqual(sum(bool(item["cache_hit"]) for item in results), 1)
        self.assertEqual(len({item["path"] for item in results}), 1)

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

    def test_ffmpeg_command_uses_fast_hevc_2k_24fps_without_audio_downmix(self) -> None:
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
        self.assertIn("faster", command)
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

    def test_proxy_accepts_rotation_materialized_as_swapped_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "rotated-source.mp4"
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
                        "duration_seconds": 242.289,
                        "fps": 30.0,
                        "frame_count": 7268.67,
                        "width": 1920.0,
                        "height": 1080.0,
                        "bit_rate_bps": 20_000_000.0,
                    },
                    {
                        "duration_seconds": 242.25,
                        "fps": 24.0,
                        "frame_count": 5814.0,
                        "width": 1080.0,
                        "height": 1920.0,
                        "bit_rate_bps": 5_000_000.0,
                    },
                ],
            ), patch(
                "poc.visual_review_poc.native_video_proxy.subprocess.run",
                side_effect=fake_run,
            ):
                result = prepare_native_video_proxy(
                    source,
                    Path(temp_dir) / "proxy",
                    1024,
                    profiles=("hevc_mp4",),
                )

        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["proxy_width"], 1080)
        self.assertEqual(result["proxy_height"], 1920)

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
        self.assertIn("-cpu-used 4", serialized)

    def test_proxy_command_honors_duration_based_byte_budget(self) -> None:
        command = build_video_proxy_command(
            "ffmpeg",
            Path("source.mp4"),
            Path("proxy.mp4"),
            max_long_edge=2560,
            target_fps=24.0,
            codec_profile="hevc_mp4",
            target_video_bitrate_bps=3_700_000,
        )

        serialized = " ".join(command)
        self.assertIn("-maxrate 3700k", serialized)
        self.assertIn("-bufsize 7400k", serialized)

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

    def test_recommendation_assesses_source_at_one_hundred_mb_even_when_quality_is_normal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "large-source.mp4"
            source.write_bytes(b"0")
            with patch.object(
                Path,
                "is_file",
                return_value=True,
            ), patch.object(
                Path,
                "stat",
                return_value=type("Stat", (), {"st_size": 100 * 1024 * 1024})(),
            ), patch(
                "poc.visual_review_poc.native_video_proxy._video_metadata",
                return_value={
                    "duration_seconds": 240.0,
                    "fps": 24.0,
                    "frame_count": 5760.0,
                    "width": 1920.0,
                    "height": 1080.0,
                    "bit_rate_bps": 4_000_000.0,
                },
            ):
                recommendation = video_proxy_recommendation(source)

        self.assertTrue(recommendation["recommended"])
        self.assertEqual(recommendation["reasons"], ["source_above_100mb"])

    def test_recommendation_keeps_compact_1080p_30fps_source(self) -> None:
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
        self.assertEqual(
            recommendation["observations"],
            ["fps_above_24_without_size_quality_pressure"],
        )

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
                result = prepare_native_video_proxy(
                    source,
                    Path(temp_dir) / "proxy",
                    1024,
                    profiles=("hevc_mp4",),
                )

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
