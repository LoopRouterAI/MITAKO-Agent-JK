from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional, Tuple


VALID_CONTINUITY_STATES = {"visible", "partial", "occluded", "out_of_frame", "not_yet_exposed", "unknown"}
CONTINUITY_SUBJECTS = {"shipping_package", "product_package", "claimed_item"}


def _validate_findings(mode: str, findings: Any, target_indices: List[Any]) -> str:
    if not isinstance(findings, list):
        return "frame_findings_not_array"
    indices = [item.get("global_frame_index") for item in findings if isinstance(item, dict)]
    if len(indices) != len(target_indices) or set(indices) != set(target_indices) or len(indices) != len(set(indices)):
        return "target_frame_coverage_invalid"
    if mode == "object_continuity_only":
        for item in findings:
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
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    frames = case.get("frames") or []
    targets = [frames[index:index + chunk_size] for index in range(0, len(frames), chunk_size)]

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
        result = invoke(pass_case)
        if result.get("status") == "success":
            allowed = {item.get("global_frame_index") for item in target}
            parsed = dict(result.get("parsed") or {})
            parsed["frame_findings"] = [
                item
                for item in (parsed.get("frame_findings") or [])
                if item.get("global_frame_index") in allowed
            ]
            validation_error = _validate_findings(mode, parsed.get("frame_findings"), list(allowed))
            if validation_error:
                return {"status": "failed", "error": validation_error}
            if mode == "damage_causality_only" and not isinstance(parsed.get("damage_causality_assessment"), dict):
                return {"status": "failed", "error": "damage_causality_assessment_missing"}
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
        {"chunk_index": index + 1, "error": (item or {}).get("error") or (item or {}).get("status") or "empty_result"}
        for index, item in enumerate(completed)
        if not item or item.get("status") != "success"
    ]
    return results, failures
