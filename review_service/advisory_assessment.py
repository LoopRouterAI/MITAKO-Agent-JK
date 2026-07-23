# -*- coding: utf-8 -*-
"""把模型结果归一为可供甲方系统消费的审核建议，不执行售后业务动作。"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional


POLICY_REF = "MITAKO-ADVISORY-20260723@1"


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _items(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if value in (None, "", {}):
        return []
    return [value]


def _confidence(*values: Any) -> Optional[float]:
    for value in values:
        try:
            if value not in (None, ""):
                return max(0.0, min(float(value), 1.0))
        except (TypeError, ValueError):
            continue
    return None


def _routing_policy(metadata: Dict[str, Any]) -> Dict[str, float]:
    raw = _dict(metadata.get("review_routing_policy"))
    required = _confidence(raw.get("required_below_confidence"), 0.5)
    optional = _confidence(raw.get("optional_below_confidence"), 0.8)
    required = 0.5 if required is None else required
    optional = max(required, 0.8 if optional is None else optional)
    try:
        resubmit = max(0.5, min(float(raw.get("out_of_frame_resubmit_seconds", 3.0)), 30.0))
    except (TypeError, ValueError):
        resubmit = 3.0
    return {
        "required_below_confidence": required,
        "optional_below_confidence": optional,
        "out_of_frame_resubmit_seconds": resubmit,
    }


def _conflicts(parsed: Dict[str, Any]) -> List[Any]:
    found: List[Any] = []
    for key in ("evidence_conflicts", "conflicting_evidence", "contradictions"):
        found.extend(_items(parsed.get(key)))
    minor = _dict(parsed.get("minor_material_assessment"))
    consistency = _dict(minor.get("field_consistency"))
    found.extend(_items(consistency.get("conflicts")))
    return found


def _signal(code: str, severity: str, effect: str, **extra: Any) -> Dict[str, Any]:
    return {"code": code, "severity": severity, "effect": effect, **extra}


def html_report_requested(metadata_or_job: Dict[str, Any]) -> bool:
    metadata = _dict(metadata_or_job.get("metadata")) or metadata_or_job
    options = _dict(metadata.get("output_options"))
    return options.get("include_html_report") is not False


def attach_advisory_assessment(
    review: Dict[str, Any],
    metadata: Dict[str, Any],
    *,
    readiness: Optional[Dict[str, Any]] = None,
    media_forensics: Optional[Dict[str, Any]] = None,
    succeeded: Optional[bool] = None,
) -> Dict[str, Any]:
    output = dict(review)
    summary = dict(output.get("summary") or {})
    agent_report = dict(output.get("agent_report") or {})
    parsed = dict(agent_report.get("parsed") or {})
    overall = _dict(parsed.get("overall_audit"))
    brief = dict(output.get("agent_brief") or {})
    policy = _routing_policy(metadata)

    label = str(
        output.get("predicted_label")
        or summary.get("predicted_label")
        or parsed.get("predicted_label")
        or "review"
    ).strip().lower()
    confidence = _confidence(
        output.get("confidence"),
        summary.get("confidence"),
        parsed.get("confidence"),
        overall.get("confidence"),
    )
    conclusion_code = {
        "positive": "evidence_supports_claim",
        "negative": "evidence_does_not_support_claim",
        "review": "evidence_inconclusive",
    }.get(label, "evidence_inconclusive")
    conclusion = str(
        brief.get("conclusion")
        or overall.get("conclusion")
        or parsed.get("conclusion")
        or "当前证据尚不足以形成明确事实判断。"
    ).strip()
    readiness_guard = _dict(output.get("input_readiness_guard"))
    if readiness_guard.get("applied") is True:
        conclusion = "当前业务基准或必需材料不完整，现有证据不足以形成明确事实判断。"

    readiness = _dict(readiness)
    missing_required = [str(item) for item in readiness.get("missing_required") or []]
    material_gaps = [str(item) for item in _items(parsed.get("material_gaps"))]
    missing_material = list(dict.fromkeys(missing_required + material_gaps))
    conflicts = _conflicts(parsed)
    authoritative = _dict(parsed.get("authoritative_verification"))
    authoritative_pending = str(authoritative.get("status") or "").lower() in {
        "customer_integration_required",
        "manual_verification_required",
        "pending",
    }
    diagnostics = _dict(output.get("diagnostics")) or _dict(agent_report.get("diagnostics"))
    failed = succeeded is False or summary.get("review_status") == "failed" or bool(diagnostics)

    continuity = _dict(parsed.get("object_continuity_assessment"))
    try:
        out_of_frame_seconds = max(0.0, float(continuity.get("longest_out_of_frame_seconds") or 0.0))
    except (TypeError, ValueError):
        out_of_frame_seconds = 0.0
    identity_unresolved = any(
        event.get("identity_reestablished") is False
        for subject in continuity.get("tracked_subjects") or []
        if isinstance(subject, dict)
        for event in subject.get("out_of_frame_events") or []
        if isinstance(event, dict)
    )

    signals: List[Dict[str, Any]] = []
    if out_of_frame_seconds >= policy["out_of_frame_resubmit_seconds"]:
        signals.append(_signal(
            "out_of_frame_over_threshold",
            "warning",
            "当前开箱证据不完整，建议补充连续原视频；该信号不能单独证明调包、剪辑或欺诈。",
            duration_seconds=round(out_of_frame_seconds, 3),
            threshold_seconds=policy["out_of_frame_resubmit_seconds"],
        ))
    elif out_of_frame_seconds > 0:
        signals.append(_signal(
            "short_out_of_frame",
            "warning",
            "短暂离镜或遮挡仅降低证据强度，不单独触发拒绝或强制人工复审。",
            duration_seconds=round(out_of_frame_seconds, 3),
            threshold_seconds=policy["out_of_frame_resubmit_seconds"],
        ))
    if identity_unresolved:
        signals.append(_signal(
            "identity_reestablishment_unresolved",
            "warning",
            "重新入镜后的同物关系尚未由证据链确认。",
        ))
    if missing_material:
        signals.append(_signal(
            "material_gap",
            "warning",
            "缺失材料应优先补齐；增加抽帧或改用更强模型不能替代缺失的业务证据。",
            items=missing_material[:20],
        ))
    if conflicts:
        signals.append(_signal(
            "evidence_conflict",
            "critical",
            "不同证据之间存在实质冲突，需要授权人员核对原始材料。",
            items=conflicts[:20],
        ))
    if authoritative_pending:
        signals.append(_signal(
            "authoritative_verification_pending",
            "critical",
            "材料图像识别已完成，但身份、实名、订单或支付归属仍需甲方权威系统或授权人员核验。",
            pending_checks=_items(authoritative.get("pending_checks"))[:20],
        ))
    forensic_summary = _dict(_dict(media_forensics).get("summary"))
    forensic_count = int(forensic_summary.get("risk_signal_count") or 0)
    if forensic_count:
        signals.append(_signal(
            "media_forensic_risk",
            "warning",
            "媒体技术取证发现风险信号；风险信号不等于已证实剪辑。",
            risk_level=str(forensic_summary.get("risk_level") or "unknown"),
            signal_count=forensic_count,
        ))

    required_reasons: List[str] = []
    optional_reasons: List[str] = []
    if failed:
        required_reasons.append("review_service_failure")
    if conflicts:
        required_reasons.append("evidence_conflict")
    if authoritative_pending:
        required_reasons.append("authoritative_verification_pending")
    if confidence is None and not missing_material:
        required_reasons.append("confidence_unavailable")
    elif confidence is not None and confidence < policy["required_below_confidence"] and not missing_material:
        required_reasons.append("confidence_below_required_threshold")

    needs_more_material = bool(missing_material) or out_of_frame_seconds >= policy["out_of_frame_resubmit_seconds"]
    if not required_reasons and not needs_more_material:
        if confidence is not None and confidence < policy["optional_below_confidence"]:
            optional_reasons.append("confidence_below_optional_threshold")
        if label == "review":
            optional_reasons.append("inconclusive_model_assessment")
        if out_of_frame_seconds > 0 or identity_unresolved or forensic_count:
            optional_reasons.append("non_blocking_risk_signal")

    if required_reasons:
        level = "required"
        workflow = "human_review"
        recommendation = "建议必须由授权人员复核原始证据后再进入甲方业务规则。"
        reason_codes = list(dict.fromkeys(required_reasons))
    elif needs_more_material:
        level = "not_required"
        workflow = "request_more_material"
        recommendation = "当前可直接向用户补充收集材料，无需仅因材料缺口先占用人工审核席位。"
        reason_codes = ["material_resubmission_available"]
    elif optional_reasons:
        level = "optional"
        workflow = "continue_by_customer_policy"
        recommendation = "存在非阻断风险信号，甲方可按风险偏好抽检；不要求每单人工复审。"
        reason_codes = list(dict.fromkeys(optional_reasons))
    else:
        level = "not_required"
        workflow = "continue_by_customer_policy"
        recommendation = "当前证据链与置信度达到本次配置门槛，可由甲方系统按自身业务规则继续处理。"
        reason_codes = ["configured_thresholds_satisfied"]

    advisory = {
        "scenario": str(metadata.get("scenario") or ""),
        "assessment": {
            "conclusion_code": conclusion_code,
            "conclusion": conclusion,
            "confidence": confidence,
            "confidence_level": (
                "unavailable" if confidence is None else "high" if confidence >= policy["optional_below_confidence"]
                else "medium" if confidence >= policy["required_below_confidence"] else "low"
            ),
            "calibration_status": "uncalibrated_evidence_score",
        },
        "human_review": {
            "level": level,
            "reason_codes": reason_codes,
            "recommendation": recommendation,
        },
        "workflow_recommendation": workflow,
        "signals": signals,
        "policy": {
            "policy_ref": POLICY_REF,
            "effective_thresholds": policy,
            "advisory_only": True,
            "business_action_allowed": False,
            "boundary": "本服务不直接决定退款、补发、换货、拒绝或最终定责。",
        },
    }

    parsed["business_action_allowed"] = False
    parsed["predicted_label"] = label
    if confidence is not None:
        parsed["confidence"] = confidence
    parsed["human_required"] = level == "required"
    parsed["decision"] = workflow
    parsed["system_yes_no"] = {
        "positive": "YES",
        "negative": "NO",
        "review": "REVIEW",
    }.get(label, "REVIEW")
    parsed["advisory_assessment"] = advisory
    agent_report["parsed"] = parsed
    agent_report["advisory_assessment"] = advisory
    summary["needs_human_review"] = level == "required"
    summary["predicted_label"] = label
    if confidence is not None:
        summary["confidence"] = confidence
    summary["human_review_level"] = level
    summary["workflow_recommendation"] = workflow
    if readiness_guard.get("applied") is True:
        brief["conclusion"] = conclusion
    brief["human_review_level"] = level
    brief["workflow_recommendation"] = workflow
    output["summary"] = summary
    output["agent_report"] = agent_report
    output["agent_brief"] = brief
    output["advisory_assessment"] = advisory
    return output
