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
    """商品有伤只有形成直接因果链时才允许输出确定标签。"""
    output = dict(result)
    if scenario != "product_damage":
        return output

    assessment = normalize_damage_causality(output.get("damage_causality_assessment"))
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

    if direct_customer_damage:
        label = "negative"
    elif direct_preexisting_damage:
        label = "positive"
    else:
        label = "review"

    output["predicted_label"] = label
    output["system_yes_no"] = {"positive": "YES", "negative": "NO"}.get(label, "REVIEW")
    if label == "review":
        output["decision"] = "manual_review"
        output["confidence"] = min(_float(output.get("confidence"), 0.5), 0.69)
        output["causality_guard_reason"] = (
            "伤情存在性与损伤成因必须分开判断；当前缺少足以证明损伤在拆封前已存在，"
            "或由用户操作直接造成的连续前后证据。"
        )
    else:
        output["confidence"] = min(_float(output.get("confidence"), origin_confidence), origin_confidence or 1.0)
        output["causality_guard_reason"] = "已形成拆封/操作前后可回链的直接因果证据。"
    return output


def aggregate_damage_causality(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    assessments = [normalize_damage_causality(row.get("damage_causality_assessment")) for row in rows]
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
        best = max(assessments, key=lambda item: item["origin_confidence"], default=normalize_damage_causality({}))
        origin = best["most_likely_origin"]

    first_visible = next((item.get("first_visible_evidence") for item in assessments if item.get("first_visible_evidence")), None)
    damage_locations = [item.get("damage_type_and_location") for item in assessments if item.get("damage_type_and_location")]
    possible_origins = [origin_item for item in assessments for origin_item in item.get("possible_origins") or []]
    alternatives = [entry for item in assessments for entry in _text_list(item.get("alternative_explanations"))]
    gaps = [str(item.get("cannot_conclude_reason")) for item in assessments if item.get("cannot_conclude_reason")]

    return normalize_damage_causality(
        {
            **best,
            "damage_presence": "confirmed" if any(item["damage_presence"] == "confirmed" for item in assessments) else "uncertain",
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
            "claim_support": best["claim_support"] if not conflicting else "insufficient",
            "possible_origins": possible_origins[:20],
            "alternative_explanations": list(dict.fromkeys(map(str, alternatives)))[:12],
            "cannot_conclude_reason": (str(best.get("cannot_conclude_reason") or "") if best in direct and not conflicting else "；".join(dict.fromkeys(gaps)))[:1000]
            or ("不同时间分段对损伤成因给出冲突的直接判断。" if conflicting else ""),
            "segment_assessments": assessments,
        }
    )
