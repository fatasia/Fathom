from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse
from fathom.adapters.storage.database import AuditEventRecord
from fathom.config import Settings
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

ROLE_ORDER = {"viewer": 0, "operator": 1, "semantic_owner": 2, "admin": 3}


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AccessController:
    def __init__(self, settings: Settings) -> None:
        self._enabled = settings.auth_enabled
        self._principals = settings.auth_principals

    def authenticate(self, request: Request) -> tuple[str, str, set[str] | None] | None:
        if not self._enabled:
            return "local", "admin", None
        authorization = request.headers.get("Authorization", "")
        token = authorization.removeprefix("Bearer ").strip()
        token = token or request.headers.get("X-Fathom-Key", "").strip()
        if not token:
            return None
        digest = token_hash(token)
        for principal, configuration in self._principals.items():
            expected = str(configuration.get("token_hash", ""))
            if expected and hmac.compare_digest(digest, expected):
                role = str(configuration.get("role", "viewer"))
                if role in ROLE_ORDER:
                    configured_scope = configuration.get("object_scope")
                    if configured_scope is None or configured_scope == "*":
                        object_scope = None
                    elif isinstance(configured_scope, str):
                        object_scope = {
                            item.strip() for item in configured_scope.split(",") if item.strip()
                        }
                    elif isinstance(configured_scope, list):
                        object_scope = {str(item) for item in configured_scope}
                    else:
                        object_scope = set()
                    return principal, role, object_scope
        return None

    @staticmethod
    def authorize(role: str, method: str, path: str) -> bool:
        if ROLE_ORDER.get(role, -1) >= ROLE_ORDER["admin"]:
            return True
        if method == "GET":
            if path.startswith("/api/v1/system/audit-events"):
                return False
            sensitive = (
                "/api/v1/system/configuration",
                "/api/v1/system/backups",
                "/api/v1/model-gateway/",
                "/api/v1/data-sources",
                "/api/v1/exports/",
            )
            if any(path.startswith(prefix) for prefix in sensitive):
                return ROLE_ORDER.get(role, -1) >= ROLE_ORDER["semantic_owner"]
            return True
        viewer_paths = ("/api/v1/query/", "/a2a", "/mcp")
        if any(path.startswith(prefix) for prefix in viewer_paths):
            return ROLE_ORDER.get(role, -1) >= ROLE_ORDER["viewer"]
        operator_paths = (
            "/api/v1/ingestion/",
            "/api/v1/pipelines/",
            "/api/v1/agent-mesh/runs",
            "/api/v1/multimodal/",
        )
        if any(path.startswith(prefix) for prefix in operator_paths):
            return ROLE_ORDER.get(role, -1) >= ROLE_ORDER["operator"]
        owner_paths = (
            "/api/v1/governance/",
            "/api/v1/semantics/import",
            "/api/v1/data-sources/",
            "/api/v1/tools/",
            "/api/v1/system/backups",
            "/api/v1/model-gateway/",
        )
        if any(path.startswith(prefix) for prefix in owner_paths):
            return ROLE_ORDER.get(role, -1) >= ROLE_ORDER["semantic_owner"]
        return False


class AuditService:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def record(
        self,
        *,
        principal: str,
        role: str,
        method: str,
        path: str,
        status_code: int,
        duration_ms: float,
        client: str,
    ) -> None:
        with self._session_factory() as session:
            session.add(
                AuditEventRecord(
                    event_id=f"audit_{uuid4().hex[:16]}",
                    created_at=datetime.now(UTC),
                    principal=principal,
                    role=role,
                    method=method,
                    path=path,
                    status_code=status_code,
                    duration_ms=round(duration_ms, 2),
                    client=client,
                )
            )
            session.commit()

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            records = session.scalars(
                select(AuditEventRecord)
                .order_by(AuditEventRecord.created_at.desc())
                .limit(min(max(limit, 1), 500))
            ).all()
            return [
                {
                    "event_id": item.event_id,
                    "created_at": item.created_at.isoformat(),
                    "principal": item.principal,
                    "role": item.role,
                    "method": item.method,
                    "path": item.path,
                    "status_code": item.status_code,
                    "duration_ms": item.duration_ms,
                    "client": item.client,
                }
                for item in records
            ]


def request_timer() -> float:
    return perf_counter()


def elapsed_ms(started: float) -> float:
    return (perf_counter() - started) * 1000


def authentication_error(status_code: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": detail})
