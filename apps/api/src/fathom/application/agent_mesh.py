from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fathom.adapters.storage.database import AgentRunRecord
from fathom.application.data_sources import DataSourceService
from fathom.application.query_service import QueryService
from fathom.domains.query.models import AskRequest
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

BUILTIN_AGENTS: list[dict[str, Any]] = [
    {
        "key": "mesh_orchestrator",
        "name": "任务编排智能体",
        "layer": "control",
        "description": "识别任务复杂度，选择最短可信智能体链并控制成本、超时与上下文。",
        "model_role": "planner",
        "tools": ["route_task", "manage_context", "enforce_budget"],
        "status": "core",
    },
    {
        "key": "source_scout",
        "name": "数据探查智能体",
        "layer": "cognition",
        "description": "发现 IT/OT/文件/API Schema、采样质量并提出映射候选。",
        "model_role": "semantic_extractor",
        "tools": ["discover_schema", "profile_quality", "sample_values"],
        "status": "core",
    },
    {
        "key": "ontology_mapper",
        "name": "本体映射智能体",
        "layer": "cognition",
        "description": "把物理表、字段、事件和图像锚定到 ONN 六元业务对象空间。",
        "model_role": "semantic_extractor",
        "tools": ["search_semantics", "propose_mapping", "validate_onn"],
        "status": "core",
    },
    {
        "key": "metric_builder",
        "name": "指标构建智能体",
        "layer": "cognition",
        "description": "结合 dbt Semantic Layer 思路生成指标口径、粒度、维度和质量规则。",
        "model_role": "semantic_extractor",
        "tools": ["build_metric", "check_grain", "compare_sql_baseline"],
        "status": "core",
    },
    {
        "key": "question_planner",
        "name": "问数规划智能体",
        "layer": "reasoning",
        "description": "将自然语言翻译为可校验 FathomPlan，执行 Acquire→Build→Compute。",
        "model_role": "planner",
        "tools": ["bind_object", "bind_metric", "build_plan"],
        "status": "core",
    },
    {
        "key": "exploration_analyst",
        "name": "探索分析智能体",
        "layer": "reasoning",
        "description": "在权限和资源预算内提出下钻路径、对比、异常与相关性假设。",
        "model_role": "agent",
        "tools": ["drill_down", "compare_period", "rank_contributors"],
        "status": "core",
    },
    {
        "key": "multimodal_interpreter",
        "name": "跨模态理解智能体",
        "layer": "reasoning",
        "description": "理解 P&ID、设备照片、仪表截图、文档并与业务对象建立候选关系。",
        "model_role": "vision",
        "tools": ["inspect_image", "extract_document", "link_object"],
        "status": "optional",
    },
    {
        "key": "compute_executor",
        "name": "受控计算智能体",
        "layer": "execution",
        "description": "仅执行通过本体、权限、SQL 安全和资源预算校验的确定性计算。",
        "model_role": None,
        "tools": ["execute_template", "query_duckdb", "calculate_metric"],
        "status": "core",
    },
    {
        "key": "realtime_context",
        "name": "实时上下文智能体",
        "layer": "execution",
        "description": "消费 TDengine、OPC UA、MQTT 和 Historian 事件，维护对象实时状态。",
        "model_role": None,
        "tools": ["read_timeseries", "subscribe_event", "update_object_state"],
        "status": "optional",
    },
    {
        "key": "action_bridge",
        "name": "动作桥接智能体",
        "layer": "execution",
        "description": "将建议转为工单、告警或上层应用动作；高风险操作必须人工确认。",
        "model_role": "agent",
        "tools": ["draft_work_order", "send_webhook", "request_approval"],
        "status": "optional",
    },
    {
        "key": "evidence_guard",
        "name": "证据与权限智能体",
        "layer": "governance",
        "description": "验证身份范围、指标版本、证据充分性并阻止越权和无依据结论。",
        "model_role": None,
        "tools": ["authorize_scope", "verify_evidence", "audit_trace"],
        "status": "core",
    },
    {
        "key": "evolution_steward",
        "name": "演化学习智能体",
        "layer": "governance",
        "description": "从失败问题和反馈生成候选语义变更，评测后提交人工审批，不静默改生产。",
        "model_role": "semantic_extractor",
        "tools": ["mine_feedback", "propose_change", "run_golden_set"],
        "status": "core",
    },
]

AGENT_FLOWS = [
    {
        "key": "trusted_qa",
        "name": "可信问数",
        "trigger": "自然语言业务问题",
        "agents": [
            "mesh_orchestrator",
            "question_planner",
            "evidence_guard",
            "compute_executor",
            "evidence_guard",
        ],
        "sla": "交互式",
    },
    {
        "key": "guided_onboarding",
        "name": "小白建模",
        "trigger": "新数据源或业务问题集",
        "agents": [
            "source_scout",
            "ontology_mapper",
            "metric_builder",
            "evolution_steward",
        ],
        "sla": "异步评测",
    },
    {
        "key": "adaptive_diagnosis",
        "name": "实时诊断",
        "trigger": "异常事件或指标偏离",
        "agents": [
            "realtime_context",
            "exploration_analyst",
            "evidence_guard",
            "action_bridge",
        ],
        "sla": "事件驱动",
    },
]


def agent_mesh_overview() -> dict[str, Any]:
    counts: dict[str, int] = {}
    for agent in BUILTIN_AGENTS:
        counts[agent["layer"]] = counts.get(agent["layer"], 0) + 1
    return {
        "architecture": "ONN-constrained capability mesh",
        "agents": BUILTIN_AGENTS,
        "flows": AGENT_FLOWS,
        "counts": counts,
        "principles": [
            "shortest_trusted_path",
            "shared_fathom_plan",
            "deterministic_compute",
            "evidence_first",
            "human_approved_evolution",
        ],
    }


