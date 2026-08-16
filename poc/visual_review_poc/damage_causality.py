# -*- coding: utf-8 -*-
"""商品有伤场景的因果判定归一化与分段聚合。"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List


VALID_PRESENCE = {"confirmed", "not_visible", "uncertain"}
VALID_TIMING = {"pre_opening_visible", "appears_during_opening", "post_opening_only", "unknown"}
VALID_ORIGINS = {
    "manufacturing_or_original_packaging",
    "logistics_transport",
    "customer_opening_or_handling",
    "mixed",
    "indeterminate",
}
VALID_EVIDENCE_LEVELS = {"direct", "indirect", "insufficient"}
VALID_CLAIM_SUPPORT = {"supported", "not_supported", "insufficient"}
VALID_APPEARANCE_DIFFERENCE = {"visible", "not_visible", "uncertain"}
VALID_DEFECT_QUALIFICATION = {"confirmed", "not_qualified", "indeterminate"}
VALID_SPECIAL_PRODUCT_RULE = {"not_required", "satisfied", "required_but_not_quantified"}
VALID_ACTION_RELATIONS = {"direct_contact", "indirect_force", "no_contact", "uncertain", "not_applicable"}
DIRECT_ACTION_RELATIONS = {"direct_contact", "indirect_force"}


def _float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(0.0, min(parsed, 1.0)) if math.isfinite(parsed) else default


def _frame_key(value: Dict[str, Any]) -> tuple[int, int] | None:
    try:
        return int(value.get("video_index") or 0), int(value["global_frame_index"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def _bool(value: Any) -> bool:
    return value is True or str(value or "").strip().lower() in {"true", "yes", "1", "是"}


def _enum(value: Any, allowed: set[str], fallback: str) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in allowed else fallback


def _text_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _evidence_list(value: Any) -> List[Dict[str, Any]]:
    if isinstance(value, dict):
        value = [value]
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def normalize_supplemental_linkage(value: Any, *, temporal: bool = False) -> bool | None:
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not normalized or normalized in {"unknown", "unresolved", "uncertain", "not_assessed", "none", "null"}:
        return None
    if normalized in {"false", "no", "0", "not_linked", "mismatched"}:
        return False
    positives = {"true", "yes", "1", "verified", "matched", "linked", "high"}
    if temporal:
        positives.update({"pre_opening", "during_opening", "post_opening", "same_timeline"})
    else:
        positives.update({"same_item", "same_product", "identity_matched"})
    return True if normalized in positives else None


def linked_supplemental_damage_reference(evidence: Any) -> Dict[str, Any]:
    for item in evidence if isinstance(evidence, list) else []:
        if not isinstance(item, dict) or "image" not in str(item.get("source_type") or "").lower():
            continue
        if (
            item.get("fact")
            and item.get("damage_visible") is True
            and _float(item.get("confidence")) >= 0.8
            and normalize_supplemental_linkage(item.get("same_item_linkage")) is True
            and normalize_supplemental_linkage(item.get("temporal_linkage"), temporal=True) is True
        ):
            return {
                "source_type": "supplementary_image",
                "image_index": item.get("image_index"),
                "asset_ref": item.get("asset_ref"),
                "fact": item.get("fact"),
                "why_it_matters": item.get("why_it_matters"),
                "confidence": _float(item.get("confidence")),
                "same_item_linkage": True,
                "temporal_linkage": True,
                "damage_visible": True,
            }
    return {}


def _same_chain(before: Dict[str, Any], action: Dict[str, Any], after: Dict[str, Any]) -> bool:
    identity_keys = ("video_index", "subject", "location", "chain_id")
    if any(not before.get(key) or before.get(key) != action.get(key) or before.get(key) != after.get(key) for key in identity_keys):
        return False
    try:
        indices = [int(item.get("global_frame_index")) for item in (before, action, after)]
    except (TypeError, ValueError, OverflowError):
        return False
    return indices[0] < indices[1] < indices[2] and all(item.get("timestamp") for item in (before, action, after))


def _reference_allowed(reference: Dict[str, Any], valid_frames: set[tuple[int, int]] | None) -> bool:
    if valid_frames is None:
        return True
    key = _frame_key(reference)
    return key is not None and key in valid_frames


def _has_structured_action_chain(item: Dict[str, Any], valid_frames: set[tuple[int, int]] | None = None) -> bool:
    return any(
        _same_chain(before, action, after)
        and item.get("causal_action_relation") in DIRECT_ACTION_RELATIONS
        and action.get("action_relation") in DIRECT_ACTION_RELATIONS
        and all(_reference_allowed(reference, valid_frames) for reference in (before, action, after))
        for before in item.get("before_action_evidence") or []
        for action in item.get("action_evidence") or []
        for after in item.get("after_action_evidence") or []
    )


def _has_preopening_reference(item: Dict[str, Any], valid_frames: set[tuple[int, int]] | None = None) -> bool:
    reference = item.get("first_visible_evidence")
    if not isinstance(reference, dict):
        return False
    if _frame_key(reference) is None:
        return False
    return bool(reference.get("timestamp")) and _reference_allowed(reference, valid_frames)


def _replayable_damage_reference(
    item: Dict[str, Any],
    damage_observability: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    if not isinstance(damage_observability, dict) or damage_observability.get("same_item_linkage") is not True:
        return {}
    reference = item.get("first_visible_evidence")
    candidates = [reference] + list(item.get("after_action_evidence") or [])
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        if _frame_key(candidate) is None:
            continue
        if candidate.get("timestamp") and candidate.get("damage_visible") is True:
            return candidate
    return {}


def _has_direct_chain(item: Dict[str, Any]) -> bool:
    if item["causal_evidence_level"] != "direct" or item["damage_presence"] != "confirmed":
        return False
    if item["most_likely_origin"] == "customer_opening_or_handling":
        return (
            item["opening_action_visible"]
            and item["damage_change_observed"]
            and item["claim_support"] == "not_supported"
            and _has_structured_action_chain(item)
        )
    return (
        item["most_likely_origin"] in {"manufacturing_or_original_packaging", "logistics_transport", "mixed"}
        and item["pre_opening_state_visible"]
        and item["damage_timing"] == "pre_opening_visible"
        and item["claim_support"] == "supported"
        and _has_preopening_reference(item)
    )


def _has_linked_supplemental_damage(evidence: Any) -> bool:
    return bool(linked_supplemental_damage_reference(evidence))


def normalize_damage_causality(value: Any) -> Dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    action_evidence = _evidence_list(source.get("action_evidence"))
    action_relations = {
        _enum(item.get("action_relation"), VALID_ACTION_RELATIONS, "uncertain")
        for item in action_evidence
    }
    inferred_action_relation = next(iter(action_relations)) if len(action_relations) == 1 else "uncertain"
    possible_origins: List[Dict[str, Any]] = []
    for raw in source.get("possible_origins") or []:
        if not isinstance(raw, dict):
            continue
        origin = _enum(raw.get("origin"), VALID_ORIGINS, "indeterminate")
        possible_origins.append(
            {
                **raw,
                "origin": origin,
                "confidence": _float(raw.get("confidence")),
            }
        )
    return {
        **source,
        "damage_presence": _enum(source.get("damage_presence"), VALID_PRESENCE, "uncertain"),
        "damage_timing": _enum(source.get("damage_timing"), VALID_TIMING, "unknown"),
        "pre_opening_state_visible": _bool(source.get("pre_opening_state_visible")),
        "opening_action_visible": _bool(source.get("opening_action_visible")),
        "damage_change_observed": _bool(source.get("damage_change_observed")),
        "most_likely_origin": _enum(source.get("most_likely_origin"), VALID_ORIGINS, "indeterminate"),
        "origin_confidence": _float(source.get("origin_confidence")),
        "causal_evidence_level": _enum(source.get("causal_evidence_level"), VALID_EVIDENCE_LEVELS, "insufficient"),
        "causal_action_relation": _enum(
            source.get("causal_action_relation"), VALID_ACTION_RELATIONS, inferred_action_relation
        ),
        "claim_support": _enum(source.get("claim_support"), VALID_CLAIM_SUPPORT, "insufficient"),
        "appearance_difference": _enum(
            source.get("appearance_difference"), VALID_APPEARANCE_DIFFERENCE, "uncertain"
        ),
        "business_defect_qualification": _enum(
            source.get("business_defect_qualification"), VALID_DEFECT_QUALIFICATION, "indeterminate"
        ),
        "special_product_rule": _enum(
            source.get("special_product_rule"), VALID_SPECIAL_PRODUCT_RULE, "not_required"
        ),
        "possible_origins": possible_origins,
        "alternative_explanations": _text_list(source.get("alternative_explanations")),
        "before_action_evidence": _evidence_list(source.get("before_action_evidence")),
        "action_evidence": action_evidence,
        "after_action_evidence": _evidence_list(source.get("after_action_evidence")),
    }


def apply_damage_causality_guard(
    result: Dict[str, Any],
    scenario: str,
    valid_frames: Iterable[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """伤情事实与损伤成因分层；只有直接用户致损链可覆盖可见伤情事实。"""
    output = dict(result)
    if scenario != "product_damage":
        return output

    assessment = normalize_damage_causality(output.get("damage_causality_assessment"))
    supplemental_reference = linked_supplemental_damage_reference(output.get("adopted_evidence"))
    if supplemental_reference:
        assessment["supplemental_damage_presence"] = "confirmed"
        assessment["supplemental_damage_reference"] = supplemental_reference
    valid_frame_keys = None if valid_frames is None else {
        key
        for frame in valid_frames
        if (key := _frame_key(frame)) is not None
    }
    if (
        assessment["causal_evidence_level"] == "direct"
        and not _has_structured_action_chain(assessment, valid_frame_keys)
    ):
        reference = assessment.get("first_visible_evidence")
        assessment["causal_evidence_level"] = (
            "indirect"
            if assessment["damage_presence"] == "confirmed"
            and isinstance(reference, dict)
            and bool(reference.get("timestamp"))
            else "insufficient"
        )
        assessment["most_likely_origin"] = "indeterminate"
        assessment["origin_confidence"] = 0.0

    output["damage_causality_assessment"] = assessment
    presence = assessment["damage_presence"]
    timing = assessment["damage_timing"]
    origin = assessment["most_likely_origin"]
    evidence_level = assessment["causal_evidence_level"]
    claim_support = assessment["claim_support"]

    direct_customer_damage = (
        presence == "confirmed"
        and origin == "customer_opening_or_handling"
        and evidence_level == "direct"
        and assessment["opening_action_visible"]
        and assessment["damage_change_observed"]
        and claim_support == "not_supported"
        and _has_structured_action_chain(assessment, valid_frame_keys)
    )
    direct_preexisting_damage = (
        presence == "confirmed"
        and origin in {"manufacturing_or_original_packaging", "logistics_transport", "mixed"}
        and evidence_level == "direct"
        and assessment["pre_opening_state_visible"]
        and timing == "pre_opening_visible"
        and claim_support == "supported"
        and _has_preopening_reference(assessment, valid_frame_keys)
    )
    visible_damage_confirmed = presence == "confirmed"

    if direct_customer_damage or (presence == "not_visible" and claim_support == "not_supported"):
        tendency = "does_not_support_claim"
    elif direct_preexisting_damage or visible_damage_confirmed:
        tendency = "supports_claim"
    else:
        tendency = "inconclusive"
    output["damage_evidence_tendency"] = tendency
    output["causality_guard_reason"] = (
        "证据层只记录伤情存在性、发生阶段和因果链，不改写整案标签、置信度或人工路由；"
        "最终分类建议由版本化 SOP 策略统一生成。"
    )
    return output


def aggregate_damage_causality(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    source_rows = list(rows)
    assessments = [normalize_damage_causality(row.get("damage_causality_assessment")) for row in source_rows]
    direct = [item for item in assessments if _has_direct_chain(item)]
    direct_origins = {item["most_likely_origin"] for item in direct if item["most_likely_origin"] != "indeterminate"}
    reported_direct_origins = {
        item["most_likely_origin"]
        for item in assessments
        if item["causal_evidence_level"] == "direct" and item["most_likely_origin"] != "indeterminate"
    }
    conflicting = len(reported_direct_origins) > 1

    if conflicting:
        best = max(assessments, key=lambda item: item["origin_confidence"], default=normalize_damage_causality({}))
        origin = "indeterminate"
    elif len(direct_origins) == 1:
        origin = next(iter(direct_origins))
        candidates = [item for item in direct if item["most_likely_origin"] == origin]
        best = max(candidates, key=lambda item: item["origin_confidence"])
    elif direct:
        best = max(assessments, key=lambda item: item["origin_confidence"], default=normalize_damage_causality({}))
        origin = "indeterminate"
    else:
        concrete = [item for item in assessments if item["most_likely_origin"] != "indeterminate"]
        best = max(concrete or assessments, key=lambda item: item["origin_confidence"], default=normalize_damage_causality({}))
        origin = best["most_likely_origin"]

    replayable = [
        (item, reference)
        for row, item in zip(source_rows, assessments)
        if (reference := _replayable_damage_reference(item, row.get("damage_observability")))
    ]
    supplemental_references = [
        reference
        for row in source_rows
        if (reference := linked_supplemental_damage_reference(row.get("adopted_evidence")))
    ]
    supplemental_only_damage = bool(supplemental_references) and not replayable
    first_visible = replayable[0][1] if replayable else (
        supplemental_references[0] if supplemental_references else None
    )
    damage_locations = [
        item.get("damage_type_and_location")
        for item, _ in replayable
        if item.get("damage_type_and_location")
    ]
    origin_hypotheses: Dict[str, Dict[str, Any]] = {}
    for item in assessments:
        for hypothesis in item.get("possible_origins") or []:
            origin_key = str(hypothesis.get("origin") or "indeterminate")
            current = origin_hypotheses.get(origin_key)
            if current is None or _float(hypothesis.get("confidence")) > _float(current.get("confidence")):
                origin_hypotheses[origin_key] = hypothesis
    possible_origins = sorted(
        origin_hypotheses.values(),
        key=lambda item: (-_float(item.get("confidence")), str(item.get("origin") or "")),
    )
    alternatives = [entry for item in assessments for entry in _text_list(item.get("alternative_explanations"))]
    gaps = [str(item.get("cannot_conclude_reason")) for item in assessments if item.get("cannot_conclude_reason")]

    presence_values = {item["damage_presence"] for item in assessments}
    claim_support_values = {item["claim_support"] for item in assessments}
    aggregate_presence = "confirmed" if (
        ("confirmed" in presence_values and first_visible) or supplemental_references
    ) else (
        "not_visible" if presence_values == {"not_visible"} else "uncertain"
    )
    aggregate_claim_support = best["claim_support"] if not conflicting else "insufficient"
    if claim_support_values == {"not_supported"}:
        aggregate_claim_support = "not_supported"
    appearance_values = {item["appearance_difference"] for item in assessments}
    qualification_values = {item["business_defect_qualification"] for item in assessments}
    special_rule_values = {item["special_product_rule"] for item in assessments}
    aggregate_appearance = (
        "visible" if "visible" in appearance_values
        else "not_visible" if appearance_values == {"not_visible"}
        else "uncertain"
    )
    aggregate_qualification = (
        next(iter(qualification_values)) if len(qualification_values) == 1 else "indeterminate"
    )
    aggregate_special_rule = (
        "required_but_not_quantified"
        if "required_but_not_quantified" in special_rule_values
        else "satisfied" if special_rule_values == {"satisfied"}
        else "not_required" if special_rule_values == {"not_required"}
        else "required_but_not_quantified"
    )

    return normalize_damage_causality(
        {
            **best,
            "damage_presence": aggregate_presence,
            "damage_timing": best.get("damage_timing") if not conflicting and not supplemental_only_damage else "unknown",
            "pre_opening_state_visible": best["pre_opening_state_visible"],
            "opening_action_visible": best["opening_action_visible"],
            "damage_change_observed": best["damage_change_observed"],
            "damage_type_and_location": "；".join(dict.fromkeys(map(str, damage_locations)))[:800],
            "first_visible_evidence": first_visible,
            "most_likely_origin": "indeterminate" if supplemental_only_damage else origin,
            "origin_confidence": best["origin_confidence"] if not conflicting and not supplemental_only_damage else 0.0,
            "causal_evidence_level": "insufficient" if conflicting or supplemental_only_damage else (
                best["causal_evidence_level"] if best in direct else (
                    "indirect" if best["causal_evidence_level"] in {"direct", "indirect"} else "insufficient"
                )
            ),
            "claim_support": aggregate_claim_support,
            "appearance_difference": aggregate_appearance,
            "business_defect_qualification": aggregate_qualification,
            "special_product_rule": aggregate_special_rule,
            "possible_origins": possible_origins,
            "alternative_explanations": list(dict.fromkeys(map(str, alternatives)))[:12],
            "cannot_conclude_reason": (
                "补充图片只确认损伤存在；当前没有可回链的直接动作前后证据，不能判断损伤成因。"
                if supplemental_only_damage
                else
                str(best.get("cannot_conclude_reason") or "")
                if best in direct and not conflicting
                else "；".join(dict.fromkeys(gaps))
            )[:1000]
            or ("不同时间分段对损伤成因给出冲突的直接判断。" if conflicting else "")
            or (
                "主视频没有返回可回链的损伤帧，不能聚合为已确认损伤。"
                if "confirmed" in presence_values and not first_visible
                else ""
            ),
            "segment_assessments": assessments,
        }
    )
