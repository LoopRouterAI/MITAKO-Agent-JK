# -*- coding: utf-8 -*-
"""审核结果的可配置规则判定层。"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Optional


DEFAULT_PRODUCT_DAMAGE_POLICY_REF = "MITAKO-PD-ADVISORY@20260728.1"


APPROVED_POLICY_SNAPSHOTS: Dict[Any, Dict[str, Any]] = {
    ("mitako", DEFAULT_PRODUCT_DAMAGE_POLICY_REF): {
        "mode": "classification_recommendation",
        "opening_video_required": True,
        "missing_required_opening_video": "negative",
        "complete_video_no_claimed_damage": "negative",
        "require_claim_scope": True,
        "minimum_visibility_coverage": 0.8,
        "minimum_required_view_coverage": 0.8,
        "minimum_confidence": 0.8,
        "require_continuity_complete": True,
        "require_fully_observable": True,
        "require_claimed_region_closeup": True,
        "require_same_item_linkage": True,
        "require_media_forensics": False,
        "maximum_forensic_risk": "medium",
        "max_unobserved_seconds": 3.0,
    },
    ("mitako", "MITAKO-PD-MISSING-OPENING@20260717.1"): {
        "mode": "classification_recommendation",
        "opening_video_required": True,
        "missing_required_opening_video": "negative",
        "complete_video_no_claimed_damage": "review",
        "require_claim_scope": True,
    },
    ("mitako", "MITAKO-PD-COMPLETE-NO-DAMAGE@20260720.1"): {
        "mode": "classification_recommendation",
        "complete_video_no_claimed_damage": "negative",
        "require_claim_scope": True,
        "minimum_visibility_coverage": 0.85,
        "minimum_required_view_coverage": 1.0,
        "minimum_confidence": 0.8,
        "require_continuity_complete": True,
        "require_fully_observable": True,
        "require_claimed_region_closeup": True,
        "require_same_item_linkage": True,
        "require_media_forensics": True,
        "maximum_forensic_risk": "low",
        "max_unobserved_seconds": 0.0,
    },
}


def _dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(float(value), 1.0))
    except (TypeError, ValueError):
        return default


def _nonnegative_float(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return default


def _first_float(values: Iterable[Any], default: float = 0.0) -> float:
    for value in values:
        if value not in (None, ""):
            return _float(value, default)
    return default


def _has_video(assets: Iterable[Dict[str, Any]]) -> bool:
    return any(str(item.get("mime_type") or "").lower().startswith("video/") for item in assets)


def _claim_scope_ready(scope: Dict[str, Any], fallback_claim: str) -> bool:
    active = {str(value).strip() for value in scope.get("active_claim_ids") or [] if str(value).strip()}
    claims = {
        str(item.get("claim_id") or "").strip(): item
        for item in scope.get("claims") or []
        if isinstance(item, dict) and str(item.get("claim_id") or "").strip()
    }
    if active:
        return scope.get("split_status") == "resolved" and active.issubset(claims)
    return scope.get("split_status") == "single_legacy" and bool(
        str(scope.get("claim_text") or fallback_claim or "").strip()
    ) and bool(scope.get("issue_types"))


def _visibility_coverage(continuity: Dict[str, Any]) -> Optional[float]:
    values = [
        _float(item.get("visibility_coverage"))
        for item in continuity.get("tracked_subjects") or []
        if isinstance(item, dict) and str(item.get("subject_id") or "") == "claimed_item"
    ]
    return min(values) if values else None


def _claimed_item_longest_absence(continuity: Dict[str, Any]) -> Optional[float]:
    values = [
        _nonnegative_float(item.get("longest_out_of_frame_seconds"))
        for item in continuity.get("tracked_subjects") or []
        if isinstance(item, dict) and str(item.get("subject_id") or "") == "claimed_item"
    ]
    return max(values) if values else None


def _apply_negative(review: Dict[str, Any], audit: Dict[str, Any], confidence: float) -> Dict[str, Any]:
    output = dict(review)
    agent_report = _dict(output.get("agent_report"))
    parsed = _dict(agent_report.get("parsed"))
    previous_overall = _dict(parsed.get("overall_audit"))
    audit["evidence_verdict_before_policy"] = {
        "predicted_label": parsed.get("predicted_label"),
        "confidence": parsed.get("confidence"),
        "conclusion": previous_overall.get("conclusion") or "",
    }
    parsed.update(
        {
            "predicted_label": "negative",
            "system_yes_no": "NO",
            "decision": "fail",
            "confidence": round(confidence, 4),
            "business_action_allowed": False,
            "human_required": False,
            "human_required_for_business_action": True,
            "decision_policy_audit": audit,
            "overall_audit": {
                "conclusion": audit.get("reason") or "当前材料未满足甲方已批准的审核规则。",
                "confidence": round(confidence, 4),
                "core_reason": "这是甲方版本化材料规则的分类建议，不等同于视觉证明商品无损，也不自动触发拒绝业务动作。",
                "business_follow_up_suggestion": "如需继续支持本次诉求，请补齐规则要求的证据后重新提交；最终业务处理由甲方系统和授权人员决定。",
            },
        }
    )
    agent_report["parsed"] = parsed
    output["agent_report"] = agent_report
    summary = _dict(output.get("summary"))
    summary.update(
        {
            "predicted_label": "negative",
            "system_yes_no": "NO",
            "confidence": round(confidence, 4),
            "decision_policy_applied": True,
        }
    )
    output["summary"] = summary
    brief = _dict(output.get("agent_brief"))
    brief.update(
        {
            "conclusion": audit.get("reason") or "当前材料未满足甲方已批准的审核规则。",
            "next_step": "补齐规则要求的证据后重新提交，或由授权人员结合业务规则复核。",
            "confidence": round(confidence, 4),
        }
    )
    output["agent_brief"] = brief
    output["decision_policy_audit"] = audit
    return output


def apply_review_decision_policy(
    job: Dict[str, Any],
    review: Dict[str, Any],
    media_forensics: Optional[Dict[str, Any]] = None,
    approved_policies: Optional[Mapping[Any, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """在模型与证据守卫之后应用甲方显式开启的分类建议规则。"""
    metadata = _dict(job.get("metadata"))
    requested_policy = _dict(metadata.get("decision_policy"))
    policy_ref = str(requested_policy.get("policy_ref") or "").strip()
    registry = approved_policies if approved_policies is not None else APPROVED_POLICY_SNAPSHOTS
    tenant_id = str(job.get("tenant_id") or metadata.get("tenant_id") or "").strip()
    approved_snapshot = {}
    if policy_ref:
        approved_snapshot = _dict(registry.get((tenant_id, policy_ref)))
        if approved_policies is not None and not approved_snapshot:
            approved_snapshot = _dict(registry.get(policy_ref))
    policy = {**approved_snapshot, "policy_ref": policy_ref} if approved_snapshot else requested_policy
    scope = _dict(metadata.get("claim_scope"))
    scenario = str(job.get("scenario") or metadata.get("scenario") or "")
    agent_report = _dict(review.get("agent_report"))
    parsed = _dict(agent_report.get("parsed"))
    damage = _dict(parsed.get("damage_causality_assessment"))
    continuity = _dict(parsed.get("object_continuity_assessment"))
    video_audit = _dict(parsed.get("video_audit_conclusion"))
    observability = _dict(parsed.get("damage_observability"))
    evidence_sources = _dict(damage.get("evidence_source_summary"))
    supplemental = _dict(evidence_sources.get("supplemental_images"))
    forensics = _dict(media_forensics)
    forensic_summary = _dict(forensics.get("summary"))
    has_video = _has_video(job.get("assets") or [])
    scope_ready = _claim_scope_ready(scope, str(metadata.get("customer_claim") or ""))
    coverage = _visibility_coverage(continuity)
    claimed_item_longest_absence = _claimed_item_longest_absence(continuity)
    model_confidence = _first_float(
        [parsed.get("confidence"), _dict(review.get("summary")).get("confidence")],
        0.0,
    )
    audit: Dict[str, Any] = {
        "version": "2026-07-17.1",
        "mode": policy.get("mode") or "conservative_review",
        "policy_ref": policy_ref,
        "policy_source": "server_approved_registry" if approved_snapshot else "not_approved",
        "requested_overrides_ignored": sorted(
            key for key in requested_policy if key not in {"mode", "policy_ref"}
        ),
        "applied": False,
        "rule_id": "",
        "claim_scope": {
            "claim_id": scope.get("claim_id") or "",
            "stage": scope.get("stage") or "initial",
            "issue_types": scope.get("issue_types") or [],
            "excluded_issue_types": scope.get("excluded_issue_types") or [],
            "active_claim_ids": scope.get("active_claim_ids") or [],
            "split_status": scope.get("split_status") or "unresolved",
            "ready": scope_ready,
        },
        "evidence_gate": {
            "video_present": has_video,
            "continuity_verdict": continuity.get("continuity_verdict") or "indeterminate",
            "claimed_item_visibility_coverage": coverage,
            "damage_presence": damage.get("damage_presence") or "uncertain",
            "claim_support": damage.get("claim_support") or "insufficient",
            "damage_observability": observability.get("status") or "unknown",
            "model_confidence": model_confidence,
            "media_forensics_status": forensics.get("status") or "not_provided",
            "media_forensics_risk_level": forensic_summary.get("risk_level") or "unknown",
            "supplemental_linkage_status": supplemental.get("linkage_status") or "not_provided",
        },
        "business_boundary": "该结果仅是审核分类建议，不自动执行拒绝、退款、补发、换货或最终定责。",
    }
    output = dict(review)
    output["decision_policy_audit"] = audit
    output_agent_report = _dict(output.get("agent_report"))
    output_parsed = _dict(output_agent_report.get("parsed"))
    output_parsed["decision_policy_audit"] = audit
    output_agent_report["parsed"] = output_parsed
    output["agent_report"] = output_agent_report

    if scenario != "product_damage" or requested_policy.get("mode") != "classification_recommendation":
        audit["reason"] = "未启用商品有伤规则分类建议。"
        return output
    if not policy_ref:
        audit["reason"] = "未提供服务端已批准的版本化策略引用，保持人工复核。"
        return output
    if not approved_snapshot:
        audit["reason"] = "策略版本未在服务端批准策略注册表中启用，保持人工复核。"
        return output
    if policy.get("require_claim_scope", True) and not scope_ready:
        audit["reason"] = "未提供可审计的本次诉求范围，保持人工复核。"
        return output

    if policy.get("opening_video_required") is True and not has_video:
        if policy.get("missing_required_opening_video") == "negative":
            audit.update(
                {
                    "applied": True,
                    "rule_id": "PD-N-OPENING-VIDEO-REQUIRED",
                    "reason": "甲方策略要求商品有伤必须提交开箱视频，本案未提交，当前材料不支持本次诉求。",
                }
            )
            return _apply_negative(output, audit, 0.99)
        audit["reason"] = "缺少策略要求的开箱视频，但甲方策略仍要求人工复核。"
        return output

    if policy.get("complete_video_no_claimed_damage") == "negative":
        minimum_coverage = _float(policy.get("minimum_visibility_coverage"), 0.95)
        minimum_view_coverage = _float(policy.get("minimum_required_view_coverage"), 1.0)
        minimum_confidence = max(0.8, _float(policy.get("minimum_confidence"), 0.8))
        require_continuity_complete = policy.get("require_continuity_complete", True) is not False
        require_fully_observable = policy.get("require_fully_observable", True) is not False
        require_claimed_region_closeup = policy.get("require_claimed_region_closeup", True) is not False
        require_same_item_linkage = policy.get("require_same_item_linkage", True) is not False
        max_unobserved_seconds = _nonnegative_float(policy.get("max_unobserved_seconds"), 0.0)
        continuity_complete = continuity.get("continuity_verdict") == "continuous"
        opening_complete = str(video_audit.get("opening_integrity") or "").lower() in {
            "complete", "完整", "完整开箱", "complete_opening"
        } and video_audit.get("opening_integrity_source") == "full_timeline_continuity"
        damage_not_visible = damage.get("damage_presence") == "not_visible"
        support_not_found = damage.get("claim_support") == "not_supported"
        enough_coverage = coverage is not None and coverage >= minimum_coverage
        enough_confidence = model_confidence >= minimum_confidence
        fully_observable = observability.get("status") == "fully_observable"
        same_item_linked = observability.get("same_item_linkage") is True
        closeup_complete = observability.get("claimed_region_closeup") is True
        view_coverage = _float(observability.get("required_view_coverage"))
        required_views_complete = view_coverage >= minimum_view_coverage
        no_conflict = observability.get("conflicting_evidence") is not True
        no_unobserved_time = (
            claimed_item_longest_absence is not None
            and claimed_item_longest_absence <= max_unobserved_seconds
        )
        continuity_gate = not require_continuity_complete or continuity_complete
        observability_gate = (
            (not require_fully_observable or fully_observable)
            and required_views_complete
            and no_conflict
            and (not require_same_item_linkage or same_item_linked)
            and (not require_claimed_region_closeup or closeup_complete)
        )
        pass_integrity = (
            parsed.get("pass_integrity_status") in {None, "", "complete"}
            and not parsed.get("specialized_pass_guard_reason")
            and not (parsed.get("aggregation_warnings") or [])
        )
        sampling_boundary_covered = video_audit.get("sampling_boundary_status") == "covered"
        forensic_rank = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
        maximum_forensic_risk = str(policy.get("maximum_forensic_risk") or "low")
        forensic_gate = (
            policy.get("require_media_forensics", True) is False
            or (
                forensics.get("status") == "completed"
                and forensic_rank.get(str(forensic_summary.get("risk_level") or "unknown"), 99)
                <= forensic_rank.get(maximum_forensic_risk, 1)
            )
        )
        supplemental_count = int(supplemental.get("provided_count") or 0)
        supplemental_referenced = int(supplemental.get("referenced_count") or 0)
        supplemental_resolved = supplemental_count == 0 or (
            supplemental_referenced == supplemental_count
            and supplemental.get("linkage_status") == "not_linked"
        )
        conditions = {
            "opening_complete": opening_complete,
            "sampling_boundary_covered": sampling_boundary_covered,
            "continuity_gate": continuity_gate,
            "damage_not_visible": damage_not_visible,
            "claim_not_supported": support_not_found,
            "visibility_coverage": enough_coverage,
            "model_confidence": enough_confidence,
            "claimed_item_absence_within_limit": no_unobserved_time,
            "damage_observability": observability_gate,
            "media_forensics": forensic_gate,
            "supplemental_evidence_resolved": supplemental_resolved,
            "pass_integrity": pass_integrity,
        }
        if all(conditions.values()):
            audit.update(
                {
                    "applied": True,
                    "rule_id": "PD-N-COMPLETE-NO-CLAIMED-DAMAGE",
                    "reason": "视频技术时间轴与开箱过程完整，争议商品展示达到版本化策略门槛，主视频未观察到本次诉求范围内所述损伤。",
                }
            )
            return _apply_negative(output, audit, min(model_confidence, coverage or model_confidence))
        audit["reason"] = "完整性、可见度、损伤不支持或置信度门槛未全部满足，保持人工复核。"
        audit["failed_conditions"] = [key for key, passed in conditions.items() if not passed]
        audit["evidence_gate"].update(
            {
                "opening_complete": opening_complete,
                "minimum_visibility_coverage": minimum_coverage,
                "minimum_confidence": minimum_confidence,
                "minimum_required_view_coverage": minimum_view_coverage,
                "require_continuity_complete": require_continuity_complete,
                "require_fully_observable": require_fully_observable,
                "require_claimed_region_closeup": require_claimed_region_closeup,
                "require_same_item_linkage": require_same_item_linkage,
                "fully_observable": fully_observable,
                "same_item_linkage": same_item_linked,
                "claimed_region_closeup": closeup_complete,
                "required_view_coverage": view_coverage,
                "conflicting_evidence": observability.get("conflicting_evidence"),
                "max_unobserved_seconds": max_unobserved_seconds,
                "claimed_item_longest_out_of_frame_seconds": claimed_item_longest_absence,
                "maximum_forensic_risk": maximum_forensic_risk,
            }
        )
    return output
