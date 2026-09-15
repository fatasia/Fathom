from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from fathom.domains.query.models import MqlQuery
from pydantic import BaseModel, Field, field_validator, model_validator

IDENTIFIER_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]*$"
KEY_PATTERN = r"^[a-z][a-z0-9_.-]+$"


class MappingStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    RETIRED = "retired"


class MappingContractInput(BaseModel):
    key: str = Field(pattern=KEY_PATTERN)
    metric_key: str = Field(pattern=KEY_PATTERN)
    source_key: str = Field(pattern=KEY_PATTERN)
    version: int = Field(default=1, ge=1)
    owner: str = Field(min_length=2, max_length=160)
    schema_name: str | None = Field(default=None, pattern=IDENTIFIER_PATTERN)
    table_name: str = Field(pattern=IDENTIFIER_PATTERN)
    object_column: str = Field(pattern=IDENTIFIER_PATTERN)
    value_column: str = Field(pattern=IDENTIFIER_PATTERN)
    time_column: str = Field(pattern=IDENTIFIER_PATTERN)
    dimension_columns: dict[str, str] = Field(default_factory=dict)
    static_filters: dict[str, str | int | float | bool] = Field(default_factory=dict)
    aggregation: Literal["none", "sum", "avg", "min", "max", "count"] = "none"
    priority: int = Field(default=100, ge=0, le=10_000)
    freshness_seconds: int | None = Field(default=None, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("dimension_columns")
    @classmethod
    def validate_dimension_columns(cls, value: dict[str, str]) -> dict[str, str]:
        import re

        pattern = re.compile(IDENTIFIER_PATTERN)
        for semantic_name, physical_name in value.items():
            if not pattern.fullmatch(semantic_name) or not pattern.fullmatch(physical_name):
                raise ValueError("维度名和物理列必须是安全标识符")
        return value

    @field_validator("static_filters")
    @classmethod
    def validate_static_filters(
        cls, value: dict[str, str | int | float | bool]
    ) -> dict[str, str | int | float | bool]:
        import re

        pattern = re.compile(IDENTIFIER_PATTERN)
        if any(not pattern.fullmatch(column) for column in value):
            raise ValueError("静态过滤列必须是安全标识符")
        return value


class RuntimeQueryInput(BaseModel):
    query: MqlQuery


class RequirementCitation(BaseModel):
    source_uri: str = Field(min_length=1, max_length=1000)
    excerpt: str = Field(min_length=1, max_length=500)
    line: int = Field(ge=1)


class RequirementConflict(BaseModel):
    kind: Literal["potential_numeric_conflict", "overlapping_requirement"]
    existing_requirement_key: str = Field(pattern=KEY_PATTERN)
    linked_assets: list[str] = Field(default_factory=list)
    detail: str = Field(min_length=2, max_length=500)


class RequirementEvidenceInput(BaseModel):
    key: str = Field(pattern=KEY_PATTERN)
    title: str = Field(min_length=2, max_length=300)
    source_uri: str = Field(min_length=1, max_length=1000)
    statements: list[str] = Field(min_length=1)
    acceptance_questions: list[str] = Field(default_factory=list)
    linked_assets: list[str] = Field(default_factory=list)
    citations: list[RequirementCitation] = Field(default_factory=list)
    clarification_questions: list[str] = Field(default_factory=list)
    conflicts: list[RequirementConflict] = Field(default_factory=list)
    review_status: Literal["candidate", "in_review", "approved", "rejected"] = "candidate"
    owner: str = Field(min_length=2, max_length=160)


class RequirementExploreInput(BaseModel):
    text: str = Field(min_length=5, max_length=50_000)
    source_uri: str = Field(default="inline://requirement", max_length=1000)
    owner: str = Field(default="business-owner", min_length=2, max_length=160)


class RequirementReviewInput(BaseModel):
    decision: Literal["in_review", "approved", "rejected"]
    reviewer: str = Field(min_length=2, max_length=160)
    comment: str = Field(default="", max_length=1000)


class DependencyEdgeInput(BaseModel):
    from_key: str = Field(min_length=1, max_length=320)
    to_key: str = Field(min_length=1, max_length=320)
    relation: str = Field(min_length=2, max_length=64)
    source: str = Field(default="manual", max_length=160)


class ObjectIdentityInput(BaseModel):
    canonical_object_id: str = Field(min_length=1, max_length=160)
    source_key: str = Field(pattern=KEY_PATTERN)
    external_object_id: str = Field(min_length=1, max_length=320)
    owner: str = Field(default="data-owner", min_length=2, max_length=160)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DataQualityCheck(BaseModel):
    kind: Literal["not_null", "min", "max", "min_rows", "freshness"]
    field: str = Field(default="value", pattern=IDENTIFIER_PATTERN)
    value: float | int | None = None

    @model_validator(mode="after")
    def validate_threshold(self) -> DataQualityCheck:
        if self.kind != "not_null" and self.value is None:
            raise ValueError(f"{self.kind} 检查必须提供 value 阈值")
        return self


class DataQualityContractInput(BaseModel):
    key: str = Field(pattern=KEY_PATTERN)
    mapping_key: str = Field(pattern=KEY_PATTERN)
    checks: list[DataQualityCheck] = Field(min_length=1)
    strict: bool = True
    owner: str = Field(min_length=2, max_length=160)


class GoldenCaseInput(BaseModel):
    key: str = Field(pattern=KEY_PATTERN)
    question: str = Field(min_length=2, max_length=1000)
    query: MqlQuery
    expected_value: float
    tolerance: float = Field(default=0.001, ge=0)


class CapabilityInput(BaseModel):
    key: str = Field(pattern=KEY_PATTERN)
    label: str = Field(min_length=2, max_length=160)
    operation: Literal[
        "semantic_query",
        "source_health",
        "impact_analysis",
        "create_case",
        "send_notification",
    ]
    minimum_role: Literal["viewer", "operator", "semantic_owner", "admin"] = "viewer"
    side_effect: Literal["none", "internal", "external"] = "none"
    approval_required: bool = False
    input_schema: dict[str, Any] = Field(default_factory=dict)
    binding: dict[str, Any] = Field(default_factory=dict)
    description: str = Field(default="", max_length=1000)
    version: int = Field(default=1, ge=1)


class CapabilityInvocationInput(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)
    approval_token: str | None = Field(default=None, max_length=200)


class CapabilityCompileInput(BaseModel):
    metric_key: str = Field(pattern=KEY_PATTERN)
    owner: str = Field(default="semantic-owner", min_length=2, max_length=160)
    minimum_role: Literal["viewer", "operator", "semantic_owner", "admin"] = "viewer"
    publish: bool = False


class ReverseMappingInput(BaseModel):
    source_key: str = Field(pattern=KEY_PATTERN)
    table_name: str = Field(pattern=IDENTIFIER_PATTERN)
    owner: str = Field(default="data-owner", min_length=2, max_length=160)


class LegacyAssetExtractInput(BaseModel):
    kind: Literal["sql", "openapi"]
    content: str | dict[str, Any]
    source_key: str | None = Field(default=None, pattern=KEY_PATTERN)
    owner: str = Field(default="integration-owner", min_length=2, max_length=160)


class InsightActionInput(BaseModel):
    capability_key: str = Field(pattern=KEY_PATTERN)
    object_id: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=2, max_length=300)
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=8, max_length=160)
    approval_token: str | None = Field(default=None, max_length=200)
