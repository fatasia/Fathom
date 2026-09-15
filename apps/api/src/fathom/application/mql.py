from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fathom.adapters.storage.database import (
    EventRecord,
    MetricObservationRecord,
    ObjectInstanceRecord,
    RelationEdgeRecord,
)
from fathom.adapters.storage.semantic_repository import SqlSemanticRepository
from fathom.domains.query.models import MqlQuery
from fathom.domains.semantics.models import AssetKind, SemanticAsset
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker


class MqlValidationError(ValueError):
    pass


class MqlEngine:
    """Validate and execute a closed MQL grammar using fixed ORM templates."""

    _filter_fields = {"shift", "production_line", "equipment", "day"}
    _operators = {"eq", "in"}

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        repository: SqlSemanticRepository,
    ) -> None:
        self._session_factory = session_factory
        self._repository = repository

    def validate(
        self,
        query: MqlQuery,
        authorized_objects: set[str] | None = None,
    ) -> SemanticAsset:
        asset = next(
            (
                item
                for item in self._repository.list_assets()
                if item.key == query.metric and item.kind == AssetKind.METRIC
            ),
            None,
        )
        if asset is None:
            raise MqlValidationError(f"指标未发布：{query.metric}")
        unknown_dimensions = set(query.dimensions) - set(asset.dimensions)
        if unknown_dimensions:
            raise MqlValidationError(
                f"指标 {query.metric} 不支持维度：{', '.join(sorted(unknown_dimensions))}"
            )
        if authorized_objects is not None:
            denied = set(query.object_ids) - authorized_objects
            if denied:
                raise PermissionError(f"无权访问业务对象：{', '.join(sorted(denied))}")
        for item in query.filters:
            if item.field not in self._filter_fields or item.field not in asset.dimensions:
                raise MqlValidationError(f"过滤字段未被指标口径允许：{item.field}")
            if item.operator not in self._operators:
                raise MqlValidationError(f"过滤操作符不受支持：{item.operator}")
        with self._session_factory() as session:
            existing = set(
                session.scalars(
                    select(ObjectInstanceRecord.object_id).where(
                        ObjectInstanceRecord.object_id.in_(query.object_ids),
                        ObjectInstanceRecord.state == "active",
                    )
                ).all()
            )
        missing = set(query.object_ids) - existing
        if missing:
            raise MqlValidationError(f"业务对象不存在或未激活：{', '.join(sorted(missing))}")
        return asset

    def compile(self, query: MqlQuery) -> dict[str, Any]:
        """Expose a receipt for the fixed template; no model-authored SQL is accepted."""
        clauses = ["metric_key = :metric", "object_id IN :object_ids"]
        params: dict[str, Any] = {
            "metric": query.metric,
            "object_ids": query.object_ids,
            "limit": query.limit,
        }
        range_start, range_end = self._range_bounds(query.time_range)
        if range_start is not None:
            clauses.append("observed_at >= :range_start")
            params["range_start"] = range_start.isoformat()
        if range_end is not None:
            clauses.append("observed_at < :range_end")
            params["range_end"] = range_end.isoformat()
        for index, item in enumerate(query.filters):
            clauses.append(f"dimensions.{item.field} {item.operator} :filter_{index}")
            params[f"filter_{index}"] = item.value
        return {
            "template": "metric_observations.by_metric_object_time",
            "sql": (
                "SELECT observed_at, value, dimensions FROM metric_observations WHERE "
                + " AND ".join(clauses)
                + " ORDER BY observed_at DESC LIMIT :limit"
            ),
            "parameters": params,
        }

    def execute(
        self,
        query: MqlQuery,
        authorized_objects: set[str] | None = None,
    ) -> dict[str, Any]:
        asset = self.validate(query, authorized_objects)
        object_id = query.object_ids[0]
        with self._session_factory() as session:
            object_record = session.get(ObjectInstanceRecord, object_id)
            related_ids = list(
                session.scalars(
                    select(RelationEdgeRecord.target_id).where(
                        RelationEdgeRecord.source_id == object_id
                    )
                ).all()
            )
            statement = select(MetricObservationRecord).where(
                MetricObservationRecord.metric_key == query.metric,
                MetricObservationRecord.object_id == object_id,
            )
            range_start, range_end = self._range_bounds(query.time_range)
            if range_start is not None:
                statement = statement.where(
                    MetricObservationRecord.observed_at >= range_start
                )
            if range_end is not None:
                statement = statement.where(MetricObservationRecord.observed_at < range_end)
            current_rows = list(
                session.scalars(
                    statement.order_by(MetricObservationRecord.observed_at.desc()).limit(
                        query.limit if range_start is None else 1
                    )
                ).all()
            )
            if query.filters:
                current_rows = [
                    row
                    for row in current_rows
                    if all(self._matches(row.dimensions, item) for item in query.filters)
                ]
            observations = current_rows
            if range_start is not None and current_rows:
                previous = session.scalar(
                    select(MetricObservationRecord)
                    .where(
                        MetricObservationRecord.metric_key == query.metric,
                        MetricObservationRecord.object_id == object_id,
                        MetricObservationRecord.observed_at < range_start,
                    )
                    .order_by(MetricObservationRecord.observed_at.desc())
                    .limit(1)
                )
                if previous is not None and all(
                    self._matches(previous.dimensions, item) for item in query.filters
                ):
                    observations.append(previous)
            events = list(
                session.scalars(
                    select(EventRecord)
                    .where(
                        EventRecord.object_id.in_([object_id, *related_ids]),
                        EventRecord.occurred_at >= datetime.now(UTC) - timedelta(days=4),
                    )
                    .order_by(EventRecord.duration_minutes.desc())
                ).all()
            )
        return {
            "asset": asset,
            "object": object_record,
            "observations": observations,
            "events": events,
            "compiled": self.compile(query),
            "verification_status": "verified",
        }

    @staticmethod
    def _matches(dimensions: dict[str, Any], item: Any) -> bool:
        actual = dimensions.get(item.field)
        if item.operator == "in":
            expected = item.value if isinstance(item.value, list) else [item.value]
            return actual in expected
        return actual == item.value

    @staticmethod
    def _range_bounds(time_range: str) -> tuple[datetime | None, datetime | None]:
        now = datetime.now(UTC)
        if time_range == "latest":
            return None, None
        if time_range == "today":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            return start, start + timedelta(days=1)
        if time_range == "yesterday":
            end = now.replace(hour=0, minute=0, second=0, microsecond=0)
            return end - timedelta(days=1), end
        try:
            start = datetime.fromisoformat(time_range).replace(tzinfo=UTC)
        except ValueError:
            raise MqlValidationError(f"时间范围不可解析：{time_range}") from None
        return start, start + timedelta(days=1)
