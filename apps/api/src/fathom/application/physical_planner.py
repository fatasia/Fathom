from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from fathom.domains.query.models import MqlQuery


class PhysicalPlanningError(ValueError):
    pass


class PhysicalPlanner:
    """Compile closed MQL + reviewed mapping into parameterized read-only SQL."""

    def compile(
        self,
        query: MqlQuery,
        mapping: dict[str, Any],
        *,
        connector_type: str,
        max_rows: int,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        if connector_type not in {"postgresql", "sqlite"}:
            raise PhysicalPlanningError(
                f"语义运行时暂不支持连接器执行：{connector_type}"
            )
        definition = mapping["definition"]
        dimensions = definition.get("dimension_columns", {})
        missing_dimensions = {
            item.field for item in query.filters if item.field not in dimensions
        }
        if missing_dimensions:
            raise PhysicalPlanningError(
                "映射缺少过滤维度：" + ", ".join(sorted(missing_dimensions))
            )
        quote = self._quote
        table = quote(definition["table_name"])
        if definition.get("schema_name"):
            table = f"{quote(definition['schema_name'])}.{table}"
        time_column = quote(definition["time_column"])
        value_column = quote(definition["value_column"])
        aggregation = definition.get("aggregation", "none")
        if aggregation == "none":
            selected_value = value_column
            group_by = ""
        elif aggregation == "count":
            selected_value = "COUNT(*)"
            group_by = f" GROUP BY {time_column}"
        else:
            selected_value = f"{aggregation.upper()}({value_column})"
            group_by = f" GROUP BY {time_column}"

        clauses: list[str] = []
        parameters: dict[str, Any] = {}
        object_parameters = []
        for index, object_id in enumerate(query.object_ids):
            name = f"object_{index}"
            object_parameters.append(f":{name}")
            parameters[name] = object_id
        clauses.append(
            f"{quote(definition['object_column'])} IN ({', '.join(object_parameters)})"
        )
        for index, (column, value) in enumerate(definition.get("static_filters", {}).items()):
            name = f"static_{index}"
            clauses.append(f"{quote(column)} = :{name}")
            parameters[name] = value
        range_start, range_end = self._range_bounds(query.time_range)
        if range_start is not None:
            clauses.append(f"{time_column} >= :range_start")
            parameters["range_start"] = range_start
        if range_end is not None:
            clauses.append(f"{time_column} < :range_end")
            parameters["range_end"] = range_end
        for index, item in enumerate(query.filters):
            column = quote(dimensions[item.field])
            if item.operator == "eq":
                name = f"filter_{index}"
                clauses.append(f"{column} = :{name}")
                parameters[name] = item.value
            elif item.operator == "in":
                values = item.value if isinstance(item.value, list) else [item.value]
                names = []
                for value_index, value in enumerate(values):
                    name = f"filter_{index}_{value_index}"
                    names.append(f":{name}")
                    parameters[name] = value
                clauses.append(f"{column} IN ({', '.join(names)})")
            else:
                raise PhysicalPlanningError(f"不支持过滤操作符：{item.operator}")
        limit = min(query.limit, max_rows)
        sql = (
            f"SELECT {time_column} AS period, {selected_value} AS value "
            f"FROM {table} WHERE {' AND '.join(clauses)}{group_by} "
            f"ORDER BY {time_column} DESC LIMIT :result_limit"
        )
        parameters["result_limit"] = limit
        logical = query.model_dump(mode="json")
        logical_hash = hashlib.sha256(
            json.dumps(logical, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        return {
            "kind": "relational_select",
            "logical_plan_hash": logical_hash,
            "mapping_id": mapping["mapping_id"],
            "source_key": mapping["source_key"],
            "connector_type": connector_type,
            "sql": sql,
            "parameters": parameters,
            "limits": {"max_rows": max_rows, "timeout_seconds": timeout_seconds},
            "read_only": True,
        }

    @staticmethod
    def _quote(identifier: str) -> str:
        return f'"{identifier}"'

    @staticmethod
    def _range_bounds(time_range: str) -> tuple[datetime | None, datetime | None]:
        now = datetime.now(UTC)
        if time_range == "latest":
            return None, None
        if time_range == "today":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            return start, start + timedelta(days=1)
        if time_range == "yesterday":
            end = now.replace(hour=0, minute=0, second=0, microsecond=0)
            return end - timedelta(days=1), end
        try:
            start = datetime.fromisoformat(time_range)
            if start.tzinfo is None:
                start = start.replace(tzinfo=UTC)
        except ValueError:
            raise PhysicalPlanningError(f"时间范围不可解析：{time_range}") from None
        return start, start + timedelta(days=1)

