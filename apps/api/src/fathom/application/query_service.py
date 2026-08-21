from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fathom.adapters.storage.database import (
    EventRecord,
    MetricObservationRecord,
    ObjectInstanceRecord,
    QueryTraceRecord,
    RelationEdgeRecord,
)
from fathom.adapters.storage.semantic_repository import SqlSemanticRepository
from fathom.application.knowledge import KnowledgeSearchInput, KnowledgeService
from fathom.domains.query.models import (
    AbcStage,
    AskRequest,
    AskResponse,
    Evidence,
    FathomPlan,
    PlanAnchor,
    PlanStatus,
    SemanticBinding,
)
from fathom.domains.semantics.models import AssetKind, SemanticAsset
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker


class SemanticPlanner:
    """Build a constrained semantic IR; it never emits arbitrary SQL."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        repository: SqlSemanticRepository,
    ) -> None:
        self._session_factory = session_factory
        self._repository = repository

    def plan(self, request: AskRequest) -> FathomPlan:
        question = request.question.casefold()
        assets = self._repository.list_assets()
        metrics = [asset for asset in assets if asset.kind == AssetKind.METRIC]
        matched_metric = self._match_metric(question, metrics)
        object_match = self._match_object(question, request.scope, matched_metric)

        if object_match is None:
            anchors = (
                [PlanAnchor(kind="metric", key=matched_metric.key, label=matched_metric.label)]
                if matched_metric
                else []
            )
            return FathomPlan(
                question=request.question,
                status=PlanStatus.NEEDS_CLARIFICATION,
                intent="semantic_query",
                anchors=anchors,
                abc=[
                    AbcStage(
                        code="A",
                        name="Acquire",
                        status="blocked",
                        summary="缺少可确认的业务对象或数据范围",
                    ),
                    AbcStage(
                        code="B",
                        name="Build",
                        status="not_started",
                        summary="尚未构建对象—指标计划",
                    ),
                    AbcStage(
                        code="C",
                        name="Compute",
                        status="not_started",
                        summary="执行已阻断",
                    ),
                ],
                clarification=self._object_clarification(matched_metric),
                validations=["未识别业务对象，执行已阻断"],
            )

        object_id, object_label = object_match

        if matched_metric is None:
            return FathomPlan(
                question=request.question,
                status=PlanStatus.NEEDS_CLARIFICATION,
                intent="semantic_query",
                anchors=[PlanAnchor(kind="object", key=object_id, label=object_label)],
                abc=[
                    AbcStage(
                        code="A",
                        name="Acquire",
                        status="completed",
                        summary=f"已获取并锚定对象：{object_label}",
                    ),
                    AbcStage(
                        code="B",
                        name="Build",
                        status="blocked",
                        summary="缺少可确认的指标，未构建计算计划",
                    ),
                    AbcStage(
                        code="C",
                        name="Compute",
                        status="not_started",
                        summary="执行已阻断",
                    ),
                ],
                clarification="我已识别分析对象，但还不能确定指标。请选择达成率、OEE、停机时长或产量。",
                validations=["对象已锚定", "指标未绑定，执行已阻断"],
            )

        is_diagnostic = any(token in question for token in ["为什么", "原因", "下降", "异常"])
        time_range = self._resolve_time_range(question)
        return FathomPlan(
            question=request.question,
            status=PlanStatus.READY,
            intent="diagnose_metric" if is_diagnostic else "query_metric",
            anchors=[
                PlanAnchor(kind="object", key=object_id, label=object_label),
                PlanAnchor(kind="metric", key=matched_metric.key, label=matched_metric.label),
            ],
            binding=SemanticBinding(
                metric=matched_metric.key,
                dimensions=["production_line", "day"],
                time_range=time_range,
                comparison="previous_period" if is_diagnostic else None,
            ),
            abc=[
                AbcStage(
                    code="A",
                    name="Acquire",
                    status="completed",
                    summary=f"获取对象、范围和时间：{object_label} · {time_range}",
                ),
                AbcStage(
                    code="B",
                    name="Build",
                    status="completed",
                    summary=f"构建指标与关系计划：{matched_metric.label} · 日粒度",
                ),
                AbcStage(
                    code="C",
                    name="Compute",
                    status="ready",
                    summary="通过权限和口径校验，可进入确定性计算",
                ),
            ],
            policy_scope={"mode": "read_only", "object_scope": [object_id]},
            validations=[
                "对象、指标和时间语义已绑定",
                "指标来自已发布语义契约",
                "查询限制为只读并应用对象范围",
            ],
        )

    @staticmethod
    def _match_metric(question: str, metrics: list[SemanticAsset]) -> SemanticAsset | None:
        candidates: list[tuple[int, SemanticAsset]] = []
        for metric in metrics:
            terms = [metric.label, metric.key, *metric.aliases]
            matches = [len(term) for term in terms if term.casefold() in question]
            if matches:
                candidates.append((max(matches), metric))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    def _match_object(
        self,
        question: str,
        scope: dict[str, str],
        matched_metric: SemanticAsset | None,
    ) -> tuple[str, str] | None:
        with self._session_factory() as session:
            for key in ("object_id", "line", "equipment", "plant"):
                scoped_id = scope.get(key)
                if not scoped_id:
                    continue
                instance = session.get(ObjectInstanceRecord, scoped_id)
                if instance:
                    return instance.object_id, instance.label
            instances = session.scalars(
                select(ObjectInstanceRecord).where(ObjectInstanceRecord.state == "active")
            ).all()

        type_priority = {
            "plant": 1,
            "production_line": 2,
            "work_order": 3,
            "equipment": 4,
        }
        candidates: list[tuple[int, int, ObjectInstanceRecord]] = []
        for instance in instances:
            terms = {instance.object_id.casefold(), instance.label.casefold()}
            if "生产" in instance.label:
                terms.add(instance.label.replace("生产", "").casefold())
            numeric_suffix = re.search(r"(\d+)$", instance.object_id)
            if numeric_suffix and instance.object_type == "production_line":
                number = int(numeric_suffix.group(1))
                terms.update({f"{number}号线", f"{number}线"})
            terms.update(
                str(value).casefold()
                for value in instance.attributes.values()
                if isinstance(value, str) and len(value) >= 2
            )
            matches = [len(term) for term in terms if term and term in question]
            if matches:
                candidates.append(
                    (type_priority.get(instance.object_type, 2), max(matches), instance)
                )
        if not candidates:
            metric_objects = self._metric_object_candidates(matched_metric)
            if len(metric_objects) == 1:
                return metric_objects[0].object_id, metric_objects[0].label
            return None
        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return candidates[0][2].object_id, candidates[0][2].label

    def _metric_object_candidates(
        self, matched_metric: SemanticAsset | None
    ) -> list[ObjectInstanceRecord]:
        if matched_metric is None:
            return []
        with self._session_factory() as session:
            object_ids = select(MetricObservationRecord.object_id).where(
                MetricObservationRecord.metric_key == matched_metric.key
            )
            return list(
                session.scalars(
                    select(ObjectInstanceRecord)
                    .where(
                        ObjectInstanceRecord.state == "active",
                        ObjectInstanceRecord.object_id.in_(object_ids),
                    )
                    .order_by(ObjectInstanceRecord.label)
                ).all()
            )

    def _object_clarification(self, matched_metric: SemanticAsset | None) -> str:
        candidates = self._metric_object_candidates(matched_metric)
        if candidates:
            labels = "、".join(item.label for item in candidates[:5])
            return f"你想看哪个范围：{labels}？直接说业务名称即可。"
        with self._session_factory() as session:
            has_objects = session.scalar(
                select(ObjectInstanceRecord.object_id)
                .where(ObjectInstanceRecord.state == "active")
                .limit(1)
            )
        if has_objects is None:
            return (
                "当前还没有可查询的企业事实数据。请先在“数据接入”连接数据源并完成语义映射；"
                "指标定义已经保留，但系统不会用示例数字代替真实结果。"
            )
        return "请告诉我想看的工厂、产线或设备名称，例如“一号线”；无需填写技术 ID。"

    @staticmethod
    def _resolve_time_range(question: str) -> str:
        if "昨天" in question or "昨日" in question:
            return "yesterday"
        if "今天" in question or "今日" in question:
            return "today"
        date_match = re.search(r"(20\d{2})[-年/.](\d{1,2})[-月/.](\d{1,2})日?", question)
        if date_match:
            year, month, day = (int(value) for value in date_match.groups())
            try:
                return datetime(year, month, day, tzinfo=UTC).date().isoformat()
            except ValueError:
                pass
        return "latest"


class QueryService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        semantic_repository: SqlSemanticRepository,
        knowledge_service: KnowledgeService | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._repository = semantic_repository
        self._planner = SemanticPlanner(session_factory, semantic_repository)
        self._knowledge_service = knowledge_service

    def plan(self, request: AskRequest) -> FathomPlan:
        """Build a validated plan without executing data access or writing a trace."""
        return self._planner.plan(request)

    def ask(
        self,
        request: AskRequest,
        authorized_objects: set[str] | None = None,
    ) -> AskResponse:
        plan = self.plan(request)
        trace_id = f"tr_{uuid4().hex[:16]}"
        semantic_version = request.semantic_version or "manufacturing.execution@0.1.0"

        if plan.status != PlanStatus.READY or plan.binding is None:
            knowledge_response = self._answer_from_knowledge(
                request.question, trace_id, semantic_version
            )
            if knowledge_response is not None:
                self._save_trace(
                    trace_id,
                    request.question,
                    knowledge_response.plan,
                    knowledge_response.status,
                )
                return knowledge_response
            no_data = bool(plan.clarification and plan.clarification.startswith("当前还没有"))
            response = AskResponse(
                status="no_data" if no_data else plan.status.value,
                answer=plan.clarification or "需要补充信息后才能执行。",
                plan=plan,
                data={"columns": [], "rows": []},
                chart_spec={"type": "none"},
                evidence=[],
                quality_warnings=["尚未接入企业事实数据"] if no_data else [],
                suggested_followups=(
                    ["去数据接入连接企业数据源", "查看已发布指标定义"]
                    if no_data
                    else ["直接说出工厂、产线或设备名称", "换一个业务指标提问"]
                ),
                trace_id=trace_id,
                semantic_version=semantic_version,
                data_freshness=datetime.now(UTC).isoformat(),
            )
            self._save_trace(trace_id, request.question, plan, response.status)
            return response

        object_id = next(anchor.key for anchor in plan.anchors if anchor.kind == "object")
        if authorized_objects is not None and object_id not in authorized_objects:
            raise PermissionError(f"无权访问业务对象：{object_id}")
        with self._session_factory() as session:
            object_record = session.get(ObjectInstanceRecord, object_id)
            related_ids = session.scalars(
                select(RelationEdgeRecord.target_id).where(
                    RelationEdgeRecord.source_id == object_id
                )
            ).all()
            event_scope = [object_id, *related_ids]
            observation_query = select(MetricObservationRecord).where(
                MetricObservationRecord.metric_key == plan.binding.metric,
                MetricObservationRecord.object_id == object_id,
            )
            range_end = self._range_end(plan.binding.time_range)
            if range_end is not None:
                observation_query = observation_query.where(
                    MetricObservationRecord.observed_at < range_end
                )
            observations = session.scalars(
                observation_query
                .order_by(MetricObservationRecord.observed_at.desc())
                .limit(2)
            ).all()
            events = session.scalars(
                select(EventRecord)
                .where(
                    EventRecord.object_id.in_(event_scope),
                    EventRecord.occurred_at >= datetime.now(UTC) - timedelta(days=4),
                )
                .order_by(EventRecord.duration_minutes.desc())
            ).all()

        asset = next(
            asset for asset in self._repository.list_assets() if asset.key == plan.binding.metric
        )
        object_label = object_record.label if object_record else object_id
        source_key = object_record.source_key if object_record else "unknown"
        if not observations:
            response = AskResponse(
                status="no_data",
                answer=(
                    f"已识别“{object_label}”和“{asset.label}”，"
                    f"但在请求的时间范围内没有真实观测数据。系统没有使用示例值补齐结果。"
                ),
                plan=plan,
                data={"columns": [], "rows": []},
                chart_spec={"type": "none"},
                evidence=[
                    Evidence(
                        type="semantic_contract",
                        title=f"{asset.label} · 已发布口径",
                        reference=f"semantic://{asset.key}@0.1.0",
                        detail=asset.expression or asset.description,
                    )
                ],
                quality_warnings=["请求范围内没有可验证的真实观测值"],
                suggested_followups=["检查数据源同步状态", "查看该指标的数据映射"],
                trace_id=trace_id,
                semantic_version=semantic_version,
                data_freshness=datetime.now(UTC).isoformat(),
            )
            self._save_trace(trace_id, request.question, plan, response.status)
            return response

        current = observations[0]
        previous = observations[1] if len(observations) > 1 else None
        delta = current.value - previous.value if previous else 0.0
        relevant_events = [event for event in events if event.payload.get("line") == object_id][:4]
        answer = self._compose_answer(
            object_label,
            asset,
            current.value,
            delta,
            relevant_events,
            plan.intent,
        )
        rows = [
            {
                "period": observation.observed_at.date().isoformat(),
                "value": observation.value,
            }
            for observation in reversed(observations)
        ]
        freshness = max(observation.observed_at for observation in observations).isoformat()
        response = AskResponse(
            status="completed",
            answer=answer,
            plan=plan,
            data={
                "columns": ["period", "value"],
                "rows": rows,
                "current": current.value,
                "previous": previous.value if previous else None,
                "delta": round(delta, 2),
                "unit": asset.unit,
                "contributors": [
                    {
                        "label": event.payload.get("reason", event.event_type),
                        "minutes": event.duration_minutes,
                        "object": event.object_id,
                    }
                    for event in relevant_events
                ],
            },
            chart_spec={
                "type": "comparison_with_contributors",
                "metric": asset.label,
                "unit": asset.unit,
            },
            evidence=[
                Evidence(
                    type="semantic_contract",
                    title=f"{asset.label} · 已认证口径",
                    reference=f"semantic://{asset.key}@0.1.0",
                    detail=asset.expression or asset.description,
                ),
                Evidence(
                    type="observation",
                    title="指标观测值",
                    reference=f"source://{source_key}",
                    detail=f"对象 {object_label}，数据时间 {freshness}",
                ),
                *[
                    Evidence(
                        type="event",
                        title=event.payload.get("reason", event.event_type),
                        reference=f"event://{event.id}",
                        detail=f"{event.object_id} · {event.duration_minutes:.0f} 分钟",
                    )
                    for event in relevant_events[:3]
                ],
            ],
            quality_warnings=[],
            suggested_followups=[
                "按设备拆解非计划停机",
                "比较 OEE 与订单达成率的变化",
                "生成设备维护 Case 草案",
            ],
            trace_id=trace_id,
            semantic_version=semantic_version,
            data_freshness=freshness,
        )
        self._save_trace(trace_id, request.question, plan, response.status)
        return response

    def _answer_from_knowledge(
        self, question: str, trace_id: str, semantic_version: str
    ) -> AskResponse | None:
        if self._knowledge_service is None:
            return None
        search = self._knowledge_service.search(
            KnowledgeSearchInput(query=question, top_k=4)
        )
        hits = search["items"]
        if not hits or float(hits[0].get("score", 0)) < 0.35:
            return None
        top = hits[0]
        plan = FathomPlan(
            question=question,
            status=PlanStatus.READY,
            intent="knowledge_search",
            anchors=[
                PlanAnchor(
                    kind="knowledge_base",
                    key=top["knowledge_base_key"],
                    label=top["title"],
                )
            ],
            abc=[
                AbcStage(
                    code="A",
                    name="Acquire",
                    status="completed",
                    summary="检索已启用的内置与外接知识库",
                ),
                AbcStage(
                    code="B",
                    name="Build",
                    status="completed",
                    summary="按相关度合并、去重并保留来源",
                ),
                AbcStage(
                    code="C",
                    name="Compute",
                    status="completed",
                    summary="返回知识原文与可追溯引用",
                ),
            ],
            validations=["知识片段保留原始来源", "未使用知识库之外的事实补写答案"],
        )
        excerpt = str(top["content"]).strip()
        if len(excerpt) > 900:
            excerpt = f"{excerpt[:900].rstrip()}…"
        return AskResponse(
            status="completed",
            answer=f"根据《{top['title']}》：\n{excerpt}",
            plan=plan,
            data={"columns": [], "rows": []},
            chart_spec={"type": "none"},
            evidence=[
                Evidence(
                    type="knowledge",
                    title=item["title"],
                    reference=item["source_uri"],
                    detail=f"{item['retrieval']} · 相关度 {float(item['score']):.2f}",
                )
                for item in hits
            ],
            quality_warnings=search["warnings"],
            suggested_followups=["查看完整来源", "换一种说法继续检索"],
            trace_id=trace_id,
            semantic_version=semantic_version,
            data_freshness=datetime.now(UTC).isoformat(),
        )

    @staticmethod
    def _compose_answer(
        object_label: str,
        asset: SemanticAsset,
        current: float,
        delta: float,
        events: list[EventRecord],
        intent: str,
    ) -> str:
        unit = asset.unit or ""
        direction = "下降" if delta < 0 else "上升"
        summary = (
            f"{object_label}{asset.label}为 {current:.1f}{unit}，"
            f"较前一日{direction} {abs(delta):.1f}{unit}。"
        )
        if intent != "diagnose_metric" or not events:
            return summary
        total_minutes = sum(event.duration_minutes for event in events)
        top_reason = events[0].payload.get("reason", events[0].event_type)
        return (
            f"{summary} 主要关联 {total_minutes:.0f} 分钟的异常与换型事件，"
            f"其中影响最大的是“{top_reason}”。这是基于事件关联的诊断结论，不等同于已证明的因果关系。"
        )

    @staticmethod
    def _range_end(time_range: str) -> datetime | None:
        now = datetime.now(UTC)
        if time_range == "latest":
            return None
        if time_range == "today":
            return now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        if time_range == "yesterday":
            return now.replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            start = datetime.fromisoformat(time_range).replace(tzinfo=UTC)
        except ValueError:
            return None
        return start + timedelta(days=1)

    def _save_trace(self, trace_id: str, question: str, plan: FathomPlan, status: str) -> None:
        with self._session_factory() as session:
            session.add(
                QueryTraceRecord(
                    trace_id=trace_id,
                    created_at=datetime.now(UTC),
                    question=question,
                    plan=plan.model_dump(mode="json"),
                    status=status,
                )
            )
            session.commit()
