# -*- coding: utf-8 -*-
"""原生视频紧凑感知结果与现有审核契约之间的共享适配。"""
from __future__ import annotations

import copy
import math
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Tuple

import cv2

from poc.visual_review_poc.local_video_triage_demo import format_time


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


def _refs(parsed: Dict[str, Any], field: str) -> List[Dict[str, Any]]:
    return [
        {
            "field": field,
            "video_index": 1,
            "timestamp": str(item.get("timestamp") or ""),
            "asset_ref": str(item.get("asset_ref") or "native_video_1"),
            "visible_facts": str(item.get("fact") or ""),
        }
        for item in parsed.get("evidence_refs") or []
        if isinstance(item, dict)
        and item.get("field") == field
        and str(item.get("asset_ref") or "").strip() == "native_video_1"
        and str(item.get("timestamp") or "").strip()
        and str(item.get("fact") or "").strip()
    ]


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

_EVIDENCE_FIELDS = frozenset((*_ATOMIC_VIDEO_FIELDS, "claimed_item", "supplemental_damage_visible"))


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


def _derive_overall_video_result(compact: Dict[str, Any]) -> str:
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
        str(item.get("field") or "")
        for item in compact.get("evidence_refs") or []
        if isinstance(item, dict)
        and str(item.get("asset_ref") or "").strip() == "native_video_1"
        and str(item.get("timestamp") or "").strip()
        and str(item.get("fact") or "").strip()
    }
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
    sealed = compact.get("sealed_start")
    continuous = compact.get("continuous")
    confidences = _normalized_field_confidences(compact.get("field_confidences"))
    confidence_values = []
    for field in ("sealed_start", "continuous"):
        try:
            value = float(confidences.get(field))
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(value):
            confidence_values.append(max(0.0, min(value, 1.0)))
    present = sealed is True and continuous is True
    reason = (
        "现有材料包含从封箱状态连续记录初次拆开包裹的开箱视频证据。"
        if present
        else "现有材料没有形成可信的初次开箱证据：未同时确认封箱起始与连续拆封过程。"
    )
    return {
        "present": present,
        "status": "pass" if present else "yellow",
        "confidence": round(min(confidence_values), 4) if confidence_values else None,
        "reason": reason,
        "evidence_refs": _refs(compact, "sealed_start") + _refs(compact, "continuous"),
        "derivation": "sealed_start_and_continuous",
    }