class AgentRunInput(BaseModel):
    flow_key: str
    question: str | None = Field(default=None, min_length=2, max_length=1000)
    source_key: str | None = None
    scope: dict[str, str] = Field(default_factory=dict)


class AgentMeshRuntime:
    """Small persistent runtime for the three built-in, governed flows."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        query_service: QueryService,
        data_source_service: DataSourceService,
    ) -> None:
        self._session_factory = session_factory
        self._query_service = query_service
        self._data_source_service = data_source_service

    def run(
        self,
        payload: AgentRunInput,
        authorized_objects: set[str] | None = None,
    ) -> dict[str, Any]:
        started_at = datetime.now(UTC)
        if payload.flow_key == "trusted_qa":
            result = self._run_trusted_qa(payload, authorized_objects)
        elif payload.flow_key == "guided_onboarding":
            result = self._run_guided_onboarding(payload)
        elif payload.flow_key == "adaptive_diagnosis":
            result = self._run_adaptive_diagnosis(payload, authorized_objects)
        else:
            raise ValueError(f"Unknown agent flow: {payload.flow_key}")

        run = {
            "run_id": f"run_{uuid4().hex[:16]}",
            "flow_key": payload.flow_key,
            "status": result["status"],
            "started_at": started_at.isoformat(),
            "completed_at": datetime.now(UTC).isoformat(),
            **result,
        }
        with self._session_factory() as session:
            session.add(
                AgentRunRecord(
                    run_id=run["run_id"],
                    created_at=started_at,
                    flow_key=payload.flow_key,
                    status=run["status"],
                    trace_id=run.get("trace_id"),
                    result=run,
                )
            )
            session.commit()
        return run

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self._session_factory() as session:
            record = session.get(AgentRunRecord, run_id)
            return record.result if record else None

    def list_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            records = session.scalars(
                select(AgentRunRecord)
                .order_by(AgentRunRecord.created_at.desc())
                .limit(min(max(limit, 1), 100))
            ).all()
            return [record.result for record in records]

    def _run_trusted_qa(
        self, payload: AgentRunInput, authorized_objects: set[str] | None
    ) -> dict[str, Any]:
        if not payload.question:
            raise ValueError("trusted_qa requires question")
        answer = self._query_service.ask(
            AskRequest(question=payload.question, scope=payload.scope),
            authorized_objects,
        )
        completed = answer.status == "completed"
        receipts = [
            self._receipt(1, "mesh_orchestrator", "completed", "选择可信问数最短链路"),
            self._receipt(2, "question_planner", "completed", answer.plan.intent),
            self._receipt(
                3,
                "evidence_guard",
                "completed" if completed else "blocked",
                "本体、权限与指标口径校验",
            ),
            self._receipt(
                4,
                "compute_executor",
                "completed" if completed else "not_started",
                "确定性数据计算",
            ),
            self._receipt(
                5,
                "evidence_guard",
                "completed" if completed else "not_started",
                f"输出 {len(answer.evidence)} 条证据",
            ),
        ]
        return {
            "status": "completed" if completed else answer.status,
            "trace_id": answer.trace_id,
            "receipts": receipts,
            "output": answer.model_dump(mode="json"),
        }

    def _run_guided_onboarding(self, payload: AgentRunInput) -> dict[str, Any]:
        if not payload.source_key:
            raise ValueError("guided_onboarding requires source_key")
        discovered = self._data_source_service.discover(payload.source_key)
        scaffold = self._data_source_service.scaffold(payload.source_key)
        receipts = [
            self._receipt(
                1,
                "source_scout",
                "completed",
                f"发现 {len(discovered['tables'])} 个数据对象",
            ),
            self._receipt(
                2,
                "ontology_mapper",
                "completed",
                f"生成 {len(scaffold['objects'])} 个候选对象",
            ),
            self._receipt(3, "metric_builder", "needs_review", "等待业务问题与指标口径确认"),
            self._receipt(4, "evolution_steward", "awaiting_approval", "候选项未写入生产本体"),
        ]
        return {
            "status": "awaiting_approval",
            "trace_id": None,
            "receipts": receipts,
            "output": {"discovery": discovered, "scaffold": scaffold},
        }

    def _run_adaptive_diagnosis(
        self, payload: AgentRunInput, authorized_objects: set[str] | None
    ) -> dict[str, Any]:
        question = payload.question or "为什么一号线昨天 OEE 异常？"
        answer = self._query_service.ask(
            AskRequest(question=question, scope=payload.scope),
            authorized_objects,
        )
        completed = answer.status == "completed"
        receipts = [
            self._receipt(1, "realtime_context", "completed", "读取持久化指标与事件快照"),
            self._receipt(
                2,
                "exploration_analyst",
                "completed" if completed else "blocked",
                "执行异常贡献因子分析",
            ),
            self._receipt(
                3,
                "evidence_guard",
                "completed" if completed else "blocked",
                f"核验 {len(answer.evidence)} 条证据",
            ),
            self._receipt(
                4,
                "action_bridge",
                "awaiting_approval" if completed else "not_started",
                "仅生成动作草案，未调用外部系统",
            ),
        ]
        return {
            "status": "awaiting_approval" if completed else answer.status,
            "trace_id": answer.trace_id,
            "receipts": receipts,
            "output": answer.model_dump(mode="json"),
        }

    @staticmethod
    def _receipt(sequence: int, agent: str, status: str, summary: str) -> dict[str, Any]:
        return {
            "sequence": sequence,
            "agent": agent,
            "status": status,
            "summary": summary,
            "recorded_at": datetime.now(UTC).isoformat(),
        }
