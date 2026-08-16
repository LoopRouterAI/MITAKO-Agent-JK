# -*- coding: utf-8 -*-
"""Gemini 审核结果的共享结构化输出契约。"""
from __future__ import annotations


def _string(*, enum: list[str] | None = None, nullable: bool = False) -> dict:
    value: dict = {"type": "string"}
    if enum:
        value["enum"] = enum
    if nullable:
        value["nullable"] = True
    return value


def _number(*, nullable: bool = False) -> dict:
    value = {"type": "number"}
    if nullable:
        value["nullable"] = True
    return value


def _integer(*, nullable: bool = False) -> dict:
    value = {"type": "integer"}
    if nullable:
        value["nullable"] = True
    return value


def _boolean(*, nullable: bool = False) -> dict:
    value = {"type": "boolean"}
    if nullable:
        value["nullable"] = True
    return value


def _array(items: dict, *, max_items: int | None = None) -> dict:
    value = {"type": "array", "items": items}
    if max_items is not None:
        value["maxItems"] = max_items
    return value


def _object(
    properties: dict[str, dict],
    *,
    required: tuple[str, ...] = (),
    nullable: bool = False,
) -> dict:
    value: dict = {"type": "object", "properties": properties}
    if required:
        value["required"] = list(required)
    if nullable:
        value["nullable"] = True
    return value


TIMESTAMP_EVIDENCE = _object(
    {
        "video_index": _integer(nullable=True),
        "global_frame_index": _integer(nullable=True),
        "timestamp": _string(),
        "asset_ref": _string(),
        "fact": _string(),
        "action_relation": _string(
            enum=["direct_contact", "indirect_force", "no_contact", "uncertain", "not_applicable"],
            nullable=True,
        ),
    },
    required=("timestamp", "asset_ref", "fact"),
)

SUBJECT_VISIBILITY = _object(
    {
        "subject_id": _string(enum=["shipping_package", "product_package", "claimed_item"]),
        "state": _string(enum=["visible", "partial", "occluded", "out_of_frame", "not_yet_exposed", "unknown"]),
        "identity_match": _string(enum=["matched", "not_matched", "unknown"], nullable=True),
    },
    required=("subject_id", "state"),
)

FRAME_FINDING = _object(
    {
        "video_index": _integer(nullable=True),
        "global_frame_index": _integer(nullable=True),
        "timestamp": _string(),
        "visible_facts": _string(),
        "risk": _string(),
        "subject_visibility": _array(SUBJECT_VISIBILITY),
    },
    required=("timestamp", "visible_facts", "risk", "subject_visibility"),
)

INDEXED_FRAME_FINDING = _object(
    {
        **FRAME_FINDING["properties"],
        "video_index": _integer(),
        "global_frame_index": _integer(),
    },
    required=(
        "video_index",
        "global_frame_index",
        "timestamp",
        "visible_facts",
        "risk",
        "subject_visibility",
    ),
)

OUT_OF_FRAME_EVENT = _object(
    {
        "start_timestamp": _string(),
        "end_timestamp": _string(),
        "duration_seconds": _number(),
        "visibility": _string(enum=["out_of_frame", "occluded", "unknown"]),
        "within_required_display_window": _boolean(),
        "identity_reestablished": _boolean(),
        "reason": _string(),
    },
    required=(
        "start_timestamp",
        "end_timestamp",
        "duration_seconds",
        "visibility",
        "within_required_display_window",
        "identity_reestablished",
        "reason",
    ),
)

TRACKED_SUBJECT = _object(
    {
        "subject_id": _string(enum=["shipping_package", "product_package", "claimed_item"]),
        "description": _string(),
        "tracking_start": _string(),
        "tracking_end": _string(),
        "first_exposed_timestamp": _string(),
        "visibility_coverage": _number(),
        "out_of_frame_events": _array(OUT_OF_FRAME_EVENT),
    },
    required=(
        "subject_id",
        "description",
        "tracking_start",
        "tracking_end",
        "first_exposed_timestamp",
        "visibility_coverage",
        "out_of_frame_events",
    ),
)

OBJECT_CONTINUITY = _object(
    {
        "tracked_subjects": _array(TRACKED_SUBJECT),
        "continuity_verdict": _string(enum=["continuous", "brief_occlusion", "long_absence", "indeterminate"]),
        "longest_out_of_frame_seconds": _number(),
        "total_unobserved_seconds": _number(),
        "critical_events": _array(TIMESTAMP_EVIDENCE),
    },
    required=(
        "tracked_subjects",
        "continuity_verdict",
        "longest_out_of_frame_seconds",
        "total_unobserved_seconds",
        "critical_events",
    ),
    nullable=True,
)

