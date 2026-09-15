from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fathom.adapters.storage.database import ConversationRecord, ConversationTurnRecord
from fathom.application.feedback import FeedbackService
from fathom.domains.query.models import AskRequest, AskResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker


class ConversationCreate(BaseModel):
    title: str = Field(default="新对话", min_length=1, max_length=200)


class ConversationRename(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ConversationService:
    """Persist user-visible chat sessions without storing attachment bodies."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        feedback_service: FeedbackService | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._feedback_service = feedback_service

    def create(self, title: str = "新对话") -> dict:
        now = datetime.now(UTC)
        record = ConversationRecord(
            conversation_id=f"chat_{uuid4().hex[:20]}",
            title=self._clean_title(title),
            created_at=now,
            updated_at=now,
        )
        with self._session_factory() as session:
            session.add(record)
            session.commit()
        return self._serialize(record, turn_count=0, last_question="")

    def list(self, limit: int = 100) -> list[dict]:
        count_query = (
            select(
                ConversationTurnRecord.conversation_id,
                func.count(ConversationTurnRecord.turn_id).label("turn_count"),
            )
            .group_by(ConversationTurnRecord.conversation_id)
            .subquery()
        )
        last_turn_query = (
            select(
                ConversationTurnRecord.conversation_id,
                func.max(ConversationTurnRecord.created_at).label("last_created_at"),
            )
            .group_by(ConversationTurnRecord.conversation_id)
            .subquery()
        )
        with self._session_factory() as session:
            rows = session.execute(
                select(ConversationRecord, count_query.c.turn_count)
                .outerjoin(
                    count_query,
                    count_query.c.conversation_id == ConversationRecord.conversation_id,
                )
                .order_by(ConversationRecord.updated_at.desc())
                .limit(min(max(limit, 1), 200))
            ).all()
            latest_times = {
                conversation_id: created_at
                for conversation_id, created_at in session.execute(
                    select(
                        last_turn_query.c.conversation_id,
                        last_turn_query.c.last_created_at,
                    )
                ).all()
            }
            latest_questions = {}
            for conversation_id, created_at in latest_times.items():
                latest_questions[conversation_id] = session.scalar(
                    select(ConversationTurnRecord.question).where(
                        ConversationTurnRecord.conversation_id == conversation_id,
                        ConversationTurnRecord.created_at == created_at,
                    )
                ) or ""
        return [
            self._serialize(
                record,
                turn_count=int(turn_count or 0),
                last_question=latest_questions.get(record.conversation_id, ""),
            )
            for record, turn_count in rows
        ]

    def get(self, conversation_id: str) -> dict:
        with self._session_factory() as session:
            record = session.get(ConversationRecord, conversation_id)
            if record is None:
                raise LookupError("会话不存在")
            turns = session.scalars(
                select(ConversationTurnRecord)
                .where(ConversationTurnRecord.conversation_id == conversation_id)
                .order_by(ConversationTurnRecord.created_at)
            ).all()
        return {
            **self._serialize(
                record,
                turn_count=len(turns),
                last_question=turns[-1].question if turns else "",
            ),
            "turns": [self._serialize_turn(turn) for turn in turns],
        }

    def rename(self, conversation_id: str, title: str) -> dict:
        with self._session_factory() as session:
            record = session.get(ConversationRecord, conversation_id)
            if record is None:
                raise LookupError("会话不存在")
            record.title = self._clean_title(title)
            record.updated_at = datetime.now(UTC)
            session.commit()
            turn_count = session.scalar(
                select(func.count(ConversationTurnRecord.turn_id)).where(
                    ConversationTurnRecord.conversation_id == conversation_id
                )
            )
        return self._serialize(record, turn_count=int(turn_count or 0), last_question="")

    def delete(self, conversation_id: str) -> None:
        with self._session_factory() as session:
            record = session.get(ConversationRecord, conversation_id)
            if record is None:
                raise LookupError("会话不存在")
            session.execute(
                delete(ConversationTurnRecord).where(
                    ConversationTurnRecord.conversation_id == conversation_id
                )
            )
            session.delete(record)
            session.commit()

    def record_turn(
        self,
        conversation_id: str,
        request: AskRequest,
        response: AskResponse,
    ) -> dict:
        now = datetime.now(UTC)
        if self._feedback_service is not None:
            self._feedback_service.capture_implicit(conversation_id, request.question)
        with self._session_factory() as session:
            conversation = session.get(ConversationRecord, conversation_id)
            if conversation is None:
                raise LookupError("会话不存在")
            existing_turns = session.scalar(
                select(func.count(ConversationTurnRecord.turn_id)).where(
                    ConversationTurnRecord.conversation_id == conversation_id
                )
            )
            turn = ConversationTurnRecord(
                turn_id=f"turn_{uuid4().hex[:20]}",
                conversation_id=conversation_id,
                created_at=now,
                question=request.question,
                attachments=[
                    {"name": item.name, "content_type": item.content_type}
                    for item in request.attachments
                ],
                response=response.model_dump(mode="json"),
            )
            session.add(turn)
            if not existing_turns and conversation.title == "新对话":
                conversation.title = self._clean_title(request.question)
            conversation.updated_at = now
            session.commit()
        response.turn_id = turn.turn_id
        return self._serialize_turn(turn)

    @staticmethod
    def _clean_title(title: str) -> str:
        cleaned = " ".join(title.strip().split()) or "新对话"
        return cleaned[:36]

    @staticmethod
    def _serialize(
        record: ConversationRecord,
        *,
        turn_count: int,
        last_question: str,
    ) -> dict:
        return {
            "conversation_id": record.conversation_id,
            "title": record.title,
            "created_at": record.created_at.isoformat(),
            "updated_at": record.updated_at.isoformat(),
            "turn_count": turn_count,
            "last_question": last_question,
        }

    @staticmethod
    def _serialize_turn(turn: ConversationTurnRecord) -> dict:
        return {
            "turn_id": turn.turn_id,
            "created_at": turn.created_at.isoformat(),
            "question": turn.question,
            "attachments": turn.attachments,
            "response": turn.response,
        }
