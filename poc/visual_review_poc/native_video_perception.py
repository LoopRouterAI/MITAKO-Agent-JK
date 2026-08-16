# -*- coding: utf-8 -*-
"""原生视频紧凑感知结果与现有审核契约之间的共享适配。"""
from __future__ import annotations

import copy
import math
import re
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Tuple

import cv2

from poc.visual_review_poc.local_video_triage_demo import format_time
from poc.visual_review_poc.unified_model_pass import (
    claimed_item_identity_window_is_traceable,
)


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
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


def apply_perception_evidence_scope(case: Dict[str, Any]) -> Dict[str, Any]:
    """主视频感知只携带目标商品参考图，补充材料不参与开箱事实判定。"""
    scoped = copy.deepcopy(case)
    scoped["frames"] = []
    scoped["supplemental_images"] = []
    identity = (
        (scoped.get("structured_business_context") or {}).get("continuity_claim_identity")
        or {}
    )
    identity_refs = {
        str(identity.get(key) or "").strip()
        for key in ("item_ref", "sku")
        if str(identity.get(key) or "").strip()
    }
    if identity_refs:
        matches = []
        for image in scoped.get("official_reference_images") or []:
            refs = {
                str(image.get(key) or "").strip()
                for key in ("item_ref", "sku")
                if str(image.get(key) or "").strip()
            }
            refs.update(
                str(item or "").strip()
                for key in ("item_refs", "skus")
                for item in image.get(key) or []
                if str(item or "").strip()
            )
            if identity_refs.intersection(refs):
                matches = [image]
                break
        scoped["official_reference_images"] = matches
    return scoped


def build_claim_identity_case(case: Dict[str, Any]) -> Dict[str, Any]:
    identity_case = copy.deepcopy(case)
    identity_case.pop("native_video", None)
    identity_case["frames"] = []
    identity_case.setdefault("structured_business_context", {})["analysis_mode"] = (
        "claim_identity_only"
    )
    return identity_case


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
    if confidence < 0.7 or not str(item.get("product_name") or "").strip():
        return {}
    return {
        key: item.get(key)
        for key in ("item_ref", "sku", "product_name", "specification")
        if item.get(key) not in (None, "")
    }


def candidate_detail_timestamps(
    parsed: Dict[str, Any],
    max_candidates: int = 8,
) -> List[float]:
    evidence_refs = [
        item for item in parsed.get("evidence_refs") or []
        if isinstance(item, dict)
    ]
    issue_values = [
        _timestamp_seconds(item.get("timestamp"))
        for item in evidence_refs
        if item.get("field") == "issue_visible"
    ]
    damage_timestamp = _timestamp_seconds(
        (parsed.get("damage_assessment") or {}).get("timestamp")
    )
    claimed_values = [
        _timestamp_seconds(item.get("timestamp"))
        for item in evidence_refs
        if item.get("field") == "claimed_item"
    ]
    values = issue_values + [damage_timestamp] + claimed_values
    timestamps = [round(item, 3) for item in values if item is not None]
    if not timestamps:
        claimed = parsed.get("claimed_item_assessment") or {}
        timestamps = [
            round(item, 3)
            for item in (
                _timestamp_seconds(claimed.get("first_visible_timestamp")),
                _timestamp_seconds(claimed.get("last_visible_timestamp")),
            )
            if item is not None
        ]
    return list(dict.fromkeys(timestamps))[: max(1, int(max_candidates))]


def requires_claimed_item_detail(parsed: Dict[str, Any], scenario: str) -> bool:
    if scenario != "product_damage":
        return False
    return bool(candidate_detail_timestamps(parsed))


def extract_candidate_frames(
    video: Path,
    timestamps: Iterable[float],
    output_dir: Path,
    *,
    offsets: tuple[float, ...] = (-0.25, 0.0, 0.25),
    max_frames: int = 24,
) -> List[Dict[str, Any]]:
    """按模型自主发现的时间点提取独立 WebP 细节帧，最长边不超过 1080P。"""
    targets = []
    for timestamp in timestamps:
        try:
            base = float(timestamp)
        except (TypeError, ValueError, OverflowError):
            continue
        if not math.isfinite(base) or base < 0:
            continue
        targets.extend(max(0.0, base + offset) for offset in offsets)
    targets = list(dict.fromkeys(round(item, 3) for item in targets))[: max(1, int(max_frames))]
    if not targets:
        return []

    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        return []
    output_dir.mkdir(parents=True, exist_ok=True)
    extracted: List[Dict[str, Any]] = []
    try:
        for target in targets:
            capture.set(cv2.CAP_PROP_POS_MSEC, target * 1000)
            ok, frame = capture.read()
            if not ok or frame is None:
                continue
            height, width = frame.shape[:2]
            scale = min(1.0, 1920 / max(height, width))
            if scale < 1.0:
                frame = cv2.resize(
                    frame,
                    (max(1, int(width * scale)), max(1, int(height * scale))),
                    interpolation=cv2.INTER_AREA,
                )
            path = output_dir / f"candidate_{len(extracted) + 1:02d}_{target:.3f}s.webp"
            encoded_ok, encoded = cv2.imencode(
                ".webp",
                frame,
                [cv2.IMWRITE_WEBP_QUALITY, 101],
            )
            if not encoded_ok:
                continue
            encoded.tofile(str(path))
            extracted.append({
                "frame_index": len(extracted) + 1,
                "timestamp_seconds": target,
                "path": path,
            })
    finally:
        capture.release()
    return extracted


def build_candidate_detail_case(
    case: Dict[str, Any],
    extracted_frames: List[Dict[str, Any]],
) -> Dict[str, Any]:
    detail = apply_perception_evidence_scope(case)
    detail.pop("native_video", None)
    detail["frames"] = [
        {
            "video_index": 1,
            "global_frame_index": int(item["frame_index"]),
            "timestamp": format_time(float(item["timestamp_seconds"])),
            "timestamp_seconds": float(item["timestamp_seconds"]),
            "api_path": str(item["path"]),
            "api_mime_type": "image/webp",
        }
        for item in extracted_frames
    ]
    detail.setdefault("structured_business_context", {})["analysis_mode"] = (
        "claimed_item_detail_only"
    )
    return detail


