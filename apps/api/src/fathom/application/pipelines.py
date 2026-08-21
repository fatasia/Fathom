from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import duckdb
import sqlglot
from fathom.adapters.storage.database import (
    DataSourceRecord,
    PipelineRecord,
    PipelineRunRecord,
)
from fathom.domains.pipelines.models import PipelineDefinition
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from sqlglot import exp


class PipelineService:
    """Execute bounded, local DuckDB pipeline previews against governed sources."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def list(self) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            records = session.scalars(select(PipelineRecord).order_by(PipelineRecord.key)).all()
            return [self._serialize(record) for record in records]

    def save(self, definition: PipelineDefinition, published: bool = False) -> dict[str, Any]:
        with self._session_factory() as session:
            record = session.get(PipelineRecord, definition.key)
            values = {
                **definition.model_dump(mode="json"),
                "published": published,
                "updated_at": datetime.now(UTC),
            }
            if record is None:
                record = PipelineRecord(**values)
                session.add(record)
            else:
                for key, value in values.items():
                    setattr(record, key, value)
            session.commit()
            session.refresh(record)
            return self._serialize(record)

    def delete(self, pipeline_key: str) -> None:
        with self._session_factory() as session:
            record = session.get(PipelineRecord, pipeline_key)
            if record is None:
                raise LookupError(pipeline_key)
            session.delete(record)
            session.commit()

    def runs(self, pipeline_key: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        limit = min(max(limit, 1), 200)
        with self._session_factory() as session:
            query = select(PipelineRunRecord)
            if pipeline_key:
                query = query.where(PipelineRunRecord.pipeline_key == pipeline_key)
            records = session.scalars(
                query.order_by(PipelineRunRecord.started_at.desc()).limit(limit)
            ).all()
            return [
                {
                    "run_id": record.run_id,
                    "pipeline_key": record.pipeline_key,
                    "status": record.status,
                    "started_at": record.started_at.isoformat(),
                    "finished_at": record.finished_at.isoformat(),
                    "result": record.result,
                }
                for record in records
            ]

    def preview(self, definition: PipelineDefinition, limit: int = 100) -> dict[str, Any]:
        if definition.mode != "preview":
            raise ValueError("交互式执行只允许 preview；full/incremental 请交给已审批调度器")
        limit = min(max(limit, 1), 1000)
        source = self._source(definition.source)
        relation_sql = self._relation_sql(source)
        query = f"SELECT * FROM {relation_sql}"
        quality_rules: list[dict[str, Any]] = []
        mappings: list[dict[str, Any]] = []

        for step in definition.steps:
            config = step.configuration
            if step.operation == "rename":
                source_name = self._identifier(config, "from")
                target_name = self._identifier(config, "to")
                query = (
                    "SELECT * EXCLUDE ("
                    f"{self._quote(source_name)}), {self._quote(source_name)} "
                    f"AS {self._quote(target_name)} FROM ({query})"
                )
            elif step.operation == "cast":
                column = self._identifier(config, "column")
                data_type = self._safe_type(config.get("type"))
                query = (
                    f"SELECT * REPLACE (CAST({self._quote(column)} AS {data_type}) "
                    f"AS {self._quote(column)}) FROM ({query})"
                )
            elif step.operation == "filter":
                condition = self._safe_expression(config.get("expression"))
                query = f"SELECT * FROM ({query}) WHERE {condition}"
            elif step.operation == "derive":
                column = self._identifier(config, "column")
                expression = self._safe_expression(config.get("expression"))
                query = f"SELECT *, {expression} AS {self._quote(column)} FROM ({query})"
            elif step.operation == "deduplicate":
                columns = config.get("columns")
                if not isinstance(columns, list) or not columns:
                    raise ValueError("deduplicate 需要非空 columns")
                partition = ", ".join(self._quote(str(item)) for item in columns)
                query = (
                    "SELECT * EXCLUDE (__fathom_row) FROM (SELECT *, "
                    f"row_number() OVER (PARTITION BY {partition}) AS __fathom_row "
                    f"FROM ({query})) WHERE __fathom_row = 1"
                )
            elif step.operation == "quality_check":
                quality_rules.append(config)
            elif step.operation == "onn_map":
                mappings.append(config)

        connection = duckdb.connect(":memory:")
        try:
            connection.execute("SET memory_limit = '256MB'")
            connection.execute("SET threads = 2")
            columns = [item[0] for item in connection.execute(f"DESCRIBE ({query})").fetchall()]
            rows = connection.execute(f"SELECT * FROM ({query}) LIMIT ?", [limit]).fetchall()
            total = connection.execute(f"SELECT count(*) FROM ({query})").fetchone()[0]
            quality = self._quality(connection, query, quality_rules)
        except duckdb.Error as error:
            raise ValueError(f"管道执行失败：{error}") from error
        finally:
            connection.close()

        result = {
            "run_id": f"pipe_{uuid4().hex[:16]}",
            "key": definition.key,
            "status": "passed" if all(item["passed"] for item in quality) else "failed",
            "source": definition.source,
            "row_count": total,
            "preview_count": len(rows),
            "columns": columns,
            "rows": [dict(zip(columns, row, strict=True)) for row in rows],
            "quality": quality,
            "onn_mappings": mappings,
            "sql": query,
            "limits": {"rows": limit, "memory": "256MB", "threads": 2},
        }
        now = datetime.now(UTC)
        with self._session_factory() as session:
            session.add(
                PipelineRunRecord(
                    run_id=result["run_id"],
                    pipeline_key=definition.key,
                    status=result["status"],
                    started_at=now,
                    finished_at=now,
                    result=result,
                )
            )
            session.commit()
        return result

    @staticmethod
    def _serialize(record: PipelineRecord) -> dict[str, Any]:
        return {
            "key": record.key,
            "label": record.label,
            "source": record.source,
            "target": record.target,
            "mode": record.mode,
            "cursor_field": record.cursor_field,
            "steps": record.steps,
            "published": record.published,
            "updated_at": record.updated_at.isoformat(),
        }

    def _source(self, key: str) -> DataSourceRecord:
        with self._session_factory() as session:
            record = session.get(DataSourceRecord, key)
            if record is None:
                raise LookupError(key)
            if not record.enabled:
                raise ValueError("数据源已停用")
            session.expunge(record)
            return record

    def _relation_sql(self, source: DataSourceRecord) -> str:
        config = source.configuration
        if source.connector_type == "file":
            path = self._path(config)
            literal = self._literal(str(path))
            suffix = path.suffix.casefold()
            if suffix in {".csv", ".tsv"}:
                return f"read_csv_auto({literal}, header=true)"
            if suffix in {".json", ".jsonl"}:
                return f"read_json_auto({literal})"
            if suffix == ".parquet":
                return f"read_parquet({literal})"
            raise ValueError("管道预览支持 CSV、TSV、JSON、JSONL、Parquet")
        if source.connector_type in {"sqlite", "duckdb"}:
            path = self._path(config)
            table = self._identifier(config, "table")
            literal = self._literal(str(path))
            function = "sqlite_scan" if source.connector_type == "sqlite" else "duckdb_scan"
            return f"{function}({literal}, {self._literal(table)})"
        raise ValueError("轻量内置执行器支持文件、SQLite 与 DuckDB；其他源通过外部调度器执行")

    @staticmethod
    def _quality(
        connection: duckdb.DuckDBPyConnection,
        query: str,
        rules: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        results = []
        for rule in rules:
            column = PipelineService._identifier(rule, "column")
            rule_type = str(rule.get("rule", "not_null"))
            if rule_type == "not_null":
                failures = connection.execute(
                    f"SELECT count(*) FROM ({query}) WHERE {PipelineService._quote(column)} IS NULL"
                ).fetchone()[0]
            elif rule_type == "unique":
                failures = connection.execute(
                    "SELECT count(*) - count(DISTINCT "
                    f"{PipelineService._quote(column)}) FROM ({query})"
                ).fetchone()[0]
            elif rule_type in {"min", "max"}:
                operator = "<" if rule_type == "min" else ">"
                value = rule.get("value")
                if not isinstance(value, (int, float)):
                    raise ValueError(f"{rule_type} 规则需要数值 value")
                failures = connection.execute(
                    f"SELECT count(*) FROM ({query}) WHERE "
                    f"{PipelineService._quote(column)} {operator} ?",
                    [value],
                ).fetchone()[0]
            else:
                raise ValueError(f"不支持的质量规则：{rule_type}")
            results.append(
                {
                    "rule": rule_type,
                    "column": column,
                    "failures": failures,
                    "passed": failures == 0,
                }
            )
        return results

    @staticmethod
    def _safe_expression(value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("表达式不能为空")
        try:
            parsed = sqlglot.parse_one(value, read="duckdb")
        except sqlglot.errors.ParseError as error:
            raise ValueError(f"无效表达式：{error}") from error
        forbidden = (exp.Subquery, exp.Select, exp.Table, exp.Command)
        if any(parsed.find(node) for node in forbidden):
            raise ValueError("表达式不能包含子查询、数据表或命令")
        return parsed.sql(dialect="duckdb")

    @staticmethod
    def _safe_type(value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("cast 需要 type")
        try:
            parsed = sqlglot.parse_one(f"CAST(NULL AS {value})", read="duckdb")
        except sqlglot.errors.ParseError as error:
            raise ValueError(f"无效数据类型：{error}") from error
        return parsed.args["to"].sql(dialect="duckdb")

    @staticmethod
    def _identifier(config: dict[str, Any], key: str) -> str:
        value = config.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"缺少 {key}")
        return value

    @staticmethod
    def _path(config: dict[str, Any]) -> Path:
        value = config.get("path")
        if not isinstance(value, str) or not value:
            raise ValueError("数据源需要 path")
        path = Path(value).expanduser().resolve()
        if not path.is_file():
            raise ValueError(f"数据文件不存在：{path}")
        return path

    @staticmethod
    def _quote(value: str) -> str:
        return '"' + value.replace('"', '""') + '"'

    @staticmethod
    def _literal(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"
