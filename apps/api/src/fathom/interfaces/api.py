from __future__ import annotations

import base64
import io
import json
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Annotated
from xml.etree import ElementTree

import yaml
from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fathom.application.agent_mesh import AgentRunInput, agent_mesh_overview
from fathom.application.capabilities import detect_capabilities
from fathom.application.conversations import ConversationCreate, ConversationRename
from fathom.application.data_sources import DataSourceInput, connector_catalog
from fathom.application.feedback import (
    ExternalFeedbackInput,
    ExternalMessageLinkInput,
    FeedbackInput,
    FeedbackResolution,
)
from fathom.application.governance import GovernanceDecision, SemanticAssetProposal
from fathom.application.ingestion import (
    EventInput,
    MetricObservationInput,
    ObjectInstanceInput,
    RelationInput,
)
from fathom.application.knowledge import (
    KnowledgeBaseInput,
    KnowledgeDocumentInput,
    KnowledgeSearchInput,
)
from fathom.application.model_gateway import (
    MODEL_ROLES,
    PROVIDER_PROFILES,
    ModelProviderInput,
    ModelRouteInput,
)
from fathom.application.platform_tools import (
    RestoreRequest,
    SemanticImportRequest,
    SqlPreviewRequest,
    SqlTemplateInput,
    SqlTemplateService,
    export_dataset_csv,
    inspect_import,
)
from fathom.application.python_extensions import (
    PythonExtensionInput,
    PythonExtensionService,
    PythonRunInput,
)
from fathom.domains.pipelines.models import PipelineDefinition
from fathom.domains.query.models import AskRequest, AskResponse, QueryAttachment
from fathom.domains.runtime.models import (
    CapabilityCompileInput,
    CapabilityInput,
    CapabilityInvocationInput,
    DataQualityContractInput,
    DependencyEdgeInput,
    GoldenCaseInput,
    LegacyAssetExtractInput,
    MappingContractInput,
    ObjectIdentityInput,
    RequirementEvidenceInput,
    RequirementExploreInput,
    RequirementReviewInput,
    ReverseMappingInput,
    RuntimeQueryInput,
)
from fathom.domains.semantics.models import DomainContract

router = APIRouter(prefix="/api/v1")


def _authorized_objects(request: Request) -> set[str] | None:
    return getattr(request.state, "authorized_objects", None)


def _runtime_identity(request: Request) -> dict[str, str]:
    return {
        "principal": str(getattr(request.state, "principal", "local")),
        "role": str(getattr(request.state, "role", "admin")),
    }


def _ensure_object_access(request: Request, object_id: str) -> None:
    allowed = _authorized_objects(request)
    if allowed is not None and object_id not in allowed:
        raise HTTPException(status_code=403, detail=f"无权访问业务对象：{object_id}")


def _ensure_objects_access(request: Request, object_ids: set[str]) -> None:
    allowed = _authorized_objects(request)
    denied = sorted(object_ids - allowed) if allowed is not None else []
    if denied:
        raise HTTPException(
            status_code=403,
            detail=f"无权写入业务对象：{', '.join(denied[:10])}",
        )


@router.get("/agent-mesh/overview")
def get_agent_mesh_overview() -> dict:
    return agent_mesh_overview()


@router.get("/agent-mesh/runs")
def list_agent_runs(request: Request, limit: int = 20) -> dict:
    return {"items": request.app.state.agent_mesh_runtime.list_recent(limit)}


@router.get("/agent-mesh/runs/{run_id}")
def get_agent_run(run_id: str, request: Request) -> dict:
    result = request.app.state.agent_mesh_runtime.get(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return result


@router.post("/agent-mesh/runs")
def run_agent_flow(payload: AgentRunInput, request: Request) -> dict:
    try:
        return request.app.state.agent_mesh_runtime.run(
            payload, getattr(request.state, "authorized_objects", None)
        )
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/governance/evaluations/latest")
def latest_evaluation(request: Request) -> dict:
    report = request.app.state.evaluation_service.latest()
    return (
        {"status": "not_run", "report": None}
        if report is None
        else {
            "status": "completed",
            "report": report,
        }
    )


@router.get("/governance/golden-question-set")
def get_golden_question_set(request: Request) -> dict:
    return request.app.state.golden_question_set.catalog()


@router.post("/governance/evaluations")
def run_evaluation(request: Request) -> dict:
    return request.app.state.evaluation_service.run_certified_suite()


@router.get("/governance/changes")
def list_governance_changes(request: Request, status: str | None = None) -> dict:
    return {"items": request.app.state.governance_service.list(status)}


@router.post("/governance/asset-candidates")
def propose_semantic_asset(payload: SemanticAssetProposal, request: Request) -> dict:
    try:
        actor = getattr(request.state, "principal", "semantic_builder")
        return request.app.state.governance_service.propose_asset(payload, actor)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/governance/changes/{change_id}")
def get_governance_change(change_id: str, request: Request) -> dict:
    change = request.app.state.governance_service.get(change_id)
    if change is None:
        raise HTTPException(status_code=404, detail="语义变更不存在")
    return change


@router.post("/governance/changes/{change_id}/decision")
def decide_governance_change(change_id: str, payload: GovernanceDecision, request: Request) -> dict:
    try:
        return request.app.state.governance_service.decide(change_id, payload)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=f"语义变更不存在：{error}") from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/health")