OVERALL_AUDIT = _object(
    {
        "conclusion": _string(),
        "confidence": _number(),
        "core_reason": _string(),
        "business_follow_up_suggestion": _string(),
    },
    required=("conclusion", "confidence", "core_reason", "business_follow_up_suggestion"),
)

SPEED_REVIEW_IMPACT = _object(
    {
        "status": _string(enum=["none", "uncertain", "material"]),
        "critical_evidence_observable": _boolean(nullable=True),
        "affected_review_items": _array(_string()),
        "evidence_refs": _array(TIMESTAMP_EVIDENCE),
        "reason": _string(),
    },
    required=("status", "critical_evidence_observable", "affected_review_items", "evidence_refs", "reason"),
)

OPENING_EVIDENCE_REFERENCE = _object(
    {
        "field": _string(enum=[
            "sealed_start",
            "waybill_visible",
            "single_take_continuity",
            "issue_visible_in_continuous_opening",
        ]),
        "video_index": _integer(nullable=True),
        "global_frame_index": _integer(nullable=True),
        "timestamp": _string(),
    },
    required=("field", "timestamp"),
)

OPENING_VIDEO_COMPLIANCE = _object(
    {
        "sealed_start": _boolean(nullable=True),
        "waybill_visible": _boolean(nullable=True),
        "single_take_continuity": _boolean(nullable=True),
        "issue_visible_in_continuous_opening": _boolean(nullable=True),
        "evidence_refs": _array(OPENING_EVIDENCE_REFERENCE),
        "result": _string(enum=["compliant", "noncompliant", "indeterminate"]),
    },
    required=(
        "sealed_start",
        "waybill_visible",
        "single_take_continuity",
        "issue_visible_in_continuous_opening",
        "evidence_refs",
        "result",
    ),
)

OPENING_COMPLIANCE_RESPONSE_SCHEMA = OPENING_VIDEO_COMPLIANCE

OPENING_START_RESPONSE_SCHEMA = _object(
    {
        "result": _string(enum=["sealed", "unsealed", "indeterminate"]),
        "sealed_start": _boolean(nullable=True),
        "evidence_refs": _array(_object(
            {
                "video_index": _integer(),
                "global_frame_index": _integer(),
                "timestamp": _string(),
            },
            required=("video_index", "global_frame_index", "timestamp"),
        )),
        "reason": _string(),
    },
    required=("result", "sealed_start", "evidence_refs", "reason"),
)

OPENING_VIDEO_ROLE_RESPONSE_SCHEMA = _object(
    {
        "candidates": _array(_object(
            {
                "video_index": _integer(),
                "is_opening_video": _boolean(nullable=True),
                "sealed_package_visible": _boolean(nullable=True),
                "opening_action_visible": _boolean(nullable=True),
                "confidence": _number(),
                "reason": _string(),
                "evidence_refs": _array(_object(
                    {
                        "global_frame_index": _integer(),
                        "timestamp": _string(),
                    },
                    required=("global_frame_index", "timestamp"),
                ), max_items=3),
            },
            required=(
                "video_index", "is_opening_video", "sealed_package_visible",
                "opening_action_visible", "confidence", "reason", "evidence_refs",
            ),
        )),
    },
    required=("candidates",),
)

NATIVE_ATOMIC_CLAIM = _object(
    {
        "claim_id": _string(),
        "subject_ref": _string(),
        "location": _string(),
        "damage_type": _string(),
        "main_video_visibility": _string(enum=["visible", "clearly_not_visible", "uncertain", "not_assessed"]),
        "supplemental_visibility": _string(enum=["visible", "clearly_not_visible", "uncertain", "not_assessed"]),
        "same_item_linkage": _boolean(nullable=True),
        "damage_presence": _string(enum=["confirmed", "not_found_after_clear_coverage", "insufficient"]),
        "condition_at_unboxing": _string(enum=["supported", "not_supported", "insufficient"]),
        "severity_level": _string(enum=["none", "minor", "moderate", "severe", "extreme", "unknown"]),
        "severity_confidence": _number(),
        "structural_failure": _boolean(nullable=True),
        "conflicting_evidence": _boolean(),
        "evidence_refs": _array(
            _object(
                {
                    "asset_ref": _string(),
                    "timestamp": _string(nullable=True),
                    "fact": _string(),
                },
                required=("asset_ref", "timestamp", "fact"),
            ),
            max_items=4,
        ),
        "reason": _string(),
    },
    required=(
        "claim_id", "subject_ref", "location", "damage_type",
        "main_video_visibility", "supplemental_visibility", "same_item_linkage",
        "damage_presence", "condition_at_unboxing",
        "severity_level", "severity_confidence", "structural_failure",
        "conflicting_evidence", "evidence_refs", "reason",
    ),
)

