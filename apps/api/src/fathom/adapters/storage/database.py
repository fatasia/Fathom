from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fathom.config import Settings
from sqlalchemy import JSON, DateTime, Float, Integer, String, create_engine, inspect, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class SemanticAssetRecord(Base):
    __tablename__ = "semantic_assets"

    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    label: Mapped[str] = mapped_column(String(160), index=True)
    domain: Mapped[str] = mapped_column(String(160), index=True)
    owner: Mapped[str] = mapped_column(String(160))
    definition: Mapped[dict] = mapped_column(JSON)


class RelationEdgeRecord(Base):
    __tablename__ = "relation_edges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    relation_key: Mapped[str] = mapped_column(String(160), index=True)
    source_id: Mapped[str] = mapped_column(String(160), index=True)
    target_id: Mapped[str] = mapped_column(String(160), index=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ObjectInstanceRecord(Base):
    __tablename__ = "object_instances"

    object_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    object_type: Mapped[str] = mapped_column(String(160), index=True)
    label: Mapped[str] = mapped_column(String(160), index=True)
    source_key: Mapped[str] = mapped_column(String(160), index=True)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)
    state: Mapped[str] = mapped_column(String(32), default="active", index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class MetricObservationRecord(Base):
    __tablename__ = "metric_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    metric_key: Mapped[str] = mapped_column(String(160), index=True)
    object_id: Mapped[str] = mapped_column(String(160), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    value: Mapped[float] = mapped_column(Float)
    dimensions: Mapped[dict] = mapped_column(JSON)


class EventRecord(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(160), index=True)
    object_id: Mapped[str] = mapped_column(String(160), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    duration_minutes: Mapped[float] = mapped_column(Float, default=0)
    payload: Mapped[dict] = mapped_column(JSON)


class QueryTraceRecord(Base):
    __tablename__ = "query_traces"

    trace_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    question: Mapped[str] = mapped_column(String(1000))
    plan: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32))


class AuditEventRecord(Base):
    __tablename__ = "audit_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    principal: Mapped[str] = mapped_column(String(160), index=True)
    role: Mapped[str] = mapped_column(String(64), index=True)
    method: Mapped[str] = mapped_column(String(16))
    path: Mapped[str] = mapped_column(String(1000), index=True)
    status_code: Mapped[int] = mapped_column(Integer)
    duration_ms: Mapped[float] = mapped_column(Float)
    client: Mapped[str] = mapped_column(String(160), default="unknown")


class EvaluationRunRecord(Base):
    __tablename__ = "evaluation_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    suite_key: Mapped[str] = mapped_column(String(160), index=True)
    semantic_version: Mapped[str] = mapped_column(String(160))
    accuracy: Mapped[float] = mapped_column(Float)
    passed: Mapped[bool] = mapped_column(default=False)
    report: Mapped[dict] = mapped_column(JSON)


class SemanticChangeRecord(Base):
    __tablename__ = "semantic_changes"

    change_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(String(2000))
    confidence: Mapped[float] = mapped_column(Float)
    impact: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    patch: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), index=True)
    evaluation_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    previous_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    history: Mapped[list] = mapped_column(JSON, default=list)


class AgentRunRecord(Base):
    __tablename__ = "agent_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    flow_key: Mapped[str] = mapped_column(String(160), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result: Mapped[dict] = mapped_column(JSON)


