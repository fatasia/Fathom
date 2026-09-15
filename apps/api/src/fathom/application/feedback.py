from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from fathom.adapters.storage.database import (
    ConversationTurnRecord,
    ExternalMessageLinkRecord,
    FeedbackRecord,
)
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker


class FeedbackInput(BaseModel):
    rating: Literal["like", "dislike"]
    content: str = Field(default="", max_length=2000)
    category: str | None = Field(default=None, max_length=64)


class FeedbackResolution(BaseModel):
    status: Literal["open", "reviewing", "resolved", "ignored"]
    resolution: str = Field(default="", max_length=2000)


class ExternalMessageLinkInput(BaseModel):
    provider: str = Field(default="external", min_length=1, max_length=64)
    app_id: str = Field(min_length=1, max_length=160)
    external_conversation_id: str = Field(min_length=1, max_length=160)
    external_message_id: str = Field(min_length=1, max_length=160)
    conversation_id: str | None = None
    turn_id: str | None = None
    trace_id: str | None = None


class ExternalFeedbackInput(BaseModel):
    app_id: str = Field(min_length=1, max_length=160)
    conversation_id: str = Field(min_length=1, max_length=160)
    message_id: str = Field(min_length=1, max_length=160)
    rating: Literal["like", "dislike"]
    content: str = Field(default="", max_length=2000)


