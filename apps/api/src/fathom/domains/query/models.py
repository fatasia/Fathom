from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class PlanStatus(StrEnum):
    READY = "ready"
    NEEDS_CLARIFICATION = "needs_clarification"
    REJECTED = "rejected"


class PlanAnchor(BaseModel):
    kind: str
    key: str
    label: str


class SemanticBinding(BaseModel):
    metric: str
    dimensions: list[str] = Field(default_factory=list)
    time_range: str = "latest"
    comparison: str | None = None


class AbcStage(BaseModel):
    code: str
    name: str
    status: str
    summary: str


class FathomPlan(BaseModel):
    question: str
    status: PlanStatus
    intent: str
    anchors: list[PlanAnchor]
    binding: SemanticBinding | None = None
    abc: list[AbcStage] = Field(default_factory=list)
    policy_scope: dict[str, Any] = Field(default_factory=dict)
    validations: list[str] = Field(default_factory=list)
    clarification: str | None = None


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    scope: dict[str, str] = Field(default_factory=dict)
    semantic_version: str | None = None


class Evidence(BaseModel):
    type: str
    title: str
    reference: str
    detail: str


class AskResponse(BaseModel):
    status: str
    answer: str
    plan: FathomPlan
    data: dict[str, Any]
    chart_spec: dict[str, Any]
    evidence: list[Evidence]
    quality_warnings: list[str]
    suggested_followups: list[str]
    trace_id: str
    semantic_version: str
    data_freshness: str
