# -*- coding: utf-8 -*-
"""多视频工单的低成本开箱视频角色预筛。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Sequence

import cv2


OPENING_ROLE_FIELDS = {
    "opening_video",
    "unboxing_video",
    "initial_opening_video",
    "initial_unboxing_video",
}
OPENING_ROLE_VIDEOS_PER_REQUEST = 2


def opening_role_batches(
    videos: Sequence[Path],
) -> List[List[tuple[int, Path]]]:
    indexed = list(enumerate(videos, start=1))
    return [
        indexed[start:start + OPENING_ROLE_VIDEOS_PER_REQUEST]
        for start in range(0, len(indexed), OPENING_ROLE_VIDEOS_PER_REQUEST)
    ]


def _format_time(seconds: float) -> str:
    total_milliseconds = max(0, int(round(seconds * 1000)))
    minutes, remainder = divmod(total_milliseconds, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{minutes:02d}:{whole_seconds:02d}.{milliseconds:03d}"


def declared_video_roles(
    evidence_context: Dict[str, Any],
    videos: Sequence[Path],
) -> Dict[str, List[str]]:
    raw_manifest = evidence_context.get("asset_manifest")
    if isinstance(raw_manifest, str):
        try:
            manifest = json.loads(raw_manifest or "{}")
        except json.JSONDecodeError:
            manifest = {}
    else:
        manifest = raw_manifest if isinstance(raw_manifest, dict) else {}
    fields_by_name = {
        Path(str(asset.get("original_name") or "").replace("\\", "/")).name.lower(): [
            str(field).strip().lower()
            for field in asset.get("fields") or []
            if str(field).strip()
        ]
        for asset in manifest.get("assets") or []
        if isinstance(asset, dict)
    }
    return {
        video.name: fields_by_name.get(video.name.lower(), [])
        for video in videos
    }


def extract_opening_role_previews(
    videos: Sequence[Path],
    output_dir: Path,
    *,
    preview_seconds: int = 10,
    max_long_edge: int = 1920,
    video_indices: Sequence[int] | None = None,
) -> List[Dict[str, Any]]:
    """每条视频仅取前十秒约 1 FPS 的独立 WebP，不拼图。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    frames: List[Dict[str, Any]] = []
    indices = list(video_indices or range(1, len(videos) + 1))
    if len(indices) != len(videos):
        raise ValueError("video_indices_length_mismatch")
    for video_index, video in zip(indices, videos):
        capture = cv2.VideoCapture(str(video))
        if not capture.isOpened():
            continue
        try:
            fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
            frame_count = float(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
            duration = frame_count / fps if fps > 0 and frame_count > 0 else 0.0
            limit = preview_seconds if duration <= 0 else min(preview_seconds, max(1, int(duration) + 1))
            for second in range(limit):
                capture.set(cv2.CAP_PROP_POS_MSEC, float(second) * 1000.0)
                ok, frame = capture.read()
                if not ok:
                    continue
                height, width = frame.shape[:2]
                scale = min(1.0, max_long_edge / max(height, width))
                if scale < 1.0:
                    frame = cv2.resize(
                        frame,
                        (max(2, int(width * scale)), max(2, int(height * scale))),
                        interpolation=cv2.INTER_AREA,
                    )
                global_index = (video_index - 1) * preview_seconds + second + 1
                target = output_dir / f"video_{video_index:02d}_{second:02d}s.webp"
                encoded_ok, encoded = cv2.imencode(
                    ".webp", frame, [cv2.IMWRITE_WEBP_QUALITY, 88]
                )
                if not encoded_ok:
                    continue
                encoded.tofile(str(target))
                frames.append({
                    "video_index": video_index,
                    "global_frame_index": global_index,
                    "timestamp_seconds": float(second),
                    "timestamp": _format_time(float(second)),
                    "video_file": video.name,
                    "path": str(target),
                    "api_path": str(target),
                    "api_mime_type": "image/webp",
                    "selection_role": "opening_video_role_preview",
                })
        finally:
            capture.release()
    return frames


def build_opening_role_case(
    videos: Sequence[Path],
    frames: Sequence[Dict[str, Any]],
    declared_roles: Dict[str, List[str]],
    *,
    video_indices: Sequence[int] | None = None,
) -> Dict[str, Any]:
    indices = list(video_indices or range(1, len(videos) + 1))
    if len(indices) != len(videos):
        raise ValueError("video_indices_length_mismatch")
    return {
        "case_id": "opening-video-role-preflight",
        "scenario": "video_unboxing",
        "scenario_label": "开箱视频角色预筛",
        "customer_claim": "",
        "videos": [
            {
                "video_index": index,
                "file": video.name,
                "declared_opening_role": bool(
                    OPENING_ROLE_FIELDS.intersection(declared_roles.get(video.name) or [])
                ),
            }
            for index, video in zip(indices, videos)
        ],
        "frames": [dict(frame) for frame in frames],
        "supplemental_images": [],
        "official_reference_images": [],
        "structured_business_context": {
            "business_scenario": "video_unboxing",
            "analysis_mode": "opening_video_role_preflight",
        },
    }


def select_opening_video_candidates(
    videos: Sequence[Path],
    parsed: Dict[str, Any] | None,
    declared_roles: Dict[str, List[str]],
    *,
    minimum_confidence: float = 0.75,
) -> Dict[str, Any]:
    rows = parsed.get("candidates") if isinstance(parsed, dict) else []
    selected_indices = []
    public_rows = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        try:
            index = int(row.get("video_index") or 0)
            confidence = float(row.get("confidence") or 0.0)
        except (TypeError, ValueError, OverflowError):
            continue
        if not 1 <= index <= len(videos):
            continue
        evidence = row.get("evidence_refs") or []
        qualified = (
            row.get("is_opening_video") is True
            and confidence >= minimum_confidence
            and bool(evidence)
            and (
                row.get("sealed_package_visible") is True
                or row.get("opening_action_visible") is True
            )
        )
        if qualified:
            selected_indices.append(index)
        public_rows.append({
            "video_index": index,
            "confidence": round(max(0.0, min(confidence, 1.0)), 4),
            "is_opening_video": row.get("is_opening_video"),
            "sealed_package_visible": row.get("sealed_package_visible"),
            "opening_action_visible": row.get("opening_action_visible"),
            "reason": str(row.get("reason") or "")[:240],
            "declared_opening_role": bool(
                OPENING_ROLE_FIELDS.intersection(declared_roles.get(videos[index - 1].name) or [])
            ),
        })
    selected_indices = sorted(set(selected_indices))
    narrowed = bool(selected_indices)
    selected_set = set(selected_indices)
    selected = (
        [videos[index - 1] for index in selected_indices]
        + [video for index, video in enumerate(videos, start=1) if index not in selected_set]
        if narrowed
        else list(videos)
    )
    return {
        "status": "completed",
        "strategy": "first_10_seconds_1fps_individual_webp",
        "preview_is_full_compliance": False,
        "routing_decision": "opening_candidates_ranked_first" if narrowed else "keep_all_candidates",
        "selected_video_indices": selected_indices,
        "selected_videos": selected,
        "candidate_count": len(videos),
        "rows": public_rows,
    }


__all__ = [
    "OPENING_ROLE_FIELDS",
    "build_opening_role_case",
    "declared_video_roles",
    "extract_opening_role_previews",
    "opening_role_batches",
    "select_opening_video_candidates",
]
