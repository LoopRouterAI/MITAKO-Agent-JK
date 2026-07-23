# -*- coding: utf-8 -*-
"""开箱视频主体连续性的结构化校验与分段聚合。"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List
import re


VALID_VERDICTS = {"continuous", "brief_occlusion", "long_absence", "indeterminate"}
VALID_VISIBILITY = {"visible", "occluded", "out_of_frame", "not_yet_exposed", "unknown"}
CANONICAL_SUBJECTS = ("shipping_package", "product_package", "claimed_item")


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return default


def _enum(value: Any, allowed: set[str], fallback: str) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in allowed else fallback


def _events(value: Any) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for raw in value if isinstance(value, list) else []:
        if not isinstance(raw, dict):
            continue
        duration = _float(raw.get("duration_seconds"))
        result.append(
            {
                **raw,
                "visibility": _enum(raw.get("visibility") or "out_of_frame", VALID_VISIBILITY, "unknown"),
                "duration_seconds": duration,
            }
        )
    return result


def normalize_object_continuity(value: Any) -> Dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    subjects = []
    all_events: List[Dict[str, Any]] = []
    for index, raw in enumerate(source.get("tracked_subjects") or [], start=1):
        if not isinstance(raw, dict):
            continue
        events = _events(raw.get("out_of_frame_events") or raw.get("unobserved_events"))
        all_events.extend(events)
        subjects.append(
            {
                **raw,
                "subject_id": str(raw.get("subject_id") or f"subject_{index}"),
                "description": str(raw.get("description") or raw.get("subject") or "未命名主体"),
                "out_of_frame_events": events,
                "longest_out_of_frame_seconds": max(
                    (event["duration_seconds"] for event in events),
                    default=0.0,
                ),
                "visibility_coverage": min(_float(raw.get("visibility_coverage")), 1.0),
            }
        )
    longest = max((event["duration_seconds"] for event in all_events), default=0.0)
    return {
        **source,
        "tracked_subjects": subjects,
        "tracked_subject_defined": bool(subjects),
        "continuity_verdict": _enum(source.get("continuity_verdict"), VALID_VERDICTS, "indeterminate"),
        "longest_out_of_frame_seconds": longest,
        "total_unobserved_seconds": _float(source.get("total_unobserved_seconds")),
        "out_of_frame_events": all_events,
    }


def _review_output(output: Dict[str, Any], reason: str) -> Dict[str, Any]:
    output["predicted_label"] = "review"
    output["system_yes_no"] = "REVIEW"
    output["decision"] = "manual_review"
    try:
        output["confidence"] = min(float(output.get("confidence") or 0.5), 0.69)
    except (TypeError, ValueError):
        output["confidence"] = 0.5
    output["continuity_guard_reason"] = reason
    return output


def apply_object_continuity_guard(
    result: Dict[str, Any],
    scenario: str,
    has_video: bool,
    policy: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    output = dict(result)
    if not has_video or scenario not in {"video_unboxing", "wrong_item", "missing_item", "product_damage"}:
        return output
    policy = policy or {}
    warning_seconds = max(0.5, _float(policy.get("out_of_frame_warning_seconds"), 3.0))
    assessment = normalize_object_continuity(output.get("object_continuity_assessment"))
    assessment["policy"] = {
        "out_of_frame_warning_seconds": warning_seconds,
        "effect": "超过阈值建议补充连续原视频，不自动拒绝，也不单独强制人工复核",
    }
    output["object_continuity_assessment"] = assessment
    if not assessment["tracked_subject_defined"]:
        return _review_output(output, "没有定义并逐段跟踪快递包装、商品包装或争议商品主体，无法证明全程未离镜。")
    if assessment["continuity_verdict"] == "indeterminate":
        return _review_output(output, "主体连续性结论不确定，需要查看原视频和离镜时间点。")
    if assessment["continuity_verdict"] == "long_absence" or assessment["longest_out_of_frame_seconds"] >= warning_seconds:
        output["continuity_recommendation"] = "request_more_material"
        output["continuity_requires_human_review"] = False
        output["continuity_guard_reason"] = (
            f"检测到主体最长连续离镜/不可观察 {assessment['longest_out_of_frame_seconds']:.2f} 秒，"
            f"达到 {warning_seconds:.2f} 秒补件阈值；该信号不能单独证明调包、剪辑或欺诈。"
        )
        return output
    output["continuity_recommendation"] = "continue_with_warning" if assessment["longest_out_of_frame_seconds"] > 0 else "continue"
    output["continuity_requires_human_review"] = False
    output["continuity_guard_reason"] = "已按主体输出连续性时间轴，未超过配置的离镜复核阈值。"
    return output


def _seconds(value: Any) -> float | None:
    if value in (None, ""):
        return None
    text = str(value).strip().lower()
    text = re.sub(r"\s*(?:seconds?|secs?|s|秒)$", "", text)
    try:
        if ":" not in text:
            return float(text)
        parts = [float(item) for item in text.split(":")]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
    except ValueError:
        return None
    return None


def _visibility_rows(
    rows: Iterable[Dict[str, Any]],
    frames: Iterable[Dict[str, Any]],
) -> Dict[tuple[int, str], List[Dict[str, Any]]]:
    frame_registry = {
        (int(frame.get("video_index") or 0), int(frame.get("global_frame_index") or 0)): frame
        for frame in frames
        if frame.get("global_frame_index") is not None
    }
    global_registry = {
        int(frame.get("global_frame_index") or 0): frame
        for frame in frames
        if frame.get("global_frame_index") is not None
    }
    timelines: Dict[tuple[int, str], List[Dict[str, Any]]] = {}
    for row in rows:
        for finding in row.get("frame_findings") or []:
            if not isinstance(finding, dict):
                continue
            video_index = int(finding.get("video_index") or 0)
            frame_index = int(finding.get("global_frame_index") or finding.get("frame_index") or 0)
            registered = frame_registry.get((video_index, frame_index)) or global_registry.get(frame_index) or {}
            video_index = int(registered.get("video_index") or video_index)
            timestamp = _seconds(registered.get("source_timestamp") or registered.get("timestamp"))
            if timestamp is None:
                continue
            raw = finding.get("subject_visibility") or []
            if isinstance(raw, dict):
                raw = [{"subject_id": key, "state": value} for key, value in raw.items()]
            for item in raw if isinstance(raw, list) else []:
                if not isinstance(item, dict):
                    continue
                subject_id = str(item.get("subject_id") or "").strip()
                if subject_id not in CANONICAL_SUBJECTS:
                    continue
                state = _enum(item.get("state") or item.get("visibility"), VALID_VISIBILITY | {"partial"}, "unknown")
                timelines.setdefault((video_index, subject_id), []).append(
                    {
                        "video_index": video_index,
                        "timestamp": timestamp,
                        "timestamp_label": registered.get("source_timestamp") or registered.get("timestamp"),
                        "local_timestamp": registered.get("timestamp"),
                        "global_frame_index": frame_index,
                        "state": state,
                    }
                )
    for values in timelines.values():
        values.sort(key=lambda item: (item["timestamp"], int(item.get("global_frame_index") or 0)))
    return timelines


def _derived_subject(video_index: int, subject_id: str, rows: List[Dict[str, Any]]) -> Dict[str, Any] | None:
    exposed = next((index for index, item in enumerate(rows) if item["state"] in {"visible", "partial", "occluded"}), None)
    if exposed is None:
        return None
    tracked = rows[exposed:]
    events: List[Dict[str, Any]] = []
    start_index: int | None = None
    for index, item in enumerate(tracked):
        if item["state"] == "out_of_frame" and start_index is None:
            start_index = index
        elif item["state"] in {"visible", "partial"} and start_index is not None:
            start = tracked[start_index]
            before = tracked[start_index - 1] if start_index > 0 else None
            duration = max(0.0, item["timestamp"] - start["timestamp"])
            events.append(
                {
                    "start_timestamp": start["timestamp_label"],
                    "end_timestamp": item["timestamp_label"],
                    "local_start_timestamp": start.get("local_timestamp"),
                    "local_end_timestamp": item.get("local_timestamp"),
                    "duration_seconds": round(duration, 3),
                    "visibility": "out_of_frame",
                    "before_evidence": before,
                    "out_of_frame_evidence": start,
                    "after_evidence": item,
                    "identity_reestablished": False,
                    "reason": "逐帧状态只能确认主体重新入镜，不能自动证明仍为离镜前同一物件。",
                    "source": "deterministic_frame_timeline",
                }
            )
            start_index = None
    if start_index is not None:
        start = tracked[start_index]
        end = tracked[-1]
        events.append(
            {
                "start_timestamp": start["timestamp_label"],
                "end_timestamp": end["timestamp_label"],
                "local_start_timestamp": start.get("local_timestamp"),
                "local_end_timestamp": end.get("local_timestamp"),
                "duration_seconds": round(max(0.0, end["timestamp"] - start["timestamp"]), 3),
                "visibility": "out_of_frame",
                "before_evidence": tracked[start_index - 1] if start_index > 0 else None,
                "out_of_frame_evidence": start,
                "after_evidence": None,
                "identity_reestablished": False,
                "reason": "主体离镜后直到最后一个送审帧仍未恢复。",
                "source": "deterministic_frame_timeline",
            }
        )
    visible = [item for item in tracked if item["state"] in {"visible", "partial"}]
    return {
        "subject_id": subject_id,
        "video_index": video_index,
        "description": {
            "shipping_package": "快递包装",
            "product_package": "商品包装/承载物",
            "claimed_item": "争议商品本体",
        }[subject_id],
        "tracking_start": tracked[0]["timestamp_label"],
        "tracking_end": tracked[-1]["timestamp_label"],
        "first_exposed_timestamp": tracked[0]["timestamp_label"],
        "visibility_coverage": round(len(visible) / max(len(tracked), 1), 4),
        "unknown_frame_count": sum(item["state"] == "unknown" for item in tracked),
        "out_of_frame_events": events,
        "longest_out_of_frame_seconds": max((item["duration_seconds"] for item in events), default=0.0),
        "timeline_source": "frame_findings.subject_visibility",
    }


def aggregate_object_continuity(
    rows: Iterable[Dict[str, Any]],
    frames: Iterable[Dict[str, Any]] | None = None,
    policy: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    rows = list(rows)
    frames = list(frames or [])
    assessments = [normalize_object_continuity(row.get("object_continuity_assessment")) for row in rows]
    timelines = _visibility_rows(rows, frames)
    derived = [
        _derived_subject(video_index, subject_id, values)
        for (video_index, subject_id), values in timelines.items()
    ]
    derived_subjects = [item for item in derived if item]
    subjects = derived_subjects or [subject for item in assessments for subject in item.get("tracked_subjects") or []]
    longest = max((subject.get("longest_out_of_frame_seconds") or 0 for subject in subjects), default=0.0)
    warning_seconds = max(0.5, _float((policy or {}).get("out_of_frame_warning_seconds"), 3.0))
    verdicts = {item["continuity_verdict"] for item in assessments}
    unresolved = any(
        event.get("identity_reestablished") is False
        for subject in subjects
        for event in subject.get("out_of_frame_events") or []
    ) or any(int(subject.get("unknown_frame_count") or 0) > 0 for subject in subjects)
    if unresolved:
        verdict = "indeterminate"
    elif longest > warning_seconds:
        verdict = "long_absence"
    elif longest > 0:
        verdict = "brief_occlusion"
    elif "indeterminate" in verdicts or not subjects:
        verdict = "indeterminate"
    elif "brief_occlusion" in verdicts:
        verdict = "brief_occlusion"
    else:
        verdict = "continuous"
    return normalize_object_continuity(
        {
            "tracked_subjects": subjects,
            "continuity_verdict": verdict,
            "longest_out_of_frame_seconds": longest,
            "total_unobserved_seconds": round(sum(
                event.get("duration_seconds") or 0
                for subject in subjects
                for event in subject.get("out_of_frame_events") or []
            ), 3),
            "segment_assessments": assessments,
            "timeline_derivation": "deterministic_frame_timeline" if derived_subjects else "model_segment_summary",
        }
    )
