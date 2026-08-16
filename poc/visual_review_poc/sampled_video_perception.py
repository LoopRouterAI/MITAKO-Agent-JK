"""商品有伤的 1 FPS 帧序列回退：并发观察事实，再统一归并。"""
from __future__ import annotations

import copy
import time
from typing import Any, Callable, Dict, List

from poc.visual_review_poc.native_video_perception import expand_native_video_perception
from poc.visual_review_poc.specialized_model_pass import run_adaptive_tasks

CLAIMED_ITEM_EVIDENCE_FIELDS = {
    "claimed_item",
    "claimed_item_assessment",
    "claimed_item_assessment.appeared",
}


def is_claimed_item_evidence_field(value: Any) -> bool:
    """兼容供应商返回的对象路径字段，并统一视为争议商品证据。"""
    return str(value or "").strip() in CLAIMED_ITEM_EVIDENCE_FIELDS


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
    frames: List[Dict[str, Any]],
    *,
    batch_size: int = 16,
    overlap: int = 2,
) -> List[List[Dict[str, Any]]]:
    """保持全局顺序，并用少量重叠帧避免批次边界丢失动作。"""
    size = max(2, min(int(batch_size), 24))
    overlap_count = max(0, min(int(overlap), size - 1))
    batches: List[List[Dict[str, Any]]] = []
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
    frames: List[Dict[str, Any]],
    *,
    batch_index: int,
    total_batches: int,
    overlap: int,
) -> Dict[str, Any]:
    if not frames:
        raise ValueError("sampled_frame_batch_cannot_be_empty")
    prepared = copy.deepcopy(case)
    prepared.pop("native_video", None)
    prepared.pop("native_videos", None)
    prepared["frames"] = list(frames)
    media_slots = max(0, 24 - len(frames))
    anchor = _resolved_identity_anchor(prepared)
    anchor_ref = ""
    prepared["supplemental_images"] = []
    prepared["official_reference_images"] = []
    if media_slots and anchor:
        target = (
            "supplemental_images" if anchor[0] == "supplemental"
            else "official_reference_images"
        )
        prepared[target] = [copy.deepcopy(anchor[1])]
        anchor_ref = anchor[2]
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
            "identity_anchor_asset_ref": anchor_ref,
            "identity_anchor_role": "identity_only" if anchor_ref else "none",
        },
    })
    return prepared


