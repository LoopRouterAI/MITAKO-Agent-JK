"""将商品有伤图片事实转换为统一决策输入，不补造视频事实。"""
from __future__ import annotations

import copy
import math
from typing import Any, Dict, List


def _confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return max(0.0, min(number, 1.0)) if math.isfinite(number) else 0.0


def _valid_refs(parsed: Dict[str, Any], field: str, claim_id: str | None = None) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []
    for item in parsed.get("evidence_refs") or []:
        if not isinstance(item, dict) or item.get("field") != field:
            continue
        item_claim_id = str(item.get("claim_id") or "").strip()
        if claim_id is not None and item_claim_id != claim_id:
            continue
        asset_ref = str(item.get("asset_ref") or "").strip()
        fact = str(item.get("fact") or "").strip()
        if not asset_ref or not fact:
            continue
        if field == "supplemental_damage_visible" and not asset_ref.startswith("supplemental_image_"):
            continue
        if field == "claimed_item" and not asset_ref.startswith(("supplemental_image_", "official_product_reference_")):
            continue
        suffix = asset_ref.rsplit("_", 1)[-1]
        refs.append({
            "field": field,
            "claim_id": item_claim_id,
            "source_type": "official_product_reference" if asset_ref.startswith("official_product_reference_") else "supplementary_image",
            "asset_ref": asset_ref,
            "image_index": int(suffix) if asset_ref.startswith("supplemental_image_") and suffix.isdigit() else None,
            "reference_index": int(suffix) if asset_ref.startswith("official_product_reference_") and suffix.isdigit() else None,
            "timestamp": None,
            "fact": fact,
            "visible_facts": fact,
        })
    return refs


