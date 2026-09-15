from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from fathom.adapters.storage.database import ExtractionRunRecord, SchemaSnapshotRecord
from fathom.application.data_sources import DataSourceService
from fathom.application.governance import GovernanceService, SemanticAssetProposal
from fathom.domains.semantics.models import AssetKind
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker


class SemanticModelGateway(Protocol):
    def invoke_role(
        self, role: str, prompt: str, images: list[str] | None = None
    ) -> dict[str, Any]: ...


class SemanticExtractionService:
    """Idempotent schema/document extraction that can only create review candidates."""

    _numeric_markers = (
        "int",
        "decimal",
        "numeric",
        "real",
        "double",
        "float",
        "number",
    )
    _metric_terms = (
        "amount",
        "quantity",
        "qty",
        "count",
        "total",
        "price",
        "cost",
        "revenue",
        "rate",
        "ratio",
        "percent",
        "duration",
        "minutes",
        "output",
        "score",
        "金额",
        "数量",
        "产量",
        "成本",
        "收入",
        "比率",
        "时长",
    )
    _identity_terms = ("id", "code", "key", "编号", "编码")

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        data_sources: DataSourceService,
        governance: GovernanceService,
        model_gateway: SemanticModelGateway | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._data_sources = data_sources
        self._governance = governance
        self._model_gateway = model_gateway

    def extract_data_source(
        self,
        source_key: str,
        *,
        business_questions: str = "",
        domain: str | None = None,
    ) -> dict[str, Any]:
        discovered = self._data_sources.discover(source_key)
        checksum = self._hash(discovered)
        previous = self._latest_snapshot(source_key)
        if previous is not None and previous.checksum == checksum:
            result = {
                "source": source_key,
                "status": "unchanged",
                "snapshot_id": previous.snapshot_id,
                "discovery": discovered,
                "scaffold": {"objects": [], "attributes": [], "relations": []},
                "candidates": [],
                "governance": {"created": [], "skipped": [], "conflicts": []},
                "diff": self._empty_diff(),
            }
            self._record_run("data_source", source_key, checksum, "unchanged", result)
            return result

        diff = self._schema_diff(previous.schema_document if previous else None, discovered)
        snapshot_id = f"schema_{uuid4().hex[:16]}"
        with self._session_factory() as session:
            session.add(
                SchemaSnapshotRecord(
                    snapshot_id=snapshot_id,
                    source_key=source_key,
                    checksum=checksum,
                    schema_document=discovered,
                    diff=diff,
                    created_at=datetime.now(UTC),
                )
            )
            session.commit()

        scaffold = self._data_sources.scaffold_from_discovery(source_key, discovered)
        extraction_domain = domain or f"federated.{self._safe_key(source_key)}"
        candidates = self._model_candidates(
            trigger="data_source",
            source_key=source_key,
            domain=extraction_domain,
            content={
                "schema": discovered,
                "diff": diff,
                "business_questions": business_questions,
            },
        )
        if not candidates:
            candidates = self._schema_candidates(
                source_key,
                discovered,
                extraction_domain,
                business_questions,
            )
        batch_id = f"batch_{uuid4().hex[:16]}"
        governance = self._governance.propose_extracted_assets(
            candidates,
            actor="guided_onboarding",
            batch_id=batch_id,
        )
        result = {
            "source": source_key,
            "status": "candidates_created",
            "snapshot_id": snapshot_id,
            "batch_id": batch_id,
            "discovery": discovered,
            "scaffold": scaffold,
            "diff": diff,
            "candidates": [item["proposal"] for item in candidates],
            "governance": governance,
        }
        self._record_run("data_source", source_key, checksum, "completed", result)
        return result

    def extract_knowledge_document(
        self,
        *,
        document_id: str,
        knowledge_base_key: str,
        title: str,
        content: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        input_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        with self._session_factory() as session:
            existing = session.scalar(
                select(ExtractionRunRecord).where(
                    ExtractionRunRecord.trigger_type == "knowledge",
                    ExtractionRunRecord.source_key == document_id,
                    ExtractionRunRecord.input_hash == input_hash,
                    ExtractionRunRecord.status == "completed",
                )
            )
        if existing is not None:
            return {**existing.result, "deduplicated": True}

        if not self._looks_like_semantic_document(title, content):
            result = {
                "status": "indexed_only",
                "document_id": document_id,
                "reason": "未检测到指标、口径、公式或数据字典内容",
                "candidates": [],
                "governance": {"created": [], "skipped": [], "conflicts": []},
            }
            self._record_run("knowledge", document_id, input_hash, "completed", result)
            return result

        domain = str(metadata.get("domain") or f"knowledge.{self._safe_key(knowledge_base_key)}")
        candidates = self._model_candidates(
            trigger="knowledge",
            source_key=document_id,
            domain=domain,
            content={"title": title, "content": content[:60_000], "metadata": metadata},
        )
        if not candidates:
            candidates = self._knowledge_candidates(
                document_id=document_id,
                title=title,
                content=content,
                domain=domain,
            )
        batch_id = f"batch_{uuid4().hex[:16]}"
        governance = self._governance.propose_extracted_assets(
            candidates,
            actor="knowledge_extractor",
            batch_id=batch_id,
        )
        result = {
            "status": "candidates_created" if candidates else "indexed_only",
            "document_id": document_id,
            "batch_id": batch_id,
            "candidates": [item["proposal"] for item in candidates],
            "governance": governance,
        }
        self._record_run("knowledge", document_id, input_hash, "completed", result)
        return result

    def list_runs(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            records = session.scalars(
                select(ExtractionRunRecord)
                .order_by(ExtractionRunRecord.created_at.desc())
                .limit(min(max(limit, 1), 500))
            ).all()
        return [
            {
                "run_id": item.run_id,
                "trigger_type": item.trigger_type,
                "source_key": item.source_key,
                "input_hash": item.input_hash,
                "status": item.status,
                "result": item.result,
                "created_at": item.created_at.isoformat(),
                "completed_at": item.completed_at.isoformat(),
            }
            for item in records
        ]

    def _model_candidates(
        self,
        *,
        trigger: str,
        source_key: str,
        domain: str,
        content: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if self._model_gateway is None:
            return []
        prompt = (
            "你是企业数据语义提炼器。只提取输入中有明确证据的业务对象、属性、关系、"
            "指标、事件和策略。禁止猜测公式。返回 JSON 对象："
            '{"assets":[{"key":"...","kind":"object|attribute|relation|metric|event|policy",'
            '"label":"...","description":"...","aliases":[],"source":"...",'
            '"unit":null,"dimensions":[],"expression":null,"confidence":0.0,'
            '"evidence":[]}]}。所有 key 使用小写字母、数字、点、下划线或连字符。'
            f"默认 domain={domain}，owner=unassigned，触发类型={trigger}，来源={source_key}。\n\n"
            + json.dumps(content, ensure_ascii=False, default=str)
        )
        try:
            response = self._model_gateway.invoke_role("semantic_extractor", prompt)
            text = str(response.get("text", "")).strip()
            payload = self._parse_json(text)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return []
        items = payload.get("assets", []) if isinstance(payload, dict) else []
        candidates: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                proposal = SemanticAssetProposal(
                    key=self._safe_key(str(item["key"])),
                    kind=AssetKind(str(item["kind"])),
                    label=str(item["label"]).strip(),
                    description=str(item.get("description", "")),
                    domain=domain,
                    owner=str(item.get("owner") or "unassigned"),
                    aliases=[str(value) for value in item.get("aliases", [])],
                    source=str(item.get("source") or source_key),
                    unit=str(item["unit"]) if item.get("unit") else None,
                    dimensions=[str(value) for value in item.get("dimensions", [])],
                    expression=str(item["expression"]) if item.get("expression") else None,
                    metadata={
                        "status": "candidate",
                        "extraction": "model",
                        "trigger": trigger,
                        "source_key": source_key,
                    },
                )
            except (KeyError, ValueError):
                continue
            candidates.append(
                {
                    "proposal": proposal.model_dump(mode="json"),
                    "confidence": float(item.get("confidence", 0.7)),
                    "evidence": [str(value) for value in item.get("evidence", [])]
                    or [f"{trigger}:{source_key}"],
                }
            )
        return candidates

    def _schema_candidates(
        self,
        source_key: str,
        discovered: dict[str, Any],
        domain: str,
        business_questions: str,
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        namespace = self._safe_key(source_key)
        question_terms = {
            term.casefold()
            for term in re.findall(r"[\w\u4e00-\u9fff]{2,}", business_questions)
        }
        for table in discovered.get("tables", []):
            raw_table = str(table.get("name", "")).strip()
            if not raw_table:
                continue
            table_key = self._safe_key(raw_table)
            object_key = f"{namespace}.{table_key}"
            object_label = raw_table.replace("_", " ").strip().title()
            table_evidence = f"schema://{source_key}/{raw_table}"
            candidates.append(
                self._candidate(
                    key=object_key,
                    kind=AssetKind.OBJECT,
                    label=object_label,
                    description=f"从数据源 {source_key} 的表 {raw_table} 发现的业务对象候选。",
                    domain=domain,
                    source=f"{source_key}.{raw_table}",
                    confidence=0.82,
                    evidence=[table_evidence],
                    metadata={"table": raw_table, "status": "candidate"},
                )
            )
            dimensions: list[str] = []
            numeric_columns: list[dict[str, Any]] = []
            for column in table.get("columns", []):
                raw_column = str(column.get("name", "")).strip()
                if not raw_column:
                    continue
                column_key = self._safe_key(raw_column)
                source_type = str(column.get("type", "unknown"))
                lower = raw_column.casefold()
                is_numeric = any(
                    marker in source_type.casefold() for marker in self._numeric_markers
                )
                is_identity = (
                    bool(column.get("primary_key"))
                    or lower in self._identity_terms
                    or any(lower.endswith(f"_{marker}") for marker in self._identity_terms)
                )
                attribute_key = f"{object_key}.{column_key}"
                candidates.append(
                    self._candidate(
                        key=attribute_key,
                        kind=AssetKind.ATTRIBUTE,
                        label=raw_column.replace("_", " ").title(),
                        description=f"{object_label} 的字段 {raw_column}。",
                        domain=domain,
                        source=f"{source_key}.{raw_table}.{raw_column}",
                        confidence=0.78,
                        evidence=[f"{table_evidence}#{raw_column}"],
                        metadata={
                            "object": object_key,
                            "source_type": source_type,
                            "identity_candidate": is_identity,
                            "status": "candidate",
                        },
                    )
                )
                if is_numeric and not is_identity:
                    numeric_columns.append(column)
                elif not is_identity and len(dimensions) < 8:
                    dimensions.append(attribute_key)

            for column in numeric_columns:
                raw_column = str(column["name"])
                lower = raw_column.casefold()
                explicitly_requested = any(term in lower for term in question_terms)
                metric_like = explicitly_requested or any(
                    term in lower for term in self._metric_terms
                )
                if not metric_like:
                    continue
                aggregation = (
                    "avg"
                    if any(term in lower for term in ("rate", "ratio", "percent"))
                    else "sum"
                )
                unit = "%" if any(term in lower for term in ("rate", "ratio", "percent")) else None
                candidates.append(
                    self._candidate(
                        key=f"{object_key}.{self._safe_key(raw_column)}_metric",
                        kind=AssetKind.METRIC,
                        label=raw_column.replace("_", " ").title(),
                        description=(
                            f"从 {raw_table}.{raw_column} 识别的指标候选；"
                            "聚合和业务边界必须由负责人复核。"
                        ),
                        domain=domain,
                        source=f"{source_key}.{raw_table}.{raw_column}",
                        confidence=0.64,
                        evidence=[f"{table_evidence}#{raw_column}"],
                        unit=unit,
                        dimensions=dimensions,
                        expression=f"{aggregation}({raw_column})",
                        metadata={
                            "table": raw_table,
                            "column": raw_column,
                            "aggregation_candidate": aggregation,
                            "requires_business_review": True,
                            "status": "candidate",
                        },
                    )
                )

            for foreign_key in table.get("foreign_keys", []):
                target_table = str(foreign_key.get("target_table", "")).strip()
                if not target_table:
                    continue
                target_key = f"{namespace}.{self._safe_key(target_table)}"
                relation_key = f"{object_key}.to.{self._safe_key(target_table)}"
                candidates.append(
                    self._candidate(
                        key=relation_key,
                        kind=AssetKind.RELATION,
                        label=f"{object_label} 关联 {target_table.replace('_', ' ').title()}",
                        description="由数据库外键发现的关系候选。",
                        domain=domain,
                        source=f"{source_key}.{raw_table}",
                        confidence=0.96,
                        evidence=[table_evidence],
                        metadata={
                            "source_object": object_key,
                            "target_object": target_key,
                            "source_column": foreign_key.get("column"),
                            "target_column": foreign_key.get("target_column"),
                            "status": "candidate",
                        },
                    )
                )
            if any(
                term in raw_table.casefold()
                for term in ("event", "alarm", "fault", "downtime")
            ):
                candidates.append(
                    self._candidate(
                        key=f"{object_key}.event",
                        kind=AssetKind.EVENT,
                        label=f"{object_label}事件",
                        description=f"从事件型表 {raw_table} 识别的事件候选。",
                        domain=domain,
                        source=f"{source_key}.{raw_table}",
                        confidence=0.72,
                        evidence=[table_evidence],
                        metadata={"table": raw_table, "status": "candidate"},
                    )
                )
        return candidates

    def _knowledge_candidates(
        self, *, document_id: str, title: str, content: str, domain: str
    ) -> list[dict[str, Any]]:
        metric_match = re.search(
            r"(?:指标(?:名称)?|metric)\s*[:：]\s*([^\n|]{1,80})",
            content,
            flags=re.IGNORECASE,
        )
        formula_match = re.search(
            r"(?:公式|计算公式|expression|formula)\s*[:：]\s*([^\n|]{1,300})",
            content,
            flags=re.IGNORECASE,
        )
        if not metric_match or not formula_match:
            return []
        label = metric_match.group(1).strip(" *#")
        expression = formula_match.group(1).strip(" *#")
        alias_match = re.search(r"(?:别名|同义词|aliases?)\s*[:：]\s*([^\n]+)", content, re.I)
        aliases = (
            [item.strip() for item in re.split(r"[,，、;/]", alias_match.group(1)) if item.strip()]
            if alias_match
            else []
        )
        proposal = SemanticAssetProposal(
            key=f"{self._safe_key(domain)}.{self._safe_key(label)}",
            kind=AssetKind.METRIC,
            label=label,
            description=f"从《{title}》提炼的指标候选，发布前必须确认公式和适用范围。",
            domain=domain,
            owner="unassigned",
            aliases=aliases,
            source=f"knowledge://{document_id}",
            expression=expression,
            metadata={
                "document_id": document_id,
                "requires_business_review": True,
                "status": "candidate",
            },
        )
        return [
            {
                "proposal": proposal.model_dump(mode="json"),
                "confidence": 0.72,
                "evidence": [f"knowledge://{document_id}", f"formula:{expression}"],
            }
        ]

    @staticmethod
    def _candidate(
        *,
        key: str,
        kind: AssetKind,
        label: str,
        description: str,
        domain: str,
        source: str,
        confidence: float,
        evidence: list[str],
        metadata: dict[str, Any],
        unit: str | None = None,
        dimensions: list[str] | None = None,
        expression: str | None = None,
    ) -> dict[str, Any]:
        proposal = SemanticAssetProposal(
            key=key,
            kind=kind,
            label=label,
            description=description,
            domain=domain,
            owner="unassigned",
            source=source,
            unit=unit,
            dimensions=dimensions or [],
            expression=expression,
            metadata=metadata,
        )
        return {
            "proposal": proposal.model_dump(mode="json"),
            "confidence": confidence,
            "evidence": evidence,
        }

    def _latest_snapshot(self, source_key: str) -> SchemaSnapshotRecord | None:
        with self._session_factory() as session:
            return session.scalar(
                select(SchemaSnapshotRecord)
                .where(SchemaSnapshotRecord.source_key == source_key)
                .order_by(SchemaSnapshotRecord.created_at.desc())
                .limit(1)
            )

    def _record_run(
        self,
        trigger_type: str,
        source_key: str,
        input_hash: str,
        status: str,
        result: dict[str, Any],
    ) -> None:
        now = datetime.now(UTC)
        with self._session_factory() as session:
            session.add(
                ExtractionRunRecord(
                    run_id=f"extract_{uuid4().hex[:16]}",
                    trigger_type=trigger_type,
                    source_key=source_key,
                    input_hash=input_hash,
                    status=status,
                    result=result,
                    created_at=now,
                    completed_at=now,
                )
            )
            session.commit()

    @classmethod
    def _schema_diff(
        cls, previous: dict[str, Any] | None, current: dict[str, Any]
    ) -> dict[str, Any]:
        if previous is None:
            return {
                "added_tables": sorted(
                    str(table.get("name")) for table in current.get("tables", [])
                ),
                "removed_tables": [],
                "changed_tables": [],
                "added_columns": [],
                "removed_columns": [],
                "changed_columns": [],
            }
        old_tables = {str(table.get("name")): table for table in previous.get("tables", [])}
        new_tables = {str(table.get("name")): table for table in current.get("tables", [])}
        added_columns: list[str] = []
        removed_columns: list[str] = []
        changed_columns: list[str] = []
        changed_tables: list[str] = []
        for table_name in sorted(old_tables.keys() & new_tables.keys()):
            old_columns = {
                str(column.get("name")): str(column.get("type", ""))
                for column in old_tables[table_name].get("columns", [])
            }
            new_columns = {
                str(column.get("name")): str(column.get("type", ""))
                for column in new_tables[table_name].get("columns", [])
            }
            for name in sorted(new_columns.keys() - old_columns.keys()):
                added_columns.append(f"{table_name}.{name}")
            for name in sorted(old_columns.keys() - new_columns.keys()):
                removed_columns.append(f"{table_name}.{name}")
            for name in sorted(old_columns.keys() & new_columns.keys()):
                if old_columns[name].casefold() != new_columns[name].casefold():
                    changed_columns.append(f"{table_name}.{name}")
            if any(
                item.startswith(f"{table_name}.")
                for item in [*added_columns, *removed_columns, *changed_columns]
            ):
                changed_tables.append(table_name)
        return {
            "added_tables": sorted(new_tables.keys() - old_tables.keys()),
            "removed_tables": sorted(old_tables.keys() - new_tables.keys()),
            "changed_tables": changed_tables,
            "added_columns": added_columns,
            "removed_columns": removed_columns,
            "changed_columns": changed_columns,
        }

    @staticmethod
    def _empty_diff() -> dict[str, list[str]]:
        return {
            "added_tables": [],
            "removed_tables": [],
            "changed_tables": [],
            "added_columns": [],
            "removed_columns": [],
            "changed_columns": [],
        }

    @staticmethod
    def _looks_like_semantic_document(title: str, content: str) -> bool:
        haystack = f"{title}\n{content[:20_000]}".casefold()
        terms = ("指标", "口径", "计算公式", "数据字典", "metric", "formula", "definition")
        return any(term in haystack for term in terms)

    @staticmethod
    def _parse_json(value: str) -> dict[str, Any]:
        stripped = value.strip()
        if stripped.startswith("```"):
            stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.I)
            stripped = re.sub(r"\s*```$", "", stripped)
        return json.loads(stripped)

    @staticmethod
    def _hash(value: dict[str, Any]) -> str:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _safe_key(value: str) -> str:
        normalized = re.sub(r"[^a-z0-9_.-]+", "_", value.casefold()).strip("_.-")
        if not normalized:
            normalized = f"asset_{hashlib.sha256(value.encode()).hexdigest()[:10]}"
        if not normalized[0].isalpha():
            normalized = f"asset_{normalized}"
        return normalized[:160]
