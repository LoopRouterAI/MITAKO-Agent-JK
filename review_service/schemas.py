# -*- coding: utf-8 -*-
"""审核服务的 OpenAPI 数据契约。"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


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


class ReviewSamplingPolicy(BaseModel):
    preset: ReviewStrength = "adaptive"
    fps: float = Field(default=1.0, ge=0.1, le=2.0)
    max_frames_per_video: Optional[int] = Field(default=None, ge=1, le=1800)
    frames_per_model_call: int = Field(default=24, ge=1, le=24)
    auto_escalate: Optional[bool] = False
    confidence_threshold: Optional[float] = Field(default=0.75, ge=0.0, le=1.0)
    forensic_checks: Optional[Union[bool, List[ForensicCheck]]] = None


class ReviewContinuityPolicy(BaseModel):
    out_of_frame_warning_seconds: float = Field(default=2.0, ge=0.5, le=30.0)
    require_identity_reestablishment: bool = True
    force_dense_scan: bool = False
    scan_fps: Optional[float] = Field(default=None, ge=0.2, le=2.0)


class ReviewDamageCausalityPolicy(BaseModel):
    force_action_scan: bool = False
    dedicated_chunk_frames: int = Field(default=20, ge=8, le=24)
    context_frames: int = Field(default=6, ge=2, le=8)


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
    logistics: Dict[str, Any] = Field(default_factory=dict)
    conversation_history: List[Dict[str, Any]] = Field(default_factory=list)
    sop_context: Dict[str, Any] = Field(default_factory=dict)
    asset_fields: Dict[str, List[str]] = Field(default_factory=dict)
    source_record: Dict[str, Any] = Field(default_factory=dict)
    sampling_policy: ReviewSamplingPolicy = Field(default_factory=ReviewSamplingPolicy)
    continuity_policy: ReviewContinuityPolicy = Field(default_factory=ReviewContinuityPolicy)
    damage_causality_policy: ReviewDamageCausalityPolicy = Field(default_factory=ReviewDamageCausalityPolicy)


class ReviewAsset(BaseModel):
    asset_id: str
    original_name: str
    stored_name: str
    mime_type: str
    size: int
    sha256: str
    fields: List[str] = Field(default_factory=list)


class ReviewJob(BaseModel):
    job_id: str
    tenant_id: str
    client_case_id: str
    idempotency_key: str = ""
    scenario: ReviewScenario
    status: str
    metadata: Dict[str, Any]
    assets: List[ReviewAsset]
    result: Dict[str, Any] = Field(default_factory=dict)
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
