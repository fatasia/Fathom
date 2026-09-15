from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient
from fathom.config import Settings
from fathom.main import create_app

METRICS = {
    "order_fulfillment_rate": 87.4,
    "oee": 78.2,
    "actual_output": 874.0,
    "planned_output": 1000.0,
    "downtime_minutes": 96.0,
}


def main() -> None:
    if not os.getenv("FATHOM_DEMO_PG_PASSWORD"):
        raise SystemExit(
            "Set FATHOM_DEMO_PG_PASSWORD before configuration; the password is not persisted."
        )
    settings = Settings(
        environment="development",
        database_url="sqlite:///./data/fathom.db",
        semantic_directory=Path("semantic"),
    )
    with TestClient(create_app(settings)) as client:
        source = client.put(
            "/api/v1/data-sources/postgres_runtime_demo",
            json={
                "key": "postgres_runtime_demo",
                "name": "本机 PostgreSQL 语义运行时",
                "connector_type": "postgresql",
                "configuration": {
                    "host": "127.0.0.1",
                    "port": 5432,
                    "username": "postgres",
                    "database": "postgres",
                    "schema": "fathom_p0p3_demo",
                },
                "secret_reference": "env://FATHOM_DEMO_PG_PASSWORD",
                "enabled": True,
            },
        )
        source.raise_for_status()
        tested = client.post("/api/v1/data-sources/postgres_runtime_demo/test")
        tested.raise_for_status()
        client.post(
            "/api/v1/ingestion/objects",
            json=[
                {
                    "object_id": "line_01",
                    "object_type": "production_line",
                    "label": "一号线",
                    "source_key": "postgres_runtime_demo",
                    "attributes": {"plant": "华东工厂", "line_code": "LINE-01"},
                    "state": "active",
                }
            ],
        ).raise_for_status()
        client.post(
            "/api/v1/runtime/object-identities",
            json={
                "canonical_object_id": "line_01",
                "source_key": "postgres_runtime_demo",
                "external_object_id": "line_01",
                "owner": "master-data-owner",
                "metadata": {"system": "PostgreSQL demo"},
            },
        ).raise_for_status()
        existing = {
            item["key"]: item
            for item in client.get("/api/v1/runtime/mappings").json()["items"]
        }
        for metric, expected in METRICS.items():
            mapping_key = f"{metric}.postgres_runtime_demo"
            if mapping_key not in existing:
                mapping = {
                    "key": mapping_key,
                    "metric_key": metric,
                    "source_key": "postgres_runtime_demo",
                    "version": 1,
                    "owner": "production-excellence",
                    "schema_name": "fathom_p0p3_demo",
                    "table_name": "metric_observations",
                    "object_column": "object_id",
                    "value_column": "value",
                    "time_column": "observed_at",
                    "dimension_columns": {
                        "production_line": "production_line",
                        "shift": "shift",
                    },
                    "static_filters": {"metric_key": metric},
                    "aggregation": "none",
                    "priority": 500,
                }
                client.put(
                    f"/api/v1/runtime/mappings/{mapping_key}/versions/1", json=mapping
                ).raise_for_status()
                client.post(
                    f"/api/v1/runtime/mappings/{mapping_key}/versions/1/publish"
                ).raise_for_status()
            quality_key = f"{metric}.runtime.quality"
            client.put(
                f"/api/v1/runtime/quality-contracts/{quality_key}",
                json={
                    "key": quality_key,
                    "mapping_key": mapping_key,
                    "owner": "data-governance",
                    "strict": True,
                    "checks": [
                        {"kind": "not_null", "field": "value"},
                        {"kind": "min_rows", "field": "value", "value": 1},
                    ],
                },
            ).raise_for_status()
            for variant in range(4):
                case_key = f"runtime.{metric}.{variant}"
                client.put(
                    f"/api/v1/runtime/golden-cases/{case_key}",
                    json={
                        "key": case_key,
                        "question": f"一号线 {metric} 运行时黄金问题 {variant + 1}",
                        "query": {
                            "metric": metric,
                            "object_ids": ["line_01"],
                            "limit": 1,
                        },
                        "expected_value": expected,
                        "tolerance": 0.0001,
                    },
                ).raise_for_status()
        requirement_candidate = client.post(
            "/api/v1/runtime/requirements/explore",
            json={
                "text": (
                    "生产经理需要查询一号线 OEE，并说明数据来源。\n"
                    "为什么昨天 OEE 下降？"
                ),
                "source_uri": "demo://production/oee-review",
                "owner": "production-manager",
            },
        )
        requirement_candidate.raise_for_status()
        requirement = requirement_candidate.json()["candidate"]
        client.post("/api/v1/runtime/requirements", json=requirement).raise_for_status()
        client.post(
            f"/api/v1/runtime/requirements/{requirement['key']}/review",
            json={
                "decision": "approved",
                "reviewer": "semantic-owner",
                "comment": "演示域验收需求",
            },
        ).raise_for_status()
        capabilities = {
            item["key"]
            for item in client.get("/api/v1/runtime/capabilities").json()["items"]
        }
        for metric in METRICS:
            capability_key = f"semantic.metric.{metric}"
            if capability_key not in capabilities:
                client.post(
                    "/api/v1/runtime/capabilities/compile",
                    json={
                        "metric_key": metric,
                        "owner": "semantic-owner",
                        "minimum_role": "viewer",
                        "publish": True,
                    },
                ).raise_for_status()
        evaluation = client.post("/api/v1/runtime/evaluations")
        evaluation.raise_for_status()
        report = evaluation.json()
        print(
            f"Configured PostgreSQL runtime: {report['passed_count']}/{report['total']} "
            f"golden cases passed; accuracy={report['accuracy']:.2%}"
        )


if __name__ == "__main__":
    main()
