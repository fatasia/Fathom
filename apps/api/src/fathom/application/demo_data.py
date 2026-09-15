"""File-backed demo dataset and golden question set.

Both live under ``seed/`` so a fresh clone can run ``fathom demo-init`` and
``fathom eval`` without editing code. Values here are the example domain shipped
with the repository; deployments replace the files with their own.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from fathom.adapters.storage.database import (
    EventRecord,
    MetricObservationRecord,
    ObjectInstanceRecord,
    RelationEdgeRecord,
)
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

DEMO_DATASET_FILENAME = "demo-dataset.yaml"
GOLDEN_QUESTIONS_FILENAME = "golden-questions.yaml"


class SeedFileError(ValueError):
    """Raised when a seed file is missing or internally inconsistent."""


class DemoObject(BaseModel):
    object_id: str
    object_type: str
    label: str
    attributes: dict[str, Any] = Field(default_factory=dict)


class DemoRelation(BaseModel):
    relation_key: str
    source_id: str
    target_id: str


class DemoObservation(BaseModel):
    metric_key: str
    object_id: str
    day_offset: int
    value: float


class DemoEvent(BaseModel):
    event_type: str
    object_id: str
    day_offset: int = 0
    hour: int = 0
    duration_minutes: float = 0.0
    payload: dict[str, Any] = Field(default_factory=dict)


class DemoDataset(BaseModel):
    name: str
    label: str
    description: str = ""
    source_key: str
    objects: list[DemoObject]
    relations: list[DemoRelation] = Field(default_factory=list)
    observations: list[DemoObservation] = Field(default_factory=list)
    events: list[DemoEvent] = Field(default_factory=list)

    def validate_references(self) -> None:
        known = {item.object_id for item in self.objects}
        referenced = {
            *[item.source_id for item in self.relations],
            *[item.target_id for item in self.relations],
            *[item.object_id for item in self.observations],
            *[item.object_id for item in self.events],
        }
        missing = sorted(referenced - known)
        if missing:
            raise SeedFileError(f"示例数据集引用了未定义的对象：{', '.join(missing)}")


class GoldenMetric(BaseModel):
    key: str
    aliases: list[str] = Field(min_length=1)
    expected_value: float


class GoldenQuestionSet(BaseModel):
    suite_key: str
    semantic_version: str
    threshold: float = 0.99
    scope_note: str = ""
    metrics: list[GoldenMetric]
    question_patterns: list[str] = Field(min_length=1)
    safety_questions: list[str] = Field(default_factory=list)

    def certified_cases(self) -> list[tuple[str, str]]:
        """Every pattern × every alias, paired with the metric it must bind to."""
        return [
            (pattern.format(metric=metric.aliases[index % len(metric.aliases)]), metric.key)
            for metric in self.metrics
            for index, pattern in enumerate(self.question_patterns)
        ]

    def deterministic_question(self, metric: GoldenMetric) -> str:
        """The canonical phrasing used by the execution and evidence gates."""
        return self.question_patterns[0].format(metric=metric.aliases[0])

    def catalog(self) -> dict[str, Any]:
        """The exact case list behind the production evaluation gate."""
        semantic_cases = [
            {
                "id": f"semantic-{index:03d}",
                "category": "semantic_plan",
                "question": question,
                "expected": f"绑定指标：{expected}",
                "rule": "指标、对象、时间与范围必须通过语义约束",
            }
            for index, (question, expected) in enumerate(self.certified_cases(), start=1)
        ]
        execution_cases = [
            {
                "id": f"execution-{index:02d}",
                "category": "deterministic_execution",
                "question": self.deterministic_question(metric),
                "expected": f"基准值：{metric.expected_value:g}（严格一致）",
                "rule": "由确定性口径执行，不允许模型编造数值",
            }
            for index, metric in enumerate(self.metrics, start=1)
        ]
        evidence_cases = [
            {
                "id": f"evidence-{index:02d}",
                "category": "evidence_completeness",
                "question": self.deterministic_question(metric),
                "expected": "包含 trace ID，且至少 2 条数据证据",
                "rule": "结果必须可追溯到口径、数据与执行链路",
            }
            for index, metric in enumerate(self.metrics, start=1)
        ]
        safety_cases = [
            {
                "id": f"safety-{index:02d}",
                "category": "safe_blocking",
                "question": question,
                "expected": "澄清或安全拒答，不绑定未知指标",
                "rule": "未知、越权或证据不足时禁止猜测",
            }
            for index, question in enumerate(self.safety_questions, start=1)
        ]
        cases = semantic_cases + execution_cases + evidence_cases + safety_cases
        return {
            "suite_key": self.suite_key,
            "semantic_version": self.semantic_version,
            "threshold": self.threshold,
            "scope_note": self.scope_note,
            "categories": [
                {"key": "semantic_plan", "label": "语义规划", "count": len(semantic_cases)},
                {
                    "key": "deterministic_execution",
                    "label": "确定性数值",
                    "count": len(execution_cases),
                },
                {"key": "evidence_completeness", "label": "证据完整", "count": len(evidence_cases)},
                {"key": "safe_blocking", "label": "安全拒答", "count": len(safety_cases)},
            ],
            "total": len(cases),
            "cases": cases,
        }


def _read_yaml(path: Path) -> Any:
    if not path.is_file():
        raise SeedFileError(f"未找到种子文件：{path}")
    with path.open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def load_demo_dataset(path: Path) -> DemoDataset:
    dataset = DemoDataset.model_validate(_read_yaml(path))
    dataset.validate_references()
    return dataset


def load_golden_question_set(path: Path) -> GoldenQuestionSet:
    return GoldenQuestionSet.model_validate(_read_yaml(path))


def demo_base_time(reference: datetime | None = None) -> datetime:
    """Anchor relative day offsets at 08:00 UTC so repeated runs stay aligned."""
    return (reference or datetime.now(UTC)).replace(hour=8, minute=0, second=0, microsecond=0)


def demo_dataset_present(session: Session, source_key: str) -> bool:
    return (
        session.scalar(
            select(ObjectInstanceRecord.object_id)
            .where(ObjectInstanceRecord.source_key == source_key)
            .limit(1)
        )
        is not None
    )


def seed_demo_dataset(
    session_factory: sessionmaker[Session],
    dataset: DemoDataset,
    *,
    reference: datetime | None = None,
) -> dict[str, int]:
    """Load the demo dataset once; a second call is a no-op.

    Writes only facts tagged with the dataset ``source_key``, so operator data
    and previously ingested sources are never touched.
    """
    now = reference or datetime.now(UTC)
    base = demo_base_time(now)
    with session_factory() as session:
        if demo_dataset_present(session, dataset.source_key):
            return {"objects": 0, "relations": 0, "observations": 0, "events": 0, "skipped": 1}

        session.add_all(
            ObjectInstanceRecord(
                object_id=item.object_id,
                object_type=item.object_type,
                label=item.label,
                source_key=dataset.source_key,
                attributes=item.attributes,
                updated_at=now,
            )
            for item in dataset.objects
        )
        session.add_all(
            RelationEdgeRecord(
                relation_key=item.relation_key,
                source_id=item.source_id,
                target_id=item.target_id,
                valid_from=now,
            )
            for item in dataset.relations
        )
        session.add_all(
            MetricObservationRecord(
                metric_key=item.metric_key,
                object_id=item.object_id,
                observed_at=base + timedelta(days=item.day_offset),
                value=item.value,
                dimensions={"plant": "east_plant", "shift": "all"},
            )
            for item in dataset.observations
        )
        session.add_all(
            EventRecord(
                event_type=item.event_type,
                object_id=item.object_id,
                occurred_at=base + timedelta(days=item.day_offset, hours=item.hour),
                duration_minutes=item.duration_minutes,
                payload=item.payload,
            )
            for item in dataset.events
        )
        session.commit()
        return {
            "objects": len(dataset.objects),
            "relations": len(dataset.relations),
            "observations": len(dataset.observations),
            "events": len(dataset.events),
            "skipped": 0,
        }


def clear_demo_dataset(session_factory: sessionmaker[Session], source_key: str) -> int:
    """Remove facts carrying ``source_key``; published semantics are preserved."""
    with session_factory() as session:
        object_ids = set(
            session.scalars(
                select(ObjectInstanceRecord.object_id).where(
                    ObjectInstanceRecord.source_key == source_key
                )
            ).all()
        )
        if not object_ids:
            return 0
        session.query(RelationEdgeRecord).filter(
            (RelationEdgeRecord.source_id.in_(object_ids))
            | (RelationEdgeRecord.target_id.in_(object_ids))
        ).delete(synchronize_session=False)
        session.query(MetricObservationRecord).filter(
            MetricObservationRecord.object_id.in_(object_ids)
        ).delete(synchronize_session=False)
        session.query(EventRecord).filter(
            EventRecord.object_id.in_(object_ids)
        ).delete(synchronize_session=False)
        session.query(ObjectInstanceRecord).filter(
            ObjectInstanceRecord.source_key == source_key
        ).delete(synchronize_session=False)
        session.commit()
        return len(object_ids)


def dataset_summary(session_factory: sessionmaker[Session], source_key: str) -> dict[str, int]:
    """Count the loaded demo facts, for ``demo-init --status`` output."""
    with session_factory() as session:
        object_ids = set(
            session.scalars(
                select(ObjectInstanceRecord.object_id).where(
                    ObjectInstanceRecord.source_key == source_key
                )
            ).all()
        )
        if not object_ids:
            return {"objects": 0, "observations": 0, "events": 0}
        observations = session.scalar(
            select(func.count())
            .select_from(MetricObservationRecord)
            .where(MetricObservationRecord.object_id.in_(object_ids))
        )
        events = session.scalar(
            select(func.count())
            .select_from(EventRecord)
            .where(EventRecord.object_id.in_(object_ids))
        )
    return {
        "objects": len(object_ids),
        "observations": int(observations or 0),
        "events": int(events or 0),
    }