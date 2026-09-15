from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from fathom.adapters.storage.database import (
    create_session_factory,
    seed_sql_templates,
)
from fathom.adapters.storage.semantic_repository import SqlSemanticRepository
from fathom.application.actions import ActionService
from fathom.application.agent_mesh import AgentMeshRuntime
from fathom.application.capability_registry import CapabilityRegistry
from fathom.application.connector_executor import ConnectorExecutor
from fathom.application.contract_loader import load_contracts
from fathom.application.conversations import ConversationService
from fathom.application.data_quality import DataQualityService
from fathom.application.data_sources import DataSourceService
from fathom.application.demo_data import (
    DEMO_DATASET_FILENAME,
    GOLDEN_QUESTIONS_FILENAME,
    load_demo_dataset,
    load_golden_question_set,
    seed_demo_dataset,
)
from fathom.application.diagnosis import DiagnosisService
from fathom.application.evaluation import EvaluationService
from fathom.application.feedback import FeedbackService
from fathom.application.governance import GovernanceService
from fathom.application.ingestion import IngestionService
from fathom.application.knowledge import KnowledgeService
from fathom.application.lineage import LineageService
from fathom.application.mapping_registry import MappingRegistry
from fathom.application.model_gateway import ModelGatewayService
from fathom.application.object_context import ObjectContextService
from fathom.application.object_identities import ObjectIdentityService
from fathom.application.physical_planner import PhysicalPlanner
from fathom.application.pipelines import PipelineService
from fathom.application.platform_tools import BackupService, SqlTemplateService
from fathom.application.policy_enforcement import PolicyEnforcementPoint
from fathom.application.python_extensions import PythonExtensionService
from fathom.application.query_service import QueryService
from fathom.application.requirements import RequirementService
from fathom.application.reverse_mapping import ReverseMappingService
from fathom.application.runtime_evaluation import RuntimeEvaluationService
from fathom.application.security import (
    AccessController,
    AuditService,
    authentication_error,
    elapsed_ms,
    request_timer,
)
from fathom.application.semantic_extraction import SemanticExtractionService
from fathom.application.semantic_runtime import SemanticRuntimeService
from fathom.config import Settings, settings
from fathom.interfaces.agent_gateway import router as agent_gateway_router
from fathom.interfaces.api import router


