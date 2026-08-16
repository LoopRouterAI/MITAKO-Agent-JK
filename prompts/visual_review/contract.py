# -*- coding: utf-8 -*-
"""四场景审核易变契约的单一运行时入口。"""
from __future__ import annotations

import copy
import math
import re
from typing import Any


REVIEW_CONTRACT_VERSION = "2026-08-15.1"

SCENARIO_LABELS = {
    "product_damage": "商品有伤",
    "wrong_item": "发错货",
    "missing_item": "漏发货",
    "minor_refund": "未成年人退款资料",
}


_OPENING_REQUIREMENT_FIELDS = {
    "opening_action": "opening_action_visible",
    "sealed_start": "sealed_start",
    "waybill_visible": "waybill_visible",
    "continuous": "single_take_continuity",
    "all_items_shown": "claimed_item_presentation",
    "issue_visible": "issue_visible_in_continuous_opening",
}

_MATERIAL_REQUIREMENT_FIELDS = {
    "opening_action": "opening_action",
    "sealed_start": "sealed_start",
    "waybill_visible": "waybill_visible",
    "continuous": "continuous",
    "all_items_shown": "claimed_item_presentation",
    "issue_visible": "issue_assessable",
}


def _typed_native_reference(item: Any, field: str) -> dict[str, Any] | None:
    if not isinstance(item, dict) or item.get("field") != field:
        return None
    asset_ref = str(item.get("asset_ref") or "").strip()
    match = re.fullmatch(r"native_video_(\d+)", asset_ref)
    timestamp = str(item.get("timestamp") or "").strip()
    fact = str(item.get("fact") or item.get("visible_facts") or "").strip()
    if not match or not timestamp or not fact:
        return None
    video_index = int(match.group(1))
    supplied_index = item.get("video_index")
    if supplied_index not in (None, ""):
        try:
            if int(supplied_index) != video_index:
                return None
        except (TypeError, ValueError, OverflowError):
            return None
    return {
        **item,
        "field": field,
        "asset_ref": asset_ref,
        "video_index": video_index,
        "timestamp": timestamp,
        "fact": fact,
    }


