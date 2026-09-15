from __future__ import annotations

from datetime import datetime

from fathom.adapters.storage.database import Base
from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column


class MappingContractRecord(Base):
    __tablename__ = "mapping_contracts"

    mapping_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    mapping_key: Mapped[str] = mapped_column(String(160), index=True)
    metric_key: Mapped[str] = mapped_column(String(160), index=True)
    source_key: Mapped[str] = mapped_column(String(160), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), index=True)
    owner: Mapped[str] = mapped_column(String(160))
    checksum: Mapped[str] = mapped_column(String(64), index=True)
    definition: Mapped[dict] = mapped_column(JSON)
    compatibility: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    __table_args__ = (UniqueConstraint("mapping_key", "version"),)


class PolicyDecisionRecord(Base):
    __tablename__ = "policy_decisions"

    decision_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    principal: Mapped[str] = mapped_column(String(160), index=True)
    role: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(160), index=True)
    resource: Mapped[str] = mapped_column(String(320), index=True)
    effect: Mapped[str] = mapped_column(String(16), index=True)
    reason: Mapped[str] = mapped_column(String(1000))
    obligations: Mapped[list] = mapped_column(JSON, default=list)
    context: Mapped[dict] = mapped_column(JSON, default=dict)


class ExecutionReceiptRecord(Base):
    __tablename__ = "execution_receipts"

    receipt_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    principal: Mapped[str] = mapped_column(String(160), index=True)
    action: Mapped[str] = mapped_column(String(160), index=True)
    resource: Mapped[str] = mapped_column(String(320), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    logical_plan_hash: Mapped[str] = mapped_column(String(64), index=True)
    physical_plan: Mapped[dict] = mapped_column(JSON, default=dict)
    mapping_id: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    policy_decision_id: Mapped[str] = mapped_column(String(64), index=True)
    source_key: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[float] = mapped_column(Float, default=0)
    result_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    data_freshness: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    quality_report: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(String(2000), nullable=True)


class RequirementEvidenceRecord(Base):
    __tablename__ = "requirement_evidence"

    evidence_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    evidence_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(300), index=True)
    source_uri: Mapped[str] = mapped_column(String(1000))
    owner: Mapped[str] = mapped_column(String(160), index=True)
    definition: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class DependencyEdgeRecord(Base):
    __tablename__ = "dependency_edges"

    edge_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    from_key: Mapped[str] = mapped_column(String(320), index=True)
    to_key: Mapped[str] = mapped_column(String(320), index=True)
    relation: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(160), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    __table_args__ = (UniqueConstraint("from_key", "to_key", "relation"),)


class ObjectIdentityRecord(Base):
    __tablename__ = "object_identities"

    identity_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    canonical_object_id: Mapped[str] = mapped_column(String(160), index=True)
    source_key: Mapped[str] = mapped_column(String(160), index=True)
    external_object_id: Mapped[str] = mapped_column(String(320), index=True)
    owner: Mapped[str] = mapped_column(String(160), index=True)
    definition: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    __table_args__ = (
        UniqueConstraint("canonical_object_id", "source_key"),
        UniqueConstraint("source_key", "external_object_id"),
    )


class DataQualityContractRecord(Base):
    __tablename__ = "data_quality_contracts"

    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    mapping_key: Mapped[str] = mapped_column(String(160), index=True)
    owner: Mapped[str] = mapped_column(String(160), index=True)
    checks: Mapped[list] = mapped_column(JSON)
    strict: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(32), default="published", index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class RuntimeGoldenCaseRecord(Base):
    __tablename__ = "runtime_golden_cases"

    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    question: Mapped[str] = mapped_column(String(1000))
    query: Mapped[dict] = mapped_column(JSON)
    expected_value: Mapped[float] = mapped_column(Float)
    tolerance: Mapped[float] = mapped_column(Float, default=0.001)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class CapabilityRecord(Base):
    __tablename__ = "runtime_capabilities"

    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    label: Mapped[str] = mapped_column(String(160), index=True)
    operation: Mapped[str] = mapped_column(String(64), index=True)
    minimum_role: Mapped[str] = mapped_column(String(64))
    side_effect: Mapped[str] = mapped_column(String(32))
    approval_required: Mapped[bool] = mapped_column(Boolean, default=False)
    definition: Mapped[dict] = mapped_column(JSON)
    published: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ActionRunRecord(Base):
    __tablename__ = "action_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    capability_key: Mapped[str] = mapped_column(String(160), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    object_id: Mapped[str] = mapped_column(String(160), index=True)
    title: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(32), index=True)
    principal: Mapped[str] = mapped_column(String(160), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