NATIVE_VIDEO_PERCEPTION_RESPONSE_SCHEMA = _object(
    {
        "sealed_start": _boolean(nullable=True),
        "waybill_visible": _boolean(nullable=True),
        "continuous": _boolean(nullable=True),
        "has_edit": _boolean(nullable=True),
        "has_offscreen": _boolean(nullable=True),
        "has_speed_change": _boolean(nullable=True),
        "all_items_shown": _boolean(nullable=True),
        "issue_visible": _boolean(nullable=True),
        "opening_action_assessment": _object(
            {
                "present": _boolean(nullable=True),
                "confidence": _number(),
                "reason": _string(),
                "asset_ref": _string(nullable=True),
                "timestamp": _string(nullable=True),
                "fact": _string(nullable=True),
            },
            required=(
                "present", "confidence", "reason",
                "asset_ref", "timestamp", "fact",
            ),
        ),
        "claimed_item_assessment": _object(
            {
                "identity_description": _string(),
                "identity_anchor_asset_ref": _string(),
                "identity_confidence": _number(),
                "alternative_candidates_checked": _string(),
                "appeared": _boolean(nullable=True),
                "first_visible_timestamp": _string(nullable=True),
                "last_visible_timestamp": _string(nullable=True),
                "presentation_complete": _boolean(nullable=True),
                "offscreen_during_presentation": _boolean(nullable=True),
                "reason": _string(),
            },
            required=(
                "identity_description",
                "identity_anchor_asset_ref",
                "identity_confidence",
                "alternative_candidates_checked",
                "appeared",
                "first_visible_timestamp",
                "last_visible_timestamp",
                "presentation_complete",
                "offscreen_during_presentation",
                "reason",
            ),
        ),
        "speed_assessment": _object(
            {
                "value": _string(enum=["normal", "accelerated", "unknown"]),
                "confidence": _number(),
                "evidence_basis": _string(enum=[
                    "observable_realtime_anchor",
                    "natural_audio_cadence",
                    "motion_semantics_only",
                    "none",
                ]),
                "affects_visual_judgement": _boolean(nullable=True),
                "reason": _string(),
            },
            required=(
                "value",
                "confidence",
                "evidence_basis",
                "affects_visual_judgement",
                "reason",
            ),
        ),
        "damage_assessment": _object(
            {
                "causal_chain_status": _string(enum=[
                    "direct_customer_action",
                    "pre_existing_visible",
                    "no_observed_change",
                    "indeterminate",
                ]),
                "causal_evidence_level": _string(enum=[
                    "direct", "corroborated", "indirect", "none",
                ]),
                "causal_evidence_refs": _array(
                    _object(
                        {
                            "stage": _string(enum=["before_action", "action", "after_action"]),
                            "asset_ref": _string(),
                            "timestamp": _string(),
                            "subject": _string(),
                            "location": _string(),
                            "chain_id": _string(),
                            "action_relation": _string(enum=[
                                "direct_contact", "indirect_force", "no_contact", "uncertain", "not_applicable",
                            ]),
                            "damage_visible": _boolean(nullable=True),
                            "fact": _string(),
                        },
                        required=(
                            "stage", "asset_ref", "timestamp", "subject", "location",
                            "chain_id", "action_relation", "damage_visible", "fact",
                        ),
                    ),
                    max_items=3,
                ),
                "reason": _string(),
            },
            required=(
                "causal_chain_status",
                "causal_evidence_level",
                "causal_evidence_refs",
                "reason",
            ),
        ),
        "atomic_claim_results": _array(NATIVE_ATOMIC_CLAIM, max_items=20),
        "field_confidences": _object(
            {
                "sealed_start": _number(),
                "waybill_visible": _number(),
                "continuous": _number(),
                "has_edit": _number(),
                "has_offscreen": _number(),
                "has_speed_change": _number(),
                "all_items_shown": _number(),
                "issue_visible": _number(),
            },
            required=(
                "sealed_start",
                "waybill_visible",
                "continuous",
                "has_edit",
                "has_offscreen",
                "has_speed_change",
                "all_items_shown",
                "issue_visible",
            ),
        ),
        "evidence_refs": _array(
            _object(
                {
                    # 百度云对完整契约存在复杂度上限；允许值由本地适配层白名单校验。
                    "field": _string(),
                    "asset_ref": _string(),
                    "timestamp": _string(nullable=True),
                    "fact": _string(),
                },
                required=("field", "asset_ref", "timestamp", "fact"),
            ),
            max_items=18,
        ),
    },
    required=(
        "sealed_start",
        "waybill_visible",
        "continuous",
        "has_edit",
        "has_offscreen",
        "has_speed_change",
        "all_items_shown",
        "issue_visible",
        "opening_action_assessment",
        "claimed_item_assessment",
        "speed_assessment",
        "damage_assessment",
        "atomic_claim_results",
        "field_confidences",
        "evidence_refs",
    ),
)

