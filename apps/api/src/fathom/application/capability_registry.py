from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

from fathom.adapters.storage.runtime_records import CapabilityRecord
from fathom.adapters.storage.semantic_repository import SqlSemanticRepository
from fathom.application.data_sources import DataSourceService
from fathom.application.lineage import LineageService
from fathom.application.policy_enforcement import PolicyEnforcementPoint
from fathom.domains.query.models import MqlQuery
from fathom.domains.runtime.models import (
    CapabilityCompileInput,
    CapabilityInput,
    DependencyEdgeInput,
)
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker


class RuntimeExecutor(Protocol):
    def execute(
        self,
        query: MqlQuery,
        *,
        principal: str,
        role: str,
        authorized_objects: set[str] | None,
        trace_id: str | None = None,
    ) -> dict[str, Any]: ...


class ActionDispatcher(Protocol):
    def create_case(
        self,
        *,
        capability_key: str,
        object_id: str,
        title: str,
        payload: dict[str, Any],
        idempotency_key: str,
        principal: str,
    ) -> dict[str, Any]: ...

    def send_notification(
        self,
        *,
        capability_key: str,
        object_id: str,
        title: str,
        payload: dict[str, Any],
        idempotency_key: str,
        principal: str,
    ) -> dict[str, Any]: ...


