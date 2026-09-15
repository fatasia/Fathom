from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fathom.adapters.storage.runtime_records import DataQualityContractRecord
from fathom.domains.runtime.models import DataQualityContractInput
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker


class DataQualityService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def save(self, payload: DataQualityContractInput) -> dict[str, Any]:
        now = datetime.now(UTC)
        with self._session_factory() as session:
            record = session.get(DataQualityContractRecord, payload.key)
            values = payload.model_dump(mode="json")
            if record is None:
                record = DataQualityContractRecord(
                    key=payload.key,
                    mapping_key=payload.mapping_key,
                    owner=payload.owner,
                    checks=values["checks"],
                    strict=payload.strict,
                    status="published",
                    updated_at=now,
                )
                session.add(record)
            else:
                record.mapping_key = payload.mapping_key
                record.owner = payload.owner
                record.checks = values["checks"]
                record.strict = payload.strict
                record.status = "published"
                record.updated_at = now
            session.commit()
            session.refresh(record)
            return self._serialize(record)

    def list(self) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            records = session.scalars(
                select(DataQualityContractRecord).order_by(DataQualityContractRecord.key)
            ).all()
            return [self._serialize(record) for record in records]

    def evaluate(self, mapping_key: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        with self._session_factory() as session:
            contract = session.scalar(
                select(DataQualityContractRecord).where(
                    DataQualityContractRecord.mapping_key == mapping_key,
                    DataQualityContractRecord.status == "published",
                )
            )
        if contract is None:
            return {"status": "not_configured", "passed": True, "strict": False, "checks": []}
        results = [self._evaluate_check(check, rows) for check in contract.checks]
        passed = all(item["passed"] for item in results)
        return {
            "contract_key": contract.key,
            "status": "passed" if passed else "failed",
            "passed": passed,
            "strict": contract.strict,
            "checks": results,
        }

    @staticmethod
    def _evaluate_check(check: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
        kind = check["kind"]
        field = check.get("field", "value")
        expected = check.get("value")
        values = [row.get(field) for row in rows]
        if kind == "not_null":
            passed = bool(rows) and all(value is not None for value in values)
            actual: Any = sum(value is None for value in values)
        elif kind == "min_rows":
            passed = len(rows) >= int(expected or 0)
            actual = len(rows)
        elif kind == "min":
            numeric = [float(value) for value in values if value is not None]
            actual = min(numeric) if numeric else None
            passed = actual is not None and actual >= float(expected)
        elif kind == "max":
            numeric = [float(value) for value in values if value is not None]
            actual = max(numeric) if numeric else None
            passed = actual is not None and actual <= float(expected)
        elif kind == "freshness":
            parsed = [DataQualityService._as_datetime(value) for value in values if value]
            latest = max(parsed) if parsed else None
            actual = (datetime.now(UTC) - latest).total_seconds() if latest else None
            passed = actual is not None and actual <= float(expected)
        else:
            passed = False
            actual = None
        return {
            "kind": kind,
            "field": field,
            "expected": expected,
            "actual": actual,
            "passed": passed,
        }

    @staticmethod
    def _as_datetime(value: Any) -> datetime:
        if isinstance(value, datetime):
            parsed = value
        else:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    @staticmethod
    def _serialize(record: DataQualityContractRecord) -> dict[str, Any]:
        return {
            "key": record.key,
            "mapping_key": record.mapping_key,
            "owner": record.owner,
            "checks": record.checks,
            "strict": record.strict,
            "status": record.status,
            "updated_at": record.updated_at.isoformat(),
        }