def health(request: Request) -> dict:
    return {
        "status": "healthy",
        "name": request.app.state.settings.app_name,
        "version": "0.1.0",
    }


@router.get("/system/capabilities")
def capabilities(request: Request) -> dict:
    return detect_capabilities(request.app.state.settings)


@router.get("/integrations/dify/status")
def dify_integration_status(request: Request) -> dict:
    console_base_url = request.app.state.settings.dify_console_url.rstrip("/")
    service_running = False
    setup_completed = False
    message = "Dify 未启动"
    try:
        setup_url = f"{console_base_url}/console/api/setup"
        with urllib.request.urlopen(setup_url, timeout=1.2) as response:
            payload = json.load(response)
        service_running = True
        setup_completed = payload.get("step") == "finished"
        message = "Dify 已启动；点击打开工具页" if setup_completed else "Dify 等待初始化"
    except (OSError, ValueError, urllib.error.URLError):
        pass
    return {
        "service_running": service_running,
        "setup_completed": setup_completed,
        "console_url": f"{console_base_url}/tools",
        "schema_url": "/api/v1/integrations/dify/openapi.yaml",
        "message": message,
    }


@router.get("/integrations/dify/openapi.yaml", response_class=FileResponse)
def download_dify_openapi() -> FileResponse:
    schema_path = (
        Path(__file__).resolve().parents[5] / "integrations" / "dify" / "fathom-openapi.yaml"
    )
    if not schema_path.is_file():
        raise HTTPException(status_code=404, detail="FATHOM 工具配置不存在")
    return FileResponse(
        schema_path,
        media_type="application/yaml",
        filename="fathom-openapi.yaml",
    )


@router.get("/system/configuration")
def effective_configuration(request: Request) -> dict:
    active = request.app.state.settings
    return {
        "precedence": ["environment", "yaml", "web", "default"],
        "config_file": str(active.config_file) if active.config_file else None,
        "effective": {
            "environment": active.environment,
            "storage_profile": active.storage_profile,
            "database_url": active.database_url,
            "semantic_directory": str(active.semantic_directory),
            "enable_duckdb": active.enable_duckdb,
            "enable_vector_search": active.enable_vector_search,
            "duckdb_memory_limit": active.duckdb_memory_limit,
            "duckdb_threads": active.duckdb_threads,
            "auth_enabled": active.auth_enabled,
            "auth_principal_count": len(active.auth_principals),
        },
        "note": "密钥仅显示引用，不通过该接口返回明文",
    }


@router.get("/system/audit-events")
def list_audit_events(request: Request, limit: int = 100) -> dict:
    return {"items": request.app.state.audit_service.list(limit)}


@router.get("/model-gateway/presets")
def model_gateway_presets() -> dict:
    return {"providers": PROVIDER_PROFILES, "roles": MODEL_ROLES}


@router.get("/model-gateway/providers")
def list_model_providers(request: Request) -> dict:
    return {"items": request.app.state.model_gateway_service.list_providers()}


