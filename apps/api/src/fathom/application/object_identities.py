from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from fathom.adapters.storage.runtime_records import ObjectIdentityRecord
from fathom.application.data_sources import DataSourceService
from fathom.application.lineage import LineageService
from fathom.domains.runtime.models import DependencyEdgeInput, ObjectIdentityInput
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker


class ObjectIdentityService:
    """Small canonical-ID registry for querying the same object across source systems."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        data_sources: DataSourceService,
        lineage: LineageService,
    ) -> None:
        self._session_factory = session_factory
        self._data_sources = data_sources
        self._lineage = lineage

    def save(self, payload: ObjectIdentityInput) -> dict[str, Any]:
        self._data_sources.get_record(payload.source_key)
        identity_id = self._identity_id(payload.canonical_object_id, payload.source_key)
        now = datetime.now(UTC)
        with self._session_factory() as session:
            record = session.get(ObjectIdentityRecord, identity_id)
            claimed = session.scalar(
                select(ObjectIdentityRecord).where(
                    ObjectIdentityRecord.source_key == payload.source_key,
                    ObjectIdentityRecord.external_object_id == payload.external_object_id,
                    ObjectIdentityRecord.identity_id != identity_id,
                )
            )
            if claimed is not None:
                raise ValueError(
                    "同一来源标识已经绑定到其他规范对象："
                    f"{claimed.canonical_object_id}"
                )
            if record is None:
                record = ObjectIdentityRecord(
                    identity_id=identity_id,
                    canonical_object_id=payload.canonical_object_id,
                    source_key=payload.source_key,
                    external_object_id=payload.external_object_id,
                    owner=payload.owner,
                    definition=payload.model_dump(mode="json"),
                    updated_at=now,
                )
                session.add(record)
            else:
                record.external_object_id = payload.external_object_id
                record.owner = payload.owner
                record.definition = payload.model_dump(mode="json")
                record.updated_at = now
            session.commit()
            session.refresh(record)
            result = self._serialize(record)
        self._lineage.add(
            DependencyEdgeInput(
                from_key=f"object:{payload.canonical_object_id}",
                to_key=f"source-object:{payload.source_key}:{payload.external_object_id}",
                relation="identified_as",
                source="object_identity_registry",
            )
        )
        return result

    def list(
        self, canonical_object_id: str | None = None, source_key: str | None = None
    ) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            statement = select(ObjectIdentityRecord)
            if canonical_object_id:
                statement = statement.where(
                    ObjectIdentityRecord.canonical_object_id == canonical_object_id
                )
            if source_key:
                statement = statement.where(ObjectIdentityRecord.source_key == source_key)
            records = session.scalars(
                statement.order_by(
                    ObjectIdentityRecord.canonical_object_id,
                    ObjectIdentityRecord.source_key,
                )
            ).all()
            return [self._serialize(record) for record in records]

    def resolve(self, source_key: str, canonical_ids: list[str]) -> dict[str, str]:
        if not canonical_ids:
            return {}
        with self._session_factory() as session:
            records = session.scalars(
                select(ObjectIdentityRecord).where(
                    ObjectIdentityRecord.source_key == source_key,
                    ObjectIdentityRecord.canonical_object_id.in_(canonical_ids),
                )
            ).all()
        configured = {
            record.canonical_object_id: record.external_object_id for record in records
        }
        return {
            canonical_id: configured.get(canonical_id, canonical_id)
            for canonical_id in canonical_ids
        }

    @staticmethod
    def _identity_id(canonical_object_id: str, source_key: str) -> str:
        digest = hashlib.sha256(
            f"{canonical_object_id}\0{source_key}".encode()
        ).hexdigest()[:24]
        return f"identity_{digest}"

    @staticmethod
    def _serialize(record: ObjectIdentityRecord) -> dict[str, Any]:
        return {
            "identity_id": record.identity_id,
            "canonical_object_id": record.canonical_object_id,
            "source_key": record.source_key,
            "external_object_id": record.external_object_id,
            "owner": record.owner,
            "metadata": record.definition.get("metadata", {}),
            "updated_at": record.updated_at.isoformat(),
        }
