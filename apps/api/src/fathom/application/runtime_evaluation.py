from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from fathom.adapters.storage.database import EvaluationRunRecord
from fathom.adapters.storage.runtime_records import RuntimeGoldenCaseRecord
from fathom.domains.query.models import MqlQuery
from fathom.domains.runtime.models import GoldenCaseInput
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker


class RuntimeExecutor(Protocol):
    def execute(
        self,
        query: MqlQuery,
        *,
        principal: str,
        role: str,
        authorized_objects: set[str] | None,
        trace_id: str | None = None,
    ) -> dict[str, Any]: ...


class RuntimeEvaluationService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        runtime: RuntimeExecutor,
    ) -> None:
        self._session_factory = session_factory
        self._runtime = runtime

    def save_case(self, payload: GoldenCaseInput) -> dict[str, Any]:
        now = datetime.now(UTC)
        with self._session_factory() as session:
            record = session.get(RuntimeGoldenCaseRecord, payload.key)
            if record is None:
                record = RuntimeGoldenCaseRecord(
                    key=payload.key,
                    question=payload.question,
                    query=payload.query.model_dump(mode="json"),
                    expected_value=payload.expected_value,
                    tolerance=payload.tolerance,
                    enabled=True,
                    updated_at=now,
                )
                session.add(record)
            else:
                record.question = payload.question
                record.query = payload.query.model_dump(mode="json")
                record.expected_value = payload.expected_value
                record.tolerance = payload.tolerance
                record.enabled = True
                record.updated_at = now
            session.commit()
            session.refresh(record)
            return self._serialize(record)

    def list_cases(self) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            records = session.scalars(
                select(RuntimeGoldenCaseRecord)
                .where(RuntimeGoldenCaseRecord.enabled.is_(True))
                .order_by(RuntimeGoldenCaseRecord.key)
            ).all()
            return [self._serialize(record) for record in records]

    def run(self) -> dict[str, Any]:
        cases = self.list_cases()
        results = []
        for case in cases:
            try:
                execution = self._runtime.execute(
                    MqlQuery.model_validate(case["query"]),
                    principal="runtime-evaluator",
                    role="admin",
                    authorized_objects=None,
                )
                rows = execution["rows"]
                actual = float(rows[0]["value"]) if rows else None
                passed = actual is not None and abs(actual - case["expected_value"]) <= case[
                    "tolerance"
                ]
                error = None
            except Exception as exception:  # receipt retains connector detail
                actual = None
                passed = False
                error = str(exception)
            results.append({**case, "actual_value": actual, "passed": passed, "error": error})
        passed_count = sum(item["passed"] for item in results)
        total = len(results)
        accuracy = passed_count / total if total else 0.0
        report = {
            "run_id": f"eval_{uuid4().hex[:16]}",
            "suite_key": "runtime.external.golden",
            "total": total,
            "passed_count": passed_count,
            "accuracy": accuracy,
            "passed": bool(total) and accuracy == 1.0,
            "results": results,
        }
        with self._session_factory() as session:
            session.add(
                EvaluationRunRecord(
                    run_id=report["run_id"],
                    created_at=datetime.now(UTC),
                    suite_key=report["suite_key"],
                    semantic_version="runtime-mappings",
                    accuracy=accuracy,
                    passed=report["passed"],
                    report=report,
                )
            )
            session.commit()
        return report

    @staticmethod
    def _serialize(record: RuntimeGoldenCaseRecord) -> dict[str, Any]:
        return {
            "key": record.key,
            "question": record.question,
            "query": record.query,
            "expected_value": record.expected_value,
            "tolerance": record.tolerance,
            "enabled": record.enabled,
            "updated_at": record.updated_at.isoformat(),
        }

