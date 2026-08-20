from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fathom.adapters.storage.database import EvaluationRunRecord
from fathom.application.query_service import QueryService
from fathom.domains.query.models import AskRequest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

CERTIFIED_METRIC_ALIASES = {
    "order_fulfillment_rate": ["订单达成率", "达成率", "计划达成率", "fulfillment"],
    "oee": ["OEE", "设备综合效率", "综合效率"],
    "downtime_minutes": ["停机时长", "停机时间", "停线时长"],
    "actual_output": ["实际产量", "产量", "完成量"],
    "planned_output": ["计划产量", "计划量"],
}

QUESTION_PATTERNS = [
    "查询一号线昨天的{metric}",
    "一号线昨天{metric}是多少？",
    "分析一号线的{metric}",
    "请给出一号线{metric}趋势",
    "为什么一号线{metric}下降？",
    "华东工厂一号线的{metric}",
    "看一下1号线昨天{metric}",
    "line_01 {metric}",
    "帮我统计一号线的{metric}",
    "我要了解一号线{metric}",
    "一号线 {metric} 日报",
    "对比一号线两天的{metric}",
    "诊断一号线{metric}异常",
    "解释一号线{metric}变化",
    "一号线的{metric}表现如何",
    "复核一号线{metric}",
    "获取一号线{metric}",
    "计算一号线{metric}",
    "展示一号线{metric}",
    "一号线{metric}有没有下降",
]

EXECUTION_CASES = {
    "order_fulfillment_rate": 87.4,
    "oee": 78.2,
    "downtime_minutes": 138.0,
    "actual_output": 874.0,
    "planned_output": 1000.0,
}

SAFETY_CASES = [
    "一号线利润是多少",
    "一号线碳排强度",
    "一号线客户满意度",
    "一号线预算完成情况",
    "一号线人员绩效",
    "一号线未知指标甲",
    "一号线未知指标乙",
    "一号线预测指标",
    "一号线随便算一个值",
    "一号线怎么样",
]


def certified_cases() -> list[tuple[str, str]]:
    return [
        (pattern.format(metric=aliases[index % len(aliases)]), expected)
        for expected, aliases in CERTIFIED_METRIC_ALIASES.items()
        for index, pattern in enumerate(QUESTION_PATTERNS)
    ]


class EvaluationService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        query_service: QueryService,
    ) -> None:
        self._session_factory = session_factory
        self._query_service = query_service

    def run_certified_suite(self) -> dict[str, Any]:
        cases = certified_cases()
        failures = []
        correct = 0
        for question, expected in cases:
            plan = self._query_service.plan(AskRequest(question=question))
            actual = plan.binding.metric if plan.binding else None
            if actual == expected:
                correct += 1
            else:
                failures.append({"question": question, "expected": expected, "actual": actual})

        accuracy = correct / len(cases)
        execution_failures = []
        evidence_failures = []
        for metric_key, expected_value in EXECUTION_CASES.items():
            alias = CERTIFIED_METRIC_ALIASES[metric_key][0]
            answer = self._query_service.ask(AskRequest(question=f"查询一号线昨天的{alias}"))
            actual_value = answer.data.get("current")
            if actual_value != expected_value:
                execution_failures.append(
                    {
                        "metric": metric_key,
                        "expected": expected_value,
                        "actual": actual_value,
                    }
                )
            if not answer.trace_id or len(answer.evidence) < 2:
                evidence_failures.append(
                    {
                        "metric": metric_key,
                        "trace": bool(answer.trace_id),
                        "evidence_count": len(answer.evidence),
                    }
                )
        safety_failures = []
        for question in SAFETY_CASES:
            plan = self._query_service.plan(AskRequest(question=question))
            if plan.status.value != "needs_clarification" or plan.binding is not None:
                safety_failures.append({"question": question, "status": plan.status.value})
        supplemental_passed = not (execution_failures or evidence_failures or safety_failures)
        report = {
            "run_id": f"eval_{uuid4().hex[:16]}",
            "suite_key": "manufacturing.execution.semantic-plan.v1",
            "semantic_version": "manufacturing.execution@0.1.0",
            "threshold": 0.99,
            "total": len(cases),
            "correct": correct,
            "accuracy": accuracy,
            "accuracy_percent": round(accuracy * 100, 2),
            "passed": accuracy >= 0.99 and supplemental_passed,
            "failures": failures[:20],
            "gates": {
                "semantic_plan": {
                    "passed": accuracy >= 0.99,
                    "correct": correct,
                    "total": len(cases),
                },
                "deterministic_execution": {
                    "passed": not execution_failures,
                    "total": len(EXECUTION_CASES),
                    "failures": execution_failures,
                },
                "evidence_completeness": {
                    "passed": not evidence_failures,
                    "total": len(EXECUTION_CASES),
                    "failures": evidence_failures,
                },
                "safe_blocking": {
                    "passed": not safety_failures,
                    "total": len(SAFETY_CASES),
                    "failures": safety_failures,
                },
            },
            "evaluated_at": datetime.now(UTC).isoformat(),
            "scope_note": "仅代表已认证制造执行语义域问题集，不代表任意企业问题。",
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
                select(EvaluationRunRecord).order_by(EvaluationRunRecord.created_at.desc()).limit(1)
            )
            return record.report if record else None