def create_app(app_settings: Settings | None = None) -> FastAPI:
    active_settings = app_settings or settings

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        session_factory = create_session_factory(active_settings)
        repository = SqlSemanticRepository(session_factory)
        contracts = load_contracts(active_settings.semantic_directory)
        if not contracts:
            raise RuntimeError(
                f"No semantic contracts found in {active_settings.semantic_directory}"
            )
        for contract in contracts:
            repository.replace_contract(contract)
        golden_set = load_golden_question_set(
            active_settings.seed_directory / GOLDEN_QUESTIONS_FILENAME
        )
        if active_settings.environment == "test":
            seed_demo_dataset(
                session_factory,
                load_demo_dataset(active_settings.seed_directory / DEMO_DATASET_FILENAME),
            )
        seed_sql_templates(session_factory)
        app.state.settings = active_settings
        app.state.session_factory = session_factory
        app.state.semantic_repository = repository
        app.state.golden_question_set = golden_set
        app.state.relations = [
            relation for contract in contracts for relation in contract.relations
        ]
        app.state.model_gateway_service = ModelGatewayService(session_factory)
        app.state.model_gateway_service.seed_from_configuration(active_settings.model_gateway)
        app.state.governance_service = GovernanceService(
            session_factory, suite_key=golden_set.suite_key
        )
        app.state.governance_service.seed()
        app.state.data_source_service = DataSourceService(session_factory)
        app.state.lineage_service = LineageService(session_factory)
        app.state.mapping_registry = MappingRegistry(
            session_factory, app.state.data_source_service
        )
        app.state.policy_enforcement = PolicyEnforcementPoint(
            session_factory,
            max_rows=active_settings.runtime_max_rows,
            timeout_seconds=active_settings.runtime_query_timeout_seconds,
        )
        app.state.data_quality_service = DataQualityService(session_factory)
        app.state.object_identity_service = ObjectIdentityService(
            session_factory,
            app.state.data_source_service,
            app.state.lineage_service,
        )
        app.state.semantic_runtime_service = SemanticRuntimeService(
            session_factory,
            repository,
            app.state.data_source_service,
            app.state.mapping_registry,
            app.state.policy_enforcement,
            PhysicalPlanner(),
            ConnectorExecutor(app.state.data_source_service),
            app.state.data_quality_service,
            app.state.lineage_service,
            app.state.object_identity_service,
        )
        app.state.requirement_service = RequirementService(
            session_factory, repository, app.state.lineage_service
        )
        app.state.action_service = ActionService(session_factory)
        app.state.capability_registry = CapabilityRegistry(
            session_factory,
            app.state.semantic_runtime_service,
            app.state.data_source_service,
            app.state.lineage_service,
            app.state.policy_enforcement,
            app.state.action_service,
            repository,
        )
        app.state.capability_registry.seed()
        app.state.reverse_mapping_service = ReverseMappingService(
            app.state.data_source_service, repository
        )
        app.state.runtime_evaluation_service = RuntimeEvaluationService(
            session_factory, app.state.semantic_runtime_service
        )
        app.state.semantic_extraction_service = SemanticExtractionService(
            session_factory,
            app.state.data_source_service,
            app.state.governance_service,
            app.state.model_gateway_service,
        )
        app.state.knowledge_service = KnowledgeService(
            session_factory, app.state.semantic_extraction_service
        )
        app.state.feedback_service = FeedbackService(session_factory)
        app.state.conversation_service = ConversationService(
            session_factory, app.state.feedback_service
        )
        app.state.diagnosis_service = DiagnosisService(session_factory)
        app.state.query_service = QueryService(
            session_factory,
            repository,
            app.state.knowledge_service,
            app.state.model_gateway_service,
            app.state.diagnosis_service,
            app.state.semantic_runtime_service,
        )
        app.state.evaluation_service = EvaluationService(
            session_factory, app.state.query_service, golden_set
        )
        app.state.ingestion_service = IngestionService(session_factory)
        app.state.sql_template_service = SqlTemplateService(session_factory)
        app.state.backup_service = BackupService(active_settings)
        app.state.pipeline_service = PipelineService(session_factory)
        app.state.python_extension_service = PythonExtensionService(session_factory)
        app.state.object_context_service = ObjectContextService(session_factory)
        app.state.agent_mesh_runtime = AgentMeshRuntime(
            session_factory,
            app.state.query_service,
            app.state.data_source_service,
            app.state.semantic_extraction_service,
        )
        app.state.audit_service = AuditService(session_factory)
        yield

    app = FastAPI(
        title="渊渟 FATHOM API",
        version="0.1.0",
        description="Ontology, semantic query and agent harness core.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    access_controller = AccessController(active_settings)

    @app.middleware("http")
    async def security_and_audit(request, call_next):
        path = request.url.path
        public = (
            request.method == "OPTIONS"
            or path == "/api/v1/health"
            or path.startswith("/assets/")
            or not path.startswith(("/api/", "/a2a", "/mcp"))
        )
        identity = (
            ("public", "viewer", set()) if public else access_controller.authenticate(request)
        )
        if identity is None:
            return authentication_error(401, "缺少或无效的访问令牌")
        principal, role, authorized_objects = identity
        if not public and not access_controller.authorize(role, request.method, path):
            return authentication_error(403, "当前角色无权执行此操作")
        request.state.principal = principal
        request.state.role = role
        request.state.authorized_objects = authorized_objects
        started = request_timer()
        response = await call_next(request)
        if request.method != "GET" and hasattr(request.app.state, "audit_service"):
            request.app.state.audit_service.record(
                principal=principal,
                role=role,
                method=request.method,
                path=path,
                status_code=response.status_code,
                duration_ms=elapsed_ms(started),
                client=request.client.host if request.client else "unknown",
            )
        return response

    app.include_router(router)
    app.include_router(agent_gateway_router)

    static_directory = Path(__file__).parent / "interfaces" / "static"
    if static_directory.exists():
        app.mount("/assets", StaticFiles(directory=static_directory / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str) -> FileResponse:
            # The SPA fallback must not swallow API paths: an unknown /api route
            # has to stay a 404 so callers see a real error instead of HTML.
            if path.startswith(("api/", "a2a", "mcp")):
                raise HTTPException(status_code=404, detail="Not Found")
            candidate = static_directory / path
            if path and candidate.is_file() and candidate.resolve().is_relative_to(
                static_directory.resolve()
            ):
                return FileResponse(candidate)
            return FileResponse(static_directory / "index.html")

    return app


app = create_app()