@router.put("/model-gateway/providers/{provider_key}")
def save_model_provider(provider_key: str, payload: ModelProviderInput, request: Request) -> dict:
    if provider_key != payload.key:
        raise HTTPException(status_code=400, detail="Path key and payload key must match")
    try:
        return request.app.state.model_gateway_service.save_provider(payload)
    except (ValueError, RuntimeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/model-gateway/providers/{provider_key}/probe")
def probe_model_provider(provider_key: str, request: Request) -> dict:
    try:
        return request.app.state.model_gateway_service.probe(provider_key)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/multimodal/inspect")
async def inspect_multimodal_context(
    request: Request,
    file: Annotated[UploadFile, File(...)],
    object_id: str,
    prompt: str = "识别图像中的设备、状态、异常和可见文字，并说明不确定项。",
) -> dict:
    if file.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(status_code=422, detail="支持 JPEG、PNG、WebP 图像")
    content = await file.read(5 * 1024 * 1024 + 1)
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="单张图像不能超过 5MB")
    try:
        _ensure_object_access(request, object_id)
        context = request.app.state.object_context_service.get_context(object_id)
        image_url = f"data:{file.content_type};base64," + base64.b64encode(content).decode("ascii")
        result = request.app.state.model_gateway_service.invoke_role(
            "vision",
            f"业务对象上下文：{json.dumps(context, ensure_ascii=False)}\n任务：{prompt}",
            [image_url],
        )
        return {
            "status": "completed",
            "object_id": object_id,
            "analysis": result["text"],
            "model": result["model"],
            "provider_key": result["provider_key"],
            "mode": result["mode"],
            "note": "视觉结果作为候选证据，不自动修改生产本体。",
        }
    except LookupError as error:
        raise HTTPException(status_code=404, detail=f"业务对象不存在：{error}") from error
    except (ValueError, OSError, urllib.error.URLError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/model-gateway/routes")
def list_model_routes(request: Request) -> dict:
    return {"items": request.app.state.model_gateway_service.list_routes()}


@router.put("/model-gateway/routes/{role}")
def save_model_route(role: str, payload: ModelRouteInput, request: Request) -> dict:
    if role != payload.role:
        raise HTTPException(status_code=400, detail="Path role and payload role must match")
    try:
        return request.app.state.model_gateway_service.save_route(payload)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/semantics/assets")
def list_semantic_assets(request: Request, query: str = "", limit: int = 50) -> dict:
    repository = request.app.state.semantic_repository
    assets = (
        repository.search(query, min(limit, 100)) if query else repository.list_assets()[:limit]
    )
    return {"items": [asset.model_dump(mode="json") for asset in assets], "total": len(assets)}


@router.get("/semantics/overview")
def semantic_overview(request: Request) -> dict:
    repository = request.app.state.semantic_repository
    assets = repository.list_assets()
    counts: dict[str, int] = {}
    for asset in assets:
        counts[asset.kind.value] = counts.get(asset.kind.value, 0) + 1
    return {
        "domain": "manufacturing.execution",
        "version": "0.1.0",
        "status": "published",
        "counts": counts,
        "assets": [asset.model_dump(mode="json") for asset in assets],
        "relations": [relation.model_dump(mode="json") for relation in request.app.state.relations],
    }


@router.get("/ontology/instances")
def list_object_instances(
    request: Request, object_type: str | None = None, limit: int = 100
) -> dict:
    items = request.app.state.object_context_service.list(object_type, limit)
    allowed = _authorized_objects(request)
    if allowed is not None:
        items = [item for item in items if item["object_id"] in allowed]
    return {"items": items, "total": len(items)}


@router.post("/ingestion/objects")
def ingest_objects(payload: list[ObjectInstanceInput], request: Request) -> dict:
    _ensure_objects_access(request, {item.object_id for item in payload})
    try:
        return request.app.state.ingestion_service.upsert_objects(payload)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/ingestion/relations")
def ingest_relations(payload: list[RelationInput], request: Request) -> dict:
    _ensure_objects_access(
        request,
        {object_id for item in payload for object_id in (item.source_id, item.target_id)},
    )
    try:
        return request.app.state.ingestion_service.add_relations(payload)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/ingestion/metric-observations")
def ingest_metric_observations(payload: list[MetricObservationInput], request: Request) -> dict:
    _ensure_objects_access(request, {item.object_id for item in payload})
    try:
        return request.app.state.ingestion_service.upsert_observations(payload)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/ingestion/events")
def ingest_events(payload: list[EventInput], request: Request) -> dict:
    _ensure_objects_access(request, {item.object_id for item in payload})
    try:
        return request.app.state.ingestion_service.add_events(payload)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/ontology/instances/{object_id}/context")
def get_object_context(object_id: str, request: Request) -> dict:
    _ensure_object_access(request, object_id)
    try:
        return request.app.state.object_context_service.get_context(object_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=f"Object not found: {error}") from error


@router.get("/query/conversations")
def list_conversations(request: Request, limit: int = 100) -> dict:
    return {"items": request.app.state.conversation_service.list(limit)}


@router.post("/query/conversations")
def create_conversation(payload: ConversationCreate, request: Request) -> dict:
    return request.app.state.conversation_service.create(payload.title)


@router.get("/query/conversations/{conversation_id}")
def get_conversation(conversation_id: str, request: Request) -> dict:
    try:
        return request.app.state.conversation_service.get(conversation_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.put("/query/conversations/{conversation_id}")
def rename_conversation(
    conversation_id: str,
    payload: ConversationRename,
    request: Request,
) -> dict:
    try:
        return request.app.state.conversation_service.rename(conversation_id, payload.title)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.delete("/query/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: str, request: Request) -> Response:
    try:
        request.app.state.conversation_service.delete(conversation_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return Response(status_code=204)


@router.post("/query/conversations/{conversation_id}/turns/{turn_id}/feedback")
def submit_turn_feedback(
    conversation_id: str,
    turn_id: str,
    payload: FeedbackInput,
    request: Request,
) -> dict:
    try:
        return request.app.state.feedback_service.submit_turn(
            conversation_id, turn_id, payload
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/feedback")
def list_feedback(request: Request, status: str | None = None, limit: int = 100) -> dict:
    return {"items": request.app.state.feedback_service.list(status=status, limit=limit)}


@router.post("/feedback/{feedback_id}/resolve")
def resolve_feedback(
    feedback_id: str, payload: FeedbackResolution, request: Request
) -> dict:
    try:
        return request.app.state.feedback_service.resolve(feedback_id, payload)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/integrations/external/message-links")
def link_external_message(payload: ExternalMessageLinkInput, request: Request) -> dict:
    try:
        return request.app.state.feedback_service.link_external(payload)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/integrations/external/feedback/import")
def import_external_feedback(payload: ExternalFeedbackInput, request: Request) -> dict:
    return request.app.state.feedback_service.import_external(payload)


@router.get("/semantic-extraction/runs")
def list_semantic_extraction_runs(request: Request, limit: int = 100) -> dict:
    return {"items": request.app.state.semantic_extraction_service.list_runs(limit)}


@router.post("/data-sources/{source_key}/extract")
def extract_data_source_semantics(source_key: str, request: Request) -> dict:
    try:
        return request.app.state.semantic_extraction_service.extract_data_source(source_key)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/analysis-runs/{analysis_run_id}")
def get_analysis_run(analysis_run_id: str, request: Request) -> dict:
    result = request.app.state.diagnosis_service.get(analysis_run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="分析运行不存在")
    return result


@router.post("/query/ask", response_model=AskResponse)
def ask_data(payload: AskRequest, request: Request) -> AskResponse:
    try:
        result = request.app.state.query_service.ask(
            payload,
            _authorized_objects(request),
            **_runtime_identity(request),
        )
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    if payload.conversation_id:
        try:
            request.app.state.conversation_service.record_turn(
                payload.conversation_id, payload, result
            )
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
    return result


@router.post("/query/answer", response_class=PlainTextResponse)
def ask_data_text(payload: AskRequest, request: Request) -> PlainTextResponse:
    """Return only the user-facing answer for chat tools and simple workflows."""
    try:
        result = request.app.state.query_service.ask(
            payload,
            _authorized_objects(request),
            **_runtime_identity(request),
        )
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    if payload.conversation_id:
        try:
            request.app.state.conversation_service.record_turn(
                payload.conversation_id, payload, result
            )
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
    return PlainTextResponse(
        result.answer,
        headers={
            "X-Fathom-Status": result.status,
            "X-Fathom-Trace-Id": result.trace_id,
        },
    )


@router.post("/query/stream")
def ask_data_stream(payload: AskRequest, request: Request) -> StreamingResponse:
    """Stream progress, answer deltas and the final evidence-bearing result over SSE."""

    if payload.conversation_id:
        try:
            request.app.state.conversation_service.get(payload.conversation_id)
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    def event_stream():
        progress = [
            ("acquire", "正在理解问题与业务范围"),
            ("build", "正在绑定语义、指标与权限"),
        ]
        for stage, message in progress:
            data = json.dumps({"stage": stage, "message": message}, ensure_ascii=False)
            yield f"event: progress\ndata: {data}\n\n"
        try:
            result = request.app.state.query_service.ask(
                payload,
                _authorized_objects(request),
                **_runtime_identity(request),
            )
        except PermissionError as error:
            data = json.dumps({"message": str(error)}, ensure_ascii=False)
            yield f"event: error\ndata: {data}\n\n"
            return
        data = json.dumps(
            {"stage": "compute", "message": "可信结果已生成，正在组织回答"},
            ensure_ascii=False,
        )
        yield f"event: progress\ndata: {data}\n\n"
        for index in range(0, len(result.answer), 18):
            delta = json.dumps({"text": result.answer[index : index + 18]}, ensure_ascii=False)
            yield f"event: delta\ndata: {delta}\n\n"
        if payload.conversation_id:
            request.app.state.conversation_service.record_turn(
                payload.conversation_id, payload, result
            )
        complete = json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
        yield f"event: complete\ndata: {complete}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/query/attachments")
async def prepare_query_attachment(file: Annotated[UploadFile, File(...)]) -> QueryAttachment:
    """Validate and extract a lightweight chat attachment before it enters a prompt."""

    filename = Path(file.filename or "attachment").name
    suffix = Path(filename).suffix.casefold()
    content = await file.read(8 * 1024 * 1024 + 1)
    if len(content) > 8 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="单个附件不能超过 8 MB")
    content_type = file.content_type or "application/octet-stream"
    if content_type in {"image/jpeg", "image/png", "image/webp"}:
        encoded = base64.b64encode(content).decode("ascii")
        return QueryAttachment(
            name=filename,
            content_type=content_type,
            data_url=f"data:{content_type};base64,{encoded}",
        )

    text_suffixes = {".txt", ".md", ".csv", ".json", ".jsonl", ".yaml", ".yml"}
    try:
        if suffix in text_suffixes:
            extracted = content.decode("utf-8-sig")
        elif suffix == ".pdf":
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(content))
            if len(reader.pages) > 100:
                raise HTTPException(status_code=422, detail="PDF 最多支持 100 页")
            extracted = "\n\n".join(page.extract_text() or "" for page in reader.pages)
        elif suffix == ".docx":
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                document = archive.read("word/document.xml")
            root = ElementTree.fromstring(document)  # noqa: S314
            extracted = "\n".join(text for text in root.itertext() if text.strip())
        else:
            raise HTTPException(
                status_code=415,
                detail="支持图片、TXT、Markdown、CSV、JSON、YAML、PDF 和 DOCX",
            )
    except (UnicodeDecodeError, zipfile.BadZipFile, KeyError, ValueError) as error:
        raise HTTPException(status_code=422, detail=f"附件内容无法读取：{filename}") from error
    extracted = extracted.strip()
    if not extracted:
        raise HTTPException(status_code=422, detail="附件中没有可读取的文本")
    if len(extracted) > 200_000:
        extracted = extracted[:200_000] + "\n[内容已截断]"
    return QueryAttachment(name=filename, content_type=content_type, text=extracted)


@router.get("/tools/sql-templates")
def list_sql_templates(request: Request) -> dict:
    return {"items": request.app.state.sql_template_service.list()}


@router.post("/tools/sql-templates/validate")
def validate_sql_template(payload: SqlTemplateInput) -> dict:
    return SqlTemplateService.validate(payload.sql_text, payload.dialect, payload.parameters)


@router.put("/tools/sql-templates/{template_key}")
def save_sql_template(template_key: str, payload: SqlTemplateInput, request: Request) -> dict:
    if template_key != payload.key:
        raise HTTPException(status_code=400, detail="Path key and payload key must match")
    try:
        return request.app.state.sql_template_service.save(payload)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.delete("/tools/sql-templates/{template_key}", status_code=204)
def delete_sql_template(template_key: str, request: Request) -> Response:
    try:
        request.app.state.sql_template_service.delete(template_key)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return Response(status_code=204)


@router.get("/tools/sql-templates/{template_key}/versions")
def list_sql_template_versions(template_key: str, request: Request) -> dict:
    return {"items": request.app.state.sql_template_service.versions(template_key)}


@router.post("/tools/sql-templates/{template_key}/versions/{version}/restore")
def restore_sql_template_version(template_key: str, version: int, request: Request) -> dict:
    try:
        return request.app.state.sql_template_service.restore_version(template_key, version)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/tools/sql-templates/{template_key}/preview")
def preview_sql_template(
    template_key: str, payload: SqlPreviewRequest, request: Request
) -> dict:
    try:
        return request.app.state.sql_template_service.preview(
            template_key, payload.parameters, payload.limit
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/system/backups")
def list_backups(request: Request) -> dict:
    return {"items": request.app.state.backup_service.list()}


@router.post("/system/backups")
def create_backup(request: Request) -> dict:
    try:
        return request.app.state.backup_service.create()
    except (RuntimeError, OSError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/system/backups/{backup_name}")
def download_backup(backup_name: str, request: Request) -> FileResponse:
    try:
        path = request.app.state.backup_service.resolve(backup_name)
    except (ValueError, FileNotFoundError) as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return FileResponse(path, filename=path.name, media_type="application/zip")


@router.post("/system/backups/{backup_name}/restore")
def restore_backup(backup_name: str, payload: RestoreRequest, request: Request) -> dict:
    try:
        return request.app.state.backup_service.restore(backup_name, payload.confirmation)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (ValueError, RuntimeError, OSError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/semantics/export")
def export_semantics(request: Request) -> Response:
    buffer = io.BytesIO()
    semantic_directory: Path = request.app.state.settings.semantic_directory
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        manifest = {
            "format": "fathom-semantics/v1",
            "files": [],
        }
        for path in semantic_directory.glob("**/*.yaml"):
            name = path.relative_to(semantic_directory).as_posix()
            archive.write(path, name)
            manifest["files"].append(name)
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="fathom-semantics.zip"'},
    )


@router.get("/exports/{dataset}.csv")
def export_dataset(dataset: str, request: Request, limit: int = 100_000) -> Response:
    try:
        content = export_dataset_csv(request.app.state.session_factory, dataset, limit)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="fathom-{dataset}.csv"'},
    )


@router.post("/imports/preview")
async def preview_import(file: Annotated[UploadFile, File(...)]) -> dict:
    content = await file.read()
    try:
        return inspect_import(file.filename or "upload", content)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/semantics/import")
def import_semantics(payload: SemanticImportRequest, request: Request) -> dict:
    try:
        raw = yaml.safe_load(payload.content)
        contract = DomainContract.model_validate(raw)
    except (ValueError, yaml.YAMLError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    result = {
        "valid": True,
        "domain": contract.domain,
        "version": contract.version,
        "assets": len(contract.assets),
        "relations": len(contract.relations),
        "applied": False,
        "protective_backup": None,
    }
    if payload.apply:
        if request.app.state.settings.environment == "production":
            raise HTTPException(
                status_code=409,
                detail="生产环境禁止绕过候选、评测与审批直接导入语义",
            )
        protective = request.app.state.backup_service.create(
            reason=f"before-semantic-import:{contract.domain}@{contract.version}"
        )
        request.app.state.semantic_repository.replace_contract(contract)
        relations_by_key = {relation.key: relation for relation in request.app.state.relations}
        relations_by_key.update({relation.key: relation for relation in contract.relations})
        request.app.state.relations = list(relations_by_key.values())
        semantic_directory: Path = request.app.state.settings.semantic_directory.resolve()
        semantic_directory.mkdir(parents=True, exist_ok=True)
        safe_name = "".join(
            character if character.isalnum() or character in "._-" else "-"
            for character in contract.domain
        )
        target = (semantic_directory / f"{safe_name}.yaml").resolve()
        if target.parent != semantic_directory:
            raise HTTPException(status_code=400, detail="Invalid semantic domain path")
        temporary = target.with_suffix(".yaml.tmp")
        temporary.write_text(payload.content, encoding="utf-8")
        temporary.replace(target)
        result["applied"] = True
        result["protective_backup"] = protective["name"]
    return result


@router.get("/data-sources/types")
def list_data_source_types() -> dict:
    return {"items": connector_catalog()}


@router.get("/knowledge-bases")
def list_knowledge_bases(request: Request) -> dict:
    return {"items": request.app.state.knowledge_service.list_bases()}


@router.put("/knowledge-bases/{knowledge_base_key}")
def save_knowledge_base(
    knowledge_base_key: str, payload: KnowledgeBaseInput, request: Request
) -> dict:
    if knowledge_base_key != payload.key:
        raise HTTPException(status_code=400, detail="Path key and payload key must match")
    try:
        return request.app.state.knowledge_service.save_base(payload)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.delete("/knowledge-bases/{knowledge_base_key}", status_code=204)
def delete_knowledge_base(knowledge_base_key: str, request: Request) -> Response:
    try:
        request.app.state.knowledge_service.delete_base(knowledge_base_key)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return Response(status_code=204)


@router.post("/knowledge-bases/{knowledge_base_key}/test")
def test_knowledge_base(knowledge_base_key: str, request: Request) -> dict:
    try:
        return request.app.state.knowledge_service.test_base(knowledge_base_key)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (ValueError, OSError, urllib.error.URLError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/knowledge-bases/{knowledge_base_key}/documents")
def list_knowledge_documents(knowledge_base_key: str, request: Request) -> dict:
    try:
        return {
            "items": request.app.state.knowledge_service.list_documents(
                knowledge_base_key
            )
        }
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/knowledge-bases/{knowledge_base_key}/documents")
def ingest_knowledge_document(
    knowledge_base_key: str, payload: KnowledgeDocumentInput, request: Request
) -> dict:
    try:
        return request.app.state.knowledge_service.ingest_document(
            knowledge_base_key, payload
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/knowledge-bases/{knowledge_base_key}/documents/upload")
async def upload_knowledge_document(
    knowledge_base_key: str,
    file: Annotated[UploadFile, File(...)],
    request: Request,
) -> dict:
    filename = file.filename or "document.txt"
    suffix = Path(filename).suffix.casefold()
    if suffix not in {".txt", ".md", ".csv", ".json", ".jsonl", ".yaml", ".yml"}:
        raise HTTPException(
            status_code=422,
            detail="轻量内置库支持 TXT、Markdown、CSV、JSON、JSONL、YAML",
        )
    raw = await file.read(5_000_001)
    if len(raw) > 5_000_000:
        raise HTTPException(status_code=413, detail="单个知识文档不能超过 5 MB")
    try:
        content = raw.decode("utf-8-sig")
        payload = KnowledgeDocumentInput(
            title=Path(filename).stem,
            content=content,
            source_uri=f"upload://{filename}",
            metadata={"filename": filename, "content_type": file.content_type},
        )
        return request.app.state.knowledge_service.ingest_document(
            knowledge_base_key, payload
        )
    except UnicodeDecodeError as error:
        raise HTTPException(status_code=422, detail="文档必须使用 UTF-8 编码") from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.delete(
    "/knowledge-bases/{knowledge_base_key}/documents/{document_id}",
    status_code=204,
)
def delete_knowledge_document(
    knowledge_base_key: str, document_id: str, request: Request
) -> Response:
    try:
        request.app.state.knowledge_service.delete_document(
            knowledge_base_key, document_id
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return Response(status_code=204)


@router.post("/knowledge/search")
def search_knowledge(payload: KnowledgeSearchInput, request: Request) -> dict:
    try:
        return request.app.state.knowledge_service.search(payload)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=f"知识库不可用：{error}") from error


@router.get("/data-sources")
def list_data_sources(request: Request) -> dict:
    return {"items": request.app.state.data_source_service.list()}


@router.put("/data-sources/{source_key}")
def save_data_source(source_key: str, payload: DataSourceInput, request: Request) -> dict:
    if source_key != payload.key:
        raise HTTPException(status_code=400, detail="Path key and payload key must match")
    try:
        return request.app.state.data_source_service.save(payload)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/data-sources/{source_key}/test")
def test_data_source(source_key: str, request: Request) -> dict:
    try:
        return request.app.state.data_source_service.test(source_key)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/data-sources/{source_key}/discover")
def discover_data_source(source_key: str, request: Request) -> dict:
    try:
        return request.app.state.data_source_service.discover(source_key)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/data-sources/{source_key}/scaffold")
def scaffold_data_source(source_key: str, request: Request) -> dict:
    try:
        return request.app.state.data_source_service.scaffold(source_key)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/runtime/mappings")
def list_runtime_mappings(request: Request, metric_key: str | None = None) -> dict:
    return {"items": request.app.state.mapping_registry.list(metric_key)}


@router.put("/runtime/mappings/{mapping_key}/versions/{version}")
def save_runtime_mapping(
    mapping_key: str,
    version: int,
    payload: MappingContractInput,
    request: Request,
) -> dict:
    if payload.key != mapping_key or payload.version != version:
        raise HTTPException(status_code=409, detail="路径中的映射标识/版本与载荷不一致")
    try:
        return request.app.state.semantic_runtime_service.register_mapping(payload)
    except (LookupError, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/runtime/mappings/{mapping_key}/versions/{version}/compatibility")
def check_runtime_mapping(mapping_key: str, version: int, request: Request) -> dict:
    try:
        return request.app.state.mapping_registry.check_compatibility(mapping_key, version)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/runtime/mappings/{mapping_key}/versions/{version}/publish")
def publish_runtime_mapping(mapping_key: str, version: int, request: Request) -> dict:
    try:
        return request.app.state.semantic_runtime_service.publish_mapping(mapping_key, version)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/runtime/mappings/{mapping_key}/versions/{version}/rollback")
def rollback_runtime_mapping(mapping_key: str, version: int, request: Request) -> dict:
    try:
        return request.app.state.mapping_registry.rollback(mapping_key, version)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/runtime/query")
def execute_runtime_query(payload: RuntimeQueryInput, request: Request) -> dict:
    try:
        result = request.app.state.semantic_runtime_service.execute(
            payload.query,
            authorized_objects=_authorized_objects(request),
            **_runtime_identity(request),
        )
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except LookupError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return {
        "rows": result["rows"],
        "compiled": result["compiled"],
        "receipt": result["receipt"],
        "mapping": result["mapping"],
        "policy_decision": result["policy_decision"],
        "quality": result["quality"],
        "route_attempts": result["route_attempts"],
        "verification_status": result["verification_status"],
    }


@router.get("/runtime/receipts")
def list_runtime_receipts(request: Request, limit: int = 100) -> dict:
    return {"items": request.app.state.semantic_runtime_service.list_receipts(limit)}


@router.get("/runtime/requirements")
def list_runtime_requirements(request: Request) -> dict:
    return {"items": request.app.state.requirement_service.list()}


@router.post("/runtime/requirements")
def save_runtime_requirement(payload: RequirementEvidenceInput, request: Request) -> dict:
    return request.app.state.requirement_service.save(payload)


@router.post("/runtime/requirements/explore")
def explore_runtime_requirement(payload: RequirementExploreInput, request: Request) -> dict:
    return request.app.state.requirement_service.explore(payload)


@router.post("/runtime/requirements/{requirement_key}/review")
def review_runtime_requirement(
    requirement_key: str, payload: RequirementReviewInput, request: Request
) -> dict:
    try:
        return request.app.state.requirement_service.review(requirement_key, payload)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/runtime/object-identities")
def list_runtime_object_identities(
    request: Request,
    canonical_object_id: str | None = None,
    source_key: str | None = None,
) -> dict:
    return {
        "items": request.app.state.object_identity_service.list(
            canonical_object_id, source_key
        )
    }


@router.post("/runtime/object-identities")
def save_runtime_object_identity(payload: ObjectIdentityInput, request: Request) -> dict:
    try:
        return request.app.state.object_identity_service.save(payload)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/runtime/lineage")
def list_runtime_lineage(request: Request, node: str | None = None) -> dict:
    return {"items": request.app.state.lineage_service.list(node)}


@router.post("/runtime/lineage")
def save_runtime_lineage(payload: DependencyEdgeInput, request: Request) -> dict:
    return request.app.state.lineage_service.add(payload)


@router.get("/runtime/impact")
def get_runtime_impact(node: str, request: Request) -> dict:
    return request.app.state.lineage_service.impact(node)


@router.get("/runtime/quality-contracts")
def list_runtime_quality_contracts(request: Request) -> dict:
    return {"items": request.app.state.data_quality_service.list()}


@router.put("/runtime/quality-contracts/{contract_key}")
def save_runtime_quality_contract(
    contract_key: str, payload: DataQualityContractInput, request: Request
) -> dict:
    if payload.key != contract_key:
        raise HTTPException(status_code=409, detail="路径中的质量契约标识与载荷不一致")
    return request.app.state.data_quality_service.save(payload)


@router.get("/runtime/golden-cases")
def list_runtime_golden_cases(request: Request) -> dict:
    return {"items": request.app.state.runtime_evaluation_service.list_cases()}


@router.put("/runtime/golden-cases/{case_key}")
def save_runtime_golden_case(
    case_key: str, payload: GoldenCaseInput, request: Request
) -> dict:
    if payload.key != case_key:
        raise HTTPException(status_code=409, detail="路径中的黄金问题标识与载荷不一致")
    return request.app.state.runtime_evaluation_service.save_case(payload)


@router.post("/runtime/evaluations")
def run_runtime_evaluation(request: Request) -> dict:
    return request.app.state.runtime_evaluation_service.run()


@router.get("/runtime/capabilities")
def list_runtime_capabilities(request: Request, published_only: bool = True) -> dict:
    return {"items": request.app.state.capability_registry.list(published_only)}


@router.post("/runtime/capabilities/compile")
def compile_runtime_capability(payload: CapabilityCompileInput, request: Request) -> dict:
    try:
        return request.app.state.capability_registry.compile_metric(payload)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.put("/runtime/capabilities/{capability_key}")
def save_runtime_capability(
    capability_key: str, payload: CapabilityInput, request: Request
) -> dict:
    if payload.key != capability_key:
        raise HTTPException(status_code=409, detail="路径中的能力标识与载荷不一致")
    try:
        return request.app.state.capability_registry.save(payload)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/runtime/capabilities/{capability_key}/publish")
def publish_runtime_capability(capability_key: str, request: Request) -> dict:
    try:
        return request.app.state.capability_registry.publish(capability_key)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/runtime/capabilities/{capability_key}/invoke")
def invoke_runtime_capability(
    capability_key: str, payload: CapabilityInvocationInput, request: Request
) -> dict:
    try:
        return request.app.state.capability_registry.invoke(
            capability_key,
            payload.arguments,
            authorized_objects=_authorized_objects(request),
            approval_token=payload.approval_token,
            **_runtime_identity(request),
        )
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/runtime/reverse-mappings")
def propose_reverse_mappings(payload: ReverseMappingInput, request: Request) -> dict:
    try:
        return request.app.state.reverse_mapping_service.propose(payload)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/runtime/reverse-assets")
def extract_legacy_runtime_assets(
    payload: LegacyAssetExtractInput, request: Request
) -> dict:
    try:
        return request.app.state.reverse_mapping_service.extract_legacy(payload)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/runtime/actions")
def list_runtime_actions(request: Request, limit: int = 100) -> dict:
    return {"items": request.app.state.action_service.list(limit)}


@router.get("/pipelines/capabilities")
def pipeline_capabilities() -> dict:
    return {
        "engine": "duckdb_sql",
        "operations": [
            "rename",
            "cast",
            "filter",
            "derive",
            "deduplicate",
            "quality_check",
            "onn_map",
        ],
        "modes": ["preview", "full", "incremental"],
        "external_orchestrators": ["dbt", "DataWorks", "WeData", "Airflow"],
    }


@router.get("/pipelines")
def list_pipelines(request: Request) -> dict:
    return {"items": request.app.state.pipeline_service.list()}


@router.put("/pipelines/{pipeline_key}")
def save_pipeline(
    pipeline_key: str,
    payload: PipelineDefinition,
    request: Request,
    published: bool = False,
) -> dict:
    if pipeline_key != payload.key:
        raise HTTPException(status_code=400, detail="Path key and payload key must match")
    return request.app.state.pipeline_service.save(payload, published)


@router.delete("/pipelines/{pipeline_key}", status_code=204)
def delete_pipeline(pipeline_key: str, request: Request) -> Response:
    try:
        request.app.state.pipeline_service.delete(pipeline_key)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return Response(status_code=204)


@router.get("/pipeline-runs")
def list_pipeline_runs(
    request: Request, pipeline_key: str | None = None, limit: int = 50
) -> dict:
    return {"items": request.app.state.pipeline_service.runs(pipeline_key, limit)}


@router.post("/pipelines/validate")
def validate_pipeline(payload: PipelineDefinition) -> dict:
    return {
        "valid": True,
        "key": payload.key,
        "steps": len(payload.steps),
        "mode": payload.mode,
        "warnings": []
        if payload.mode != "full"
        else ["全量同步上线前需要设置行数、超时和资源预算"],
    }


@router.post("/pipelines/preview")
def preview_pipeline(payload: PipelineDefinition, request: Request, limit: int = 100) -> dict:
    try:
        return request.app.state.pipeline_service.preview(payload, limit)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=f"数据源不存在：{error}") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/python-extensions")
def list_python_extensions(request: Request) -> dict:
    return {"items": request.app.state.python_extension_service.list()}


@router.post("/python-extensions/validate")
def validate_python_extension(payload: PythonExtensionInput) -> dict:
    return PythonExtensionService.validate(payload.code)


@router.put("/python-extensions/{extension_key}")
def save_python_extension(
    extension_key: str, payload: PythonExtensionInput, request: Request
) -> dict:
    if extension_key != payload.key:
        raise HTTPException(status_code=400, detail="Path key and payload key must match")
    try:
        return request.app.state.python_extension_service.save(payload)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.delete("/python-extensions/{extension_key}", status_code=204)
def delete_python_extension(extension_key: str, request: Request) -> Response:
    try:
        request.app.state.python_extension_service.delete(extension_key)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return Response(status_code=204)


@router.post("/python-extensions/{extension_key}/runs")
def run_python_extension(
    extension_key: str, payload: PythonRunInput, request: Request
) -> dict:
    try:
        result = request.app.state.python_extension_service.run(
            extension_key, payload.input_data
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if result["status"] == "failed":
        raise HTTPException(status_code=422, detail=result["error"])
    return result


@router.get("/python-extension-runs")
def list_python_extension_runs(
    request: Request, extension_key: str | None = None, limit: int = 50
) -> dict:
    return {
        "items": request.app.state.python_extension_service.runs(extension_key, limit)
    }
