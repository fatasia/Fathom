from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fathom.adapters.storage.runtime_records import ActionRunRecord
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker


class ActionService:
    """Small governed action boundary; deliberately not a generic workflow engine."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create_case(
        self,
        *,
        capability_key: str,
        object_id: str,
        title: str,
        payload: dict[str, Any],
        idempotency_key: str,
        principal: str,
    ) -> dict[str, Any]:
        return self._create(
            capability_key=capability_key,
            object_id=object_id,
            title=title,
            payload=payload,
            idempotency_key=idempotency_key,
            principal=principal,
            result={
                "case_id": f"case_{uuid4().hex[:12]}",
                "state": "open",
                "message": "维护 Case 已创建，等待责任人处理。",
            },
        )

    def send_notification(
        self,
        *,
        capability_key: str,
        object_id: str,
        title: str,
        payload: dict[str, Any],
        idempotency_key: str,
        principal: str,
    ) -> dict[str, Any]:
        channel = str(payload.get("channel", "internal"))
        if channel not in {"internal", "email", "webhook"}:
            raise ValueError("通知 channel 仅支持 internal、email、webhook")
        return self._create(
            capability_key=capability_key,
            object_id=object_id,
            title=title,
            payload=payload,
            idempotency_key=idempotency_key,
            principal=principal,
            result={
                "notification_id": f"notice_{uuid4().hex[:12]}",
                "state": "queued",
                "channel": channel,
                "message": "治理通知已进入受控发送队列。",
            },
        )

    def _create(
        self,
        *,
        capability_key: str,
        object_id: str,
        title: str,
        payload: dict[str, Any],
        idempotency_key: str,
        principal: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        if not object_id or len(title) < 2 or len(idempotency_key) < 8:
            raise ValueError("object_id、title 和至少 8 位 idempotency_key 必填")
        with self._session_factory() as session:
            existing = session.scalar(
                select(ActionRunRecord).where(
                    ActionRunRecord.idempotency_key == idempotency_key
                )
            )
            if existing:
                return {**self._serialize(existing), "idempotent_replay": True}
            run_id = f"act_{uuid4().hex[:20]}"
            record = ActionRunRecord(
                run_id=run_id,
                capability_key=capability_key,
                idempotency_key=idempotency_key,
                object_id=object_id,
                title=title,
                status="completed",
                principal=principal,
                payload=payload,
                result=result,
                created_at=datetime.now(UTC),
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return {**self._serialize(record), "idempotent_replay": False}

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            records = session.scalars(
                select(ActionRunRecord)
                .order_by(ActionRunRecord.created_at.desc())
                .limit(min(max(limit, 1), 1000))
            ).all()
            return [self._serialize(record) for record in records]

    @staticmethod
    def _serialize(record: ActionRunRecord) -> dict[str, Any]:
        return {
            "run_id": record.run_id,
            "capability_key": record.capability_key,
            "idempotency_key": record.idempotency_key,
            "object_id": record.object_id,
            "title": record.title,
            "status": record.status,
            "principal": record.principal,
            "payload": record.payload,
            "result": record.result,
            "created_at": record.created_at.isoformat(),
        }
