from __future__ import annotations

import base64
import io
import json
import urllib.error
import zipfile
from pathlib import Path
from typing import Annotated

import yaml
from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from fathom.application.agent_mesh import AgentRunInput, agent_mesh_overview
from fathom.application.capabilities import detect_capabilities
from fathom.application.data_sources import DataSourceInput, connector_catalog
from fathom.application.governance import GovernanceDecision, SemanticAssetProposal
from fathom.application.ingestion import (
    IndustrialEventInput,
    MetricObservationInput,
    ObjectInstanceInput,
    RelationInput,
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
    SqlTemplateInput,
    SqlTemplateService,
    export_dataset_csv,
    inspect_import,
)
from fathom.domains.pipelines.models import PipelineDefinition, PythonExtensionManifest
from fathom.domains.query.models import AskRequest, AskResponse
from fathom.domains.semantics.models import DomainContract

router = APIRouter(prefix="/api/v1")


def _authorized_objects(request: Request) -> set[str] | None:
    return getattr(request.state, "authorized_objects", None)


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
def ingest_events(payload: list[IndustrialEventInput], request: Request) -> dict:
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


@router.post("/query/ask", response_model=AskResponse)
def ask_data(payload: AskRequest, request: Request) -> AskResponse:
    try:
        return request.app.state.query_service.ask(
            payload, getattr(request.state, "authorized_objects", None)
        )
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error


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


@router.post("/python-extensions/validate")
def validate_python_extension(payload: PythonExtensionManifest) -> dict:
    warnings = []
    if payload.network_access:
        warnings.append("网络访问需要安全 Owner 单独审批")
    if payload.writable_paths:
        warnings.append("可写目录必须位于任务临时空间")
    return {
        "valid": True,
        "executable": payload.approved and not warnings,
        "sandbox": {
            "timeout_seconds": payload.timeout_seconds,
            "memory_mb": payload.memory_mb,
            "network_access": payload.network_access,
            "writable_paths": payload.writable_paths,
        },
        "warnings": warnings,
    }
