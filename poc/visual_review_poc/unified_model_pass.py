from __future__ import annotations

from typing import Any, Dict, Iterable, List


CONTINUITY_SUBJECTS = {"shipping_package", "product_package", "claimed_item"}


def native_dimension_gaps(parsed: Dict[str, Any], scenario: str) -> List[str]:
    """原生视频没有预设帧号，按可回链时间戳检查关键结构是否真正有内容。"""
    gaps = []
    overall = parsed.get("overall_audit")
    if not isinstance(overall, dict) or not str(overall.get("conclusion") or "").strip():
        gaps.append("overall_audit")
    findings = parsed.get("frame_findings")
    if not isinstance(findings, list) or not any(
        isinstance(item, dict)
        and str(item.get("timestamp") or "").strip()
        and str(item.get("visible_facts") or "").strip()
        for item in findings
    ):
        gaps.append("frame_findings")
    continuity = parsed.get("object_continuity_assessment")
    if not isinstance(continuity, dict) or not continuity.get("continuity_verdict") or not continuity.get("tracked_subjects"):
        gaps.append("object_continuity")
    video_audit = parsed.get("video_audit_conclusion")
    opening = video_audit.get("opening_video_compliance") if isinstance(video_audit, dict) else None
    required_opening_fields = (
        "sealed_start",
        "waybill_visible",
        "single_take_continuity",
        "issue_visible_in_continuous_opening",
    )
    validated_fields = set(opening.get("validated_fields") or []) if isinstance(opening, dict) else set()
    evidence_refs = opening.get("evidence_refs") or [] if isinstance(opening, dict) else []
    evidenced_fields = {
        str(ref.get("field") or "")
        for ref in evidence_refs
        if isinstance(ref, dict) and str(ref.get("timestamp") or "").strip()
    }
    if (
        not isinstance(opening, dict)
        or not opening.get("result")
        or not isinstance(opening.get("evidence_refs"), list)
        or not all(isinstance(opening.get(field), bool) for field in required_opening_fields)
        or not set(required_opening_fields).issubset(validated_fields)
        or not set(required_opening_fields).issubset(evidenced_fields)
    ):
        gaps.append("opening_video_compliance")
    unverified_hard_failure = isinstance(opening, dict) and any(
        opening.get(field) is False
        and (field not in validated_fields or field not in evidenced_fields)
        for field in required_opening_fields
    )
    if unverified_hard_failure:
        gaps.append("opening_video_hard_failure_candidate")
    validated_atomic_fields = set(
        video_audit.get("validated_atomic_fields") or []
    ) if isinstance(video_audit, dict) else set()
    resolved_atomic_fields = {
        field
        for field in (
            "sealed_start", "waybill_visible", "continuous", "has_edit",
            "has_offscreen", "has_speed_change", "all_items_shown", "issue_visible",
        )
        if isinstance(parsed.get(field), bool)
    }
    if not resolved_atomic_fields.issubset(validated_atomic_fields):
        gaps.append("atomic_video_field_evidence")
    if scenario == "product_damage":
        damage = parsed.get("damage_causality_assessment")
        if not isinstance(damage, dict) or not damage.get("damage_presence") or not damage.get("claim_support"):
            gaps.append("damage_causality")
        claim_facts = parsed.get("claim_fact_assessment")
        if not isinstance(claim_facts, dict) or any(
            not isinstance(claim_facts.get(key), expected)
            for key, expected in (
                ("atomic_claim_results", list),
                ("order_linkage", dict),
                ("scene_match", dict),
                ("assembly", dict),
            )
        ):
            gaps.append("claim_facts")
    return sorted(gaps)


def unified_dimension_gaps(results: Iterable[Dict[str, Any]], scenario: str) -> List[str]:
    gaps = set()
    for result in results:
        targets = {
            int(value)
            for value in result.get("_input_frame_indices") or []
            if str(value).isdigit()
        }
        parsed = result.get("parsed") if isinstance(result.get("parsed"), dict) else {}
        findings = {
            int(item["global_frame_index"]): item
            for item in parsed.get("frame_findings") or []
            if (
                isinstance(item, dict)
                and str(item.get("global_frame_index") or "").isdigit()
                and int(item["global_frame_index"]) in targets
            )
        }
        if not targets:
            gaps.add("object_continuity")
        else:
            finding_subjects = {
                index: {
                    str(item.get("subject_id"))
                    for item in (findings.get(index) or {}).get("subject_visibility") or []
                    if isinstance(item, dict)
                }
                for index in findings
            }
            fully_covered = targets.issubset(findings) and all(
                finding_subjects.get(index) == CONTINUITY_SUBJECTS for index in targets
            )
            if not fully_covered:
                gaps.add("object_continuity")
        if scenario == "product_damage":
            damage = parsed.get("damage_causality_assessment")
            if not isinstance(damage, dict) or not damage.get("damage_presence") or not damage.get("claim_support"):
                gaps.add("damage_causality")
    return sorted(gaps)
