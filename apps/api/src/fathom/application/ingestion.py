from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fathom.adapters.storage.database import (
    EventRecord,
    MetricObservationRecord,
    ObjectInstanceRecord,
    RelationEdgeRecord,
    SemanticAssetRecord,
)
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker


class ObjectInstanceInput(BaseModel):
    object_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]+$", max_length=160)
    object_type: str = Field(min_length=1, max_length=160)
    label: str = Field(min_length=1, max_length=160)
    source_key: str = Field(min_length=1, max_length=160)
    attributes: dict[str, Any] = Field(default_factory=dict)
    state: str = Field(default="active", max_length=32)


class RelationInput(BaseModel):
    relation_key: str = Field(min_length=1, max_length=160)
    source_id: str = Field(min_length=1, max_length=160)
    target_id: str = Field(min_length=1, max_length=160)
    valid_from: datetime = Field(default_factory=lambda: datetime.now(UTC))


class MetricObservationInput(BaseModel):
    metric_key: str = Field(min_length=1, max_length=160)
    object_id: str = Field(min_length=1, max_length=160)
    observed_at: datetime
    value: float
    dimensions: dict[str, str | int | float | bool] = Field(default_factory=dict)


class IndustrialEventInput(BaseModel):
    event_type: str = Field(min_length=1, max_length=160)
    object_id: str = Field(min_length=1, max_length=160)
    occurred_at: datetime
    duration_minutes: float = Field(default=0, ge=0)
    payload: dict[str, Any] = Field(default_factory=dict)


class IngestionService:
    """Validated writes into the lightweight object/metric/event serving layer."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def upsert_objects(self, items: list[ObjectInstanceInput]) -> dict[str, Any]:
        self._bounded(items)
        now = datetime.now(UTC)
        with self._session_factory() as session:
            created = 0
            updated = 0
            for item in items:
                record = session.get(ObjectInstanceRecord, item.object_id)
                values = item.model_dump()
                values["updated_at"] = now
                if record is None:
                    session.add(ObjectInstanceRecord(**values))
                    created += 1
                else:
                    for key, value in values.items():
                        setattr(record, key, value)
                    updated += 1
            session.commit()
        return {"accepted": len(items), "created": created, "updated": updated}

    def add_relations(self, items: list[RelationInput]) -> dict[str, Any]:
        self._bounded(items)
        with self._session_factory() as session:
            object_ids = {
                object_id for item in items for object_id in (item.source_id, item.target_id)
            }
            existing_objects = set(
                session.scalars(
                    select(ObjectInstanceRecord.object_id).where(
                        ObjectInstanceRecord.object_id.in_(object_ids)
                    )
                ).all()
            )
            missing = sorted(object_ids - existing_objects)
            if missing:
                raise ValueError(f"关系引用了不存在的对象：{', '.join(missing[:10])}")
            created = 0
            skipped = 0
            for item in items:
                existing = session.scalar(
                    select(RelationEdgeRecord.id).where(
                        RelationEdgeRecord.relation_key == item.relation_key,
                        RelationEdgeRecord.source_id == item.source_id,
                        RelationEdgeRecord.target_id == item.target_id,
                    )
                )
                if existing:
                    skipped += 1
                    continue
                session.add(RelationEdgeRecord(**item.model_dump()))
                created += 1
            session.commit()
        return {"accepted": len(items), "created": created, "skipped": skipped}

    def upsert_observations(self, items: list[MetricObservationInput]) -> dict[str, Any]:
        self._bounded(items)
        with self._session_factory() as session:
            self._validate_metric_objects(session, items)
            created = 0
            updated = 0
            for item in items:
                existing = session.scalar(
                    select(MetricObservationRecord).where(
                        MetricObservationRecord.metric_key == item.metric_key,
                        MetricObservationRecord.object_id == item.object_id,
                        MetricObservationRecord.observed_at == item.observed_at,
                    )
                )
                values = item.model_dump()
                if existing is None:
                    session.add(MetricObservationRecord(**values))
                    created += 1
                else:
                    existing.value = item.value
                    existing.dimensions = item.dimensions
                    updated += 1
            session.commit()
        return {"accepted": len(items), "created": created, "updated": updated}

    def add_events(self, items: list[IndustrialEventInput]) -> dict[str, Any]:
        self._bounded(items)
        with self._session_factory() as session:
            object_ids = {item.object_id for item in items}
            existing_objects = set(
                session.scalars(
                    select(ObjectInstanceRecord.object_id).where(
                        ObjectInstanceRecord.object_id.in_(object_ids)
                    )
                ).all()
            )
            missing = sorted(object_ids - existing_objects)
            if missing:
                raise ValueError(f"事件引用了不存在的对象：{', '.join(missing[:10])}")
            session.add_all(EventRecord(**item.model_dump()) for item in items)
            session.commit()
        return {"accepted": len(items), "created": len(items)}

    @staticmethod
    def _validate_metric_objects(session: Session, items: list[MetricObservationInput]) -> None:
        metric_keys = {item.metric_key for item in items}
        object_ids = {item.object_id for item in items}
        metrics = set(
            session.scalars(
                select(SemanticAssetRecord.key).where(
                    SemanticAssetRecord.key.in_(metric_keys),
                    SemanticAssetRecord.kind == "metric",
                )
            ).all()
        )
        objects = set(
            session.scalars(
                select(ObjectInstanceRecord.object_id).where(
                    ObjectInstanceRecord.object_id.in_(object_ids)
                )
            ).all()
        )
        missing_metrics = sorted(metric_keys - metrics)
        missing_objects = sorted(object_ids - objects)
        if missing_metrics:
            raise ValueError(f"指标未在已发布语义中定义：{', '.join(missing_metrics[:10])}")
        if missing_objects:
            raise ValueError(f"观测值引用了不存在的对象：{', '.join(missing_objects[:10])}")

    @staticmethod
    def _bounded(items: list[Any]) -> None:
        if not items:
            raise ValueError("批次不能为空")
        if len(items) > 10_000:
            raise ValueError("单批最多 10000 条，请分批提交")