PRODUCT_DAMAGE_IMAGE_ATOMIC_CLAIM = _object(
    {
        "claim_id": _string(),
        "subject_ref": _string(),
        "location": _string(),
        "damage_type": _string(),
        "supplemental_visibility": _string(enum=[
            "visible", "clearly_not_visible", "uncertain", "not_assessed",
        ]),
        "same_item_linkage": _boolean(nullable=True),
        "damage_presence": _string(enum=[
            "confirmed", "not_found_after_clear_coverage", "insufficient",
        ]),
        "severity_level": _string(enum=[
            "none", "minor", "moderate", "severe", "extreme", "unknown",
        ]),
        "severity_confidence": _number(),
        "structural_failure": _boolean(nullable=True),
        "conflicting_evidence": _boolean(),
        "reason": _string(),
    },
    required=(
        "claim_id", "subject_ref", "location", "damage_type",
        "supplemental_visibility", "same_item_linkage", "damage_presence",
        "severity_level", "severity_confidence", "structural_failure",
        "conflicting_evidence", "reason",
    ),
)


PRODUCT_DAMAGE_IMAGE_RESPONSE_SCHEMA = _object(
    {
        "claimed_item_assessment": _object(
            {
                "identity_description": _string(),
                "identity_confidence": _number(),
                "same_item_linkage": _boolean(nullable=True),
                "reason": _string(),
            },
            required=("identity_description", "identity_confidence", "same_item_linkage", "reason"),
        ),
        "atomic_claim_results": _array(PRODUCT_DAMAGE_IMAGE_ATOMIC_CLAIM, max_items=20),
        "evidence_refs": _array(
            _object(
                {
                    "field": _string(enum=["claimed_item", "supplemental_damage_visible"]),
                    "claim_id": _string(),
                    "asset_ref": _string(),
                    "fact": _string(),
                },
                required=("field", "claim_id", "asset_ref", "fact"),
            ),
            max_items=16,
        ),
    },
    required=("claimed_item_assessment", "atomic_claim_results", "evidence_refs"),
)


CLAIM_IDENTITY_RESPONSE_SCHEMA = _object(
    {
        "match_status": _string(enum=["matched", "ambiguous", "not_matched"]),
        "confidence": _number(),
        "expected_order_item": _object(
            {
                "item_ref": _string(),
                "sku": _string(),
                "product_name": _string(),
                "specification": _string(),
            },
            required=("item_ref", "sku", "product_name", "specification"),
        ),
        "evidence_refs": _array(
            _object(
                {
                    "asset_ref": _string(),
                    "fact": _string(),
                },
                required=("asset_ref", "fact"),
            ),
            max_items=12,
        ),
        "reason": _string(),
    },
    required=("match_status", "confidence", "expected_order_item", "evidence_refs", "reason"),
)

CLAIMED_ITEM_DETAIL_RESPONSE_SCHEMA = _object(
    {
        "identity_match": _string(enum=["matched", "not_matched", "uncertain"]),
        "identity_confidence": _number(),
        "issue_visibility": _string(enum=["visible", "not_visible", "uncertain"]),
        "issue_confidence": _number(),
        "issue_location": _string(),
        "presentation_quality": _string(enum=["clear", "partial", "insufficient"]),
        "evidence_refs": _array(
            _object(
                {
                    "global_frame_index": _integer(),
                    "timestamp": _string(),
                    "identity_fact": _string(),
                    "issue_fact": _string(),
                },
                required=(
                    "global_frame_index",
                    "timestamp",
                    "identity_fact",
                    "issue_fact",
                ),
            ),
            max_items=12,
        ),
        "reason": _string(),
    },
    required=(
        "identity_match",
        "identity_confidence",
        "issue_visibility",
        "issue_confidence",
        "issue_location",
        "presentation_quality",
        "evidence_refs",
        "reason",
    ),
)

