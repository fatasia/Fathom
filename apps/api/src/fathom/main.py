from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from fathom.adapters.storage.database import (
    create_session_factory,
    seed_demo_object_instances,
    seed_demo_observations,
    seed_sql_templates,
)
from fathom.adapters.storage.semantic_repository import SqlSemanticRepository
from fathom.application.agent_mesh import AgentMeshRuntime
from fathom.application.contract_loader import load_contracts
from fathom.application.data_sources import DataSourceService
from fathom.application.evaluation import EvaluationService
from fathom.application.governance import GovernanceService
from fathom.application.ingestion import IngestionService
from fathom.application.model_gateway import ModelGatewayService
from fathom.application.object_context import ObjectContextService
from fathom.application.pipelines import PipelineService
from fathom.application.platform_tools import BackupService, SqlTemplateService
from fathom.application.query_service import QueryService
from fathom.application.security import (
    AccessController,
    AuditService,
    authentication_error,
    elapsed_ms,
    request_timer,
)
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
        seed_demo_observations(session_factory)
        seed_demo_object_instances(session_factory)
        seed_sql_templates(session_factory)
        app.state.settings = active_settings
        app.state.session_factory = session_factory
        app.state.semantic_repository = repository
        app.state.relations = [
            relation for contract in contracts for relation in contract.relations
        ]
        app.state.query_service = QueryService(session_factory, repository)
        app.state.evaluation_service = EvaluationService(session_factory, app.state.query_service)
        app.state.governance_service = GovernanceService(session_factory)
        app.state.governance_service.seed()
        app.state.ingestion_service = IngestionService(session_factory)
        app.state.sql_template_service = SqlTemplateService(session_factory)
        app.state.backup_service = BackupService(active_settings)
        app.state.data_source_service = DataSourceService(session_factory)
        app.state.pipeline_service = PipelineService(session_factory)
        app.state.object_context_service = ObjectContextService(session_factory)
        app.state.agent_mesh_runtime = AgentMeshRuntime(
            session_factory,
            app.state.query_service,
            app.state.data_source_service,
        )
        app.state.model_gateway_service = ModelGatewayService(session_factory)
        app.state.model_gateway_service.seed_from_configuration(active_settings.model_gateway)
        app.state.audit_service = AuditService(session_factory)
        yield

    app = FastAPI(
        title="渊渟 FATHOM API",
        version="0.1.0",
        description="Industrial ontology, semantic query and agent harness core.",
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
            candidate = static_directory / path
            if path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(static_directory / "index.html")

    return app


app = create_app()
