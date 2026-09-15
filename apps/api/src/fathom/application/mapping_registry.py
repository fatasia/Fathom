from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from fathom.adapters.storage.runtime_records import MappingContractRecord
from fathom.application.data_sources import DataSourceService
from fathom.domains.runtime.models import MappingContractInput, MappingStatus
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker


class MappingRegistry:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        data_sources: DataSourceService,
    ) -> None:
        self._session_factory = session_factory
        self._data_sources = data_sources

    def save(self, payload: MappingContractInput) -> dict[str, Any]:
        definition = payload.model_dump(mode="json")
        mapping_id = self._mapping_id(payload.key, payload.version)
        checksum = self._checksum(definition)
        now = datetime.now(UTC)
        with self._session_factory() as session:
            record = session.get(MappingContractRecord, mapping_id)
            if record is None:
                record = MappingContractRecord(
                    mapping_id=mapping_id,
                    mapping_key=payload.key,
                    metric_key=payload.metric_key,
                    source_key=payload.source_key,
                    version=payload.version,
                    status=MappingStatus.DRAFT.value,
                    owner=payload.owner,
                    checksum=checksum,
                    definition=definition,
                    compatibility={},
                    created_at=now,
                    updated_at=now,
                )
                session.add(record)
            else:
                if record.status != MappingStatus.DRAFT.value:
                    raise ValueError("已发布或退役的映射版本不可覆盖，请创建新版本")
                record.metric_key = payload.metric_key
                record.source_key = payload.source_key
                record.owner = payload.owner
                record.checksum = checksum
                record.definition = definition
                record.compatibility = {}
                record.updated_at = now
            session.commit()
            session.refresh(record)
            return self._serialize(record)

    def list(self, metric_key: str | None = None) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            statement = select(MappingContractRecord)
            if metric_key:
                statement = statement.where(MappingContractRecord.metric_key == metric_key)
            records = session.scalars(
                statement.order_by(
                    MappingContractRecord.mapping_key, MappingContractRecord.version.desc()
                )
            ).all()
            return [self._serialize(record) for record in records]

    def get(self, mapping_key: str, version: int | None = None) -> dict[str, Any]:
        with self._session_factory() as session:
            if version is None:
                statement = (
                    select(MappingContractRecord)
                    .where(MappingContractRecord.mapping_key == mapping_key)
                    .order_by(MappingContractRecord.version.desc())
                    .limit(1)
                )
                record = session.scalar(statement)
            else:
                record = session.get(
                    MappingContractRecord, self._mapping_id(mapping_key, version)
                )
            if record is None:
                raise LookupError(mapping_key)
            return self._serialize(record)

    def published_for_metric(self, metric_key: str) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            records = session.scalars(
                select(MappingContractRecord).where(
                    MappingContractRecord.metric_key == metric_key,
                    MappingContractRecord.status == MappingStatus.PUBLISHED.value,
                )
            ).all()
            items = [self._serialize(record) for record in records]
        source_status = {item["key"]: item for item in self._data_sources.list()}
        status_rank = {"online": 3, "untested": 2, "driver_required": 1, "offline": 0}
        return sorted(
            items,
            key=lambda item: (
                status_rank.get(source_status.get(item["source_key"], {}).get("status"), 1),
                int(item["definition"].get("priority", 100)),
                item["version"],
            ),
            reverse=True,
        )

    def check_compatibility(self, mapping_key: str, version: int) -> dict[str, Any]:
        mapping = self.get(mapping_key, version)
        definition = mapping["definition"]
        discovered = self._data_sources.discover(mapping["source_key"])
        table = next(
            (
                item
                for item in discovered.get("tables", [])
                if item.get("name") == definition["table_name"]
            ),
            None,
        )
        required = {
            definition["object_column"],
            definition["value_column"],
            definition["time_column"],
            *definition.get("dimension_columns", {}).values(),
            *definition.get("static_filters", {}).keys(),
        }
        available = {column["name"] for column in table.get("columns", [])} if table else set()
        missing = sorted(required - available)
        result = {
            "compatible": table is not None and not missing,
            "source_key": mapping["source_key"],
            "table": definition["table_name"],
            "required_columns": sorted(required),
            "available_columns": sorted(available),
            "missing_columns": missing,
            "checked_at": datetime.now(UTC).isoformat(),
        }
        with self._session_factory() as session:
            record = session.get(MappingContractRecord, mapping["mapping_id"])
            if record:
                record.compatibility = result
                record.updated_at = datetime.now(UTC)
                session.commit()
        return result

    def publish(self, mapping_key: str, version: int) -> dict[str, Any]:
        compatibility = self.check_compatibility(mapping_key, version)
        if not compatibility["compatible"]:
            raise ValueError(
                "映射与当前 Schema 不兼容："
                + ", ".join(compatibility["missing_columns"] or ["table missing"])
            )
        mapping_id = self._mapping_id(mapping_key, version)
        with self._session_factory() as session:
            record = session.get(MappingContractRecord, mapping_id)
            if record is None:
                raise LookupError(mapping_key)
            published = session.scalars(
                select(MappingContractRecord).where(
                    MappingContractRecord.mapping_key == mapping_key,
                    MappingContractRecord.status == MappingStatus.PUBLISHED.value,
                )
            ).all()
            for current in published:
                current.status = MappingStatus.RETIRED.value
                current.updated_at = datetime.now(UTC)
            record.status = MappingStatus.PUBLISHED.value
            record.compatibility = compatibility
            record.updated_at = datetime.now(UTC)
            session.commit()
            session.refresh(record)
            return self._serialize(record)

    def rollback(self, mapping_key: str, version: int) -> dict[str, Any]:
        return self.publish(mapping_key, version)

    @staticmethod
    def _mapping_id(mapping_key: str, version: int) -> str:
        return f"{mapping_key}@{version}"

    @staticmethod
    def _checksum(definition: dict[str, Any]) -> str:
        payload = json.dumps(definition, ensure_ascii=False, sort_keys=True).encode()
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _serialize(record: MappingContractRecord) -> dict[str, Any]:
        return {
            "mapping_id": record.mapping_id,
            "key": record.mapping_key,
            "metric_key": record.metric_key,
            "source_key": record.source_key,
            "version": record.version,
            "status": record.status,
            "owner": record.owner,
            "checksum": record.checksum,
            "definition": record.definition,
            "compatibility": record.compatibility,
            "created_at": record.created_at.isoformat(),
            "updated_at": record.updated_at.isoformat(),
        }

