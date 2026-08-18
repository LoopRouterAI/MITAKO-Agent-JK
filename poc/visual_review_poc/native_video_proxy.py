# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Any, Dict, Iterable

if os.name == "nt":
    import msvcrt
else:
    import fcntl

import cv2

from review_media_safety import valid_media_file
from review_service.resource_guard import TRANSCODE_GATE, recommended_concurrency

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


def _video_metadata(path: Path) -> Dict[str, Any]:
    ffprobe_exe = _ffprobe_executable()
    if ffprobe_exe:
        try:
            completed = subprocess.run(
                [
                    ffprobe_exe,
                    "-v", "error",
                    "-select_streams", "v:0",
                    "-show_entries",
                    "stream=codec_name,width,height,avg_frame_rate,r_frame_rate,nb_frames,duration,bit_rate:format=duration,bit_rate,size",
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
                "codec_name": str(stream.get("codec_name") or "").lower(),
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
            "-c:v", "libx265", "-preset", "faster", "-crf", "21",
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
            "-c:v", "libvpx-vp9", "-deadline", "good", "-cpu-used", "4",
            "-row-mt", "1", "-crf", "24", "-b:v", "5500k",
            "-maxrate", "5500k", "-bufsize", "11M", "-pix_fmt", "yuv420p",
        ],
        "audio_args": ["-c:a", "libopus", "-b:a", "128k"],
        "container_args": [],
    },
}


def _transcode_concurrency() -> int:
    try:
        return recommended_concurrency(max(1, min(int(os.getenv("REVIEW_VIDEO_TRANSCODE_CONCURRENCY", "2")), 8)))
    except ValueError:
        return 2


# 保留可替换名称供既有测试和诊断使用；实际槽位由共享资源守门统一管理。
_TRANSCODE_SLOTS = TRANSCODE_GATE
_PROXY_CACHE_VERSION = 1


