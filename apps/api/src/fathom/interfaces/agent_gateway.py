from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

router = APIRouter()

MCP_VERSION = "2025-11-25"


class JsonRpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: str | int | None = None
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


def _rpc_result(request_id: str | int | None, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _rpc_error(request_id: str | int | None, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _check_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if not origin:
        return
    hostname = urlparse(origin).hostname
    if hostname not in {"127.0.0.1", "localhost", "host.docker.internal"}:
        raise HTTPException(status_code=403, detail="MCP Origin is not allowed")


@router.get("/api/v1/agent-gateway/capabilities")
def agent_gateway_capabilities() -> dict[str, Any]:
    return {
        "positioning": "platform-neutral industrial semantic and agent access gateway",
        "protocols": [
            {"key": "openapi", "version": "3.1", "status": "ready"},
            {
                "key": "mcp",
                "version": MCP_VERSION,
                "transport": "streamable-http-json",
                "status": "ready",
            },
            {
                "key": "a2a",
                "version": "0.3.0",
                "transport": "json-rpc",
                "methods": ["message/send"],
                "status": "ready",
            },
        ],
        "consumers": [
            "OpenAPI tool clients",
            "MCP clients",
            "A2A clients",
            "workflow and agent platforms",
            "BI, digital twin and operations applications",
        ],
        "shared_controls": [
            "identity_scope",
            "ontology_validation",
            "metric_certification",
            "resource_budget",
            "evidence",
            "trace_id",
        ],
    }


@router.get("/.well-known/agent-card.json")
def a2a_agent_card(request: Request) -> dict[str, Any]:
    return {
        "protocolVersion": "0.3.0",
        "name": "渊渟 FATHOM Industrial Semantic Agent",
        "description": "受 ONN 与 ABC 约束的工业问数、语义检索和证据服务。",
        "url": str(request.base_url).rstrip("/") + "/a2a",
        "preferredTransport": "JSONRPC",
        "capabilities": {"streaming": False, "pushNotifications": False},
        "defaultInputModes": ["text/plain", "application/json"],
        "defaultOutputModes": ["text/plain", "application/json"],
        "skills": [
            {
                "id": "industrial-semantic-query",
                "name": "工业语义问数",
                "description": "查询认证指标并返回 ABC 计划、证据和 trace_id。",
                "tags": ["industrial", "ontology", "analytics", "evidence"],
                "examples": ["为什么一号线昨天订单达成率下降？"],
            }
        ],
    }


@router.post("/a2a")
def a2a_endpoint(payload: JsonRpcRequest, request: Request) -> dict[str, Any]:
    """Execute the synchronous A2A v0.3 message/send subset.

    FATHOM deliberately advertises neither streaming nor push notifications. This
    keeps the Lite runtime dependency-free while still giving any A2A client a
    standards-shaped, traceable query path.
    """
    if payload.method != "message/send":
        return _rpc_error(payload.id, -32601, f"Method not found: {payload.method}")

    message = payload.params.get("message")
    if not isinstance(message, dict):
        return _rpc_error(payload.id, -32602, "params.message must be an object")

    question = _a2a_text(message)
    if len(question) < 2:
        return _rpc_error(payload.id, -32602, "message must contain a text part")

    from fathom.domains.query.models import AskRequest

    try:
        response = request.app.state.query_service.ask(
            AskRequest(
                question=question,
                scope=_a2a_scope(message),
                semantic_version=message.get("metadata", {}).get("semanticVersion"),
            ),
            getattr(request.state, "authorized_objects", None),
        )
    except PermissionError as error:
        return _rpc_error(payload.id, -32003, str(error))
    except (LookupError, TypeError, ValueError) as error:
        return _rpc_error(payload.id, -32602, str(error))

    result = response.model_dump(mode="json")
    context_id = message.get("contextId") or str(uuid4())
    return _rpc_result(
        payload.id,
        {
            "kind": "message",
            "role": "agent",
            "messageId": str(uuid4()),
            "contextId": context_id,
            "parts": [
                {"kind": "text", "text": response.answer},
                {
                    "kind": "data",
                    "data": {
                        "status": response.status,
                        "plan": result["plan"],
                        "data": result["data"],
                        "evidence": result["evidence"],
                        "qualityWarnings": result["quality_warnings"],
                    },
                },
            ],
            "metadata": {
                "traceId": response.trace_id,
                "semanticVersion": response.semantic_version,
                "dataFreshness": response.data_freshness,
            },
        },
    )


def _a2a_text(message: dict[str, Any]) -> str:
    parts = message.get("parts", [])
    if not isinstance(parts, list):
        return ""
    return "\n".join(
        str(part.get("text", "")).strip()
        for part in parts
        if isinstance(part, dict) and part.get("kind") == "text" and part.get("text")
    ).strip()


def _a2a_scope(message: dict[str, Any]) -> dict[str, str]:
    metadata = message.get("metadata", {})
    if not isinstance(metadata, dict):
        return {}
    raw_scope = metadata.get("scope", {})
    if not isinstance(raw_scope, dict):
        return {}
    return {str(key): str(value) for key, value in raw_scope.items()}


@router.post("/mcp", response_model=None)
def mcp_endpoint(payload: JsonRpcRequest, request: Request) -> Response | dict[str, Any]:
    _check_origin(request)
    if payload.method == "notifications/initialized":
        return Response(status_code=202)
    if payload.method == "initialize":
        return _rpc_result(
            payload.id,
            {
                "protocolVersion": MCP_VERSION,
                "capabilities": {"tools": {"listChanged": False}, "resources": {}},
                "serverInfo": {"name": "fathom", "version": "0.1.0"},
                "instructions": "Use certified semantic tools; preserve evidence and trace_id.",
            },
        )
    if payload.method == "ping":
        return _rpc_result(payload.id, {})
    if payload.method == "tools/list":
        return _rpc_result(payload.id, {"tools": _mcp_tools()})
    if payload.method == "tools/call":
        return _call_mcp_tool(payload, request)
    if payload.method == "resources/list":
        return _rpc_result(
            payload.id,
            {
                "resources": [
                    {
                        "uri": "fathom://semantics/overview",
                        "name": "FATHOM ONN semantic overview",
                        "description": (
                            "Published objects, relations, attributes, metrics, "
                            "events and policies."
                        ),
                        "mimeType": "application/json",
                    }
                ]
            },
        )
    if payload.method == "resources/read":
        uri = payload.params.get("uri")
        if uri != "fathom://semantics/overview":
            return _rpc_error(payload.id, -32602, f"Unknown resource: {uri}")
        content = _semantic_overview(request)
        return _rpc_result(
            payload.id,
            {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "application/json",
                        "text": json.dumps(content, ensure_ascii=False),
                    }
                ]
            },
        )
    return _rpc_error(payload.id, -32601, f"Method not found: {payload.method}")


