# -*- coding: utf-8 -*-
"""审核服务的 OpenAPI 数据契约。"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .decision_policy import DEFAULT_PRODUCT_DAMAGE_POLICY_REF


ReviewScenario = Literal["product_damage", "wrong_item", "missing_item", "minor_refund"]
ReviewStrength = Literal["adaptive", "strong", "strict", "forensic", "custom"]
ForensicCheck = Literal[
    "container_integrity",
    "timeline_consistency",
    "stream_consistency",
    "frame_rate_consistency",
    "packet_timeline",
    "editor_metadata",
]


def _validate_optional_iso_timestamp(value: str) -> str:
    if not value:
        return value
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamp_must_be_iso8601_with_timezone") from exc
    if parsed.tzinfo is None:
        raise ValueError("timestamp_must_be_iso8601_with_timezone")
    return value


class ReviewSamplingPolicy(BaseModel):
    preset: ReviewStrength = "adaptive"
    fps: float = Field(default=1.0, ge=0.1, le=2.0)
    max_frames_per_video: Optional[int] = Field(default=None, ge=1, le=1800)
    frames_per_model_call: int = Field(default=24, ge=1, le=24)
    auto_escalate: Optional[bool] = False
    confidence_threshold: Optional[float] = Field(default=0.75, ge=0.0, le=1.0)
    forensic_checks: Optional[Union[bool, List[ForensicCheck]]] = None


class ReviewContinuityPolicy(BaseModel):
    out_of_frame_warning_seconds: float = Field(default=3.0, ge=0.5, le=30.0)
    require_identity_reestablishment: bool = True
    force_dense_scan: bool = False
    scan_fps: Optional[float] = Field(default=None, ge=0.2, le=2.0)


class ReviewDamageCausalityPolicy(BaseModel):
    force_action_scan: bool = False
    dedicated_chunk_frames: int = Field(default=20, ge=8, le=24)
    context_frames: int = Field(default=6, ge=2, le=8)


class ReviewOutputOptions(BaseModel):
    include_html_report: bool = True


class ReviewRoutingPolicy(BaseModel):
    required_below_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    optional_below_confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    out_of_frame_resubmit_seconds: float = Field(default=3.0, ge=0.5, le=30.0)

    @model_validator(mode="after")
    def validate_threshold_order(self) -> "ReviewRoutingPolicy":
        if self.required_below_confidence > self.optional_below_confidence:
            raise ValueError("required_below_confidence must be <= optional_below_confidence")
        return self


class ReviewMinorRefundPolicy(BaseModel):
    """未成年人资料视觉初审策略；权威验真未接入时默认不阻断。"""

    review_mode: Literal["standard", "strict"] = "standard"
    authoritative_verification: Literal["disabled", "advisory", "required"] = "disabled"


class ReviewAtomicClaim(BaseModel):
    claim_id: str = Field(min_length=1, max_length=160)
    role: Literal["primary", "additional"] = "primary"
    subject_ref: str = Field(default="", max_length=160)
    issue_type: str = Field(default="unspecified", max_length=160)
    location: str = Field(default="unspecified", max_length=240)
    first_asserted_at: str = Field(default="", max_length=80)
    turn_id: str = Field(default="", max_length=160)
    evidence_asset_ids: List[str] = Field(default_factory=list, max_length=80)
    required_views: List[str] = Field(default_factory=list, max_length=40)


class ReviewClaimScope(BaseModel):
    """本次审核实际覆盖的诉求，避免把后续追加问题混入当前结论。"""

    claim_id: str = Field(default="", max_length=160)
    scope_version: str = Field(default="1", max_length=40)
    split_status: Literal["resolved", "single_legacy", "ambiguous", "unresolved"] = "unresolved"
    stage: Literal["initial", "supplemental", "appeal", "combined"] = "initial"
    claim_text: str = Field(default="", max_length=4000)
    issue_types: List[str] = Field(default_factory=list, max_length=40)
    item_refs: List[str] = Field(default_factory=list, max_length=40)
    evidence_asset_names: List[str] = Field(default_factory=list, max_length=80)
    excluded_issue_types: List[str] = Field(default_factory=list, max_length=40)
    active_claim_ids: List[str] = Field(default_factory=list, max_length=40)
    claims: List[ReviewAtomicClaim] = Field(default_factory=list, max_length=40)


class ReviewDecisionPolicy(BaseModel):
    """甲方可选的规则判定策略；默认不把证据不足自动判为不支持。"""

    mode: Literal["conservative_review", "classification_recommendation"] = "classification_recommendation"
    policy_ref: str = Field(default=DEFAULT_PRODUCT_DAMAGE_POLICY_REF, max_length=160)
    opening_video_required: bool = False
    missing_required_opening_video: Literal["review", "negative"] = "review"
    complete_video_no_claimed_damage: Literal["review", "negative"] = "review"
    require_claim_scope: bool = True
    minimum_visibility_coverage: float = Field(default=0.85, ge=0.5, le=1.0)
    minimum_required_view_coverage: float = Field(default=1.0, ge=0.5, le=1.0)
    minimum_confidence: float = Field(default=0.8, ge=0.5, le=1.0)
    require_continuity_complete: bool = True
    require_fully_observable: bool = True
    require_claimed_region_closeup: bool = True
    require_same_item_linkage: bool = True
    require_media_forensics: bool = True
    maximum_forensic_risk: Literal["none", "low", "medium"] = "low"
    max_unobserved_seconds: float = Field(default=0.0, ge=0.0, le=30.0)


class ReviewSamplingPlanRequest(BaseModel):
    duration_seconds: float = Field(gt=0, le=86400)
    source_bytes: int = Field(ge=0)
    video_count: int = Field(default=1, ge=1, le=40)
    scenario: Optional[ReviewScenario] = None
    sampling_policy: ReviewSamplingPolicy = Field(default_factory=ReviewSamplingPolicy)
    continuity_policy: ReviewContinuityPolicy = Field(default_factory=ReviewContinuityPolicy)
    damage_causality_policy: ReviewDamageCausalityPolicy = Field(default_factory=ReviewDamageCausalityPolicy)


class ReviewSamplingPlanResponse(BaseModel):
    ok: bool = True
    plan: Dict[str, Any]


class ReviewExpectedItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    item_ref: str = Field(min_length=1, max_length=160)
    sku: str = ""
    product_name: str = ""
    specification: str = ""
    expected_quantity: int = Field(ge=1, le=10000)
    item_type: Literal["paid_item", "bundle_component", "gift", "bonus", "insert", "other"] = "paid_item"
    master_image_urls: List[str] = Field(default_factory=list)
    packaging_identifiers: List[str] = Field(default_factory=list)


class ReviewExpectedPackage(BaseModel):
    model_config = ConfigDict(extra="allow")

    package_ref: str = Field(min_length=1, max_length=160)
    tracking_no: str = ""
    expected_item_refs: List[str] = Field(default_factory=list)
    shipment_status: str = ""


class ReviewFulfillmentBaseline(BaseModel):
    model_config = ConfigDict(extra="allow")

    baseline_version: str = Field(min_length=1, max_length=160)
    expected_items: List[ReviewExpectedItem] = Field(default_factory=list)
    expected_package_count: int = Field(default=1, ge=1, le=100)
    packages: List[ReviewExpectedPackage] = Field(default_factory=list)
    split_shipment: bool = False
    benefit_rules: List[Dict[str, Any]] = Field(default_factory=list)
    benefit_rules_complete: bool = False
    selection_rules: List[Dict[str, Any]] = Field(default_factory=list)
    selection_rules_complete: bool = False
    standard_packing_list: List[Dict[str, Any]] = Field(default_factory=list)


class ReviewEvidenceCoverage(BaseModel):
    model_config = ConfigDict(extra="allow")

    submitted_package_refs: List[str] = Field(default_factory=list)
    submitted_tracking_nos: List[str] = Field(default_factory=list)
    all_packages_uploaded: bool = False
    all_items_displayed: bool = False
    coverage_notes: str = ""


class ReviewLogisticsEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str = Field(min_length=1, max_length=80)
    occurred_at: str = Field(default="", max_length=80)
    location: str = Field(default="", max_length=240)

    @field_validator("occurred_at")
    @classmethod
    def validate_occurred_at(cls, value: str) -> str:
        return _validate_optional_iso_timestamp(value)


class ReviewLogisticsPackage(BaseModel):
    model_config = ConfigDict(extra="allow")

    package_ref: str = Field(min_length=1, max_length=160)
    tracking_ref: str = Field(default="", max_length=240)
    carrier: str = Field(default="", max_length=160)
    shipment_status: str = Field(default="", max_length=80)
    events: List[ReviewLogisticsEvent] = Field(default_factory=list, max_length=200)


class ReviewLogisticsContext(BaseModel):
    model_config = ConfigDict(extra="allow")

    source: str = Field(default="customer_logistics_system", max_length=160)
    snapshot_at: str = Field(default="", max_length=80)
    packages: List[ReviewLogisticsPackage] = Field(default_factory=list, max_length=100)
    all_packages_delivered: Optional[bool] = None

    @field_validator("snapshot_at")
    @classmethod
    def validate_snapshot_at(cls, value: str) -> str:
        return _validate_optional_iso_timestamp(value)


class ReviewCustomerRiskContext(BaseModel):
    """甲方系统生成的脱敏统计摘要；不接收历史对话或用户隐私原文。"""

    source: str = Field(default="customer_risk_service", max_length=160, pattern=r"^[A-Za-z0-9_.:-]+$")
    snapshot_at: str = Field(default="", max_length=80)
    lookback_days: int = Field(default=180, ge=1, le=3650)
    prior_after_sales_count: int = Field(default=0, ge=0, le=100000)
    prior_upheld_count: int = Field(default=0, ge=0, le=100000)
    prior_rejected_count: int = Field(default=0, ge=0, le=100000)
    same_scenario_count: int = Field(default=0, ge=0, le=100000)
    risk_level: Literal["unknown", "low", "medium", "high"] = "unknown"
    reason_codes: List[str] = Field(default_factory=list, max_length=40)

    @field_validator("snapshot_at")
    @classmethod
    def validate_snapshot_at(cls, value: str) -> str:
        return _validate_optional_iso_timestamp(value)

    @field_validator("reason_codes")
    @classmethod
    def validate_reason_codes(cls, values: List[str]) -> List[str]:
        for value in values:
            if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", value) or re.search(r"\d{7,}", value):
                raise ValueError("customer_risk_reason_code_invalid")
        return values


class ReviewCaseMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    client_case_id: str = Field(min_length=1, max_length=128)
    scenario: ReviewScenario
    source: str = "customer_service_system"
    batch_id: str = Field(default="", max_length=160)
    priority: Literal["low", "normal", "high"] = "normal"
    idempotency_key: str = Field(default="", max_length=160)
    ticket_id: str = ""
    user_id: str = ""
    order_no: str = ""
    customer_claim: str = ""
    complaint_stage: str = ""
    customer_tone: str = ""
    order_items: List[Dict[str, Any]] = Field(default_factory=list)
    fulfillment_baseline: Optional[ReviewFulfillmentBaseline] = None
    evidence_coverage: ReviewEvidenceCoverage = Field(default_factory=ReviewEvidenceCoverage)
    product_master_data: Dict[str, Any] = Field(default_factory=dict)
    warehouse_master_data: Dict[str, Any] = Field(default_factory=dict)
    logistics: ReviewLogisticsContext = Field(default_factory=ReviewLogisticsContext)
    conversation_history: List[Dict[str, Any]] = Field(default_factory=list)
    customer_risk_context: ReviewCustomerRiskContext = Field(default_factory=ReviewCustomerRiskContext)
    sop_context: Dict[str, Any] = Field(default_factory=dict)
    asset_fields: Dict[str, List[str]] = Field(default_factory=dict)
    source_record: Dict[str, Any] = Field(default_factory=dict)
    claim_scope: ReviewClaimScope = Field(default_factory=ReviewClaimScope)
    decision_policy: ReviewDecisionPolicy = Field(default_factory=ReviewDecisionPolicy)
    sampling_policy: ReviewSamplingPolicy = Field(default_factory=ReviewSamplingPolicy)
    continuity_policy: ReviewContinuityPolicy = Field(default_factory=ReviewContinuityPolicy)
    damage_causality_policy: ReviewDamageCausalityPolicy = Field(default_factory=ReviewDamageCausalityPolicy)
    output_options: ReviewOutputOptions = Field(default_factory=ReviewOutputOptions)
    review_routing_policy: ReviewRoutingPolicy = Field(default_factory=ReviewRoutingPolicy)
    minor_refund_policy: ReviewMinorRefundPolicy = Field(default_factory=ReviewMinorRefundPolicy)

    @field_validator("conversation_history", mode="before")
    @classmethod
    def validate_conversation_history(cls, value: Any) -> Any:
        if value in (None, ""):
            return []
        if not isinstance(value, list) or len(value) > 100:
            raise ValueError("conversation_history_invalid")
        user_roles = {"user", "customer"}
        service_roles = {"customer_service", "service_agent", "agent", "admin"}
        service_types = {"question", "request_more_material", "status_update"}
        final_keys = {"decision", "resolution", "refund_result", "final_outcome", "human_conclusion", "approved"}
        final_markers = ("人工最终", "最终决定", "同意退款", "已退款", "拒绝退款", "审核通过", "审核不通过")
        for item in value:
            if not isinstance(item, dict):
                raise ValueError("conversation_message_invalid")
            role = str(item.get("role") or item.get("from") or item.get("sender_role") or "").strip().lower()
            message_type = str(item.get("message_type") or item.get("type") or "").strip().lower()
            if role not in user_roles and (role not in service_roles or message_type not in service_types):
                raise ValueError("conversation_role_or_type_not_allowed")
            if any(str(key).strip().lower() in final_keys for key in item):
                raise ValueError("conversation_final_outcome_not_allowed")
            text = str(item.get("text") or item.get("content") or "")
            if len(text) > 4000 or any(marker in text for marker in final_markers):
                raise ValueError("conversation_final_outcome_not_allowed")
        return value


class ReviewAsset(BaseModel):
    asset_id: str
    original_name: str
    stored_name: str
    mime_type: str
    size: int
    sha256: str
    fields: List[str] = Field(default_factory=list)


class ReviewAssessmentDetails(BaseModel):
    conclusion_code: Literal[
        "evidence_supports_claim",
        "evidence_does_not_support_claim",
        "evidence_inconclusive",
        "technical_processing_incomplete",
    ]
    conclusion: str
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    confidence_level: Literal["high", "medium", "low", "unavailable"]
    calibration_status: Literal[
        "uncalibrated_evidence_score",
        "not_applicable_processing_incomplete",
    ]


class ReviewHumanReviewAdvice(BaseModel):
    level: Literal["required", "optional", "not_required"]
    reason_codes: List[str] = Field(default_factory=list)
    recommendation: str


class ReviewAdvisorySignal(BaseModel):
    model_config = ConfigDict(extra="allow")

    code: str
    severity: Literal["info", "warning", "critical"]
    effect: str


class ReviewAdvisoryPolicy(BaseModel):
    model_config = ConfigDict(extra="allow")

    policy_ref: str
    effective_thresholds: Dict[str, float] = Field(default_factory=dict)
    advisory_only: Literal[True] = True
    business_action_allowed: Literal[False] = False
    boundary: str


class ReviewAdvisoryAssessment(BaseModel):
    scenario: str
    assessment: ReviewAssessmentDetails
    human_review: ReviewHumanReviewAdvice
    workflow_recommendation: Literal[
        "human_review",
        "request_more_material",
        "continue_by_customer_policy",
        "system_retry",
    ]
    signals: List[ReviewAdvisorySignal] = Field(default_factory=list)
    policy: ReviewAdvisoryPolicy


class ReviewReportReference(BaseModel):
    requested: bool
    status: Literal["ready", "not_requested", "unavailable"]
    html_url: Optional[str] = None


class ReviewPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    advisory_assessment: Optional[ReviewAdvisoryAssessment] = None
    report: Optional[ReviewReportReference] = None


class ReviewJobResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    review: Optional[ReviewPayload] = None


class ReviewJob(BaseModel):
    job_id: str
    tenant_id: str
    client_case_id: str
    idempotency_key: str = ""
    scenario: ReviewScenario
    status: str
    metadata: Dict[str, Any]
    assets: List[ReviewAsset]
    result: ReviewJobResult = Field(default_factory=ReviewJobResult)
    diagnostics: Dict[str, Any] = Field(default_factory=dict)
    attempts: int = 0
    created_at: float
    started_at: float = 0
    completed_at: float = 0
    updated_at: float


class ReviewJobResponse(BaseModel):
    ok: bool = True
    created: bool = False
    job: ReviewJob


class ReviewErrorResponse(BaseModel):
    detail: Any


class ReviewJobListResponse(BaseModel):
    ok: bool = True
    jobs: List[ReviewJob]


class ReviewBatchResponse(BaseModel):
    ok: bool = True
    batch_id: str
    summary: Dict[str, Any]
    jobs: List[ReviewJob]


class ReviewMetricsResponse(BaseModel):
    ok: bool = True
    metrics: Dict[str, Any]


class ReviewContractResponse(BaseModel):
    ok: bool = True
    contract: Dict[str, Any]


class ReviewMetadataValidationResponse(BaseModel):
    ok: bool = True
    metadata: ReviewCaseMetadata
    readiness: Dict[str, Any]
