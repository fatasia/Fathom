from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from fathom.config import Settings
from fathom.main import create_app

METRICS = {
    "order_fulfillment_rate": (93.6, 87.4),
    "oee": (84.7, 78.2),
    "actual_output": (936.0, 874.0),
    "planned_output": (1000.0, 1000.0),
    "downtime_minutes": (42.0, 96.0),
}


def make_client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            Settings(
                environment="test",
                database_url=f"sqlite:///{tmp_path / 'runtime-state.db'}",
                semantic_directory=Path("semantic"),
            )
        )
    )


def create_fact_database(path: Path, object_id: str = "line_01") -> None:
    today = datetime.now(UTC).replace(hour=8, minute=0, second=0, microsecond=0)
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE metric_observations (
            metric_key TEXT NOT NULL,
            object_id TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            value REAL NOT NULL,
            shift TEXT NOT NULL,
            production_line TEXT NOT NULL
        )
        """
    )
    rows = []
    for metric, (previous, yesterday) in METRICS.items():
        rows.extend(
            [
                (
                    metric,
                    object_id,
                    (today - timedelta(days=2)).isoformat(),
                    previous,
                    "day",
                    object_id,
                ),
                (
                    metric,
                    object_id,
                    (today - timedelta(days=1)).isoformat(),
                    yesterday,
                    "day",
                    object_id,
                ),
            ]
        )
    connection.executemany(
        "INSERT INTO metric_observations VALUES (?, ?, ?, ?, ?, ?)", rows
    )
    connection.commit()
    connection.close()


def register_source(client: TestClient, key: str, path: Path) -> None:
    response = client.put(
        f"/api/v1/data-sources/{key}",
        json={
            "key": key,
            "name": f"Runtime facts {key}",
            "connector_type": "sqlite",
            "configuration": {"path": str(path)},
            "enabled": True,
        },
    )
    assert response.status_code == 200, response.text
    assert client.post(f"/api/v1/data-sources/{key}/test").json()["status"] == "online"


def register_mapping(
    client: TestClient,
    metric: str,
    source_key: str,
    *,
    mapping_key: str | None = None,
    priority: int = 100,
    schema_name: str | None = None,
) -> None:
    key = mapping_key or f"{metric}.{source_key}"
    payload = {
        "key": key,
        "metric_key": metric,
        "source_key": source_key,
        "version": 1,
        "owner": "runtime-test",
        "schema_name": schema_name,
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
        "priority": priority,
    }
    saved = client.put(f"/api/v1/runtime/mappings/{key}/versions/1", json=payload)
    assert saved.status_code == 200, saved.text
    published = client.post(f"/api/v1/runtime/mappings/{key}/versions/1/publish")
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"


def test_p0_to_p3_semantic_runtime_vertical_slice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    facts = tmp_path / "facts.db"
    create_fact_database(facts)
    monkeypatch.setenv("FATHOM_ACTION_APPROVAL_TOKEN", "runtime-approved")
    with make_client(tmp_path) as client:
        register_source(client, "facts_primary", facts)
        for metric in METRICS:
            register_mapping(client, metric, "facts_primary")

        quality = client.put(
            "/api/v1/runtime/quality-contracts/oee.quality",
            json={
                "key": "oee.quality",
                "mapping_key": "oee.facts_primary",
                "owner": "data-quality",
                "strict": True,
                "checks": [
                    {"kind": "not_null", "field": "value"},
                    {"kind": "min", "field": "value", "value": 0},
                    {"kind": "max", "field": "value", "value": 100},
                    {"kind": "min_rows", "field": "value", "value": 1},
                ],
            },
        )
        assert quality.status_code == 200, quality.text

        runtime = client.post(
            "/api/v1/runtime/query",
            json={
                "query": {"metric": "oee", "object_ids": ["line_01"], "limit": 2}
            },
        )
        assert runtime.status_code == 200, runtime.text
        runtime_body = runtime.json()
        assert runtime_body["rows"][0]["value"] == 78.2
        assert runtime_body["compiled"]["template"] == "mapping.oee.facts_primary@1"
        assert runtime_body["quality"]["passed"] is True
        assert runtime_body["receipt"]["result_hash"]
        assert runtime_body["policy_decision"]["effect"] == "allow"

        ask = client.post("/api/v1/query/ask", json={"question": "一号线 OEE 是多少？"})
        assert ask.status_code == 200, ask.text
        ask_body = ask.json()
        assert ask_body["data"]["current"] == 78.2
        assert ask_body["data"]["execution_receipt"]["source_key"] == "facts_primary"
        assert any(item["type"] == "execution_receipt" for item in ask_body["evidence"])

        requirement_candidate = client.post(
            "/api/v1/runtime/requirements/explore",
            json={
                "text": "生产经理需要查询一号线 OEE。为什么昨天 OEE 下降？必须有真实数据证据。",
                "source_uri": "meeting://production/001",
                "owner": "production-manager",
            },
        ).json()["candidate"]
        assert "oee" in requirement_candidate["linked_assets"]
        requirement = client.post(
            "/api/v1/runtime/requirements", json=requirement_candidate
        )
        assert requirement.status_code == 200, requirement.text
        impact = client.get(
            f"/api/v1/runtime/impact?node=requirement:{requirement_candidate['key']}"
        ).json()
        assert "semantic:oee" in impact["nodes"]

        for metric, (_, latest) in METRICS.items():
            for variant in range(4):
                case_key = f"golden.{metric}.{variant}"
                saved_case = client.put(
                    f"/api/v1/runtime/golden-cases/{case_key}",
                    json={
                        "key": case_key,
                        "question": f"一号线 {metric} 黄金问题 {variant + 1}",
                        "query": {
                            "metric": metric,
                            "object_ids": ["line_01"],
                            "limit": 1,
                        },
                        "expected_value": latest,
                        "tolerance": 0.0001,
                    },
                )
                assert saved_case.status_code == 200, saved_case.text
        evaluation = client.post("/api/v1/runtime/evaluations")
        assert evaluation.status_code == 200, evaluation.text
        assert evaluation.json()["total"] == 20
        assert evaluation.json()["passed"] is True

        capability = client.post(
            "/api/v1/runtime/capabilities/semantic.query/invoke",
            json={
                "arguments": {
                    "query": {"metric": "oee", "object_ids": ["line_01"], "limit": 1}
                }
            },
        )
        assert capability.status_code == 200, capability.text
        assert capability.json()["result"]["rows"][0]["value"] == 78.2

        denied_action = client.post(
            "/api/v1/runtime/capabilities/action.create_case/invoke",
            json={
                "arguments": {
                    "object_id": "line_01",
                    "title": "检查 OEE 下降",
                    "idempotency_key": "oee-case-001",
                }
            },
        )
        assert denied_action.status_code == 403
        action_payload = {
            "arguments": {
                "object_id": "line_01",
                "title": "检查 OEE 下降",
                "idempotency_key": "oee-case-001",
                "payload": {"evidence_receipt": runtime_body["receipt"]["receipt_id"]},
            },
            "approval_token": "runtime-approved",
        }
        action = client.post(
            "/api/v1/runtime/capabilities/action.create_case/invoke", json=action_payload
        )
        replay = client.post(
            "/api/v1/runtime/capabilities/action.create_case/invoke", json=action_payload
        )
        assert action.status_code == 200, action.text
        assert replay.json()["result"]["idempotent_replay"] is True

        reverse = client.post(
            "/api/v1/runtime/reverse-mappings",
            json={
                "source_key": "facts_primary",
                "table_name": "metric_observations",
                "owner": "data-owner",
            },
        )
        assert reverse.status_code == 200, reverse.text
        assert len(reverse.json()["candidates"]) >= len(METRICS)

        preferred = tmp_path / "preferred.db"
        create_fact_database(preferred)
        register_source(client, "facts_preferred", preferred)
        register_mapping(
            client,
            "oee",
            "facts_preferred",
            mapping_key="oee.preferred",
            priority=500,
        )
        preferred.unlink()
        routed = client.post(
            "/api/v1/runtime/query",
            json={"query": {"metric": "oee", "object_ids": ["line_01"], "limit": 1}},
        )
        assert routed.status_code == 200, routed.text
        assert routed.json()["mapping"]["source_key"] == "facts_primary"
        assert routed.json()["route_attempts"][0]["source_key"] == "facts_preferred"

        mcp_tools = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        ).json()["result"]["tools"]
        assert "fathom.runtime.semantic.query" in {item["name"] for item in mcp_tools}


def test_bcd_lightweight_governed_loops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    facts = tmp_path / "facts.db"
    external_facts = tmp_path / "mes-facts.db"
    create_fact_database(facts)
    create_fact_database(external_facts, object_id="MES-L01")
    monkeypatch.setenv("FATHOM_ACTION_APPROVAL_TOKEN", "runtime-approved")

    with make_client(tmp_path) as client:
        register_source(client, "facts_primary", facts)
        register_source(client, "mes_external", external_facts)
        register_mapping(client, "oee", "facts_primary")
        register_mapping(
            client,
            "oee",
            "mes_external",
            mapping_key="oee.mes_external",
            priority=900,
        )

        existing_requirement = client.post(
            "/api/v1/runtime/requirements",
            json={
                "key": "requirement.oee.target80",
                "title": "OEE 目标口径",
                "source_uri": "policy://production/oee",
                "statements": ["生产线 OEE 目标必须达到 80%。"],
                "acceptance_questions": ["一号线 OEE 是否达到 80%？"],
                "linked_assets": ["oee"],
                "review_status": "approved",
                "owner": "production-owner",
            },
        )
        assert existing_requirement.status_code == 200, existing_requirement.text
        explored = client.post(
            "/api/v1/runtime/requirements/explore",
            json={
                "text": "生产经理要求 OEE 目标必须达到 85%。\n需要查询一号线 OEE。",
                "source_uri": "meeting://production/target-review",
                "owner": "production-manager",
            },
        )
        assert explored.status_code == 200, explored.text
        explored_body = explored.json()
        assert explored_body["candidate"]["citations"][0]["source_uri"].startswith(
            "meeting://"
        )
        assert explored_body["clarification_questions"]
        assert explored_body["conflicts"][0]["kind"] == "potential_numeric_conflict"
        candidate = explored_body["candidate"]
        saved = client.post("/api/v1/runtime/requirements", json=candidate)
        assert saved.status_code == 200, saved.text
        reviewed = client.post(
            f"/api/v1/runtime/requirements/{candidate['key']}/review",
            json={
                "decision": "approved",
                "reviewer": "semantic-owner",
                "comment": "按新年度目标批准",
            },
        )
        assert reviewed.status_code == 200, reviewed.text
        assert reviewed.json()["definition"]["review_status"] == "approved"

        identity = client.post(
            "/api/v1/runtime/object-identities",
            json={
                "canonical_object_id": "line_01",
                "source_key": "mes_external",
                "external_object_id": "MES-L01",
                "owner": "master-data-owner",
                "metadata": {"system": "MES"},
            },
        )
        assert identity.status_code == 200, identity.text
        routed = client.post(
            "/api/v1/runtime/query",
            json={"query": {"metric": "oee", "object_ids": ["line_01"], "limit": 1}},
        )
        assert routed.status_code == 200, routed.text
        routed_body = routed.json()
        assert routed_body["mapping"]["source_key"] == "mes_external"
        assert routed_body["compiled"]["parameters"]["object_0"] == "MES-L01"
        assert routed_body["receipt"]["physical_plan"]["object_identity_map"] == {
            "line_01": "MES-L01"
        }

        sql_candidates = client.post(
            "/api/v1/runtime/reverse-assets",
            json={
                "kind": "sql",
                "source_key": "facts_primary",
                "owner": "integration-owner",
                "content": (
                    "SELECT object_id, observed_at, value FROM metric_observations "
                    "WHERE metric_key = 'oee'"
                ),
            },
        )
        assert sql_candidates.status_code == 200, sql_candidates.text
        assert "oee" in sql_candidates.json()["matched_metrics"]
        assert sql_candidates.json()["mapping_candidates"][0]["status"] == "candidate"

        api_candidates = client.post(
            "/api/v1/runtime/reverse-assets",
            json={
                "kind": "openapi",
                "owner": "integration-owner",
                "content": {
                    "openapi": "3.1.0",
                    "paths": {
                        "/maintenance/cases": {
                            "post": {
                                "operationId": "createMaintenanceCase",
                                "summary": "创建维修工单",
                            }
                        }
                    },
                },
            },
        )
        assert api_candidates.status_code == 200, api_candidates.text
        api_capability = api_candidates.json()["capability_candidates"][0]
        assert api_capability["approval_required"] is True
        assert api_capability["status"] == "candidate"

        compiled = client.post(
            "/api/v1/runtime/capabilities/compile",
            json={
                "metric_key": "oee",
                "owner": "semantic-owner",
                "minimum_role": "viewer",
                "publish": True,
            },
        )
        assert compiled.status_code == 200, compiled.text
        assert compiled.json()["definition"]["binding"] == {"metric": "oee"}
        compiled_key = compiled.json()["key"]
        invoked = client.post(
            f"/api/v1/runtime/capabilities/{compiled_key}/invoke",
            json={"arguments": {"object_ids": ["line_01"], "limit": 1}},
        )
        assert invoked.status_code == 200, invoked.text
        assert invoked.json()["result"]["rows"][0]["value"] == 78.2
        override = client.post(
            f"/api/v1/runtime/capabilities/{compiled_key}/invoke",
            json={
                "arguments": {
                    "metric": "actual_output",
                    "object_ids": ["line_01"],
                    "limit": 1,
                }
            },
        )
        assert override.status_code == 422

        notification_payload = {
            "arguments": {
                "object_id": "line_01",
                "title": "OEE 目标口径已调整",
                "idempotency_key": "notice-oee-001",
                "payload": {"channel": "internal", "requirement": candidate["key"]},
            },
            "approval_token": "runtime-approved",
        }
        notification = client.post(
            "/api/v1/runtime/capabilities/action.send_notification/invoke",
            json=notification_payload,
        )
        notification_replay = client.post(
            "/api/v1/runtime/capabilities/action.send_notification/invoke",
            json=notification_payload,
        )
        assert notification.status_code == 200, notification.text
        assert notification.json()["result"]["result"]["state"] == "queued"
        assert notification_replay.json()["result"]["idempotent_replay"] is True

        mcp_tools = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        ).json()["result"]["tools"]
        assert f"fathom.runtime.{compiled_key}" in {item["name"] for item in mcp_tools}


@pytest.mark.skipif(
    not os.getenv("FATHOM_TEST_POSTGRES_PASSWORD"),
    reason="Set FATHOM_TEST_POSTGRES_PASSWORD to run the local PostgreSQL integration test",
)
def test_postgresql_mapping_executes_read_only_and_records_receipt(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        source = client.put(
            "/api/v1/data-sources/postgres_demo",
            json={
                "key": "postgres_demo",
                "name": "Local PostgreSQL runtime demo",
                "connector_type": "postgresql",
                "configuration": {
                    "host": "127.0.0.1",
                    "port": 5432,
                    "username": "postgres",
                    "database": "postgres",
                    "schema": "fathom_p0p3_demo",
                },
                "secret_reference": "env://FATHOM_TEST_POSTGRES_PASSWORD",
                "enabled": True,
            },
        )
        assert source.status_code == 200, source.text
        tested = client.post("/api/v1/data-sources/postgres_demo/test")
        assert tested.status_code == 200, tested.text
        assert tested.json()["status"] == "online"
        register_mapping(
            client,
            "oee",
            "postgres_demo",
            mapping_key="oee.postgres_demo",
            schema_name="fathom_p0p3_demo",
        )
        result = client.post(
            "/api/v1/runtime/query",
            json={"query": {"metric": "oee", "object_ids": ["line_01"], "limit": 2}},
        )
        assert result.status_code == 200, result.text
        body = result.json()
        assert body["rows"][0]["value"] == 78.2
        assert body["receipt"]["source_key"] == "postgres_demo"
        assert body["receipt"]["status"] == "completed"
        assert body["receipt"]["physical_plan"]["read_only"] is True
        assert "123456" not in str(body)
