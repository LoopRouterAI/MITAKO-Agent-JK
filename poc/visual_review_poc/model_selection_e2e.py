# -*- coding: utf-8 -*-
"""三大审核场景模型选型 E2E：同一证据包，多模型对比。"""
from __future__ import annotations

import argparse
import base64
import copy
import json
import logging
import math
import mimetypes
import os
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.utils import parsedate_to_datetime
from pathlib import Path
from threading import BoundedSemaphore
from typing import Any, Dict, List, Optional
from urllib.parse import unquote, urlparse

import cv2
import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from poc.visual_review_poc.local_video_triage_demo import (
    DEFAULT_POLICY,
    POC_DIR,
    REPORT_DIR,
    TMP_DIR,
    build_system_prompt,
    enforce_boundary,
    evaluate,
    extract_usage,
    format_time,
    h,
    json_block,
    load_case,
    load_case_from_folder,
    load_env,
    load_report_label,
    parse_model_json,
    policy_decision,
    resize_frame,
    sample_video_frames,
    _safe_confidence,
)
from poc.visual_review_poc.damage_causality import (
    aggregate_damage_causality,
    apply_damage_causality_guard,
    normalize_supplemental_linkage,
)
from poc.visual_review_poc.object_continuity import (
    aggregate_object_continuity,
    apply_object_continuity_guard,
)
from configs.model_catalog import (
    MODEL_CONFIGS,
    PRICING_NOTE,
    summarize_cost_observability as _cost_observability,
)
from prompts.visual_review.scenes import resolve_response_schema
from prompts.visual_review.response_validation import (
    ModelResponseValidationError,
    provider_response_schema,
    validate_model_response,
)
from poc.visual_review_poc.review_model_prompt import (
    build_claim_identity_prompt,
    build_claimed_item_detail_prompt,
    build_fulfillment_observation_prompt,
    build_opening_compliance_prompt,
    build_opening_start_prompt,
    build_product_damage_image_prompt,
    build_selection_prompt,
)
from prompts.visual_review.review_model_prompt import build_opening_video_role_prompt
from poc.visual_review_poc.model_result_scoring import score_result
from poc.visual_review_poc.fulfillment_reconciliation import (
    aggregate_fulfillment_reconciliation,
    apply_fulfillment_guard,
)
from poc.visual_review_poc.specialized_model_pass import run_adaptive_tasks, run_specialized_frame_pass
from review_service.resource_guard import recommended_concurrency
from poc.visual_review_poc.sampled_video_perception import run_sampled_video_perception
from poc.visual_review_poc.native_video_perception import normalize_minor_damage_evidence
from poc.visual_review_poc.minor_material_pipeline import run_minor_material_pipeline
from poc.visual_review_poc.media_deduplication import deduplicate_media
from poc.visual_review_poc.media_preflight import (
    compress_image,
    prepare_image_media as prepare_media,
)
from poc.visual_review_poc.unified_model_pass import (
    claimed_item_evidence_times,
    claimed_item_identity_window_is_traceable,
    unified_dimension_gaps,
)
from runtime_paths import app_root
from review_media_safety import ignored_upload_reason, valid_media_file
from poc.visual_review_poc.official_reference_images import prepare_official_reference_images
from poc.visual_review_poc.model_auth import gemini_channel_options
from poc.visual_review_poc.observability import log_visual_event, sanitize_error_text
from prompts.visual_review.core import (
    CLAIM_IDENTITY_SYSTEM_PROMPT,
    CLAIMED_ITEM_DETAIL_SYSTEM_PROMPT,
    OPENING_COMPLIANCE_SYSTEM_PROMPT,
    OPENING_START_SYSTEM_PROMPT,
    OPENING_VIDEO_ROLE_SYSTEM_PROMPT,
    build_fulfillment_observation_system_prompt,
    build_native_video_perception_system_prompt,
    build_product_damage_image_system_prompt,
    freeze_rule_snapshot,
)

ROOT = app_root()
SAMPLE_ROOT = ROOT / "docs" / "三大审核场景的小量样本"
CNY_PER_USD = 7.0
LOGGER = logging.getLogger("mitako.visual_review")
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
try:
    PROVIDER_MAX_INFLIGHT = max(1, min(int(os.getenv("REVIEW_PROVIDER_MAX_INFLIGHT", "4") or 4), 32))
except ValueError:
    PROVIDER_MAX_INFLIGHT = 4
_PROVIDER_REQUEST_GATE = BoundedSemaphore(PROVIDER_MAX_INFLIGHT)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="三大审核场景模型选型 E2E")
    parser.add_argument("--samples-dir", default=str(SAMPLE_ROOT), help="样本目录")
    parser.add_argument("--models", default="gemini35lite,gemini37", help="逗号分隔模型 key")
    parser.add_argument("--fps", type=float, default=1.0)
    parser.add_argument("--sampling-mode", choices=["adaptive", "dense"], default="adaptive")
    parser.add_argument("--max-frames-per-video", type=int, default=24)
    parser.add_argument("--api-frame-limit", type=int, default=24)
    parser.add_argument("--probe-seconds", type=float, default=0.0)
    parser.add_argument("--frame-width", type=int, default=960)
    parser.add_argument("--supplemental-image-limit", type=int, default=20)
    parser.add_argument("--request-timeout", type=int, default=300)
    parser.add_argument("--soft-retries", type=int, default=2)
    parser.add_argument("--concurrency", type=int, default=4)
    return parser.parse_args()


def mime_for(path: Path) -> str:
    if path.suffix.lower() == ".webp":
        return "image/webp"
    return mimetypes.guess_type(str(path))[0] or "image/jpeg"


def data_url(path: Path, mime_type: str) -> str:
    return f"data:{mime_type};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def extract_video_start_anchors(video: Path, run_dir: Path, frame_width: int) -> List[Dict[str, Any]]:
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        return []
    run_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    try:
        for timestamp_seconds in (0.0, 1.0):
            cap.set(cv2.CAP_PROP_POS_MSEC, timestamp_seconds * 1000)
            ok, frame = cap.read()
            if not ok:
                continue
            frame = resize_frame(frame, frame_width)
            path = run_dir / f"opening_anchor_{int(timestamp_seconds):02d}s.jpg"
            encoded_ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 84])
            if not encoded_ok:
                continue
            encoded.tofile(str(path))
            frames.append({
                "frame_index": len(frames) + 1,
                "timestamp": format_time(timestamp_seconds),
                "timestamp_seconds": timestamp_seconds,
                "file": path.name,
                "path": str(path),
            })
    finally:
        cap.release()
    return frames


def discover_case_videos(sample_dir: Path) -> Tuple[List[Path], Dict[str, Any]]:
    submitted_videos = sorted(
        path
        for path in sample_dir.iterdir()
        if path.is_file()
        and path.suffix.lower() in VIDEO_SUFFIXES
        and not ignored_upload_reason(path.name)
        and valid_media_file(path)
    )
    return deduplicate_media(submitted_videos)


def load_case_bundle(
    sample_dir: Path,
    args: argparse.Namespace,
    run_dir: Path,
    scenario_override: str = "",
    native_video: Optional[Dict[str, Any]] = None,
    native_videos: Optional[List[Dict[str, Any]]] = None,
    selected_videos: Optional[List[Path]] = None,
) -> Dict[str, Any]:
    videos, video_deduplication = discover_case_videos(sample_dir)
    if selected_videos is not None:
        discovered = {video.resolve(): video for video in videos}
        videos = [
            discovered[Path(item).resolve()]
            for item in selected_videos
            if Path(item).resolve() in discovered
        ]
    case = load_case(videos[0], args.supplemental_image_limit) if videos else load_case_from_folder(sample_dir, args.supplemental_image_limit)
    if scenario_override:
        case["scenario"] = scenario_override
    if not videos and not case.get("supplemental_images"):
        raise SystemExit(f"样本缺少可审核的视频或图片：{sample_dir}")
    native_sources = [dict(item) for item in native_videos or [] if isinstance(item, dict)]
    if not native_sources and native_video:
        native_sources = [dict(native_video)]
    if native_sources:
        if len(native_sources) != len(videos):
            raise SystemExit("原生视频源数量与本次送审视频数量不一致")
        media_dir = run_dir / "api_media"
        anchors: List[Dict[str, Any]] = []
        video_summaries: List[Dict[str, Any]] = []
        for video_index, (video, source) in enumerate(zip(videos, native_sources), start=1):
            source.setdefault("api_path", str(video))
            source.setdefault("api_mime_type", mime_for(video))
            source["video_index"] = video_index
            video_anchors = extract_video_start_anchors(
                video,
                run_dir / f"native_start_anchors_{video_index}",
                args.frame_width,
            )
            for frame in video_anchors:
                frame["selection_role"] = "opening_anchor"
                frame["video_index"] = video_index
                frame["video_file"] = video.name
                anchors.append(frame)
            video_summaries.append({
                "video_index": video_index,
                "file": video.name,
                "source_bytes": video.stat().st_size,
                "duration_seconds": source.get("duration_seconds"),
                "sampled_frames": len(video_anchors),
                "model_input": {"type": "native_video"},
            })
        for index, frame in enumerate(anchors, start=1):
            frame["global_frame_index"] = index
        detail_quality = case.get("scenario") == "product_damage"
        case["frames"] = prepare_media(
            anchors,
            media_dir / "native_detail_frames",
            max_edge=1920,
            quality=88 if detail_quality else 82,
            lossless_webp=True,
        )
        case["videos"] = video_summaries
        case["video_deduplication"] = video_deduplication
        case["rejected_videos"] = []
        case["model_frames_per_call"] = len(case["frames"])
        case["sampling_mode"] = "native_video"
        image_execution: List[Dict[str, Any]] = []
        case["supplemental_images"] = prepare_media(
            case["supplemental_images"],
            media_dir / "images",
            diagnostics=image_execution,
        )
        case["_media_preflight_image_execution"] = image_execution
        prepare_official_reference_images(case)
        case["native_video"] = native_sources[0]
        case["native_videos"] = native_sources
        transports = {
            "file_uri" if source.get("file_uri") else "inline_data"
            for source in native_sources
        }
        case.setdefault("structured_business_context", {})["native_video_review"] = {
            "enabled": True,
            "transport": transports.pop() if len(transports) == 1 else "mixed",
            "video_count": len(native_sources),
        }
        return case
    frame_groups: List[List[Dict[str, Any]]] = []
    video_summaries = []
    rejected_videos: List[Dict[str, str]] = []
    for video_index, video in enumerate(videos, start=1):
        window_metadata: Dict[str, Any] = {}
        window_sidecar = video.with_suffix(video.suffix + ".window.json")
        if window_sidecar.exists():
            try:
                window_metadata = json.loads(window_sidecar.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                window_metadata = {}
        source_offset = float(window_metadata.get("source_start_seconds") or 0.0)
        try:
            sample = sample_video_frames(
                video,
                args.fps,
                args.max_frames_per_video,
                args.probe_seconds,
                args.frame_width,
                run_dir / f"video_{video_index}",
                args.sampling_mode,
            )
        except (OSError, RuntimeError, SystemExit, ValueError):
            rejected_videos.append({"file": video.name, "reason": "视频无法解码，已从本次审核中隔离"})
            continue
        picked = sample["frames"]
        video_summaries.append({
            "video_index": video_index,
            "file": video.name,
            "source_start_seconds": source_offset,
            "source_end_seconds": window_metadata.get("source_end_seconds"),
            **{k: v for k, v in sample.items() if k != "frames"},
        })
        group: List[Dict[str, Any]] = []
        for frame in picked:
            copied = dict(frame)
            copied["video_index"] = video_index
            copied["video_file"] = video.name
            copied["source_timestamp_seconds"] = round(float(copied.get("timestamp_seconds") or 0) + source_offset, 3)
            copied["source_timestamp"] = format_time(copied["source_timestamp_seconds"])
            group.append(copied)
        frame_groups.append(group)
    case["videos"] = video_summaries
    case["video_deduplication"] = video_deduplication
    case["rejected_videos"] = rejected_videos
    if video_summaries:
        first_accepted = sample_dir / str(video_summaries[0]["file"])
        case["video_file"] = first_accepted.name
        case["video_path"] = str(first_accepted)
    if not video_summaries and not case.get("supplemental_images"):
        raise SystemExit(f"样本内的视频均无法读取，且没有可审核图片：{sample_dir}")
    case["frames"] = [dict(frame) for group in frame_groups for frame in group]
    for index, frame in enumerate(case["frames"], start=1):
        frame["global_frame_index"] = index
    case["model_frames_per_call"] = max(1, min(int(args.api_frame_limit), 24))
    case["sampling_mode"] = args.sampling_mode
    media_dir = run_dir / "api_media"
    product_damage = case.get("scenario") == "product_damage"
    case["frames"] = prepare_media(
        case["frames"],
        media_dir / "frames",
        max_edge=1920,
        quality=88 if product_damage else 82,
        lossless_webp=True,
    )
    image_execution: List[Dict[str, Any]] = []
    case["supplemental_images"] = prepare_media(
        case["supplemental_images"],
        media_dir / "images",
        diagnostics=image_execution,
    )
    case["_media_preflight_image_execution"] = image_execution
    prepare_official_reference_images(case)
    return case


def gemini_payload(
    system_prompt: str,
    user_prompt: str,
    case: Dict[str, Any],
    cfg: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    parts: List[Dict[str, Any]] = []
    native_videos = [
        item for item in case.get("native_videos") or []
        if isinstance(item, dict) and (item.get("file_uri") or item.get("api_path"))
    ]
    if not native_videos and case.get("native_video"):
        native_videos = [case["native_video"]]
    for native_video in native_videos:
        video_index = native_video.get("video_index") or 1
        mime_type = native_video.get("api_mime_type") or "video/mp4"
        if native_video.get("file_uri"):
            video_part: Dict[str, Any] = {"fileData": {
                "mimeType": mime_type,
                "fileUri": str(native_video["file_uri"]),
            }}
        else:
            path = Path(native_video["api_path"])
            video_part = {"inlineData": {
                "mimeType": mime_type,
                "data": base64.b64encode(path.read_bytes()).decode("ascii"),
            }}
        configured_sampling_fps = (cfg or {}).get("native_video_sampling_fps")
        try:
            sampling_fps = float(
                native_video.get("sampling_fps")
                if native_video.get("sampling_fps") is not None
                else configured_sampling_fps
            )
        except (TypeError, ValueError, OverflowError):
            sampling_fps = 0.0
        if 0.1 <= sampling_fps <= 24.0:
            video_part["videoMetadata"] = {"fps": sampling_fps}
        parts.append({"text": f"原生视频 {video_index} / asset_ref=native_video_{video_index}"})
        parts.append(video_part)
    for frame in case["frames"]:
        path = Path(frame["api_path"])
        parts.append({"text": f"视频{frame['video_index']} 帧{frame['global_frame_index']} / {frame['timestamp']} / asset_ref=video_{frame['video_index']}_frame_{frame['global_frame_index']}"})
        parts.append({"inlineData": {"mimeType": frame["api_mime_type"], "data": base64.b64encode(path.read_bytes()).decode("ascii")}})
    for image in case["supplemental_images"]:
        path = Path(image["api_path"])
        parts.append({"text": f"补充图片 {image['image_index']} / asset_ref=supplemental_image_{image['image_index']}"})
        parts.append({"inlineData": {"mimeType": image["api_mime_type"], "data": base64.b64encode(path.read_bytes()).decode("ascii")}})
    for image in case.get("official_reference_images") or []:
        path = Path(image["api_path"])
        parts.append({"text": f"官方商品参考图 {image['reference_index']} / 商品名={image.get('product_name') or '未提供'} / SKU={image.get('sku') or '未提供'} / asset_ref=official_product_reference_{image['reference_index']}。仅用于核对订单商品标准外观，不能作为用户开箱证据。"})
        parts.append({"inlineData": {"mimeType": image["api_mime_type"], "data": base64.b64encode(path.read_bytes()).decode("ascii")}})
    parts.append({"text": user_prompt})
    analysis_mode = str((case.get("structured_business_context") or {}).get("analysis_mode") or "")
    business_scenario = str(
        (case.get("structured_business_context") or {}).get("business_scenario")
        or case.get("scenario")
        or ""
    )
    if (
        not analysis_mode
        and business_scenario == "product_damage"
        and not native_videos
        and case.get("frames")
    ):
        analysis_mode = "sampled_video_perception"
    if (
        not analysis_mode
        and business_scenario == "product_damage"
        and not native_videos
        and not case.get("frames")
        and case.get("supplemental_images")
    ):
        analysis_mode = "product_damage_images"
    response_schema = resolve_response_schema(
        business_scenario,
        analysis_mode,
        bool(native_videos),
    )
    generation_config: Dict[str, Any] = {
        "responseMimeType": "application/json",
        "responseSchema": provider_response_schema(response_schema),
    }
    configured_max_output = (cfg or {}).get("max_output_tokens")
    if configured_max_output is not None:
        try:
            generation_config["maxOutputTokens"] = max(
                256,
                min(65536, int(configured_max_output)),
            )
        except (TypeError, ValueError, OverflowError):
            pass
    thinking_level = str((cfg or {}).get("thinking_level") or "").strip().upper()
    if thinking_level in {"MINIMAL", "LOW", "MEDIUM", "HIGH"}:
        generation_config["thinkingConfig"] = {"thinkingLevel": thinking_level}
    media_resolution = str((cfg or {}).get("media_resolution") or "").strip().upper()
    if media_resolution in {"LOW", "MEDIUM", "HIGH"}:
        generation_config["mediaResolution"] = f"MEDIA_RESOLUTION_{media_resolution}"
    return {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"parts": parts}],
        "generationConfig": generation_config,
    }