VIDEO_AUDIT = _object(
    {
        "continuity_score": _number(),
        "continuity_reason": _string(),
        "swap_risk_level": _string(enum=["high", "medium", "low"]),
        "edit_or_cut_risk": _string(),
        "opening_integrity": _string(),
        "playback_speed": _string(enum=["normal", "accelerated", "unknown"]),
        "sampling_fps": _number(nullable=True),
        "speed_review_impact": SPEED_REVIEW_IMPACT,
        "opening_video_compliance": OPENING_VIDEO_COMPLIANCE,
    },
    required=(
        "continuity_score",
        "continuity_reason",
        "swap_risk_level",
        "edit_or_cut_risk",
        "opening_integrity",
        "playback_speed",
        "sampling_fps",
        "speed_review_impact",
        "opening_video_compliance",
    ),
)

ATOMIC_CLAIM = _object(
    {
        "claim_id": _string(),
        "subject_ref": _string(),
        "support_status": _string(enum=["supported", "not_supported", "insufficient"]),
        "evidence_refs": _array(TIMESTAMP_EVIDENCE),
        "reason": _string(),
    },
    required=("claim_id", "subject_ref", "support_status", "evidence_refs", "reason"),
)

CLAIM_FACT = _object(
    {
        "atomic_claim_results": _array(ATOMIC_CLAIM),
        "order_linkage": _object(
            {
                "status": _string(enum=["verified", "failed", "indeterminate"]),
                "expected_package_fact": _string(),
                "observed_package_fact": _string(),
                "evidence_refs": _array(TIMESTAMP_EVIDENCE),
                "reason": _string(),
            },
            required=("status", "expected_package_fact", "observed_package_fact", "evidence_refs", "reason"),
        ),
        "scene_match": _object(
            {
                "status": _string(enum=["matched", "mismatched", "indeterminate"]),
                "claimed_scene": _string(),
                "observed_scene": _string(),
                "reason": _string(),
            },
            required=("status", "claimed_scene", "observed_scene", "reason"),
        ),
        "assembly": _object(
            {
                "state": _string(enum=["permanent_damage", "resolved_assembly_issue", "unresolved", "not_applicable"]),
                "reassembly_result": _string(enum=["successful", "failed", "not_tested", "unknown"]),
                "permanent_damage": _string(enum=["supported", "not_supported", "insufficient"]),
                "evidence_refs": _array(TIMESTAMP_EVIDENCE),
                "reason": _string(),
            },
            required=("state", "reassembly_result", "permanent_damage", "evidence_refs", "reason"),
        ),
    },
    required=("atomic_claim_results", "order_linkage", "scene_match", "assembly"),
    nullable=True,
)

DAMAGE_CAUSALITY = _object(
    {
        "damage_presence": _string(enum=["confirmed", "not_visible", "uncertain"]),
        "damage_type_and_location": _string(),
        "first_visible_evidence": TIMESTAMP_EVIDENCE,
        "pre_opening_state_visible": _boolean(nullable=True),
        "opening_action_visible": _boolean(nullable=True),
        "damage_change_observed": _boolean(nullable=True),
        "damage_timing": _string(enum=["pre_opening_visible", "appears_during_opening", "post_opening_only", "unknown"]),
        "most_likely_origin": _string(enum=["manufacturing_or_original_packaging", "logistics_transport", "customer_opening_or_handling", "mixed", "indeterminate"]),
        "origin_confidence": _number(),
        "causal_evidence_level": _string(enum=["direct", "indirect", "insufficient"]),
        "causal_action_relation": _string(enum=[
            "direct_contact", "indirect_force", "no_contact", "uncertain", "not_applicable",
        ]),
        "claim_support": _string(enum=["supported", "not_supported", "insufficient"]),
        "before_action_evidence": _array(TIMESTAMP_EVIDENCE),
        "action_evidence": _array(TIMESTAMP_EVIDENCE),
        "after_action_evidence": _array(TIMESTAMP_EVIDENCE),
        "alternative_explanations": _array(_string()),
        "cannot_conclude_reason": _string(),
    },
    required=(
        "damage_presence",
        "damage_type_and_location",
        "first_visible_evidence",
        "damage_timing",
        "most_likely_origin",
        "origin_confidence",
        "causal_evidence_level",
        "causal_action_relation",
        "claim_support",
        "before_action_evidence",
        "action_evidence",
        "after_action_evidence",
        "alternative_explanations",
        "cannot_conclude_reason",
    ),
    nullable=True,
)