class SqlTemplateRecord(Base):
    __tablename__ = "sql_templates"

    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    label: Mapped[str] = mapped_column(String(160), index=True)
    description: Mapped[str] = mapped_column(String(1000), default="")
    dialect: Mapped[str] = mapped_column(String(32), default="sqlite")
    sql_text: Mapped[str] = mapped_column(String)
    parameters: Mapped[list] = mapped_column(JSON, default=list)
    published: Mapped[bool] = mapped_column(default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DataSourceRecord(Base):
    __tablename__ = "data_sources"

    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    connector_type: Mapped[str] = mapped_column(String(64), index=True)
    configuration: Mapped[dict] = mapped_column(JSON, default=dict)
    secret_reference: Mapped[str | None] = mapped_column(String(256), nullable=True)
    enabled: Mapped[bool] = mapped_column(default=True)
    status: Mapped[str] = mapped_column(String(32), default="untested")
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ModelProviderRecord(Base):
    __tablename__ = "model_providers"

    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    provider_type: Mapped[str] = mapped_column(String(64), index=True)
    base_url: Mapped[str] = mapped_column(String(1000))
    api_mode: Mapped[str] = mapped_column(String(64), default="auto")
    default_model: Mapped[str] = mapped_column(String(256))
    secret_reference: Mapped[str | None] = mapped_column(String(256), nullable=True)
    capabilities: Mapped[list] = mapped_column(JSON, default=list)
    available_models: Mapped[list] = mapped_column(JSON, default=list)
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(default=True)
    status: Mapped[str] = mapped_column(String(32), default="untested")
    source: Mapped[str] = mapped_column(String(32), default="web")
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ModelRouteRecord(Base):
    __tablename__ = "model_routes"

    role: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider_key: Mapped[str] = mapped_column(String(160))
    model_override: Mapped[str | None] = mapped_column(String(256), nullable=True)
    parameter_overrides: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(32), default="web")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def create_session_factory(app_settings: Settings) -> sessionmaker[Session]:
    if app_settings.database_url.startswith("sqlite"):
        database_path = app_settings.database_url.removeprefix("sqlite:///")
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(
        app_settings.database_url,
        connect_args={"check_same_thread": False}
        if app_settings.database_url.startswith("sqlite")
        else {},
    )
    Base.metadata.create_all(engine)
    if app_settings.database_url.startswith("sqlite"):
        # Lite installs upgrade in place without requiring a separate migration service.
        columns = {column["name"] for column in inspect(engine).get_columns("model_providers")}
        if "available_models" not in columns:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE model_providers "
                        "ADD COLUMN available_models JSON NOT NULL DEFAULT '[]'"
                    )
                )
    return sessionmaker(engine, expire_on_commit=False)


