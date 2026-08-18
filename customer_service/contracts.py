# -*- coding: utf-8 -*-
"""客服对话的强类型事实、动作和公开状态契约。"""
from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ActionStatus(StrEnum):
    NOT_REQUESTED = "not_requested"
    REQUESTED = "requested"
    ACCEPTED = "accepted"
    QUEUED = "queued"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PENDING_HUMAN = "pending_human"


class FactSource(StrEnum):
    USER_STATEMENT = "user_statement"
    ATTACHMENT_SERVICE = "attachment_service"
    ORDER_SERVICE = "order_service"
    PRODUCT_SERVICE = "product_service"
    ACTIVITY_SERVICE = "activity_service"
    WAREHOUSE_SERVICE = "warehouse_service"
    HANDOFF_SERVICE = "handoff_service"
    REVIEW_SERVICE = "review_service"
    HUMAN_UPDATE = "human_update"


class Fact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    value: Any
    source: FactSource
    source_ref: str = ""
    verified: bool = False
    observed_at: str = ""

    @model_validator(mode="after")
    def user_statement_is_never_verified(self) -> "Fact":
        if self.source == FactSource.USER_STATEMENT:
            self.verified = False
        elif self.verified and not self.source_ref.strip():
            raise ValueError("verified_system_fact_requires_source_ref")
        return self


class ActionState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str
    status: ActionStatus
    receipt_id: str = ""
    tool_name: str = ""
    reason_code: str = ""
    occurred_at: str = ""

    @model_validator(mode="after")
    def completed_action_requires_receipt(self) -> "ActionState":
        if self.status in {ActionStatus.QUEUED, ActionStatus.SUCCEEDED}:
            if not all(
                value.strip()
                for value in (self.receipt_id, self.tool_name, self.occurred_at)
            ):
                raise ValueError("completed_action_requires_receipt")
        return self


class IntentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent_code: str
    scenario_code: str
    intent_codes: list[str] = Field(default_factory=list)
    scenario_codes: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    matched_evidence: list[str] = Field(default_factory=list)
    requires_clarification: bool = False
    clarification_fields: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def primary_codes_are_in_atomic_lists(self) -> "IntentResult":
        self.intent_codes = list(dict.fromkeys([self.intent_code, *self.intent_codes]))
        self.scenario_codes = list(dict.fromkeys([self.scenario_code, *self.scenario_codes]))
        return self


class NextStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    label: str
    user_action_required: bool = False


class ReplyPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    facts: list[Fact] = Field(default_factory=list)
    must_say: list[str] = Field(default_factory=list)
    must_not_say: list[str] = Field(default_factory=list)
    action: ActionState
    next_step: NextStep
    allowed_time_commitment: str | None = None


class ConversationState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: IntentResult
    facts: list[Fact] = Field(default_factory=list)
    material_state: dict[str, Any] = Field(default_factory=dict)
    action_state: ActionState
    next_step: NextStep
    core_conclusion: str
