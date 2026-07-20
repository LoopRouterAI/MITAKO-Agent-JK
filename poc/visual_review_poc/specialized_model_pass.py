from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional, Tuple



VALID_CONTINUITY_STATES = {"visible", "partial", "occluded", "out_of_frame", "not_yet_exposed", "unknown"}
CONTINUITY_SUBJECTS = {"shipping_package", "product_package", "claimed_item"}
OPENING_STAGES = {"sealed_package", "opening_in_progress", "item_exposed", "contents_displayed", "post_opening", "unknown"}


def _frame_index(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    text = str(value or "").strip()
    return int(text) if text.isdigit() else None


def _validate_findings(mode: str, findings: Any, target_indices: List[Any]) -> str:
    if not isinstance(findings, list):
        return "frame_findings_not_array"
    indices = [_frame_index(item.get("global_frame_index")) for item in findings if isinstance(item, dict)]
    normalized_targets = [_frame_index(item) for item in target_indices]
    if (
        None in indices
        or None in normalized_targets
        or len(indices) != len(normalized_targets)
        or set(indices) != set(normalized_targets)
        or len(indices) != len(set(indices))
    ):
        return "target_frame_coverage_invalid"
    if mode == "object_continuity_only":
        for item in findings:
            if not isinstance(item, dict) or str(item.get("opening_stage") or "") not in OPENING_STAGES:
                return "opening_stage_invalid"
            visibility = item.get("subject_visibility") if isinstance(item, dict) else None
            if not isinstance(visibility, list):
                return "subject_visibility_missing"
            subjects = {
                str(subject.get("subject_id")): str(subject.get("state") or subject.get("visibility"))
                for subject in visibility
                if isinstance(subject, dict)
            }
            if set(subjects) != CONTINUITY_SUBJECTS or any(state not in VALID_CONTINUITY_STATES for state in subjects.values()):
                return "subject_visibility_invalid"
    if mode == "damage_causality_only":
        for item in findings:
            if not isinstance(item, dict) or not item.get("timestamp") or not item.get("visible_facts"):
                return "causality_frame_finding_invalid"
    return ""


def run_specialized_frame_pass(
    case: Dict[str, Any],
    *,
    mode: str,
    target_index_key: str,
    chunk_size: int,
    context_frame_count: int,
    workers: int,
    invoke: Callable[[Dict[str, Any]], Dict[str, Any]],
    repair_attempts: int = 0,
    preserve_partial_coverage: bool = False,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    frames = case.get("frames") or []
    targets = [frames[index:index + chunk_size] for index in range(0, len(frames), chunk_size)]

    def invoke_prepared(pass_case: Dict[str, Any]) -> Dict[str, Any]:
        result = invoke(pass_case)
        result["input_representation"] = "individual_frames"
        result["model_image_count"] = len(pass_case["frames"])
        return result

    def merge_billing(primary: Dict[str, Any], repair: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(primary)
        primary_usage = primary.get("usage") if isinstance(primary.get("usage"), dict) else {}
        repair_usage = repair.get("usage") if isinstance(repair.get("usage"), dict) else {}
        merged["usage"] = {
            key: int(primary_usage.get(key) or 0) + int(repair_usage.get(key) or 0)
            for key in ("input_tokens", "output_tokens", "total_tokens")
        }
        primary_cost = primary.get("cost") if isinstance(primary.get("cost"), dict) else {}
        repair_cost = repair.get("cost") if isinstance(repair.get("cost"), dict) else {}
        merged["cost"] = {
            "estimated_usd": round(
                float(primary_cost.get("estimated_usd") or 0)
                + float(repair_cost.get("estimated_usd") or 0),
                6,
            )
        }
        statuses = {str(primary.get("cost_status") or ""), str(repair.get("cost_status") or "")}
        merged["cost_status"] = "partial_unknown" if "unknown" in statuses else "estimated"
        merged["latency_seconds"] = round(
            float(primary.get("latency_seconds") or 0) + float(repair.get("latency_seconds") or 0),
            2,
        )
        merged["model_image_count"] = int(primary.get("model_image_count") or 0) + int(repair.get("model_image_count") or 0)
        merged["repair_calls"] = int(primary.get("repair_calls") or 0) + 1
        return merged

    def review(index: int, target: List[Dict[str, Any]]) -> Dict[str, Any]:
        start = index * chunk_size
        pass_case = dict(case)
        pass_case["frames"] = frames[max(0, start - context_frame_count):start] + target
        pass_case["supplemental_images"] = []
        structured = dict(case.get("structured_business_context") or {})
        structured.update(
            {
                "analysis_mode": mode,
                f"{mode}_chunk": {"index": index + 1, "total": len(targets)},
                target_index_key: [item.get("global_frame_index") for item in target],
            }
        )
        pass_case["structured_business_context"] = structured
        result = invoke_prepared(pass_case)
        if result.get("status") == "success":
            target_indices = [item.get("global_frame_index") for item in target]
            allowed = set(target_indices)
            parsed = dict(result.get("parsed") or {})
            normalized_findings = []
            for item in parsed.get("frame_findings") or []:
                if not isinstance(item, dict):
                    continue
                index_value = _frame_index(item.get("global_frame_index"))
                if index_value not in allowed:
                    continue
                normalized_findings.append({**item, "global_frame_index": index_value})
            parsed["frame_findings"] = normalized_findings
            by_index = {}
            for item in normalized_findings:
                by_index.setdefault(item.get("global_frame_index"), item)
            parsed["frame_findings"] = [
                by_index[item] for item in target_indices if item in by_index
            ]
            validation_error = _validate_findings(mode, parsed.get("frame_findings"), target_indices)
            found_indices = {
                item.get("global_frame_index")
                for item in parsed.get("frame_findings") or []
                if isinstance(item, dict)
            }
            missing_indices = [item for item in target_indices if item not in found_indices]
            if validation_error == "target_frame_coverage_invalid" and repair_attempts > 0 and missing_indices:
                repair_case = dict(pass_case)
                repair_case["frames"] = [
                    item for item in target if item.get("global_frame_index") in set(missing_indices)
                ]
                repair_structured = dict(structured)
                repair_structured[target_index_key] = missing_indices
                repair_structured["specialized_repair"] = {
                    "attempt": 1,
                    "missing_target_count": len(missing_indices),
                }
                repair_case["structured_business_context"] = repair_structured
                repair = invoke_prepared(repair_case)
                result = merge_billing(result, repair)
                if repair.get("status") != "success" and not preserve_partial_coverage:
                    return {**result, "status": "failed", "error": "specialized_repair_failed", "parsed": {}}
                repair_parsed = dict(repair.get("parsed") or {}) if repair.get("status") == "success" else {}
                repair_findings = [
                    {**item, "global_frame_index": _frame_index(item.get("global_frame_index"))}
                    for item in (repair_parsed.get("frame_findings") or [])
                    if isinstance(item, dict)
                    and _frame_index(item.get("global_frame_index")) in set(missing_indices)
                ]
                repair_error = _validate_findings(mode, repair_findings, missing_indices)
                if repair_error and not preserve_partial_coverage:
                    return {**result, "status": "failed", "error": repair_error, "parsed": {}}
                by_index.update({item.get("global_frame_index"): item for item in repair_findings})
                parsed["frame_findings"] = [by_index[item] for item in target_indices if item in by_index]
                if mode == "damage_causality_only" and not isinstance(parsed.get("damage_causality_assessment"), dict):
                    parsed["damage_causality_assessment"] = repair_parsed.get("damage_causality_assessment")
                validation_error = _validate_findings(mode, parsed.get("frame_findings"), target_indices)
            missing_after_repair = [item for item in target_indices if item not in by_index]
            if (
                preserve_partial_coverage
                and validation_error == "target_frame_coverage_invalid"
                and missing_after_repair
            ):
                target_by_index = {item.get("global_frame_index"): item for item in target}
                for missing_index in missing_after_repair:
                    source = target_by_index[missing_index]
                    unknown = {
                        "global_frame_index": missing_index,
                        "video_index": source.get("video_index"),
                        "timestamp": source.get("timestamp") or "unknown",
                        "visible_facts": "模型未返回该帧的结构化观察，不能据此判断画面事实。",
                        "observation_status": "model_output_missing",
                    }
                    if mode == "object_continuity_only":
                        unknown.update({
                            "opening_stage": "unknown",
                            "subject_visibility": [
                                {"subject_id": subject, "state": "unknown"}
                                for subject in sorted(CONTINUITY_SUBJECTS)
                            ],
                        })
                    by_index[missing_index] = unknown
                parsed["frame_findings"] = [by_index[item] for item in target_indices]
                parsed["specialized_coverage"] = {
                    "status": "partial_unknown",
                    "target_frame_count": len(target_indices),
                    "model_observed_frame_count": len(target_indices) - len(missing_after_repair),
                    "missing_target_frame_indices": missing_after_repair,
                }
                result["coverage_status"] = "partial_unknown"
                result["missing_target_frame_indices"] = missing_after_repair
                validation_error = _validate_findings(mode, parsed.get("frame_findings"), target_indices)
            if validation_error:
                return {**result, "status": "failed", "error": validation_error, "parsed": {}}
            if mode == "damage_causality_only" and not isinstance(parsed.get("damage_causality_assessment"), dict):
                if not preserve_partial_coverage:
                    return {**result, "status": "failed", "error": "damage_causality_assessment_missing", "parsed": {}}
                parsed["damage_causality_assessment"] = {
                    "damage_presence": "uncertain",
                    "damage_type_and_location": "模型未返回本段损伤归因总评。",
                    "pre_opening_state_visible": False,
                    "opening_action_visible": False,
                    "damage_change_observed": False,
                    "damage_timing": "unknown",
                    "most_likely_origin": "unknown",
                    "origin_confidence": 0.0,
                    "causal_evidence_level": "insufficient",
                    "claim_support": "insufficient",
                    "possible_origins": [],
                    "before_action_evidence": [],
                    "action_evidence": [],
                    "after_action_evidence": [],
                }
                result["coverage_status"] = "partial_unknown"
                result["assessment_status"] = "model_output_missing"
                result["coverage_gap_reason"] = "damage_causality_assessment_missing"
                parsed["specialized_coverage"] = {
                    **(parsed.get("specialized_coverage") or {}),
                    "status": "partial_unknown",
                    "assessment_status": "model_output_missing",
                    "reason": "damage_causality_assessment_missing",
                }
            result["parsed"] = parsed
        return result

    completed: List[Optional[Dict[str, Any]]] = [None] * len(targets)
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(targets) or 1))) as pool:
        futures = {pool.submit(review, index, target): index for index, target in enumerate(targets)}
        for future in as_completed(futures):
            index = futures[future]
            try:
                completed[index] = future.result()
            except Exception as exc:
                completed[index] = {"status": "failed", "error": str(exc)[:500]}
    results = [item for item in completed if item and item.get("status") == "success"]
    failures = [
        {
            "chunk_index": index + 1,
            "error": (item or {}).get("error") or (item or {}).get("status") or "empty_result",
            "usage": (item or {}).get("usage") or {},
            "cost": (item or {}).get("cost") or {},
            "cost_status": (item or {}).get("cost_status") or "",
            "latency_seconds": (item or {}).get("latency_seconds") or 0,
            "repair_calls": int((item or {}).get("repair_calls") or 0),
        }
        for index, item in enumerate(completed)
        if not item or item.get("status") != "success"
    ]
    return results, failures
