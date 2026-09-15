from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Any
from uuid import uuid4

from fathom.adapters.storage.database import (
    EventRecord,
    ObjectInstanceRecord,
    RelationEdgeRecord,
)
from fathom.adapters.storage.runtime_records import ExecutionReceiptRecord
from fathom.adapters.storage.semantic_repository import SqlSemanticRepository
from fathom.application.connector_executor import ConnectorExecutor
from fathom.application.data_quality import DataQualityService
from fathom.application.data_sources import DataSourceService
from fathom.application.lineage import LineageService
from fathom.application.mapping_registry import MappingRegistry
from fathom.application.mql import MqlEngine
from fathom.application.object_identities import ObjectIdentityService
from fathom.application.physical_planner import PhysicalPlanner
from fathom.application.policy_enforcement import PolicyEnforcementPoint
from fathom.domains.query.models import MqlQuery
from fathom.domains.runtime.models import DependencyEdgeInput, MappingContractInput
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker


@dataclass
class RuntimeObservation:
    observed_at: datetime
    value: float
    dimensions: dict[str, Any] = field(default_factory=dict)


class SemanticRuntimeService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        repository: SqlSemanticRepository,
        data_sources: DataSourceService,
        mapping_registry: MappingRegistry,
        policy: PolicyEnforcementPoint,
        planner: PhysicalPlanner,
        executor: ConnectorExecutor,
        quality: DataQualityService,
        lineage: LineageService,
        identities: ObjectIdentityService,
    ) -> None:
        self._session_factory = session_factory
        self._repository = repository
        self._data_sources = data_sources
        self._mappings = mapping_registry
        self._policy = policy
        self._planner = planner
        self._executor = executor
        self._quality = quality
        self._lineage = lineage
        self._identities = identities
        self._mql = MqlEngine(session_factory, repository)

    def register_mapping(self, payload: MappingContractInput) -> dict[str, Any]:
        asset = next(
            (item for item in self._repository.list_assets() if item.key == payload.metric_key),
            None,
        )
        if asset is None or asset.kind.value != "metric":
            raise ValueError(f"映射必须指向已发布指标：{payload.metric_key}")
        self._data_sources.get_record(payload.source_key)
        mapping = self._mappings.save(payload)
        self._lineage.add(
            DependencyEdgeInput(
                from_key=f"semantic:{payload.metric_key}",
                to_key=f"mapping:{mapping['mapping_id']}",
                relation="implemented_by",
                source="mapping_registry",
            )
        )
        self._lineage.add(
            DependencyEdgeInput(
                from_key=f"source:{payload.source_key}",
                to_key=f"mapping:{mapping['mapping_id']}",
                relation="provides",
                source="mapping_registry",
            )
        )
        return mapping

    def publish_mapping(self, mapping_key: str, version: int) -> dict[str, Any]:
        return self._mappings.publish(mapping_key, version)

    def has_mapping(self, metric_key: str) -> bool:
        return bool(self._mappings.published_for_metric(metric_key))

    def execute(
        self,
        query: MqlQuery,
        *,
        principal: str,
        role: str,
        authorized_objects: set[str] | None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        trace_id = trace_id or f"tr_{uuid4().hex[:16]}"
        started_at = datetime.now(UTC)
        started = perf_counter()
        asset = self._mql.validate(query, authorized_objects)
        decision = self._policy.decide_query(
            principal=principal,
            role=role,
            resource=f"semantic:{query.metric}",
            object_ids=query.object_ids,
            authorized_objects=authorized_objects,
        )
        max_rows = self._obligation(decision, "max_rows", 1_000)
        timeout_seconds = self._obligation(decision, "timeout_seconds", 8)
        if decision["effect"] != "allow":
            receipt = self._save_receipt(
                trace_id=trace_id,
                started_at=started_at,
                principal=principal,
                action="semantic.query",
                resource=f"semantic:{query.metric}",
                status="denied",
                logical_plan_hash=self._logical_hash(query),
                physical_plan={},
                mapping_id=None,
                decision_id=decision["decision_id"],
                source_key=None,
                rows=[],
                duration_ms=(perf_counter() - started) * 1000,
                quality_report={},
                error=decision["reason"],
            )
            raise PermissionError(f"{decision['reason']} · {receipt['receipt_id']}")

        mappings = self._mappings.published_for_metric(query.metric)
        if not mappings:
            receipt = self._save_receipt(
                trace_id=trace_id,
                started_at=started_at,
                principal=principal,
                action="semantic.query",
                resource=f"semantic:{query.metric}",
                status="mapping_missing",
                logical_plan_hash=self._logical_hash(query),
                physical_plan={},
                mapping_id=None,
                decision_id=decision["decision_id"],
                source_key=None,
                rows=[],
                duration_ms=(perf_counter() - started) * 1000,
                quality_report={},
                error="没有已发布的物理映射",
            )
            raise LookupError(f"指标没有已发布的物理映射：{query.metric} · {receipt['receipt_id']}")

        attempts = []
        last_error: Exception | None = None
        for mapping in mappings:
            plan: dict[str, Any] = {}
            source = self._data_sources.get_record(mapping["source_key"])
            try:
                identity_map = self._identities.resolve(
                    mapping["source_key"], query.object_ids
                )
                source_query = query.model_copy(
                    update={
                        "object_ids": [identity_map[item] for item in query.object_ids]
                    }
                )
                plan = self._planner.compile(
                    source_query,
                    mapping,
                    connector_type=source.connector_type,
                    max_rows=int(max_rows),
                    timeout_seconds=int(timeout_seconds),
                )
                plan["logical_plan_hash"] = self._logical_hash(query)
                plan["object_identity_map"] = identity_map
                result = self._executor.execute(plan)
                rows = result["rows"]
                quality_report = self._quality.evaluate(mapping["key"], rows)
                if quality_report.get("strict") and not quality_report.get("passed"):
                    raise ValueError("严格数据质量契约未通过")
                receipt = self._save_receipt(
                    trace_id=trace_id,
                    started_at=started_at,
                    principal=principal,
                    action="semantic.query",
                    resource=f"semantic:{query.metric}",
                    status="completed",
                    logical_plan_hash=plan["logical_plan_hash"],
                    physical_plan=plan,
                    mapping_id=mapping["mapping_id"],
                    decision_id=decision["decision_id"],
                    source_key=mapping["source_key"],
                    rows=rows,
                    duration_ms=(perf_counter() - started) * 1000,
                    quality_report=quality_report,
                    error=None,
                )
                self._lineage.add(
                    DependencyEdgeInput(
                        from_key=f"mapping:{mapping['mapping_id']}",
                        to_key=f"receipt:{receipt['receipt_id']}",
                        relation="executed_as",
                        source="runtime",
                    )
                )
                observations = [self._observation(row) for row in rows]
                object_record, events = self._context(query.object_ids[0])
                return {
                    "asset": asset,
                    "object": object_record,
                    "observations": observations,
                    "events": events,
                    "rows": rows,
                    "compiled": {
                        "template": f"mapping.{mapping['mapping_id']}",
                        "sql": plan["sql"],
                        "parameters": self._json_safe(plan["parameters"]),
                        "receipt_id": receipt["receipt_id"],
                    },
                    "receipt": receipt,
                    "policy_decision": decision,
                    "mapping": mapping,
                    "quality": quality_report,
                    "route_attempts": attempts,
                    "verification_status": (
                        "verified"
                        if quality_report.get("status") == "passed"
                        else "verified_unchecked"
                    ),
                }
            except Exception as error:
                last_error = error
                failed_receipt = self._save_receipt(
                    trace_id=trace_id,
                    started_at=started_at,
                    principal=principal,
                    action="semantic.query",
                    resource=f"semantic:{query.metric}",
                    status="failed",
                    logical_plan_hash=plan.get(
                        "logical_plan_hash", self._logical_hash(query)
                    ),
                    physical_plan=plan,
                    mapping_id=mapping["mapping_id"],
                    decision_id=decision["decision_id"],
                    source_key=mapping["source_key"],
                    rows=[],
                    duration_ms=(perf_counter() - started) * 1000,
                    quality_report={},
                    error=str(error),
                )
                attempts.append(
                    {
                        "mapping_id": mapping["mapping_id"],
                        "source_key": mapping["source_key"],
                        "status": "failed",
                        "receipt_id": failed_receipt["receipt_id"],
                        "error": str(error),
                    }
                )
        raise RuntimeError(
            f"所有已发布数据源执行失败：{last_error or 'unknown error'}"
        ) from last_error

    def list_receipts(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            records = session.scalars(
                select(ExecutionReceiptRecord)
                .order_by(ExecutionReceiptRecord.created_at.desc())
                .limit(min(max(limit, 1), 1000))
            ).all()
            return [self._serialize_receipt(record) for record in records]

    def _save_receipt(
        self,
        *,
        trace_id: str,
        started_at: datetime,
        principal: str,
        action: str,
        resource: str,
        status: str,
        logical_plan_hash: str,
        physical_plan: dict[str, Any],
        mapping_id: str | None,
        decision_id: str,
        source_key: str | None,
        rows: list[dict[str, Any]],
        duration_ms: float,
        quality_report: dict[str, Any],
        error: str | None,
    ) -> dict[str, Any]:
        completed_at = datetime.now(UTC)
        result_hash = (
            hashlib.sha256(
                json.dumps(self._json_safe(rows), ensure_ascii=False, sort_keys=True).encode()
            ).hexdigest()
            if rows
            else None
        )
        freshness = self._freshness(rows)
        record = ExecutionReceiptRecord(
            receipt_id=f"rcpt_{uuid4().hex[:20]}",
            trace_id=trace_id,
            created_at=started_at,
            completed_at=completed_at,
            principal=principal,
            action=action,
            resource=resource,
            status=status,
            logical_plan_hash=logical_plan_hash,
            physical_plan=self._json_safe(physical_plan),
            mapping_id=mapping_id,
            policy_decision_id=decision_id,
            source_key=source_key,
            row_count=len(rows),
            duration_ms=round(duration_ms, 3),
            result_hash=result_hash,
            data_freshness=freshness,
            quality_report=quality_report,
            error=(error[:2000] if error else None),
        )
        with self._session_factory() as session:
            session.add(record)
            session.commit()
            session.refresh(record)
            return self._serialize_receipt(record)

    def _context(
        self, object_id: str
    ) -> tuple[ObjectInstanceRecord | None, list[EventRecord]]:
        with self._session_factory() as session:
            object_record = session.get(ObjectInstanceRecord, object_id)
            if object_record is not None:
                session.expunge(object_record)
            related_ids = list(
                session.scalars(
                    select(RelationEdgeRecord.target_id).where(
                        RelationEdgeRecord.source_id == object_id
                    )
                ).all()
            )
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
            for event in events:
                session.expunge(event)
        return object_record, events

    @staticmethod
    def _obligation(decision: dict[str, Any], kind: str, default: Any) -> Any:
        return next(
            (
                item.get("value", default)
                for item in decision["obligations"]
                if item.get("kind") == kind
            ),
            default,
        )

    @staticmethod
    def _observation(row: dict[str, Any]) -> RuntimeObservation:
        raw = row.get("period")
        if isinstance(raw, datetime):
            observed_at = raw
        else:
            observed_at = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=UTC)
        return RuntimeObservation(observed_at=observed_at, value=float(row["value"]))

    @staticmethod
    def _logical_hash(query: MqlQuery) -> str:
        return hashlib.sha256(
            json.dumps(query.model_dump(mode="json"), sort_keys=True).encode()
        ).hexdigest()

    @staticmethod
    def _freshness(rows: list[dict[str, Any]]) -> datetime | None:
        values = []
        for row in rows:
            raw = row.get("period")
            if not raw:
                continue
            parsed = (
                raw
                if isinstance(raw, datetime)
                else datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            )
            values.append(parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC))
        return max(values) if values else None

    @classmethod
    def _json_safe(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): cls._json_safe(child) for key, child in value.items()}
        if isinstance(value, list):
            return [cls._json_safe(child) for child in value]
        if isinstance(value, datetime):
            return value.isoformat()
        return value

    @staticmethod
    def _serialize_receipt(record: ExecutionReceiptRecord) -> dict[str, Any]:
        return {
            "receipt_id": record.receipt_id,
            "trace_id": record.trace_id,
            "created_at": record.created_at.isoformat(),
            "completed_at": record.completed_at.isoformat(),
            "principal": record.principal,
            "action": record.action,
            "resource": record.resource,
            "status": record.status,
            "logical_plan_hash": record.logical_plan_hash,
            "physical_plan": record.physical_plan,
            "mapping_id": record.mapping_id,
            "policy_decision_id": record.policy_decision_id,
            "source_key": record.source_key,
            "row_count": record.row_count,
            "duration_ms": record.duration_ms,
            "result_hash": record.result_hash,
            "data_freshness": (
                record.data_freshness.isoformat() if record.data_freshness else None
            ),
            "quality_report": record.quality_report,
            "error": record.error,
        }
