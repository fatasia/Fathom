from __future__ import annotations

import hashlib
from collections import deque
from datetime import UTC, datetime
from typing import Any

from fathom.adapters.storage.runtime_records import DependencyEdgeRecord
from fathom.domains.runtime.models import DependencyEdgeInput
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker


class LineageService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def add(self, payload: DependencyEdgeInput) -> dict[str, Any]:
        raw = f"{payload.from_key}\0{payload.to_key}\0{payload.relation}"
        edge_id = f"dep_{hashlib.sha256(raw.encode()).hexdigest()[:20]}"
        with self._session_factory() as session:
            record = session.get(DependencyEdgeRecord, edge_id)
            if record is None:
                record = DependencyEdgeRecord(
                    edge_id=edge_id,
                    from_key=payload.from_key,
                    to_key=payload.to_key,
                    relation=payload.relation,
                    source=payload.source,
                    created_at=datetime.now(UTC),
                )
                session.add(record)
                try:
                    session.commit()
                except IntegrityError:
                    session.rollback()
                    record = session.scalar(
                        select(DependencyEdgeRecord).where(
                            DependencyEdgeRecord.from_key == payload.from_key,
                            DependencyEdgeRecord.to_key == payload.to_key,
                            DependencyEdgeRecord.relation == payload.relation,
                        )
                    )
            if record is None:
                raise RuntimeError("依赖边保存失败")
            return self._serialize(record)

    def list(self, node: str | None = None) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            statement = select(DependencyEdgeRecord)
            if node:
                statement = statement.where(
                    or_(
                        DependencyEdgeRecord.from_key == node,
                        DependencyEdgeRecord.to_key == node,
                    )
                )
            records = session.scalars(
                statement.order_by(DependencyEdgeRecord.created_at)
            ).all()
            return [self._serialize(record) for record in records]

    def impact(self, node: str, max_depth: int = 8) -> dict[str, Any]:
        with self._session_factory() as session:
            records = session.scalars(select(DependencyEdgeRecord)).all()
        adjacency: dict[str, list[DependencyEdgeRecord]] = {}
        for record in records:
            adjacency.setdefault(record.from_key, []).append(record)
        visited = {node}
        queue: deque[tuple[str, int]] = deque([(node, 0)])
        impacted: list[dict[str, Any]] = []
        while queue:
            current, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for edge in adjacency.get(current, []):
                impacted.append({**self._serialize(edge), "depth": depth + 1})
                if edge.to_key not in visited:
                    visited.add(edge.to_key)
                    queue.append((edge.to_key, depth + 1))
        return {"root": node, "nodes": sorted(visited), "edges": impacted}

    @staticmethod
    def _serialize(record: DependencyEdgeRecord) -> dict[str, Any]:
        return {
            "edge_id": record.edge_id,
            "from_key": record.from_key,
            "to_key": record.to_key,
            "relation": record.relation,
            "source": record.source,
            "created_at": record.created_at.isoformat(),
        }

