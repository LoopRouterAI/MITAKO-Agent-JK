# -*- coding: utf-8 -*-
from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any, Dict

import cv2

from review_media_safety import valid_media_file

try:
    import imageio_ffmpeg
except ImportError:  # pragma: no cover - 发布依赖缺失时走既有抽帧回退
    imageio_ffmpeg = None


def _ffmpeg_executable() -> str:
    if imageio_ffmpeg is None:
        return ""
    try:
        return str(imageio_ffmpeg.get_ffmpeg_exe() or "")
    except Exception:
        return ""


def _video_metadata(path: Path) -> Dict[str, float]:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        return {}
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        frames = float(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
        return {
            "fps": fps,
            "frame_count": frames,
            "duration_seconds": frames / fps if fps > 0 else 0.0,
            "width": float(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0.0),
            "height": float(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0.0),
        }
    finally:
        capture.release()


def build_video_proxy_command(ffmpeg_exe: str, source: Path, target: Path) -> list[str]:
    return [
        ffmpeg_exe,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-vf",
        "scale=960:1280:force_original_aspect_ratio=decrease:force_divisible_by=2,fps=10",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "26",
        "-maxrate",
        "2M",
        "-bufsize",
        "4M",
        "-c:a",
        "aac",
        "-b:a",
        "64k",
        "-ac",
        "1",
        "-movflags",
        "+faststart",
        "-map_metadata",
        "-1",
        str(target),
    ]


def prepare_native_video_proxy(
    source: Path,
    output_dir: Path,
    max_bytes: int,
    timeout_seconds: int = 300,
) -> Dict[str, Any]:
    ffmpeg_exe = _ffmpeg_executable()
    source_metadata = _video_metadata(source)
    if not ffmpeg_exe or source_metadata.get("duration_seconds", 0.0) <= 0:
        return {"status": "unavailable", "audio_policy": "preserve_when_present"}
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "native_video_proxy.mp4"
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            build_video_proxy_command(ffmpeg_exe, source, target),
            capture_output=True,
            text=True,
            timeout=max(30, min(int(timeout_seconds), 600)),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        target.unlink(missing_ok=True)
        return {
            "status": "failed",
            "error_type": type(exc).__name__,
            "audio_policy": "preserve_when_present",
        }
    proxy_metadata = _video_metadata(target)
    proxy_bytes = target.stat().st_size if target.is_file() else 0
    source_duration = float(source_metadata.get("duration_seconds") or 0.0)
    proxy_duration = float(proxy_metadata.get("duration_seconds") or 0.0)
    duration_tolerance = max(1.0, source_duration * 0.02)
    valid = (
        completed.returncode == 0
        and valid_media_file(target)
        and 0 < proxy_bytes <= max_bytes
        and abs(source_duration - proxy_duration) <= duration_tolerance
    )
    if not valid:
        target.unlink(missing_ok=True)
        return {
            "status": "failed",
            "error_type": "proxy_validation_failed",
            "proxy_bytes": proxy_bytes,
            "audio_policy": "preserve_when_present",
        }
    return {
        "status": "ready",
        "path": str(target),
        "source_bytes": source.stat().st_size,
        "proxy_bytes": proxy_bytes,
        "source_duration_seconds": round(source_duration, 3),
        "proxy_duration_seconds": round(proxy_duration, 3),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "audio_policy": "preserve_when_present",
    }