@contextmanager
def _cache_entry_lock(entry: Path, timeout_seconds: int):
    """同一缓存键跨线程、跨进程只允许一次转码。"""
    entry.parent.mkdir(parents=True, exist_ok=True)
    lock_path = entry.parent / f".{entry.name}.lock"
    deadline = time.monotonic() + max(1, int(timeout_seconds))
    with lock_path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        acquired = False
        while not acquired and time.monotonic() < deadline:
            handle.seek(0)
            try:
                if os.name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError:
                time.sleep(0.05)
        try:
            yield acquired
        finally:
            if acquired:
                handle.seek(0)
                if os.name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def video_proxy_recommendation(
    source: Path,
    *,
    max_long_edge: int = 2560,
    max_fps: float = 24.0,
    max_bitrate_bps: float = 6_000_000.0,
    max_source_bytes: int = 100 * 1024 * 1024,
    policy: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """只在原片明显超出审核上传质量预算时建议生成质量代理。"""
    if isinstance(policy, dict):
        max_long_edge = int(policy.get("video_max_long_edge") or max_long_edge)
        max_fps = float(policy.get("video_max_fps") or max_fps)
        max_bitrate_bps = float(policy.get("video_max_bitrate_mbps") or (max_bitrate_bps / 1_000_000)) * 1_000_000
        max_source_bytes = int(policy.get("video_max_source_mb") or (max_source_bytes / (1024 * 1024))) * 1024 * 1024
    metadata = _video_metadata(source)
    recommendation = video_proxy_recommendation_from_metadata(
        {
            **metadata,
            "source_bytes": source.stat().st_size if source.is_file() else 0,
        },
        max_long_edge=max_long_edge,
        max_fps=max_fps,
        max_bitrate_bps=max_bitrate_bps,
        max_source_bytes=max_source_bytes,
        policy=policy,
    )
    return {**recommendation, "source_metadata": metadata}


def video_proxy_recommendation_from_metadata(
    metadata: Dict[str, Any],
    *,
    max_long_edge: int = 2560,
    max_fps: float = 24.0,
    max_bitrate_bps: float = 6_000_000.0,
    max_source_bytes: int = 100 * 1024 * 1024,
    policy: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """用同一质量预算生成计划与执行决策。"""
    if isinstance(policy, dict):
        max_long_edge = int(policy.get("video_max_long_edge") or max_long_edge)
        max_fps = float(policy.get("video_max_fps") or max_fps)
        max_bitrate_bps = float(policy.get("video_max_bitrate_mbps") or (max_bitrate_bps / 1_000_000)) * 1_000_000
        max_source_bytes = int(policy.get("video_max_source_mb") or (max_source_bytes / (1024 * 1024))) * 1024 * 1024
    reasons = []
    observations = []
    fps_above_budget = float(metadata.get("fps") or 0) > max_fps
    if max(float(metadata.get("width") or 0), float(metadata.get("height") or 0)) > max_long_edge:
        reasons.append("resolution_above_2k")
    if float(metadata.get("bit_rate_bps") or 0) > max_bitrate_bps:
        reasons.append("bitrate_above_6mbps")
    if int(metadata.get("source_bytes") or 0) >= max_source_bytes:
        codec = str(metadata.get("codec_name") or "").lower()
        if reasons or codec not in {"vp9", "hevc", "h265", "av1"}:
            reasons.append("source_above_100mb")
        else:
            observations.append("source_above_100mb_already_efficient")
    if fps_above_budget:
        if reasons:
            reasons.insert(0, "fps_above_24")
        else:
            observations.append("fps_above_24_without_size_quality_pressure")
    return {
        "recommended": bool(reasons),
        "reasons": reasons,
        "observations": observations,
        "max_long_edge": int(max_long_edge),
        "max_fps": float(max_fps),
        "max_bitrate_bps": float(max_bitrate_bps),
        "max_source_bytes": int(max_source_bytes),
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
    codec_profile: str = "vp9_webm",
    target_video_bitrate_bps: int = 5_500_000,
) -> list[str]:
    profile = PROXY_CODEC_PROFILES[codec_profile]
    bitrate_kbps = max(1, int(target_video_bitrate_bps) // 1000)
    video_args = list(profile["video_args"])
    for flag, multiplier in (("-b:v", 1), ("-maxrate", 1), ("-bufsize", 2)):
        if flag in video_args:
            value = "11M" if flag == "-bufsize" and bitrate_kbps == 5500 else f"{bitrate_kbps * multiplier}k"
            video_args[video_args.index(flag) + 1] = value
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
        *video_args,
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


def _cached_proxy(entry: Path, source: Path, source_sha256: str) -> Dict[str, Any] | None:
    manifest = entry / "manifest.json"
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        if payload.get("version") != _PROXY_CACHE_VERSION:
            return None
        result = payload.get("result")
        if not isinstance(result, dict) or result.get("status") != "ready":
            return None
        proxy = Path(str(result.get("path") or "")).resolve()
        if not proxy.is_relative_to(entry.resolve()) or not proxy.is_file():
            return None
        if result.get("source_sha256") != source_sha256:
            return None
        if int(result.get("source_bytes") or -1) != source.stat().st_size:
            return None
        if int(result.get("proxy_bytes") or -1) != proxy.stat().st_size:
            return None
        if not valid_media_file(proxy) or result.get("proxy_sha256") != _sha256(proxy):
            return None
        return {**result, "cache_hit": True}
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _write_proxy_cache(entry: Path, result: Dict[str, Any]) -> None:
    manifest = entry / "manifest.json"
    temporary = entry / "manifest.json.tmp"
    temporary.write_text(
        json.dumps(
            {"version": _PROXY_CACHE_VERSION, "result": result},
            ensure_ascii=False,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    temporary.replace(manifest)


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
    source_long_edge = max(source_width, source_height)
    source_short_edge = min(source_width, source_height)
    proxy_long_edge = max(proxy_width, proxy_height)
    proxy_short_edge = min(proxy_width, proxy_height)
    if proxy_long_edge > source_long_edge or proxy_short_edge > source_short_edge:
        return False
    if proxy_long_edge > max_long_edge:
        return False
    required_short_edge = min(source_short_edge, 1080)
    if proxy_short_edge < required_short_edge:
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


def _prepare_native_video_proxy(
    source: Path,
    output_dir: Path,
    max_bytes: int,
    timeout_seconds: int = 1800,
    profiles: Iterable[str] = ("vp9_webm",),
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
    duration_seconds = float(source_metadata.get("duration_seconds") or 0.0)
    total_bitrate_budget = int((max_bytes * 8 / duration_seconds) * 0.92)
    target_video_bitrate_bps = max(
        2_000_000,
        min(5_500_000, total_bitrate_budget - 128_000),
    )
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
                        target_video_bitrate_bps=target_video_bitrate_bps,
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
                "target_video_bitrate_bps": target_video_bitrate_bps,
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


def prepare_native_video_proxy(
    source: Path,
    output_dir: Path,
    max_bytes: int,
    timeout_seconds: int = 1800,
    profiles: Iterable[str] = ("vp9_webm",),
    cache_dir: Path | None = None,
) -> Dict[str, Any]:
    selected_profiles = tuple(profiles)
    cache_entry: Path | None = None
    source_sha256 = ""
    if cache_dir is not None:
        source_sha256 = _sha256(source)
        cache_key = hashlib.sha256(
            json.dumps(
                {
                    "version": _PROXY_CACHE_VERSION,
                    "source_sha256": source_sha256,
                    "max_bytes": int(max_bytes),
                    "profiles": selected_profiles,
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        cache_entry = Path(cache_dir).resolve() / cache_key
        cached = _cached_proxy(cache_entry, source, source_sha256)
        if cached:
            return {**cached, "transcode_queue_seconds": 0.0}

    queue_started = time.perf_counter()
    lock_context = (
        _cache_entry_lock(cache_entry, timeout_seconds)
        if cache_entry is not None
        else nullcontext(True)
    )
    with lock_context as cache_lock_acquired:
        queue_seconds = round(time.perf_counter() - queue_started, 3)
        if not cache_lock_acquired:
            return {
                "status": "failed",
                "error_type": "transcode_cache_lock_timeout",
                "transcode_queue_seconds": queue_seconds,
                "audio_policy": "transcode_when_present_no_downmix",
            }
        if cache_entry is not None:
            cached = _cached_proxy(cache_entry, source, source_sha256)
            if cached:
                return {**cached, "transcode_queue_seconds": queue_seconds}

        acquired = _TRANSCODE_SLOTS.acquire(timeout=max(30, min(int(timeout_seconds), 1800)))
        queue_seconds = round(time.perf_counter() - queue_started, 3)
        if not acquired:
            return {
                "status": "failed",
                "error_type": "transcode_queue_timeout",
                "transcode_queue_seconds": queue_seconds,
                "audio_policy": "transcode_when_present_no_downmix",
            }
        try:
            result = _prepare_native_video_proxy(
                source,
                cache_entry if cache_entry is not None else output_dir,
                max_bytes,
                timeout_seconds=timeout_seconds,
                profiles=selected_profiles,
            )
            result = {
                **result,
                "source_sha256": source_sha256 or result.get("source_sha256"),
                "cache_hit": False,
                "transcode_queue_seconds": queue_seconds,
            }
            if cache_entry is not None and result.get("status") == "ready":
                _write_proxy_cache(cache_entry, result)
            return result
        finally:
            _TRANSCODE_SLOTS.release()
