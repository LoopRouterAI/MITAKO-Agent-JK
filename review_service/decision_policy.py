# -*- coding: utf-8 -*-
"""审核结果的可配置规则判定层。"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Optional

from poc.visual_review_poc.object_continuity import subject_longest_out_of_frame


DEFAULT_PRODUCT_DAMAGE_POLICY_REF = "MITAKO-PD-ADVISORY@20260811.2"


APPROVED_POLICY_SNAPSHOTS: Dict[Any, Dict[str, Any]] = {
    ("mitako", DEFAULT_PRODUCT_DAMAGE_POLICY_REF): {
        "mode": "classification_recommendation",
        "recommendation_gate_mode": "core_sop",
        "opening_video_required": True,
        "missing_required_opening_video": "negative",
        "noncompliant_opening_video": "negative",
        "direct_customer_damage": "negative",
        "extreme_visible_damage_without_opening": "positive",
        "confirmed_visible_damage": "positive",
        "complete_video_no_claimed_damage": "negative",
        "require_claim_scope": True,
        "minimum_visibility_coverage": 0.7,
        "minimum_required_view_coverage": 0.6,
        "minimum_confidence": 0.65,
        "require_continuity_complete": False,
        "require_fully_observable": False,
        "require_claimed_region_closeup": False,
        "require_same_item_linkage": False,
        "require_media_forensics": False,
        "maximum_forensic_risk": "medium",
        "max_unobserved_seconds": 3.0,
    },
    ("mitako", "MITAKO-PD-ADVISORY@20260811.1"): {
        "mode": "classification_recommendation",
        "recommendation_gate_mode": "core_sop",
        "opening_video_required": True,
        "missing_required_opening_video": "negative",
        "noncompliant_opening_video": "negative",
        "direct_customer_damage": "negative",
        "confirmed_visible_damage": "positive",
        "complete_video_no_claimed_damage": "negative",
        "require_claim_scope": True,
        "minimum_visibility_coverage": 0.7,
        "minimum_required_view_coverage": 0.6,
        "minimum_confidence": 0.65,
        "require_continuity_complete": False,
        "require_fully_observable": False,
        "require_claimed_region_closeup": False,
        "require_same_item_linkage": False,
        "require_media_forensics": False,
        "maximum_forensic_risk": "medium",
        "max_unobserved_seconds": 3.0,
    },
    ("mitako", "MITAKO-PD-ADVISORY@20260806.1"): {
        "mode": "classification_recommendation",
        "recommendation_gate_mode": "core_sop",
        "opening_video_required": False,
        "verified_supplemental_damage": "positive",
        "missing_video_no_visible_damage": "negative",
        "noncompliant_opening_video": "negative",
        "direct_customer_damage": "negative",
        "confirmed_visible_damage": "positive",
        "complete_video_no_claimed_damage": "negative",
        "require_claim_scope": True,
        "minimum_visibility_coverage": 0.7,
        "minimum_required_view_coverage": 0.6,
        "minimum_confidence": 0.65,
        "require_continuity_complete": False,
        "require_fully_observable": False,
        "require_claimed_region_closeup": False,
        "require_same_item_linkage": False,
        "require_media_forensics": False,
        "maximum_forensic_risk": "medium",
        "max_unobserved_seconds": 3.0,
    },
    ("mitako", "MITAKO-PD-ADVISORY@20260731.1"): {
        "mode": "classification_recommendation",
        "recommendation_gate_mode": "core_sop",
        "opening_video_required": True,
        "missing_required_opening_video": "negative",
        "noncompliant_opening_video": "negative",
        "confirmed_visible_damage": "positive",
        "complete_video_no_claimed_damage": "negative",
        "require_claim_scope": True,
        "minimum_visibility_coverage": 0.7,
        "minimum_required_view_coverage": 0.6,
        "minimum_confidence": 0.65,
        "require_continuity_complete": False,
        "require_fully_observable": False,
        "require_claimed_region_closeup": False,
        "require_same_item_linkage": False,
        "require_media_forensics": False,
        "maximum_forensic_risk": "medium",
        "max_unobserved_seconds": 3.0,
    },
    ("mitako", "MITAKO-PD-ADVISORY@20260728.1"): {
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


def _opening_field_has_reference(opening: Dict[str, Any], field_name: str) -> bool:
    references = opening.get("evidence_refs") or []
    if isinstance(references, dict):
        references = references.get(field_name) or []
    return any(
        isinstance(item, dict)
        and (item.get("field") in {None, field_name})
        and item.get("video_index")
        and item.get("global_frame_index")
        and item.get("timestamp")
        for item in references
    )


def _replace_opening_evidence(parsed: Dict[str, Any], opening: Dict[str, Any]) -> None:
    """用主连续开箱链的结构化复核事实替换同帧冲突描述。"""
    references = opening.get("evidence_refs") or []
    if isinstance(references, dict):
        references = [
            {**item, "field": item.get("field") or field}
            for field, items in references.items()
            for item in (items or [])
            if isinstance(item, dict)
        ]
    references = [item for item in references if isinstance(item, dict)]
    verified_fields = set(opening.get("validated_fields") or [])
    ref_keys = {
        (item.get("video_index"), item.get("global_frame_index"))
        for item in references
        if item.get("video_index") is not None and item.get("global_frame_index") is not None
    }
    evidence = [
        item for item in parsed.get("adopted_evidence") or []
        if not isinstance(item, dict)
        or (item.get("video_index"), item.get("global_frame_index")) not in ref_keys
    ]
    labels = {
        "sealed_start": "封箱起始",
        "waybill_visible": "面单可核验",
        "single_take_continuity": "一镜到底连续拆封",
        "issue_visible_in_continuous_opening": "伤点在连续开箱中清晰展示",
    }
    verified = []
    for field, label in labels.items():
        ref = next((item for item in references if item.get("field") in {None, field}), None)
        timeline_absence = (
            field == "issue_visible_in_continuous_opening"
            and opening.get(field) is False
            and opening.get("source") == "global_timeline_aggregation"
            and opening.get("result") == "noncompliant"
        )
        if field not in verified_fields or not isinstance(opening.get(field), bool) or (not ref and not timeline_absence):
            continue
        ref = ref or {}
        verified.append({
            "source_type": "video_frame",
            "video_index": ref.get("video_index"),
            "global_frame_index": ref.get("global_frame_index"),
            "timestamp": ref.get("timestamp"),
            "fact": f"{label}：{'符合' if opening[field] else '不符合'}。",
            "why_it_matters": "来自主连续开箱链的结构化复核；后补图片或短片不能覆盖该时态。",
        })
    if verified:
        parsed["adopted_evidence"] = verified + evidence


def _normalize_noncompliant_opening_damage(parsed: Dict[str, Any], opening: Dict[str, Any]) -> None:
    """主开箱未展示伤点时，不让未关联补图冒充主视频支持结论。"""
    if opening.get("issue_visible_in_continuous_opening") is not False:
        return
    damage = _dict(parsed.get("damage_causality_assessment"))
    sources = _dict(damage.get("evidence_source_summary"))
    primary = _dict(sources.get("primary_video"))
    if primary.get("damage_presence") == "confirmed":
        return
    primary["claim_support"] = "insufficient"
    sources["primary_video"] = primary
    supplemental = _dict(sources.get("supplemental_images"))
    if supplemental.get("linkage_status") != "verified":
        damage["claim_support"] = "insufficient"
    damage["evidence_source_summary"] = sources
    parsed["damage_causality_assessment"] = damage


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


def _default_claim_scope(scope: Dict[str, Any], fallback_claim: str, scenario: str) -> Dict[str, Any]:
    has_explicit_scope = bool(
        scope.get("active_claim_ids")
        or scope.get("claims")
        or scope.get("issue_types")
        or str(scope.get("claim_text") or "").strip()
        or scope.get("split_status") in {"resolved", "single_legacy", "ambiguous"}
    )
    if has_explicit_scope or not fallback_claim.strip() or scenario != "product_damage":
        return scope
    return {
        "split_status": "single_legacy",
        "claim_text": fallback_claim,
        "issue_types": ["product_damage"],
    }


def _visibility_coverage(continuity: Dict[str, Any]) -> Optional[float]:
    values = [
        _float(item.get("visibility_coverage"))
        for item in continuity.get("tracked_subjects") or []
        if isinstance(item, dict) and str(item.get("subject_id") or "") == "claimed_item"
    ]
    return min(values) if values else None


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
    core_reason = audit.get("reason") or "当前材料未满足甲方已批准的审核规则。"
    if audit.get("rule_id") == "PD-N-OPENING-VIDEO-REQUIRED":
        core_reason += " 这是开箱资料合规结论，不等于视觉证明商品无损。"
    next_step = "按甲方 SOP 审核倾向继续处理，由授权人员决定具体业务动作。"
    business_follow_up_reason = "当前材料未满足甲方已批准的审核规则；最终业务动作仍由甲方授权系统或人员决定。"
    if audit.get("rule_id") == "PD-N-NONCOMPLIANT-OPENING-VIDEO":
        opening = _dict(_dict(audit.get("evidence_gate")).get("opening_video_compliance"))
        _replace_opening_evidence(parsed, opening)
        _normalize_noncompliant_opening_damage(parsed, opening)
        business_follow_up_reason = "主连续开箱材料不合规，补充图片或短片不能倒补开箱时态；最终业务动作仍由甲方授权系统或人员决定。"
    parsed.update(
        {
            "predicted_label": "negative",
            "system_yes_no": "NO",
            "decision": "fail",
            "confidence": round(confidence, 4),
            "business_action_allowed": False,
            "human_required": False,
            "human_required_for_business_action": True,
            "business_follow_up_reason": business_follow_up_reason,
            "next_step": next_step,
            "decision_policy_audit": audit,
            "overall_audit": {
                "conclusion": audit.get("reason") or "当前材料未满足甲方已批准的审核规则。",
                "confidence": round(confidence, 4),
                "core_reason": core_reason,
                "business_follow_up_suggestion": "按甲方 SOP 审核倾向继续处理；最终业务动作由甲方系统或授权人员决定。",
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
            "next_step": next_step,
            "confidence": round(confidence, 4),
        }
    )
    output["agent_brief"] = brief
    output["decision_policy_audit"] = audit
    return output


def _apply_positive(review: Dict[str, Any], audit: Dict[str, Any], confidence: float) -> Dict[str, Any]:
    output = dict(review)
    agent_report = _dict(output.get("agent_report"))
    parsed = _dict(agent_report.get("parsed"))
    previous_overall = _dict(parsed.get("overall_audit"))
    audit["evidence_verdict_before_policy"] = {
        "predicted_label": parsed.get("predicted_label"),
        "confidence": parsed.get("confidence"),
        "conclusion": previous_overall.get("conclusion") or "",
    }
    next_step = "按甲方 SOP 继续处理，并由授权人员决定具体业务动作。"
    parsed.update(
        {
            "predicted_label": "positive",
            "system_yes_no": "YES",
            "decision": "pass",
            "confidence": round(confidence, 4),
            "business_action_allowed": False,
            "human_required": False,
            "human_required_for_business_action": True,
            "next_step": next_step,
            "decision_policy_audit": audit,
            "overall_audit": {
                "conclusion": audit.get("reason") or "当前可见证据支持商品有伤诉求。",
                "confidence": round(confidence, 4),
                "core_reason": audit.get("reason") or "当前可见证据支持商品有伤诉求。",
                "business_follow_up_suggestion": "可按甲方 SOP 继续处理；责任、比例和最终业务动作由甲方系统或授权人员决定。",
            },
        }
    )
    agent_report["parsed"] = parsed
    output["agent_report"] = agent_report
    summary = _dict(output.get("summary"))
    summary.update(
        {
            "predicted_label": "positive",
            "system_yes_no": "YES",
            "confidence": round(confidence, 4),
            "decision_policy_applied": True,
        }
    )
    output["summary"] = summary
    brief = _dict(output.get("agent_brief"))
    brief.update(
        {
            "conclusion": audit.get("reason") or "当前可见证据支持商品有伤诉求。",
            "next_step": next_step,
            "confidence": round(confidence, 4),
        }
    )
    output["agent_brief"] = brief
    output["decision_policy_audit"] = audit
    return output


def _apply_review(review: Dict[str, Any], audit: Dict[str, Any], confidence: float) -> Dict[str, Any]:
    output = dict(review)
    agent_report = _dict(output.get("agent_report"))
    parsed = _dict(agent_report.get("parsed"))
    audit["evidence_verdict_before_policy"] = {
        "predicted_label": parsed.get("predicted_label"),
        "confidence": parsed.get("confidence"),
        "conclusion": _dict(parsed.get("overall_audit")).get("conclusion") or "",
    }
    next_step = "按审核建议完成补充核验后再分类。"
    parsed.update({
        "predicted_label": "review",
        "system_yes_no": "REVIEW",
        "decision": "manual_review",
        "confidence": round(confidence, 4),
        "business_action_allowed": False,
        "human_required": True,
        "business_follow_up_reason": audit.get("reason") or "当前证据仍需强化复核。",
        "next_step": next_step,
        "decision_policy_audit": audit,
        "overall_audit": {
            "conclusion": audit.get("reason") or "当前证据仍需强化复核。",
            "confidence": round(confidence, 4),
            "core_reason": audit.get("reason") or "当前证据仍需强化复核。",
            "business_follow_up_suggestion": "按审核建议完成补充核验后再分类；最终业务动作由甲方系统或授权人员决定。",
        },
    })
    agent_report["parsed"] = parsed
    output["agent_report"] = agent_report
    summary = _dict(output.get("summary"))
    summary.update({
        "predicted_label": "review",
        "system_yes_no": "REVIEW",
        "confidence": round(confidence, 4),
        "decision_policy_applied": True,
    })
    output["summary"] = summary
    brief = _dict(output.get("agent_brief"))
    brief.update({
        "conclusion": audit.get("reason") or "当前证据仍需强化复核。",
        "next_step": next_step,
        "confidence": round(confidence, 4),
    })
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
    fallback_claim = str(metadata.get("customer_claim") or "")
    scenario = str(job.get("scenario") or metadata.get("scenario") or "")
    scope = _default_claim_scope(_dict(metadata.get("claim_scope")), fallback_claim, scenario)
    agent_report = _dict(review.get("agent_report"))
    parsed = _dict(agent_report.get("parsed"))
    claim_facts = _dict(parsed.get("claim_fact_assessment"))
    atomic_claim_results = [
        _dict(item)
        for item in claim_facts.get("atomic_claim_results") or []
        if isinstance(item, dict)
    ]
    order_linkage = _dict(claim_facts.get("order_linkage"))
    scene_match = _dict(claim_facts.get("scene_match"))
    assembly = _dict(claim_facts.get("assembly"))
    damage = _dict(parsed.get("damage_causality_assessment"))
    continuity = _dict(parsed.get("object_continuity_assessment"))
    video_audit = _dict(parsed.get("video_audit_conclusion"))
    observability = _dict(parsed.get("damage_observability"))
    speed_impact = _dict(video_audit.get("speed_review_impact"))
    opening_compliance = _dict(video_audit.get("opening_video_compliance"))
    evidence_sources = _dict(damage.get("evidence_source_summary"))
    primary_video = _dict(evidence_sources.get("primary_video"))
    supplemental = _dict(evidence_sources.get("supplemental_images"))
    forensics = _dict(media_forensics)
    forensic_summary = _dict(forensics.get("summary"))
    has_video = _has_video(job.get("assets") or [])
    scope_ready = _claim_scope_ready(scope, fallback_claim)
    coverage = _visibility_coverage(continuity)
    claimed_item_longest_absence = subject_longest_out_of_frame(continuity, "claimed_item")
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
            "order_linkage_status": order_linkage.get("status") or "not_provided",
            "claim_scene_match": scene_match.get("status") or "not_provided",
            "assembly_state": assembly.get("state") or "not_provided",
            "atomic_claim_result_count": len(atomic_claim_results),
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

    active_claim_ids = [str(item) for item in scope.get("active_claim_ids") or [] if str(item)]
    if len(active_claim_ids) > 1:
        result_ids = [str(item.get("claim_id") or "") for item in atomic_claim_results]
        result_by_id = {str(item.get("claim_id") or ""): item for item in atomic_claim_results}
        incomplete_ids = [
            claim_id
            for claim_id in active_claim_ids
            if claim_id not in result_by_id
            or not str(result_by_id[claim_id].get("subject_ref") or "").strip()
            or result_by_id[claim_id].get("support_status") not in {"supported", "not_supported"}
            or not result_by_id[claim_id].get("evidence_refs")
        ]
        if set(result_ids) != set(active_claim_ids) or len(result_ids) != len(set(result_ids)) or incomplete_ids:
            audit.update({
                "applied": True,
                "rule_id": "PD-R-ATOMIC-CLAIM-INCOMPLETE",
                "reason": "多诉求案件仍有诉求未绑定独立商品、证据与事实结论，不能用整单总标签覆盖原子审核结果。",
            })
            audit["evidence_gate"]["atomic_claim_incomplete_ids"] = incomplete_ids
            return _apply_review(output, audit, min(model_confidence, 0.69))

    if order_linkage.get("status") == "failed":
        audit.update({
            "applied": True,
            "rule_id": "PD-R-ORDER-LINKAGE-FAILED",
            "reason": order_linkage.get("reason") or "送审媒体与目标订单或包裹的归属明确冲突，现有视觉事实不能归因到本次订单。",
        })
        return _apply_review(output, audit, min(model_confidence, 0.69))
    if scene_match.get("status") == "mismatched":
        audit.update({
            "applied": True,
            "rule_id": "PD-R-CLAIM-SCENE-MISMATCH",
            "reason": scene_match.get("reason") or "本次原子诉求不属于商品实体损伤，需转入对应规则或仓库核验流程。",
        })
        return _apply_review(output, audit, min(model_confidence, 0.69))
    assembly_refs = [
        ref
        for ref in assembly.get("evidence_refs") or []
        if isinstance(ref, dict)
        and (
            (ref.get("video_index") and ref.get("global_frame_index"))
            or ref.get("image_index")
        )
    ]
    if (
        assembly.get("state") == "resolved_assembly_issue"
        and assembly.get("reassembly_result") == "successful"
        and assembly.get("permanent_damage") == "not_supported"
        and assembly_refs
    ):
        audit.update({
            "applied": True,
            "rule_id": "PD-N-RESOLVED-ASSEMBLY-ISSUE",
            "reason": "证据显示部件已成功复装，未见断裂、缺料或不可逆形变，当前事实不支持永久商品损伤诉求。",
        })
        return _apply_negative(output, audit, model_confidence)

    supplemental_count = int(supplemental.get("provided_count") or 0)
    supplemental_referenced = int(supplemental.get("referenced_count") or 0)
    supplemental_damage_confirmed = (
        damage.get("supplemental_damage_presence") == "confirmed"
        and supplemental.get("linkage_status") == "verified"
        and supplemental_count > 0
        and supplemental_referenced > 0
    )
    severity = _dict(damage.get("severity_assessment"))
    extreme_structural_damage = (
        not has_video
        and policy.get("extreme_visible_damage_without_opening") == "positive"
        and supplemental_damage_confirmed
        and damage.get("damage_presence") == "confirmed"
        and damage.get("business_defect_qualification") == "confirmed"
        and severity.get("level") == "extreme"
        and severity.get("structural_failure") is True
        and order_linkage.get("status") == "verified"
        and observability.get("same_item_linkage") is True
        and observability.get("conflicting_evidence") is False
        and forensics.get("status") == "completed"
        and str(forensic_summary.get("risk_level") or "unknown") in {"none", "low", "medium"}
        and model_confidence >= 0.8
    )
    if extreme_structural_damage:
        audit.update({
            "applied": True,
            "rule_id": "PD-P-EXTREME-VISIBLE-DAMAGE-WITHOUT-OPENING",
            "reason": (
                "现有清晰材料确认争议商品存在极重结构性损坏，且订单、同物与真实性核验均无冲突；"
                "即使缺少开箱视频，当前证据也倾向跟进处理。损伤存在已确认，成因未确认。"
            ),
        })
        audit["evidence_gate"].update({
            "severity_level": severity.get("level"),
            "structural_failure": True,
            "same_item_linkage": True,
            "business_defect_qualification": "confirmed",
        })
        return _apply_positive(output, audit, model_confidence)
    if (
        not has_video
        and policy.get("verified_supplemental_damage") == "positive"
        and supplemental_damage_confirmed
    ):
        audit.update(
            {
                "applied": True,
                "rule_id": "PD-P-VERIFIED-SUPPLEMENTAL-DAMAGE",
                "reason": "按照商品有伤 SOP，本轮虽未提交开箱视频，但现有清晰照片已确认所诉损伤，当前证据倾向支持用户的有伤诉求。",
            }
        )
        return _apply_positive(output, audit, model_confidence)

    if (
        not has_video
        and policy.get("missing_video_no_visible_damage") == "negative"
        and damage.get("damage_presence") == "not_visible"
        and damage.get("claim_support") == "not_supported"
    ):
        audit.update(
            {
                "applied": True,
                "rule_id": "PD-N-NO-VIDEO-NO-VISIBLE-DAMAGE",
                "reason": "按照商品有伤 SOP，本案未提交开箱视频，现有照片也未观察到所诉损伤，当前证据倾向不支持用户诉求。",
            }
        )
        return _apply_negative(output, audit, model_confidence)

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

    is_current_advisory = policy_ref == DEFAULT_PRODUCT_DAMAGE_POLICY_REF
    speed_status = str(speed_impact.get("status") or "none").strip().lower()
    sampling_fps = _nonnegative_float(video_audit.get("sampling_fps"), 0.0)
    successful_evidence_pass = (
        parsed.get("pass_integrity_status") in {None, "", "complete", "partial_specialized"}
        and not parsed.get("specialized_pass_guard_reason")
    )
    missing_opening_fields = [
        field_name
        for field_name in (
            "sealed_start", "waybill_visible", "single_take_continuity",
            "issue_visible_in_continuous_opening",
        )
        if opening_compliance.get(field_name) is False
    ]
    validated_opening_fields = set(opening_compliance.get("validated_fields") or [])
    full_timeline_issue_absence_verified = (
        missing_opening_fields == ["issue_visible_in_continuous_opening"]
        and opening_compliance.get("result") == "noncompliant"
        and opening_compliance.get("single_take_continuity") is True
        and _opening_field_has_reference(opening_compliance, "single_take_continuity")
    )
    global_opening_failure_verified = (
        video_audit.get("source") == "global_timeline_aggregation"
        and opening_compliance.get("source") == "global_timeline_aggregation"
        and video_audit.get("sampling_boundary_status") == "covered"
        and successful_evidence_pass
        and bool(missing_opening_fields)
        and (
            set(missing_opening_fields).issubset(validated_opening_fields)
            or full_timeline_issue_absence_verified
        )
    )
    if global_opening_failure_verified and full_timeline_issue_absence_verified:
        opening_compliance["validated_fields"] = sorted(
            validated_opening_fields | {"issue_visible_in_continuous_opening"}
        )
    opening_start_failure_verified = (
        missing_opening_fields == ["sealed_start"]
        and (opening_compliance.get("field_sources") or {}).get("sealed_start") == "opening_start_verification"
        and "sealed_start" in validated_opening_fields
        and _opening_field_has_reference(opening_compliance, "sealed_start")
    )
    opening_compliance_failure_verified = (
        opening_compliance.get("source") == "opening_compliance_verification"
        and video_audit.get("sampling_boundary_status") == "covered"
        and successful_evidence_pass
        and bool(missing_opening_fields)
        and set(missing_opening_fields).issubset(validated_opening_fields)
        and all(
            _opening_field_has_reference(opening_compliance, field_name)
            for field_name in missing_opening_fields
        )
    )
    opening_hard_failure_verified = (
        global_opening_failure_verified
        or opening_start_failure_verified
        or opening_compliance_failure_verified
    )
    opening_field_labels = {
        "sealed_start": "完整未拆封快递外包装起点",
        "waybill_visible": "面单可核验",
        "single_take_continuity": "一镜到底连续拆封",
        "issue_visible_in_continuous_opening": "伤点在连续开箱中清晰展示",
    }
    missing_opening_text = "、".join(
        opening_field_labels[field_name] for field_name in missing_opening_fields
    )
    if (
        is_current_advisory
        and has_video
        and policy.get("noncompliant_opening_video") == "negative"
        and opening_hard_failure_verified
    ):
        audit.update({
            "applied": True,
            "rule_id": "PD-N-NONCOMPLIANT-OPENING-VIDEO",
            "reason": (
                "按照商品有伤 SOP，可回链的开箱起始帧专项复核确认视频并非从完整未拆封快递外包装开始，当前开箱材料不合规。"
                if opening_start_failure_verified
                else f"按照商品有伤 SOP，完整时间轴证据确认视频未满足{missing_opening_text}的硬要求，当前开箱材料不合规。"
            ),
        })
        audit["evidence_gate"].update({
            "opening_complete": False,
            "opening_video_compliance": opening_compliance,
            "missing_opening_fields": missing_opening_fields,
        })
        return _apply_negative(output, audit, model_confidence)

    native_overall_result = str(parsed.get("overall_video_result") or "").strip().lower()
    native_timeline = video_audit.get("technical_timeline_status") == "native_full_video"
    if is_current_advisory and native_timeline and native_overall_result == "noncompliant":
        audit.update({
            "applied": True,
            "rule_id": "PD-N-NATIVE-VIDEO-NONCOMPLIANT",
            "reason": "完整原生视频九项核对已确定存在硬门槛失败，后续伤点或补充图片不能覆盖该不合格结论。",
        })
        audit["evidence_gate"]["overall_video_result"] = native_overall_result
        return _apply_negative(output, audit, model_confidence)
    if is_current_advisory and native_timeline and native_overall_result == "indeterminate":
        audit.update({
            "applied": True,
            "rule_id": "PD-R-NATIVE-VIDEO-INDETERMINATE",
            "reason": "完整原生视频仍有开箱、商品身份、伤点或速度影响无法确认，保留黄色复核，不允许由后续规则直接转为支持。",
        })
        audit["evidence_gate"]["overall_video_result"] = native_overall_result
        return _apply_review(output, audit, min(model_confidence, 0.69))

    if (
        is_current_advisory
        and video_audit.get("playback_speed") in {"accelerated", "unknown"}
        and speed_status in {"uncertain", "material"}
        and speed_impact.get("critical_evidence_observable") is not True
    ):
        audit.update({
            "applied": True,
            "rule_id": "PD-R-SPEED-UNRESOLVED",
            "reason": "视频速度无法可靠确认，且当前证据不足以判断受影响的关键节点；保留黄色复核，不因速度本身判负，也不强制提高抽帧密度。",
        })
        audit["evidence_gate"].update({
            "playback_speed": video_audit.get("playback_speed"),
            "sampling_fps": sampling_fps,
            "speed_review_impact": speed_status,
            "affected_review_items": speed_impact.get("affected_review_items") or [],
        })
        return _apply_review(output, audit, min(model_confidence, 0.69))

    opening_integrity = str(video_audit.get("opening_integrity") or "").strip().lower()
    timeline_verified = video_audit.get("opening_integrity_source") == "full_timeline_continuity"
    max_unobserved_seconds = _nonnegative_float(policy.get("max_unobserved_seconds"), 0.0)
    explicitly_incomplete = timeline_verified and opening_integrity in {
        "incomplete", "不完整", "开箱不完整", "invalid", "noncompliant"
    }
    unresolved_opening_after_full_timeline = (
        timeline_verified
        and opening_integrity == "indeterminate"
        and video_audit.get("sampling_boundary_status") == "covered"
        and continuity.get("claimed_item_timeline_complete") is True
        and successful_evidence_pass
        and damage.get("damage_presence") != "confirmed"
        and damage.get("claim_support") != "supported"
        and supplemental.get("linkage_status") != "verified"
    )
    direct_customer_damage = (
        damage.get("damage_presence") == "confirmed"
        and damage.get("damage_timing") == "appears_during_opening"
        and damage.get("damage_change_observed") is True
        and damage.get("opening_action_visible") is True
        and damage.get("most_likely_origin") == "customer_opening_or_handling"
        and damage.get("causal_evidence_level") == "direct"
        and damage.get("claim_support") == "not_supported"
    )
    long_unresolved_absence = (
        claimed_item_longest_absence is not None
        and claimed_item_longest_absence > max_unobserved_seconds
        and continuity.get("continuity_verdict") in {"long_absence", "indeterminate"}
        and continuity.get("claimed_item_timeline_complete") is True
        and continuity.get("claimed_item_reference_status") == "available"
    )
    claimed_item_never_shown = (
        continuity.get("claimed_item_never_exposed") is True
        and continuity.get("claimed_item_timeline_complete") is True
        and continuity.get("claimed_item_reference_status") == "available"
        and video_audit.get("sampling_boundary_status") == "covered"
    )
    if policy.get("noncompliant_opening_video") == "negative" and claimed_item_never_shown:
        audit.update(
            {
                "applied": True,
                "rule_id": "PD-N-CLAIMED-ITEM-NOT-SHOWN",
                "reason": "按照商品有伤 SOP，完整送审时间轴中未展示与订单 SKU 匹配的争议商品，当前视频不支持本次诉求。",
            }
        )
        audit["evidence_gate"].update(
            {
                "opening_complete": False,
                "claimed_item_never_exposed": True,
                "claimed_item_reference_status": "available",
            }
        )
        return _apply_negative(output, audit, model_confidence)
    if policy.get("direct_customer_damage") == "negative" and direct_customer_damage:
        audit.update(
            {
                "applied": True,
                "rule_id": "PD-N-DIRECT-CUSTOMER-DAMAGE",
                "reason": "按照商品有伤 SOP，同一部位已形成操作前、操作中和操作后直接证据链，损伤在用户操作过程中出现，当前证据倾向不支持本次诉求。",
            }
        )
        return _apply_negative(output, audit, model_confidence)
    if (
        policy.get("noncompliant_opening_video") == "negative"
        and (
            explicitly_incomplete
            or long_unresolved_absence
            or (unresolved_opening_after_full_timeline and not is_current_advisory)
        )
    ):
        supplemental_count = int(supplemental.get("provided_count") or 0)
        note = (
            "补充图片可作为损伤参考，但不能替代合规开箱视频；可供客服按 SOP 最低档补偿规则参考。"
            if supplemental_count else
            "本轮没有可替代合规开箱视频的补充损伤证据。"
        )
        audit.update(
            {
                "applied": True,
                "rule_id": "PD-N-NONCOMPLIANT-OPENING-VIDEO",
                "reason": "按照商品有伤 SOP，本案开箱视频不合规，当前证据倾向不支持本次诉求。",
                "supplemental_evidence_note": note,
            }
        )
        audit["evidence_gate"].update(
            {
                "opening_complete": False,
                "opening_integrity": opening_integrity or "unknown",
                "full_timeline_unresolved_opening": unresolved_opening_after_full_timeline,
                "max_unobserved_seconds": max_unobserved_seconds,
                "claimed_item_longest_out_of_frame_seconds": claimed_item_longest_absence,
            }
        )
        return _apply_negative(output, audit, model_confidence)

    first_visible_evidence = _dict(damage.get("first_visible_evidence"))
    first_visible_source = str(first_visible_evidence.get("source_type") or "").strip().lower()
    supplemental_only = (
        first_visible_source in {"supplementary_image", "supplemental_image", "image"}
        or (
            bool(primary_video)
            and primary_video.get("damage_presence") != "confirmed"
            and supplemental_count > 0
        )
    )
    if (
        is_current_advisory
        and has_video
        and damage.get("damage_presence") == "confirmed"
        and supplemental_only
        and supplemental.get("linkage_status") in {"unresolved", "not_linked", "unknown", None, ""}
    ):
        audit.update({
            "applied": True,
            "rule_id": "PD-R-SUPPLEMENTAL-TEMPORAL-LINKAGE-UNRESOLVED",
            "reason": "损伤只在后补图片中可见，尚不能证明它在连续开箱过程中的出现时点；需复核同物与时间关联，不能直接转为开箱视频支持结论。",
        })
        return _apply_review(output, audit, min(model_confidence, 0.69))
    if (
        is_current_advisory
        and damage.get("appearance_difference") == "visible"
        and damage.get("business_defect_qualification") == "not_qualified"
    ):
        audit.update({
            "applied": True,
            "rule_id": "PD-N-SPECIAL-PRODUCT-NOT-QUALIFIED",
            "reason": "当前画面存在外观差异，但依据已提供的商品标准不构成业务质量缺陷，当前证据不支持质量缺陷诉求。",
        })
        return _apply_negative(output, audit, model_confidence)
    if (
        is_current_advisory
        and damage.get("appearance_difference") == "visible"
        and damage.get("business_defect_qualification") == "indeterminate"
        and damage.get("special_product_rule") != "not_applicable"
    ):
        audit.update({
            "applied": True,
            "rule_id": "PD-R-SPECIAL-PRODUCT-DEFECT-UNRESOLVED",
            "reason": "已观察到特殊商品外观差异，但缺少可执行的商品缺陷标准，不能把材质、工艺或形态差异直接认定为业务缺陷。",
        })
        return _apply_review(output, audit, min(model_confidence, 0.69))

    structural_opening_fields = {
        "sealed_start",
        "waybill_visible",
        "single_take_continuity",
    }
    required_opening_fields = structural_opening_fields | {
        "issue_visible_in_continuous_opening",
    }
    opening_gate_resolved = (
        opening_compliance.get("result") in {"compliant", "noncompliant"}
        and all(opening_compliance.get(field) is True for field in structural_opening_fields)
        and isinstance(opening_compliance.get("issue_visible_in_continuous_opening"), bool)
        and required_opening_fields.issubset(validated_opening_fields)
        and all(
            _opening_field_has_reference(opening_compliance, field)
            for field in required_opening_fields
        )
    )
    if (
        is_current_advisory
        and has_video
        and policy.get("opening_video_required") is True
        and not opening_gate_resolved
    ):
        audit.update({
            "applied": True,
            "rule_id": "PD-R-OPENING-GATE-INDETERMINATE",
            "reason": (
                "商品有伤必须先通过开箱视频门槛；当前封箱起始、面单、连续拆封或伤点展示"
                "仍有字段未确认或无法回链，不能仅凭后补图片或孤立伤点转为支持。"
            ),
        })
        audit["evidence_gate"].update({
            "opening_complete": False,
            "opening_video_compliance": opening_compliance,
            "opening_validated_fields": sorted(validated_opening_fields),
        })
        if opening_compliance.get("result") == "noncompliant":
            _normalize_noncompliant_opening_damage(output_parsed, opening_compliance)
            output_agent_report["parsed"] = output_parsed
            output["agent_report"] = output_agent_report
        return _apply_review(output, audit, min(model_confidence, 0.69))

    main_damage_confirmed = (
        damage.get("damage_presence") == "confirmed"
        and not supplemental_only
        and (
            bool(first_visible_evidence)
            or damage.get("claim_support") == "supported"
        )
    )
    if policy.get("confirmed_visible_damage") == "positive" and main_damage_confirmed:
        audit.update(
            {
                "applied": True,
                "rule_id": "PD-P-CONFIRMED-VISIBLE-DAMAGE",
                "reason": "按照商品有伤 SOP，本轮可见证据已确认所诉损伤，当前证据倾向支持用户的有伤诉求；损伤责任和具体业务动作仍由甲方规则决定。",
            }
        )
        audit["evidence_gate"].update(
            {
                "claimed_item_longest_out_of_frame_seconds": claimed_item_longest_absence,
                "continuity_risk_preserved": claimed_item_longest_absence not in (None, 0),
            }
        )
        return _apply_positive(output, audit, model_confidence)

    if policy.get("complete_video_no_claimed_damage") == "negative":
        minimum_coverage = _float(policy.get("minimum_visibility_coverage"), 0.95)
        minimum_view_coverage = _float(policy.get("minimum_required_view_coverage"), 1.0)
        minimum_confidence = _float(policy.get("minimum_confidence"), 0.8)
        require_continuity_complete = policy.get("require_continuity_complete", True) is not False
        require_fully_observable = policy.get("require_fully_observable", True) is not False
        require_claimed_region_closeup = policy.get("require_claimed_region_closeup", True) is not False
        require_same_item_linkage = policy.get("require_same_item_linkage", True) is not False
        continuity_complete = continuity.get("continuity_verdict") == "continuous"
        opening_complete = str(video_audit.get("opening_integrity") or "").lower() in {
            "complete", "完整", "完整开箱", "complete_opening"
        }
        damage_not_visible = (
            damage.get("damage_presence") == "not_visible"
            or (
                damage.get("damage_presence") == "uncertain"
                and not _dict(damage.get("first_visible_evidence"))
            )
        )
        support_not_found = damage.get("claim_support") in {"not_supported", "insufficient"}
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
        pass_integrity = successful_evidence_pass
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
        supplemental_resolved = supplemental_count == 0 or supplemental_referenced == supplemental_count
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
        strict_recommendation = policy.get("recommendation_gate_mode") != "core_sop"
        recommendation_conditions = (
            dict(conditions)
            if strict_recommendation
            else {
                key: conditions[key]
                for key in (
                    "opening_complete",
                    "damage_not_visible",
                    "claim_not_supported",
                    "pass_integrity",
                )
            }
        )
        audit["failed_conditions"] = [key for key, passed in conditions.items() if not passed]
        if all(recommendation_conditions.values()):
            audit.update(
                {
                    "applied": True,
                    "rule_id": "PD-N-COMPLETE-NO-CLAIMED-DAMAGE",
                    "reason": "按照商品有伤 SOP，开箱过程完整且主视频在有效展示范围内未观察到本次诉求所述损伤，当前证据倾向不支持诉求；未通过的辅助技术项仅用于抽检提示，不抹掉该审核建议。",
                }
            )
            if supplemental_count:
                audit["supplemental_evidence_note"] = (
                    "补充照片可供最低档安慰性补偿参考，但不能推翻完整主视频未观察到所诉损伤的审核倾向。"
                )
            return _apply_negative(output, audit, min(model_confidence, coverage or model_confidence))
        audit["reason"] = "主视频尚未同时满足完整开箱、未见所诉损伤、诉求不受支持和聚合过程完整；保留复核信号，不据此自动形成支持或不支持结论。"
        audit["recommendation_failed_conditions"] = [
            key for key, passed in recommendation_conditions.items() if not passed
        ]
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
                "strict_recommendation": strict_recommendation,
            }
        )
    if (
        opening_compliance.get("result") == "noncompliant"
        and output_parsed.get("predicted_label") == "review"
    ):
        _normalize_noncompliant_opening_damage(output_parsed, opening_compliance)
        output_parsed["business_follow_up_reason"] = audit.get("reason") or "开箱合规项尚未闭环，保留复核信号。"
        output_agent_report["parsed"] = output_parsed
        output["agent_report"] = output_agent_report
    return output
