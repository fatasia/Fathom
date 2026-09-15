from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fathom.adapters.storage.runtime_records import RequirementEvidenceRecord
from fathom.adapters.storage.semantic_repository import SqlSemanticRepository
from fathom.application.lineage import LineageService
from fathom.domains.runtime.models import (
    DependencyEdgeInput,
    RequirementEvidenceInput,
    RequirementExploreInput,
    RequirementReviewInput,
)
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker


class RequirementService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        repository: SqlSemanticRepository,
        lineage: LineageService,
    ) -> None:
        self._session_factory = session_factory
        self._repository = repository
        self._lineage = lineage

    def save(self, payload: RequirementEvidenceInput) -> dict[str, Any]:
        now = datetime.now(UTC)
        definition = payload.model_dump(mode="json")
        with self._session_factory() as session:
            record = session.scalar(
                select(RequirementEvidenceRecord).where(
                    RequirementEvidenceRecord.evidence_key == payload.key
                )
            )
            if record is None:
                record = RequirementEvidenceRecord(
                    evidence_id=f"req_{uuid4().hex[:20]}",
                    evidence_key=payload.key,
                    title=payload.title,
                    source_uri=payload.source_uri,
                    owner=payload.owner,
                    definition=definition,
                    created_at=now,
                    updated_at=now,
                )
                session.add(record)
            else:
                record.title = payload.title
                record.source_uri = payload.source_uri
                record.owner = payload.owner
                record.definition = definition
                record.updated_at = now
            session.commit()
            session.refresh(record)
            item = self._serialize(record)
        for asset in payload.linked_assets:
            self._lineage.add(
                DependencyEdgeInput(
                    from_key=f"requirement:{payload.key}",
                    to_key=f"semantic:{asset}",
                    relation="justifies",
                    source="requirement_evidence",
                )
            )
        return item

    def list(self) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            records = session.scalars(
                select(RequirementEvidenceRecord).order_by(
                    RequirementEvidenceRecord.updated_at.desc()
                )
            ).all()
            return [self._serialize(record) for record in records]

    def explore(self, payload: RequirementExploreInput) -> dict[str, Any]:
        text = payload.text.strip()
        sentences = [
            item.strip(" -\t")
            for item in re.split(r"[\r\n]+|(?<=[。！？?])", text)
            if item.strip(" -\t")
        ]
        assets = self._repository.list_assets()
        matched = []
        for asset in assets:
            terms = [asset.key, asset.label, *asset.aliases]
            if any(term.casefold() in text.casefold() for term in terms if term):
                matched.append(asset.key)
        explicit_questions = [item for item in sentences if "?" in item or "？" in item]
        questions = list(explicit_questions)
        if not questions:
            questions = [
                item
                for item in sentences
                if any(token in item for token in ("查询", "分析", "多少", "为什么", "趋势"))
            ]
        statements = [
            item
            for item in sentences
            if item not in questions
            and any(token in item for token in ("需要", "必须", "应", "支持", "要求"))
        ]
        if not statements:
            statements = sentences[:5]
        if not questions:
            questions = ["该需求在已发布语义和真实数据上能否得到可验证答案？"]
        cited_sentences = list(dict.fromkeys([*statements, *questions]))
        citations = []
        for sentence in cited_sentences[:20]:
            offset = text.find(sentence)
            citations.append(
                {
                    "source_uri": payload.source_uri,
                    "excerpt": sentence[:500],
                    "line": text[: max(offset, 0)].count("\n") + 1,
                }
            )
        clarification_questions = []
        if not matched:
            clarification_questions.append("该需求对应哪个已发布业务对象或指标？")
        if len(matched) > 1:
            clarification_questions.append(
                "本需求的主指标是什么，其他匹配资产是维度、原因还是结果？"
            )
        if not explicit_questions:
            clarification_questions.append("业务负责人将用哪个问题验收这项需求？")
        conflicts = self._potential_conflicts(sorted(set(matched)), text)
        digest = hashlib.sha256(
            f"{payload.source_uri}\0{text}".encode()
        ).hexdigest()[:12]
        candidate = RequirementEvidenceInput(
            key=f"requirement.{digest}",
            title=(sentences[0][:80] if sentences else "需求探索候选"),
            source_uri=payload.source_uri,
            statements=statements[:20],
            acceptance_questions=questions[:20],
            linked_assets=sorted(set(matched)),
            citations=citations,
            clarification_questions=clarification_questions,
            conflicts=conflicts,
            owner=payload.owner,
        )
        return {
            "status": "candidate",
            "candidate": candidate.model_dump(mode="json"),
            "matched_assets": sorted(set(matched)),
            "clarification_questions": clarification_questions,
            "conflicts": conflicts,
            "notice": "探索结果未自动发布，需由业务与语义负责人评审。",
        }

    def review(self, key: str, payload: RequirementReviewInput) -> dict[str, Any]:
        with self._session_factory() as session:
            record = session.scalar(
                select(RequirementEvidenceRecord).where(
                    RequirementEvidenceRecord.evidence_key == key
                )
            )
            if record is None:
                raise LookupError(key)
            definition = dict(record.definition)
            definition["review_status"] = payload.decision
            definition["review"] = {
                "reviewer": payload.reviewer,
                "comment": payload.comment,
                "reviewed_at": datetime.now(UTC).isoformat(),
            }
            record.definition = definition
            record.updated_at = datetime.now(UTC)
            session.commit()
            session.refresh(record)
            return self._serialize(record)

    def _potential_conflicts(
        self, linked_assets: list[str], text: str
    ) -> list[dict[str, Any]]:
        if not linked_assets:
            return []
        incoming_numbers = set(re.findall(r"\d+(?:\.\d+)?%?", text))
        conflicts = []
        with self._session_factory() as session:
            records = session.scalars(select(RequirementEvidenceRecord)).all()
        for record in records:
            definition = record.definition or {}
            overlap = sorted(set(linked_assets) & set(definition.get("linked_assets", [])))
            if not overlap:
                continue
            existing_text = " ".join(definition.get("statements", []))
            existing_numbers = set(re.findall(r"\d+(?:\.\d+)?%?", existing_text))
            if incoming_numbers and existing_numbers and incoming_numbers != existing_numbers:
                conflicts.append(
                    {
                        "kind": "potential_numeric_conflict",
                        "existing_requirement_key": record.evidence_key,
                        "linked_assets": overlap,
                        "detail": (
                            "同一语义资产出现不同数值口径："
                            f"现有 {sorted(existing_numbers)}，候选 {sorted(incoming_numbers)}。"
                        ),
                    }
                )
        return conflicts[:20]

    @staticmethod
    def _serialize(record: RequirementEvidenceRecord) -> dict[str, Any]:
        return {
            "evidence_id": record.evidence_id,
            "key": record.evidence_key,
            "title": record.title,
            "source_uri": record.source_uri,
            "owner": record.owner,
            "definition": record.definition,
            "created_at": record.created_at.isoformat(),
            "updated_at": record.updated_at.isoformat(),
        }
