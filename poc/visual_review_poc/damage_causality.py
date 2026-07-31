# -*- coding: utf-8 -*-
"""商品有伤场景的因果判定归一化与分段聚合。"""
from __future__ import annotations

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


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(float(value), 1.0))
    except (TypeError, ValueError):
        return default


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


def _same_chain(before: Dict[str, Any], action: Dict[str, Any], after: Dict[str, Any]) -> bool:
    identity_keys = ("video_index", "subject", "location", "chain_id")
    if any(not before.get(key) or before.get(key) != action.get(key) or before.get(key) != after.get(key) for key in identity_keys):
        return False
    try:
        indices = [int(item.get("global_frame_index")) for item in (before, action, after)]
    except (TypeError, ValueError):
        return False
    return indices[0] < indices[1] < indices[2] and all(item.get("timestamp") for item in (before, action, after))


def _reference_allowed(reference: Dict[str, Any], valid_frames: set[tuple[int, int]] | None) -> bool:
    if valid_frames is None:
        return True
    try:
        key = (int(reference.get("video_index")), int(reference.get("global_frame_index")))
    except (TypeError, ValueError):
        return False
    return key in valid_frames


def _has_structured_action_chain(item: Dict[str, Any], valid_frames: set[tuple[int, int]] | None = None) -> bool:
    return any(
        _same_chain(before, action, after)
        and all(_reference_allowed(reference, valid_frames) for reference in (before, action, after))
        for before in item.get("before_action_evidence") or []
        for action in item.get("action_evidence") or []
        for after in item.get("after_action_evidence") or []
    )


def _has_preopening_reference(item: Dict[str, Any], valid_frames: set[tuple[int, int]] | None = None) -> bool:
    reference = item.get("first_visible_evidence")
    if not isinstance(reference, dict):
        return False
    try:
        int(reference.get("video_index"))
        int(reference.get("global_frame_index"))
    except (TypeError, ValueError):
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
        try:
            int(candidate.get("video_index"))
            int(candidate.get("global_frame_index"))
        except (TypeError, ValueError):
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
    for item in evidence if isinstance(evidence, list) else []:
        if not isinstance(item, dict) or "image" not in str(item.get("source_type") or "").lower():
            continue
        linkage = item.get("same_item_linkage")
        linkage_text = str(linkage or "").strip().lower()
        linkage_unresolved = not linkage or any(
            marker in linkage_text for marker in ("unresolved", "unknown", "不确定", "无法", "未建立")
        )
        if item.get("fact") and _float(item.get("confidence")) >= 0.8 and not linkage_unresolved:
            return True
    return False


def normalize_damage_causality(value: Any) -> Dict[str, Any]:
    source = value if isinstance(value, dict) else {}
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
        "claim_support": _enum(source.get("claim_support"), VALID_CLAIM_SUPPORT, "insufficient"),
        "possible_origins": possible_origins,
        "alternative_explanations": _text_list(source.get("alternative_explanations")),
        "before_action_evidence": _evidence_list(source.get("before_action_evidence")),
        "action_evidence": _evidence_list(source.get("action_evidence")),
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
    if _has_linked_supplemental_damage(output.get("adopted_evidence")):
        assessment["supplemental_damage_presence"] = "confirmed"
    output["damage_causality_assessment"] = assessment
    presence = assessment["damage_presence"]
    timing = assessment["damage_timing"]
    origin = assessment["most_likely_origin"]
    evidence_level = assessment["causal_evidence_level"]
    claim_support = assessment["claim_support"]
    origin_confidence = assessment["origin_confidence"]
    valid_frame_keys = None if valid_frames is None else {
        (int(frame.get("video_index") or 0), int(frame.get("global_frame_index") or 0))
        for frame in valid_frames
        if frame.get("global_frame_index") is not None
    }

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
    first_visible = replayable[0][1] if replayable else None
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
    aggregate_presence = "confirmed" if "confirmed" in presence_values and first_visible else (
        "not_visible" if presence_values == {"not_visible"} else "uncertain"
    )
    aggregate_claim_support = best["claim_support"] if not conflicting else "insufficient"
    if claim_support_values == {"not_supported"}:
        aggregate_claim_support = "not_supported"

    return normalize_damage_causality(
        {
            **best,
            "damage_presence": aggregate_presence,
            "damage_timing": best.get("damage_timing") if not conflicting else "unknown",
            "pre_opening_state_visible": best["pre_opening_state_visible"],
            "opening_action_visible": best["opening_action_visible"],
            "damage_change_observed": best["damage_change_observed"],
            "damage_type_and_location": "；".join(dict.fromkeys(map(str, damage_locations)))[:800],
            "first_visible_evidence": first_visible,
            "most_likely_origin": origin,
            "origin_confidence": best["origin_confidence"] if not conflicting else 0.0,
            "causal_evidence_level": "insufficient" if conflicting else (
                best["causal_evidence_level"] if best in direct else (
                    "indirect" if best["causal_evidence_level"] in {"direct", "indirect"} else "insufficient"
                )
            ),
            "claim_support": aggregate_claim_support,
            "possible_origins": possible_origins,
            "alternative_explanations": list(dict.fromkeys(map(str, alternatives)))[:12],
            "cannot_conclude_reason": (
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
