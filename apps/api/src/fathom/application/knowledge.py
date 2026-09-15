from __future__ import annotations

import hashlib
import json
import os
import re
import ssl
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlencode, urlparse

import certifi
from fathom.adapters.storage.database import (
    KnowledgeBaseRecord,
    KnowledgeChunkRecord,
    KnowledgeDocumentRecord,
)
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

if TYPE_CHECKING:
    from fathom.application.semantic_extraction import SemanticExtractionService


class KnowledgeBaseInput(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_.-]+$")
    name: str = Field(min_length=2, max_length=160)
    kind: Literal["internal", "external"] = "internal"
    configuration: dict[str, Any] = Field(default_factory=dict)
    secret_reference: str | None = Field(default=None, max_length=500)
    enabled: bool = True

    @model_validator(mode="after")
    def validate_configuration(self) -> KnowledgeBaseInput:
        if self._contains_secret(self.configuration):
            raise ValueError("密钥不能写入普通配置，请使用 env://VARIABLE 凭证引用")
        if self.kind == "external":
            endpoint = str(self.configuration.get("endpoint", ""))
            parsed = urlparse(endpoint)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("外接知识库需要完整的 http/https endpoint")
            if parsed.username or parsed.password:
                raise ValueError("endpoint 不能包含用户名或密码")
        if self.secret_reference and not self.secret_reference.startswith("env://"):
            raise ValueError("知识库凭证仅接受 env://VARIABLE 引用")
        return self

    @staticmethod
    def _contains_secret(value: Any) -> bool:
        secret_keys = {"api_key", "token", "password", "authorization", "secret"}
        if isinstance(value, dict):
            return any(
                str(key).casefold() in secret_keys
                or KnowledgeBaseInput._contains_secret(item)
                for key, item in value.items()
            )
        if isinstance(value, list):
            return any(KnowledgeBaseInput._contains_secret(item) for item in value)
        return False