class FeedbackService:
    """Capture explicit ratings and conservative implicit correction signals."""

    _negative = ("不是", "错了", "不对", "我要的是", "答非所问", "重新", "理解错", "怎么又", "离谱")
    _positive = ("对的", "答对了", "谢谢", "很好", "明白了", "正是")
    _categories: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("wrong_metric", ("指标", "口径", "不是这个", "我要的是")),
        ("wrong_time", ("时间", "昨天", "今天", "本周", "日期")),
        ("wrong_scope", ("范围", "基地", "工厂", "产线", "设备")),
        ("wrong_value", ("数字", "数值", "算错", "不一致")),
        ("stale_data", ("数据旧", "没更新", "延迟", "不同步")),
        ("weak_explanation", ("解释", "证据", "为什么", "没说清")),
        ("latency", ("太慢", "卡", "响应慢")),
    )

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def submit_turn(
        self,
        conversation_id: str,
        turn_id: str,
        payload: FeedbackInput,
        *,
        source: str = "self_ui",
    ) -> dict[str, Any]:
        with self._session_factory() as session:
            turn = session.get(ConversationTurnRecord, turn_id)
            if turn is None or turn.conversation_id != conversation_id:
                raise LookupError("对话轮次不存在")
            record = self._build_record(
                source=source,
                rating=payload.rating,
                content=payload.content,
                category=payload.category,
                conversation_id=conversation_id,
                turn_id=turn_id,
                trace_id=str(turn.response.get("trace_id") or "") or None,
                response=turn.response,
            )
            session.add(record)
            session.commit()
            session.refresh(record)
        return self._serialize(record)

    def capture_implicit(self, conversation_id: str, text: str) -> dict[str, Any] | None:
        rating, confidence = self._implicit_signal(text)
        if rating is None:
            return None
        with self._session_factory() as session:
            previous = session.scalar(
                select(ConversationTurnRecord)
                .where(ConversationTurnRecord.conversation_id == conversation_id)
                .order_by(ConversationTurnRecord.created_at.desc())
                .limit(1)
            )
            if previous is None:
                return None
            duplicate = session.scalar(
                select(FeedbackRecord).where(
                    FeedbackRecord.turn_id == previous.turn_id,
                    FeedbackRecord.source == "implicit_text",
                    FeedbackRecord.content == text,
                )
            )
            if duplicate is not None:
                return self._serialize(duplicate)
            record = self._build_record(
                source="implicit_text",
                rating=rating,
                content=text,
                category=None,
                conversation_id=conversation_id,
                turn_id=previous.turn_id,
                trace_id=str(previous.response.get("trace_id") or "") or None,
                response=previous.response,
                confidence=confidence,
            )
            session.add(record)
            session.commit()
            session.refresh(record)
        return self._serialize(record)

    def link_external(self, payload: ExternalMessageLinkInput) -> dict[str, Any]:
        if payload.turn_id:
            with self._session_factory() as session:
                if session.get(ConversationTurnRecord, payload.turn_id) is None:
                    raise LookupError("对话轮次不存在")
        with self._session_factory() as session:
            existing = session.scalar(
                select(ExternalMessageLinkRecord).where(
                    ExternalMessageLinkRecord.provider == payload.provider,
                    ExternalMessageLinkRecord.app_id == payload.app_id,
                    ExternalMessageLinkRecord.external_message_id == payload.external_message_id,
                )
            )
            if existing is None:
                existing = ExternalMessageLinkRecord(
                    link_id=f"link_{uuid4().hex[:16]}",
                    **payload.model_dump(),
                    created_at=datetime.now(UTC),
                )
                session.add(existing)
            else:
                for key, value in payload.model_dump().items():
                    setattr(existing, key, value)
            session.commit()
            session.refresh(existing)
        return self._serialize_link(existing)

    def import_external(self, payload: ExternalFeedbackInput) -> dict[str, Any]:
        with self._session_factory() as session:
            link = session.scalar(
                select(ExternalMessageLinkRecord).where(
                    ExternalMessageLinkRecord.provider == "external",
                    ExternalMessageLinkRecord.app_id == payload.app_id,
                    ExternalMessageLinkRecord.external_message_id == payload.message_id,
                )
            )
            response: dict[str, Any] = {}
            if link and link.turn_id:
                turn = session.get(ConversationTurnRecord, link.turn_id)
                response = turn.response if turn else {}
            record = self._build_record(
                source="external",
                rating=payload.rating,
                content=payload.content,
                category=None,
                conversation_id=link.conversation_id if link else None,
                turn_id=link.turn_id if link else None,
                trace_id=link.trace_id if link else None,
                external_message_id=payload.message_id,
                response=response,
            )
            session.add(record)
            session.commit()
            session.refresh(record)
        return self._serialize(record)

    def list(self, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        statement = select(FeedbackRecord)
        if status:
            statement = statement.where(FeedbackRecord.status == status)
        with self._session_factory() as session:
            records = session.scalars(
                statement.order_by(FeedbackRecord.created_at.desc()).limit(
                    min(max(limit, 1), 500)
                )
            ).all()
        return [self._serialize(item) for item in records]

    def resolve(self, feedback_id: str, payload: FeedbackResolution) -> dict[str, Any]:
        with self._session_factory() as session:
            record = session.get(FeedbackRecord, feedback_id)
            if record is None:
                raise LookupError(feedback_id)
            record.status = payload.status
            record.resolution = payload.resolution
            record.updated_at = datetime.now(UTC)
            session.commit()
            session.refresh(record)
        return self._serialize(record)

    def _build_record(
        self,
        *,
        source: str,
        rating: str,
        content: str,
        category: str | None,
        conversation_id: str | None,
        turn_id: str | None,
        trace_id: str | None,
        response: dict[str, Any],
        confidence: float = 1.0,
        external_message_id: str | None = None,
    ) -> FeedbackRecord:
        now = datetime.now(UTC)
        sentiment = "positive" if rating == "like" else "negative"
        emotion = self._emotion(content, rating)
        return FeedbackRecord(
            feedback_id=f"fb_{uuid4().hex[:16]}",
            conversation_id=conversation_id,
            turn_id=turn_id,
            trace_id=trace_id,
            external_message_id=external_message_id,
            source=source,
            rating=rating,
            content=content,
            category=category or self._category(content),
            sentiment=sentiment,
            emotion=emotion,
            confidence=confidence,
            semantic_version=response.get("semantic_version"),
            mql=(response.get("plan") or {}).get("mql") or {},
            result_hash=self._result_hash(response) if response else None,
            status="open",
            resolution="",
            created_at=now,
            updated_at=now,
        )

    def _implicit_signal(self, text: str) -> tuple[str | None, float]:
        if any(token in text for token in self._negative):
            return "dislike", 0.86
        if any(token in text for token in self._positive):
            return "like", 0.78
        return None, 0.0

    def _category(self, content: str) -> str:
        for category, terms in self._categories:
            if any(term in content for term in terms):
                return category
        return "general"

    @staticmethod
    def _emotion(content: str, rating: str) -> str:
        if rating == "like":
            return "satisfied"
        if any(token in content for token in ("离谱", "怎么又", "太差", "生气")):
            return "frustrated"
        if any(token in content for token in ("不是", "不对", "我要的是", "理解错")):
            return "corrective"
        return "dissatisfied"

    @staticmethod
    def _result_hash(response: dict[str, Any]) -> str:
        canonical = json.dumps(response.get("data", {}), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _serialize(record: FeedbackRecord) -> dict[str, Any]:
        return {
            "feedback_id": record.feedback_id,
            "conversation_id": record.conversation_id,
            "turn_id": record.turn_id,
            "trace_id": record.trace_id,
            "external_message_id": record.external_message_id,
            "source": record.source,
            "rating": record.rating,
            "content": record.content,
            "category": record.category,
            "sentiment": record.sentiment,
            "emotion": record.emotion,
            "confidence": record.confidence,
            "semantic_version": record.semantic_version,
            "mql": record.mql,
            "result_hash": record.result_hash,
            "status": record.status,
            "resolution": record.resolution,
            "created_at": record.created_at.isoformat(),
            "updated_at": record.updated_at.isoformat(),
        }

    @staticmethod
    def _serialize_link(record: ExternalMessageLinkRecord) -> dict[str, Any]:
        return {
            "link_id": record.link_id,
            "provider": record.provider,
            "app_id": record.app_id,
            "external_conversation_id": record.external_conversation_id,
            "external_message_id": record.external_message_id,
            "conversation_id": record.conversation_id,
            "turn_id": record.turn_id,
            "trace_id": record.trace_id,
            "created_at": record.created_at.isoformat(),
        }