def prepare_sampled_reduce_case(
    case: Dict[str, Any],
    batch_results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    prepared = copy.deepcopy(case)
    prepared.pop("native_video", None)
    prepared.pop("native_videos", None)
    frame_by_ref = {
        f"video_{frame.get('video_index')}_frame_{frame.get('global_frame_index')}": frame
        for frame in prepared.get("frames") or []
    }
    candidate_refs: List[str] = []
    for row in batch_results:
        parsed = row.get("parsed") or {}
        assessment = parsed.get("claimed_item_assessment") or {}
        refs = [assessment.get("identity_anchor_asset_ref")]
        refs.extend(
            item.get("asset_ref")
            for item in parsed.get("evidence_refs") or []
            if isinstance(item, dict)
            and is_claimed_item_evidence_field(item.get("field"))
        )
        candidate_refs.extend(
            str(ref) for ref in refs if ref and str(ref) in frame_by_ref
        )
    candidate_refs = list(dict.fromkeys(candidate_refs))[:12]
    prepared["frames"] = [frame_by_ref[ref] for ref in candidate_refs]
    anchor = _resolved_identity_anchor(prepared)
    prepared["supplemental_images"] = []
    prepared["official_reference_images"] = []
    if candidate_refs and len(candidate_refs) < 24 and anchor:
        target = (
            "supplemental_images" if anchor[0] == "supplemental"
            else "official_reference_images"
        )
        prepared[target] = [copy.deepcopy(anchor[1])]
    prepared.setdefault("structured_business_context", {}).update({
        "analysis_mode": "sampled_video_perception_reduce",
        "sampled_batch_results": copy.deepcopy(batch_results),
        "sampled_reduce_candidate_frame_refs": candidate_refs,
    })
    return prepared


def _model_calls(result: Dict[str, Any]) -> int:
    try:
        count = int(result.get("model_http_request_count") or 0)
    except (TypeError, ValueError, OverflowError):
        count = 0
    if count:
        return count
    return 0 if result.get("cost_status") == "not_incurred" else 1


def run_sampled_video_perception(
    case: Dict[str, Any],
    *,
    invoke_model: Callable[[Dict[str, Any]], Dict[str, Any]],
    merge_billing: Callable[[Dict[str, Any], List[Dict[str, Any]]], Dict[str, Any]],
    batch_size: int = 16,
    overlap: int = 2,
    workers: int = 4,
) -> Dict[str, Any]:
    """帧批次只观察原子事实；全局字段仅由最后一次归并生成。"""
    wall_started = time.time()
    frames = list(case.get("frames") or [])
    has_anchor = _resolved_identity_anchor(case) is not None
    effective_size = min(int(batch_size), 23) if has_anchor else int(batch_size)
    batches = build_overlapping_frame_batches(
        frames,
        batch_size=effective_size,
        overlap=overlap,
    )
    if not batches:
        return {
            "status": "failed",
            "error": "sampled_frame_timeline_empty",
            "cost_status": "not_incurred",
            "chunking": {"segment_count": 0, "total_model_calls": 0},
        }

    def observe(item: tuple[int, List[Dict[str, Any]]]) -> Dict[str, Any]:
        index, current_frames = item
        current = prepare_sampled_batch_case(
            case,
            current_frames,
            batch_index=index + 1,
            total_batches=len(batches),
            overlap=overlap,
        )
        result = invoke_model(current)
        result["_sampled_batch"] = copy.deepcopy(
            current["structured_business_context"]["sampled_frame_batch"]
        )
        return result

    completed, concurrency = run_adaptive_tasks(
        list(enumerate(batches)),
        workers=max(1, min(int(workers), 4, len(batches))),
        invoke=observe,
    )
    failed = [item for item in completed if item.get("status") != "success"]
    if failed:
        merged = merge_billing(completed[0], completed[1:])
        no_request_was_incurred = all(
            item.get("status") == "skipped"
            and item.get("cost_status") == "not_incurred"
            for item in completed
        )
        merged.update({
            "status": "skipped" if no_request_was_incurred else "failed",
            "error": (
                str(completed[0].get("error") or "model_request_skipped")
                if no_request_was_incurred
                else "sampled_batch_observation_failed"
            ),
            "latency_seconds": round(time.time() - wall_started, 2),
            "chunking": {
                "pipeline_mode": "parallel_overlapping_1fps_facts",
                "segment_count": len(batches),
                "completed_segments": len(completed) - len(failed),
                "total_frames": len(frames),
                "total_model_calls": sum(_model_calls(item) for item in completed),
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
            "parsed": copy.deepcopy(result.get("parsed") or {}),
        })
    rows.sort(key=lambda item: int(item.get("batch_index") or 0))
    reduced = invoke_model(prepare_sampled_reduce_case(case, rows))
    merged = merge_billing(reduced, completed)
    if reduced.get("status") == "success":
        compact = copy.deepcopy(reduced.get("parsed") or {})
        expanded = expand_native_video_perception(compact, case, sampling_fps=1.0)
        merged["compact_perception"] = compact
        merged["parsed_before_boundary"] = copy.deepcopy(expanded)
        merged["parsed"] = expanded
    total_calls = sum(_model_calls(item) for item in [*completed, reduced])
    merged["batch_results"] = rows
    merged["latency_seconds"] = round(time.time() - wall_started, 2)
    merged["chunking"] = {
        "pipeline_mode": "parallel_overlapping_1fps_facts",
        "segment_count": len(batches),
        "completed_segments": len(completed),
        "frames_per_segment": effective_size,
        "overlap_frames": int(overlap),
        "total_frames": len(frames),
        "main_review_frames": len(frames),
        "total_model_calls": total_calls,
        "concurrency": concurrency,
        "channels": {
            "sampled_observation": {
                "model_calls": sum(_model_calls(item) for item in completed),
                "segment_calls": len(completed),
            },
            "sampled_reduce": {"model_calls": _model_calls(reduced)},
        },
    }
    return merged
