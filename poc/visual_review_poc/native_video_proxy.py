# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Iterable

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


def _ffprobe_executable() -> str:
    configured = os.getenv("REVIEW_FFPROBE_PATH", "").strip()
    candidates = [
        configured,
        shutil.which("ffprobe") or "",
        str(
            Path(__file__).resolve().parents[2]
            / "node_modules"
            / "ffprobe-static"
            / "bin"
            / "win32"
            / "x64"
            / "ffprobe.exe"
        ),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return ""


def _ratio(value: Any) -> float:
    text = str(value or "").strip()
    if not text or text in {"0/0", "N/A"}:
        return 0.0
    try:
        if "/" in text:
            numerator, denominator = text.split("/", 1)
            return float(numerator) / float(denominator)
        return float(text)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def _video_metadata(path: Path) -> Dict[str, float]:
    ffprobe_exe = _ffprobe_executable()
    if ffprobe_exe:
        try:
            completed = subprocess.run(
                [
                    ffprobe_exe,
                    "-v", "error",
                    "-select_streams", "v:0",
                    "-show_entries",
                    "stream=width,height,avg_frame_rate,r_frame_rate,nb_frames,duration,bit_rate:format=duration,bit_rate,size",
                    "-of", "json",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
            payload = json.loads(completed.stdout or "{}") if completed.returncode == 0 else {}
            streams = payload.get("streams") or []
            stream = streams[0] if streams else {}
            fps = _ratio(stream.get("avg_frame_rate")) or _ratio(stream.get("r_frame_rate"))
            duration = _ratio(stream.get("duration")) or _ratio((payload.get("format") or {}).get("duration"))
            frame_count = _ratio(stream.get("nb_frames"))
            if frame_count <= 0 and duration > 0 and fps > 0:
                frame_count = duration * fps
            metadata = {
                "fps": fps,
                "frame_count": frame_count,
                "duration_seconds": duration,
                "width": _ratio(stream.get("width")),
                "height": _ratio(stream.get("height")),
                "bit_rate_bps": _ratio(stream.get("bit_rate"))
                or _ratio((payload.get("format") or {}).get("bit_rate")),
            }
            if min(metadata["duration_seconds"], metadata["width"], metadata["height"]) > 0:
                return metadata
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
            pass

    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        return {}
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
        frames = float(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
        duration = frames / fps if fps > 0 else 0.0
        return {
            "fps": fps,
            "frame_count": frames,
            "duration_seconds": duration,
            "width": float(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0.0),
            "height": float(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0.0),
            "bit_rate_bps": (
                float(path.stat().st_size * 8) / duration
                if duration > 0 and path.is_file()
                else 0.0
            ),
        }
    finally:
        capture.release()


PROXY_CODEC_PROFILES = {
    "hevc_mp4": {
        "suffix": ".mp4",
        "mime_type": "video/mp4",
        "video_args": [
            "-c:v", "libx265", "-preset", "medium", "-crf", "21",
            "-maxrate", "5500k", "-bufsize", "11M",
            "-tag:v", "hvc1", "-pix_fmt", "yuv420p",
        ],
        "audio_args": ["-c:a", "aac", "-b:a", "128k"],
        "container_args": ["-movflags", "+faststart"],
    },
    "vp9_webm": {
        "suffix": ".webm",
        "mime_type": "video/webm",
        "video_args": [
            "-c:v", "libvpx-vp9", "-deadline", "good", "-cpu-used", "2",
            "-row-mt", "1", "-crf", "24", "-b:v", "5500k",
            "-maxrate", "5500k", "-bufsize", "11M", "-pix_fmt", "yuv420p",
        ],
        "audio_args": ["-c:a", "libopus", "-b:a", "128k"],
        "container_args": [],
    },
}


def video_proxy_recommendation(
    source: Path,
    *,
    max_long_edge: int = 2560,
    max_fps: float = 24.0,
    max_bitrate_bps: float = 6_000_000.0,
) -> Dict[str, Any]:
    """只在原片明显超出审核上传质量预算时建议生成质量代理。"""
    metadata = _video_metadata(source)
    reasons = []
    observations = []
    if max(float(metadata.get("width") or 0), float(metadata.get("height") or 0)) > max_long_edge:
        reasons.append("resolution_above_2k")
    if float(metadata.get("fps") or 0) > max_fps + 0.05:
        observations.append("fps_above_24")
    if float(metadata.get("bit_rate_bps") or 0) > max_bitrate_bps:
        reasons.append("bitrate_above_6mbps")
    return {
        "recommended": bool(reasons),
        "reasons": reasons,
        "observations": observations,
        "source_metadata": metadata,
        "max_long_edge": int(max_long_edge),
        "max_fps": float(max_fps),
        "max_bitrate_bps": float(max_bitrate_bps),
    }


def _fps_text(value: float) -> str:
    rounded = round(float(value), 3)
    return str(int(rounded)) if rounded.is_integer() else str(rounded)


def build_video_proxy_command(
    ffmpeg_exe: str,
    source: Path,
    target: Path,
    *,
    max_long_edge: int = 2560,
    target_fps: float = 24.0,
    codec_profile: str = "hevc_mp4",
) -> list[str]:
    profile = PROXY_CODEC_PROFILES[codec_profile]
    scale = (
        f"scale=w=min(iw\\,{int(max_long_edge)}):h=min(ih\\,{int(max_long_edge)}):"
        "force_original_aspect_ratio=decrease:force_divisible_by=2:flags=lanczos,"
        f"fps={_fps_text(target_fps)}"
    )
    command = [
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
        scale,
        *profile["video_args"],
        *profile["audio_args"],
        *profile["container_args"],
        "-map_metadata",
        "-1",
        str(target),
    ]
    return command


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _proxy_metadata_valid(
    source: Dict[str, float],
    proxy: Dict[str, float],
    *,
    max_long_edge: int,
    target_fps: float,
    max_bitrate_bps: float = 6_000_000.0,
) -> bool:
    source_duration = float(source.get("duration_seconds") or 0.0)
    proxy_duration = float(proxy.get("duration_seconds") or 0.0)
    duration_tolerance = max(0.1, 2.0 / max(target_fps, 1.0))
    if source_duration <= 0 or abs(source_duration - proxy_duration) > duration_tolerance:
        return False

    source_width = int(source.get("width") or 0)
    source_height = int(source.get("height") or 0)
    proxy_width = int(proxy.get("width") or 0)
    proxy_height = int(proxy.get("height") or 0)
    if min(source_width, source_height, proxy_width, proxy_height) <= 0:
        return False
    if proxy_width > source_width or proxy_height > source_height:
        return False
    if max(proxy_width, proxy_height) > max_long_edge:
        return False
    required_short_edge = min(min(source_width, source_height), 1080)
    if min(proxy_width, proxy_height) < required_short_edge:
        return False

    proxy_fps = float(proxy.get("fps") or 0.0)
    if abs(proxy_fps - target_fps) > 0.05:
        return False
    expected_frames = proxy_duration * target_fps
    if abs(float(proxy.get("frame_count") or 0.0) - expected_frames) > 2.0:
        return False
    proxy_bitrate = float(proxy.get("bit_rate_bps") or 0.0)
    if proxy_bitrate > max_bitrate_bps * 1.1:
        return False
    return True


def prepare_native_video_proxy(
    source: Path,
    output_dir: Path,
    max_bytes: int,
    timeout_seconds: int = 1800,
    profiles: Iterable[str] = ("hevc_mp4", "vp9_webm"),
) -> Dict[str, Any]:
    ffmpeg_exe = _ffmpeg_executable()
    source_metadata = _video_metadata(source)
    source_bytes = source.stat().st_size if source.is_file() else 0
    if not ffmpeg_exe or source_metadata.get("duration_seconds", 0.0) <= 0:
        return {
            "status": "unavailable",
            "error_type": "video_metadata_unavailable" if ffmpeg_exe else "ffmpeg_unavailable",
            "audio_policy": "preserve_when_present",
        }
    selected_profiles = tuple(item for item in profiles if item in PROXY_CODEC_PROFILES)
    if not selected_profiles:
        return {"status": "failed", "error_type": "unsupported_proxy_profile"}
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    deadline = started + max(30, min(int(timeout_seconds), 1800))
    source_fps = float(source_metadata.get("fps") or 0.0)
    target_fps = min(source_fps, 24.0) if source_fps > 0 else 24.0
    source_long_edge = max(int(source_metadata.get("width") or 0), int(source_metadata.get("height") or 0))
    long_edges = [2560]
    if source_long_edge > 1920:
        long_edges.append(1920)
    attempts = []

    for max_long_edge in long_edges:
        for codec_profile in selected_profiles:
            profile = PROXY_CODEC_PROFILES[codec_profile]
            target = output_dir / f"native_video_proxy_{codec_profile}_{max_long_edge}{profile['suffix']}"
            target.unlink(missing_ok=True)
            remaining = int(deadline - time.perf_counter())
            if remaining < 1:
                return {
                    "status": "failed",
                    "error_type": "proxy_timeout",
                    "attempts": attempts,
                    "audio_policy": "transcode_when_present_no_downmix",
                }
            try:
                completed = subprocess.run(
                    build_video_proxy_command(
                        ffmpeg_exe,
                        source,
                        target,
                        max_long_edge=max_long_edge,
                        target_fps=target_fps,
                        codec_profile=codec_profile,
                    ),
                    capture_output=True,
                    text=True,
                    timeout=max(1, remaining),
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                target.unlink(missing_ok=True)
                attempts.append({
                    "codec_profile": codec_profile,
                    "max_long_edge": max_long_edge,
                    "status": type(exc).__name__,
                })
                continue

            proxy_bytes = target.stat().st_size if target.is_file() else 0
            if completed.returncode != 0 or not valid_media_file(target):
                target.unlink(missing_ok=True)
                attempts.append({
                    "codec_profile": codec_profile,
                    "max_long_edge": max_long_edge,
                    "status": "encode_failed",
                    "returncode": completed.returncode,
                })
                continue
            if not 0 < proxy_bytes <= max_bytes or (source_bytes > 0 and proxy_bytes >= source_bytes):
                target.unlink(missing_ok=True)
                attempts.append({
                    "codec_profile": codec_profile,
                    "max_long_edge": max_long_edge,
                    "status": "not_smaller_than_source" if proxy_bytes >= source_bytes > 0 else "size_exceeded",
                    "proxy_bytes": proxy_bytes,
                })
                continue

            proxy_metadata = _video_metadata(target)
            if not _proxy_metadata_valid(
                source_metadata,
                proxy_metadata,
                max_long_edge=max_long_edge,
                target_fps=target_fps,
            ):
                target.unlink(missing_ok=True)
                attempts.append({
                    "codec_profile": codec_profile,
                    "max_long_edge": max_long_edge,
                    "status": "metadata_validation_failed",
                })
                continue

            return {
                "status": "ready",
                "path": str(target),
                "mime_type": profile["mime_type"],
                "codec_profile": codec_profile,
                "source_bytes": source_bytes,
                "proxy_bytes": proxy_bytes,
                "source_sha256": _sha256(source),
                "proxy_sha256": _sha256(target),
                "source_duration_seconds": round(float(source_metadata["duration_seconds"]), 3),
                "proxy_duration_seconds": round(float(proxy_metadata["duration_seconds"]), 3),
                "source_width": int(source_metadata["width"]),
                "source_height": int(source_metadata["height"]),
                "proxy_width": int(proxy_metadata["width"]),
                "proxy_height": int(proxy_metadata["height"]),
                "source_fps": round(source_fps, 3),
                "proxy_fps": round(float(proxy_metadata["fps"]), 3),
                "source_bitrate_bps": round(float(source_metadata.get("bit_rate_bps") or 0.0)),
                "proxy_bitrate_bps": round(float(proxy_metadata.get("bit_rate_bps") or 0.0)),
                "elapsed_seconds": round(time.perf_counter() - started, 3),
                "audio_policy": "transcode_when_present_no_downmix",
                "attempts": attempts,
            }

    return {
        "status": "failed",
        "error_type": "quality_budget_conflict",
        "attempts": attempts,
        "audio_policy": "transcode_when_present_no_downmix",
    }