DAMAGE_OBSERVABILITY = _object(
    {
        "status": _string(enum=["fully_observable", "partial", "not_observable", "unknown"]),
        "same_item_linkage": _boolean(),
        "claimed_region_closeup": _boolean(),
        "required_view_coverage": _number(),
        "conflicting_evidence": _boolean(),
        "missing_views": _array(_string()),
    },
    required=(
        "status",
        "same_item_linkage",
        "claimed_region_closeup",
        "required_view_coverage",
        "conflicting_evidence",
        "missing_views",
    ),
    nullable=True,
)

EVIDENCE_ITEM = _object(
    {
        "source_type": _string(),
        "asset_ref": _string(),
        "fact": _string(),
        "why_it_matters": _string(),
        "confidence": _number(),
        "video_index": _integer(nullable=True),
        "global_frame_index": _integer(nullable=True),
        "timestamp": _string(nullable=True),
        "image_index": _integer(nullable=True),
    },
    required=("source_type", "asset_ref", "fact", "why_it_matters", "confidence"),
)

EVIDENCE_REFERENCE = _object(
    {
        "source_type": _string(),
        "asset_ref": _string(),
        "fact": _string(),
        "timestamp": _string(nullable=True),
    },
    required=("source_type", "asset_ref", "fact"),
)


REVIEW_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": _string(enum=["pass", "manual_review", "request_more_material", "fail"]),
        "predicted_label": _string(enum=["positive", "negative", "review"]),
        "system_yes_no": _string(enum=["YES", "NO", "REVIEW"]),
        "confidence": _number(),
        "overall_audit": OVERALL_AUDIT,
        "visual_evidence_verdict": _string(),
        "confidence_reason": _string(),
        "video_audit_conclusion": VIDEO_AUDIT,
        "object_continuity_assessment": OBJECT_CONTINUITY,
        "audit_methods": _array(_string()),
        "frame_findings": _array(FRAME_FINDING),
        "adopted_evidence": _array(EVIDENCE_ITEM),
        "supporting_evidence": _array(EVIDENCE_REFERENCE),
        "challenging_evidence": _array(EVIDENCE_REFERENCE),
        "human_required": _boolean(),
        "business_follow_up_reason": _string(),
        "next_step": _string(),
        "model_limitations": _string(),
        "claim_fact_assessment": CLAIM_FACT,
        "damage_causality_assessment": DAMAGE_CAUSALITY,
        "damage_observability": DAMAGE_OBSERVABILITY,
    },
    "required": [
        "decision",
        "predicted_label",
        "system_yes_no",
        "confidence",
        "overall_audit",
        "visual_evidence_verdict",
        "confidence_reason",
        "video_audit_conclusion",
        "object_continuity_assessment",
        "audit_methods",
        "frame_findings",
        "adopted_evidence",
        "supporting_evidence",
        "challenging_evidence",
        "human_required",
        "business_follow_up_reason",
        "next_step",
        "model_limitations",
        "claim_fact_assessment",
        "damage_causality_assessment",
        "damage_observability",
    ],
}

_NATIVE_OMITTED_FIELDS = {
    "supporting_evidence",
    "challenging_evidence",
    "audit_methods",
    "visual_evidence_verdict",
    "confidence_reason",
    "model_limitations",
}

NATIVE_VIDEO_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        key: value
        for key, value in REVIEW_RESPONSE_SCHEMA["properties"].items()
        if key not in _NATIVE_OMITTED_FIELDS
    },
    "required": [
        key
        for key in REVIEW_RESPONSE_SCHEMA["required"]
        if key not in _NATIVE_OMITTED_FIELDS
    ],
}

FRAME_RESPONSE_SCHEMA = {
    **NATIVE_VIDEO_RESPONSE_SCHEMA,
    "properties": {
        **NATIVE_VIDEO_RESPONSE_SCHEMA["properties"],
        "frame_findings": _array(INDEXED_FRAME_FINDING),
    },
}

FULFILLMENT_EVIDENCE_REF = _object(
    {
        "asset_ref": _string(),
        "timestamp": _string(nullable=True),
        "field": _string(),
        "fact": _string(),
        "observed_identifier": _string(nullable=True),
    },
    required=("asset_ref", "timestamp", "field", "fact"),
)