def expand_native_video_perception(
    parsed: Dict[str, Any],
    case: Dict[str, Any],
    *,
    sampling_fps: float,
) -> Dict[str, Any]:
    """将紧凑九字段事实扩展到现有报告、决策和安全投影共用契约。"""
    compact = copy.deepcopy(parsed)
    compact["evidence_refs"] = [
        item
        for item in compact.get("evidence_refs") or []
        if isinstance(item, dict) and item.get("field") in _EVIDENCE_FIELDS
    ]
    compact["field_confidences"] = _normalized_field_confidences(
        compact.get("field_confidences")
    )
    result = _derive_overall_video_result(compact)
    compact["overall_video_result"] = result
    label = {"compliant": "positive", "noncompliant": "negative"}.get(result, "review")
    confidence = _overall_evidence_confidence(compact)
    claimed = compact.get("claimed_item_assessment") or {}
    speed = compact.get("speed_assessment") or {}
    damage = compact.get("damage_assessment") or {}

    frame_findings = []
    for item in compact.get("evidence_refs") or []:
        if not isinstance(item, dict):
            continue
        timestamp = str(item.get("timestamp") or "").strip()
        fact = str(item.get("fact") or "").strip()
        if timestamp and fact:
            frame_findings.append({
                "video_index": 1,
                "timestamp": timestamp,
                "visible_facts": fact,
                "evidence_field": str(item.get("field") or ""),
                "asset_ref": str(item.get("asset_ref") or "native_video_1"),
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
        "sealed_start": compact.get("sealed_start"),
        "waybill_visible": compact.get("waybill_visible"),
        "single_take_continuity": compact.get("continuous"),
        "issue_visible_in_continuous_opening": compact.get("issue_visible"),
    }
    opening_ref_fields = {
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
    if opening_result == "compliant" and len(validated_opening_fields) != len(opening_fields):
        opening_result = "indeterminate"
    opening = {
        **opening_fields,
        "result": opening_result,
        "evidence_refs": opening_refs,
        "validated_fields": validated_opening_fields,
        "field_sources": {field: "native_full_video_perception" for field in opening_fields},
        "source": "native_full_video_perception",
    }

    speed_value = str(speed.get("value") or "unknown")
    speed_affects = speed.get("affects_visual_judgement")
    speed_status = (
        "material" if speed_value == "accelerated" and speed_affects is True
        else "none" if speed_value in {"normal", "accelerated"} and speed_affects is False
        else "none" if speed_value == "normal"
        else "uncertain"
    )
    affected_items = (
        ["opening_action", "claimed_item_presentation", "issue_first_visible"]
        if speed_affects is True else []
    )
    critical_observable = False if speed_affects is True else True if speed_value == "accelerated" else None

    issue_visible = compact.get("issue_visible")
    same_item = damage.get("same_item_linkage")
    damage_presence = "confirmed" if issue_visible is True else "not_visible" if issue_visible is False else "uncertain"
    severity = {
        "level": str(damage.get("severity_level") or "unknown"),
        "structural_failure": damage.get("structural_failure"),
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
        and str(item.get("asset_ref") or "").strip() == "native_video_1"
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
    direct_chain_complete = (
        len(stage_items) == 3
        and all(value is not None for value in stage_times)
        and stage_times[0] < stage_times[1] < stage_times[2]
        and len({str(item.get("subject")).strip() for item in stage_items}) == 1
        and len({str(item.get("location")).strip() for item in stage_items}) == 1
        and len({str(item.get("chain_id")).strip() for item in stage_items}) == 1
        and stage_items[0].get("damage_visible") is False
        and stage_items[2].get("damage_visible") is True
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
                "timestamp": str(item.get("timestamp") or ""),
                "fact": str(item.get("fact") or ""),
                "subject": str(item.get("subject") or ""),
                "location": str(item.get("location") or ""),
                "chain_id": str(item.get("chain_id") or ""),
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
        "damage_presence": damage_presence,
        "claim_support": claim_support,
        "detail_sufficient": damage.get("main_video_detail_sufficient"),
        "referenced_count": len(issue_refs),
        "evidence_refs": issue_refs,
    }
    supplemental_count = len(case.get("supplemental_images") or [])
    supplemental_visible = damage.get("supplemental_damage_visible")
    supplemental_refs = _supplemental_damage_refs(compact)
    supplemental_confirmed = supplemental_visible is True and bool(supplemental_refs)
    supplemental_summary = {
        "provided_count": supplemental_count,
        "referenced_count": len(supplemental_refs),
        "damage_presence": "confirmed" if supplemental_confirmed else "not_assessed",
        "linkage_status": "verified" if supplemental_confirmed and same_item is True else "not_assessed",
        "evidence_refs": supplemental_refs,
    }

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
                "source": "native_full_video_perception",
            },
            "opening_video_compliance": opening,
            "validated_atomic_fields": validated_atomic_fields,
            "sampling_boundary_status": "covered",
            "technical_timeline_status": "native_full_video",
            "evidence_continuity_status": continuity_verdict,
            "source": "global_timeline_aggregation",
        },
        "damage_causality_assessment": {
            "damage_presence": damage_presence,
            "main_video_detail_sufficient": damage.get("main_video_detail_sufficient"),
            "supplemental_damage_presence": supplemental_summary["damage_presence"],
            "damage_type_and_location": str(damage.get("location") or ""),
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
            "atomic_claim_results": [],
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
                "clear"
                if damage.get("main_video_detail_sufficient") is True
                else "limited"
            ),
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
    effective_sampling_fps = 1.0
    if sampling_fps is not None:
        effective_sampling_fps = float(sampling_fps)
        native_video["sampling_fps"] = effective_sampling_fps
    else:
        native_video.pop("sampling_fps", None)
    perception_case["native_video"] = native_video
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
