# -*- coding: utf-8 -*-
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from poc.visual_review_poc.native_video_proxy import (
    build_video_proxy_command,
    prepare_native_video_proxy,
)


class NativeVideoProxyTest(unittest.TestCase):
    def test_ffmpeg_command_preserves_optional_audio_and_bounds_visual_cost(self) -> None:
        command = build_video_proxy_command("ffmpeg", Path("source.mp4"), Path("proxy.mp4"))
        serialized = " ".join(command)

        self.assertIn("0:a?", command)
        self.assertIn("libx264", command)
        self.assertIn("fps=10", serialized)
        self.assertIn("force_original_aspect_ratio=decrease", serialized)
        self.assertEqual(command[-1], "proxy.mp4")

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
                side_effect=[{"duration_seconds": 178.55}, {"duration_seconds": 178.5}],
            ), patch(
                "poc.visual_review_poc.native_video_proxy.subprocess.run",
                side_effect=fake_run,
            ):
                result = prepare_native_video_proxy(source, Path(temp_dir) / "proxy", 1024)

        self.assertEqual(result["status"], "ready")
        self.assertLessEqual(result["proxy_bytes"], 1024)
        self.assertEqual(result["audio_policy"], "preserve_when_present")


if __name__ == "__main__":
    unittest.main()