def expand_product_damage_image_observation(parsed: Dict[str, Any], case: Dict[str, Any]) -> Dict[str, Any]:
    """只扩展图片能够证明的事实；开箱、时序、速度和责任全部保持未评估。"""
    compact = copy.deepcopy(parsed)
    claimed = compact.get("claimed_item_assessment") or {}
    raw_claims = [item for item in compact.get("atomic_claim_results") or [] if isinstance(item, dict)]
    legacy_damage = compact.get("damage_assessment") or {}
    if not raw_claims and legacy_damage:
        raw_claims = [{
            "claim_id": "CLM-1",
            "subject_ref": str(claimed.get("identity_description") or "claimed_item"),
            "location": str(legacy_damage.get("location") or ""),
            "damage_type": "",
            "supplemental_visibility": "visible" if legacy_damage.get("damage_visible") is True else "uncertain",
            "same_item_linkage": claimed.get("same_item_linkage"),
            "damage_presence": "confirmed" if legacy_damage.get("damage_visible") is True else "insufficient",
            "severity_level": str(legacy_damage.get("severity_level") or "unknown"),
            "severity_confidence": legacy_damage.get("severity_confidence"),
            "structural_failure": legacy_damage.get("structural_failure"),
            "conflicting_evidence": legacy_damage.get("conflicting_evidence") is True,
            "reason": str(legacy_damage.get("reason") or ""),
        }]
    atomic_claims: List[Dict[str, Any]] = []
    for item in raw_claims:
        claim_id = str(item.get("claim_id") or "").strip()
        if not claim_id:
            continue
        claimed_refs_for_item = _valid_refs(compact, "claimed_item", claim_id)
        damage_refs_for_item = _valid_refs(compact, "supplemental_damage_visible", claim_id)
        if legacy_damage and not claimed_refs_for_item and not damage_refs_for_item:
            claimed_refs_for_item = _valid_refs(compact, "claimed_item")
            damage_refs_for_item = _valid_refs(compact, "supplemental_damage_visible")
        has_user_identity_ref = any(
            str(ref.get("asset_ref") or "").startswith("supplemental_image_")
            for ref in claimed_refs_for_item
        )
        same_item_for_item = (
            item.get("same_item_linkage") is True
            and claimed.get("same_item_linkage") is True
            and has_user_identity_ref
        )
        damage_visible_for_item = (
            item.get("damage_presence") == "confirmed"
            and item.get("supplemental_visibility") == "visible"
            and bool(damage_refs_for_item)
        )
        atomic_claims.append({
            "claim_id": claim_id,
            "subject_ref": str(item.get("subject_ref") or "").strip(),
            "location": str(item.get("location") or "").strip(),
            "damage_type": str(item.get("damage_type") or "").strip(),
            "supplemental_visibility": str(item.get("supplemental_visibility") or "not_assessed"),
            "same_item_linkage": same_item_for_item,
            "damage_presence": "confirmed" if damage_visible_for_item else "insufficient",
            "support_status": "insufficient",
            "severity_level": str(item.get("severity_level") or "unknown"),
            "severity_confidence": _confidence(item.get("severity_confidence")),
            "structural_failure": item.get("structural_failure") if isinstance(item.get("structural_failure"), bool) else None,
            "conflicting_evidence": item.get("conflicting_evidence") is True,
            "evidence_refs": [*claimed_refs_for_item, *damage_refs_for_item],
            "reason": str(item.get("reason") or "").strip(),
        })
    severity_rank = {"unknown": -1, "none": 0, "minor": 1, "moderate": 2, "severe": 3, "extreme": 4}
    strongest = max(
        atomic_claims,
        key=lambda item: (severity_rank.get(item["severity_level"], -1), item["severity_confidence"]),
        default={},
    )
    claimed_refs = _valid_refs(compact, "claimed_item")
    damage_refs = _valid_refs(compact, "supplemental_damage_visible")
    visible_claims = [item for item in atomic_claims if item["damage_presence"] == "confirmed"]
    damage_visible = bool(visible_claims)
    same_item = bool(visible_claims) and all(item["same_item_linkage"] is True for item in visible_claims)
    detail_sufficient = damage_visible and all(bool(item["evidence_refs"]) for item in visible_claims)
    identity_confidence = _confidence(claimed.get("identity_confidence"))
    severity_confidence = _confidence(strongest.get("severity_confidence"))
    confidence = min(identity_confidence, severity_confidence) if damage_visible else identity_confidence
    severity = {
        "level": str(strongest.get("severity_level") or "unknown"),
        "structural_failure": strongest.get("structural_failure"),
        "confidence": severity_confidence,
        "reason": str(strongest.get("reason") or ""),
    }
    business_qualification = (
        "confirmed"
        if damage_visible
        and same_item
        and severity["level"] in {"severe", "extreme"}
        and severity["structural_failure"] is True
        and severity_confidence >= 0.8
        else "not_qualified"
        if atomic_claims and all(item["severity_level"] in {"none", "minor", "moderate"} for item in atomic_claims)
        else "indeterminate"
    )
    supplemental_summary = {
        "provided_count": len(case.get("supplemental_images") or []),
        "referenced_count": len(damage_refs),
        "damage_presence": "confirmed" if damage_visible else "not_assessed",
        "linkage_status": "verified" if damage_visible and same_item else "not_assessed",
        "evidence_refs": damage_refs,
    }
    evidence = [*claimed_refs, *damage_refs]
    first_damage_ref = damage_refs[0] if damage_refs else {}
    return {
        **compact,
        "predicted_label": "review",
        "system_yes_no": "REVIEW",
        "decision": "request_more_material",
        "confidence": confidence,
        "human_required": True,
        "visual_evidence_verdict": "用户图片中可见所诉商品损伤；是否形成到手已损的证据链仍需按开箱规则判断。" if damage_visible else "现有图片不足以确认所诉商品损伤。",
        "overall_audit": {
            "conclusion": "现有图片仅完成商品身份、伤情和严重度观察。",
            "confidence": confidence,
            "core_reason": str(strongest.get("reason") or claimed.get("reason") or "图片事实已完成观察。"),
            "business_follow_up_suggestion": "普通伤情需补充初次开箱视频；高置信严重结构伤由服务端重大质量问题规则单独判断。",
        },
        "opening_video_evidence": {
            "present": False, "sop_compliant": False, "status": "yellow", "confidence": 1.0,
            "reason": "本轮送审材料没有开箱视频，图片不能替代初次拆包和连续开箱证据。",
            "evidence_refs": [], "validated_requirements": [], "derivation": "media_inventory",
        },
        "video_audit_conclusion": {
            "technical_timeline_status": "not_provided", "source": "not_assessed",
            "opening_video_compliance": {
                "opening_action_visible": None, "sealed_start": None, "waybill_visible": None,
                "single_take_continuity": None, "issue_visible_in_continuous_opening": None,
                "result": "indeterminate", "validated_fields": [], "evidence_refs": [], "source": "not_assessed",
            },
            "playback_speed": "unknown",
            "speed_review_impact": {
                "status": "not_assessed", "critical_evidence_observable": None,
                "affected_review_items": [], "evidence_refs": [],
                "reason": "未提供视频，未执行播放速度判断。", "source": "not_assessed",
            },
        },
        "damage_causality_assessment": {
            "damage_presence": "confirmed" if damage_visible else "uncertain",
            "main_video_detail_sufficient": None,
            "supplemental_damage_presence": supplemental_summary["damage_presence"],
            "damage_type_and_location": str(strongest.get("location") or ""),
            "business_defect_qualification": business_qualification,
            "severity_assessment": severity,
            "first_visible_evidence": {"asset_ref": first_damage_ref.get("asset_ref"), "image_index": first_damage_ref.get("image_index"), "evidence_refs": damage_refs},
            "claim_support": "supported" if damage_visible and same_item else "insufficient",
            "damage_timing": "indeterminate", "damage_change_observed": False,
            "pre_opening_state_visible": False, "opening_action_visible": False,
            "most_likely_origin": "indeterminate", "causal_evidence_level": "none",
            "causal_action_relation": "not_applicable",
            "causal_chain_assessment": {"status": "indeterminate", "evidence_level": "none", "reason": "静态图片不能证明损伤出现时态或形成责任。"},
            "evidence_source_summary": {
                "primary_video": {"damage_presence": "not_assessed", "referenced_count": 0, "evidence_refs": []},
                "supplemental_images": supplemental_summary,
            },
            "evidence_refs": damage_refs, "reason": str(strongest.get("reason") or ""),
        },
        "damage_observability": {
            "status": "fully_observable" if detail_sufficient and same_item else "partial",
            "same_item_linkage": same_item, "claimed_region_closeup": detail_sufficient,
            "required_view_coverage": 1.0 if detail_sufficient else 0.0,
            "conflicting_evidence": any(item["conflicting_evidence"] for item in atomic_claims),
            "missing_views": [] if detail_sufficient else ["所诉部位清晰近景"],
            "reason": str(strongest.get("reason") or claimed.get("reason") or ""),
        },
        "claim_fact_assessment": {
            "atomic_claim_results": atomic_claims,
            "order_linkage": {"status": "verified" if same_item else "indeterminate", "reason": str(claimed.get("reason") or "商品身份仍需核对。"), "evidence_refs": claimed_refs},
            "scene_match": {"status": "matched", "reason": "当前诉求属于商品实体损伤审核。"},
            "assembly": {"state": "not_applicable", "reason": "本轮未观察到可复位装配事实。"},
        },
        "adopted_evidence": evidence, "supporting_evidence": evidence, "challenging_evidence": [],
        "model_limitations": ["未提供视频，未评估开箱链、时序、速度、剪辑和损伤成因。"],
    }