FULFILLMENT_OBSERVED_ITEM = _object(
    {
        "item_ref": _string(),
        "sku": _string(),
        "product_name": _string(),
        "specification": _string(),
        "item_role": _string(),
        "series": _string(),
        "edition": _string(),
        "physical_form": _string(),
        "included_parts": _array(_string()),
        "visible_identifiers": _array(_string()),
        "descriptive_dimensions": _array(_string()),
        "observed_quantity": _integer(nullable=True),
        "package_ref": _string(),
        "evidence_refs": _array(FULFILLMENT_EVIDENCE_REF),
    },
    required=(
        "item_ref", "sku", "product_name", "specification",
        "item_role", "series", "edition", "physical_form",
        "included_parts", "visible_identifiers", "descriptive_dimensions",
        "observed_quantity", "package_ref", "evidence_refs",
    ),
)

FULFILLMENT_UNCONFIRMED_ITEM = _object(
    {
        "description": _string(),
        "package_ref": _string(),
        "reason": _string(),
        "evidence_refs": _array(FULFILLMENT_EVIDENCE_REF),
    },
    required=("description", "package_ref", "reason", "evidence_refs"),
)

FULFILLMENT_PACKAGE_OBSERVATION = _object(
    {
        "package_ref": _string(),
        "sealed_start": _boolean(nullable=True),
        "waybill_visible": _boolean(nullable=True),
        "observed_waybill_identifier": _string(nullable=True),
        "waybill_matches_order": _boolean(nullable=True),
        "single_take_continuity": _boolean(nullable=True),
        "opening_complete": _boolean(nullable=True),
        "all_contents_laid_out": _boolean(nullable=True),
        "received_group_photo_complete": _boolean(nullable=True),
        "green_bag_visible": _boolean(nullable=True),
        "evidence_refs": _array(FULFILLMENT_EVIDENCE_REF),
    },
    required=(
        "package_ref",
        "sealed_start",
        "waybill_visible",
        "observed_waybill_identifier",
        "waybill_matches_order",
        "single_take_continuity",
        "opening_complete",
        "all_contents_laid_out",
        "received_group_photo_complete",
        "green_bag_visible",
        "evidence_refs",
    ),
)

def _fulfillment_observation_response_schema(schema_version: str) -> Dict[str, Any]:
    return _object({
        "schema_version": _string(enum=[schema_version]),
        "confidence": _number(),
        "fulfillment_reconciliation": _object(
            {
                "observed_items": _array(FULFILLMENT_OBSERVED_ITEM),
                "unconfirmed_items": _array(FULFILLMENT_UNCONFIRMED_ITEM),
                "package_observations": _array(FULFILLMENT_PACKAGE_OBSERVATION),
                "confidence": _number(),
                "observation_reason": _string(),
            },
            required=(
                "observed_items",
                "unconfirmed_items",
                "package_observations",
                "confidence",
                "observation_reason",
            ),
        ),
    }, required=("schema_version", "confidence", "fulfillment_reconciliation"))


WRONG_ITEM_OBSERVATION_RESPONSE_SCHEMA = _fulfillment_observation_response_schema(
    "wrong_item_observation_v2"
)
MISSING_ITEM_OBSERVATION_RESPONSE_SCHEMA = _fulfillment_observation_response_schema(
    "missing_item_observation_v2"
)

_COVERAGE_ACK = _object(
    {
        "expected_image_indices": _array(_integer()),
        "observed_image_indices": _array(_integer()),
    },
    required=("expected_image_indices", "observed_image_indices"),
)

MINOR_MATERIAL_INVENTORY_RESPONSE_SCHEMA = _object(
    {
        "schema_version": _string(enum=["minor_inventory_v2"]),
        "coverage_ack": _COVERAGE_ACK,
        "material_observations": _array(_object(
            {
                "image_index": _integer(),
                "asset_ref": _string(),
                "document_type": _string(enum=[
                    "identity_card", "passport", "household_register", "birth_certificate",
                    "signed_commitment", "order_payment_proof", "mobile_realname_proof",
                    "carrier_invoice", "other", "unknown",
                ]),
                "subject_role": _string(enum=["guardian", "minor", "unknown", "not_applicable"]),
                "document_side": _string(enum=["front", "back", "page", "multiple", "unknown"]),
                "issuing_country_or_region": _string(),
                "readability": _string(enum=["clear", "partial", "unknown"]),
                "document_state": _string(enum=["filled", "blank_template", "example", "unknown"]),
                "sop_eligibility": _string(enum=["valid", "supporting_only", "invalid", "unknown"]),
                "order_payment_evidence_type": _string(enum=["order", "payment", "combined", "unknown"]),
                "application_scope_coverage": _string(enum=["complete", "partial", "unknown"]),
                "document_box_2d": _array(_integer()),
                "quality_issues": _array(_string(enum=[
                    "blur", "glare", "occlusion", "excessive_redaction", "incomplete_page",
                    "suspected_editing", "other",
                ])),
                "editing_evidence_codes": _array(_string(enum=[
                    "inconsistent_text_edge", "duplicated_region", "local_resampling_artifact",
                    "impossible_geometry", "other_specific_anomaly",
                ])),
            },
            required=(
                "image_index", "asset_ref", "document_type", "subject_role", "document_side",
                "issuing_country_or_region", "readability", "document_state", "sop_eligibility",
                "order_payment_evidence_type", "application_scope_coverage", "document_box_2d",
                "quality_issues", "editing_evidence_codes",
            ),
        )),
        "batch_limitations": _array(_string()),
    },
    required=("schema_version", "coverage_ack", "material_observations", "batch_limitations"),
)