def model_request_profile(cfg: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    """从实际请求体生成内部验收摘要，不保存 Prompt、媒体或凭据。"""
    generation = payload.get("generationConfig") or {}
    thinking = (generation.get("thinkingConfig") or {}).get("thinkingLevel")
    media_resolution = str(generation.get("mediaResolution") or "")
    video_parts = [
        part
        for content in payload.get("contents") or []
        for part in content.get("parts") or []
        if isinstance(part, dict)
        and ("inlineData" in part or "fileData" in part)
        and str(
            (part.get("inlineData") or part.get("fileData") or {}).get("mimeType") or ""
        ).startswith("video/")
    ]
    fps_values = [
        float((part.get("videoMetadata") or {})["fps"])
        for part in video_parts
        if (part.get("videoMetadata") or {}).get("fps") is not None
    ]
    transports = {
        "file_uri" if "fileData" in part else "inline_data"
        for part in video_parts
    }
    return {
        "provider": str(cfg.get("provider") or ""),
        "model": str(cfg.get("model") or ""),
        "thinking_level": str(thinking or "provider_default").lower(),
        "media_resolution": (
            media_resolution.removeprefix("MEDIA_RESOLUTION_").lower()
            or "provider_default"
        ),
        "max_output_tokens": generation.get("maxOutputTokens", "provider_default"),
        "native_video_count": len(video_parts),
        "sampling_fps": fps_values[0] if fps_values and len(set(fps_values)) == 1 else None,
        "transport": (
            next(iter(transports))
            if len(transports) == 1
            else "mixed" if transports else "none"
        ),
    }


def openai_messages(system_prompt: str, user_prompt: str, case: Dict[str, Any]) -> List[Dict[str, Any]]:
    content: List[Dict[str, Any]] = [{"type": "text", "text": user_prompt}]
    for frame in case["frames"]:
        path = Path(frame["api_path"])
        content.append({"type": "text", "text": f"视频{frame['video_index']} 帧{frame['global_frame_index']} / {frame['timestamp']} / asset_ref=video_{frame['video_index']}_frame_{frame['global_frame_index']}"})
        content.append({"type": "image_url", "image_url": {"url": data_url(path, frame["api_mime_type"])}})
    for image in case["supplemental_images"]:
        path = Path(image["api_path"])
        content.append({"type": "text", "text": f"补充图片 {image['image_index']} / asset_ref=supplemental_image_{image['image_index']}"})
        content.append({"type": "image_url", "image_url": {"url": data_url(path, image["api_mime_type"])}})
    for image in case.get("official_reference_images") or []:
        path = Path(image["api_path"])
        content.append({"type": "text", "text": f"官方商品参考图 {image['reference_index']} / 商品名={image.get('product_name') or '未提供'} / SKU={image.get('sku') or '未提供'} / asset_ref=official_product_reference_{image['reference_index']}。仅用于核对订单商品标准外观，不能作为用户开箱证据。"})
        content.append({"type": "image_url", "image_url": {"url": data_url(path, image["api_mime_type"])}})
    return [{"role": "system", "content": system_prompt}, {"role": "user", "content": content}]


def classify_error(status: Optional[int], text: str) -> str:
    lowered = (text or "").lower()
    if status == 400 and "upload to gcs failed" in lowered and "internal_error" in lowered:
        return "soft"
    if status in {408, 409, 425, 429, 500, 502, 503, 504}:
        return "soft"
    return "soft" if any(t in lowered for t in ("timeout", "rate limit", "overloaded", "temporarily")) else "hard"


def is_retryable_failure(result: Dict[str, Any]) -> bool:
    return result.get("error_type") == "soft" or result.get("status_code") in {
        408, 409, 425, 429, 500, 502, 503, 504
    }


def collect_channel_route_attempts(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        dict(attempt)
        for row in rows
        for attempt in row.get("_channel_route_attempts") or []
        if isinstance(attempt, dict)
    ]


def _retry_delay(retry_after: Any, attempt: int) -> float:
    text = str(retry_after or "").strip()
    if text:
        try:
            return min(max(float(text), 0.0), 30.0)
        except ValueError:
            try:
                return min(max(parsedate_to_datetime(text).timestamp() - time.time(), 0.0), 30.0)
            except (TypeError, ValueError, OverflowError):
                pass
    return min(2 ** (attempt - 1), 8) + random.uniform(0.1, 0.4)


def estimate_model_cost(cfg: Dict[str, Any], usage: Dict[str, Any]) -> Dict[str, Any]:
    input_tokens = int(usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    tiers = cfg.get("pricing_tiers") or []
    tier = next((item for item in tiers if input_tokens <= int(item["max_input_tokens"])), None)
    input_price = float((tier or cfg).get("input_price", 0))
    output_price = float((tier or cfg).get("output_price", 0))
    amount = input_tokens / 1_000_000 * input_price + output_tokens / 1_000_000 * output_price
    usd = amount if cfg["currency"] == "USD" else amount / CNY_PER_USD
    return {
        "amount": round(amount, 6),
        "currency": cfg["currency"],
        "estimated_usd": round(usd, 6),
        "input_price_per_1m": input_price,
        "output_price_per_1m": output_price,
        "pricing_tier": tier,
        "fx_cny_per_usd": CNY_PER_USD,
        "source": cfg["source"],
        "note": "按供应商 usage 中计入的输入、输出 tokens 与当前配置单价估算；不同媒体模态的最终账单以供应商为准。",
    }


def post_with_retries(
    endpoint: str,
    headers: Dict[str, str],
    payload: Dict[str, Any],
    timeout: int,
    retries: int,
    deadline_at: Optional[float] = None,
) -> Dict[str, Any]:
    last: Dict[str, Any] = {}
    request_attempts: List[Dict[str, Any]] = []
    for attempt in range(1, retries + 2):
        remaining = deadline_at - time.monotonic() if deadline_at is not None else None
        if remaining is not None and remaining <= 0:
            log_visual_event(
                LOGGER,
                "visual_model_http_failure",
                endpoint=endpoint,
                attempt=attempt,
                max_attempts=retries + 1,
                timeout_seconds=timeout,
                error_type="deadline",
                will_retry=False,
            )
            return {
                "ok": False,
                "status_code": None,
                "latency_seconds": 0,
                "error": "case_deadline_exceeded",
                "error_type": "deadline",
                "attempt": attempt - 1,
                "request_attempts": request_attempts,
            }
        started = time.time()
        log_visual_event(
            LOGGER,
            "visual_model_http_attempt",
            endpoint=endpoint,
            attempt=attempt,
            max_attempts=retries + 1,
            timeout_seconds=timeout,
        )
        acquired = False
        try:
            if remaining is None:
                _PROVIDER_REQUEST_GATE.acquire()
                acquired = True
            else:
                acquired = _PROVIDER_REQUEST_GATE.acquire(timeout=max(0.0, remaining))
                if not acquired:
                    log_visual_event(
                        LOGGER,
                        "visual_model_http_failure",
                        endpoint=endpoint,
                        attempt=attempt,
                        max_attempts=retries + 1,
                        timeout_seconds=timeout,
                        error_type="deadline",
                        will_retry=False,
                    )
                    return {
                        "ok": False,
                        "status_code": None,
                        "latency_seconds": round(time.time() - started, 2),
                        "error": "case_deadline_exceeded",
                        "error_type": "deadline",
                        "attempt": attempt - 1,
                        "request_attempts": request_attempts,
                    }
                remaining = deadline_at - time.monotonic()
                if remaining <= 0:
                    log_visual_event(
                        LOGGER,
                        "visual_model_http_failure",
                        endpoint=endpoint,
                        attempt=attempt,
                        max_attempts=retries + 1,
                        timeout_seconds=timeout,
                        error_type="deadline",
                        will_retry=False,
                    )
                    return {
                        "ok": False,
                        "status_code": None,
                        "latency_seconds": round(time.time() - started, 2),
                        "error": "case_deadline_exceeded",
                        "error_type": "deadline",
                        "attempt": attempt - 1,
                        "request_attempts": request_attempts,
                    }
            effective_timeout = min(float(timeout), max(0.1, remaining)) if remaining is not None else float(timeout)
            request_timeout = httpx.Timeout(effective_timeout, connect=min(10.0, effective_timeout))
            with httpx.Client(timeout=request_timeout) as client:
                response = client.post(endpoint, headers=headers, json=payload)
            latency = round(time.time() - started, 2)
            if response.status_code < 400:
                request_attempts.append({
                    "attempt": attempt,
                    "outcome": "success",
                    "status_code": response.status_code,
                    "latency_seconds": latency,
                    "request_sent": True,
                })
                log_visual_event(
                    LOGGER,
                    "visual_model_http_success",
                    endpoint=endpoint,
                    attempt=attempt,
                    max_attempts=retries + 1,
                    status_code=response.status_code,
                    latency_seconds=latency,
                )
                return {
                    "ok": True,
                    "status_code": response.status_code,
                    "latency_seconds": latency,
                    "data": response.json(),
                    "attempt": attempt,
                    "request_attempts": request_attempts,
                }
            last = {"ok": False, "status_code": response.status_code, "latency_seconds": latency, "error": sanitize_error_text(response.text), "error_type": classify_error(response.status_code, response.text), "attempt": attempt, "retry_after": response.headers.get("Retry-After")}
        except Exception as exc:
            last = {"ok": False, "status_code": None, "latency_seconds": round(time.time() - started, 2), "error": sanitize_error_text(exc), "error_type": classify_error(None, str(exc)), "attempt": attempt}
        finally:
            if acquired:
                _PROVIDER_REQUEST_GATE.release()
        request_attempts.append({
            "attempt": attempt,
            "outcome": "failed",
            "status_code": last.get("status_code"),
            "latency_seconds": last.get("latency_seconds"),
            "error_type": last.get("error_type"),
            "request_sent": True,
        })
        log_visual_event(
            LOGGER,
            "visual_model_http_failure",
            endpoint=endpoint,
            attempt=attempt,
            max_attempts=retries + 1,
            status_code=last.get("status_code"),
            latency_seconds=last.get("latency_seconds"),
            error_type=last.get("error_type"),
            will_retry=bool(last.get("error_type") == "soft" and attempt <= retries),
        )
        if last["error_type"] != "soft" or attempt > retries:
            return {**last, "request_attempts": request_attempts}
        delay = _retry_delay(last.get("retry_after"), attempt)
        if deadline_at is not None and deadline_at - time.monotonic() <= delay:
            return {
                **last,
                "error": "case_deadline_exceeded",
                "error_type": "deadline",
                "request_attempts": request_attempts,
            }
        time.sleep(delay)
    return {**last, "request_attempts": request_attempts}


def gemini_request_options(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    return gemini_channel_options(cfg["model"])


def extract_openai_text(data: Dict[str, Any]) -> str:
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict):
                texts.append(str(item.get("text") or item.get("content") or item.get("output_text") or ""))
        return "\n".join(t for t in texts if t).strip()
    return str(message.get("reasoning_content") or "").strip()


def compact_response(data: Dict[str, Any]) -> Dict[str, Any]:
    """保留模型响应里用于复盘的内容，避免把整包重复图像或无关字段塞进报告。"""
    response_id = data.get("id") or data.get("responseId")
    output = {
        "id": response_id,
        "response_id": data.get("responseId") or response_id,
        "task_id": data.get("taskId"),
        "model": data.get("model") or data.get("modelVersion"),
        "usage": data.get("usage") or data.get("usageMetadata"),
    }
    if data.get("choices") is not None:
        output["choices"] = data.get("choices")
    if data.get("candidates") is not None:
        output["candidates"] = data.get("candidates")
    if data.get("promptFeedback") is not None:
        output["promptFeedback"] = data.get("promptFeedback")
    return output


def derive_native_video_overall_result(parsed: Dict[str, Any]) -> Dict[str, Any]:
    """把模型感知事实归一为甲方九标签，综合结论不交给模型自由发挥。"""
    normalized = normalize_minor_damage_evidence(copy.deepcopy(parsed))
    damage = dict(normalized.get("damage_assessment") or {})
    if (
        damage.get("main_video_detail_sufficient") is False
        and damage.get("visible_in_continuous_opening") is False
    ):
        damage["visible_in_continuous_opening"] = None
        damage["detail_review_signal"] = "yellow"
    normalized["damage_assessment"] = damage
    if isinstance(damage.get("visible_in_continuous_opening"), bool):
        normalized["issue_visible"] = damage["visible_in_continuous_opening"]
    elif damage.get("main_video_detail_sufficient") is False:
        normalized["issue_visible"] = None

    claimed_item = dict(normalized.get("claimed_item_assessment") or {})
    claimed_item_times = claimed_item_evidence_times(normalized)
    if claimed_item.get("appeared") is True and len(claimed_item_times) >= 2:
        claimed_item["first_visible_timestamp"] = format_time(min(claimed_item_times))
        claimed_item["last_visible_timestamp"] = format_time(max(claimed_item_times))
        normalized["claimed_item_assessment"] = claimed_item
    elif not claimed_item_identity_window_is_traceable(normalized):
        claimed_item["presentation_complete"] = None
        claimed_item["offscreen_during_presentation"] = None
        normalized["claimed_item_assessment"] = claimed_item
        normalized["all_items_shown"] = None
        normalized["has_offscreen"] = None
    if isinstance(claimed_item.get("offscreen_during_presentation"), bool):
        normalized["has_offscreen"] = claimed_item["offscreen_during_presentation"]

    speed = dict(normalized.get("speed_assessment") or {})
    speed_downgraded_to_unknown = False
    reliable_normal_bases = {"observable_realtime_anchor"}
    if speed.get("value") == "normal" and speed.get("evidence_basis") not in reliable_normal_bases:
        speed_downgraded_to_unknown = True
        first_visible = _time_seconds(claimed_item.get("first_visible_timestamp"))
        last_visible = _time_seconds(claimed_item.get("last_visible_timestamp"))
        brief_presentation = (
            first_visible is not None
            and last_visible is not None
            and 0 <= last_visible - first_visible <= 5.0
        )
        speed["value"] = "unknown"
        try:
            speed["confidence"] = min(float(speed.get("confidence") or 0.0), 0.5)
        except (TypeError, ValueError, OverflowError):
            speed["confidence"] = 0.0
        if brief_presentation or claimed_item.get("presentation_complete") is not True:
            speed["affects_visual_judgement"] = True
        speed["review_signal"] = "yellow"
        speed["reason"] = (
            "缺少可核验的原速基准；自然音频和动作节奏都不能证明视频未加速。"
            + ("争议商品展示很短，播放速度不确定会影响伤点判断。" if brief_presentation else "")
        )
    elif speed.get("value") == "accelerated":
        speed["review_signal"] = "orange"
    elif speed.get("value") == "unknown":
        speed["review_signal"] = "yellow"
    normalized["speed_assessment"] = speed
    if speed.get("value") == "accelerated":
        normalized["has_speed_change"] = True
    elif speed.get("value") == "normal":
        normalized["has_speed_change"] = False
    elif speed.get("value") == "unknown":
        normalized["has_speed_change"] = None

    if speed_downgraded_to_unknown:
        evidence_refs = []
        speed_ref_written = False
        for item in normalized.get("evidence_refs") or []:
            if not isinstance(item, dict) or item.get("field") != "has_speed_change":
                evidence_refs.append(item)
                continue
            if speed_ref_written:
                continue
            replacement = dict(item)
            replacement["fact"] = "无法确认是否变速；缺少可核验的原速基准。"
            evidence_refs.append(replacement)
            speed_ref_written = True
        normalized["evidence_refs"] = evidence_refs

    hard_required_values = {
        "sealed_start": True,
        "waybill_visible": True,
        "continuous": True,
        "has_edit": False,
        "has_offscreen": False,
        "all_items_shown": True,
    }
    hard_failed = any(
        isinstance(normalized.get(field), bool)
        and normalized[field] is not expected
        for field, expected in hard_required_values.items()
    )
    issue_visible = normalized.get("issue_visible")
    issue_failed = issue_visible is False and speed.get("affects_visual_judgement") is not True
    unknown = any(
        not isinstance(normalized.get(field), bool)
        for field in (*hard_required_values, "issue_visible")
    ) or (issue_visible is False and speed.get("affects_visual_judgement") is True)
    normalized["overall_video_result"] = (
        "noncompliant" if hard_failed or issue_failed
        else "indeterminate" if unknown or speed.get("affects_visual_judgement") is True
        else "compliant"
    )
    return normalized


def merge_claimed_item_detail_assessment(
    perception: Dict[str, Any],
    detail: Dict[str, Any],
) -> Dict[str, Any]:
    """局部高分辨率复核只覆盖商品身份与伤点可见性，不改写其他视频事实。"""
    merged = copy.deepcopy(perception)
    detail_copy = copy.deepcopy(detail)
    merged["claimed_item_detail_assessment"] = detail_copy
    damage = dict(merged.get("damage_assessment") or {})
    visibility = str(detail_copy.get("issue_visibility") or "uncertain")
    identity_match = str(detail_copy.get("identity_match") or "uncertain")
    if identity_match != "matched":
        damage["same_item_linkage"] = False if identity_match == "not_matched" else None
        damage["visible_in_continuous_opening"] = None
    elif visibility == "visible":
        damage["same_item_linkage"] = True
        damage["visible_in_continuous_opening"] = True
    elif visibility == "not_visible":
        damage["same_item_linkage"] = True
        if damage.get("visible_in_continuous_opening") is True:
            damage["visible_in_continuous_opening"] = None
            conflicts = list(merged.get("evidence_conflicts") or [])
            conflict = "完整视频与候选细节复核结论冲突"
            if conflict not in conflicts:
                conflicts.append(conflict)
            merged["evidence_conflicts"] = conflicts
        else:
            damage["visible_in_continuous_opening"] = False
    else:
        damage["same_item_linkage"] = True
        if damage.get("visible_in_continuous_opening") is not True:
            damage["visible_in_continuous_opening"] = None
    damage["detail_verification_reason"] = str(detail_copy.get("reason") or "")
    merged["damage_assessment"] = damage
    merged["issue_visible"] = damage.get("visible_in_continuous_opening")

    claimed_item = dict(merged.get("claimed_item_assessment") or {})
    detail_timestamps = [
        seconds
        for item in detail_copy.get("evidence_refs") or []
        if isinstance(item, dict)
        for seconds in [_time_seconds(item.get("timestamp"))]
        if seconds is not None
    ]
    coarse_start = _time_seconds(claimed_item.get("first_visible_timestamp"))
    coarse_end = _time_seconds(claimed_item.get("last_visible_timestamp"))
    detail_conflicts_with_coarse_window = bool(detail_timestamps) and (
        coarse_start is None
        or coarse_end is None
        or not any(
            coarse_start - 1.0 <= timestamp <= coarse_end + 1.0
            for timestamp in detail_timestamps
        )
    )
    if identity_match == "matched" and detail_conflicts_with_coarse_window:
        claimed_item.update({
            "appeared": True,
            "first_visible_timestamp": format_time(min(detail_timestamps)),
            "last_visible_timestamp": format_time(max(detail_timestamps)),
            "presentation_complete": None,
            "offscreen_during_presentation": None,
            "reason": str(detail_copy.get("reason") or "局部身份复核修正了候选时间窗。"),
        })
        merged["claimed_item_assessment"] = claimed_item
        merged["has_offscreen"] = None

    speed = dict(merged.get("speed_assessment") or {})
    if (
        speed.get("value") == "unknown"
        and detail_copy.get("presentation_quality") in {"partial", "insufficient"}
    ):
        speed["affects_visual_judgement"] = True
        speed["review_signal"] = "yellow"
    merged["speed_assessment"] = speed
    return derive_native_video_overall_result(merged)


def call_model(
    cfg: Dict[str, Any],
    case: Dict[str, Any],
    timeout: int,
    retries: int,
    deadline_at: Optional[float] = None,
) -> Dict[str, Any]:
    business_scenario = str(
        (case.get("structured_business_context") or {}).get("business_scenario")
        or case.get("scenario")
        or ""
    )
    analysis_mode = str((case.get("structured_business_context") or {}).get("analysis_mode") or "")
    if (
        not analysis_mode
        and business_scenario == "product_damage"
        and not (case.get("native_video") or case.get("native_videos"))
        and case.get("frames")
    ):
        analysis_mode = "sampled_video_perception"
    if (
        not analysis_mode
        and business_scenario == "product_damage"
        and not (case.get("native_video") or case.get("native_videos") or case.get("frames"))
        and case.get("supplemental_images")
    ):
        analysis_mode = "product_damage_images"
    if analysis_mode == "opening_video_role_preflight":
        system_prompt = OPENING_VIDEO_ROLE_SYSTEM_PROMPT
        user_prompt = build_opening_video_role_prompt(case)
    elif analysis_mode == "opening_start_only":
        system_prompt = OPENING_START_SYSTEM_PROMPT
        user_prompt = build_opening_start_prompt(case)
    elif analysis_mode == "opening_compliance_only":
        system_prompt = OPENING_COMPLIANCE_SYSTEM_PROMPT
        user_prompt = build_opening_compliance_prompt(case)
    elif analysis_mode == "claim_identity_only":
        system_prompt = CLAIM_IDENTITY_SYSTEM_PROMPT
        user_prompt = build_claim_identity_prompt(case)
    elif analysis_mode == "claimed_item_detail_only":
        system_prompt = CLAIMED_ITEM_DETAIL_SYSTEM_PROMPT
        user_prompt = build_claimed_item_detail_prompt(case)
    elif analysis_mode in {
        "native_video_perception",
        "sampled_video_perception",
        "sampled_video_batch_observation",
        "sampled_video_perception_reduce",
    }:
        freeze_rule_snapshot(case)
        system_prompt = build_native_video_perception_system_prompt(
            business_scenario or case["scenario"],
            tenant_id=str(case.get("_rule_tenant_id") or "mitako"),
            rule_snapshot=case.get("_business_rule_snapshot"),
            input_mode={
                "sampled_video_perception": "sampled_frames",
                "sampled_video_batch_observation": "sampled_batch",
                "sampled_video_perception_reduce": "sampled_summaries",
            }.get(analysis_mode, "native_video"),
        )
        user_prompt = build_selection_prompt(case)
    elif analysis_mode == "product_damage_images":
        system_prompt = build_product_damage_image_system_prompt()
        user_prompt = build_product_damage_image_prompt(case)
    elif not analysis_mode and business_scenario in {"wrong_item", "missing_item"}:
        system_prompt = build_fulfillment_observation_system_prompt(business_scenario)
        user_prompt = build_fulfillment_observation_prompt(case)
    else:
        freeze_rule_snapshot(case)
        system_prompt = build_system_prompt(
            business_scenario or case["scenario"],
            tenant_id=str(case.get("_rule_tenant_id") or "mitako"),
            rule_snapshot=case.get("_business_rule_snapshot"),
        )
        user_prompt = build_selection_prompt(case)
    failures: List[Dict[str, Any]] = []
    channel_attempts: List[Dict[str, Any]] = []
    http_attempts: List[Dict[str, Any]] = []
    if cfg["provider"] == "gemini_native":
        options = gemini_request_options(cfg)
        if not options:
            return {"status": "skipped", "error": "missing_api_key", "cost_status": "not_incurred"}
        payload = gemini_payload(system_prompt, user_prompt, case, cfg)
        request_profile = model_request_profile(cfg, payload)
        response: Dict[str, Any] = {}
        external_file_uri = bool((case.get("native_video") or {}).get("file_uri"))
        attempted_channel = False
        for option_index, option in enumerate(options):
            if external_file_uri and option.get("supports_external_file_uri") is not True:
                channel_attempts.append({
                    "channel": option.get("channel") or "configured",
                    "model": option.get("model") or cfg["model"],
                    "decision": "skipped_unsupported_file_uri",
                })
                continue
            attempted_channel = True
            response = post_with_retries(
                option["endpoint"], option["headers"], payload, timeout, retries, deadline_at
            )
            attempt_rows = response.get("request_attempts") or [{
                "attempt": response.get("attempt"),
                "outcome": "success" if response.get("ok") else "failed",
                "status_code": response.get("status_code"),
                "latency_seconds": response.get("latency_seconds"),
                "error_type": response.get("error_type"),
                "request_sent": True,
            }]
            http_attempts.extend({
                **{
                    key: item.get(key)
                    for key in (
                        "attempt", "outcome", "status_code", "latency_seconds",
                        "error_type", "request_sent",
                    )
                },
                "channel": option.get("channel") or "configured",
                "model": option.get("model") or cfg["model"],
            } for item in attempt_rows if isinstance(item, dict))
            if response.get("ok"):
                channel_attempts.append({
                    "channel": option.get("channel") or "configured",
                    "model": option.get("model") or cfg["model"],
                    "status_code": response.get("status_code"),
                    "decision": "selected",
                })
                break
            failures.append({key: response.get(key) for key in ("status_code", "latency_seconds", "error_type", "attempt")})
            retryable = is_retryable_failure(response)
            has_compatible_fallback = any(
                not external_file_uri or candidate.get("supports_external_file_uri") is True
                for candidate in options[option_index + 1:]
            )
            channel_attempts.append({
                "channel": option.get("channel") or "configured",
                "model": option.get("model") or cfg["model"],
                "status_code": response.get("status_code"),
                "error_type": response.get("error_type"),
                "decision": "fallback_retryable" if retryable and has_compatible_fallback else (
                    "exhausted" if retryable else "stop_non_retryable"
                ),
            })
            if not retryable:
                break
        if not attempted_channel:
            return {
                "status": "skipped",
                "error": "unsupported_external_file_uri_transport",
                "_channel_route_attempts": channel_attempts,
                "cost_status": "not_incurred",
            }
        if not response.get("ok"):
            return {
                "status": "failed",
                **response,
                "attempts": failures,
                "http_attempts": http_attempts,
                **_model_http_metrics(http_attempts),
                "_channel_route_attempts": channel_attempts,
                "cost_status": "unknown",
            }
        text = "\n".join(p.get("text", "") for p in (((response["data"].get("candidates") or [{}])[0].get("content") or {}).get("parts") or []) if isinstance(p, dict))
        usage = extract_usage(response["data"])
    else:
        key = os.getenv(cfg["key_env"])
        if not key:
            return {"status": "skipped", "error": f"missing_{cfg['key_env']}", "cost_status": "not_incurred"}
        payload = {
            "model": cfg["model"],
            "messages": openai_messages(system_prompt, user_prompt, case),
            "temperature": 0.1,
            "max_tokens": 4096,
            "response_format": {"type": "json_object"},
        }
        request_profile = {
            "provider": str(cfg.get("provider") or ""),
            "model": str(cfg.get("model") or ""),
            "thinking_level": "provider_default",
            "media_resolution": "provider_default",
            "max_output_tokens": payload.get("max_tokens", "provider_default"),
            "native_video_count": 0,
            "sampling_fps": None,
            "transport": "image_parts",
        }
        response = post_with_retries(
            cfg["endpoint"],
            {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            payload,
            timeout,
            retries,
            deadline_at,
        )
        attempt_rows = response.get("request_attempts") or [{
            "attempt": response.get("attempt"),
            "outcome": "success" if response.get("ok") else "failed",
            "status_code": response.get("status_code"),
            "latency_seconds": response.get("latency_seconds"),
            "error_type": response.get("error_type"),
            "request_sent": True,
        }]
        http_attempts.extend(
            {
                key: item.get(key)
                for key in (
                    "attempt", "outcome", "status_code", "latency_seconds",
                    "error_type", "request_sent",
                )
            }
            for item in attempt_rows
            if isinstance(item, dict)
        )
        if not response.get("ok"):
            return {
                "status": "failed",
                **response,
                "http_attempts": http_attempts,
                **_model_http_metrics(http_attempts),
                "cost_status": "unknown",
            }
        text = extract_openai_text(response["data"])
        raw_usage = response["data"].get("usage") or {}
        usage = {
            "input_tokens": raw_usage.get("prompt_tokens"),
            "output_tokens": raw_usage.get("completion_tokens"),
            "total_tokens": raw_usage.get("total_tokens"),
            "raw": raw_usage,
        }
    unknown_cost_calls = sum(
        1
        for item in http_attempts
        if item.get("outcome") == "failed" and item.get("request_sent") is True
    )
    cost_status = "partial_unknown" if unknown_cost_calls else "estimated"
    response_schema = resolve_response_schema(
        business_scenario or case["scenario"],
        analysis_mode,
        bool(case.get("native_video") or case.get("native_videos")),
    )
    try:
        parsed_before_boundary = validate_model_response(
            parse_model_json(text),
            response_schema,
        )
    except ModelResponseValidationError as exc:
        return {
            "status": "invalid_output",
            "error_type": "response_schema_validation",
            "error": str(exc),
            "model": cfg["model"],
            "display_model": cfg.get("display_model") or cfg["model"],
            "provider": cfg["provider"],
            "status_code": response.get("status_code"),
            "latency_seconds": response.get("latency_seconds"),
            "usage": usage,
            "cost": estimate_model_cost(cfg, usage),
            "cost_status": cost_status,
            "unknown_cost_calls": unknown_cost_calls,
            "estimated_cost_calls": 1,
            "request_profile": request_profile,
            "http_attempts": http_attempts,
            **_model_http_metrics(http_attempts),
            "raw_response": compact_response(response.get("data") or {}),
        }
    if analysis_mode in {
        "object_continuity_only", "damage_causality_only",
        "opening_start_only", "opening_compliance_only", "native_video_perception",
        "opening_video_role_preflight",
        "sampled_video_perception",
        "sampled_video_batch_observation", "sampled_video_perception_reduce",
        "claim_identity_only",
        "claimed_item_detail_only", "product_damage_images",
    }:
        if analysis_mode == "product_damage_images":
            from prompts.visual_review.product_damage_image_adapter import (
                expand_product_damage_image_observation,
            )
            parsed = expand_product_damage_image_observation(parsed_before_boundary, case)
        else:
            parsed = (
                derive_native_video_overall_result(parsed_before_boundary)
                if analysis_mode in {
                    "native_video_perception",
                    "sampled_video_perception",
                    "sampled_video_perception_reduce",
                }
                else parsed_before_boundary
            )
    else:
        if (business_scenario or case["scenario"]) in {"wrong_item", "missing_item"}:
            review_chunk = (case.get("structured_business_context") or {}).get("review_chunk")
            if not review_chunk:
                parsed_before_boundary["fulfillment_reconciliation"] = aggregate_fulfillment_reconciliation(
                    [parsed_before_boundary], case, business_scenario or case["scenario"]
                )
        parsed = apply_damage_causality_guard(
            enforce_boundary(parsed_before_boundary),
            business_scenario or case["scenario"],
            case.get("frames") or [],
        )
        parsed = apply_object_continuity_guard(
            parsed,
            business_scenario or case["scenario"],
            bool(case.get("videos") or case.get("frames")),
            (case.get("structured_business_context") or {}).get("continuity_policy"),
        )
        parsed = apply_fulfillment_guard(parsed, business_scenario or case["scenario"])
    label = load_report_label(case["case_id"])
    return {
        "status": "success",
        "model": cfg["model"],
        "display_model": cfg.get("display_model") or cfg["model"],
        "label": cfg["label"],
        "provider": cfg["provider"],
        "status_code": response.get("status_code"),
        "attempt": response.get("attempt"),
        "latency_seconds": response.get("latency_seconds"),
        "usage": usage,
        "cost": estimate_model_cost(cfg, usage),
        "cost_status": cost_status,
        "unknown_cost_calls": unknown_cost_calls,
        "estimated_cost_calls": 1,
        "request_profile": request_profile,
        "attempts": failures,
        "http_attempts": http_attempts,
        **_model_http_metrics(http_attempts),
        "_channel_route_attempts": channel_attempts if cfg["provider"] == "gemini_native" else [],
        "raw_text": text,
        "raw_response": compact_response(response.get("data") or {}),
        "parsed_before_boundary": parsed_before_boundary,
        "parsed": parsed,
        "evaluation": evaluate(parsed, label),
        "policy_decision": policy_decision(parsed),
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
    }


def opening_start_verification_case(case: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "case_id": case.get("case_id") or "opening-start-verification",
        "scenario": case.get("scenario") or "video_unboxing",
        "scenario_label": case.get("scenario_label") or "开箱视频审核",
        "customer_claim": "",
        "order_context": {},
        "videos": case.get("videos") or [],
        "frames": [copy.deepcopy(frame) for frame in (case.get("frames") or [])[:2]],
        "supplemental_images": [],
        "official_reference_images": [],
        "structured_business_context": {
            "business_scenario": case.get("scenario") or "video_unboxing",
            "analysis_mode": "opening_start_only",
        },
    }


def call_opening_start_verification(
    cfg: Dict[str, Any],
    case: Dict[str, Any],
    timeout: int,
    retries: int,
    deadline_at: Optional[float] = None,
) -> Dict[str, Any]:
    verification_case = opening_start_verification_case(case)
    if not verification_case["frames"]:
        return {"status": "skipped", "error": "missing_opening_start_anchors", "cost_status": "not_incurred"}
    return call_model(
        cfg,
        verification_case,
        timeout=timeout,
        retries=retries,
        deadline_at=deadline_at,
    )


def opening_compliance_verification_case(case: Dict[str, Any]) -> Dict[str, Any]:
    videos = sorted(
        [
            (
                _safe_int(video.get("video_index") or index),
                _safe_number(video.get("duration_seconds")),
            )
            for index, video in enumerate(case.get("videos") or [], start=1)
        ],
        key=lambda item: item[1],
        reverse=True,
    )
    primary_video_index = videos[0][0] if videos else 0
    if len(videos) > 1 and (videos[0][1] < 15 or videos[0][1] < videos[1][1] * 3):
        primary_video_index = 0
    primary_frames = [
        copy.deepcopy(frame)
        for frame in case.get("frames") or []
        if _safe_int(frame.get("video_index")) == primary_video_index
    ]
    return {
        "case_id": case.get("case_id") or "opening-compliance-verification",
        "scenario": case.get("scenario") or "video_unboxing",
        "scenario_label": case.get("scenario_label") or "开箱视频审核",
        "customer_claim": case.get("customer_claim") or "",
        "order_context": {},
        "videos": [
            copy.deepcopy(video)
            for video in case.get("videos") or []
            if _safe_int(video.get("video_index")) == primary_video_index
        ],
        "frames": _representative_frames(primary_frames, 24),
        "supplemental_images": [],
        "official_reference_images": [],
        "structured_business_context": {
            "business_scenario": case.get("scenario") or "video_unboxing",
            "analysis_mode": "opening_compliance_only",
        },
    }


def call_opening_compliance_verification(
    cfg: Dict[str, Any],
    case: Dict[str, Any],
    timeout: int,
    retries: int,
    deadline_at: Optional[float] = None,
) -> Dict[str, Any]:
    verification_case = opening_compliance_verification_case(case)
    if not verification_case["frames"]:
        return {
            "status": "skipped",
            "error": "primary_opening_video_unresolved",
            "cost_status": "not_incurred",
        }
    return call_model(
        cfg,
        verification_case,
        timeout=timeout,
        retries=retries,
        deadline_at=deadline_at,
    )


def merge_opening_compliance_verification(
    result: Dict[str, Any],
    verification_result: Dict[str, Any],
    anchors: Optional[List[Dict[str, Any]]] = None,
    scenario: str = "",
) -> Dict[str, Any]:
    output = merge_model_billing(result, [verification_result])
    output["opening_compliance_verification"] = {
        key: copy.deepcopy(verification_result.get(key))
        for key in (
            "status", "latency_seconds", "usage", "cost",
            "cost_status", "_channel_route_attempts",
        )
        if verification_result.get(key) is not None
    }
    verification = (
        verification_result.get("parsed")
        if verification_result.get("status") == "success"
        else None
    )
    if not isinstance(verification, dict):
        return output
    registry = {
        (
            _safe_int(frame.get("video_index")),
            _safe_int(frame.get("global_frame_index")),
        ): str(frame.get("timestamp") or "")
        for frame in anchors or []
    }
    field_names = (
        "sealed_start", "waybill_visible", "single_take_continuity",
        "issue_visible_in_continuous_opening",
    )
    refs_by_field: Dict[str, List[Dict[str, Any]]] = {
        field: [] for field in field_names
    }
    for reference in verification.get("evidence_refs") or []:
        if not isinstance(reference, dict) or reference.get("field") not in refs_by_field:
            continue
        key = (
            _safe_int(reference.get("video_index")),
            _safe_int(reference.get("global_frame_index")),
        )
        timestamp = registry.get(key)
        if not key[0] or not key[1] or not timestamp:
            continue
        refs_by_field[str(reference["field"])].append({
            "field": reference["field"],
            "video_index": key[0],
            "global_frame_index": key[1],
            "timestamp": timestamp,
        })
    verified_fields = {
        field
        for field in field_names
        if isinstance(verification.get(field), bool) and refs_by_field[field]
    }
    if not verified_fields:
        return output
    for parsed_key in ("parsed_before_boundary", "parsed"):
        parsed = output.get(parsed_key)
        if not isinstance(parsed, dict):
            continue
        opening = parsed.setdefault("video_audit_conclusion", {}).setdefault(
            "opening_video_compliance", {}
        )
        protected_fields = {
            "sealed_start"
        } if (
            (opening.get("field_sources") or {}).get("sealed_start") == "opening_start_verification"
            and "sealed_start" in (opening.get("validated_fields") or [])
        ) else set()
        fields_to_apply = verified_fields - protected_fields
        old_refs = opening.get("evidence_refs") or []
        if isinstance(old_refs, dict):
            old_refs = [
                {**item, "field": field}
                for field, items in old_refs.items()
                for item in items or []
                if isinstance(item, dict)
            ]
        opening["evidence_refs"] = [
            item
            for item in old_refs
            if isinstance(item, dict) and item.get("field") not in fields_to_apply
        ] + [
            reference
            for field in field_names
            if field in fields_to_apply
            for reference in refs_by_field[field]
        ]
        for field in fields_to_apply:
            opening[field] = verification[field]
        opening["field_sources"] = {
            **(opening.get("field_sources") or {}),
            **{
                field: "opening_compliance_verification"
                for field in fields_to_apply
            },
        }
        opening["validated_fields"] = sorted(
            set(opening.get("validated_fields") or []) | fields_to_apply
        )
        required_fields = field_names if scenario == "product_damage" else field_names[:3]
        values = [opening.get(field) for field in required_fields]
        opening["result"] = (
            "noncompliant"
            if False in values
            else "compliant"
            if all(value is True for value in values)
            else "indeterminate"
        )
        opening["source"] = "opening_compliance_verification"
    if isinstance(output.get("parsed"), dict):
        output["policy_decision"] = policy_decision(output["parsed"])
    return output


def merge_opening_start_verification(
    native_result: Dict[str, Any],
    verification_result: Dict[str, Any],
    anchors: Optional[List[Dict[str, Any]]] = None,
    scenario: str = "",
    include_billing: bool = True,
) -> Dict[str, Any]:
    output = (
        merge_model_billing(native_result, [verification_result])
        if include_billing
        else copy.deepcopy(native_result)
    )
    verification = verification_result.get("parsed") if verification_result.get("status") == "success" else None
    output["opening_start_verification"] = {
        key: copy.deepcopy(verification_result.get(key))
        for key in ("status", "latency_seconds", "usage", "cost", "cost_status", "_channel_route_attempts")
        if verification_result.get(key) is not None
    }
    if not isinstance(verification, dict):
        return output
    expected_value = {"sealed": True, "unsealed": False, "indeterminate": None}.get(verification.get("result"))
    if verification.get("sealed_start") is not expected_value or expected_value is None:
        return output
    registry = {
        (int(frame.get("video_index") or 0), int(frame.get("global_frame_index") or 0)): str(frame.get("timestamp") or "")
        for frame in anchors or []
    }
    refs = []
    for ref in verification.get("evidence_refs") or []:
        if not isinstance(ref, dict):
            continue
        try:
            key = (int(ref.get("video_index") or 0), int(ref.get("global_frame_index") or 0))
        except (TypeError, ValueError, OverflowError):
            continue
        trusted_timestamp = registry.get(key) if registry else str(ref.get("timestamp") or "")
        if not key[0] or not key[1] or not trusted_timestamp:
            continue
        refs.append({
            "field": "sealed_start",
            "video_index": key[0],
            "global_frame_index": key[1],
            "timestamp": trusted_timestamp,
        })
    if not refs:
        return output
    for parsed_key in ("parsed_before_boundary", "parsed"):
        parsed = output.get(parsed_key)
        if not isinstance(parsed, dict):
            continue
        video_audit = parsed.setdefault("video_audit_conclusion", {})
        opening = video_audit.setdefault("opening_video_compliance", {})
        old_refs = opening.get("evidence_refs") or []
        if isinstance(old_refs, dict):
            old_refs = [
                {**item, "field": field}
                for field, items in old_refs.items()
                for item in items or []
                if isinstance(item, dict)
            ]
        opening["evidence_refs"] = [
            item for item in old_refs
            if isinstance(item, dict) and item.get("field") != "sealed_start"
        ] + refs
        opening["sealed_start"] = expected_value
        opening["field_sources"] = {
            **(opening.get("field_sources") or {}),
            "sealed_start": "opening_start_verification",
        }
        opening["validated_fields"] = sorted(set(opening.get("validated_fields") or []) | {"sealed_start"})
        opening["source"] = "hybrid_native_video_with_opening_start_verification"
        opening["start_verification_reason"] = str(verification.get("reason") or "")
        hard_fields = ["sealed_start", "waybill_visible", "single_take_continuity"]
        if scenario == "product_damage":
            hard_fields.append("issue_visible_in_continuous_opening")
        hard_values = [opening.get(field) for field in hard_fields]
        opening["result"] = "noncompliant" if False in hard_values else "compliant" if all(value is True for value in hard_values) else "indeterminate"
        if parsed_key == "parsed" and scenario == "product_damage" and expected_value is False:
            confidence = _safe_confidence(parsed.get("confidence"), 0.9)
            conclusion = "开箱起始专项复核确认视频并非从完整未拆封快递外包装开始，当前开箱材料不合规。"
            parsed.update({
                "predicted_label": "negative",
                "system_yes_no": "NO",
                "decision": "fail",
                "confidence": confidence,
                "business_action_allowed": False,
                "human_required_for_business_action": True,
                "opening_start_guard_reason": conclusion,
                "overall_audit": {
                    "conclusion": conclusion,
                    "confidence": confidence,
                    "core_reason": f"{conclusion} 这是开箱资料合规结论，不等于商品无损。",
                    "business_follow_up_suggestion": "如需继续支持本次诉求，请补充符合开箱起始要求的证据；最终业务处理由甲方系统和授权人员决定。",
                },
            })
    if scenario == "product_damage" and isinstance(output.get("parsed"), dict):
        output["policy_decision"] = policy_decision(output["parsed"])
    return output


def _time_seconds(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    text = str(value).strip()
    match = re.search(r"(?:(\d+):)?(\d{1,2}):(\d{1,2}(?:\.\d+)?)", text)
    if match:
        return int(match.group(1) or 0) * 3600 + int(match.group(2)) * 60 + float(match.group(3))
    try:
        return float(text.rstrip("s秒"))
    except ValueError:
        return None


def _aggregate_damage_observability(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    values = [item.get("damage_observability") for item in rows if isinstance(item.get("damage_observability"), dict)]
    if not values:
        return {
            "status": "unknown",
            "same_item_linkage": False,
            "claimed_region_closeup": False,
            "required_view_coverage": 0.0,
            "conflicting_evidence": False,
            "missing_views": ["模型未返回结构化可观察性结果"],
        }
    statuses = {str(item.get("status") or "unknown") for item in values}
    conflicting = any(item.get("conflicting_evidence") is True for item in values)
    fully_observable = statuses == {"fully_observable"} and not conflicting
    return {
        "status": "fully_observable" if fully_observable else (
            "not_observable" if statuses == {"not_observable"} else "partial"
        ),
        "same_item_linkage": all(item.get("same_item_linkage") is True for item in values),
        "claimed_region_closeup": all(item.get("claimed_region_closeup") is True for item in values),
        "required_view_coverage": min(
            _safe_confidence(item.get("required_view_coverage")) for item in values
        ),
        "conflicting_evidence": conflicting,
        "missing_views": list(dict.fromkeys(
            str(view)
            for item in values
            for view in item.get("missing_views") or []
            if str(view).strip()
        ))[:40],
        "segment_assessments": values,
    }


def _damage_key_evidence(
    rows: List[Dict[str, Any]],
    valid_frame_keys: Optional[set[Tuple[int, int]]] = None,
    limit: int = 8,
) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    for row in rows:
        for item in row.get("frame_findings") or []:
            if not isinstance(item, dict):
                continue
            key = _frame_key(item)
            if key is None or (valid_frame_keys is not None and key not in valid_frame_keys):
                continue
            findings.append(dict(item))
    by_key = {_frame_key(item): item for item in findings}
    ordered = [by_key[key] for key in sorted(by_key)]
    priority = [
        item for item in ordered
        if str(item.get("damage_state") or "") in {"visible", "uncertain"}
        or str(item.get("action") or "none") != "none"
    ]
    selected = list({_frame_key(item): item for item in priority}.values())[:limit]
    return [
        {
            "source_type": "video_frame",
            "video_index": item.get("video_index"),
            "global_frame_index": item.get("global_frame_index"),
            "timestamp": item.get("timestamp"),
            "fact": item.get("visible_facts") or "该关键帧未形成可读描述。",
            "why_it_matters": item.get("why_it_matters") or "用于复核主视频是否支持本次损伤诉求。",
        }
        for item in selected
    ]


OPENING_STAGE_ORDER = (
    "sealed_package",
    "opening_in_progress",
    "item_exposed",
    "contents_displayed",
)


def _opening_integrity_from_continuity(
    findings: List[Dict[str, Any]],
    sampling_boundary_status: str,
) -> tuple[str, str]:
    stages = [str(item.get("opening_stage") or "unknown") for item in findings if isinstance(item, dict)]
    if not stages:
        return "indeterminate", "model_segment_consensus"
    if sampling_boundary_status != "covered" or "unknown" in stages:
        return "indeterminate", "full_timeline_continuity"
    positions = []
    for stage in OPENING_STAGE_ORDER:
        try:
            start = positions[-1] + 1 if positions else 0
            positions.append(stages.index(stage, start))
        except ValueError:
            return "indeterminate", "full_timeline_continuity"
    return "complete", "full_timeline_continuity"


def _apply_global_timeline_summary(
    case: Dict[str, Any],
    parsed: Dict[str, Any],
    parsed_rows: List[Dict[str, Any]],
    chunk_conclusions: List[str],
) -> Dict[str, Any]:
    """用全量帧注册表生成公开摘要，局部分段叙述只保留为内部审计。"""
    output = dict(parsed)
    frames = list(case.get("frames") or [])
    frame_registry = {
        _frame_key(item): str(item.get("timestamp") or "").strip()
        for item in frames
        if isinstance(item, dict) and _frame_key(item) is not None
    }

    def registered_reference(reference: Any) -> bool:
        if not isinstance(reference, dict):
            return False
        key = _frame_key(reference)
        return bool(
            key in frame_registry
            and str(reference.get("timestamp") or "").strip()
            and str(reference.get("timestamp") or "").strip() == frame_registry[key]
        )

    frame_times = [_time_seconds(item.get("timestamp")) for item in frames]
    valid_frame_times = [value for value in frame_times if value is not None]
    sampled_start = min(valid_frame_times) if valid_frame_times else None
    sampled_end = max(valid_frame_times) if valid_frame_times else None
    source_durations = [
        _safe_number(item.get("duration_seconds"))
        for item in case.get("videos") or []
        if _safe_number(item.get("duration_seconds")) > 0
    ]
    source_duration = max(source_durations) if source_durations else None
    timeline_coverage_ratio = (
        round(max(0.0, min(sampled_end / source_duration, 1.0)), 4)
        if sampled_end is not None and source_duration and source_duration > 0
        else None
    )
    timeline_tolerance = max(0.5, (source_duration or 0.0) * 0.01)
    sampling_boundary_status = (
        "covered"
        if sampled_start is not None
        and sampled_start <= timeline_tolerance
        and sampled_end is not None
        and source_duration is not None
        and sampled_end >= source_duration - timeline_tolerance
        else "incomplete" if sampled_end is not None and source_duration is not None else "unknown"
    )
    continuity = output.get("object_continuity_assessment") or {}
    claimed_subjects = [
        item for item in continuity.get("tracked_subjects") or []
        if isinstance(item, dict) and str(item.get("subject_id") or "") == "claimed_item"
    ]
    first_exposed_values = [
        (_time_seconds(item.get("first_exposed_timestamp")), str(item.get("first_exposed_timestamp") or ""))
        for item in claimed_subjects
    ]
    valid_first_exposed = [item for item in first_exposed_values if item[0] is not None]
    first_exposed = min(valid_first_exposed, key=lambda item: item[0])[1] if valid_first_exposed else ""

    contradictions: List[Dict[str, Any]] = []
    end_pattern = re.compile(r"(?:视频)?(?:在|于)?\s*((?:\d+:)?\d{1,2}:\d{1,2}(?:\.\d+)?)\s*(?:结束|截止)")
    for index, conclusion in enumerate(chunk_conclusions, start=1):
        for token in end_pattern.findall(conclusion):
            alleged_end = _time_seconds(token)
            if alleged_end is not None and sampled_end is not None and alleged_end + 0.25 < sampled_end:
                contradictions.append(
                    {
                        "code": "chunk_end_before_later_evidence",
                        "chunk_index": index,
                        "alleged_end": token,
                        "later_sampled_evidence_seconds": round(sampled_end, 3),
                    }
                )

    video_audit_rows = [
        value if isinstance(value, dict) else {}
        for item in parsed_rows
        if isinstance(item, dict)
        for value in [item.get("video_audit_conclusion")]
    ]
    opening_values = sorted({
        str(item.get("opening_integrity") or "").strip().lower()
        for item in video_audit_rows
        if str(item.get("opening_integrity") or "").strip()
    })
    playback_speed_values = sorted({
        str(item.get("playback_speed") or "").strip().lower()
        for item in video_audit_rows
        if str(item.get("playback_speed") or "").strip().lower()
        in {"normal", "accelerated", "unknown"}
    })
    playback_speed = (
        "accelerated"
        if "accelerated" in playback_speed_values
        else "normal" if playback_speed_values == ["normal"] else "unknown"
    )
    requested_fps = []
    for item in case.get("videos") or []:
        try:
            requested_fps.append(float(item.get("fps_requested")))
        except (TypeError, ValueError):
            continue
    sampling_fps = max(requested_fps) if requested_fps else None
    speed_rows = [item.get("speed_review_impact") or {} for item in video_audit_rows]
    speed_rows = [item for item in speed_rows if isinstance(item, dict)]
    speed_rank = {"none": 0, "uncertain": 1, "material": 2}
    speed_status_values = [
        str(item.get("status") or "").lower()
        for item in speed_rows
        if str(item.get("status") or "").lower() in speed_rank
    ]
    speed_status = max(
        speed_status_values,
        key=lambda value: speed_rank.get(value, 1),
        default="none" if playback_speed == "normal" else "unknown",
    )
    affected_review_items = sorted({
        str(value)
        for item in speed_rows
        for value in item.get("affected_review_items") or []
        if str(value) in {
            "sealed_start", "waybill", "opening_action",
            "claimed_item_continuity", "issue_first_visible",
        }
    })
    observable_values = [
        item.get("critical_evidence_observable")
        for item in speed_rows
        if isinstance(item.get("critical_evidence_observable"), bool)
    ]
    critical_evidence_observable = (
        False if speed_status in {"uncertain", "material"}
        else all(observable_values) if observable_values else None
    )
    if playback_speed == "normal":
        speed_status = "none"
        affected_review_items = []
        critical_evidence_observable = None
    elif (
        playback_speed == "accelerated"
        and speed_status == "none"
        and (critical_evidence_observable is False or affected_review_items)
    ):
        speed_status = "uncertain"
        critical_evidence_observable = False
    speed_evidence_refs = [
        dict(reference)
        for item in speed_rows
        if str(item.get("status") or "").lower() == speed_status
        for reference in item.get("evidence_refs") or []
        if registered_reference(reference)
    ]
    opening_compliance_rows = [
        item.get("opening_video_compliance") or {}
        for item in video_audit_rows
    ]
    opening_compliance_rows = [item for item in opening_compliance_rows if isinstance(item, dict)]

    def opening_field_refs(item: Dict[str, Any], field_name: str) -> List[Dict[str, Any]]:
        raw_refs = item.get("evidence_refs") or []
        candidates = (
            raw_refs.get(field_name, [])
            if isinstance(raw_refs, dict)
            else [ref for ref in raw_refs if isinstance(ref, dict) and ref.get("field") == field_name]
        )
        return [dict(ref) for ref in candidates if registered_reference(ref)]

    sealed_true_video_indices = {
        _safe_int(ref.get("video_index"))
        for item in opening_compliance_rows
        if item.get("sealed_start") is True
        for ref in opening_field_refs(item, "sealed_start")
        if _safe_int(ref.get("video_index")) > 0
    }
    sealed_evidence_video_indices = {
        _safe_int(ref.get("video_index"))
        for item in opening_compliance_rows
        for ref in opening_field_refs(item, "sealed_start")
        if _safe_int(ref.get("video_index")) > 0
    }
    primary_opening_video_indices = sealed_true_video_indices or sealed_evidence_video_indices

    def scoped_opening_values(
        field_name: str,
        expected_value: bool | None = None,
    ) -> tuple[List[bool], List[Dict[str, Any]]]:
        values: List[bool] = []
        refs: List[Dict[str, Any]] = []
        for item in opening_compliance_rows:
            value = item.get(field_name)
            if not isinstance(value, bool):
                continue
            if expected_value is not None and value is not expected_value:
                continue
            field_refs = opening_field_refs(item, field_name)
            if primary_opening_video_indices:
                primary_refs = [
                    ref for ref in field_refs
                    if _safe_int(ref.get("video_index")) in primary_opening_video_indices
                ]
                if field_refs and not primary_refs:
                    continue
                field_refs = primary_refs
            values.append(value)
            refs.extend(field_refs)
        return values, refs

    def aggregate_opening_field(field_name: str) -> bool | None:
        values, _ = scoped_opening_values(field_name)
        if False in values:
            return False
        return True if True in values else None

    opening_field_names = (
        "sealed_start", "waybill_visible", "single_take_continuity",
        "issue_visible_in_continuous_opening",
    )
    aggregated_opening_values = {
        field_name: aggregate_opening_field(field_name)
        for field_name in opening_field_names
    }
    opening_evidence_refs = {
        field_name: [
            {key: value for key, value in reference.items() if key != "field"}
            for reference in scoped_opening_values(
                field_name,
                aggregated_opening_values[field_name],
            )[1]
        ]
        if aggregated_opening_values[field_name] is not None else []
        for field_name in opening_field_names
    }

    opening_video_compliance = dict(aggregated_opening_values)
    opening_video_compliance["evidence_refs"] = opening_evidence_refs
    damage_assessment = output.get("damage_causality_assessment") or {}
    primary_damage = (damage_assessment.get("evidence_source_summary") or {}).get("primary_video") or {}
    damage_presence = str(primary_damage.get("damage_presence") or damage_assessment.get("damage_presence") or "").lower()
    claim_support = str(primary_damage.get("claim_support") or damage_assessment.get("claim_support") or "").lower()
    if (
        str(case.get("scenario") or "") == "product_damage"
        and opening_video_compliance["issue_visible_in_continuous_opening"] is True
        and (damage_presence != "confirmed" or claim_support != "supported")
    ):
        opening_video_compliance["issue_visible_in_continuous_opening"] = False
        opening_evidence_refs["issue_visible_in_continuous_opening"] = []
    opening_required_fields = (
        "sealed_start", "waybill_visible", "single_take_continuity",
        "issue_visible_in_continuous_opening",
    ) if str(case.get("scenario") or "") == "product_damage" else (
        "sealed_start", "waybill_visible", "single_take_continuity",
    )
    opening_video_compliance["validated_fields"] = sorted(
        field_name
        for field_name in opening_required_fields
        if sampling_boundary_status == "covered"
        and opening_video_compliance[field_name] is False
        and opening_evidence_refs[field_name]
    )
    opening_video_compliance["source"] = "global_timeline_aggregation"
    opening_video_compliance["result"] = (
        "noncompliant"
        if any(opening_video_compliance[field] is False for field in opening_required_fields)
        else "compliant"
        if all(opening_video_compliance[field] is True for field in opening_required_fields)
        else "indeterminate"
    )
    opening_integrity, opening_integrity_source = _opening_integrity_from_continuity(
        list(output.get("continuity_frame_findings") or []),
        sampling_boundary_status,
    )
    risk_rank = {"low": 0, "medium": 1, "high": 2}
    swap_risk = max(
        (str(item.get("swap_risk_level") or "low").lower() for item in video_audit_rows),
        key=lambda value: risk_rank.get(value, 1),
        default="medium",
    )
    coverage_text = ""
    if sampled_end is not None:
        coverage_text = f"送审时间轴已覆盖至 {format_time(sampled_end)}"
    if source_duration is not None:
        coverage_text += f"，源视频时长约 {format_time(source_duration)}"
    if first_exposed:
        coverage_text += f"；争议商品首次曝光于 {first_exposed}"
    continuity_reason = coverage_text or "未获得可规范化的全局视频时间轴。"
    if continuity.get("continuity_verdict") == "long_absence":
        continuity_reason += f"；检测到最长离镜 {_safe_number(continuity.get('longest_out_of_frame_seconds')):.2f} 秒。"

    label = str(output.get("predicted_label") or "review")
    label_text = {"positive": "当前证据支持本次诉求", "negative": "当前证据不支持本次诉求", "review": "当前证据仍需复核"}.get(label, "当前证据仍需复核")
    output["video_audit_conclusion"] = {
        "continuity_score": None,
        "continuity_reason": continuity_reason,
        "swap_risk_level": swap_risk,
        "edit_or_cut_risk": "需结合媒体取证与连续性时间轴判断",
        "opening_integrity": opening_integrity,
        "opening_integrity_source": opening_integrity_source,
        "segment_opening_claims": opening_values,
        "playback_speed": playback_speed,
        "segment_playback_speed_values": playback_speed_values,
        "sampling_fps": sampling_fps,
        "speed_review_impact": {
            "status": speed_status,
            "critical_evidence_observable": critical_evidence_observable,
            "affected_review_items": affected_review_items,
            "evidence_refs": speed_evidence_refs,
            "source": "segment_consensus",
        },
        "opening_video_compliance": opening_video_compliance,
        "sampling_boundary_status": sampling_boundary_status,
        "technical_timeline_status": "requires_media_forensics",
        "evidence_continuity_status": continuity.get("continuity_verdict") or "indeterminate",
        "source": "global_timeline_aggregation",
    }
    output["overall_audit"] = {
        "conclusion": f"{label_text}。{continuity_reason}",
        "confidence": output.get("confidence"),
        "core_reason": "结论由完整帧注册表、专项连续性结果和全部分段结构化证据聚合，未采用局部分段的结束叙述。",
        "business_follow_up_suggestion": "按证据门槛和甲方已批准策略处理；本服务不自动执行退款、补发、换货或拒绝。",
    }
    output["global_review_summary"] = {
        "sampled_start_seconds": sampled_start,
        "sampled_end_seconds": sampled_end,
        "source_duration_seconds": source_duration,
        "claimed_item_first_exposed_timestamp": first_exposed or None,
        "opening_integrity": opening_integrity,
        "opening_integrity_source": opening_integrity_source,
        "continuity_verdict": continuity.get("continuity_verdict") or "indeterminate",
        "sampling_boundary_status": sampling_boundary_status,
        "technical_timeline_status": "requires_media_forensics",
        "timeline_coverage_ratio": timeline_coverage_ratio,
        "chunk_narratives_excluded_from_public_conclusion": True,
    }
    output["aggregation_warnings"] = contradictions
    return output


def _safe_number(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(0.0, parsed) if math.isfinite(parsed) else default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return default


def _model_http_metrics(attempts: List[Dict[str, Any]]) -> Dict[str, Any]:
    sent = [
        item
        for item in attempts
        if isinstance(item, dict) and item.get("request_sent") is True
    ]
    return {
        "model_http_request_count": len(sent),
        "model_latency_seconds_sum": round(
            sum(_safe_number(item.get("latency_seconds")) for item in sent),
            2,
        ),
    }


def _physical_model_call_count(item: Dict[str, Any]) -> int:
    attempts = item.get("http_attempts") or []
    sent_count = len([
        attempt
        for attempt in attempts
        if isinstance(attempt, dict) and attempt.get("request_sent") is True
    ])
    explicit_count = _safe_int(item.get("model_http_request_count"))
    if explicit_count or sent_count:
        return max(explicit_count, sent_count)
    if item.get("cost_status") == "not_incurred":
        return 0
    return 1 + _safe_int(item.get("repair_calls"))


def _physical_model_latency(item: Dict[str, Any]) -> float:
    if "model_latency_seconds_sum" in item:
        return _safe_number(item.get("model_latency_seconds_sum"))
    attempts = item.get("http_attempts") or []
    sent_latency = sum(
        _safe_number(attempt.get("latency_seconds"))
        for attempt in attempts
        if isinstance(attempt, dict) and attempt.get("request_sent") is True
    )
    return sent_latency or _safe_number(item.get("latency_seconds"))


def merge_model_billing(
    result: Dict[str, Any],
    additions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    rows = [copy.deepcopy(result), *(copy.deepcopy(item) for item in additions)]
    output = rows[0]
    output["usage"] = {
        key: sum(_safe_int((item.get("usage") or {}).get(key)) for item in rows)
        for key in ("input_tokens", "output_tokens", "total_tokens")
    }
    base_cost = dict(output.get("cost") or {})
    base_cost["estimated_usd"] = round(
        sum(_safe_number((item.get("cost") or {}).get("estimated_usd")) for item in rows),
        6,
    )
    currencies = {
        str((item.get("cost") or {}).get("currency") or "")
        for item in rows
        if (item.get("cost") or {}).get("currency")
    }
    if len(currencies) == 1:
        base_cost["amount"] = round(
            sum(_safe_number((item.get("cost") or {}).get("amount")) for item in rows),
            6,
        )
    output["cost"] = base_cost
    output.update(_cost_observability(rows))
    output["model_http_request_count"] = sum(
        _safe_int(item.get("model_http_request_count"))
        or len([
            attempt
            for attempt in item.get("http_attempts") or []
            if isinstance(attempt, dict) and attempt.get("request_sent") is True
        ])
        for item in rows
    )
    output["model_latency_seconds_sum"] = round(sum(
        _safe_number(item.get("model_latency_seconds_sum") or item.get("latency_seconds"))
        for item in rows
    ), 2)
    output["http_attempts"] = [
        copy.deepcopy(attempt)
        for item in rows
        for attempt in item.get("http_attempts") or []
        if isinstance(attempt, dict)
    ]
    output["_channel_route_attempts"] = collect_channel_route_attempts(rows)
    return output


def _frame_key(item: Dict[str, Any]) -> tuple[int, int] | None:
    try:
        return int(item.get("video_index") or 0), int(item["global_frame_index"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def _aggregate_chunk_results(
    case: Dict[str, Any],
    results: List[Dict[str, Any]],
    main_failures: Optional[List[Dict[str, Any]]] = None,
    continuity_results: Optional[List[Dict[str, Any]]] = None,
    continuity_failures: Optional[List[Dict[str, Any]]] = None,
    causality_results: Optional[List[Dict[str, Any]]] = None,
    causality_failures: Optional[List[Dict[str, Any]]] = None,
    main_review_frame_count: Optional[int] = None,
    supplemental_results: Optional[List[Dict[str, Any]]] = None,
    supplemental_failures: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    def channel_summary(items: List[Dict[str, Any]]) -> Dict[str, Any]:
        representations = sorted({str(item.get("input_representation")) for item in items if item.get("input_representation")})
        repair_calls = sum(_safe_int(item.get("repair_calls")) for item in items)
        return {
            "model_calls": sum(_physical_model_call_count(item) for item in items),
            "segment_calls": len(items),
            "repair_calls": repair_calls,
            "input_representations": representations,
            "model_images": sum(_safe_int(item.get("model_image_count")) for item in items),
            "model_latency_seconds_sum": round(
                sum(_physical_model_latency(item) for item in items), 2
            ),
            "input_tokens": sum(_safe_int((item.get("usage") or {}).get("input_tokens")) for item in items),
            "output_tokens": sum(_safe_int((item.get("usage") or {}).get("output_tokens")) for item in items),
            "total_tokens": sum(_safe_int((item.get("usage") or {}).get("total_tokens")) for item in items),
            "estimated_usd": round(sum(_safe_number((item.get("cost") or {}).get("estimated_usd")) for item in items), 6),
            **_cost_observability(items),
        }

    parsed_rows = [item.get("parsed") or {} for item in results]
    supplemental_rows = [item.get("parsed") or {} for item in (supplemental_results or [])]
    confidences = [_safe_confidence(item.get("confidence")) for item in parsed_rows]
    best_index = max(range(len(parsed_rows)), key=lambda index: confidences[index])
    parsed = dict(parsed_rows[best_index])
    predicted = "review"
    confidence = round(sum(confidences) / max(len(confidences), 1), 4)
    for key in ("frame_findings", "adopted_evidence", "supporting_evidence", "challenging_evidence", "supplemental_image_reviews", "issue_timestamps", "material_gaps", "skeptical_questions", "audit_methods"):
        rows = (
            parsed_rows + supplemental_rows
            if key in {"adopted_evidence", "supporting_evidence", "challenging_evidence", "supplemental_image_reviews", "material_gaps"}
            else parsed_rows
        )
        parsed[key] = [entry for item in rows for entry in (item.get(key) or [])][:120]
    business_scenario = str((case.get("structured_business_context") or {}).get("business_scenario") or case.get("scenario") or "")
    causality_complete = bool(causality_results) and not causality_failures
    causality_rows = [item.get("parsed") or {} for item in (causality_results or [])]
    if business_scenario == "product_damage":
        primary_damage_rows = causality_rows or parsed_rows
        primary_damage_assessment = aggregate_damage_causality(primary_damage_rows)
        damage_rows = primary_damage_rows + supplemental_rows
        damage_assessment = aggregate_damage_causality(damage_rows)
        supplemental_evidence = [
            dict(entry)
            for row in parsed_rows + supplemental_rows
            for key in ("adopted_evidence", "supporting_evidence", "challenging_evidence", "supplemental_image_reviews")
            for entry in row.get(key) or []
            if isinstance(entry, dict)
            and str(entry.get("source_type") or "").lower() in {
                "supplementary_image", "supplemental_image", "supplemental_image_review", "image",
            }
        ]
        referenced_indices = sorted({
            int(item["image_index"])
            for item in supplemental_evidence
            if str(item.get("image_index") or "").isdigit()
        })
        linkage_states = [
            (
                normalize_supplemental_linkage(item.get("same_item_linkage")),
                normalize_supplemental_linkage(item.get("temporal_linkage"), temporal=True),
            )
            for item in supplemental_evidence
        ]
        linkage_verified = any(same is True and temporal is True for same, temporal in linkage_states)
        provided_count = len(case.get("supplemental_images") or [])
        linkage_explicitly_rejected = (
            provided_count > 0
            and len(referenced_indices) == provided_count
            and bool(supplemental_evidence)
            and bool(linkage_states)
            and all(
                same is not None
                and temporal is not None
                and not (same is True and temporal is True)
                for same, temporal in linkage_states
            )
        )
        linkage_status = "verified" if linkage_verified else "not_linked" if linkage_explicitly_rejected else "unresolved"
        supplemental_findings = []
        seen_supplemental = set()
        for item in supplemental_evidence:
            key = (item.get("image_index"), str(item.get("fact") or item.get("description") or ""))
            if key in seen_supplemental:
                continue
            seen_supplemental.add(key)
            supplemental_findings.append({
                "source_type": "supplementary_image",
                "image_index": item.get("image_index"),
                "fact": item.get("fact") or item.get("description") or "补充图片已被模型引用，但没有形成可公开的事实描述。",
                "why_it_matters": item.get("why_it_matters") or "用于核对补充图片是否支持主诉，以及能否与主视频建立同物、同部位和过程关联。",
                "same_item_linkage": normalize_supplemental_linkage(item.get("same_item_linkage")),
                "temporal_linkage": normalize_supplemental_linkage(item.get("temporal_linkage"), temporal=True),
            })
        damage_assessment["evidence_source_summary"] = {
            "primary_video": {
                "scope": "sampled_opening_video",
                "damage_presence": primary_damage_assessment.get("damage_presence"),
                "claim_support": primary_damage_assessment.get("claim_support"),
            },
            "supplemental_images": {
                "provided_count": provided_count,
                "processed_count": len(referenced_indices),
                "referenced_count": len(referenced_indices),
                "referenced_image_indices": referenced_indices,
                "unreferenced_image_indices": [
                    index for index in range(1, provided_count + 1) if index not in referenced_indices
                ],
                "linkage_status": linkage_status,
                "evidence_findings": supplemental_findings[:12],
            },
            "decision_boundary": "补充特写图未建立同物、同部位和过程关联时，不能单独推翻主视频结论。",
        }
        valid_frame_keys = {
            key
            for item in case.get("frames") or []
            if (key := _frame_key(item)) is not None
        }
        damage_assessment["key_evidence"] = _damage_key_evidence(damage_rows, valid_frame_keys)
        parsed["damage_causality_assessment"] = damage_assessment
        parsed["damage_observability"] = _aggregate_damage_observability(parsed_rows + causality_rows)
        if causality_rows:
            parsed["causality_frame_findings"] = [
                finding
                for row in causality_rows
                for finding in (row.get("frame_findings") or [])
            ][:2400]
    continuity_complete = bool(continuity_results) and not continuity_failures
    continuity_rows = [item.get("parsed") or {} for item in (continuity_results or [])]
    continuity_coverage_gaps = [
        {
            "chunk_index": index + 1,
            "missing_target_frame_indices": item.get("missing_target_frame_indices") or [],
            "missing_target_frame_count": len(item.get("missing_target_frame_indices") or []),
            "reason": item.get("coverage_gap_reason") or "frame_findings_missing",
            "assessment_status": item.get("assessment_status") or "",
        }
        for index, item in enumerate(continuity_results or [])
        if item.get("coverage_status") == "partial_unknown"
    ]
    causality_coverage_gaps = [
        {
            "chunk_index": index + 1,
            "missing_target_frame_indices": item.get("missing_target_frame_indices") or [],
            "missing_target_frame_count": len(item.get("missing_target_frame_indices") or []),
            "reason": item.get("coverage_gap_reason") or "frame_findings_missing",
            "assessment_status": item.get("assessment_status") or "",
        }
        for index, item in enumerate(causality_results or [])
        if item.get("coverage_status") == "partial_unknown"
    ]
    if case.get("videos") or case.get("frames"):
        parsed["object_continuity_assessment"] = aggregate_object_continuity(
            continuity_rows or parsed_rows,
            case.get("frames") or [],
            (case.get("structured_business_context") or {}).get("continuity_policy"),
        )
        if continuity_rows:
            parsed["continuity_frame_findings"] = [
                finding
                for row in continuity_rows
                for finding in (row.get("frame_findings") or [])
            ][:2400]
    if business_scenario in {"wrong_item", "missing_item"}:
        parsed["fulfillment_reconciliation"] = aggregate_fulfillment_reconciliation(parsed_rows, case, business_scenario)
    conclusions = [str((item.get("overall_audit") or {}).get("conclusion") or "").strip() for item in parsed_rows]
    parsed.update({
        "predicted_label": predicted,
        "system_yes_no": {"positive": "YES", "negative": "NO"}.get(predicted, "REVIEW"),
        "confidence": confidence,
        "overall_audit": {
            "conclusion": "分段结论已转入内部审计，公开结论将在全局时间轴校验后生成。",
            "confidence": confidence,
            "core_reason": f"已完成 {len(results)} 个时间分段的独立审核并聚合证据。",
            "business_follow_up_suggestion": "请VIP客服结合全部分段证据和业务规则复核。",
        },
        "business_action_allowed": False,
        "human_required": True,
        "chunk_audits": [
            {"chunk_index": index, "predicted_label": item.get("predicted_label"), "confidence": item.get("confidence")}
            for index, item in enumerate(parsed_rows, start=1)
        ],
    })
    billed_results = (
        results
        + (main_failures or [])
        + (supplemental_results or [])
        + (supplemental_failures or [])
        + (continuity_results or [])
        + (causality_results or [])
        + (continuity_failures or [])
        + (causality_failures or [])
    )
    usage = {
        key: sum(_safe_int((item.get("usage") or {}).get(key)) for item in billed_results)
        for key in ("input_tokens", "output_tokens", "total_tokens")
    }
    estimated_usd = round(sum(_safe_number((item.get("cost") or {}).get("estimated_usd")) for item in billed_results), 6)
    cost_observability = _cost_observability(billed_results)
    total_model_calls = sum(_physical_model_call_count(item) for item in billed_results)
    http_attempts = [
        copy.deepcopy(attempt)
        for item in billed_results
        for attempt in item.get("http_attempts") or []
        if isinstance(attempt, dict)
    ]
    label = load_report_label(case["case_id"])
    parsed = apply_damage_causality_guard(enforce_boundary(parsed), business_scenario, case.get("frames") or [])
    parsed = apply_object_continuity_guard(
        parsed,
        business_scenario,
        bool(case.get("videos") or case.get("frames")),
        (case.get("structured_business_context") or {}).get("continuity_policy"),
    )
    parsed = apply_fulfillment_guard(parsed, business_scenario)
    specialized_incomplete = (
        (continuity_failures or [])
        + (causality_failures or [])
        + (supplemental_failures or [])
        + continuity_coverage_gaps
        + causality_coverage_gaps
    )
    if main_failures:
        parsed.update({
            "predicted_label": "review",
            "system_yes_no": "REVIEW",
            "decision": "manual_review",
            "confidence": min(_safe_confidence(parsed.get("confidence"), 0.5), 0.69),
            "business_action_allowed": False,
            "human_required": True,
            "specialized_pass_guard_reason": "主审核存在失败、模型输出缺口或结构不完整；已返回的有效证据予以保留，但不能使用不完整的主审核结果形成确定结论。",
            "pass_integrity_status": "degraded",
        })
    elif specialized_incomplete:
        parsed["pass_integrity_status"] = "partial_specialized"
        parsed["specialized_pass_warning"] = "连续性、损伤成因或补充图片专项存在局部缺口；成功返回的证据继续有效，缺口只使对应证据维度保持未知。"
    else:
        parsed["pass_integrity_status"] = "complete"
    parsed = _apply_global_timeline_summary(case, parsed, parsed_rows, conclusions)
    damage_assessment = parsed.get("damage_causality_assessment") or {}
    fulfillment_assessment = parsed.get("fulfillment_reconciliation") or {}
    continuity_assessment = parsed.get("object_continuity_assessment") or {}
    visibility_coverages = [
        _safe_number(item.get("visibility_coverage"))
        for item in continuity_assessment.get("tracked_subjects") or []
        if isinstance(item, dict)
    ]
    parsed["confidence_components"] = {
        "main_segment_mean": confidence,
        "damage_origin": damage_assessment.get("origin_confidence"),
        "fulfillment_reconciliation": fulfillment_assessment.get("confidence"),
        "continuity_visibility_coverage": (
            round(sum(visibility_coverages) / len(visibility_coverages), 4)
            if visibility_coverages
            else None
        ),
        "final_decision": parsed.get("confidence"),
        "calibration_status": "uncalibrated_model_score",
        "interpretation": "各分数分别表示模型自评、成因假设、对账识别和规则降级后的决策强度；在留出集校准前均不等同于真实正确率。",
    }
    request_profile = next(
        (
            copy.deepcopy(item["request_profile"])
            for item in billed_results
            if isinstance(item.get("request_profile"), dict) and item["request_profile"]
        ),
        {},
    )
    return {
        "status": "success",
        "latency_seconds": round(sum(_safe_number(item.get("latency_seconds")) for item in billed_results), 2),
        "model_http_request_count": total_model_calls,
        "model_latency_seconds_sum": round(
            sum(_physical_model_latency(item) for item in billed_results), 2
        ),
        "http_attempts": http_attempts,
        "usage": usage,
        "cost": {"estimated_usd": estimated_usd},
        "request_profile": request_profile,
        **cost_observability,
        "_channel_route_attempts": collect_channel_route_attempts(billed_results),
        "parsed": parsed,
        "evaluation": evaluate(parsed, label),
        "policy_decision": policy_decision(parsed),
        "chunking": {
            "segment_count": len(results) + len(main_failures or []),
            "frames_per_segment": case.get("model_frames_per_call"),
            "total_frames": len(case.get("frames") or []),
            "main_review_frames": (
                int(main_review_frame_count)
                if main_review_frame_count is not None
                else len(case.get("frames") or [])
            ),
            "total_model_calls": total_model_calls,
            "channels": {
                "main_review": channel_summary(results + (main_failures or [])),
                "supplemental_evidence": channel_summary(
                    (supplemental_results or []) + (supplemental_failures or [])
                ),
                "object_continuity": channel_summary((continuity_results or []) + (continuity_failures or [])),
                "damage_causality": channel_summary((causality_results or []) + (causality_failures or [])),
            },
            "main_review_pass": {
                "status": "degraded" if main_failures else "completed",
                "successful_segment_count": len(results),
                "failures": main_failures or [],
            },
            "supplemental_evidence_pass": {
                "status": (
                    "degraded" if supplemental_failures
                    else "completed" if supplemental_results
                    else "disabled"
                ),
                "segment_count": len(supplemental_results or []),
                "failures": supplemental_failures or [],
            },
            "continuity_pass": {
                "status": "degraded" if continuity_failures or continuity_coverage_gaps else ("completed" if continuity_complete else "disabled"),
                "segment_count": len(continuity_results or []),
                "failures": continuity_failures or [],
                "coverage_gaps": continuity_coverage_gaps,
            },
            "damage_causality_pass": {
                "status": "degraded" if causality_failures or causality_coverage_gaps else ("completed" if causality_complete else "disabled"),
                "segment_count": len(causality_results or []),
                "failures": causality_failures or [],
                "coverage_gaps": causality_coverage_gaps,
            },
        },
    }


def _representative_frames(frames: List[Dict[str, Any]], max_frames: int) -> List[Dict[str, Any]]:
    if max_frames <= 0 or len(frames) <= max_frames:
        return list(frames)
    if max_frames == 1:
        return [frames[0]]
    last_index = len(frames) - 1
    indices = [round(position * last_index / (max_frames - 1)) for position in range(max_frames)]
    return [frames[index] for index in indices]


def derive_claim_identity(results: List[Dict[str, Any]], case: Dict[str, Any]) -> Dict[str, Any]:
    def parsed_dict(item: Any) -> Dict[str, Any]:
        value = item.get("parsed") if isinstance(item, dict) else None
        return value if isinstance(value, dict) else {}

    identity: Dict[str, Any] = {"customer_claim": str(case.get("customer_claim") or "").strip()}
    for result in sorted(
        results,
        key=lambda item: _safe_confidence(parsed_dict(item).get("confidence")),
        reverse=True,
    ):
        parsed = parsed_dict(result)
        claim = parsed.get("customer_claim_parse") if isinstance(parsed.get("customer_claim_parse"), dict) else {}
        order_item = parsed.get("expected_order_item") if isinstance(parsed.get("expected_order_item"), dict) else {}
        actual_item = parsed.get("actual_received_item") if isinstance(parsed.get("actual_received_item"), dict) else {}
        candidates = {
            "item_ref": order_item.get("item_ref") or actual_item.get("item_ref"),
            "sku": order_item.get("sku") or actual_item.get("sku"),
            "product_name": order_item.get("product_name") or actual_item.get("product_name"),
            "specification": order_item.get("specification") or actual_item.get("specification"),
            "expected_item": claim.get("expected_item"),
            "claimed_received_item": claim.get("claimed_received_item"),
        }
        for key, value in candidates.items():
            if key not in identity and value not in (None, "", [], {}):
                identity[key] = value
    return {key: value for key, value in identity.items() if value not in (None, "", [], {})}


def call_model_chunked(
    cfg: Dict[str, Any],
    case: Dict[str, Any],
    timeout: int,
    retries: int,
    deadline_at: Optional[float] = None,
) -> Dict[str, Any]:
    wall_started = time.time()
    freeze_rule_snapshot(case)

    def invoke_model(current_case: Dict[str, Any]) -> Dict[str, Any]:
        if deadline_at is None:
            return call_model(cfg, current_case, timeout, retries)
        return call_model(
            cfg,
            current_case,
            timeout,
            retries,
            deadline_at=deadline_at,
        )

    frames = case.get("frames") or []
    limit = max(1, min(int(case.get("model_frames_per_call") or 24), 24))
    scenario = str((case.get("structured_business_context") or {}).get("business_scenario") or case.get("scenario") or "")
    policy = (case.get("structured_business_context") or {}).get("continuity_policy") or {}
    causality_policy = (case.get("structured_business_context") or {}).get("damage_causality_policy") or {}
    unified_multitask = (
        cfg.get("provider") == "gemini_native"
        and cfg.get("unified_multitask", True) is not False
        and scenario in {"video_unboxing", "wrong_item", "missing_item", "product_damage"}
        and policy.get("force_dense_scan") is True
        and (scenario != "product_damage" or causality_policy.get("force_action_scan") is True)
    )
    if scenario in {"minor_material", "minor_refund"}:
        workers = recommended_concurrency(max(1, min(int(os.getenv("REVIEW_MINOR_WORKERS", "6") or 6), 8)))
        output = run_minor_material_pipeline(
            case,
            invoke=invoke_model,
            workers=workers,
        )
        parsed = output.get("parsed") or {}
        output["evaluation"] = evaluate(parsed, load_report_label(case["case_id"]))
        output["policy_decision"] = policy_decision(parsed)
        return output
    if (
        scenario == "product_damage"
        and frames
        and not str(
            (case.get("structured_business_context") or {}).get("analysis_mode") or ""
        )
    ):
        result = run_sampled_video_perception(
            case,
            invoke_model=invoke_model,
            merge_billing=merge_model_billing,
            batch_size=limit,
            overlap=max(
                0,
                min(int(os.getenv("REVIEW_SAMPLED_BATCH_OVERLAP", "2") or 2), limit - 1),
            ),
            workers=recommended_concurrency(max(
                1,
                min(int(os.getenv("REVIEW_CHUNK_WORKERS", "2") or 2), 4),
            )),
        )
        parsed = result.get("parsed") or {}
        result["evaluation"] = evaluate(parsed, load_report_label(case["case_id"]))
        result["policy_decision"] = policy_decision(parsed)
        return result
    if (
        scenario in {"wrong_item", "missing_item"}
        and (case.get("native_video") or case.get("native_videos"))
        and case.get("supplemental_images")
    ):
        video_case = copy.deepcopy(case)
        video_case["frames"] = []
        video_case["supplemental_images"] = []
        video_case["official_reference_images"] = []
        video_structured = dict(video_case.get("structured_business_context") or {})
        video_structured["review_chunk"] = {"pass_type": "fulfillment_video"}
        video_case["structured_business_context"] = video_structured

        supplemental_case = copy.deepcopy(case)
        supplemental_case["native_video"] = None
        supplemental_case["native_videos"] = []
        supplemental_case["videos"] = []
        supplemental_case["frames"] = []
        supplemental_structured = dict(supplemental_case.get("structured_business_context") or {})
        supplemental_structured["review_chunk"] = {"pass_type": "fulfillment_supplemental"}
        supplemental_case["structured_business_context"] = supplemental_structured

        source_results = []
        source_failures = []
        for source_case, representation in (
            (video_case, "native_video_only"),
            (supplemental_case, "supplemental_images_only"),
        ):
            source_result = invoke_model(source_case)
            source_result["input_representation"] = representation
            source_result["model_image_count"] = len(source_case.get("supplemental_images") or [])
            (source_results if source_result.get("status") == "success" else source_failures).append(source_result)
        if not source_results:
            result = merge_model_billing(source_failures[0], source_failures[1:])
            result["chunking"] = {
                "pipeline_mode": "source_isolated_fulfillment",
                "segment_count": len(source_failures),
                "total_model_calls": sum(_physical_model_call_count(item) for item in source_failures),
            }
            return result
        result = _aggregate_chunk_results(case, source_results, main_failures=source_failures)
        result.setdefault("chunking", {})["pipeline_mode"] = "source_isolated_fulfillment"
        return result
    if not frames:
        result = invoke_model(case)
        result["chunking"] = {
            "segment_count": 1,
            "frames_per_segment": limit,
            "total_frames": 0,
            "main_review_frames": 0,
        }
        result["model_latency_seconds_sum"] = result.get("latency_seconds")
        result["latency_seconds"] = round(time.time() - wall_started, 2)
        return result
    main_frames = frames
    if (
        scenario == "product_damage"
        and policy.get("force_dense_scan")
        and causality_policy.get("force_action_scan")
        and not unified_multitask
    ):
        main_frame_limit = max(
            24,
            min(int(os.getenv("REVIEW_PRODUCT_DAMAGE_MAIN_MAX_FRAMES", "48") or 48), 96),
        )
        main_frames = _representative_frames(frames, main_frame_limit)
    chunks = [main_frames[index:index + limit] for index in range(0, len(main_frames), limit)]
    workers = recommended_concurrency(max(1, min(int(os.getenv("REVIEW_CHUNK_WORKERS", "2") or 2), 4, len(chunks))))
    reference_segment_limit = max(1, min(int(os.getenv("REVIEW_PRODUCT_IMAGE_MAX_SEGMENTS", "3") or 3), 3, len(chunks)))
    reference_segment_indices = {
        round(position * (len(chunks) - 1) / max(reference_segment_limit - 1, 1))
        for position in range(reference_segment_limit)
    }

    def review_chunk(index: int, chunk: List[Dict[str, Any]]) -> Dict[str, Any]:
        chunk_case = dict(case)
        chunk_case["frames"] = chunk
        chunk_case["supplemental_images"] = (
            [] if scenario == "product_damage" else (case.get("supplemental_images") or [])[:4]
        )
        chunk_case["official_reference_images"] = (
            case.get("official_reference_images") or []
        ) if index in reference_segment_indices else []
        structured = dict(case.get("structured_business_context") or {})
        structured["unified_multitask"] = unified_multitask
        structured["review_chunk"] = {
            "index": index + 1,
            "total": len(chunks),
            "is_final_chunk": index + 1 == len(chunks),
            "global_video_frame_count": len(frames),
            "main_review_frame_count": len(main_frames),
            "instruction": "本段最后一帧只代表本分段观察截止点；除非 is_final_chunk=true 且有全局媒体时长佐证，不得表述为视频结束。",
            "official_reference_images_attached": len(chunk_case["official_reference_images"]),
        }
        chunk_case["structured_business_context"] = structured
        result = invoke_model(chunk_case)
        result["_input_frame_indices"] = [frame.get("global_frame_index") for frame in chunk]
        result["input_representation"] = "individual_frames"
        result["model_image_count"] = len(chunk) + len(chunk_case["official_reference_images"])
        return result

    completed, concurrency_audit = run_adaptive_tasks(
        list(enumerate(chunks)),
        workers=workers,
        invoke=lambda item: review_chunk(item[0], item[1]),
    )
    failures = [
        {
            "chunk_index": index + 1,
            "status": item.get("status") or "failed",
            "error": item.get("error") or item.get("status"),
            "error_type": item.get("error_type") or "",
            "status_code": item.get("status_code"),
            "usage": item.get("usage") or {},
            "cost": item.get("cost") or {},
            "cost_status": item.get("cost_status") or "",
            "latency_seconds": item.get("latency_seconds") or 0,
            "model_http_request_count": item.get("model_http_request_count") or 0,
            "model_latency_seconds_sum": item.get("model_latency_seconds_sum") or 0,
            "http_attempts": item.get("http_attempts") or [],
            "_channel_route_attempts": item.get("_channel_route_attempts") or [],
        }
        for index, item in enumerate(completed)
        if item.get("status") != "success"
    ]
    successful = [item for item in completed if item.get("status") == "success"]
    dimension_gaps = unified_dimension_gaps(successful, scenario) if unified_multitask else []
    if failures and not successful:
        all_skipped = all(item.get("status") == "skipped" for item in completed)
        incurred_calls = sum(_physical_model_call_count(item) for item in completed)
        usage = {
            key: sum(_safe_int((item.get("usage") or {}).get(key)) for item in completed)
            for key in ("input_tokens", "output_tokens", "total_tokens")
        }
        return {
            "status": "skipped" if all_skipped else "failed",
            "error": failures[0].get("error") if all_skipped else "chunk_review_failed",
            "error_type": (
                failures[0].get("error_type")
                if failures and len({item.get("error_type") for item in failures}) == 1
                else ""
            ),
            "status_code": next((item.get("status_code") for item in failures if item.get("status_code")), None),
            "chunk_failures": failures,
            "usage": usage,
            "cost": {
                "estimated_usd": round(sum(_safe_number((item.get("cost") or {}).get("estimated_usd")) for item in completed), 6)
            },
            **_cost_observability(completed),
            "model_http_request_count": incurred_calls,
            "http_attempts": [
                copy.deepcopy(attempt)
                for item in completed
                for attempt in item.get("http_attempts") or []
                if isinstance(attempt, dict)
            ],
            "_channel_route_attempts": collect_channel_route_attempts(completed),
            "model_latency_seconds_sum": round(
                sum(_physical_model_latency(item) for item in completed), 2
            ),
            "latency_seconds": round(time.time() - wall_started, 2),
            "chunking": {
                "segment_count": len(chunks),
                "total_frames": len(frames),
                "main_review_frames": len(main_frames),
                "total_model_calls": incurred_calls,
                "concurrency": concurrency_audit,
                "channels": {"main_review": {
                    "model_calls": incurred_calls,
                    "total_tokens": usage["total_tokens"],
                    "estimated_usd": round(sum(_safe_number((item.get("cost") or {}).get("estimated_usd")) for item in completed), 6),
                }},
            },
        }

    supplemental_results: List[Dict[str, Any]] = []
    supplemental_failures: List[Dict[str, Any]] = []
    supplemental_concurrency: Dict[str, Any] = {}
    supplemental_images = case.get("supplemental_images") or []
    if scenario == "product_damage" and supplemental_images:
        supplemental_context_frames = _representative_frames(frames, 6)
        supplemental_references = list(case.get("official_reference_images") or [])
        supplemental_batch_size = min(
            8,
            max(1, 24 - len(supplemental_context_frames) - len(supplemental_references)),
        )
        supplemental_chunks = [
            supplemental_images[index:index + supplemental_batch_size]
            for index in range(0, len(supplemental_images), supplemental_batch_size)
        ]

        def review_supplemental_chunk(index: int, images: List[Dict[str, Any]]) -> Dict[str, Any]:
            chunk_case = dict(case)
            chunk_case["frames"] = supplemental_context_frames
            chunk_case["supplemental_images"] = images
            chunk_case["official_reference_images"] = supplemental_references
            structured = dict(case.get("structured_business_context") or {})
            structured["review_chunk"] = {
                "pass_type": "supplemental_evidence",
                "index": index + 1,
                "total": len(supplemental_chunks),
                "is_final_chunk": index + 1 == len(supplemental_chunks),
                "instruction": (
                    "本轮专门逐张审核补充图片。每张图片都必须在 adopted_evidence、"
                    "supporting_evidence 或 challenging_evidence 中引用 image_index；"
                    "分别填写 damage_visible 布尔值、同物关联和时序关联；文字描述不能替代"
                    " damage_visible，不得因主视频证据不足而省略图片。"
                ),
            }
            chunk_case["structured_business_context"] = structured
            result = invoke_model(chunk_case)
            result["input_representation"] = "supplemental_batch"
            result["model_image_count"] = (
                len(supplemental_context_frames) + len(images) + len(supplemental_references)
            )
            if result.get("status") != "success":
                return result
            expected_indices = {
                int(image["image_index"])
                for image in images
                if str(image.get("image_index") or "").isdigit()
            }
            parsed = dict(result.get("parsed") or {})
            found_indices = set()
            for key in ("adopted_evidence", "supporting_evidence", "challenging_evidence"):
                anchored = []
                for raw in parsed.get(key) or []:
                    item = dict(raw) if isinstance(raw, dict) else raw
                    if isinstance(item, dict) and "image" in str(item.get("source_type") or "").lower():
                        image_index = item.get("image_index")
                        if not str(image_index or "").isdigit() and len(expected_indices) == 1:
                            image_index = next(iter(expected_indices))
                            item["image_index"] = image_index
                        if str(image_index or "").isdigit() and int(image_index) in expected_indices:
                            image_index = int(image_index)
                            found_indices.add(image_index)
                            item.setdefault("asset_ref", f"supplemental_image_{image_index}")
                    anchored.append(item)
                parsed[key] = anchored
            parsed["supplemental_image_reviews"] = [
                {
                    "source_type": "supplemental_image_review",
                    "image_index": image_index,
                    "asset_ref": f"supplemental_image_{image_index}",
                    "fact": "该补充图片已完成独立审核，本轮未形成可采信的损伤或反证描述。",
                    "why_it_matters": "用于区分已处理但无有效发现与系统尚未处理。",
                    "same_item_linkage": None,
                    "temporal_linkage": None,
                }
                for image_index in sorted(expected_indices - found_indices)
            ]
            return {**result, "parsed": parsed}

        supplemental_completed, supplemental_concurrency = run_adaptive_tasks(
            list(enumerate(supplemental_chunks)),
            workers=max(1, min(workers, len(supplemental_chunks))),
            invoke=lambda item: review_supplemental_chunk(item[0], item[1]),
        )
        supplemental_results = [
            item for item in supplemental_completed if item.get("status") == "success"
        ]
        supplemental_failures = [
            {
                "chunk_index": index + 1,
                "status": item.get("status") or "failed",
                "error": item.get("error") or item.get("status"),
                "error_type": item.get("error_type") or "",
                "status_code": item.get("status_code"),
                "usage": item.get("usage") or {},
                "cost": item.get("cost") or {},
                "cost_status": item.get("cost_status") or "",
                "latency_seconds": item.get("latency_seconds") or 0,
                "_channel_route_attempts": item.get("_channel_route_attempts") or [],
            }
            for index, item in enumerate(supplemental_completed)
            if item.get("status") != "success"
        ]
    specialized_case = dict(case)
    specialized_structured = dict(case.get("structured_business_context") or {})
    claim_identity = derive_claim_identity(successful, case)
    if claim_identity:
        specialized_structured["continuity_claim_identity"] = claim_identity
    specialized_case["structured_business_context"] = specialized_structured
    continuity_results: List[Dict[str, Any]] = []
    continuity_failures: List[Dict[str, Any]] = []
    if (
        policy.get("force_dense_scan")
        and scenario in {"video_unboxing", "wrong_item", "missing_item", "product_damage"}
        and (not unified_multitask or "object_continuity" in dimension_gaps)
    ):
        configured_continuity_limit = max(
            12,
            min(int(os.getenv("REVIEW_CONTINUITY_FRAMES_PER_CALL", "24") or 24), 24),
        )
        continuity_results, continuity_failures = run_specialized_frame_pass(
            specialized_case,
            mode="object_continuity_only",
            target_index_key="continuity_target_frame_indices",
            chunk_size=configured_continuity_limit,
            context_frame_count=3,
            workers=workers,
            invoke=invoke_model,
            repair_attempts=1,
            preserve_partial_coverage=True,
        )
    causality_results: List[Dict[str, Any]] = []
    causality_failures: List[Dict[str, Any]] = []
    if (
        scenario == "product_damage"
        and causality_policy.get("force_action_scan")
        and (not unified_multitask or "damage_causality" in dimension_gaps)
    ):
        causality_results, causality_failures = run_specialized_frame_pass(
            specialized_case,
            mode="damage_causality_only",
            target_index_key="causality_target_frame_indices",
            chunk_size=max(8, min(int(causality_policy.get("dedicated_chunk_frames") or 20), 24)),
            context_frame_count=max(2, min(int(causality_policy.get("context_frames") or 6), 8)),
            workers=workers,
            invoke=invoke_model,
            repair_attempts=1,
            preserve_partial_coverage=True,
        )
    aggregated = _aggregate_chunk_results(
        specialized_case,
        successful,
        failures,
        continuity_results,
        continuity_failures,
        causality_results,
        causality_failures,
        len(main_frames),
        supplemental_results,
        supplemental_failures,
    )
    chunking = aggregated.setdefault("chunking", {})
    chunking["concurrency"] = concurrency_audit
    chunking["official_reference_segments"] = len(reference_segment_indices)
    chunking["official_reference_model_sends"] = (
        len(case.get("official_reference_images") or []) * len(reference_segment_indices)
    )
    chunking["unified_multitask"] = {
        "enabled": unified_multitask,
        "status": (
            "completed" if unified_multitask and not dimension_gaps
            else "dimension_fallback" if unified_multitask
            else "disabled"
        ),
        "dimension_gaps": dimension_gaps,
    }
    if supplemental_concurrency:
        chunking["supplemental_evidence_pass"]["concurrency"] = supplemental_concurrency
    aggregated["latency_seconds"] = round(time.time() - wall_started, 2)
    return aggregated


def summarize(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_model: Dict[str, List[Dict[str, Any]]] = {}
    for row in results:
        by_model.setdefault(row["model_key"], []).append(row)
    summaries = []
    for key, rows in by_model.items():
        ok_rows = [r for r in rows if r["result"].get("status") == "success"]
        scores = [score_result(r["result"]) for r in rows]
        total_cost = sum(float(((r["result"].get("cost") or {}).get("estimated_usd") or 0)) for r in ok_rows)
        total_original_cost = sum(float(((r["result"].get("cost") or {}).get("amount") or 0)) for r in ok_rows)
        currency = MODEL_CONFIGS[key]["currency"]
        hit_count = sum(1 for r in ok_rows if (r["result"].get("evaluation") or {}).get("hit"))
        structured_count = sum(1 for r in ok_rows if score_result(r["result"])["field_completeness"] >= 0.85 and score_result(r["result"])["evidence_reference_score"] >= 0.67)
        full_success = len(ok_rows) == len(rows) and len(rows) > 0
        eligible = full_success and hit_count == len(rows) and structured_count == len(rows)
        summaries.append(
            {
                "model_key": key,
                "label": MODEL_CONFIGS[key]["label"],
                "success": len(ok_rows),
                "total": len(rows),
                "hit": hit_count,
                "structured": structured_count,
                "hit_rate": round(hit_count / max(len(rows), 1), 3),
                "structured_rate": round(structured_count / max(len(rows), 1), 3),
                "avg_quality": round(sum(s["quality"] for s in scores) / max(len(scores), 1), 2),
                "avg_value": round(sum(s["value"] for s in scores) / max(len(scores), 1), 2),
                "total_cost_usd": round(total_cost, 6),
                "total_cost_amount": round(total_original_cost, 6),
                "currency": currency,
                "total_cost_display": f"{round(total_original_cost, 6)} {currency} / ${round(total_cost, 6)}",
                "avg_latency": round(sum(float(r["result"].get("latency_seconds") or 0) for r in ok_rows) / max(len(ok_rows), 1), 2),
                "eligible_for_recommendation": eligible,
                "exclusion_reason": "" if eligible else "未满足 100% 成功、100% 报告侧命中、100% 结构化完整且证据可回链的 POC 推荐门槛。",
            }
        )
    eligible_summaries = [s for s in summaries if s["eligible_for_recommendation"]]
    recommend_effect = max(eligible_summaries, key=lambda x: (x["avg_quality"], x["hit"], x["structured"], -x["avg_latency"])) if eligible_summaries else None
    recommend_value = sorted(eligible_summaries, key=lambda x: (x["total_cost_usd"], -x["avg_quality"], x["avg_latency"]))[:2]
    return {"models": summaries, "best_effect": recommend_effect, "best_value": recommend_value}


def render_html(report: Dict[str, Any]) -> str:
    def file_uri_to_path(uri: str) -> Optional[Path]:
        parsed = urlparse(str(uri or ""))
        if parsed.scheme != "file":
            return None
        path = unquote(parsed.path)
        if re.match(r"^/[A-Za-z]:", path):
            path = path[1:]
        return Path(path)

    def media_src(uri: str) -> str:
        path = file_uri_to_path(uri)
        if path and path.exists():
            mime = mime_for(path)
            return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"
        return uri

    def money(cost: Dict[str, Any]) -> str:
        if not cost:
            return "-"
        amount = cost.get("amount")
        currency = cost.get("currency")
        usd = cost.get("estimated_usd")
        return f"{h(amount)} {h(currency)} / ${h(usd)}"

    def field_score(result: Dict[str, Any]) -> str:
        score = score_result(result)
        return f"{h(score.get('field_completeness'))} / {h(score.get('evidence_reference_score'))}"

    def model_status(m: Dict[str, Any]) -> str:
        if m.get("eligible_for_recommendation"):
            return "可进入推荐池"
        return m.get("exclusion_reason") or "未进入推荐池"

    summary_rows = "".join(
        "<tr>"
        f"<td><b>{h(m['label'])}</b><br><small>{h(m['model_key'])}</small></td>"
        f"<td>{m['success']}/{m['total']}</td>"
        f"<td>{m['hit']} / {h(m.get('hit_rate'))}</td>"
        f"<td>{m['structured']} / {h(m.get('structured_rate'))}</td>"
        f"<td>{m['avg_quality']}</td>"
        f"<td>{m['avg_value']}</td>"
        f"<td>{h(m.get('total_cost_display') or ('$' + str(m['total_cost_usd'])))}</td>"
        f"<td>{m['avg_latency']}s</td>"
        f"<td>{h(model_status(m))}</td>"
        "</tr>"
        for m in report["summary"]["models"]
    )

    case_packages: Dict[str, Dict[str, Any]] = {}
    for row in report["results"]:
        case_packages.setdefault(
            row["case_id"],
            {
                "case_id": row["case_id"],
                "scenario_label": row["scenario_label"],
                "evidence_package": row["evidence_package"],
            },
        )

    evidence_sections = []
    for case in case_packages.values():
        package = case["evidence_package"]
        video_rows = "".join(
            f"<tr><td>{h(v.get('video_index'))}</td><td>{h(v.get('file'))}</td><td>{h(v.get('duration_seconds'))}s</td><td>{h(v.get('native_fps'))}</td><td>{h(v.get('sampled_frames'))}</td></tr>"
            for v in package.get("videos", [])
        )
        frame_cards = "".join(
            "<figure>"
            f"<a href=\"{h(media_src(f.get('api_uri') or f.get('uri')))}\" target=\"_blank\"><img src=\"{h(media_src(f.get('api_uri') or f.get('uri')))}\" alt=\"{h(f.get('file'))}\"></a>"
            f"<figcaption>视频{h(f.get('video_index'))} · 全局帧{h(f.get('global_frame_index'))} · {h(f.get('timestamp'))}</figcaption>"
            "</figure>"
            for f in package.get("frames", [])
        )
        image_cards = "".join(
            "<figure>"
            f"<a href=\"{h(media_src(i.get('api_uri') or i.get('uri')))}\" target=\"_blank\"><img src=\"{h(media_src(i.get('api_uri') or i.get('uri')))}\" alt=\"{h(i.get('file'))}\"></a>"
            f"<figcaption>补充图{h(i.get('image_index'))} · {h(i.get('file'))}</figcaption>"
            "</figure>"
            for i in package.get("supplemental_images", [])
        )
        evidence_sections.append(
            f"""<details class="case-block" open>
              <summary>{h(case['case_id'])} · {h(case['scenario_label'])} · {h(package.get('frames_sent'))} 帧 / {h(package.get('supplemental_images_sent'))} 张补充图</summary>
              <h3>视频清单</h3>
              <table><thead><tr><th>序号</th><th>文件</th><th>时长</th><th>原生 FPS</th><th>送入帧数</th></tr></thead><tbody>{video_rows}</tbody></table>
              <h3>送入模型的视频帧</h3>
              <div class="media-grid">{frame_cards}</div>
              <h3>送入模型的补充图片</h3>
              <div class="media-grid">{image_cards}</div>
            </details>"""
        )

    detail_rows = []
    for row in report["results"]:
        result = row["result"]
        parsed = result.get("parsed") or {}
        usage = result.get("usage") or {}
        eval_result = result.get("evaluation") or {}
        detail_rows.append(
            "<tr>"
            f"<td>{h(row['case_id'])}<br><small>{h(row['scenario_label'])}</small></td>"
            f"<td><b>{h(MODEL_CONFIGS[row['model_key']]['label'])}</b><br><small>{h(result.get('display_model') or result.get('model'))}</small></td>"
            f"<td>{h(result.get('status'))}</td>"
            f"<td>{h(parsed.get('system_yes_no') or (result.get('policy_decision') or {}).get('system_yes_no'))}</td>"
            f"<td>{h(parsed.get('predicted_label'))}</td>"
            f"<td>{h(parsed.get('confidence'))}</td>"
            f"<td>{h(eval_result.get('hit'))}</td>"
            f"<td>{field_score(result)}</td>"
            f"<td>{h(usage.get('input_tokens'))} / {h(usage.get('output_tokens'))} / {h(usage.get('total_tokens'))}</td>"
            f"<td>{money(result.get('cost') or {})}</td>"
            f"<td>{h(result.get('latency_seconds'))}s</td>"
            f"<td>{h(parsed.get('visual_evidence_verdict') or parsed.get('confidence_reason') or result.get('error'))}</td>"
            "</tr>"
        )
    raw_details = "".join(
        f"""<details>
          <summary>{h(row['case_id'])} / {h(MODEL_CONFIGS[row['model_key']]['label'])} · 模型原始返回与解析</summary>
          <div class="subgrid">
            <div><h3>模型原始文本</h3><pre>{h((row['result'].get('raw_text') or row['result'].get('error') or ''))}</pre></div>
            <div><h3>模型原始解析 JSON</h3><pre>{json_block(row['result'].get('parsed_before_boundary') or {})}</pre></div>
            <div><h3>边界保护后结果</h3><pre>{json_block(row['result'].get('parsed') or {})}</pre></div>
            <div><h3>接口响应摘要</h3><pre>{json_block(row['result'].get('raw_response') or {})}</pre></div>
          </div>
          <details><summary>本次 System Prompt</summary><pre>{h(row['result'].get('system_prompt') or '')}</pre></details>
          <details><summary>本次 User Prompt</summary><pre>{h(row['result'].get('user_prompt') or '')}</pre></details>
        </details>"""
        for row in report["results"]
    )
    best_effect = report["summary"].get("best_effect") or {}
    best_value = report["summary"].get("best_value") or []
    best_value_text = "、".join(m["label"] for m in best_value) if best_value else "暂无满足推荐门槛的模型"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>三大审核模型选型 E2E</title>
  <style>
    :root {{ --ink:#1d2723; --muted:#6f7b74; --line:#dfe7de; --paper:#fffdf7; --wash:#f4f1e8; --accent:#5f7f5d; --deep:#15211d; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:"Microsoft YaHei","Segoe UI",Arial,sans-serif; background:var(--wash); color:var(--ink); }}
    main {{ max-width:1480px; margin:0 auto; padding:26px 16px 64px; }}
    section {{ background:var(--paper); border:1px solid var(--line); border-radius:8px; padding:18px; margin:14px 0; box-shadow:0 12px 30px rgba(35,45,36,.06); }}
    h1 {{ margin:0 0 8px; font-size:30px; letter-spacing:0; }}
    h2 {{ margin:0 0 12px; font-size:20px; letter-spacing:0; }}
    h3 {{ margin:14px 0 8px; font-size:15px; }}
    p, li {{ line-height:1.7; }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; }}
    th,td {{ border-bottom:1px solid var(--line); padding:10px; text-align:left; vertical-align:top; }}
    th {{ background:#ece8dc; color:#26322c; }}
    small,.muted {{ color:var(--muted); }}
    pre {{ white-space:pre-wrap; word-break:break-word; background:var(--deep); color:#edf5ee; padding:12px; border-radius:8px; max-height:520px; overflow:auto; font-size:12px; line-height:1.55; }}
    details {{ border:1px solid var(--line); border-radius:8px; padding:10px 12px; margin:10px 0; background:#fffefa; }}
    summary {{ cursor:pointer; font-weight:700; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:10px; }}
    .subgrid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); gap:12px; }}
    .cell {{ border:1px solid var(--line); border-radius:8px; padding:12px; background:#fbfaf3; }}
    .cell b {{ display:block; margin-top:5px; font-size:18px; }}
    .media-grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(130px,1fr)); gap:10px; }}
    figure {{ margin:0; border:1px solid var(--line); border-radius:8px; overflow:hidden; background:white; }}
    figure img {{ width:100%; aspect-ratio:9/12; object-fit:cover; display:block; }}
    figcaption {{ padding:7px; font-size:12px; color:var(--muted); line-height:1.4; }}
    .table-scroll {{ overflow:auto; }}
    .pill {{ display:inline-block; padding:3px 8px; border-radius:999px; background:#e7ece4; color:#334238; font-size:12px; }}
    @media (max-width:760px) {{ main {{ padding:14px 10px 40px; }} section {{ padding:13px; }} h1 {{ font-size:24px; }} table {{ min-width:900px; }} }}
  </style>
</head>
<body>
<main>
  <section>
    <h1>三大审核模型选型 E2E</h1>
    <p>同一 Case 的多视频已合并为一个证据包；所有候选模型接收同一批抽帧和补充图片。人工标签只在报告侧评测使用，没有进入模型 Prompt。样本量仍小，本报告只能给 POC 选型信号，不代表生产准确率。</p>
    <p><span class="pill">命中定义</span> 命中只表示模型输出的 predicted_label 与报告侧人工标签一致；它不是模型自己给自己的评分，也不是业务裁决。</p>
    <p><span class="pill">成本口径</span> {h(report.get('pricing_note') or '成本为报告侧估算，实际以渠道账单为准。')}</p>
  </section>
  <section>
    <h2>推荐结论</h2>
    <div class="grid">
      <div class="cell"><small>效果最好/最稳候选</small><b>{h(best_effect.get('label') or '暂无满足推荐门槛的模型')}</b></div>
      <div class="cell"><small>性价比最高两个</small><b>{h(best_value_text)}</b></div>
      <div class="cell"><small>策略阈值</small><b>≥{DEFAULT_POLICY['auto_confidence']} 高置信抽检；&lt;{DEFAULT_POLICY['manual_confidence']} 逐条人工</b></div>
      <div class="cell"><small>推荐准入</small><b>100% 成功 + 100% 命中 + 结构化完整</b></div>
    </div>
  </section>
  <section>
    <h2>模型汇总</h2>
    <div class="table-scroll"><table><thead><tr><th>模型</th><th>成功</th><th>命中/命中率</th><th>结构化/完整率</th><th>质量分</th><th>性价比分</th><th>总成本（原币 / USD）</th><th>平均耗时</th><th>推荐状态</th></tr></thead><tbody>{summary_rows}</tbody></table></div>
  </section>
  <section>
    <h2>证据包核对</h2>
    {''.join(evidence_sections)}
  </section>
  <section>
    <h2>逐 Case 结果</h2>
    <div class="table-scroll"><table><thead><tr><th>Case</th><th>模型</th><th>状态</th><th>YES/NO</th><th>标签</th><th>置信度</th><th>命中</th><th>字段/证据回链</th><th>输入/输出/总 tokens</th><th>成本</th><th>耗时</th><th>结论摘要</th></tr></thead><tbody>{''.join(detail_rows)}</tbody></table></div>
  </section>
  <section>
    <h2>原始返回与解析</h2>
    {raw_details}
  </section>
</main>
</body>
</html>"""


def run(args: argparse.Namespace) -> Dict[str, Any]:
    load_env()
    stamp = time.strftime("%Y%m%d_%H%M%S")
    run_dir = TMP_DIR / f"model_selection_{stamp}"
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    sample_dirs = [p for p in sorted(Path(args.samples_dir).iterdir()) if p.is_dir() and p.name.startswith("sample_")]
    model_keys = [m.strip() for m in args.models.split(",") if m.strip() in MODEL_CONFIGS]
    cases = [load_case_bundle(sample_dir, args, run_dir / sample_dir.name) for sample_dir in sample_dirs]
    jobs = []
    for case in cases:
        for model_key in model_keys:
            jobs.append((case, model_key))

    results: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
        future_map = {
            pool.submit(call_model, MODEL_CONFIGS[model_key], case, args.request_timeout, args.soft_retries): (case, model_key)
            for case, model_key in jobs
        }
        for future in as_completed(future_map):
            case, model_key = future_map[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {"status": "failed", "error": sanitize_error_text(exc)}
            results.append(
                {
                    "case_id": case["case_id"],
                    "scenario": case["scenario"],
                    "scenario_label": case["scenario_label"],
                    "model_key": model_key,
                    "result": result,
                    "evidence_package": {
                        "videos": case["videos"],
                        "frames_sent": len(case["frames"]),
                        "frames": [
                            {
                                "global_frame_index": f["global_frame_index"],
                                "video_index": f["video_index"],
                                "video_file": f["video_file"],
                                "timestamp": f["timestamp"],
                                "file": f["file"],
                                "uri": f.get("uri"),
                                "api_uri": Path(f["api_path"]).resolve().as_uri() if f.get("api_path") else f.get("uri"),
                                "api_bytes": f.get("api_bytes"),
                            }
                            for f in case["frames"]
                        ],
                        "supplemental_images_sent": len(case["supplemental_images"]),
                        "supplemental_images": [
                            {
                                "image_index": i["image_index"],
                                "file": i["file"],
                                "fields": i.get("fields", []),
                                "uri": i.get("uri"),
                                "api_uri": Path(i["api_path"]).resolve().as_uri() if i.get("api_path") else i.get("uri"),
                                "api_bytes": i.get("api_bytes"),
                                "width": i.get("width"),
                                "height": i.get("height"),
                                "has_exif": i.get("has_exif"),
                            }
                            for i in case["supplemental_images"]
                        ],
                    },
                }
            )
    results.sort(key=lambda x: (x["case_id"], x["model_key"]))
    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "models": {key: MODEL_CONFIGS[key] for key in model_keys},
        "summary": summarize(results),
        "results": results,
        "pricing_note": PRICING_NOTE,
    }
    json_path = REPORT_DIR / f"visual_model_selection_e2e_{stamp}.json"
    html_path = REPORT_DIR / f"visual_model_selection_e2e_{stamp}.html"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(render_html(report), encoding="utf-8")
    return {"json_report": str(json_path), "html_report": str(html_path), "summary": report["summary"]}


def main() -> int:
    print(json.dumps(run(parse_args()), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
