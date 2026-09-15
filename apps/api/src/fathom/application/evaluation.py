from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fathom.adapters.storage.database import EvaluationRunRecord
from fathom.application.demo_data import (
    GOLDEN_QUESTIONS_FILENAME,
    GoldenQuestionSet,
    load_golden_question_set,
)
from fathom.application.query_service import QueryService
from fathom.domains.query.models import AskRequest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker


def load_certified_suite(seed_directory: Path) -> GoldenQuestionSet:
    """Read the shipped golden set; operators may replace the file with their own."""
    return load_golden_question_set(seed_directory / GOLDEN_QUESTIONS_FILENAME)


def golden_question_catalog(golden_set: GoldenQuestionSet) -> dict[str, Any]:
    """Return the exact cases used by the production evaluation gate."""
    return golden_set.catalog()


class EvaluationService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        query_service: QueryService,
        golden_set: GoldenQuestionSet,
    ) -> None:
        self._session_factory = session_factory
        self._query_service = query_service
        self._golden_set = golden_set

    @property
    def suite_key(self) -> str:
        return self._golden_set.suite_key

    def run_certified_suite(self) -> dict[str, Any]:
        threshold = self._golden_set.threshold
        cases = self._golden_set.certified_cases()
        failures = []
        correct = 0
        for question, expected in cases:
            plan = self._query_service.plan(AskRequest(question=question))
            actual = plan.binding.metric if plan.binding else None
            if actual == expected:
                correct += 1
            else:
                failures.append({"question": question, "expected": expected, "actual": actual})

        accuracy = correct / len(cases) if cases else 0.0
        execution_failures = []
        evidence_failures = []
        for metric in self._golden_set.metrics:
            answer = self._query_service.ask(
                AskRequest(question=self._golden_set.deterministic_question(metric))
            )
            actual_value = answer.data.get("current")
            if actual_value != metric.expected_value:
                execution_failures.append(
                    {
                        "metric": metric.key,
                        "expected": metric.expected_value,
                        "actual": actual_value,
                    }
                )
            if not answer.trace_id or len(answer.evidence) < 2:
                evidence_failures.append(
                    {
                        "metric": metric.key,
                        "trace": bool(answer.trace_id),
                        "evidence_count": len(answer.evidence),
                    }
                )
        safety_failures = []
        for question in self._golden_set.safety_questions:
            plan = self._query_service.plan(AskRequest(question=question))
            if plan.status.value != "needs_clarification" or plan.binding is not None:
                safety_failures.append({"question": question, "status": plan.status.value})
        supplemental_passed = not (execution_failures or evidence_failures or safety_failures)
        report = {
            "run_id": f"eval_{uuid4().hex[:16]}",
            "suite_key": self._golden_set.suite_key,
            "semantic_version": self._golden_set.semantic_version,
            "threshold": threshold,
            "total": len(cases),
            "correct": correct,
            "accuracy": accuracy,
            "accuracy_percent": round(accuracy * 100, 2),
            "passed": accuracy >= threshold and supplemental_passed,
            "failures": failures[:20],
            "gates": {
                "semantic_plan": {
                    "passed": accuracy >= threshold,
                    "correct": correct,
                    "total": len(cases),
                },
                "deterministic_execution": {
                    "passed": not execution_failures,
                    "total": len(self._golden_set.metrics),
                    "failures": execution_failures,
                },
                "evidence_completeness": {
                    "passed": not evidence_failures,
                    "total": len(self._golden_set.metrics),
                    "failures": evidence_failures,
                },
                "safe_blocking": {
                    "passed": not safety_failures,
                    "total": len(self._golden_set.safety_questions),
                    "failures": safety_failures,
                },
            },
            "evaluated_at": datetime.now(UTC).isoformat(),
            "scope_note": self._golden_set.scope_note,
        }
        with self._session_factory() as session:
            session.add(
                EvaluationRunRecord(
                    run_id=report["run_id"],
                    created_at=datetime.fromisoformat(report["evaluated_at"]),
                    suite_key=report["suite_key"],
                    semantic_version=report["semantic_version"],
                    accuracy=accuracy,
                    passed=report["passed"],
                    report=report,
                )
            )
            session.commit()
        return report

    def latest(self) -> dict[str, Any] | None:
        with self._session_factory() as session:
            record = session.scalar(
                select(EvaluationRunRecord)
                .where(EvaluationRunRecord.suite_key == self._golden_set.suite_key)
                .order_by(EvaluationRunRecord.created_at.desc())
                .limit(1)
            )
            return record.report if record else None