class KnowledgeDocumentInput(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=5_000_000)
    source_uri: str = Field(default="manual://input", max_length=1000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("文档内容不能为空")
        return value


class KnowledgeSearchInput(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    knowledge_base_keys: list[str] = Field(default_factory=list)
    top_k: int = Field(default=5, ge=1, le=20)


class KnowledgeService:
    """Lightweight internal retrieval and a generic external knowledge adapter."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        semantic_extraction: SemanticExtractionService | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._semantic_extraction = semantic_extraction

    def list_bases(self) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            records = session.scalars(
                select(KnowledgeBaseRecord).order_by(KnowledgeBaseRecord.name)
            ).all()
            document_counts = dict(
                session.execute(
                    select(
                        KnowledgeDocumentRecord.knowledge_base_key,
                        func.count(KnowledgeDocumentRecord.document_id),
                    ).group_by(KnowledgeDocumentRecord.knowledge_base_key)
                ).all()
            )
            return [
                self._serialize_base(record, document_counts.get(record.key, 0))
                for record in records
            ]

    def save_base(self, payload: KnowledgeBaseInput) -> dict[str, Any]:
        with self._session_factory() as session:
            record = session.get(KnowledgeBaseRecord, payload.key)
            values = payload.model_dump()
            values["updated_at"] = datetime.now(UTC)
            if record is None:
                record = KnowledgeBaseRecord(**values)
                session.add(record)
            else:
                if record.kind != payload.kind:
                    documents = session.scalar(
                        select(func.count(KnowledgeDocumentRecord.document_id)).where(
                            KnowledgeDocumentRecord.knowledge_base_key == payload.key
                        )
                    )
                    if documents:
                        raise ValueError("已有文档的知识库不能切换内置/外接类型")
                for key, value in values.items():
                    setattr(record, key, value)
            session.commit()
            session.refresh(record)
            return self._serialize_base(record, self._document_count(session, payload.key))

    def delete_base(self, key: str) -> None:
        with self._session_factory() as session:
            record = session.get(KnowledgeBaseRecord, key)
            if record is None:
                raise LookupError(key)
            session.execute(
                delete(KnowledgeChunkRecord).where(
                    KnowledgeChunkRecord.knowledge_base_key == key
                )
            )
            session.execute(
                delete(KnowledgeDocumentRecord).where(
                    KnowledgeDocumentRecord.knowledge_base_key == key
                )
            )
            session.delete(record)
            session.commit()

    def list_documents(self, knowledge_base_key: str) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            self._require_internal_base(session, knowledge_base_key)
            records = session.scalars(
                select(KnowledgeDocumentRecord)
                .where(KnowledgeDocumentRecord.knowledge_base_key == knowledge_base_key)
                .order_by(KnowledgeDocumentRecord.updated_at.desc())
            ).all()
            return [self._serialize_document(record) for record in records]

    def ingest_document(
        self, knowledge_base_key: str, payload: KnowledgeDocumentInput
    ) -> dict[str, Any]:
        normalized = payload.content.replace("\r\n", "\n").strip()
        checksum = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        with self._session_factory() as session:
            self._require_internal_base(session, knowledge_base_key)
            existing = session.scalar(
                select(KnowledgeDocumentRecord).where(
                    KnowledgeDocumentRecord.knowledge_base_key == knowledge_base_key,
                    KnowledgeDocumentRecord.checksum == checksum,
                )
            )
            if existing is not None:
                return {**self._serialize_document(existing), "deduplicated": True}
            document_id = uuid.uuid4().hex
            record = KnowledgeDocumentRecord(
                document_id=document_id,
                knowledge_base_key=knowledge_base_key,
                title=payload.title,
                source_uri=payload.source_uri,
                content=normalized,
                document_metadata=payload.metadata,
                checksum=checksum,
                updated_at=datetime.now(UTC),
            )
            session.add(record)
            chunks = self._chunk_text(normalized)
            for position, content in enumerate(chunks):
                session.add(
                    KnowledgeChunkRecord(
                        chunk_id=uuid.uuid4().hex,
                        document_id=document_id,
                        knowledge_base_key=knowledge_base_key,
                        position=position,
                        content=content,
                        chunk_metadata={"title": payload.title, **payload.metadata},
                    )
                )
            session.commit()
            result = {
                **self._serialize_document(record),
                "chunk_count": len(chunks),
                "deduplicated": False,
            }
        if self._semantic_extraction is not None:
            result["semantic_extraction"] = (
                self._semantic_extraction.extract_knowledge_document(
                    document_id=document_id,
                    knowledge_base_key=knowledge_base_key,
                    title=payload.title,
                    content=normalized,
                    metadata=payload.metadata,
                )
            )
        return result

    def delete_document(self, knowledge_base_key: str, document_id: str) -> None:
        with self._session_factory() as session:
            record = session.get(KnowledgeDocumentRecord, document_id)
            if record is None or record.knowledge_base_key != knowledge_base_key:
                raise LookupError(document_id)
            session.execute(
                delete(KnowledgeChunkRecord).where(
                    KnowledgeChunkRecord.document_id == document_id
                )
            )
            session.delete(record)
            session.commit()

    def search(self, payload: KnowledgeSearchInput) -> dict[str, Any]:
        with self._session_factory() as session:
            statement = select(KnowledgeBaseRecord).where(KnowledgeBaseRecord.enabled.is_(True))
            if payload.knowledge_base_keys:
                statement = statement.where(
                    KnowledgeBaseRecord.key.in_(payload.knowledge_base_keys)
                )
            bases = session.scalars(statement.order_by(KnowledgeBaseRecord.name)).all()
            unknown = set(payload.knowledge_base_keys) - {base.key for base in bases}
            if unknown:
                raise LookupError(", ".join(sorted(unknown)))
            internal_keys = [base.key for base in bases if base.kind == "internal"]
            hits = self._search_internal(session, internal_keys, payload.query)
            warnings: list[str] = []
            external_bases = [base for base in bases if base.kind == "external"]
            for base in external_bases:
                try:
                    hits.extend(self._search_external(base, payload.query, payload.top_k))
                except (ValueError, OSError, urllib.error.URLError, json.JSONDecodeError) as error:
                    warnings.append(f"{base.name}：{str(error)[:240]}")
        hits.sort(key=lambda item: float(item.get("score", 0)), reverse=True)
        limited = hits[: payload.top_k]
        return {
            "query": payload.query,
            "items": limited,
            "total": len(limited),
            "searched_bases": [base.key for base in bases],
            "warnings": warnings,
        }

    def test_base(self, key: str) -> dict[str, Any]:
        with self._session_factory() as session:
            record = session.get(KnowledgeBaseRecord, key)
            if record is None:
                raise LookupError(key)
            if record.kind == "internal":
                documents = self._document_count(session, key)
                return {
                    "status": "ready",
                    "message": f"内置知识库可用，已收录 {documents} 个文档",
                }
            hits = self._search_external(record, "连接测试", 1)
            return {
                "status": "ready",
                "message": f"外接知识库已连通，测试返回 {len(hits)} 条",
            }

    def _search_internal(
        self, session: Session, knowledge_base_keys: list[str], query: str
    ) -> list[dict[str, Any]]:
        if not knowledge_base_keys:
            return []
        chunks = session.execute(
            select(KnowledgeChunkRecord, KnowledgeDocumentRecord)
            .join(
                KnowledgeDocumentRecord,
                KnowledgeDocumentRecord.document_id == KnowledgeChunkRecord.document_id,
            )
            .where(KnowledgeChunkRecord.knowledge_base_key.in_(knowledge_base_keys))
        ).all()
        query_features = self._features(query)
        normalized_query = self._normalize(query)
        hits: list[dict[str, Any]] = []
        for chunk, document in chunks:
            normalized_content = self._normalize(chunk.content)
            content_features = self._features(chunk.content)
            overlap = len(query_features.intersection(content_features))
            if not overlap and normalized_query not in normalized_content:
                continue
            coverage = overlap / max(len(query_features), 1)
            phrase_bonus = 1.0 if normalized_query in normalized_content else 0.0
            title_bonus = 0.25 if normalized_query in self._normalize(document.title) else 0.0
            score = min(1.0, 0.15 + coverage * 0.6 + phrase_bonus * 0.2 + title_bonus)
            hits.append(
                {
                    "knowledge_base_key": chunk.knowledge_base_key,
                    "document_id": document.document_id,
                    "title": document.title,
                    "content": chunk.content,
                    "source_uri": document.source_uri,
                    "score": round(score, 4),
                    "metadata": {
                        **document.document_metadata,
                        "chunk_position": chunk.position,
                    },
                    "retrieval": "internal_lexical",
                }
            )
        return hits

    def _search_external(
        self, record: KnowledgeBaseRecord, query: str, top_k: int
    ) -> list[dict[str, Any]]:
        configuration = record.configuration or {}
        endpoint = str(configuration["endpoint"])
        adapter = str(configuration.get("adapter", "generic"))
        method = str(configuration.get("method", "POST")).upper()
        timeout = min(max(float(configuration.get("timeout_seconds", 15)), 1), 60)
        secret = self._resolve_secret(record.secret_reference)
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            **{
                str(key): str(value)
                for key, value in configuration.get("headers", {}).items()
            },
        }
        if secret:
            header_name = str(configuration.get("auth_header", "Authorization"))
            prefix = str(configuration.get("auth_prefix", "Bearer "))
            headers[header_name] = f"{prefix}{secret}"
        if adapter == "dataset":
            body: dict[str, Any] = {
                "knowledge_id": configuration.get("knowledge_id", record.key),
                "query": query,
                "retrieval_setting": {
                    "top_k": top_k,
                    "score_threshold": float(configuration.get("score_threshold", 0)),
                },
            }
        else:
            body = self._substitute(
                configuration.get("body_template", {"query": "{{query}}", "top_k": "{{top_k}}"}),
                query,
                top_k,
            )
        data: bytes | None = json.dumps(body, ensure_ascii=False).encode("utf-8")
        if method == "GET":
            endpoint = f"{endpoint}{'&' if '?' in endpoint else '?'}{urlencode(body)}"
            data = None
        elif method != "POST":
            raise ValueError("外接知识库仅支持 GET 或 POST")
        context = ssl.create_default_context(cafile=certifi.where())
        request = urllib.request.Request(endpoint, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                raw = response.read(5_000_001)
        except urllib.error.HTTPError as error:
            detail = error.read(10_000).decode("utf-8", errors="replace")
            raise ValueError(f"HTTP {error.code}: {detail[:200]}") from error
        if len(raw) > 5_000_000:
            raise ValueError("外接知识库响应超过 5 MB 限制")
        payload = json.loads(raw.decode("utf-8"))
        default_items_path = "records" if adapter == "dataset" else "items"
        items_path = str(configuration.get("items_path", default_items_path))
        items = self._resolve_path(payload, items_path)
        if not isinstance(items, list):
            raise ValueError(f"响应路径 {items_path!r} 不是数组")
        return [
            self._normalize_external_item(record, item, index)
            for index, item in enumerate(items)
        ]

    @staticmethod
    def _normalize_external_item(
        record: KnowledgeBaseRecord, item: Any, index: int
    ) -> dict[str, Any]:
        if not isinstance(item, dict):
            item = {"content": str(item)}
        segment = item.get("segment") if isinstance(item.get("segment"), dict) else {}
        content = item.get("content") or item.get("text") or segment.get("content")
        metadata = item.get("metadata") or segment.get("metadata") or {}
        title = item.get("title") or metadata.get("title") or f"{record.name} #{index + 1}"
        source = item.get("source_uri") or item.get("url") or metadata.get("source") or f"external://{record.key}"
        return {
            "knowledge_base_key": record.key,
            "document_id": str(item.get("id") or item.get("document_id") or f"external-{index}"),
            "title": str(title),
            "content": str(content or ""),
            "source_uri": str(source),
            "score": round(float(item.get("score", item.get("similarity", 0.5))), 4),
            "metadata": metadata if isinstance(metadata, dict) else {},
            "retrieval": "external_http",
        }

    @staticmethod
    def _chunk_text(content: str, chunk_size: int = 1000, overlap: int = 120) -> list[str]:
        paragraphs = [
            paragraph.strip()
            for paragraph in re.split(r"\n\s*\n", content)
            if paragraph.strip()
        ]
        chunks: list[str] = []
        current = ""
        for paragraph in paragraphs or [content]:
            if len(paragraph) > chunk_size:
                if current:
                    chunks.append(current)
                    current = ""
                start = 0
                while start < len(paragraph):
                    chunks.append(paragraph[start : start + chunk_size])
                    start += chunk_size - overlap
                continue
            candidate = f"{current}\n\n{paragraph}".strip()
            if len(candidate) <= chunk_size:
                current = candidate
            else:
                chunks.append(current)
                current = f"{current[-overlap:]}\n\n{paragraph}".strip()
        if current:
            chunks.append(current)
        return chunks

    @staticmethod
    def _features(value: str) -> set[str]:
        normalized = KnowledgeService._normalize(value)
        words = set(re.findall(r"[a-z0-9_]+", normalized))
        chinese_runs = re.findall(r"[\u4e00-\u9fff]+", normalized)
        grams = {
            run[index : index + size]
            for run in chinese_runs
            for size in (1, 2, 3)
            for index in range(max(0, len(run) - size + 1))
        }
        return words | grams

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"\s+", "", value.casefold())

    @staticmethod
    def _substitute(value: Any, query: str, top_k: int) -> Any:
        if isinstance(value, str):
            if value == "{{top_k}}":
                return top_k
            return value.replace("{{query}}", query).replace("{{top_k}}", str(top_k))
        if isinstance(value, list):
            return [KnowledgeService._substitute(item, query, top_k) for item in value]
        if isinstance(value, dict):
            return {
                key: KnowledgeService._substitute(item, query, top_k)
                for key, item in value.items()
            }
        return value

    @staticmethod
    def _resolve_path(payload: Any, path: str) -> Any:
        current = payload
        if not path:
            return current
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                raise ValueError(f"响应中不存在路径：{path}")
            current = current[part]
        return current

    @staticmethod
    def _resolve_secret(reference: str | None) -> str | None:
        if not reference:
            return None
        if not reference.startswith("env://"):
            raise ValueError("知识库凭证仅接受 env://VARIABLE 引用")
        variable = reference.removeprefix("env://")
        secret = os.getenv(variable)
        if not secret:
            raise ValueError(f"环境变量 {variable} 未设置")
        return secret

    @staticmethod
    def _require_internal_base(session: Session, key: str) -> KnowledgeBaseRecord:
        record = session.get(KnowledgeBaseRecord, key)
        if record is None:
            raise LookupError(key)
        if record.kind != "internal":
            raise ValueError("外接知识库不在 FATHOM 内保存文档")
        return record

    @staticmethod
    def _document_count(session: Session, key: str) -> int:
        return int(
            session.scalar(
                select(func.count(KnowledgeDocumentRecord.document_id)).where(
                    KnowledgeDocumentRecord.knowledge_base_key == key
                )
            )
            or 0
        )

    @staticmethod
    def _serialize_base(record: KnowledgeBaseRecord, document_count: int) -> dict[str, Any]:
        return {
            "key": record.key,
            "name": record.name,
            "kind": record.kind,
            "configuration": record.configuration,
            "secret_reference": record.secret_reference,
            "has_secret": bool(record.secret_reference),
            "enabled": record.enabled,
            "document_count": document_count,
            "updated_at": record.updated_at.isoformat(),
        }

    @staticmethod
    def _serialize_document(record: KnowledgeDocumentRecord) -> dict[str, Any]:
        return {
            "document_id": record.document_id,
            "knowledge_base_key": record.knowledge_base_key,
            "title": record.title,
            "source_uri": record.source_uri,
            "metadata": record.document_metadata,
            "checksum": record.checksum,
            "size": len(record.content.encode("utf-8")),
            "updated_at": record.updated_at.isoformat(),
        }
