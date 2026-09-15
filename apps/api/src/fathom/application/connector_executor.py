from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from fathom.application.data_sources import DataSourceService
from sqlalchemy import create_engine, text


class ConnectorExecutionError(RuntimeError):
    pass


class ConnectorExecutor:
    def __init__(self, data_sources: DataSourceService) -> None:
        self._data_sources = data_sources

    def execute(self, plan: dict[str, Any]) -> dict[str, Any]:
        sql = str(plan.get("sql", "")).strip()
        if not plan.get("read_only") or not sql.casefold().startswith("select "):
            raise ConnectorExecutionError("连接器仅接受由物理计划器生成的只读 SELECT")
        if ";" in sql:
            raise ConnectorExecutionError("物理计划不得包含多语句")
        source = self._data_sources.get_record(plan["source_key"])
        if not source.enabled:
            raise ConnectorExecutionError(f"数据源已禁用：{source.key}")
        started = perf_counter()
        if source.connector_type == "sqlite":
            rows = self._execute_sqlite(source.configuration, sql, plan["parameters"])
        elif source.connector_type == "postgresql":
            rows = self._execute_postgresql(
                source.key,
                sql,
                plan["parameters"],
                int(plan["limits"]["timeout_seconds"]),
            )
        else:
            raise ConnectorExecutionError(
                f"语义运行时暂不支持连接器：{source.connector_type}"
            )
        return {
            "rows": rows,
            "row_count": len(rows),
            "duration_ms": round((perf_counter() - started) * 1000, 3),
            "source_key": source.key,
            "connector_type": source.connector_type,
        }

    @staticmethod
    def _execute_sqlite(
        configuration: dict[str, Any], sql: str, parameters: dict[str, Any]
    ) -> list[dict[str, Any]]:
        raw_path = configuration.get("path")
        if not raw_path:
            raise ConnectorExecutionError("SQLite 数据源缺少 path")
        path = Path(str(raw_path)).expanduser().resolve()
        if not path.is_file():
            raise ConnectorExecutionError(f"SQLite 文件不存在：{path}")
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            serializable = {
                key: value.isoformat() if isinstance(value, (datetime, date)) else value
                for key, value in parameters.items()
            }
            return [dict(row) for row in connection.execute(sql, serializable).fetchall()]
        except sqlite3.Error as error:
            raise ConnectorExecutionError(str(error)) from error
        finally:
            connection.close()

    def _execute_postgresql(
        self,
        source_key: str,
        sql: str,
        parameters: dict[str, Any],
        timeout_seconds: int,
    ) -> list[dict[str, Any]]:
        engine = create_engine(self._data_sources.sqlalchemy_url(source_key), pool_pre_ping=True)
        try:
            with engine.connect() as connection, connection.begin():
                connection.execute(text("SET TRANSACTION READ ONLY"))
                connection.execute(
                    text("SELECT set_config('statement_timeout', :timeout_ms, true)"),
                    {"timeout_ms": str(timeout_seconds * 1000)},
                )
                result = connection.execute(text(sql), parameters)
                return [
                    {key: self._json_value(value) for key, value in row.items()}
                    for row in result.mappings().all()
                ]
        except Exception as error:
            raise ConnectorExecutionError(str(error)) from error
        finally:
            engine.dispose()

    @staticmethod
    def _json_value(value: Any) -> Any:
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        return value
