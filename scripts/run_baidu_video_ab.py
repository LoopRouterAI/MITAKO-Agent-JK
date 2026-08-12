# -*- coding: utf-8 -*-
"""在标签隔离条件下比较百度 Gemini 的三种视频审核链路。"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from poc.visual_review_poc.local_video_triage_demo import format_time, load_env
from poc.visual_review_poc.model_auth import gemini_channel_options
from poc.visual_review_poc.model_catalog import MODEL_CONFIGS
from poc.visual_review_poc.native_video_proxy import prepare_native_video_proxy
from poc.visual_review_poc.secure_media_tunnel import open_secure_media_tunnel
from poc.visual_review_poc.model_selection_e2e import (
    call_model,
    call_model_chunked,
    call_opening_start_verification,
    derive_claim_identity,
    load_case_bundle,
    merge_model_billing,
    merge_opening_start_verification,
    mime_for,
)
from poc.visual_review_poc.specialized_model_pass import run_adaptive_tasks
from poc.visual_review_poc.unified_model_pass import native_dimension_gaps

VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
VIDEO_MIME_TYPES = {
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
}
INLINE_RAW_MEDIA_LIMIT = 70 * 1024 * 1024

PROFILE_DEFINITIONS = {
    "lite-default": ("gemini35lite", None, None),
    "lite-medium": ("gemini35lite", "medium", "high"),
    "lite-high": ("gemini35lite", "high", "high"),
    "flash36-medium": ("gemini36", "medium", "high"),
    "flash36-high": ("gemini36", "high", "high"),
}


def validate_video_sampling_fps(value: float) -> float:
    try:
        fps = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SystemExit("video-fps 必须在 0.1 到 24 之间") from exc
    if not 0.1 <= fps <= 24.0:
        raise SystemExit("video-fps 必须在 0.1 到 24 之间")
    return fps


def apply_perception_evidence_scope(case: Dict[str, Any], scope: str) -> Dict[str, Any]:
    scoped = copy.deepcopy(case)
    if scope == "video-only":
        scoped["frames"] = []
        scoped["supplemental_images"] = []
        identity = (scoped.get("structured_business_context") or {}).get(
            "continuity_claim_identity"
        ) or {}
        identity_refs = {
            str(identity.get(key) or "").strip()
            for key in ("item_ref", "sku")
            if str(identity.get(key) or "").strip()
        }
        matched_references = []
        for image in scoped.get("official_reference_images") or []:
            image_refs = {
                str(image.get(key) or "").strip()
                for key in ("item_ref", "sku")
                if str(image.get(key) or "").strip()
            }
            image_refs.update(
                str(item or "").strip()
                for key in ("item_refs", "skus")
                for item in image.get(key) or []
                if str(item or "").strip()
            )
            if identity_refs.intersection(image_refs):
                matched_references = [image]
                break
        scoped["official_reference_images"] = matched_references
    return scoped


def build_claim_identity_case(case: Dict[str, Any]) -> Dict[str, Any]:
    identity_case = copy.deepcopy(case)
    identity_case.pop("native_video", None)
    identity_case["frames"] = []
    identity_case.setdefault("structured_business_context", {})["analysis_mode"] = (
        "claim_identity_only"
    )
    return identity_case


def _timestamp_seconds(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parts = [float(item) for item in text.split(":")]
    except (TypeError, ValueError, OverflowError):
        return None
    if len(parts) == 2:
        seconds = parts[0] * 60 + parts[1]
    elif len(parts) == 3:
        seconds = parts[0] * 3600 + parts[1] * 60 + parts[2]
    else:
        return None
    return seconds if seconds >= 0 else None


def candidate_detail_window(
    parsed: Dict[str, Any],
    padding_seconds: float = 0.5,
) -> tuple[float, float] | None:
    assessment = parsed.get("claimed_item_assessment") or {}
    candidates = [
        _timestamp_seconds(assessment.get(key))
        for key in ("first_visible_timestamp", "last_visible_timestamp")
    ]
    candidates.extend(
        _timestamp_seconds(item.get("timestamp"))
        for item in parsed.get("evidence_refs") or []
        if isinstance(item, dict) and item.get("field") == "claimed_item"
    )
    timestamps = [item for item in candidates if item is not None]
    if not timestamps:
        return None
    padding = max(0.0, float(padding_seconds))
    return round(max(0.0, min(timestamps) - padding), 3), round(
        max(timestamps) + padding,
        3,
    )


def candidate_detail_timestamps(
    parsed: Dict[str, Any],
    max_candidates: int = 8,
) -> list[float]:
    """保留模型自主发现的离散候选点，避免把间隔很远的候选拼成大窗口。"""
    timestamps = [
        _timestamp_seconds(item.get("timestamp"))
        for item in parsed.get("evidence_refs") or []
        if isinstance(item, dict) and item.get("field") == "claimed_item"
    ]
    values = [round(item, 3) for item in timestamps if item is not None]
    if not values:
        assessment = parsed.get("claimed_item_assessment") or {}
        values = [
            round(item, 3)
            for item in (
                _timestamp_seconds(assessment.get("first_visible_timestamp")),
                _timestamp_seconds(assessment.get("last_visible_timestamp")),
            )
            if item is not None
        ]
    return list(dict.fromkeys(values))[:max(1, int(max_candidates))]


def build_candidate_detail_case(
    case: Dict[str, Any],
    extracted_frames: list[Dict[str, Any]],
) -> Dict[str, Any]:
    detail = apply_perception_evidence_scope(case, "video-only")
    detail.pop("native_video", None)
    detail["frames"] = [
        {
            "video_index": 1,
            "global_frame_index": int(item["frame_index"]),
            "timestamp": format_time(float(item["timestamp_seconds"])),
            "timestamp_seconds": float(item["timestamp_seconds"]),
            "api_path": str(item["path"]),
            "api_mime_type": mime_for(Path(str(item["path"]))),
        }
        for item in extracted_frames
    ]
    detail.setdefault("structured_business_context", {})["analysis_mode"] = (
        "claimed_item_detail_only"
    )
    return detail


def resolved_claim_identity(result: Dict[str, Any]) -> Dict[str, Any]:
    if result.get("status") != "success":
        return {}
    parsed = result.get("parsed") or {}
    if parsed.get("match_status") != "matched":
        return {}
    try:
        confidence = float(parsed.get("confidence") or 0.0)
    except (TypeError, ValueError, OverflowError):
        return {}
    item = parsed.get("expected_order_item") or {}
    if confidence < 0.7 or not item.get("product_name"):
        return {}
    return {
        key: item.get(key)
        for key in ("item_ref", "sku", "product_name", "specification")
        if item.get(key) not in (None, "")
    }


def claim_identity_summary(result: Dict[str, Any]) -> Dict[str, Any]:
    parsed = result.get("parsed") or {}
    return {
        "status": result.get("status"),
        "match_status": parsed.get("match_status"),
        "confidence": parsed.get("confidence"),
        "expected_order_item": parsed.get("expected_order_item") or {},
        "latency_seconds": result.get("latency_seconds"),
        "usage": result.get("usage") or {},
        "estimated_cost": result.get("cost") or {},
    }


def transcoded_url_max_bytes(video: Path, inline_budget: int) -> int:
    """URL 代理不受内联预算约束，但不允许转码后比原片更大。"""
    return max(int(inline_budget), video.stat().st_size)


def resolve_profiles(value: str) -> list[tuple[str, Dict[str, Any]]]:
    names = [item.strip() for item in value.split(",") if item.strip()]
    invalid = [name for name in names if name not in PROFILE_DEFINITIONS]
    if not names or invalid:
        raise SystemExit(f"未知模型参数组合：{', '.join(invalid or names)}")
    profiles = []
    for name in names:
        model_key, thinking_level, media_resolution = PROFILE_DEFINITIONS[name]
        cfg = dict(MODEL_CONFIGS[model_key])
        if thinking_level:
            cfg["thinking_level"] = thinking_level
        else:
            cfg.pop("thinking_level", None)
        if media_resolution:
            cfg["media_resolution"] = media_resolution
        else:
            cfg.pop("media_resolution", None)
        cfg.pop("max_output_tokens", None)
        profiles.append((name, cfg))
    return profiles


def prepare_benchmark_native_source(
    video: Path,
    output_dir: Path,
    max_bytes: int = INLINE_RAW_MEDIA_LIMIT,
    *,
    file_uri: str = "",
    force_proxy: bool = False,
    proxy_profiles: tuple[str, ...] = ("hevc_mp4", "vp9_webm"),
) -> Dict[str, Any]:
    mime_type = VIDEO_MIME_TYPES.get(video.suffix.lower(), "video/mp4")
    if file_uri:
        return {
            "video_index": 1,
            "file_uri": file_uri,
            "api_mime_type": mime_type,
            "transport": "original_signed_url",
        }
    if not force_proxy and video.stat().st_size <= max_bytes:
        return {
            "video_index": 1,
            "api_path": str(video),
            "api_mime_type": mime_type,
            "transport": "raw_inline",
        }
    proxy = prepare_native_video_proxy(
        video,
        output_dir,
        max_bytes,
        profiles=proxy_profiles,
    )
    if proxy.get("status") != "ready":
        error_type = str(proxy.get("error_type") or proxy.get("status") or "unknown")
        raise SystemExit(
            f"整段视频超过内联上限，且完整时长压缩代理生成失败（{error_type}）"
        )
    return {
        "video_index": 1,
        "api_path": str(proxy["path"]),
        "api_mime_type": str(proxy.get("mime_type") or "video/mp4"),
        "transport": "full_duration_transcoded_inline",
        "proxy": proxy,
    }


def signed_proxy_source(source: Dict[str, Any], file_uri: str) -> Dict[str, Any]:
    return {
        "video_index": int(source.get("video_index") or 1),
        "file_uri": file_uri,
        "api_mime_type": str(source.get("api_mime_type") or "video/mp4"),
        "transport": "full_duration_transcoded_url",
        "proxy": dict(source.get("proxy") or {}),
    }


def needs_sampled_frame_case(modes: list[str]) -> bool:
    return any(mode not in {"native", "perception"} for mode in modes)


def needs_native_video_case(modes: list[str]) -> bool:
    return any(mode in {"native", "perception"} for mode in modes)


def prepare_sampled_perception_case(case: Dict[str, Any]) -> Dict[str, Any]:
    prepared = copy.deepcopy(case)
    prepared.pop("native_video", None)
    prepared.setdefault("structured_business_context", {})["analysis_mode"] = (
        "sampled_video_perception"
    )
    return prepared


def bind_perception_identity(case: Dict[str, Any], parsed: Dict[str, Any]) -> None:
    """把完整视频自主识别出的争议商品身份传给后续抽帧回退。"""
    assessment = parsed.get("claimed_item_assessment") or {}
    if assessment.get("appeared") is not True:
        return
    identity = case.setdefault("structured_business_context", {}).setdefault(
        "continuity_claim_identity",
        {},
    )
    for key in (
        "identity_description",
        "identity_anchor_asset_ref",
        "identity_confidence",
        "first_visible_timestamp",
        "last_visible_timestamp",
    ):
        value = assessment.get(key)
        if value not in (None, "", [], {}):
            identity[key] = copy.deepcopy(value)


def _resolved_identity_anchor(
    case: Dict[str, Any],
) -> tuple[str, Dict[str, Any], str] | None:
    identity = (case.get("structured_business_context") or {}).get(
        "continuity_claim_identity"
    ) or {}
    requested = str(identity.get("identity_anchor_asset_ref") or "").strip()
    if not requested:
        return None
    for image in case.get("supplemental_images") or []:
        asset_ref = f"supplemental_image_{image.get('image_index')}"
        if asset_ref == requested:
            return "supplemental", image, asset_ref
    for image in case.get("official_reference_images") or []:
        asset_ref = f"official_product_reference_{image.get('reference_index')}"
        if asset_ref == requested:
            return "official", image, asset_ref
    return None


def build_overlapping_frame_batches(
    frames: list[Dict[str, Any]],
    *,
    batch_size: int = 16,
    overlap: int = 2,
) -> list[list[Dict[str, Any]]]:
    size = max(2, min(int(batch_size), 24))
    overlap_count = max(0, min(int(overlap), size - 1))
    batches: list[list[Dict[str, Any]]] = []
    start = 0
    while start < len(frames):
        end = min(len(frames), start + size)
        batches.append(list(frames[start:end]))
        if end >= len(frames):
            break
        start = end - overlap_count
    return batches


def prepare_sampled_batch_case(
    case: Dict[str, Any],
    frames: list[Dict[str, Any]],
    *,
    batch_index: int,
    total_batches: int,
    overlap: int,
) -> Dict[str, Any]:
    if not frames:
        raise ValueError("sampled_frame_batch_cannot_be_empty")
    prepared = copy.deepcopy(case)
    prepared.pop("native_video", None)
    prepared["frames"] = list(frames)
    media_slots = max(0, 24 - len(frames))
    resolved_anchor = _resolved_identity_anchor(prepared)
    identity_anchor_asset_ref = ""
    if media_slots and resolved_anchor and resolved_anchor[0] == "supplemental":
        prepared["supplemental_images"] = [copy.deepcopy(resolved_anchor[1])]
        prepared["official_reference_images"] = []
        identity_anchor_asset_ref = resolved_anchor[2]
    elif media_slots and resolved_anchor and resolved_anchor[0] == "official":
        prepared["supplemental_images"] = []
        prepared["official_reference_images"] = [copy.deepcopy(resolved_anchor[1])]
        identity_anchor_asset_ref = resolved_anchor[2]
    else:
        prepared["supplemental_images"] = []
        prepared["official_reference_images"] = []
    prepared.setdefault("structured_business_context", {}).update({
        "analysis_mode": "sampled_video_batch_observation",
        "sampled_frame_batch": {
            "index": int(batch_index),
            "total": int(total_batches),
            "start_frame_index": int(frames[0].get("global_frame_index") or 0),
            "end_frame_index": int(frames[-1].get("global_frame_index") or 0),
            "start_timestamp": str(frames[0].get("timestamp") or ""),
            "end_timestamp": str(frames[-1].get("timestamp") or ""),
            "overlap_frames": max(0, int(overlap)),
            "identity_anchor_asset_ref": identity_anchor_asset_ref,
            "identity_anchor_role": "identity_only" if identity_anchor_asset_ref else "none",
        },
    })
    return prepared


def prepare_sampled_reduce_case(
    case: Dict[str, Any],
    batch_results: list[Dict[str, Any]],
) -> Dict[str, Any]:
    prepared = copy.deepcopy(case)
    prepared.pop("native_video", None)
    frame_by_ref = {
        f"video_{frame.get('video_index')}_frame_{frame.get('global_frame_index')}": frame
        for frame in prepared.get("frames") or []
    }
    candidate_refs = []
    for row in batch_results:
        parsed = row.get("parsed") or {}
        assessment = parsed.get("claimed_item_assessment") or {}
        refs = [assessment.get("identity_anchor_asset_ref")]
        refs.extend(
            item.get("asset_ref")
            for item in parsed.get("evidence_refs") or []
            if isinstance(item, dict) and item.get("field") == "claimed_item"
        )
        candidate_refs.extend(
            str(ref)
            for ref in refs
            if ref and str(ref) in frame_by_ref
        )
    candidate_refs = list(dict.fromkeys(candidate_refs))[:12]
    prepared["frames"] = [frame_by_ref[ref] for ref in candidate_refs]
    media_slots = max(0, 24 - len(prepared["frames"]))
    resolved_anchor = _resolved_identity_anchor(prepared)
    prepared["supplemental_images"] = []
    prepared["official_reference_images"] = []
    if candidate_refs and media_slots and resolved_anchor:
        target_key = (
            "supplemental_images"
            if resolved_anchor[0] == "supplemental"
            else "official_reference_images"
        )
        prepared[target_key] = [copy.deepcopy(resolved_anchor[1])]
    prepared.setdefault("structured_business_context", {}).update({
        "analysis_mode": "sampled_video_perception_reduce",
        "sampled_batch_results": copy.deepcopy(batch_results),
        "sampled_reduce_candidate_frame_refs": candidate_refs,
    })
    return prepared


def run_sampled_perception_batched(
    cfg: Dict[str, Any],
    case: Dict[str, Any],
    *,
    timeout: int,
    retries: int,
    batch_size: int = 16,
    overlap: int = 2,
    workers: int = 4,
) -> Dict[str, Any]:
    wall_started = time.time()
    has_identity_anchor = _resolved_identity_anchor(case) is not None
    effective_batch_size = min(int(batch_size), 23) if has_identity_anchor else int(batch_size)
    batches = build_overlapping_frame_batches(
        list(case.get("frames") or []),
        batch_size=effective_batch_size,
        overlap=overlap,
    )
    if not batches:
        return {
            "status": "failed",
            "error": "sampled_frame_timeline_empty",
            "cost_status": "not_incurred",
            "batching": {"segment_count": 0, "total_model_calls": 0},
        }

    def observe(item: tuple[int, list[Dict[str, Any]]]) -> Dict[str, Any]:
        index, frames = item
        current = prepare_sampled_batch_case(
            case,
            frames,
            batch_index=index + 1,
            total_batches=len(batches),
            overlap=overlap,
        )
        result = call_model(cfg, current, timeout=timeout, retries=retries)
        result["_sampled_batch"] = {
            **current["structured_business_context"]["sampled_frame_batch"],
            "input_frame_indices": [
                int(frame.get("global_frame_index") or 0) for frame in frames
            ],
            "model_media_parts": native_media_part_count(current),
        }
        return result

    completed, concurrency = run_adaptive_tasks(
        list(enumerate(batches)),
        workers=max(1, min(int(workers), 4, len(batches))),
        invoke=observe,
    )
    failed = [item for item in completed if item.get("status") != "success"]
    if failed:
        merged = merge_model_billing(completed[0], completed[1:])
        merged.update({
            "status": "failed",
            "error": "sampled_batch_observation_failed",
            "latency_seconds": round(time.time() - wall_started, 2),
            "batching": {
                "segment_count": len(batches),
                "completed_segments": len(completed) - len(failed),
                "failed_segments": [
                    (item.get("_sampled_batch") or {}).get("index") for item in failed
                ],
                "batch_size": effective_batch_size,
                "overlap_frames": int(overlap),
                "total_model_calls": len(completed),
                "input_representation": "individual_1080p_frames",
                "concurrency": concurrency,
            },
        })
        return merged

    rows = []
    for result in completed:
        metadata = result.get("_sampled_batch") or {}
        rows.append({
            "batch_index": metadata.get("index"),
            "batch_total": metadata.get("total"),
            "start_frame_index": metadata.get("start_frame_index"),
            "end_frame_index": metadata.get("end_frame_index"),
            "start_timestamp": metadata.get("start_timestamp"),
            "end_timestamp": metadata.get("end_timestamp"),
            "input_frame_indices": metadata.get("input_frame_indices") or [],
            "parsed": result.get("parsed") or {},
        })
    rows.sort(key=lambda item: int(item.get("batch_index") or 0))
    reduce_case = prepare_sampled_reduce_case(case, rows)
    reduced = call_model(cfg, reduce_case, timeout=timeout, retries=retries)
    merged = merge_model_billing(reduced, completed)
    merged["batch_results"] = rows
    merged["request_ids"] = [
        request_id
        for item in [*completed, reduced]
        for request_id in [(item.get("raw_response") or {}).get("id")]
        if request_id
    ]
    merged["latency_seconds"] = round(time.time() - wall_started, 2)
    merged["batching"] = {
        "segment_count": len(batches),
        "completed_segments": len(completed),
        "failed_segments": [],
        "batch_size": effective_batch_size,
        "overlap_frames": int(overlap),
        "total_model_calls": len(completed) + 1,
        "input_representation": "individual_1080p_frames",
        "model_media_parts": sum(
            int((item.get("_sampled_batch") or {}).get("model_media_parts") or 0)
            for item in completed
        ),
        "identity_anchor_model_sends": sum(
            bool((item.get("_sampled_batch") or {}).get("identity_anchor_asset_ref"))
            for item in completed
        ),
        "concurrency": concurrency,
        "reducer_media_parts": native_media_part_count(reduce_case),
    }
    return merged


def native_media_part_count(case: Dict[str, Any]) -> int:
    return (
        (1 if case.get("native_video") else 0)
        + len(case.get("frames") or [])
        + len(case.get("supplemental_images") or [])
        + len(case.get("official_reference_images") or [])
    )


def result_summary(result: Dict[str, Any], *, native_media_parts: int = 0) -> Dict[str, Any]:
    parsed = result.get("parsed") or {}
    raw_parsed = result.get("parsed_before_boundary") or parsed
    chunking = result.get("chunking") or {}
    channels = chunking.get("channels") or {}
    model_calls = chunking.get("total_model_calls")
    if model_calls is None:
        model_calls = 1 if result.get("status") == "success" else 0
    opening_verification = result.get("opening_start_verification") or {}
    opening_incurred = 1 if opening_verification.get("status") not in {None, "skipped"} else 0
    model_calls = int(model_calls or 0) + opening_incurred
    model_media_parts = sum(
        int((value or {}).get("model_images") or 0)
        for value in channels.values()
        if isinstance(value, dict)
    ) or native_media_parts
    overall = raw_parsed.get("overall_audit") or {}
    findings = raw_parsed.get("frame_findings") or []
    continuity = raw_parsed.get("object_continuity_assessment") or {}
    video_audit = raw_parsed.get("video_audit_conclusion") or {}
    opening = video_audit.get("opening_video_compliance") or {}
    damage = raw_parsed.get("damage_causality_assessment") or {}
    claim_facts = raw_parsed.get("claim_fact_assessment") or {}
    required_dimensions = {
        "overall_audit": isinstance(overall, dict) and bool(overall.get("conclusion")),
        "frame_findings": isinstance(findings, list) and any(
            isinstance(item, dict) and item.get("timestamp") and item.get("visible_facts")
            for item in findings
        ),
        "object_continuity": (
            isinstance(continuity, dict)
            and bool(continuity.get("continuity_verdict"))
            and bool(continuity.get("tracked_subjects"))
        ),
        "opening_video_compliance": (
            isinstance(opening, dict)
            and all(isinstance(opening.get(field), bool) for field in (
                "sealed_start", "waybill_visible", "single_take_continuity"
            ))
            and "issue_visible_in_continuous_opening" in opening
            and opening.get("result") in {"compliant", "noncompliant", "indeterminate"}
        ),
        "damage_causality": (
            isinstance(damage, dict)
            and bool(damage.get("damage_presence"))
            and bool(damage.get("claim_support"))
        ),
        "claim_facts": (
            isinstance(claim_facts, dict)
            and isinstance(claim_facts.get("atomic_claim_results"), list)
            and isinstance(claim_facts.get("order_linkage"), dict)
            and isinstance(claim_facts.get("scene_match"), dict)
            and isinstance(claim_facts.get("assembly"), dict)
        ),
    }


    raw_response = result.get("raw_response") or {}
    usage = dict(result.get("usage") or {})
    opening_usage = opening_verification.get("usage") or {}
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        usage[key] = int(usage.get(key) or 0) + int(opening_usage.get(key) or 0)
    cost = dict(result.get("cost") or {})
    opening_cost = opening_verification.get("cost") or {}
    if cost or opening_cost:
        cost["estimated_usd"] = round(
            float(cost.get("estimated_usd") or 0) + float(opening_cost.get("estimated_usd") or 0),
            6,
        )
        if cost.get("currency") == opening_cost.get("currency") and cost.get("amount") is not None:
            cost["amount"] = round(float(cost.get("amount") or 0) + float(opening_cost.get("amount") or 0), 6)
    total_latency = round(
        float(result.get("latency_seconds") or 0) + float(opening_verification.get("latency_seconds") or 0),
        2,
    )
    return {
        "status": result.get("status"),
        "status_code": result.get("status_code"),
        "error_type": result.get("error_type"),
        "error": result.get("error"),
        "attempts": result.get("attempts") or [],
        "model_output_before_guards": raw_parsed,
        "model_output_after_guards": parsed,
        "predicted_label_after_guards": parsed.get("predicted_label"),
        "predicted_label_before_guards": raw_parsed.get("predicted_label"),
        "confidence_after_guards": parsed.get("confidence"),
        "dimension_completeness": required_dimensions,
        "complete_dimension_count": sum(required_dimensions.values()),
        "opening_video_compliance": {
            field: opening.get(field)
            for field in (
                "sealed_start",
                "waybill_visible",
                "single_take_continuity",
                "issue_visible_in_continuous_opening",
                "result",
            )
        },
        "model_calls": model_calls,
        "model_media_parts": model_media_parts,
        "wall_seconds": total_latency,
        "model_latency_seconds_sum": result.get("model_latency_seconds_sum") or total_latency,
        "usage": usage,
        "estimated_cost": cost,
        "request_ids": [raw_response["id"]] if raw_response.get("id") else [],
        "route_attempts": (result.get("_channel_route_attempts") or []) + (opening_verification.get("_channel_route_attempts") or []),
        "opening_start_verification": {
            "status": opening_verification.get("status") or "not_run",
            "latency_seconds": opening_verification.get("latency_seconds"),
        },
        "unified_multitask": chunking.get("unified_multitask") or {},
        "guard_effect": {
            "continuity": parsed.get("continuity_guard_reason"),
            "causality": parsed.get("causality_guard_reason"),
        },
    }


PERCEPTION_REQUIRED_FIELDS = (
    "sealed_start",
    "waybill_visible",
    "continuous",
    "has_edit",
    "has_offscreen",
    "has_speed_change",
    "all_items_shown",
    "issue_visible",
    "overall_video_result",
    "claimed_item_assessment",
    "speed_assessment",
    "damage_assessment",
    "evidence_refs",
)


def perception_result_summary(result: Dict[str, Any]) -> Dict[str, Any]:
    parsed = result.get("parsed") or {}
    raw_parsed = result.get("parsed_before_boundary") or parsed
    completeness = {
        field: field in parsed
        for field in PERCEPTION_REQUIRED_FIELDS
    }
    candidates = (result.get("raw_response") or {}).get("candidates") or []
    finish_reason = (
        candidates[0].get("finishReason")
        if candidates and isinstance(candidates[0], dict)
        else None
    )
    status = result.get("status")
    if status == "success" and not all(completeness.values()):
        status = "invalid_output"
    return {
        "status": status,
        "status_code": result.get("status_code"),
        "error_type": result.get("error_type"),
        "error": result.get("error"),
        "attempts": result.get("attempts") or [],
        "finish_reason": finish_reason,
        "model_output_before_guards": raw_parsed,
        "model_output_after_guards": parsed,
        "field_completeness": completeness,
        "complete_field_count": sum(completeness.values()),
        "model_calls": int(
            ((result.get("batching") or {}).get("total_model_calls"))
            or (1 if result.get("status") == "success" else 0)
        ),
        "model_media_parts": 0,
        "wall_seconds": result.get("latency_seconds") or 0,
        "model_latency_seconds_sum": (
            result.get("model_latency_seconds_sum")
            or result.get("latency_seconds")
            or 0
        ),
        "usage": result.get("usage") or {},
        "estimated_cost": result.get("cost") or {},
        "request_ids": result.get("request_ids") or ([
            (result.get("raw_response") or {}).get("id")
        ] if (result.get("raw_response") or {}).get("id") else []),
        "route_attempts": result.get("_channel_route_attempts") or [],
        "batch_results": result.get("batch_results") or [],
    }


def write_checkpoint(path: Path, report: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="百度 Gemini 视频审核链路真实 A/B")
    parser.add_argument("--case-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--modes", default="unified,native,legacy")
    parser.add_argument(
        "--profiles",
        default="lite-default",
        help="逗号分隔：lite-default,lite-medium,lite-high,flash36-medium,flash36-high",
    )
    parser.add_argument(
        "--transport",
        choices=("auto", "url", "proxy"),
        default="auto",
        help="auto：小文件原片内联、大文件原片 URL；url：强制原片 URL；proxy：显式保真转码回退",
    )
    parser.add_argument("--cloudflared", default="", help="cloudflared 可执行文件路径")
    parser.add_argument(
        "--proxy-profiles",
        default="hevc_mp4,vp9_webm",
        help="显式 proxy 模式编码顺序：hevc_mp4,vp9_webm",
    )
    parser.add_argument("--request-timeout", type=int, default=1800)
    parser.add_argument("--sampled-batch-size", type=int, default=23)
    parser.add_argument("--sampled-batch-overlap", type=int, default=1)
    parser.add_argument("--sampled-workers", type=int, default=4)
    parser.add_argument(
        "--video-fps",
        type=float,
        default=1.0,
        help="Gemini 完整视频采样帧率；模型选型建议依次验证 1、2、4 FPS",
    )
    parser.add_argument(
        "--evidence-scope",
        choices=("combined", "video-only"),
        default="combined",
        help="perception 模式的媒体范围；video-only 用于隔离补图串型风险",
    )
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    modes = [item.strip() for item in args.modes.split(",") if item.strip()]
    allowed_modes = {
        "legacy", "unified", "native", "perception",
        "sampled-perception", "sampled-batched",
    }
    if not modes or any(item not in allowed_modes for item in modes):
        raise SystemExit(
            "modes 只能包含 legacy、unified、native、perception、"
            "sampled-perception、sampled-batched"
        )
    load_env()
    cloudflared_executable = (
        args.cloudflared.strip()
        or os.getenv("CLOUDFLARED_PATH", "").strip()
        or "cloudflared"
    )
    request_timeout = max(30, min(int(args.request_timeout), 1800))
    sampled_batch_size = max(2, min(int(args.sampled_batch_size), 24))
    sampled_batch_overlap = max(
        0,
        min(int(args.sampled_batch_overlap), sampled_batch_size - 1),
    )
    sampled_workers = max(1, min(int(args.sampled_workers), 4))
    video_sampling_fps = validate_video_sampling_fps(args.video_fps)
    proxy_profiles = tuple(
        item.strip() for item in args.proxy_profiles.split(",") if item.strip()
    )
    if not proxy_profiles or any(
        item not in {"hevc_mp4", "vp9_webm"} for item in proxy_profiles
    ):
        raise SystemExit("proxy-profiles 只能包含 hevc_mp4、vp9_webm")
    profiles = resolve_profiles(args.profiles)
    for _, cfg in profiles:
        channels = gemini_channel_options(cfg["model"])
        if not channels or channels[0].get("channel") != "baidu":
            raise SystemExit(f"百度 Gemini 通道未处于首选可用状态：{cfg['model']}")

    report: Dict[str, Any] = {
        "experiment": "baidu_gemini_video_ab_v1",
        "label_isolation": "推理阶段只读取盲测包；人工标签和原始答卷不进入模型请求。",
        "case_dir": args.case_dir.name,
        "provider": "baidu",
        "perception_evidence_scope": args.evidence_scope,
        "profiles": {
            name: {
                "model": cfg["model"],
                "thinking_level": cfg.get("thinking_level") or "model_default",
                "media_resolution": cfg.get("media_resolution") or "model_default",
            }
            for name, cfg in profiles
        },
        "sampled_batched": {
            "fps": 1.0,
            "max_long_edge": 1920,
            "batch_size": sampled_batch_size,
            "overlap_frames": sampled_batch_overlap,
            "max_workers": sampled_workers,
            "image_layout": "individual_media_parts",
        },
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "results": {},
    }
    if args.resume and args.output.exists():
        report = json.loads(args.output.read_text(encoding="utf-8"))

    run_parent = ROOT / "tmp" / "baidu_video_ab"
    run_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=run_parent) as temp_dir, ExitStack() as transport_stack:
        bundle_args = SimpleNamespace(
            fps=1.0,
            sampling_mode="dense",
            max_frames_per_video=1200,
            api_frame_limit=24,
            probe_seconds=12.0,
            frame_width=1920,
            supplemental_image_limit=48,
        )
        video_paths = sorted(
            path for path in args.case_dir.iterdir()
            if path.is_file() and path.suffix.lower() in VIDEO_SUFFIXES
        )
        if needs_native_video_case(modes) and len(video_paths) != 1:
            raise SystemExit("原生视频 A/B 当前只接受恰好一个视频的盲测包")
        native_source: Dict[str, Any] = {}
        native_case: Dict[str, Any] | None = None
        tunnel_diagnostics: Dict[str, Any] = {}
        native_preparation_seconds = 0.0
        if needs_native_video_case(modes):
            native_preparation_started = time.time()
            video_path = video_paths[0]
            native_budget = 55 * 1024 * 1024
            use_url = args.transport == "url" or (
                args.transport == "auto" and video_path.stat().st_size > native_budget
            )
            file_uri = ""
            if use_url:
                tunnel = transport_stack.enter_context(
                    open_secure_media_tunnel(
                        video_path,
                        cloudflared_executable=cloudflared_executable,
                        startup_timeout=60.0,
                    )
                )
                file_uri = tunnel.url
                tunnel_diagnostics = tunnel.diagnostics
                native_source = prepare_benchmark_native_source(
                    video_path,
                    Path(temp_dir) / "native_proxy",
                    native_budget,
                    file_uri=file_uri,
                )
            elif args.transport == "proxy":
                proxy_source = prepare_benchmark_native_source(
                    video_path,
                    Path(temp_dir) / "native_proxy",
                    transcoded_url_max_bytes(video_path, native_budget),
                    force_proxy=True,
                    proxy_profiles=proxy_profiles,
                )
                tunnel = transport_stack.enter_context(
                    open_secure_media_tunnel(
                        Path(proxy_source["api_path"]),
                        cloudflared_executable=cloudflared_executable,
                        startup_timeout=60.0,
                    )
                )
                native_source = signed_proxy_source(proxy_source, tunnel.url)
                tunnel_diagnostics = tunnel.diagnostics
            else:
                native_source = prepare_benchmark_native_source(
                    video_path,
                    Path(temp_dir) / "native_proxy",
                    native_budget,
                )
            native_source["sampling_fps"] = video_sampling_fps
            native_case = load_case_bundle(
                args.case_dir,
                bundle_args,
                Path(temp_dir) / "native",
                scenario_override="product_damage",
                native_video=native_source,
            )
            native_preparation_seconds = round(
                time.time() - native_preparation_started,
                2,
            )
        case: Dict[str, Any] | None = None
        sampled_preparation_seconds = 0.0
        if needs_sampled_frame_case(modes):
            sampled_preparation_started = time.time()
            case = load_case_bundle(
                args.case_dir,
                bundle_args,
                Path(temp_dir) / "sampled",
                scenario_override="product_damage",
            )
            sampled_preparation_seconds = round(
                time.time() - sampled_preparation_started,
                2,
            )
            sampled_media_bytes = sum(
                Path(item["api_path"]).stat().st_size
                for key in ("frames", "supplemental_images", "official_reference_images")
                for item in case.get(key) or []
            )
            if (
                sampled_media_bytes > INLINE_RAW_MEDIA_LIMIT
                and "sampled-perception" in modes
            ):
                raise SystemExit("完整 1 FPS 抽帧与图片的 Base64 载荷超过请求安全线")
        else:
            sampled_media_bytes = 0
        seed_case = native_case or case
        if seed_case is None:
            raise SystemExit("没有可用于实验的证据包")
        structured = dict(seed_case.get("structured_business_context") or {})
        structured.update({
            "business_scenario": "product_damage",
            "continuity_policy": {
                "out_of_frame_warning_seconds": 2.0,
                "force_dense_scan": True,
                "scan_fps": 1.0,
                "require_identity_reestablishment": True,
            },
            "damage_causality_policy": {
                "force_action_scan": True,
                "dedicated_chunk_frames": 20,
                "context_frames": 6,
            },
        })
        structured["continuity_claim_identity"] = derive_claim_identity([], seed_case)
        if case is not None:
            case["structured_business_context"] = copy.deepcopy(structured)
        native_media_bytes = 0
        if native_case is not None:
            native_case["structured_business_context"] = copy.deepcopy(structured)
            native_case["structured_business_context"]["native_video_review"] = {"enabled": True}
            inline_image_bytes = sum(
                Path(item["api_path"]).stat().st_size
                for key in ("frames", "supplemental_images", "official_reference_images")
                for item in native_case.get(key) or []
            )
            inline_video_bytes = (
                Path(native_source["api_path"]).stat().st_size
                if native_source.get("api_path")
                else 0
            )
            native_media_bytes = inline_video_bytes + inline_image_bytes
            if native_media_bytes > INLINE_RAW_MEDIA_LIMIT:
                raise SystemExit("视频与图片的 Base64 载荷仍超过请求安全线")
        report["evidence"] = {
            "video_count": len(video_paths),
            "sampled_frame_count": len((case or {}).get("frames") or []),
            "sampled_raw_media_bytes": sampled_media_bytes,
            "native_start_anchor_count": sum(
                item.get("selection_role") == "opening_anchor"
                for item in (native_case or {}).get("frames") or []
            ),
            "native_detail_frame_count": sum(
                item.get("selection_role") == "transition_settle_detail"
                for item in (native_case or {}).get("frames") or []
            ),
            "supplemental_image_count": len(seed_case.get("supplemental_images") or []),
            "official_reference_count": len(seed_case.get("official_reference_images") or []),
            "native_raw_media_bytes": native_media_bytes,
            "native_source_bytes": video_paths[0].stat().st_size if video_paths else 0,
            "native_transport": native_source.get("transport"),
            "native_video_sampling_fps": native_source.get("sampling_fps"),
            "native_proxy": native_source.get("proxy"),
            "native_tunnel": tunnel_diagnostics,
            "native_preparation_seconds": native_preparation_seconds,
            "sampled_preparation_seconds": sampled_preparation_seconds,
        }

        for profile_name, cfg in profiles:
            for mode in modes:
                result_key = f"{profile_name}:{mode}"
                if args.resume and (report.get("results") or {}).get(result_key, {}).get("status") == "success":
                    if mode == "perception" and case is not None:
                        bind_perception_identity(
                            case,
                            report["results"][result_key].get("model_output_after_guards") or {},
                        )
                    continue
                started = time.time()
                current = copy.deepcopy(
                    native_case if mode in {"native", "perception"} else case
                )
                if current is None:
                    raise RuntimeError(f"缺少 {mode} 实验输入")
                if mode == "perception":
                    current = apply_perception_evidence_scope(
                        current,
                        args.evidence_scope,
                    )
                    current["structured_business_context"]["analysis_mode"] = (
                        "native_video_perception"
                    )
                    result = call_model(cfg, current, timeout=request_timeout, retries=1)
                    if case is not None and result.get("status") == "success":
                        bind_perception_identity(case, result.get("parsed") or {})
                    summary = perception_result_summary(result)
                    summary["model_media_parts"] = native_media_part_count(current)
                    summary["model_calls"] = 1 if result.get("status") not in {
                        "", "skipped", "not_run", "not_incurred"
                    } else 0
                    summary["pipeline_mode"] = "single_complete_video_call"
                elif mode == "sampled-perception":
                    current = prepare_sampled_perception_case(current)
                    result = call_model(cfg, current, timeout=request_timeout, retries=1)
                    summary = perception_result_summary(result)
                    summary["model_media_parts"] = native_media_part_count(current)
                    summary["model_calls"] = 1 if result.get("status") not in {
                        "", "skipped", "not_run", "not_incurred"
                    } else 0
                    summary["pipeline_mode"] = "single_full_timeline_1fps_frame_call"
                elif mode == "sampled-batched":
                    result = run_sampled_perception_batched(
                        cfg,
                        current,
                        timeout=request_timeout,
                        retries=1,
                        batch_size=sampled_batch_size,
                        overlap=sampled_batch_overlap,
                        workers=sampled_workers,
                    )
                    summary = perception_result_summary(result)
                    batching = result.get("batching") or {}
                    summary["model_media_parts"] = int(
                        batching.get("model_media_parts") or 0
                    )
                    summary["model_calls"] = int(
                        batching.get("total_model_calls") or 0
                    )
                    summary["pipeline_mode"] = (
                        "parallel_overlapping_1fps_observation_then_single_reduce"
                    )
                    summary["batching"] = batching
                elif mode == "native":
                    result = call_model(cfg, current, timeout=request_timeout, retries=1)
                    native_gaps = native_dimension_gaps(result.get("parsed") or {}, "product_damage")
                    if (
                        result.get("status") == "success"
                        and set(native_gaps).issubset({"opening_start_verification", "opening_video_hard_failure_candidate"})
                    ):
                        opening_verification = call_opening_start_verification(
                            cfg,
                            current,
                            timeout=request_timeout,
                            retries=1,
                        )
                        result = merge_opening_start_verification(
                            result,
                            opening_verification,
                            current.get("frames") or [],
                            scenario="product_damage",
                        )
                    summary = result_summary(
                        result,
                        native_media_parts=(
                            native_media_part_count(current)
                            + (
                                len(current.get("frames") or [])
                                if (result.get("opening_start_verification") or {}).get("status") not in {None, "skipped"}
                                else 0
                            )
                        ),
                    )
                else:
                    result = call_model_chunked(
                        {**cfg, "unified_multitask": mode == "unified"},
                        current,
                        timeout=request_timeout,
                        retries=1,
                    )
                    summary = result_summary(result)
                summary["profile"] = profile_name
                summary["process_wall_seconds"] = round(time.time() - started, 2)
                report.setdefault("results", {})[result_key] = summary
                write_checkpoint(args.output, report)
                print(json.dumps({"profile": profile_name, "mode": mode, **summary}, ensure_ascii=False))

    report["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S %z")
    write_checkpoint(args.output, report)
    expected = [f"{profile_name}:{mode}" for profile_name, _ in profiles for mode in modes]
    return 0 if all((report["results"].get(key) or {}).get("status") == "success" for key in expected) else 1


if __name__ == "__main__":
    raise SystemExit(main())