class CapabilityRegistry:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        runtime: RuntimeExecutor,
        data_sources: DataSourceService,
        lineage: LineageService,
        policy: PolicyEnforcementPoint,
        action_dispatcher: ActionDispatcher,
        repository: SqlSemanticRepository,
    ) -> None:
        self._session_factory = session_factory
        self._runtime = runtime
        self._data_sources = data_sources
        self._lineage = lineage
        self._policy = policy
        self._actions = action_dispatcher
        self._repository = repository

    def seed(self) -> None:
        definitions = [
            CapabilityInput(
                key="semantic.query",
                label="受治理语义查询",
                operation="semantic_query",
                minimum_role="viewer",
                input_schema={
                    "type": "object",
                    "required": ["query"],
                    "properties": {"query": {"type": "object"}},
                },
                description="执行已发布语义、映射、策略和质量契约。",
            ),
            CapabilityInput(
                key="semantic.source_health",
                label="数据源健康检查",
                operation="source_health",
                minimum_role="semantic_owner",
                input_schema={
                    "type": "object",
                    "required": ["source_key"],
                    "properties": {"source_key": {"type": "string"}},
                },
                description="检查受治理数据源的连通性。",
            ),
            CapabilityInput(
                key="semantic.impact",
                label="语义影响分析",
                operation="impact_analysis",
                minimum_role="semantic_owner",
                input_schema={
                    "type": "object",
                    "required": ["node"],
                    "properties": {"node": {"type": "string"}},
                },
                description="沿需求、语义、映射、能力和运行血缘计算影响范围。",
            ),
            CapabilityInput(
                key="action.create_case",
                label="创建维护 Case",
                operation="create_case",
                minimum_role="operator",
                side_effect="internal",
                approval_required=True,
                input_schema={
                    "type": "object",
                    "required": ["object_id", "title", "idempotency_key"],
                },
                description="把受验证洞察转换为需要审批且幂等的内部维护 Case。",
            ),
            CapabilityInput(
                key="action.send_notification",
                label="发送治理通知",
                operation="send_notification",
                minimum_role="operator",
                side_effect="internal",
                approval_required=True,
                input_schema={
                    "type": "object",
                    "required": ["object_id", "title", "idempotency_key"],
                    "properties": {
                        "object_id": {"type": "string"},
                        "title": {"type": "string"},
                        "idempotency_key": {"type": "string", "minLength": 8},
                        "payload": {"type": "object"},
                    },
                },
                description="发送需审批且幂等的内部治理通知，不直接控制生产系统。",
            ),
        ]
        for definition in definitions:
            existing = self.get(definition.key)
            if existing is None:
                self.save(definition, published=True)

    def save(self, payload: CapabilityInput, *, published: bool = False) -> dict[str, Any]:
        now = datetime.now(UTC)
        definition = payload.model_dump(mode="json")
        with self._session_factory() as session:
            record = session.get(CapabilityRecord, payload.key)
            if record is None:
                record = CapabilityRecord(
                    key=payload.key,
                    version=payload.version,
                    label=payload.label,
                    operation=payload.operation,
                    minimum_role=payload.minimum_role,
                    side_effect=payload.side_effect,
                    approval_required=payload.approval_required,
                    definition=definition,
                    published=published,
                    updated_at=now,
                )
                session.add(record)
            else:
                if record.published and payload.version <= record.version:
                    raise ValueError("已发布能力必须使用更高版本更新")
                record.version = payload.version
                record.label = payload.label
                record.operation = payload.operation
                record.minimum_role = payload.minimum_role
                record.side_effect = payload.side_effect
                record.approval_required = payload.approval_required
                record.definition = definition
                record.published = published
                record.updated_at = now
            session.commit()
            session.refresh(record)
            item = self._serialize(record)
        self._lineage.add(
            DependencyEdgeInput(
                from_key=f"capability:{payload.key}@{payload.version}",
                to_key=f"operation:{payload.operation}",
                relation="binds",
                source="capability_registry",
            )
        )
        metric_key = payload.binding.get("metric")
        if metric_key:
            self._lineage.add(
                DependencyEdgeInput(
                    from_key=f"semantic:{metric_key}",
                    to_key=f"capability:{payload.key}@{payload.version}",
                    relation="compiled_as",
                    source="capability_compiler",
                )
            )
        return item

    def compile_metric(self, payload: CapabilityCompileInput) -> dict[str, Any]:
        asset = next(
            (
                item
                for item in self._repository.list_assets()
                if item.key == payload.metric_key and item.kind.value == "metric"
            ),
            None,
        )
        if asset is None:
            raise LookupError(payload.metric_key)
        key = f"semantic.metric.{asset.key}"
        existing = self.get(key)
        version = int(existing["version"]) + 1 if existing else 1
        definition = CapabilityInput(
            key=key,
            label=f"查询{asset.label}",
            operation="semantic_query",
            minimum_role=payload.minimum_role,
            input_schema={
                "type": "object",
                "required": ["object_ids"],
                "properties": {
                    "object_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                    },
                    "time_range": {"type": "string", "default": "latest"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
                },
            },
            binding={"metric": asset.key},
            description=(
                f"由已发布语义指标 {asset.key} 编译；调用方不能覆盖绑定指标。"
            ),
            version=version,
        )
        return self.save(definition, published=payload.publish)

    def publish(self, key: str) -> dict[str, Any]:
        with self._session_factory() as session:
            record = session.get(CapabilityRecord, key)
            if record is None:
                raise LookupError(key)
            record.published = True
            record.updated_at = datetime.now(UTC)
            session.commit()
            session.refresh(record)
            return self._serialize(record)

    def get(self, key: str) -> dict[str, Any] | None:
        with self._session_factory() as session:
            record = session.get(CapabilityRecord, key)
            return self._serialize(record) if record else None

    def list(self, published_only: bool = True) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            statement = select(CapabilityRecord)
            if published_only:
                statement = statement.where(CapabilityRecord.published.is_(True))
            records = session.scalars(statement.order_by(CapabilityRecord.key)).all()
            return [self._serialize(record) for record in records]

    def invoke(
        self,
        key: str,
        arguments: dict[str, Any],
        *,
        principal: str,
        role: str,
        authorized_objects: set[str] | None,
        approval_token: str | None = None,
    ) -> dict[str, Any]:
        capability = self.get(key)
        if capability is None or not capability["published"]:
            raise LookupError(key)
        decision = self._policy.decide_capability(
            principal=principal,
            role=role,
            resource=f"capability:{key}@{capability['version']}",
            minimum_role=capability["minimum_role"],
            approval_required=capability["approval_required"],
            approval_token=approval_token,
            context={"side_effect": capability["side_effect"]},
        )
        if decision["effect"] != "allow":
            raise PermissionError(decision["reason"])
        operation = capability["operation"]
        if operation == "semantic_query":
            query_payload = dict(arguments.get("query", arguments))
            binding = dict(capability["definition"].get("binding", {}))
            for field, value in binding.items():
                supplied = query_payload.get(field)
                if supplied is not None and supplied != value:
                    raise ValueError(f"能力已绑定 {field}={value}，调用方不能覆盖")
                query_payload[field] = value
            query = MqlQuery.model_validate(query_payload)
            result = self._runtime.execute(
                query,
                principal=principal,
                role=role,
                authorized_objects=authorized_objects,
            )
            return self._public_runtime_result(result, decision)
        if operation == "source_health":
            source_key = str(arguments.get("source_key", ""))
            if not source_key:
                raise ValueError("source_key is required")
            return {"decision": decision, "result": self._data_sources.test(source_key)}
        if operation == "impact_analysis":
            node = str(arguments.get("node", ""))
            if not node:
                raise ValueError("node is required")
            return {"decision": decision, "result": self._lineage.impact(node)}
        if operation == "create_case":
            return {
                "decision": decision,
                "result": self._actions.create_case(
                    capability_key=key,
                    object_id=str(arguments.get("object_id", "")),
                    title=str(arguments.get("title", "")),
                    payload=dict(arguments.get("payload", {})),
                    idempotency_key=str(arguments.get("idempotency_key", "")),
                    principal=principal,
                ),
            }
        if operation == "send_notification":
            return {
                "decision": decision,
                "result": self._actions.send_notification(
                    capability_key=key,
                    object_id=str(arguments.get("object_id", "")),
                    title=str(arguments.get("title", "")),
                    payload=dict(arguments.get("payload", {})),
                    idempotency_key=str(arguments.get("idempotency_key", "")),
                    principal=principal,
                ),
            }
        raise ValueError(f"不支持的能力操作：{operation}")

    @staticmethod
    def _public_runtime_result(
        result: dict[str, Any], decision: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "decision": decision,
            "result": {
                "rows": result["rows"],
                "compiled": result["compiled"],
                "receipt": result["receipt"],
                "mapping": result["mapping"],
                "quality": result["quality"],
                "verification_status": result["verification_status"],
            },
        }

    @staticmethod
    def _serialize(record: CapabilityRecord) -> dict[str, Any]:
        return {
            "key": record.key,
            "version": record.version,
            "label": record.label,
            "operation": record.operation,
            "minimum_role": record.minimum_role,
            "side_effect": record.side_effect,
            "approval_required": record.approval_required,
            "definition": record.definition,
            "published": record.published,
            "updated_at": record.updated_at.isoformat(),
        }
