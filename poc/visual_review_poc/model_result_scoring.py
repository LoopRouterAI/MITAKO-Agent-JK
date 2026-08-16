from __future__ import annotations

from typing import Any, Dict


def score_result(result: Dict[str, Any]) -> Dict[str, Any]:
    if result.get("status") != "success":
        return {"quality": 0, "value": 0, "field_completeness": 0, "evidence_reference_score": 0}
    parsed = result.get("parsed") or {}
    hit = 1 if (result.get("evaluation") or {}).get("hit") else 0

    def value_at(path: str) -> Any:
        current: Any = parsed
        for part in path.split("."):
            if not isinstance(current, dict):
                return None
            current = current.get(part)
        return current

    required_paths = [
        "predicted_label",
        "system_yes_no",
        "confidence",
        "overall_audit.conclusion",
        "overall_audit.confidence",
        "overall_audit.core_reason",
        "overall_audit.business_follow_up_suggestion",
        "visual_qc_conclusion.verdict",
        "visual_qc_conclusion.confidence",
        "visual_qc_conclusion.core_reason",
        "video_audit_conclusion.continuity_score",
        "video_audit_conclusion.continuity_reason",
        "video_audit_conclusion.swap_risk_level",
        "video_audit_conclusion.edit_or_cut_risk",
        "adopted_evidence",
        "frame_findings",
        "business_follow_up_reason",
        "next_step",
    ]
    field_completeness = sum(1 for path in required_paths if value_at(path) not in (None, "", [])) / len(required_paths)
    adopted = parsed.get("adopted_evidence") or parsed.get("supporting_evidence") or []
    referenced = [
        item
        for item in adopted
        if isinstance(item, dict)
        and (item.get("timestamp") or item.get("global_frame_index") or item.get("frame_index") or item.get("image_index") or item.get("file"))
        and (item.get("fact") or item.get("description"))
    ]
    evidence_reference_score = min(1.0, len(referenced) / 3) if adopted else 0.0
    structured = 1 if field_completeness >= 0.85 and evidence_reference_score >= 0.67 else 0
    confidence = float(parsed.get("confidence") or 0)
    quality = hit * 35 + structured * 15 + field_completeness * 25 + evidence_reference_score * 20 + confidence * 5
    cost = float((result.get("cost") or {}).get("estimated_usd") or 0.001)
    value = quality / max(cost, 0.001)
    return {
        "quality": round(quality, 2),
        "value": round(value, 2),
        "field_completeness": round(field_completeness, 2),
        "evidence_reference_score": round(evidence_reference_score, 2),
    }