def _mcp_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "fathom.ask_data",
            "title": "FATHOM 工业语义问数",
            "description": "在 ONN 与 ABC 约束下计算认证指标并返回证据。",
            "inputSchema": {
                "type": "object",
                "required": ["question"],
                "properties": {
                    "question": {"type": "string", "minLength": 2},
                    "scope": {"type": "object", "additionalProperties": {"type": "string"}},
                },
            },
        },
        {
            "name": "fathom.search_semantics",
            "title": "搜索 FATHOM 语义资产",
            "description": "搜索对象、关系、属性、指标、事件和权限。",
            "inputSchema": {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                },
            },
        },
        {
            "name": "fathom.get_object_context",
            "title": "读取 ONN 对象上下文",
            "description": "读取对象实例、属性和有效关系，供 Agent 与数字孪生消费。",
            "inputSchema": {
                "type": "object",
                "required": ["object_id"],
                "properties": {"object_id": {"type": "string", "minLength": 1}},
            },
        },
    ]


def _call_mcp_tool(payload: JsonRpcRequest, request: Request) -> dict[str, Any]:
    name = payload.params.get("name")
    arguments = payload.params.get("arguments", {})
    try:
        if name == "fathom.ask_data":
            from fathom.domains.query.models import AskRequest

            result = request.app.state.query_service.ask(
                AskRequest.model_validate(arguments),
                getattr(request.state, "authorized_objects", None),
            )
            structured = result.model_dump(mode="json")
        elif name == "fathom.search_semantics":
            query = str(arguments.get("query", ""))
            limit = min(max(int(arguments.get("limit", 20)), 1), 100)
            structured = {
                "items": [
                    asset.model_dump(mode="json")
                    for asset in request.app.state.semantic_repository.search(query, limit)
                ]
            }
        elif name == "fathom.get_object_context":
            object_id = str(arguments.get("object_id", ""))
            if not object_id:
                raise ValueError("object_id is required")
            allowed = getattr(request.state, "authorized_objects", None)
            if allowed is not None and object_id not in allowed:
                raise PermissionError(f"无权访问业务对象：{object_id}")
            structured = request.app.state.object_context_service.get_context(object_id)
        else:
            return _rpc_error(payload.id, -32602, f"Unknown tool: {name}")
    except PermissionError as error:
        return _rpc_error(payload.id, -32003, str(error))
    except (TypeError, ValueError) as error:
        return _rpc_error(payload.id, -32602, str(error))
    return _rpc_result(
        payload.id,
        {
            "content": [{"type": "text", "text": json.dumps(structured, ensure_ascii=False)}],
            "structuredContent": structured,
            "isError": False,
        },
    )


def _semantic_overview(request: Request) -> dict[str, Any]:
    repository = request.app.state.semantic_repository
    assets = repository.list_assets()
    counts: dict[str, int] = {}
    for asset in assets:
        counts[asset.kind.value] = counts.get(asset.kind.value, 0) + 1
    return {
        "domain": "manufacturing.execution",
        "counts": counts,
        "assets": [asset.model_dump(mode="json") for asset in assets],
        "relations": [relation.model_dump(mode="json") for relation in request.app.state.relations],
    }
