from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fathom.adapters.storage.database import AnalysisRunRecord, EventRecord, MetricObservationRecord
from fathom.domains.semantics.models import SemanticAsset
from sqlalchemy.orm import Session, sessionmaker


class DiagnosisService:
    """Run an evidence ladder and persist a reproducible RCA receipt."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def analyze(
        self,
        *,
        trace_id: str,
        asset: SemanticAsset,
        object_id: str,
        observations: list[MetricObservationRecord],
        events: list[EventRecord],
    ) -> dict[str, Any]:
        run_id = f"rca_{uuid4().hex[:16]}"
        current = observations[0] if observations else None
        previous = observations[1] if len(observations) > 1 else None
        delta = current.value - previous.value if current and previous else None
        related = [event for event in events if self._event_matches(event, object_id)][:10]
        formula_terms = self._formula_terms(asset.expression or "")
        steps = [
            {
                "code": "confirm_anomaly",
                "status": "completed" if delta is not None else "insufficient_data",
                "evidence": [f"observation://{item.id}" for item in observations[:2]],
                "finding": None if delta is None else f"当前值相对上一期变化 {delta:.2f}",
            },
            {
                "code": "decompose_metric",
                "status": "completed" if formula_terms else "not_applicable",
                "evidence": [f"semantic://{asset.key}"],
                "finding": (
                    f"口径因子：{', '.join(formula_terms)}"
                    if formula_terms
                    else "无可拆公式"
                ),
            },
            {
                "code": "rank_contributors",
                "status": "completed" if related else "insufficient_data",
                "evidence": [f"event://{item.id}" for item in related],
                "finding": (
                    f"发现 {len(related)} 个同期事件，共 "
                    f"{sum(item.duration_minutes for item in related):.0f} 分钟"
                    if related
                    else "未发现同期事件证据"
                ),
            },
            {
                "code": "validate_hypothesis",
                "status": "completed" if related and delta is not None else "insufficient_data",
                "evidence": [f"event://{item.id}" for item in related[:3]],
                "finding": "完成时间窗和对象范围一致性校验" if related else "缺少可检验假设",
            },
        ]
        explicitly_verified = any(
            bool(event.payload.get("causal_verification"))
            and bool(event.payload.get("reason"))
            and event.duration_minutes > 0
            for event in related
        )
        if explicitly_verified and delta is not None:
            level = "verified_root_cause"
        elif related and delta is not None:
            level = "suspected_cause"
        else:
            level = "driver"
        contributors = [
            {
                "label": event.payload.get("reason", event.event_type),
                "minutes": event.duration_minutes,
                "object_id": event.object_id,
                "event_id": event.id,
                "occurred_at": event.occurred_at.isoformat(),
            }
            for event in related[:5]
        ]
        result = {
            "analysis_run_id": run_id,
            "conclusion_level": level,
            "metric": asset.key,
            "object_id": object_id,
            "delta": delta,
            "contributors": contributors,
            "evidence_count": sum(len(step["evidence"]) for step in steps),
            "counterevidence": (
                []
                if explicitly_verified
                else ["当前证据仅证明同一时间窗内的关联，尚无对照实验或因果核验标记"]
            ),
            "summary": self._summary(level, contributors),
        }
        now = datetime.now(UTC)
        with self._session_factory() as session:
            session.add(
                AnalysisRunRecord(
                    analysis_run_id=run_id,
                    trace_id=trace_id,
                    analysis_type="root_cause",
                    status="completed",
                    metric_key=asset.key,
                    object_id=object_id,
                    steps=steps,
                    result=result,
                    created_at=now,
                    completed_at=now,
                )
            )
            session.commit()
        return {**result, "steps": steps}

    def get(self, analysis_run_id: str) -> dict[str, Any] | None:
        with self._session_factory() as session:
            record = session.get(AnalysisRunRecord, analysis_run_id)
        if record is None:
            return None
        return {
            **record.result,
            "steps": record.steps,
            "status": record.status,
            "trace_id": record.trace_id,
            "created_at": record.created_at.isoformat(),
        }

    @staticmethod
    def _event_matches(event: EventRecord, object_id: str) -> bool:
        return event.object_id == object_id or event.payload.get("line") == object_id

    @staticmethod
    def _formula_terms(expression: str) -> list[str]:
        ignored = {"sum", "avg", "min", "max", "count"}
        return [
            item
            for item in dict.fromkeys(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", expression))
            if item.casefold() not in ignored
        ]

    @staticmethod
    def _summary(level: str, contributors: list[dict[str, Any]]) -> str:
        if not contributors:
            return "已确认指标变化，但缺少足够事件证据定位驱动因素。"
        top = contributors[0]["label"]
        if level == "verified_root_cause":
            return f"证据链已核验，根因为“{top}”。"
        return f"“{top}”是当前证据支持度最高的疑似原因，尚不能宣称已证明因果。"
