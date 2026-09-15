from __future__ import annotations

import hashlib
import json
import re
from typing import Any

import sqlglot
import yaml
from fathom.adapters.storage.semantic_repository import SqlSemanticRepository
from fathom.application.data_sources import DataSourceService
from fathom.domains.runtime.models import LegacyAssetExtractInput, ReverseMappingInput
from sqlglot import expressions as exp


class ReverseMappingService:
    """Generate review-only mapping candidates from discovered source metadata."""

    _time_names = ("observed_at", "event_time", "timestamp", "created_at", "date", "day")
    _object_names = ("object_id", "equipment_id", "line_id", "production_line", "asset_id")
    _value_names = ("value", "metric_value", "actual_value", "amount", "quantity")

    def __init__(
        self,
        data_sources: DataSourceService,
        repository: SqlSemanticRepository,
    ) -> None:
        self._data_sources = data_sources
        self._repository = repository

    def propose(self, payload: ReverseMappingInput) -> dict[str, Any]:
        discovered = self._data_sources.discover(payload.source_key)
        table = next(
            (
                item
                for item in discovered.get("tables", [])
                if item.get("name") == payload.table_name
            ),
            None,
        )
        if table is None:
            raise LookupError(payload.table_name)
        columns = [str(column["name"]) for column in table.get("columns", [])]
        object_column = self._first(columns, self._object_names)
        time_column = self._first(columns, self._time_names)
        candidates = []
        metrics = [item for item in self._repository.list_assets() if item.kind.value == "metric"]
        for metric in metrics:
            terms = [metric.key, *metric.aliases, metric.label]
            value_column = next(
                (
                    column
                    for column in columns
                    if any(
                        self._normalize(term) in self._normalize(column)
                        or self._normalize(column) in self._normalize(term)
                        for term in terms
                        if term
                    )
                ),
                None,
            )
            if value_column is None and "metric_key" in columns:
                value_column = self._first(columns, self._value_names)
            if not object_column or not time_column or not value_column:
                continue
            static_filters = {"metric_key": metric.key} if "metric_key" in columns else {}
            candidates.append(
                {
                    "key": f"{metric.key}.{payload.source_key}",
                    "metric_key": metric.key,
                    "source_key": payload.source_key,
                    "version": 1,
                    "owner": payload.owner,
                    "table_name": payload.table_name,
                    "object_column": object_column,
                    "value_column": value_column,
                    "time_column": time_column,
                    "dimension_columns": {
                        name: name
                        for name in ("production_line", "shift", "day", "equipment")
                        if name in columns
                    },
                    "static_filters": static_filters,
                    "aggregation": "none",
                    "priority": 100,
                    "confidence": 0.92 if static_filters else 0.72,
                    "status": "candidate",
                }
            )
        return {
            "source_key": payload.source_key,
            "table": payload.table_name,
            "columns": columns,
            "candidates": candidates,
            "next_step": "review_then_register",
        }

    def extract_legacy(self, payload: LegacyAssetExtractInput) -> dict[str, Any]:
        if payload.kind == "sql":
            return self._extract_sql(payload)
        return self._extract_openapi(payload)

    def _extract_sql(self, payload: LegacyAssetExtractInput) -> dict[str, Any]:
        if not isinstance(payload.content, str):
            raise ValueError("SQL 反向提炼的 content 必须是字符串")
        try:
            statements = sqlglot.parse(payload.content)
        except sqlglot.errors.ParseError as error:
            raise ValueError(f"SQL 无法解析：{error}") from error
        if not statements:
            raise ValueError("SQL 不能为空")
        tables = sorted(
            {
                table.sql()
                for statement in statements
                for table in statement.find_all(exp.Table)
            }
        )
        columns = sorted(
            {
                column.sql()
                for statement in statements
                for column in statement.find_all(exp.Column)
            }
        )
        normalized_sql = self._normalize(payload.content)
        matched_metrics = []
        mapping_candidates = []
        for asset in self._repository.list_assets():
            if asset.kind.value != "metric":
                continue
            terms = [asset.key, asset.label, *asset.aliases]
            if not any(self._normalize(term) in normalized_sql for term in terms if term):
                continue
            matched_metrics.append(asset.key)
            if payload.source_key and tables:
                mapping_candidates.append(
                    {
                        "key": f"{asset.key}.{payload.source_key}.legacy",
                        "metric_key": asset.key,
                        "source_key": payload.source_key,
                        "table_name": tables[0].split(".")[-1].strip('"'),
                        "owner": payload.owner,
                        "status": "candidate",
                        "confidence": 0.68,
                        "evidence": {"tables": tables, "columns": columns},
                        "missing_review_fields": [
                            "object_column",
                            "value_column",
                            "time_column",
                        ],
                    }
                )
        return {
            "kind": "sql",
            "fingerprint": hashlib.sha256(payload.content.encode()).hexdigest(),
            "tables": tables,
            "columns": columns,
            "matched_metrics": matched_metrics,
            "mapping_candidates": mapping_candidates,
            "capability_candidates": [],
            "status": "review_required",
        }

    def _extract_openapi(self, payload: LegacyAssetExtractInput) -> dict[str, Any]:
        if isinstance(payload.content, str):
            try:
                document = yaml.safe_load(payload.content)
            except yaml.YAMLError as error:
                raise ValueError(f"OpenAPI 文档无法解析：{error}") from error
        else:
            document = payload.content
        if not isinstance(document, dict) or not isinstance(document.get("paths"), dict):
            raise ValueError("OpenAPI 文档必须包含 paths")
        candidates = []
        for path, path_item in document["paths"].items():
            if not isinstance(path_item, dict):
                continue
            for method in ("get", "post", "put", "patch", "delete"):
                operation = path_item.get(method)
                if not isinstance(operation, dict):
                    continue
                operation_id = str(operation.get("operationId") or f"{method}_{path}")
                key_part = re.sub(r"[^a-z0-9_.-]+", ".", operation_id.casefold()).strip(".")
                parameters = [
                    parameter.get("name")
                    for parameter in operation.get("parameters", [])
                    if isinstance(parameter, dict) and parameter.get("name")
                ]
                candidates.append(
                    {
                        "key": f"integration.{key_part or 'operation'}",
                        "label": str(operation.get("summary") or operation_id),
                        "owner": payload.owner,
                        "binding": {"method": method.upper(), "path": str(path)},
                        "parameters": parameters,
                        "side_effect": "none" if method == "get" else "external",
                        "approval_required": method != "get",
                        "status": "candidate",
                    }
                )
        serialized = json.dumps(document, ensure_ascii=False, sort_keys=True)
        return {
            "kind": "openapi",
            "fingerprint": hashlib.sha256(serialized.encode()).hexdigest(),
            "tables": [],
            "columns": [],
            "matched_metrics": [],
            "mapping_candidates": [],
            "capability_candidates": candidates,
            "status": "review_required",
        }

    @staticmethod
    def _first(columns: list[str], preferred: tuple[str, ...]) -> str | None:
        return next((name for name in preferred if name in columns), None)

    @staticmethod
    def _normalize(value: str) -> str:
        return value.casefold().replace("_", "").replace(" ", "")
