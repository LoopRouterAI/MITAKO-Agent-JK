# -*- coding: utf-8 -*-
"""审核服务的 OpenAPI 数据契约。"""
from __future__ import annotations

from typing import Any, Dict, List, Literal

from pydantic import BaseModel, ConfigDict, Field


ReviewScenario = Literal["product_damage", "wrong_item", "missing_item", "minor_refund"]


class ReviewCaseMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")

    client_case_id: str = Field(min_length=1, max_length=128)
    scenario: ReviewScenario
    source: str = "customer_service_system"
    priority: Literal["low", "normal", "high"] = "normal"
    idempotency_key: str = Field(default="", max_length=160)
    ticket_id: str = ""
    user_id: str = ""
    order_no: str = ""
    customer_claim: str = ""
    complaint_stage: str = ""
    customer_tone: str = ""
    order_items: List[Dict[str, Any]] = Field(default_factory=list)
    product_master_data: Dict[str, Any] = Field(default_factory=dict)
    warehouse_master_data: Dict[str, Any] = Field(default_factory=dict)
    logistics: Dict[str, Any] = Field(default_factory=dict)
    conversation_history: List[Dict[str, Any]] = Field(default_factory=list)
    sop_context: Dict[str, Any] = Field(default_factory=dict)
    asset_fields: Dict[str, List[str]] = Field(default_factory=dict)


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


class ReviewMetricsResponse(BaseModel):
    ok: bool = True
    metrics: Dict[str, Any]


class ReviewContractResponse(BaseModel):
    ok: bool = True
    contract: Dict[str, Any]


class ReviewMetadataValidationResponse(BaseModel):
    ok: bool = True
    metadata: ReviewCaseMetadata
