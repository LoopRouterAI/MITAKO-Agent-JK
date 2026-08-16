# -*- coding: utf-8 -*-
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np

from poc.visual_review_poc.media_preflight import (
    build_media_preflight_execution,
    build_media_preflight_plan,
    prepare_image_media,
    prepare_image_detail_crop,
)
from poc.visual_review_poc.native_video_proxy import (
    _ffmpeg_executable,
    prepare_native_video_proxy,
)


def test_real_4k_image_becomes_individual_2k_webp_with_auditable_dimensions() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source = root / "source.png"
        x = np.arange(4000, dtype=np.uint16)[None, :]
        y = np.arange(3000, dtype=np.uint16)[:, None]
        image = np.empty((3000, 4000, 3), dtype=np.uint8)
        image[:, :, 0] = (x % 251).astype(np.uint8)
        image[:, :, 1] = (y % 241).astype(np.uint8)
        image[:, :, 2] = ((x + y) % 239).astype(np.uint8)
        ok, encoded = cv2.imencode(".png", image)
        assert ok
        encoded.tofile(str(source))

        diagnostics: list[dict] = []
        prepared = prepare_image_media(
            [{"path": source, "image_index": 1}],
            root / "prepared",
            diagnostics=diagnostics,
        )
        execution = build_media_preflight_execution(
            native_source=None,
            native_status="not_run",
            native_sampling_fps=None,
            frame_fallback_used=False,
            sampled_frame_count=0,
            supplemental_image_count=1,
            image_execution=diagnostics,
        )

        assert len(prepared) == 1
        assert Path(prepared[0]["api_path"]).suffix == ".webp"
        assert diagnostics[0]["source_width"] == 4000
        assert diagnostics[0]["source_height"] == 3000
        assert diagnostics[0]["submitted_width"] == 2560
        assert diagnostics[0]["submitted_height"] == 1920
        assert len(diagnostics[0]["source_sha256"]) == 64
        assert len(diagnostics[0]["submitted_sha256"]) == 64
        assert diagnostics[0]["submitted_encoding"] == "webp"
        assert diagnostics[0]["submitted_webp_lossless"] in {True, False}
        assert diagnostics[0]["submitted_webp_quality"] == (
            None if diagnostics[0]["submitted_webp_lossless"] else 90
        )
        assert execution["images"]["collage_used"] is False
        assert execution["images"]["failed_count"] == 0


def test_real_image_at_exact_3840_edge_keeps_dimensions_and_gets_an_independent_webp() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source = root / "exact-3840.jpg"
        image = np.empty((64, 3840, 3), dtype=np.uint8)
        image[:, :, 0] = np.arange(3840, dtype=np.uint16)[None, :] % 251
        image[:, :, 1] = 127
        image[:, :, 2] = 223
        ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 92])
        assert ok
        encoded.tofile(str(source))

        diagnostics: list[dict] = []
        prepared = prepare_image_media(
            [{"path": source, "image_index": 1}],
            root / "prepared",
            diagnostics=diagnostics,
        )

        submitted = Path(prepared[0]["api_path"])
        assert submitted != source
        assert submitted.suffix == ".webp"
        assert diagnostics[0]["source_width"] == 3840
        assert diagnostics[0]["submitted_width"] == 3840
        assert diagnostics[0]["submitted_height"] == 64
        assert diagnostics[0]["submitted_encoding"] == "webp"
        assert diagnostics[0]["submitted_webp_lossless"] in {True, False}
        assert diagnostics[0]["submitted_webp_quality"] == (
            None if diagnostics[0]["submitted_webp_lossless"] else 90
        )


def test_document_detail_crop_uses_original_pixels_and_keeps_identity() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source = root / "source.png"
        image = np.zeros((3000, 4000, 3), dtype=np.uint8)
        image[600:2400, 800:3200] = (40, 180, 220)
        ok, encoded = cv2.imencode(".png", image)
        assert ok
        encoded.tofile(str(source))
        prepared = prepare_image_media(
            [{"path": source, "image_index": 7}],
            root / "prepared",
        )[0]

        cropped = prepare_image_detail_crop(
            prepared,
            [200, 200, 800, 800],
            root / "detail",
        )

        assert cropped["image_index"] == 7
        assert cropped["path"] == source
        assert Path(cropped["api_path"]) != Path(prepared["api_path"])
        detail = cv2.imdecode(np.fromfile(cropped["api_path"], dtype=np.uint8), cv2.IMREAD_COLOR)
        assert detail is not None
        assert max(detail.shape[:2]) == 2560
        assert cropped["detail_crop_box_2d"] == [200, 200, 800, 800]


def test_real_ffmpeg_proxy_prefers_vp9_and_preserves_full_duration() -> None:
    ffmpeg = _ffmpeg_executable()
    assert ffmpeg, "发布环境必须提供可执行的 FFmpeg"
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        source = root / "source.mkv"
        completed = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=640x360:rate=30",
                "-t",
                "1",
                "-c:v",
                "ffv1",
                "-an",
                str(source),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr

        result = prepare_native_video_proxy(
            source,
            root / "proxy",
            max_bytes=source.stat().st_size,
            timeout_seconds=120,
            profiles=("vp9_webm",),
        )

        assert result["status"] == "ready", result
        assert result["codec_profile"] == "vp9_webm"
        assert result["proxy_width"] == 640
        assert result["proxy_height"] == 360
        assert result["proxy_fps"] == 24.0
        assert abs(result["source_duration_seconds"] - result["proxy_duration_seconds"]) <= 0.1
        assert result["proxy_bytes"] < result["source_bytes"]
        assert len(result["source_sha256"]) == 64
        assert len(result["proxy_sha256"]) == 64

        plan = build_media_preflight_plan([
            {
                "asset_id": "video-1",
                "original_name": source.name,
                "mime_type": "video/x-matroska",
                "size": source.stat().st_size,
            }
        ])
        assert plan["assets"][0]["preferred_codecs"] == ["vp9"]
