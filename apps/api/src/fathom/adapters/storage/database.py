from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fathom.config import Settings
from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    Integer,
    String,
    create_engine,
    inspect,
    text,
)
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


class SchemaSnapshotRecord(Base):
    __tablename__ = "schema_snapshots"

    snapshot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_key: Mapped[str] = mapped_column(String(160), index=True)
    checksum: Mapped[str] = mapped_column(String(64), index=True)
    schema_document: Mapped[dict] = mapped_column(JSON)
    diff: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ExtractionRunRecord(Base):
    __tablename__ = "extraction_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trigger_type: Mapped[str] = mapped_column(String(32), index=True)
    source_key: Mapped[str] = mapped_column(String(160), index=True)
    input_hash: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ConversationRecord(Base):
    __tablename__ = "conversations"

    conversation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ConversationTurnRecord(Base):
    __tablename__ = "conversation_turns"

    turn_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    question: Mapped[str] = mapped_column(String(1000))
    attachments: Mapped[list] = mapped_column(JSON, default=list)
    response: Mapped[dict] = mapped_column(JSON)


class FeedbackRecord(Base):
    __tablename__ = "feedback"

    feedback_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    turn_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    external_message_id: Mapped[str | None] = mapped_column(
        String(160), nullable=True, index=True
    )
    source: Mapped[str] = mapped_column(String(32), index=True)
    rating: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    content: Mapped[str] = mapped_column(String(2000), default="")
    category: Mapped[str] = mapped_column(String(64), default="general", index=True)
    sentiment: Mapped[str] = mapped_column(String(32), default="neutral", index=True)
    emotion: Mapped[str] = mapped_column(String(32), default="neutral")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    semantic_version: Mapped[str | None] = mapped_column(String(160), nullable=True)
    mql: Mapped[dict] = mapped_column(JSON, default=dict)
    result_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    resolution: Mapped[str] = mapped_column(String(2000), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ExternalMessageLinkRecord(Base):
    __tablename__ = "external_message_links"

    link_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    app_id: Mapped[str] = mapped_column(String(160), index=True)
    external_conversation_id: Mapped[str] = mapped_column(String(160), index=True)
    external_message_id: Mapped[str] = mapped_column(String(160), index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    turn_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


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


class AnalysisRunRecord(Base):
    __tablename__ = "analysis_runs"

    analysis_run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    analysis_type: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    metric_key: Mapped[str] = mapped_column(String(160), index=True)
    object_id: Mapped[str] = mapped_column(String(160), index=True)
    steps: Mapped[list] = mapped_column(JSON, default=list)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


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


class SqlTemplateVersionRecord(Base):
    __tablename__ = "sql_template_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    template_key: Mapped[str] = mapped_column(String(160), index=True)
    version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class PipelineRecord(Base):
    __tablename__ = "pipelines"

    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    label: Mapped[str] = mapped_column(String(160), index=True)
    source: Mapped[str] = mapped_column(String(160), index=True)
    target: Mapped[str] = mapped_column(String(160))
    mode: Mapped[str] = mapped_column(String(32))
    cursor_field: Mapped[str | None] = mapped_column(String(160), nullable=True)
    steps: Mapped[list] = mapped_column(JSON, default=list)
    published: Mapped[bool] = mapped_column(default=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class PipelineRunRecord(Base):
    __tablename__ = "pipeline_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    pipeline_key: Mapped[str] = mapped_column(String(160), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict] = mapped_column(JSON)


class PythonExtensionRecord(Base):
    __tablename__ = "python_extensions"

    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    label: Mapped[str] = mapped_column(String(160), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    code: Mapped[str] = mapped_column(String)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30)
    memory_mb: Mapped[int] = mapped_column(Integer, default=256)
    published: Mapped[bool] = mapped_column(default=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class PythonExtensionRunRecord(Base):
    __tablename__ = "python_extension_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    extension_key: Mapped[str] = mapped_column(String(160), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    input_data: Mapped[dict] = mapped_column(JSON)
    output_data: Mapped[dict] = mapped_column(JSON)
    logs: Mapped[str] = mapped_column(String, default="")
    error: Mapped[str | None] = mapped_column(String(2000), nullable=True)


class KnowledgeBaseRecord(Base):
    __tablename__ = "knowledge_bases"

    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    configuration: Mapped[dict] = mapped_column(JSON, default=dict)
    secret_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    enabled: Mapped[bool] = mapped_column(default=True, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class KnowledgeDocumentRecord(Base):
    __tablename__ = "knowledge_documents"

    document_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    knowledge_base_key: Mapped[str] = mapped_column(String(160), index=True)
    title: Mapped[str] = mapped_column(String(500), index=True)
    source_uri: Mapped[str] = mapped_column(String(1000))
    content: Mapped[str] = mapped_column(String)
    document_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    checksum: Mapped[str] = mapped_column(String(64), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class KnowledgeChunkRecord(Base):
    __tablename__ = "knowledge_chunks"

    chunk_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(64), index=True)
    knowledge_base_key: Mapped[str] = mapped_column(String(160), index=True)
    position: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(String)
    chunk_metadata: Mapped[dict] = mapped_column(JSON, default=dict)


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