def build_identity_recovery_case(
    case: Dict[str, Any],
    rejected_candidate_timestamps: Iterable[float],
) -> Dict[str, Any]:
    """让备选模型排除已被细节复核否定的候选后重新通看原片。"""
    recovery = copy.deepcopy(case)
    rejected = list(dict.fromkeys(
        round(float(item), 3)
        for item in rejected_candidate_timestamps
        if math.isfinite(float(item)) and float(item) >= 0
    ))
    recovery.setdefault("structured_business_context", {})["identity_recovery"] = {
        "reason": "先前模型自主发现的候选与争议商品身份不匹配",
        "rejected_candidate_timestamps": rejected,
    }
    return recovery


def _video_reference_location(item: Dict[str, Any]) -> Tuple[int, int | None] | None:
    asset_ref = str(item.get("asset_ref") or "").strip()
    native_match = re.fullmatch(r"native_video_(\d+)", asset_ref)
    frame_match = re.fullmatch(r"video_(\d+)_frame_(\d+)", asset_ref)
    if not native_match and not frame_match:
        return None
    asset_video_index = int((native_match or frame_match).group(1))
    supplied_video_index = item.get("video_index")
    if supplied_video_index not in (None, ""):
        try:
            if int(supplied_video_index) != asset_video_index:
                return None
        except (TypeError, ValueError, OverflowError):
            return None
    video_index = asset_video_index
    if native_match:
        return video_index, None
    try:
        global_frame_index = int(item["global_frame_index"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if global_frame_index != int(frame_match.group(2)):
        return None
    return video_index, global_frame_index


def _video_reference_within_duration(item: Dict[str, Any], case: Dict[str, Any]) -> bool:
    location = _video_reference_location(item)
    if location is None:
        return True
    durations = {
        int(video.get("video_index") or index): float(video["duration_seconds"])
        for index, video in enumerate(case.get("videos") or [], start=1)
        if isinstance(video, dict) and video.get("duration_seconds") not in (None, "")
    }
    duration = durations.get(location[0])
    seconds = _timestamp_seconds(item.get("timestamp"))
    return duration is None or (
        seconds is not None and seconds <= duration + 1.0
    )


def _refs(parsed: Dict[str, Any], field: str) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []
    for item in parsed.get("evidence_refs") or []:
        if not isinstance(item, dict) or item.get("field") != field:
            continue
        asset_ref = str(item.get("asset_ref") or "").strip()
        location = _video_reference_location(item)
        if location is None:
            continue
        timestamp = str(item.get("timestamp") or "").strip()
        fact = str(item.get("fact") or item.get("visible_facts") or "").strip()
        if not timestamp or not fact:
            continue
        reference = {
            "field": field,
            "video_index": location[0],
            "timestamp": timestamp,
            "asset_ref": asset_ref,
            "visible_facts": fact,
        }
        if location[1] is not None:
            reference["global_frame_index"] = location[1]
        refs.append(reference)
    return refs


def normalize_minor_damage_evidence(parsed: Dict[str, Any]) -> Dict[str, Any]:
    """轻微表面伤没有可回链主视频证据时保持不确定。"""
    damage = dict(parsed.get("damage_assessment") or {})
    reported_visible = (
        parsed.get("issue_visible") is True
        or damage.get("visible_in_continuous_opening") is True
    )
    anchors = {
        (int(item["video_index"]), str(item["timestamp"]))
        for item in _refs(parsed, "issue_visible")
    }
    if (
        reported_visible
        and damage.get("severity_level") == "minor"
        and damage.get("structural_failure") is False
        and not anchors
    ):
        parsed["issue_visible"] = None
        damage.update({
            "visible_in_continuous_opening": None,
            "main_video_detail_sufficient": False,
            "detail_review_signal": "yellow",
            "reason": "轻微表面伤缺少可回链的主视频证据，尚不足以排除反光、纹理或压缩噪点。",
        })
    parsed["damage_assessment"] = damage
    return parsed


def _supplemental_damage_refs(parsed: Dict[str, Any]) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []
    for item in parsed.get("evidence_refs") or []:
        if not isinstance(item, dict) or item.get("field") != "supplemental_damage_visible":
            continue
        asset_ref = str(item.get("asset_ref") or "").strip()
        fact = str(item.get("fact") or "").strip()
        if not asset_ref.startswith("supplemental_image_") or not fact:
            continue
        suffix = asset_ref.removeprefix("supplemental_image_")
        refs.append({
            "field": "supplemental_damage_visible",
            "source_type": "supplementary_image",
            "asset_ref": asset_ref,
            "image_index": int(suffix) if suffix.isdigit() else None,
            "timestamp": None,
            "visible_facts": fact,
        })
    return refs


def _submitted_evidence_asset_refs(case: Dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    for index, video in enumerate(case.get("videos") or [], start=1):
        if not isinstance(video, dict):
            continue
        video_index = video.get("video_index") or index
        refs.add(str(video.get("asset_ref") or f"native_video_{video_index}"))
    for image_index, image in enumerate(case.get("supplemental_images") or [], start=1):
        if not isinstance(image, dict):
            continue
        index = image.get("image_index") or image_index
        refs.add(str(image.get("asset_ref") or f"supplemental_image_{index}"))
    return refs


def _atomic_claim_results(compact: Dict[str, Any], case: Dict[str, Any]) -> List[Dict[str, Any]]:
    structured = case.get("structured_business_context") or {}
    scope = structured.get("claim_scope") or case.get("claim_scope") or {}
    active_ids = {
        str(value).strip()
        for value in scope.get("active_claim_ids") or []
        if str(value).strip()
    }
    available = {
        (
            str(item.get("asset_ref") or "").strip(),
            str(item.get("timestamp") or "").strip(),
            str(item.get("fact") or item.get("visible_facts") or "").strip(),
        ): item
        for item in compact.get("evidence_refs") or []
        if isinstance(item, dict)
    }
    submitted_asset_refs = _submitted_evidence_asset_refs(case)
    results: List[Dict[str, Any]] = []
    for item in compact.get("atomic_claim_results") or []:
        if not isinstance(item, dict):
            continue
        claim_id = str(item.get("claim_id") or "").strip()
        subject_ref = str(item.get("subject_ref") or "").strip()
        if not claim_id or not subject_ref or (active_ids and claim_id not in active_ids):
            continue
        refs = []
        for raw_ref in item.get("evidence_refs") or []:
            if not isinstance(raw_ref, dict):
                continue
            key = (
                str(raw_ref.get("asset_ref") or "").strip(),
                str(raw_ref.get("timestamp") or "").strip(),
                str(raw_ref.get("fact") or "").strip(),
            )
            source = available.get(key)
            source = source or raw_ref
            if key[0] not in submitted_asset_refs and key not in available:
                continue
            location = _video_reference_location(source)
            if location is not None:
                if not key[1] or not key[2] or not _video_reference_within_duration(source, case):
                    continue
                reference = {
                    "source_type": "video_frame",
                    "asset_ref": key[0],
                    "video_index": location[0],
                    "timestamp": key[1],
                    "fact": key[2],
                }
                if location[1] is not None:
                    reference["global_frame_index"] = location[1]
                refs.append(reference)
            elif (
                key[0] in submitted_asset_refs
                and re.fullmatch(r"supplemental_image_\d+", key[0])
                and key[2]
            ):
                refs.append({
                    "source_type": "supplementary_image",
                    "asset_ref": key[0],
                    "timestamp": None,
                    "fact": key[2],
                })
        try:
            severity_confidence = float(item.get("severity_confidence"))
        except (TypeError, ValueError, OverflowError):
            severity_confidence = 0.0
        if not math.isfinite(severity_confidence):
            severity_confidence = 0.0
        damage_presence = str(item.get("damage_presence") or "insufficient")
        condition_at_unboxing = str(item.get("condition_at_unboxing") or "insufficient")
        support_status = (
            "supported"
            if damage_presence == "confirmed" and condition_at_unboxing == "supported"
            else "not_supported"
            if damage_presence == "not_found_after_clear_coverage"
            or condition_at_unboxing == "not_supported"
            else "insufficient"
        )
        results.append({
            "claim_id": claim_id,
            "subject_ref": subject_ref,
            "location": str(item.get("location") or "").strip(),
            "damage_type": str(item.get("damage_type") or "").strip(),
            "main_video_visibility": str(item.get("main_video_visibility") or "not_assessed"),
            "supplemental_visibility": str(item.get("supplemental_visibility") or "not_assessed"),
            "same_item_linkage": item.get("same_item_linkage") if isinstance(item.get("same_item_linkage"), bool) else None,
            "damage_presence": damage_presence,
            "condition_at_unboxing": condition_at_unboxing,
            "support_status": support_status,
            "severity_level": str(item.get("severity_level") or "unknown"),
            "severity_confidence": round(max(0.0, min(severity_confidence, 1.0)), 4),
            "structural_failure": item.get("structural_failure") if isinstance(item.get("structural_failure"), bool) else None,
            "conflicting_evidence": item.get("conflicting_evidence") is True,
            "evidence_refs": refs,
            "reason": str(item.get("reason") or "").strip(),
        })
    return results


def _derive_damage_assessment_from_atomic_claims(
    compact: Dict[str, Any],
    atomic_claims: List[Dict[str, Any]],
) -> None:
    if not atomic_claims:
        return

    severity_rank = {"unknown": -1, "none": 0, "minor": 1, "moderate": 2, "severe": 3, "extreme": 4}
    strongest = max(
        atomic_claims,
        key=lambda item: (
            severity_rank.get(str(item.get("severity_level") or "unknown"), -1),
            float(item.get("severity_confidence") or 0.0),
        ),
    )
    visible_claims = [
        item for item in atomic_claims
        if item.get("damage_presence") == "confirmed"
        and item.get("main_video_visibility") == "visible"
    ]
    opening_visible_claims = [
        item for item in visible_claims
        if item.get("condition_at_unboxing") == "supported"
    ]
    clearly_absent = all(
        item.get("damage_presence") == "not_found_after_clear_coverage"
        and item.get("main_video_visibility") == "clearly_not_visible"
        for item in atomic_claims
    )
    linkage_values = [item.get("same_item_linkage") for item in atomic_claims]
    same_item_linkage = (
        False if False in linkage_values
        else True if linkage_values and all(value is True for value in linkage_values)
        else None
    )
    detail_sufficient = all(
        item.get("main_video_visibility") in {"visible", "clearly_not_visible"}
        for item in atomic_claims
    )
    severity_level = str(strongest.get("severity_level") or "unknown")
    severity_confidence = float(strongest.get("severity_confidence") or 0.0)
    business_qualification = (
        "confirmed"
        if visible_claims
        and severity_level in {"severe", "extreme"}
        and strongest.get("structural_failure") is True
        and severity_confidence >= 0.8
        else "not_qualified"
        if all(
            str(item.get("severity_level") or "unknown") in {"none", "minor", "moderate"}
            for item in atomic_claims
        )
        else "indeterminate"
    )
    first_visible_ref = next(
        (
            reference
            for item in opening_visible_claims
            for reference in item.get("evidence_refs") or []
            if str(reference.get("timestamp") or "").strip()
        ),
        {},
    )
    locations = list(dict.fromkeys(
        str(item.get("location") or "").strip()
        for item in atomic_claims
        if str(item.get("location") or "").strip()
    ))
    reasons = list(dict.fromkeys(
        str(item.get("reason") or "").strip()
        for item in atomic_claims
        if str(item.get("reason") or "").strip()
    ))

    damage = dict(compact.get("damage_assessment") or {})
    damage.update({
        "visible_in_continuous_opening": True if opening_visible_claims else False if clearly_absent else None,
        "main_video_detail_sufficient": detail_sufficient,
        "supplemental_damage_visible": any(
            item.get("supplemental_visibility") == "visible" for item in atomic_claims
        ),
        "same_item_linkage": same_item_linkage,
        "timestamp": first_visible_ref.get("timestamp"),
        "location": "；".join(locations),
        "severity_level": severity_level,
        "structural_failure": strongest.get("structural_failure"),
        "severity_confidence": severity_confidence,
        "business_defect_qualification": business_qualification,
        "conflicting_evidence": any(item.get("conflicting_evidence") is True for item in atomic_claims),
        "severity_reason": str(strongest.get("reason") or ""),
        "reason": "；".join(reasons),
    })
    compact["damage_assessment"] = damage
    compact["issue_visible"] = True if opening_visible_claims else False if clearly_absent else None

    evidence_refs = list(compact.get("evidence_refs") or [])
    known_refs = {
        (
            str(reference.get("field") or ""),
            str(reference.get("asset_ref") or ""),
            str(reference.get("timestamp") or ""),
        )
        for reference in evidence_refs
        if isinstance(reference, dict)
    }
    for claim in opening_visible_claims:
        for reference in claim.get("evidence_refs") or []:
            if reference.get("source_type") != "video_frame":
                continue
            key = (
                "issue_visible",
                str(reference.get("asset_ref") or ""),
                str(reference.get("timestamp") or ""),
            )
            if key in known_refs:
                continue
            evidence_refs.append({
                "field": "issue_visible",
                "asset_ref": key[1],
                "timestamp": key[2],
                "fact": str(reference.get("fact") or ""),
            })
            known_refs.add(key)
    compact["evidence_refs"] = evidence_refs


def _opening_result(values: Iterable[Any]) -> str:
    values = list(values)
    if any(value is False for value in values):
        return "noncompliant"
    if values and all(value is True for value in values):
        return "compliant"
    return "indeterminate"


def _plain_conclusion(result: str) -> str:
    if result == "compliant":
        return "完整开箱视频符合审核门槛，并在同一连续开箱过程中看见所诉损伤。"
    if result == "noncompliant":
        return "本轮完整视频中至少一项开箱硬要求未满足，当前证据不支持直接采信所诉损伤。"
    return "当前完整视频仍有关键事实无法确认，需要客服复核标黄项后再处理。"


_ATOMIC_VIDEO_FIELDS = (
    "sealed_start",
    "waybill_visible",
    "continuous",
    "has_edit",
    "has_offscreen",
    "has_speed_change",
    "all_items_shown",
    "issue_visible",
)

_EVIDENCE_FIELDS = frozenset((
    *_ATOMIC_VIDEO_FIELDS,
    "opening_action",
    "claimed_item",
    "supplemental_damage_visible",
))


def _overall_evidence_confidence(compact: Dict[str, Any]) -> float:
    confidences = _normalized_field_confidences(compact.get("field_confidences"))
    resolved = [field for field in _ATOMIC_VIDEO_FIELDS if isinstance(compact.get(field), bool)]
    if not resolved:
        return 0.0
    values = []
    for field in resolved:
        try:
            value = float(confidences.get(field))
        except (TypeError, ValueError, OverflowError):
            value = 0.5
        values.append(max(0.0, min(value, 1.0)))
    coverage = len(resolved) / len(_ATOMIC_VIDEO_FIELDS)
    return round((sum(values) / len(values)) * coverage, 4)


def _normalized_field_confidences(value: Any) -> Dict[str, Any]:
    if isinstance(value, (list, tuple)):
        return dict(zip(_ATOMIC_VIDEO_FIELDS, value))
    return {
        field: value.get(field)
        for field in _ATOMIC_VIDEO_FIELDS
        if isinstance(value, dict) and field in value
    }


def _atomic_fact_view(compact: Dict[str, Any]) -> List[Dict[str, Any]]:
    """把紧凑模型结果规范化为报告和决策共用的可追溯原子事实。"""
    confidences = _normalized_field_confidences(compact.get("field_confidences"))
    action = compact.get("opening_action_assessment") or {}
    reason_sources = {
        "opening_action": action,
        "has_offscreen": compact.get("claimed_item_assessment") or {},
        "all_items_shown": compact.get("claimed_item_assessment") or {},
        "has_speed_change": compact.get("speed_assessment") or {},
        "issue_visible": compact.get("damage_assessment") or {},
    }
    facts = []
    for field in ("opening_action", *_ATOMIC_VIDEO_FIELDS):
        refs = _refs(compact, field)
        value = action.get("present") if field == "opening_action" else compact.get(field)
        raw_confidence = action.get("confidence") if field == "opening_action" else confidences.get(field)
        try:
            confidence = float(raw_confidence)
        except (TypeError, ValueError, OverflowError):
            confidence = None
        if confidence is not None:
            confidence = round(max(0.0, min(confidence, 1.0)), 4) if math.isfinite(confidence) else None
        reason = str((reason_sources.get(field) or {}).get("reason") or "").strip()
        if not reason:
            reason = "；".join(dict.fromkeys(
                str(item.get("visible_facts") or "").strip()
                for item in refs
                if str(item.get("visible_facts") or "").strip()
            ))
        if not reason:
            reason = "本轮没有形成可回看的该项事实。"
        facts.append({
            "field": field,
            "value": value if isinstance(value, bool) else None,
            "confidence": confidence,
            "reason": reason,
            "evidence_refs": refs,
        })
    return facts


def _derive_overall_video_result(compact: Dict[str, Any]) -> str:
    normalize_minor_damage_evidence(compact)
    damage = dict(compact.get("damage_assessment") or {})
    if (
        damage.get("main_video_detail_sufficient") is False
        and damage.get("visible_in_continuous_opening") is False
    ):
        damage["visible_in_continuous_opening"] = None
        damage["detail_review_signal"] = "yellow"
        compact["damage_assessment"] = damage
        compact["issue_visible"] = None
    native_evidence_fields = {
        field for field in _EVIDENCE_FIELDS if _refs(compact, field)
    }
    action = compact.get("opening_action_assessment") or {}
    action_present = action.get("present")
    action_referenced = "opening_action" in native_evidence_fields
    if action_present is False and action_referenced:
        return "noncompliant"
    if action_present is not True or not action_referenced:
        return "indeterminate"

    confidences = _normalized_field_confidences(compact.get("field_confidences"))
    if isinstance(compact.get("has_edit"), bool):
        try:
            edit_confidence = float(confidences.get("has_edit"))
        except (TypeError, ValueError, OverflowError):
            edit_confidence = 0.0
        edit_refs = _refs(compact, "has_edit")
        reliable_edit = (
            math.isfinite(edit_confidence)
            and edit_confidence >= 0.8
            and (compact.get("has_edit") is False or len(edit_refs) >= 2)
        )
        if not reliable_edit:
            compact["has_edit"] = None
            compact["edit_review_signal"] = "yellow"
        elif compact.get("has_edit") is True:
            compact["edit_review_signal"] = "confirmed_critical_break"
    resolved_fields = {
        field for field in _ATOMIC_VIDEO_FIELDS if isinstance(compact.get(field), bool)
    }
    if not resolved_fields.issubset(native_evidence_fields):
        return "indeterminate"
    required_true = (
        "sealed_start",
        "waybill_visible",
        "continuous",
        "all_items_shown",
        "issue_visible",
    )
    required_false = ("has_edit", "has_offscreen")
    if any(compact.get(field) is False for field in required_true):
        return "noncompliant"
    if any(compact.get(field) is True for field in required_false):
        return "noncompliant"

    claimed = compact.get("claimed_item_assessment") or {}
    damage = compact.get("damage_assessment") or {}
    consistency_pairs = (
        (compact.get("all_items_shown"), claimed.get("presentation_complete")),
        (compact.get("has_offscreen"), claimed.get("offscreen_during_presentation")),
        (compact.get("issue_visible"), damage.get("visible_in_continuous_opening")),
    )
    if any(left is not None and right is not None and left != right for left, right in consistency_pairs):
        return "indeterminate"
    if any(compact.get(field) is None for field in (*required_true, *required_false)):
        return "indeterminate"
    if damage.get("same_item_linkage") is not True:
        return "indeterminate"

    speed = compact.get("speed_assessment") or {}
    if speed.get("affects_visual_judgement") is True:
        return "indeterminate"
    if compact.get("has_speed_change") is True and speed.get("affects_visual_judgement") is not False:
        return "indeterminate"
    if not {"sealed_start", "waybill_visible", "continuous", "issue_visible"}.issubset(
        native_evidence_fields
    ):
        return "indeterminate"
    return "compliant"


def _opening_video_evidence(compact: Dict[str, Any]) -> Dict[str, Any]:
    action = compact.get("opening_action_assessment") or {}
    action_refs = _refs(compact, "opening_action")
    confidences = _normalized_field_confidences(compact.get("field_confidences"))
    confidence_values = []
    for field in ("sealed_start", "waybill_visible", "continuous", "all_items_shown", "issue_visible"):
        try:
            value = float(confidences.get(field))
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(value):
            confidence_values.append(max(0.0, min(value, 1.0)))
    requirements = {
        "opening_action": action.get("present") is True and bool(action_refs),
        "sealed_start": compact.get("sealed_start") is True and bool(_refs(compact, "sealed_start")),
        "waybill_visible": compact.get("waybill_visible") is True and bool(_refs(compact, "waybill_visible")),
        "continuous": compact.get("continuous") is True and bool(_refs(compact, "continuous")),
        "claimed_item_presentation": compact.get("all_items_shown") is True and bool(_refs(compact, "all_items_shown")),
        "issue_assessable": isinstance(compact.get("issue_visible"), bool) and bool(_refs(compact, "issue_visible")),
    }
    present = requirements["opening_action"]
    sop_compliant = all(requirements.values())
    try:
        action_confidence = float(action.get("confidence"))
    except (TypeError, ValueError, OverflowError):
        action_confidence = None
    if action_confidence is not None and not math.isfinite(action_confidence):
        action_confidence = None
    reason = (
        "已确认初次拆开包裹动作；封箱起始、面单、连续性、商品展示和伤点可判断性另行逐项核验。"
        if present
        else "模型判断看到了初次拆包动作，但没有返回可回看的时间点，本项不能采信。"
        if action.get("present") is True
        else "现有材料没有形成可信的初次开箱证据：未直接观察到包裹从闭合状态被首次拆开的动作。"
        if action.get("present") is False
        else "本轮无法确认是否存在包裹从闭合状态被首次拆开的动作。"
    )
    return {
        "present": present,
        "sop_compliant": sop_compliant,
        "status": "pass" if present else "yellow",
        "confidence": (
            round(max(0.0, min(action_confidence, 1.0)), 4)
            if action_confidence is not None
            else None
        ),
        "reason": reason,
        "evidence_refs": [
            item
            for field in ("opening_action", "sealed_start", "waybill_visible", "continuous", "all_items_shown", "issue_visible")
            for item in _refs(compact, field)
        ],
        "validated_requirements": [key for key, passed in requirements.items() if passed],
        "derivation": "required_opening_semantics_with_evidence",
    }


def expand_native_video_perception(
    parsed: Dict[str, Any],
    case: Dict[str, Any],
    *,
    sampling_fps: float,
) -> Dict[str, Any]:
    """将紧凑九字段事实扩展到现有报告、决策和安全投影共用契约。"""
    compact = copy.deepcopy(parsed)
    action = compact.get("opening_action_assessment") or {}
    action_ref = {
        "field": "opening_action",
        "asset_ref": action.get("asset_ref"),
        "timestamp": action.get("timestamp"),
        "fact": action.get("fact"),
    }
    if (
        action.get("present") is True
        and _video_reference_location(action_ref) is not None
        and str(action_ref["timestamp"] or "").strip()
        and str(action_ref["fact"] or "").strip()
        and _video_reference_within_duration(action_ref, case)
    ):
        existing_refs = compact.setdefault("evidence_refs", [])
        if not any(
            isinstance(item, dict)
            and item.get("field") == "opening_action"
            and item.get("asset_ref") == action_ref["asset_ref"]
            and item.get("timestamp") == action_ref["timestamp"]
            for item in existing_refs
        ):
            existing_refs.append(action_ref)
    compact["evidence_refs"] = [
        item
        for item in compact.get("evidence_refs") or []
        if isinstance(item, dict)
        and item.get("field") in _EVIDENCE_FIELDS
        and _video_reference_within_duration(item, case)
    ]
    compact["field_confidences"] = _normalized_field_confidences(
        compact.get("field_confidences")
    )
    sampled_frames = any(
        _video_reference_location(item) is not None
        and re.fullmatch(r"video_\d+_frame_\d+", str(item.get("asset_ref") or "").strip())
        for item in compact.get("evidence_refs") or []
        if isinstance(item, dict)
    )
    perception_source = (
        "sampled_frame_perception" if sampled_frames else "native_full_video_perception"
    )
    if not claimed_item_identity_window_is_traceable(compact):
        claimed_item = dict(compact.get("claimed_item_assessment") or {})
        claimed_item["presentation_complete"] = None
        claimed_item["offscreen_during_presentation"] = None
        compact["claimed_item_assessment"] = claimed_item
        compact["all_items_shown"] = None
        compact["has_offscreen"] = None
    atomic_claims = _atomic_claim_results(compact, case)
    _derive_damage_assessment_from_atomic_claims(compact, atomic_claims)
    result = _derive_overall_video_result(compact)
    compact["overall_video_result"] = result
    label = {"compliant": "positive", "noncompliant": "negative"}.get(result, "review")
    confidence = _overall_evidence_confidence(compact)
    claimed = compact.get("claimed_item_assessment") or {}
    speed = compact.get("speed_assessment") or {}
    damage = compact.get("damage_assessment") or {}

    frame_findings = []
    for field in _EVIDENCE_FIELDS:
        for item in _refs(compact, field):
            frame_findings.append({
                **item,
                "evidence_field": field,
            })

    offscreen = claimed.get("offscreen_during_presentation")
    presentation_complete = claimed.get("presentation_complete")
    continuity_verdict = (
        "long_absence" if offscreen is True
        else "continuous" if compact.get("continuous") is True and offscreen is False
        else "indeterminate"
    )
    visibility_coverage = (
        "complete" if presentation_complete is True and offscreen is False
        else "partial" if offscreen is True
        else "unknown"
    )
    tracked_subject = {
        "subject_id": "claimed_item",
        "identity_description": str(claimed.get("identity_description") or "争议商品"),
        "appeared": claimed.get("appeared"),
        "first_exposed_timestamp": claimed.get("first_visible_timestamp"),
        "last_visible_timestamp": claimed.get("last_visible_timestamp"),
        "presentation_complete": presentation_complete,
        "visibility_coverage": visibility_coverage,
        "out_of_frame_intervals": [],
        "reason": str(claimed.get("reason") or ""),
    }

    opening_fields = {
        "opening_action_visible": (compact.get("opening_action_assessment") or {}).get("present"),
        "sealed_start": compact.get("sealed_start"),
        "waybill_visible": compact.get("waybill_visible"),
        "single_take_continuity": compact.get("continuous"),
        "issue_visible_in_continuous_opening": compact.get("issue_visible"),
    }
    opening_ref_fields = {
        "opening_action_visible": "opening_action",
        "sealed_start": "sealed_start",
        "waybill_visible": "waybill_visible",
        "single_take_continuity": "continuous",
        "issue_visible_in_continuous_opening": "issue_visible",
    }
    opening_refs = [
        {**reference, "field": target}
        for target, source in opening_ref_fields.items()
        for reference in _refs(compact, source)
    ]
    validated_opening_fields = sorted({
        str(reference.get("field") or "")
        for reference in opening_refs
        if (
            isinstance(reference, dict)
            and isinstance(opening_fields.get(str(reference.get("field") or "")), bool)
            and str(reference.get("timestamp") or "").strip()
            and str(reference.get("visible_facts") or "").strip()
        )
    })
    opening_result = _opening_result(opening_fields.values())
    if (
        opening_result in {"compliant", "noncompliant"}
        and len(validated_opening_fields) != len(opening_fields)
    ):
        opening_result = "indeterminate"
    opening = {
        **opening_fields,
        "result": opening_result,
        "evidence_refs": opening_refs,
        "validated_fields": validated_opening_fields,
        "field_sources": {field: perception_source for field in opening_fields},
        "source": perception_source,
    }

    speed_value = str(speed.get("value") or "unknown")
    speed_affects = speed.get("affects_visual_judgement")
    speed_status = (
        "material" if speed_value == "accelerated" and speed_affects is True
        else "none" if speed_affects is False and speed_value in {"normal", "accelerated"}
        else "none" if speed_value == "normal"
        else "uncertain"
    )
    affected_items = (
        ["opening_action", "claimed_item_presentation", "issue_first_visible"]
        if speed_affects is True else []
    )
    critical_observable = False if speed_affects is True else True if speed_affects is False else None

    issue_visible = compact.get("issue_visible")
    same_item = damage.get("same_item_linkage")
    primary_damage_presence = "confirmed" if issue_visible is True else "not_visible" if issue_visible is False else "uncertain"
    severity = {
        "level": str(damage.get("severity_level") or "unknown"),
        "structural_failure": damage.get("structural_failure"),
        "confidence": damage.get("severity_confidence"),
        "reason": str(damage.get("severity_reason") or "本轮未返回损伤严重程度。"),
    }
    causal_chain = {
        "status": str(damage.get("causal_chain_status") or "indeterminate"),
        "evidence_level": str(damage.get("causal_evidence_level") or "none"),
        "reason": str(damage.get("causal_reason") or "未形成操作前、操作中和操作后的同部位证据链。"),
    }
    causal_evidence = [
        item for item in damage.get("causal_evidence_refs") or []
        if isinstance(item, dict)
        and item.get("stage") in {"before_action", "action", "after_action"}
        and _video_reference_location(item) is not None
        and _video_reference_within_duration(item, case)
        and str(item.get("timestamp") or "").strip()
        and str(item.get("subject") or "").strip()
        and str(item.get("location") or "").strip()
        and str(item.get("chain_id") or "").strip()
        and str(item.get("fact") or "").strip()
    ]
    evidence_by_stage = {
        stage: [item for item in causal_evidence if item.get("stage") == stage]
        for stage in ("before_action", "action", "after_action")
    }
    stage_items = [
        evidence_by_stage[stage][0]
        for stage in ("before_action", "action", "after_action")
        if len(evidence_by_stage[stage]) == 1
    ]
    stage_times = [_timestamp_seconds(item.get("timestamp")) for item in stage_items]
    action_relation = (
        str(evidence_by_stage["action"][0].get("action_relation") or "uncertain")
        if len(evidence_by_stage["action"]) == 1 else "uncertain"
    )
    direct_chain_complete = (
        len(stage_items) == 3
        and all(value is not None for value in stage_times)
        and stage_times[0] < stage_times[1] < stage_times[2]
        and len({str(item.get("subject")).strip() for item in stage_items}) == 1
        and len({str(item.get("location")).strip() for item in stage_items}) == 1
        and len({str(item.get("chain_id")).strip() for item in stage_items}) == 1
        and stage_items[0].get("damage_visible") is False
        and stage_items[2].get("damage_visible") is True
        and action_relation in {"direct_contact", "indirect_force"}
    )
    if causal_chain.get("status") == "direct_customer_action" and not direct_chain_complete:
        causal_chain = {
            "status": "indeterminate",
            "evidence_level": "none",
            "reason": "模型声称存在直接因果，但动作前、动作中、动作后三阶段证据未齐全，程序未采信该结论。",
        }
    damage_change_observed = (
        causal_chain.get("status") == "direct_customer_action" and direct_chain_complete
    )
    opening_action_visible = bool(evidence_by_stage["action"])
    direct_customer_damage = (
        issue_visible is True
        and same_item is True
        and damage_change_observed
        and opening_action_visible
        and causal_chain.get("status") == "direct_customer_action"
        and causal_chain.get("evidence_level") == "direct"
    )

    def causal_stage_items(stage: str) -> List[Dict[str, Any]]:
        return [
            {
                "source_type": "video_frame",
                "asset_ref": str(item.get("asset_ref") or ""),
                "video_index": _video_reference_location(item)[0],
                "timestamp": str(item.get("timestamp") or ""),
                "fact": str(item.get("fact") or ""),
                "subject": str(item.get("subject") or ""),
                "location": str(item.get("location") or ""),
                "chain_id": str(item.get("chain_id") or ""),
                "action_relation": str(item.get("action_relation") or "not_applicable"),
                "damage_visible": item.get("damage_visible"),
            }
            for item in evidence_by_stage[stage]
        ]
    claim_support = (
        "not_supported" if direct_customer_damage
        else "supported" if (
            opening.get("result") == "compliant"
            and issue_visible is True
            and same_item is True
            and compact.get("has_edit") is False
            and compact.get("has_offscreen") is False
            and compact.get("all_items_shown") is True
        )
        else "not_supported" if result == "noncompliant" and issue_visible is not None
        else "insufficient"
    )
    issue_refs = _refs(compact, "issue_visible")
    primary_summary = {
        "damage_presence": primary_damage_presence,
        "claim_support": claim_support,
        "detail_sufficient": damage.get("main_video_detail_sufficient"),
        "referenced_count": len(issue_refs),
        "evidence_refs": issue_refs,
    }
    supplemental_count = len(case.get("supplemental_images") or [])
    supplemental_visible = damage.get("supplemental_damage_visible")
    supplemental_refs = _supplemental_damage_refs(compact)
    known_supplemental_refs = {
        (str(item.get("asset_ref") or ""), str(item.get("visible_facts") or ""))
        for item in supplemental_refs
    }
    for claim in atomic_claims:
        if not (
            claim.get("supplemental_visibility") == "visible"
            and claim.get("damage_presence") == "confirmed"
            and claim.get("same_item_linkage") is True
        ):
            continue
        for reference in claim.get("evidence_refs") or []:
            asset_ref = str(reference.get("asset_ref") or "")
            fact = str(reference.get("fact") or "")
            key = (asset_ref, fact)
            if reference.get("source_type") != "supplementary_image" or key in known_supplemental_refs:
                continue
            suffix = asset_ref.removeprefix("supplemental_image_")
            supplemental_refs.append({
                "field": "supplemental_damage_visible",
                "source_type": "supplementary_image",
                "asset_ref": asset_ref,
                "image_index": int(suffix) if suffix.isdigit() else None,
                "timestamp": None,
                "visible_facts": fact,
            })
            known_supplemental_refs.add(key)
    supplemental_visible = supplemental_visible is True or bool(supplemental_refs)
    supplemental_confirmed = supplemental_visible is True and bool(supplemental_refs)
    supplemental_summary = {
        "provided_count": supplemental_count,
        "referenced_count": len(supplemental_refs),
        "damage_presence": "confirmed" if supplemental_confirmed else "not_assessed",
        "linkage_status": "verified" if supplemental_confirmed and same_item is True else "not_assessed",
        "evidence_refs": supplemental_refs,
    }
    damage_presence = (
        "confirmed"
        if primary_damage_presence == "confirmed" or (supplemental_confirmed and same_item is True)
        else primary_damage_presence
    )

    order_linkage_status = "verified" if same_item is True else "failed" if same_item is False else "not_provided"
    next_step = (
        "可按甲方规则进入后续处理，并保留抽检。" if label == "positive"
        else "按开箱视频硬门槛处理，不用补充图片替代连续开箱证据。" if label == "negative"
        else "请客服只复核标黄的身份、伤点或播放速度，不要求整单重复审核。"
    )
    conclusion = _plain_conclusion(result)
    validated_atomic_fields = sorted({
        field for field in _ATOMIC_VIDEO_FIELDS if _refs(compact, field)
    })

    expanded = copy.deepcopy(compact)
    expanded.update({
        "predicted_label": label,
        "system_yes_no": {"positive": "YES", "negative": "NO", "review": "REVIEW"}[label],
        "confidence": confidence,
        "human_required": label == "review",
        "atomic_facts": _atomic_fact_view(compact),
        "opening_video_evidence": _opening_video_evidence(compact),
        "next_step": next_step,
        "overall_audit": {
            "conclusion": conclusion,
            "confidence": confidence,
            "core_reason": str(damage.get("reason") or claimed.get("reason") or conclusion),
            "business_follow_up_suggestion": next_step,
        },
        "frame_findings": frame_findings,
        "object_continuity_assessment": {
            "continuity_verdict": continuity_verdict,
            "claimed_item_timeline_complete": presentation_complete,
            "visibility_coverage": visibility_coverage,
            "longest_out_of_frame_seconds": None,
            "tracked_subjects": [tracked_subject],
            "reason": str(claimed.get("reason") or ""),
        },
        "video_audit_conclusion": {
            "continuity_score": None,
            "continuity_reason": str(claimed.get("reason") or "已审核完整原生视频。"),
            "swap_risk_level": "medium" if offscreen is not False else "low",
            "edit_or_cut_risk": "发现剪辑迹象" if compact.get("has_edit") is True else "未见明确剪辑迹象",
            "edit_review_signal": compact.get("edit_review_signal") or "none",
            "opening_integrity": opening["result"],
            "opening_integrity_source": "native_full_video_perception",
            "playback_speed": speed_value,
            "sampling_fps": float(sampling_fps),
            "speed_review_impact": {
                "status": speed_status,
                "critical_evidence_observable": critical_observable,
                "affected_review_items": affected_items,
                "evidence_refs": _refs(compact, "has_speed_change"),
                "reason": str(speed.get("reason") or ""),
                "source": perception_source,
            },
            "opening_video_compliance": opening,
            "validated_atomic_fields": validated_atomic_fields,
            "sampling_boundary_status": "covered",
            "technical_timeline_status": (
                "sampled_full_timeline_1fps" if sampled_frames else "native_full_video"
            ),
            "evidence_continuity_status": continuity_verdict,
            "source": "global_timeline_aggregation",
        },
        "damage_causality_assessment": {
            "damage_presence": damage_presence,
            "main_video_detail_sufficient": damage.get("main_video_detail_sufficient"),
            "supplemental_damage_presence": supplemental_summary["damage_presence"],
            "damage_type_and_location": str(damage.get("location") or ""),
            "business_defect_qualification": str(
                damage.get("business_defect_qualification") or "indeterminate"
            ),
            "severity_assessment": severity,
            "first_visible_evidence": {
                "timestamp": damage.get("timestamp"),
                "evidence_refs": issue_refs,
            },
            "claim_support": claim_support,
            "damage_timing": (
                "appears_during_opening" if damage_change_observed
                else "already_visible_before_action"
                if causal_chain.get("status") == "pre_existing_visible"
                else "indeterminate"
            ),
            "damage_change_observed": damage_change_observed,
            "pre_opening_state_visible": bool(evidence_by_stage["before_action"]),
            "opening_action_visible": opening_action_visible,
            "most_likely_origin": (
                "customer_opening_or_handling"
                if causal_chain.get("status") == "direct_customer_action"
                else "pre_existing_before_user_action"
                if causal_chain.get("status") == "pre_existing_visible"
                else "indeterminate"
            ),
            "causal_evidence_level": causal_chain.get("evidence_level"),
            "causal_action_relation": action_relation,
            "causal_chain_assessment": causal_chain,
            "causality_assessment": str(causal_chain.get("reason") or ""),
            "before_action_evidence": causal_stage_items("before_action"),
            "action_evidence": causal_stage_items("action"),
            "after_action_evidence": causal_stage_items("after_action"),
            "evidence_source_summary": {
                "primary_video": primary_summary,
                "supplemental_images": supplemental_summary,
            },
            "evidence_refs": issue_refs,
            "reason": str(damage.get("reason") or ""),
        },
        "claim_fact_assessment": {
            "atomic_claim_results": atomic_claims,
            "order_linkage": {
                "status": order_linkage_status,
                "reason": "争议商品与订单参考图已匹配。" if same_item is True else "争议商品身份仍需核对。",
                "evidence_refs": _refs(compact, "claimed_item"),
            },
            "scene_match": {"status": "matched", "reason": "当前诉求属于商品实体损伤审核。"},
            "assembly": {"state": "not_applicable", "reason": "本轮不是可复位装配问题。"},
        },
        "damage_observability": {
            "status": (
                "fully_observable"
                if damage.get("main_video_detail_sufficient") is True
                else "partial"
            ),
            "same_item_linkage": same_item is True,
            "claimed_region_closeup": damage.get("main_video_detail_sufficient") is True,
            "required_view_coverage": 1.0 if damage.get("main_video_detail_sufficient") is True else 0.0,
            "conflicting_evidence": damage.get("conflicting_evidence") is True,
            "missing_views": [] if damage.get("main_video_detail_sufficient") is True else ["所诉部位清晰近景"],
            "reason": str(damage.get("reason") or ""),
        },
        "adopted_evidence": frame_findings,
        "supporting_evidence": frame_findings,
        "challenging_evidence": [],
    })
    return expanded


def _stage_summary(result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: copy.deepcopy(result.get(key))
        for key in ("status", "model", "latency_seconds", "usage", "cost", "parsed")
        if result.get(key) not in (None, "", [], {})
    }


def _stage_metrics(result: Dict[str, Any]) -> Dict[str, Any]:
    usage = result.get("usage") or {}
    cost = result.get("cost") or {}
    incurred = str(result.get("status") or "").lower() not in {
        "", "skipped", "not_run", "not_incurred"
    }
    try:
        physical_calls = max(0, int(result.get("model_http_request_count") or 0))
    except (TypeError, ValueError, OverflowError):
        physical_calls = 0
    return {
        "model_calls": physical_calls or (1 if incurred else 0),
        "total_tokens": int(usage.get("total_tokens") or 0),
        "estimated_usd": float(cost.get("estimated_usd") or 0.0),
        "status": str(result.get("status") or "not_run"),
    }


def run_native_perception_pipeline(
    case: Dict[str, Any],
    video: Path,
    output_dir: Path,
    invoke_model: Callable[[Dict[str, Any]], Dict[str, Any]],
    *,
    sampling_fps: float | None = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """用一次完整视频调用返回视觉事实，再由本地规则扩展为报告契约。"""
    del video, output_dir
    working = copy.deepcopy(case)
    perception_case = copy.deepcopy(working)
    perception_case["frames"] = list(perception_case.get("frames") or [])[:24]
    perception_case.setdefault("structured_business_context", {})["analysis_mode"] = (
        "native_video_perception"
    )
    native_video = dict(perception_case.get("native_video") or {})
    effective_sampling_fps = float(sampling_fps) if sampling_fps is not None else 1.0
    native_video["sampling_fps"] = effective_sampling_fps
    perception_case["native_video"] = native_video
    native_videos = [
        {**item, "sampling_fps": effective_sampling_fps}
        for item in perception_case.get("native_videos") or []
        if isinstance(item, dict)
    ]
    if native_videos:
        perception_case["native_videos"] = native_videos
    result = invoke_model(perception_case)
    compact = copy.deepcopy(result.get("parsed") or {})
    if result.get("status") == "success":
        expanded = expand_native_video_perception(
            compact,
            working,
            sampling_fps=effective_sampling_fps,
        )
        result["compact_perception"] = compact
        result["parsed_before_boundary"] = copy.deepcopy(expanded)
        result["parsed"] = expanded
    native_metrics = _stage_metrics(result)
    result["perception_pipeline"] = {
        "model_calls": native_metrics["model_calls"],
        "channels": {"native_video": native_metrics},
        "mode": "single_complete_video_call",
    }
    return result, working