def seed_demo_observations(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        existing = session.scalar(select(MetricObservationRecord.id).limit(1))
        if existing is not None:
            return

        today = datetime.now(UTC).replace(hour=8, minute=0, second=0, microsecond=0)
        yesterday = today - timedelta(days=1)
        previous = today - timedelta(days=2)
        observations = [
            ("order_fulfillment_rate", "line_01", previous, 93.6),
            ("order_fulfillment_rate", "line_01", yesterday, 87.4),
            ("oee", "line_01", previous, 84.7),
            ("oee", "line_01", yesterday, 78.2),
            ("actual_output", "line_01", previous, 936.0),
            ("actual_output", "line_01", yesterday, 874.0),
            ("planned_output", "line_01", previous, 1000.0),
            ("planned_output", "line_01", yesterday, 1000.0),
            ("downtime_minutes", "line_01", previous, 62.0),
            ("downtime_minutes", "line_01", yesterday, 138.0),
        ]
        session.add_all(
            MetricObservationRecord(
                metric_key=key,
                object_id=object_id,
                observed_at=observed_at,
                value=value,
                dimensions={"plant": "east_plant", "shift": "all"},
            )
            for key, object_id, observed_at, value in observations
        )
        session.add_all(
            [
                EventRecord(
                    event_type="unplanned_downtime",
                    object_id="equipment_press_01",
                    occurred_at=yesterday + timedelta(hours=2),
                    duration_minutes=47,
                    payload={"reason": "液压压力异常", "line": "line_01"},
                ),
                EventRecord(
                    event_type="unplanned_downtime",
                    object_id="equipment_robot_03",
                    occurred_at=yesterday + timedelta(hours=6),
                    duration_minutes=31,
                    payload={"reason": "视觉定位失败", "line": "line_01"},
                ),
                EventRecord(
                    event_type="changeover_delay",
                    object_id="line_01",
                    occurred_at=yesterday + timedelta(hours=10),
                    duration_minutes=22,
                    payload={"reason": "换型物料晚到", "line": "line_01"},
                ),
            ]
        )
        session.commit()


def seed_demo_object_instances(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        if session.get(ObjectInstanceRecord, "line_01") is not None:
            return
        now = datetime.now(UTC)
        session.add_all(
            [
                ObjectInstanceRecord(
                    object_id="east_plant",
                    object_type="plant",
                    label="华东工厂",
                    source_key="demo.manufacturing",
                    attributes={"region": "华东", "timezone": "Asia/Shanghai"},
                    updated_at=now,
                ),
                ObjectInstanceRecord(
                    object_id="line_01",
                    object_type="production_line",
                    label="一号生产线",
                    source_key="demo.manufacturing",
                    attributes={"line_code": "L01", "mode": "mixed_model"},
                    updated_at=now,
                ),
                ObjectInstanceRecord(
                    object_id="equipment_press_01",
                    object_type="equipment",
                    label="一号液压机",
                    source_key="demo.manufacturing",
                    attributes={"category": "hydraulic_press", "criticality": "A"},
                    updated_at=now,
                ),
                ObjectInstanceRecord(
                    object_id="equipment_robot_03",
                    object_type="equipment",
                    label="三号视觉机器人",
                    source_key="demo.manufacturing",
                    attributes={"category": "vision_robot", "criticality": "B"},
                    updated_at=now,
                ),
                ObjectInstanceRecord(
                    object_id="work_order_240820",
                    object_type="work_order",
                    label="工单 WO-240820",
                    source_key="demo.manufacturing",
                    attributes={"planned_quantity": 1000, "status": "in_progress"},
                    updated_at=now,
                ),
            ]
        )
        session.add_all(
            [
                RelationEdgeRecord(
                    relation_key="plant_contains_line",
                    source_id="east_plant",
                    target_id="line_01",
                    valid_from=now,
                ),
                RelationEdgeRecord(
                    relation_key="line_contains_equipment",
                    source_id="line_01",
                    target_id="equipment_press_01",
                    valid_from=now,
                ),
                RelationEdgeRecord(
                    relation_key="line_contains_equipment",
                    source_id="line_01",
                    target_id="equipment_robot_03",
                    valid_from=now,
                ),
                RelationEdgeRecord(
                    relation_key="work_order_runs_on_line",
                    source_id="work_order_240820",
                    target_id="line_01",
                    valid_from=now,
                ),
            ]
        )
        session.commit()


def seed_sql_templates(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        if session.get(SqlTemplateRecord, "metric.latest_comparison") is not None:
            return
        session.add_all(
            [
                SqlTemplateRecord(
                    key="metric.latest_comparison",
                    label="指标最新周期对比",
                    description="查询指定对象和指标最近两个周期的观测值。",
                    dialect="sqlite",
                    sql_text=(
                        "SELECT observed_at, value\n"
                        "FROM metric_observations\n"
                        "WHERE metric_key = :metric_key AND object_id = :object_id\n"
                        "ORDER BY observed_at DESC\nLIMIT 2"
                    ),
                    parameters=["metric_key", "object_id"],
                    published=True,
                    updated_at=datetime.now(UTC),
                ),
                SqlTemplateRecord(
                    key="event.top_contributors",
                    label="事件影响因子排行",
                    description="按持续时长返回影响最大的事件。",
                    dialect="sqlite",
                    sql_text=(
                        "SELECT event_type, object_id, duration_minutes, payload\n"
                        "FROM events\n"
                        "WHERE occurred_at >= :start_time\n"
                        "ORDER BY duration_minutes DESC\nLIMIT :limit"
                    ),
                    parameters=["start_time", "limit"],
                    published=True,
                    updated_at=datetime.now(UTC),
                ),
            ]
        )
        session.commit()
