# -*- coding: utf-8 -*-
"""基于媒体容器和流元数据的非 AI 取证检查。"""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set


DEFAULT_CHECKS = {
    "container_integrity",
    "timeline_consistency",
    "stream_consistency",
    "frame_rate_consistency",
    "packet_timeline",
    "editor_metadata",
}
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
SAFE_TAG_KEYS = {
    "creation_time",
    "encoder",
    "major_brand",
    "compatible_brands",
    "handler_name",
    "software",
}
EDITOR_MARKERS = {
    "adobe premiere": "Adobe Premiere",
    "final cut": "Final Cut",
    "davinci": "DaVinci Resolve",
    "resolve": "DaVinci Resolve",
    "capcut": "CapCut",
    "剪映": "剪映",
}
TRANSCODER_MARKERS = {
    "lavf": "FFmpeg/Lavf",
    "ffmpeg": "FFmpeg",
    "handbrake": "HandBrake",
}
RISK_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3}


def _number(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _fraction(value: Any) -> Optional[float]:
    text = str(value or "").strip()
    if not text or text in {"0/0", "N/A"}:
        return None
    if "/" not in text:
        return _number(text)
    numerator, denominator = text.split("/", 1)
    top = _number(numerator)
    bottom = _number(denominator)
    if top is None or bottom in {None, 0.0}:
        return None
    return top / bottom


def _round_number(value: Optional[float], digits: int = 6) -> Optional[float]:
    return None if value is None else round(value, digits)


def _safe_tags(tags: Any) -> Dict[str, str]:
    if not isinstance(tags, dict):
        return {}
    output: Dict[str, str] = {}
    for raw_key, raw_value in tags.items():
        key = str(raw_key).strip().lower()
        if key in SAFE_TAG_KEYS and raw_value not in {None, ""}:
            output[key] = str(raw_value)[:240]
    return output


def _selected_checks(checks: Optional[Sequence[str]]) -> Set[str]:
    if checks is True:
        return set(DEFAULT_CHECKS)
    if checks is False:
        return set()
    if checks is None:
        return set(DEFAULT_CHECKS)
    return {str(item) for item in checks if str(item) in DEFAULT_CHECKS}


def _risk(
    code: str,
    severity: str,
    description: str,
    evidence: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "description": description,
        "evidence": evidence,
        "is_proof_of_editing": False,
    }


def _duration_mismatch(left: Optional[float], right: Optional[float]) -> bool:
    if left is None or right is None:
        return False
    return abs(left - right) > max(0.5, max(left, right) * 0.02)


def _stream_facts(stream: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "index": stream.get("index"),
        "type": str(stream.get("codec_type") or "unknown"),
        "codec": str(stream.get("codec_name") or "unknown"),
        "duration_seconds": _round_number(_number(stream.get("duration")), 3),
        "start_time_seconds": _round_number(_number(stream.get("start_time")), 3),
        "average_fps": _round_number(_fraction(stream.get("avg_frame_rate")), 6),
        "declared_fps": _round_number(_fraction(stream.get("r_frame_rate")), 6),
        "time_base": str(stream.get("time_base") or ""),
        "frame_count": int(stream["nb_frames"]) if str(stream.get("nb_frames") or "").isdigit() else None,
        "width": stream.get("width"),
        "height": stream.get("height"),
        "tags": _safe_tags(stream.get("tags")),
    }


def _derive_risks(
    format_data: Dict[str, Any],
    streams: List[Dict[str, Any]],
    checks: Set[str],
    packet_timeline: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    risks: List[Dict[str, Any]] = []
    format_duration = _number(format_data.get("duration"))
    video_streams = [item for item in streams if item.get("codec_type") == "video"]
    audio_streams = [item for item in streams if item.get("codec_type") == "audio"]
    video_durations = [_number(item.get("duration")) for item in video_streams]
    audio_durations = [_number(item.get("duration")) for item in audio_streams]
    video_duration = next((item for item in video_durations if item is not None), None)
    audio_duration = next((item for item in audio_durations if item is not None), None)

    if "container_integrity" in checks and not video_streams:
        risks.append(
            _risk(
                "video_stream_missing",
                "medium",
                "容器中未发现可解析的视频流，需要核对素材完整性或编码兼容性。",
                {"video_streams": 0, "audio_streams": len(audio_streams)},
            )
        )

    if "timeline_consistency" in checks:
        if _duration_mismatch(format_duration, video_duration):
            risks.append(
                _risk(
                    "container_video_duration_mismatch",
                    "medium",
                    "容器时长与视频流时长存在明显差异，建议复核时间轴；该差异不能单独证明剪辑。",
                    {
                        "container_duration_seconds": _round_number(format_duration, 3),
                        "video_duration_seconds": _round_number(video_duration, 3),
                    },
                )
            )
        start_times = [_number(item.get("start_time")) for item in streams]
        non_zero = [item for item in start_times if item is not None and abs(item) > 0.25]
        if non_zero:
            risks.append(
                _risk(
                    "non_zero_stream_start",
                    "low",
                    "检测到非零流起始时间，可能来自封装、转码或时间轴偏移，建议结合原文件复核。",
                    {"start_time_seconds": [_round_number(item, 3) for item in non_zero]},
                )
            )

    if "stream_consistency" in checks and _duration_mismatch(video_duration, audio_duration):
        risks.append(
            _risk(
                "audio_video_duration_mismatch",
                "medium",
                "音频流与视频流时长存在明显差异，建议检查是否为录制、封装或后处理造成。",
                {
                    "video_duration_seconds": _round_number(video_duration, 3),
                    "audio_duration_seconds": _round_number(audio_duration, 3),
                },
            )
        )

    if "frame_rate_consistency" in checks:
        for stream in video_streams:
            average_fps = _fraction(stream.get("avg_frame_rate"))
            declared_fps = _fraction(stream.get("r_frame_rate"))
            if (
                average_fps is not None
                and declared_fps is not None
                and abs(average_fps - declared_fps) > max(0.5, declared_fps * 0.03)
            ):
                risks.append(
                    _risk(
                        "frame_rate_variation",
                        "low",
                        "平均帧率与声明帧率存在差异，可能为可变帧率录制或转码结果，不等同于剪辑。",
                        {
                            "stream_index": stream.get("index"),
                            "average_fps": _round_number(average_fps, 6),
                            "declared_fps": _round_number(declared_fps, 6),
                        },
                    )
                )

    if "packet_timeline" in checks and packet_timeline:
        if packet_timeline.get("non_monotonic_count"):
            risks.append(
                _risk(
                    "packet_timestamp_regression",
                    "medium",
                    "视频包解码时间戳出现回退，可能来自异常封装、拼接或损坏，需结合原文件和画面复核。",
                    {
                        "non_monotonic_count": packet_timeline["non_monotonic_count"],
                        "coverage_seconds": packet_timeline.get("coverage_seconds"),
                    },
                )
            )
        if packet_timeline.get("large_gap_count"):
            risks.append(
                _risk(
                    "packet_timeline_gap",
                    "medium",
                    "视频包时间轴出现异常大间隔，可能来自暂停录制、拼接、封装或损坏，不能单独证明剪辑。",
                    {
                        "large_gap_count": packet_timeline["large_gap_count"],
                        "largest_gap_seconds": packet_timeline.get("largest_gap_seconds"),
                        "gap_threshold_seconds": packet_timeline.get("gap_threshold_seconds"),
                    },
                )
            )

    if "editor_metadata" in checks:
        tagged_sources: List[Dict[str, Any]] = [{"scope": "container", "tags": _safe_tags(format_data.get("tags"))}]
        tagged_sources.extend(
            {"scope": f"stream:{item.get('index')}", "tags": _safe_tags(item.get("tags"))}
            for item in streams
        )
        for source in tagged_sources:
            joined = " ".join(source["tags"].values()).lower()
            editors = sorted({name for marker, name in EDITOR_MARKERS.items() if marker in joined})
            transcoders = sorted({name for marker, name in TRANSCODER_MARKERS.items() if marker in joined})
            if editors:
                risks.append(
                    _risk(
                        "editor_metadata_present",
                        "medium",
                        "元数据包含常见编辑软件标记，说明文件可能经过软件处理，但不能据此认定内容被剪辑。",
                        {"scope": source["scope"], "software": editors},
                    )
                )
            elif transcoders:
                risks.append(
                    _risk(
                        "transcoder_metadata_present",
                        "low",
                        "元数据包含转码工具标记，说明文件可能经过重新封装或转码，但不能据此认定内容被剪辑。",
                        {"scope": source["scope"], "software": transcoders},
                    )
                )
    return risks


def _probe_file(ffprobe: str, path: Path, timeout_seconds: int) -> Dict[str, Any]:
    command = [
        ffprobe,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        "-show_packets",
        "-show_entries",
        "packet=stream_index,pts_time,dts_time,duration_time,flags",
        "-read_intervals",
        "%+#20000",
        str(path),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"status": "unavailable", "reason": "ffprobe_execution_failed"}
    if completed.returncode != 0:
        return {"status": "unavailable", "reason": "ffprobe_could_not_parse_media"}
    try:
        payload = json.loads(completed.stdout.decode("utf-8", errors="replace"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"status": "unavailable", "reason": "ffprobe_invalid_output"}
    if not isinstance(payload, dict):
        return {"status": "unavailable", "reason": "ffprobe_invalid_output"}
    return {"status": "completed", "payload": payload}


def _packet_timeline_facts(
    packets: Any,
    packet_limit: int = 20000,
    stream_index: Optional[int] = None,
) -> Dict[str, Any]:
    all_rows = [item for item in (packets or []) if isinstance(item, dict)]
    rows = [
        item
        for item in all_rows
        if stream_index is None or str(item.get("stream_index")) == str(stream_index)
    ]
    timestamps: List[float] = []
    keyframes = 0
    missing = 0
    for item in rows:
        timestamp = _number(item.get("dts_time"))
        if timestamp is None:
            timestamp = _number(item.get("pts_time"))
        if timestamp is None:
            missing += 1
            continue
        timestamps.append(timestamp)
        if "K" in str(item.get("flags") or ""):
            keyframes += 1

    deltas = [right - left for left, right in zip(timestamps, timestamps[1:])]
    positive = sorted(delta for delta in deltas if delta > 0)
    baseline_delta = positive[int((len(positive) - 1) * 0.25)] if positive else None
    median_delta = None
    if positive:
        middle = len(positive) // 2
        median_delta = (
            positive[middle]
            if len(positive) % 2
            else (positive[middle - 1] + positive[middle]) / 2
        )
    gap_threshold = max(1.0, (baseline_delta or 0.04) * 20)
    large_gaps = [delta for delta in deltas if delta > gap_threshold]
    non_monotonic = [delta for delta in deltas if delta < -0.01]
    coverage = timestamps[-1] - timestamps[0] if len(timestamps) > 1 else 0.0
    return {
        "packets_analyzed": len(rows),
        "timestamped_packets": len(timestamps),
        "missing_timestamp_packets": missing,
        "keyframes": keyframes,
        "coverage_seconds": _round_number(max(0.0, coverage), 3),
        "baseline_packet_delta_seconds": _round_number(baseline_delta, 6),
        "minimum_packet_delta_seconds": _round_number(positive[0], 6) if positive else None,
        "median_packet_delta_seconds": _round_number(median_delta, 6),
        "maximum_packet_delta_seconds": _round_number(positive[-1], 6) if positive else None,
        "gap_threshold_seconds": _round_number(gap_threshold, 3),
        "large_gap_count": len(large_gaps),
        "largest_gap_seconds": _round_number(max(large_gaps), 3) if large_gaps else None,
        "non_monotonic_count": len(non_monotonic),
        "truncated_at_packet_limit": len(all_rows) >= packet_limit,
    }


def _playback_speed_assessment(
    format_data: Optional[Dict[str, Any]] = None,
    video_stream: Optional[Dict[str, Any]] = None,
    packet_timeline: Optional[Dict[str, Any]] = None,
    *,
    reason_code: str = "source_clock_reference_unavailable",
) -> Dict[str, Any]:
    format_data = format_data or {}
    video_stream = video_stream or {}
    packet_timeline = packet_timeline or {}
    reasons = {
        "source_clock_reference_unavailable": (
            "重编码视频的 PTS、帧率和容器时长只描述编码后的播放时间轴；"
            "缺少拍摄现场时钟或原始素材基准，不能可靠反推恒定加速倍数。"
        ),
        "ffprobe_not_available": "ffprobe 不可用，未获得编码时间轴；恒定加速倍数无法判断。",
        "media_file_missing": "媒体文件不可用，未获得编码时间轴；恒定加速倍数无法判断。",
        "ffprobe_execution_failed": "ffprobe 执行失败，未获得编码时间轴；恒定加速倍数无法判断。",
        "ffprobe_could_not_parse_media": "ffprobe 无法解析媒体，恒定加速倍数无法判断。",
        "ffprobe_invalid_output": "ffprobe 输出无效，恒定加速倍数无法判断。",
        "forensic_checks_disabled": "媒体取证已关闭，恒定加速倍数未判断。",
    }
    encoded_timeline = {
        "container_duration_seconds": _round_number(_number(format_data.get("duration")), 3),
        "video_stream_duration_seconds": _round_number(_number(video_stream.get("duration")), 3),
        "average_fps": _round_number(_fraction(video_stream.get("avg_frame_rate")), 6),
        "declared_fps": _round_number(_fraction(video_stream.get("r_frame_rate")), 6),
        "frame_count": (
            int(video_stream["nb_frames"])
            if str(video_stream.get("nb_frames") or "").isdigit()
            else None
        ),
        "packet_coverage_seconds": packet_timeline.get("coverage_seconds"),
        "packet_delta_minimum_seconds": packet_timeline.get("minimum_packet_delta_seconds"),
        "packet_delta_median_seconds": packet_timeline.get("median_packet_delta_seconds"),
        "packet_delta_maximum_seconds": packet_timeline.get("maximum_packet_delta_seconds"),
    }
    return {
        "status": "unknown",
        "constant_speed_multiplier": None,
        "reason_code": reason_code,
        "reason": reasons.get(reason_code, "编码时间轴不可用，恒定加速倍数无法判断。"),
        "method": "ffprobe_encoded_timeline_only",
        "is_model_inference": False,
        "encoded_timeline": encoded_timeline,
    }


def resolve_ffprobe() -> str:
    """优先使用部署配置的固定路径，再回退到服务进程 PATH。"""
    configured = os.getenv("REVIEW_FFPROBE_PATH", "").strip()
    if configured:
        path = Path(configured).expanduser()
        if path.is_file():
            return str(path.resolve())
    return shutil.which("ffprobe") or ""


def forensics_timeout_seconds() -> int:
    try:
        timeout = int(os.getenv("REVIEW_FFPROBE_TIMEOUT_SECONDS", "20") or 20)
    except ValueError:
        timeout = 20
    return max(3, min(timeout, 120))


def is_video_asset(asset: Dict[str, Any]) -> bool:
    return (
        str(asset.get("mime_type") or "").lower().startswith("video/")
        or Path(str(asset.get("original_name") or "")).suffix.lower() in VIDEO_SUFFIXES
    )


def inspect_job_media(
    job_dir: Path,
    assets: Iterable[Dict[str, Any]],
    checks: Optional[Sequence[str]] = None,
    timeout_seconds: Optional[int] = None,
) -> Dict[str, Any]:
    """检查任务中的视频文件，输出可公开的事实和风险提示。"""
    selected = _selected_checks(checks)
    video_assets = [
        item
        for item in assets
        if is_video_asset(item)
    ]
    base = {
        "status": "not_applicable",
        "checks": sorted(selected),
        "assets": [],
        "summary": {
            "video_assets": len(video_assets),
            "analyzed_assets": 0,
            "unavailable_assets": 0,
            "risk_signal_count": 0,
            "risk_level": "none",
        },
        "interpretation": "媒体取证信号只用于提示复核方向，不能单独证明视频被剪辑、替换或篡改。",
    }
    if not video_assets:
        return base
    if not selected:
        base["status"] = "disabled"
        base["assets"] = [
            {
                "asset_id": str(item.get("asset_id") or ""),
                "file": str(item.get("original_name") or ""),
                "status": "disabled",
                "playback_speed_assessment": _playback_speed_assessment(
                    reason_code="forensic_checks_disabled"
                ),
            }
            for item in video_assets
        ]
        return base

    ffprobe = resolve_ffprobe()
    if not ffprobe:
        base["status"] = "unavailable"
        base["summary"]["unavailable_assets"] = len(video_assets)
        base["unavailable_reason"] = "ffprobe_not_available"
        base["assets"] = [
            {
                "asset_id": str(item.get("asset_id") or ""),
                "file": str(item.get("original_name") or ""),
                "status": "unavailable",
                "reason": "ffprobe_not_available",
                "playback_speed_assessment": _playback_speed_assessment(
                    reason_code="ffprobe_not_available"
                ),
            }
            for item in video_assets
        ]
        return base

    timeout = forensics_timeout_seconds() if timeout_seconds is None else max(3, min(int(timeout_seconds), 120))
    highest_risk = "none"
    total_risks = 0
    unavailable = 0
    analyzed = 0
    results: List[Dict[str, Any]] = []
    for asset in video_assets:
        public_asset = {
            "asset_id": str(asset.get("asset_id") or ""),
            "file": str(asset.get("original_name") or ""),
        }
        path = job_dir / str(asset.get("stored_name") or "")
        if not path.is_file():
            public_asset.update({
                "status": "unavailable",
                "reason": "media_file_missing",
                "playback_speed_assessment": _playback_speed_assessment(
                    reason_code="media_file_missing"
                ),
            })
            unavailable += 1
            results.append(public_asset)
            continue
        probed = _probe_file(ffprobe, path, timeout)
        if probed["status"] != "completed":
            public_asset.update({
                "status": "unavailable",
                "reason": probed["reason"],
                "playback_speed_assessment": _playback_speed_assessment(
                    reason_code=str(probed["reason"])
                ),
            })
            unavailable += 1
            results.append(public_asset)
            continue

        payload = probed["payload"]
        format_data = payload.get("format") if isinstance(payload.get("format"), dict) else {}
        streams = [item for item in payload.get("streams") or [] if isinstance(item, dict)]
        first_video_index = next(
            (item.get("index") for item in streams if item.get("codec_type") == "video"),
            None,
        )
        first_video_stream = next(
            (item for item in streams if item.get("codec_type") == "video"),
            {},
        )
        packet_timeline = (
            _packet_timeline_facts(payload.get("packets"), stream_index=first_video_index)
            if "packet_timeline" in selected
            else None
        )
        risks = _derive_risks(format_data, streams, selected, packet_timeline)
        asset_risk = max(
            (str(item.get("severity") or "none") for item in risks),
            key=lambda item: RISK_ORDER.get(item, 0),
            default="none",
        )
        highest_risk = max((highest_risk, asset_risk), key=lambda item: RISK_ORDER.get(item, 0))
        total_risks += len(risks)
        analyzed += 1
        public_asset.update(
            {
                "status": "completed",
                "container": {
                    "format": str(format_data.get("format_name") or "unknown"),
                    "duration_seconds": _round_number(_number(format_data.get("duration")), 3),
                    "start_time_seconds": _round_number(_number(format_data.get("start_time")), 3),
                    "bit_rate": int(format_data["bit_rate"]) if str(format_data.get("bit_rate") or "").isdigit() else None,
                    "tags": _safe_tags(format_data.get("tags")),
                },
                "streams": [_stream_facts(item) for item in streams],
                "packet_timeline": packet_timeline,
                "playback_speed_assessment": _playback_speed_assessment(
                    format_data,
                    first_video_stream,
                    packet_timeline,
                ),
                "risk_level": asset_risk,
                "risk_signals": risks,
            }
        )
        results.append(public_asset)

    base["assets"] = results
    base["summary"].update(
        {
            "analyzed_assets": analyzed,
            "unavailable_assets": unavailable,
            "risk_signal_count": total_risks,
            "risk_level": highest_risk,
        }
    )
    if analyzed and unavailable:
        base["status"] = "partial"
    elif analyzed:
        base["status"] = "completed"
    else:
        base["status"] = "unavailable"
    return base
