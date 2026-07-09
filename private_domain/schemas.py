# -*- coding: utf-8 -*-
"""私域 Agent OpenAPI 契约模型。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class IntegrationContract(BaseModel):
    key: str
    name: str
    status: str
    method: str
    endpoint: str
    auth: str
    fields: List[str] = Field(default_factory=list)
    owner: str
    note: str


class GroupMessageIn(BaseModel):
    model_config = ConfigDict(extra="allow")

    group_id: str
    content: str
    group_name: str = ""
    owner_id: str = ""
    member_count: int = 0
    user_id: str = ""
    external_user_id: str = ""
    message_id: str = ""
    source: str = ""
    sent_at: Optional[float] = None


class ProductEventIn(BaseModel):
    model_config = ConfigDict(extra="allow")

    event_id: str = ""
    event_type: str
    item_id: str
    ip_name: str
    character_name: str = ""
    category: str = ""
    price: Optional[float] = None
    stock: int = 0
    rarity: str = ""
    mini_program_path: str = ""
    app_deep_link: str = ""
    risk_flag: str = ""


class ReviewTask(BaseModel):
    task_id: str
    user_id: str
    session_id: str
    tenant_id: str = "mitako"
    source: str = "customer_upload"
    scenario: str
    file_name: str
    stored_name: str
    mime_type: str
    size: int
    status: str
    boundary: str = ""
    result: Dict[str, Any] = Field(default_factory=dict)
    reviewed_at: float = 0
    created_at: float
    updated_at: float


class ReviewAttachment(BaseModel):
    id: str
    kind: str = "review_task"
    review_task_id: str
    name: str
    mime_type: str
    size: int
    status: str
    scenario: str
    boundary: str = ""
    review_result: Dict[str, Any] = Field(default_factory=dict)
    reviewed_at: float = 0
    url: str


class ApiResponse(BaseModel):
    ok: bool = True


class ContractsResponse(ApiResponse):
    integration_contracts: List[IntegrationContract]


class DashboardResponse(ApiResponse):
    snapshot: Dict[str, Any]
    groups: List[Dict[str, Any]]
    events: List[Dict[str, Any]]
    customer_service_tasks: List[Dict[str, Any]]
    review_tasks: List[ReviewTask]
    campaign_candidates: List[Dict[str, Any]]
    demo_ready: bool
    demo_script: List[Dict[str, str]]
    integration_contracts: List[IntegrationContract]
    interface_status: Dict[str, str]


class DemoLoadResponse(ApiResponse):
    snapshot: Dict[str, Any]
    demo_ready: bool
    summary: Dict[str, Any]
    demo_script: List[Dict[str, str]]
    integration_contracts: List[IntegrationContract]


class DemoClearResponse(ApiResponse):
    removed: Dict[str, int]
    snapshot: Dict[str, Any]
    demo_ready: bool


class GroupMessageResponse(ApiResponse):
    group: Dict[str, Any]
    risk_level: int
    risk_type: str
    need_disable_marketing: bool
    need_customer_service: bool
    need_supervisor_alert: bool
    reply: str
    tags: Dict[str, List[str]]
    customer_service_task: Optional[Dict[str, Any]] = None
    boundary: str


class ProductEventResponse(ApiResponse):
    event: Dict[str, Any]
    candidates: List[Dict[str, Any]]
    review_required: bool
    boundary: str


class ReviewTaskUploadResponse(ApiResponse):
    review_task: ReviewTask
    attachment: ReviewAttachment


class ReviewTaskDetailResponse(ApiResponse):
    review_task: ReviewTask