MINOR_MATERIAL_VIDEO_RESPONSE_SCHEMA = _object(
    {
        "process_observations": _array(_object(
            {
                "video_index": _integer(),
                "global_frame_index": _integer(),
                "timestamp": _string(),
                "asset_ref": _string(),
                "process_type": _string(enum=[
                    "invoice_generation", "document_capture", "payment_record", "other", "uncertain",
                ]),
                "evidence_quality": _string(enum=["clear", "partial", "unreadable"]),
            },
            required=(
                "video_index", "global_frame_index", "timestamp", "asset_ref",
                "process_type", "evidence_quality",
            ),
        )),
        "process_summary": _string(),
        "limitations": _array(_string()),
    },
    required=("process_observations", "process_summary", "limitations"),
)

MINOR_MATERIAL_CONSISTENCY_RESPONSE_SCHEMA = _object(
    {
        "schema_version": _string(enum=["minor_consistency_v1"]),
        "coverage_ack": _COVERAGE_ACK,
        "consistency_check": _object(
            {
                "check_id": _string(),
                "relationship_evidence_type": _string(enum=[
                    "same_household_direct_link", "birth_certificate", "legal_guardianship_proof",
                    "separate_household_books_without_bridge", "uncertain", "not_applicable",
                ]),
                "minor_birth_date_iso": _string(nullable=True),
                "age_band": _string(enum=["under_10", "10_to_17", "18_or_over", "unknown"]),
                "low_age": _boolean(nullable=True),
                "under_nine": _boolean(nullable=True),
                "age_confidence": _string(enum=["high", "low", "unknown"]),
                "payment_capability_risk": _string(enum=["none", "high", "unknown"]),
                "relationship_document_groups": _array(_object(
                    {
                        "image_index": _integer(),
                        "document_type": _string(enum=[
                            "household_register", "birth_certificate",
                            "legal_guardianship_proof", "other",
                        ]),
                        "subject_role": _string(enum=["guardian", "minor", "both", "unknown"]),
                        "document_group": _string(enum=[
                            "group_1", "group_2", "group_3", "group_4", "uncertain", "not_applicable",
                        ]),
                    },
                    required=("image_index", "document_type", "subject_role", "document_group"),
                )),
                "field_results": _array(_object(
                    {
                        "field_name": _string(),
                        "status": _string(enum=["matched", "mismatched", "uncertain", "not_assessed"]),
                        "visibility": _string(enum=["complete", "partial", "masked", "unreadable"]),
                        "evidence_image_indices": _array(_integer()),
                    },
                    required=("field_name", "status", "visibility", "evidence_image_indices"),
                )),
                "tamper_risk": _string(enum=["low", "medium", "high", "uncertain"]),
                "risk_reason_codes": _array(_string(enum=[
                    "no_obvious_risk", "suspected_editing", "unreadable_fields", "incomplete_document",
                    "conflicting_fields", "evidence_gap",
                ])),
                "tamper_evidence_image_indices": _array(_integer()),
            },
            required=(
                "check_id", "relationship_evidence_type", "minor_birth_date_iso", "age_band", "low_age", "under_nine", "age_confidence",
                "payment_capability_risk", "relationship_document_groups", "field_results", "tamper_risk",
                "risk_reason_codes", "tamper_evidence_image_indices",
            ),
        ),
        "authoritative_verification": _string(enum=["disabled", "advisory", "required"]),
    },
    required=("schema_version", "coverage_ack", "consistency_check", "authoritative_verification"),
)