def normalize_product_damage_evidence_contract(parsed: dict[str, Any]) -> dict[str, Any]:
    """修复旧公开投影丢字段造成的矛盾，不从自由文本或人工标签推断事实。"""
    output = copy.deepcopy(parsed)
    references = [item for item in output.get("evidence_refs") or [] if isinstance(item, dict)]
    canonical_references = []
    by_field: dict[str, list[dict[str, Any]]] = {}
    for item in references:
        field = str(item.get("field") or "")
        normalized = _typed_native_reference(item, field)
        canonical_references.append(normalized or item)
        if normalized is not None:
            by_field.setdefault(field, []).append(normalized)
    output["evidence_refs"] = canonical_references

    video = output.get("video_audit_conclusion")
    video = dict(video) if isinstance(video, dict) else {}
    compliance = video.get("opening_video_compliance")
    compliance = dict(compliance) if isinstance(compliance, dict) else {}
    action = output.get("opening_action_assessment")
    action = dict(action) if isinstance(action, dict) else {}
    action_declared = action.get("present")
    if action_declared is None:
        action_declared = compliance.get("opening_action_visible")

    action_refs = by_field.get("opening_action") or []
    if action_declared is not True or not action_refs:
        return output
    if not action:
        output["opening_action_assessment"] = {
            "present": True,
            "confidence": None,
            "reason": str(action_refs[0].get("fact") or "已形成可回看的初次拆包动作证据。"),
        }

    values = {
        "opening_action": True,
        "sealed_start": output.get("sealed_start"),
        "waybill_visible": output.get("waybill_visible"),
        "continuous": output.get("continuous"),
        "all_items_shown": output.get("all_items_shown"),
        "issue_visible": output.get("issue_visible"),
    }
    validated = []
    evidence_refs = []
    for field, target in _OPENING_REQUIREMENT_FIELDS.items():
        field_refs = by_field.get(field) or []
        value = values[field]
        valid_value = isinstance(value, bool) if field == "issue_visible" else value is True
        if valid_value and field_refs:
            validated.append(field)
            evidence_refs.extend({**item, "field": target} for item in field_refs)

    sop_compliant = len(validated) == len(_OPENING_REQUIREMENT_FIELDS)
    action_confidence = action.get("confidence") if action else None
    try:
        action_confidence = float(action_confidence)
    except (TypeError, ValueError, OverflowError):
        action_confidence = None
    if action_confidence is not None and not math.isfinite(action_confidence):
        action_confidence = None
    if not action:
        action_confidence = None
    opening = dict(output.get("opening_video_evidence") or {})
    material_validated = [_MATERIAL_REQUIREMENT_FIELDS[field] for field in validated]
    opening.update({
        "present": True,
        "sop_compliant": sop_compliant,
        "status": "pass",
        "confidence": action_confidence,
        "reason": "已确认初次拆开包裹动作；其余开箱要求按结构化原片证据逐项核验。",
        "evidence_refs": evidence_refs,
        "validated_requirements": material_validated,
        "derivation": "typed_native_video_evidence_contract",
    })
    output["opening_video_evidence"] = opening

    opening_fields = {
        _OPENING_REQUIREMENT_FIELDS[field]: values[field]
        for field in _OPENING_REQUIREMENT_FIELDS
        if field != "all_items_shown"
    }
    compliance.update(opening_fields)
    compliance["result"] = "compliant" if sop_compliant else "indeterminate"
    compliance["evidence_refs"] = evidence_refs
    compliance["validated_fields"] = [
        _OPENING_REQUIREMENT_FIELDS[field]
        for field in validated
        if field != "all_items_shown"
    ]
    video["opening_video_compliance"] = compliance
    output["video_audit_conclusion"] = video

    speed_impact = video.get("speed_review_impact")
    speed_impact = speed_impact if isinstance(speed_impact, dict) else {}
    same_item = output.get("damage_observability")
    same_item = same_item if isinstance(same_item, dict) else {}
    complete_native_contract = (
        sop_compliant
        and output.get("has_edit") is False
        and bool(by_field.get("has_edit"))
        and output.get("has_offscreen") is False
        and bool(by_field.get("has_offscreen"))
        and same_item.get("same_item_linkage") is True
        and same_item.get("conflicting_evidence") is not True
        and speed_impact.get("critical_evidence_observable") is not False
        and not [item for item in speed_impact.get("affected_review_items") or [] if str(item)]
    )
    if complete_native_contract:
        output["overall_video_result"] = "compliant"
        damage = output.get("damage_causality_assessment")
        damage = dict(damage) if isinstance(damage, dict) else {}
        if damage.get("damage_presence") == "confirmed":
            issue_refs = by_field.get("issue_visible") or []
            damage["claim_support"] = "supported"
            source_summary = damage.get("evidence_source_summary")
            source_summary = dict(source_summary) if isinstance(source_summary, dict) else {}
            primary = source_summary.get("primary_video")
            primary = dict(primary) if isinstance(primary, dict) else {}
            primary.update({
                "damage_presence": "confirmed",
                "claim_support": "supported",
                "referenced_count": len(issue_refs),
                "evidence_refs": issue_refs,
            })
            source_summary["primary_video"] = primary
            damage["evidence_source_summary"] = source_summary
            output["damage_causality_assessment"] = damage

    for fact in output.get("atomic_facts") or []:
        if isinstance(fact, dict) and fact.get("field") == "opening_action":
            fact.update({
                "value": True,
                "confidence": action_confidence,
                "reason": str(action_refs[0].get("fact") or "已形成可回看的初次拆包动作证据。"),
                "evidence_refs": action_refs,
            })
    return output


__all__ = [
    "REVIEW_CONTRACT_VERSION",
    "SCENARIO_LABELS",
    "normalize_product_damage_evidence_contract",
]
