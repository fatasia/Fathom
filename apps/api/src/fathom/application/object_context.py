from __future__ import annotations

from typing import Any

from fathom.adapters.storage.database import ObjectInstanceRecord, RelationEdgeRecord
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker


class ObjectContextService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def list(self, object_type: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        statement = select(ObjectInstanceRecord).order_by(ObjectInstanceRecord.label)
        if object_type:
            statement = statement.where(ObjectInstanceRecord.object_type == object_type)
        with self._session_factory() as session:
            records = session.scalars(statement.limit(min(max(limit, 1), 500))).all()
            return [self._serialize(record) for record in records]

    def get_context(self, object_id: str) -> dict[str, Any]:
        with self._session_factory() as session:
            instance = session.get(ObjectInstanceRecord, object_id)
            if instance is None:
                raise LookupError(object_id)
            edges = session.scalars(
                select(RelationEdgeRecord).where(
                    or_(
                        RelationEdgeRecord.source_id == object_id,
                        RelationEdgeRecord.target_id == object_id,
                    )
                )
            ).all()
            related_ids = {
                edge.target_id if edge.source_id == object_id else edge.source_id for edge in edges
            }
            related = {
                record.object_id: self._serialize(record)
                for record in session.scalars(
                    select(ObjectInstanceRecord).where(
                        ObjectInstanceRecord.object_id.in_(related_ids)
                    )
                ).all()
            }
            return {
                "object": self._serialize(instance),
                "relations": [
                    {
                        "relation": edge.relation_key,
                        "direction": "outgoing" if edge.source_id == object_id else "incoming",
                        "related": related.get(
                            edge.target_id if edge.source_id == object_id else edge.source_id
                        ),
                        "valid_from": edge.valid_from.isoformat(),
                    }
                    for edge in edges
                ],
            }

    @staticmethod
    def _serialize(record: ObjectInstanceRecord) -> dict[str, Any]:
        return {
            "object_id": record.object_id,
            "object_type": record.object_type,
            "label": record.label,
            "source_key": record.source_key,
            "attributes": record.attributes,
            "state": record.state,
            "updated_at": record.updated_at.isoformat(),
        }
