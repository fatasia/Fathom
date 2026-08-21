import json
import ssl
from pathlib import Path

from fastapi.testclient import TestClient
from fathom.application.model_gateway import SecretStore
from fathom.application.security import token_hash
from fathom.config import Settings, load_settings
from fathom.main import create_app


def make_client(tmp_path: Path) -> TestClient:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'fathom-test.db'}",
        semantic_directory=Path("semantic"),
    )
    return TestClient(create_app(settings))


def test_health_and_capabilities(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        health = client.get("/api/v1/health")
        capabilities = client.get("/api/v1/system/capabilities")
    assert health.status_code == 200
    assert health.json()["status"] == "healthy"
    assert capabilities.json()["sqlite"] is True
    assert capabilities.json()["duckdb"]["enabled"] is True


def test_semantics_expose_uino_six_elements(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.get("/api/v1/semantics/overview")
    assert response.status_code == 200
    assert set(response.json()["counts"]) == {
        "object",
        "relation",
        "attribute",
        "metric",
        "event",
        "policy",
    }


def test_ask_builds_validated_plan_and_evidence(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.post(
            "/api/v1/query/ask",
            json={"question": "为什么一号线昨天订单达成率下降？"},
        )
    result = response.json()
    assert response.status_code == 200
    assert result["status"] == "completed"
    assert result["plan"]["status"] == "ready"
    assert result["plan"]["binding"]["metric"] == "order_fulfillment_rate"
    assert result["data"]["delta"] == -6.2
    assert len(result["evidence"]) >= 3


def test_unknown_metric_stops_before_execution(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.post("/api/v1/query/ask", json={"question": "一号线怎么样？"})
    result = response.json()
    assert result["status"] == "needs_clarification"
    assert result["plan"]["binding"] is None


def test_abc_uses_uino_acquire_build_compute(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.post(
            "/api/v1/query/ask",
            json={"question": "为什么一号线昨天订单达成率下降？"},
        )
    stages = response.json()["plan"]["abc"]
    assert [(stage["code"], stage["name"]) for stage in stages] == [
        ("A", "Acquire"),
        ("B", "Build"),
        ("C", "Compute"),
    ]


def test_sql_template_rejects_mutation(tmp_path: Path) -> None:
    payload = {
        "key": "unsafe.delete",
        "label": "危险模板",
        "description": "should be rejected",
        "dialect": "sqlite",
        "sql_text": "DELETE FROM events",
        "parameters": [],
        "published": False,
    }
    with make_client(tmp_path) as client:
        response = client.post("/api/v1/tools/sql-templates/validate", json=payload)
    assert response.status_code == 200
    assert response.json()["safe"] is False


def test_sql_template_versions_and_read_only_preview(tmp_path: Path) -> None:
    payload = {
        "key": "metric.oee_preview",
        "label": "OEE 观测预览",
        "description": "按对象读取 OEE",
        "dialect": "sqlite",
        "sql_text": (
            "SELECT object_id, value FROM metric_observations "
            "WHERE metric_key = :metric_key ORDER BY observed_at DESC"
        ),
        "parameters": ["metric_key"],
        "published": True,
    }
    with make_client(tmp_path) as client:
        saved = client.put("/api/v1/tools/sql-templates/metric.oee_preview", json=payload)
        preview = client.post(
            "/api/v1/tools/sql-templates/metric.oee_preview/preview",
            json={"parameters": {"metric_key": "oee"}, "limit": 10},
        )
        versions = client.get("/api/v1/tools/sql-templates/metric.oee_preview/versions")
    assert saved.status_code == 200
    assert preview.status_code == 200, preview.text
    assert preview.json()["row_count"] == 2
    assert preview.json()["rows"][0]["value"] == 78.2
    assert versions.json()["items"][0]["version"] == 1


def test_restricted_python_extension_validates_publishes_and_runs(tmp_path: Path) -> None:
    payload = {
        "key": "quality.normalize",
        "label": "质量归一化",
        "code": (
            "def transform(input_data):\n"
            "    value = float(input_data.get('value', 0))\n"
            "    return {'normalized': round(value / 100, 4)}\n"
        ),
        "timeout_seconds": 5,
        "memory_mb": 128,
        "published": True,
    }
    with make_client(tmp_path) as client:
        saved = client.put("/api/v1/python-extensions/quality.normalize", json=payload)
        executed = client.post(
            "/api/v1/python-extensions/quality.normalize/runs",
            json={"input_data": {"value": 82.5}},
        )
        rejected = client.post(
            "/api/v1/python-extensions/validate",
            json={**payload, "code": "import os\ndef transform(input_data):\n    return {}"},
        )
    assert saved.status_code == 200, saved.text
    assert executed.status_code == 200, executed.text
    assert executed.json()["output"] == {"normalized": 0.825}
    assert rejected.json()["valid"] is False
    assert "os" in rejected.json()["errors"][0]


def test_internal_knowledge_ingest_search_and_ask(tmp_path: Path) -> None:
    knowledge_base = {
        "key": "quality.manuals",
        "name": "质量作业知识",
        "kind": "internal",
        "configuration": {},
        "enabled": True,
    }
    document = {
        "title": "首件检验规范",
        "content": "首件检验必须在换线、换模和工艺参数调整后执行，并保留检验记录。",
        "source_uri": "manual://quality/first-article",
        "metadata": {"owner": "质量部"},
    }
    with make_client(tmp_path) as client:
        saved = client.put("/api/v1/knowledge-bases/quality.manuals", json=knowledge_base)
        ingested = client.post(
            "/api/v1/knowledge-bases/quality.manuals/documents", json=document
        )
        searched = client.post(
            "/api/v1/knowledge/search",
            json={"query": "什么时候必须做首件检验？", "top_k": 3},
        )
        asked = client.post(
            "/api/v1/query/ask", json={"question": "什么时候必须做首件检验？"}
        )
    assert saved.status_code == 200, saved.text
    assert ingested.status_code == 200, ingested.text
    assert ingested.json()["chunk_count"] == 1
    assert searched.status_code == 200, searched.text
    assert searched.json()["items"][0]["source_uri"] == "manual://quality/first-article"
    assert asked.status_code == 200, asked.text
    assert asked.json()["status"] == "completed"
    assert asked.json()["plan"]["intent"] == "knowledge_search"
    assert asked.json()["evidence"][0]["type"] == "knowledge"


def test_external_knowledge_rejects_inline_secret(tmp_path: Path) -> None:
    payload = {
        "key": "enterprise.knowledge",
        "name": "企业知识平台",
        "kind": "external",
        "configuration": {
            "endpoint": "https://knowledge.example.test/search",
            "api_key": "must-not-be-stored",
        },
        "enabled": True,
    }
    with make_client(tmp_path) as client:
        response = client.put("/api/v1/knowledge-bases/enterprise.knowledge", json=payload)
    assert response.status_code == 422
    assert "env://" in response.text


def test_backup_contains_database_and_semantics(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'backup-test.db'}",
        backup_directory=tmp_path / "backups",
        semantic_directory=Path("semantic"),
    )
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/v1/system/backups")
        listed = client.get("/api/v1/system/backups")
    assert response.status_code == 200
    assert response.json()["name"].endswith(".zip")
    assert listed.json()["items"][0]["name"] == response.json()["name"]


def test_import_preview_and_tdengine_connector_catalog(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        preview = client.post(
            "/api/v1/imports/preview",
            files={"file": ("events.csv", "id,event\n1,downtime\n", "text/csv")},
        )
        connectors = client.get("/api/v1/data-sources/types")
    assert preview.status_code == 200
    assert preview.json()["columns"] == ["id", "event"]
    assert "tdengine" in {item["key"] for item in connectors.json()["items"]}
    tdengine = next(item for item in connectors.json()["items"] if item["key"] == "tdengine")
    assert tdengine["operations"] == ["test", "discover", "scaffold"]
    assert "driver_available" in tdengine


def test_operational_datasets_export_as_utf8_csv(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        objects = client.get("/api/v1/exports/objects.csv")
        metrics = client.get("/api/v1/exports/metrics.csv")
        events = client.get("/api/v1/exports/events.csv")
    assert objects.status_code == 200
    assert objects.content.startswith(b"\xef\xbb\xbf")
    assert "line_01" in objects.content.decode("utf-8-sig")
    assert "order_fulfillment_rate" in metrics.content.decode("utf-8-sig")
    assert "unplanned_downtime" in events.content.decode("utf-8-sig")


def test_dify_tool_schema_is_downloadable(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.get("/api/v1/integrations/dify/openapi.yaml")
    assert response.status_code == 200
    assert "openapi: 3.0.3" in response.text
    assert "ask_data" in response.text
    assert "search_enterprise_knowledge" in response.text


def test_dbt_semantic_layer_import_creates_onn_candidate(tmp_path: Path) -> None:
    dbt_yaml = """
semantic_models:
  - name: production_orders
    model: ref('fct_production_orders')
    entities:
      - name: order_id
        type: primary
    dimensions:
      - name: production_line
        type: categorical
    measures:
      - name: completed_orders
        agg: sum
        expr: completed_count
metrics:
  - name: order_fulfillment_rate
    label: 订单达成率
    type: ratio
    type_params:
      expr: completed_orders / planned_orders
meta:
  owner: production-data
  domain: manufacturing
"""
    with make_client(tmp_path) as client:
        response = client.post(
            "/api/v1/imports/preview",
            files={"file": ("semantic_models.yml", dbt_yaml, "application/yaml")},
        )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["format"] == "dbt-semantic-layer-yaml"
    candidate = result["candidate_contract"]
    assert candidate["domain"] == "manufacturing"
    assert {asset["kind"] for asset in candidate["assets"]} >= {
        "object",
        "attribute",
        "metric",
    }


def test_file_connector_discovers_schema_and_scaffolds_onn(tmp_path: Path) -> None:
    source_file = tmp_path / "equipment.csv"
    source_file.write_text("equipment_id,name,criticality\nE-01,Press,A\n", encoding="utf-8")
    payload = {
        "key": "equipment_file",
        "name": "设备文件",
        "connector_type": "file",
        "configuration": {"path": str(source_file)},
        "enabled": True,
    }
    with make_client(tmp_path) as client:
        saved = client.put("/api/v1/data-sources/equipment_file", json=payload)
        tested = client.post("/api/v1/data-sources/equipment_file/test")
        discovered = client.post("/api/v1/data-sources/equipment_file/discover")
        scaffold = client.post("/api/v1/data-sources/equipment_file/scaffold")
    assert saved.status_code == 200
    assert tested.json()["status"] == "online"
    columns = discovered.json()["tables"][0]["columns"]
    assert [column["name"] for column in columns] == [
        "equipment_id",
        "name",
        "criticality",
    ]
    assert scaffold.json()["objects"][0]["status"] == "candidate"
    assert len(scaffold.json()["attributes"]) == 3


def test_mqtt_declared_topics_discover_without_consuming_messages(tmp_path: Path) -> None:
    payload = {
        "key": "plant_mqtt",
        "name": "车间 MQTT",
        "connector_type": "mqtt",
        "configuration": {
            "host": "127.0.0.1",
            "topics": [
                {
                    "name": "plant/line01/equipment/+/telemetry",
                    "schema": {"equipment_id": "VARCHAR", "temperature": "DOUBLE"},
                }
            ],
        },
        "enabled": True,
    }
    with make_client(tmp_path) as client:
        client.put("/api/v1/data-sources/plant_mqtt", json=payload)
        discovered = client.post("/api/v1/data-sources/plant_mqtt/discover")
        scaffold = client.post("/api/v1/data-sources/plant_mqtt/scaffold")
    assert discovered.status_code == 200, discovered.text
    assert discovered.json()["kind"] == "mqtt_topics"
    assert discovered.json()["tables"][0]["columns"][1]["name"] == "temperature"
    assert scaffold.json()["objects"][0]["status"] == "candidate"


def test_rest_connector_infers_schema_from_bounded_json_sample(tmp_path: Path, monkeypatch) -> None:
    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, limit: int) -> bytes:
            return b'{"data":[{"equipment_id":"E-01","temperature":42.5,"online":true}]}'

    monkeypatch.setattr(
        "fathom.application.data_sources.urlopen", lambda request, timeout: FakeResponse()
    )
    payload = {
        "key": "equipment_api",
        "name": "设备 REST",
        "connector_type": "rest",
        "configuration": {
            "endpoint": "https://api.example.com/equipment",
            "items_path": "data",
            "resource_name": "equipment",
        },
        "enabled": True,
    }
    with make_client(tmp_path) as client:
        client.put("/api/v1/data-sources/equipment_api", json=payload)
        discovered = client.post("/api/v1/data-sources/equipment_api/discover")
    assert discovered.status_code == 200, discovered.text
    assert discovered.json()["tables"][0]["name"] == "equipment"
    assert discovered.json()["tables"][0]["columns"] == [
        {"name": "equipment_id", "type": "VARCHAR"},
        {"name": "online", "type": "BOOLEAN"},
        {"name": "temperature", "type": "DOUBLE"},
    ]


def test_data_source_rejects_nested_or_url_embedded_secrets(tmp_path: Path) -> None:
    base = {
        "key": "unsafe_source",
        "name": "危险连接",
        "connector_type": "rest",
        "enabled": True,
    }
    with make_client(tmp_path) as client:
        nested = client.put(
            "/api/v1/data-sources/unsafe_source",
            json={
                **base,
                "configuration": {
                    "endpoint": "https://example.com",
                    "headers": {"Authorization": "Bearer leaked"},
                },
            },
        )
        embedded = client.put(
            "/api/v1/data-sources/unsafe_source",
            json={
                **base,
                "configuration": {"endpoint": "https://user:secret@example.com/data"},
            },
        )
    assert nested.status_code == 422
    assert embedded.status_code == 422


def test_pipeline_preview_executes_transformations_and_quality(tmp_path: Path) -> None:
    source_file = tmp_path / "production.csv"
    source_file.write_text(
        "equipment_id,good_count,total_count\nE-01,95,100\nE-01,95,100\nE-02,80,100\n",
        encoding="utf-8",
    )
    source = {
        "key": "production_file",
        "name": "生产数据",
        "connector_type": "file",
        "configuration": {"path": str(source_file)},
        "enabled": True,
    }
    pipeline = {
        "key": "production.quality",
        "label": "生产质量预览",
        "source": "production_file",
        "target": "preview",
        "mode": "preview",
        "steps": [
            {"operation": "deduplicate", "configuration": {"columns": ["equipment_id"]}},
            {
                "operation": "derive",
                "configuration": {
                    "column": "yield_rate",
                    "expression": "good_count * 100.0 / total_count",
                },
            },
            {
                "operation": "quality_check",
                "configuration": {"column": "equipment_id", "rule": "not_null"},
            },
            {
                "operation": "onn_map",
                "configuration": {"object": "equipment", "identity": "equipment_id"},
            },
        ],
    }
    with make_client(tmp_path) as client:
        saved = client.put("/api/v1/data-sources/production_file", json=source)
        preview = client.post("/api/v1/pipelines/preview?limit=20", json=pipeline)
    assert saved.status_code == 200
    assert preview.status_code == 200, preview.text
    result = preview.json()
    assert result["status"] == "passed"
    assert result["row_count"] == 2
    assert "yield_rate" in result["columns"]
    assert result["quality"][0]["failures"] == 0
    assert result["onn_mappings"][0]["object"] == "equipment"


def test_pipeline_preview_rejects_subqueries(tmp_path: Path) -> None:
    source_file = tmp_path / "unsafe.csv"
    source_file.write_text("id,value\n1,10\n", encoding="utf-8")
    source = {
        "key": "unsafe_file",
        "name": "预览数据",
        "connector_type": "file",
        "configuration": {"path": str(source_file)},
        "enabled": True,
    }
    pipeline = {
        "key": "unsafe.pipeline",
        "label": "危险表达式",
        "source": "unsafe_file",
        "target": "preview",
        "mode": "preview",
        "steps": [
            {
                "operation": "filter",
                "configuration": {"expression": "id IN (SELECT id FROM secret)"},
            }
        ],
    }
    with make_client(tmp_path) as client:
        client.put("/api/v1/data-sources/unsafe_file", json=source)
        preview = client.post("/api/v1/pipelines/preview", json=pipeline)
    assert preview.status_code == 422
    assert "子查询" in preview.json()["detail"]


def test_governed_evolution_requires_evaluation_and_supports_rollback(
    tmp_path: Path,
) -> None:
    change_id = "chg_alias_completion_rate"
    with make_client(tmp_path) as client:
        listed = client.get("/api/v1/governance/changes")
        review = client.post(
            f"/api/v1/governance/changes/{change_id}/decision",
            json={"action": "start_review", "actor": "data_owner", "comment": "开始复核"},
        )
        blocked = client.post(
            f"/api/v1/governance/changes/{change_id}/decision",
            json={"action": "approve", "actor": "data_owner", "comment": "批准"},
        )
        evaluation = client.post("/api/v1/governance/evaluations")
        approved = client.post(
            f"/api/v1/governance/changes/{change_id}/decision",
            json={"action": "approve", "actor": "data_owner", "comment": "评测通过"},
        )
        published = client.post(
            f"/api/v1/governance/changes/{change_id}/decision",
            json={"action": "publish", "actor": "semantic_owner", "comment": "发布"},
        )
        semantics_after_publish = client.get("/api/v1/semantics/overview")
        rolled_back = client.post(
            f"/api/v1/governance/changes/{change_id}/decision",
            json={"action": "rollback", "actor": "semantic_owner", "comment": "回滚验证"},
        )
        semantics_after_rollback = client.get("/api/v1/semantics/overview")
    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 3
    assert review.json()["status"] == "in_review"
    assert blocked.status_code == 409
    assert evaluation.json()["passed"] is True
    assert approved.json()["evaluation_run_id"] == evaluation.json()["run_id"]
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"
    published_metric = next(
        item
        for item in semantics_after_publish.json()["assets"]
        if item["key"] == "order_fulfillment_rate"
    )
    assert "完成率" in published_metric["aliases"]
    assert rolled_back.json()["status"] == "rolled_back"
    rolled_back_metric = next(
        item
        for item in semantics_after_rollback.json()["assets"]
        if item["key"] == "order_fulfillment_rate"
    )
    assert "完成率" not in rolled_back_metric["aliases"]


def test_governed_candidate_can_publish_directly_after_evaluation(tmp_path: Path) -> None:
    change_id = "chg_downtime_alias"
    with make_client(tmp_path) as client:
        blocked = client.post(
            f"/api/v1/governance/changes/{change_id}/decision",
            json={"action": "publish", "actor": "semantic_owner"},
        )
        evaluation = client.post("/api/v1/governance/evaluations")
        published = client.post(
            f"/api/v1/governance/changes/{change_id}/decision",
            json={"action": "publish", "actor": "semantic_owner"},
        )
    assert blocked.status_code == 409
    assert evaluation.json()["passed"] is True
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"
    assert published.json()["evaluation_run_id"] == evaluation.json()["run_id"]


def test_ingestion_extends_object_context_and_question_scope(tmp_path: Path) -> None:
    objects = [
        {
            "object_id": "line_02",
            "object_type": "production_line",
            "label": "二号生产线",
            "source_key": "mes.production",
            "attributes": {"line_code": "L02"},
        },
        {
            "object_id": "equipment_welder_02",
            "object_type": "equipment",
            "label": "二号焊机",
            "source_key": "mes.equipment",
            "attributes": {"criticality": "A"},
        },
    ]
    observations = [
        {
            "metric_key": "oee",
            "object_id": "line_02",
            "observed_at": "2026-08-19T08:00:00Z",
            "value": 81.5,
            "dimensions": {"shift": "all"},
        },
        {
            "metric_key": "oee",
            "object_id": "line_02",
            "observed_at": "2026-08-18T08:00:00Z",
            "value": 79.0,
            "dimensions": {"shift": "all"},
        },
    ]
    with make_client(tmp_path) as client:
        object_result = client.post("/api/v1/ingestion/objects", json=objects)
        relation_result = client.post(
            "/api/v1/ingestion/relations",
            json=[
                {
                    "relation_key": "line_contains_equipment",
                    "source_id": "line_02",
                    "target_id": "equipment_welder_02",
                }
            ],
        )
        metric_result = client.post("/api/v1/ingestion/metric-observations", json=observations)
        answer = client.post("/api/v1/query/ask", json={"question": "查询二号线的 OEE"})
        context = client.get("/api/v1/ontology/instances/line_02/context")
    assert object_result.json()["created"] == 2
    assert relation_result.json()["created"] == 1
    assert metric_result.json()["created"] == 2
    assert answer.status_code == 200
    assert answer.json()["data"]["current"] == 81.5
    assert answer.json()["plan"]["anchors"][0]["key"] == "line_02"
    assert context.json()["relations"][0]["related"]["object_id"] == "equipment_welder_02"


def test_question_without_object_scope_uses_unique_metric_object(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.post("/api/v1/query/ask", json={"question": "OEE 是多少？"})
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["plan"]["anchors"][0]["key"] == "line_01"


def test_question_only_asks_business_name_when_metric_scope_is_ambiguous(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        client.post(
            "/api/v1/ingestion/objects",
            json=[
                {
                    "object_id": "line_02",
                    "object_type": "production_line",
                    "label": "二号生产线",
                    "source_key": "test",
                    "attributes": {},
                }
            ],
        )
        client.post(
            "/api/v1/ingestion/metric-observations",
            json=[
                {
                    "metric_key": "oee",
                    "object_id": "line_02",
                    "observed_at": "2026-08-20T08:00:00Z",
                    "value": 82.0,
                    "dimensions": {},
                }
            ],
        )
        response = client.post("/api/v1/query/ask", json={"question": "OEE 是多少？"})
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "needs_clarification"
    assert "一号生产线" in result["answer"]
    assert "二号生产线" in result["answer"]
    assert "object_id" not in result["answer"]


def test_optional_api_auth_enforces_roles_and_writes_audit(tmp_path: Path) -> None:
    viewer_token = "viewer-secret"
    operator_token = "operator-secret"
    owner_token = "owner-secret"
    admin_token = "admin-secret"
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'secured.db'}",
        backup_directory=tmp_path / "backups",
        semantic_directory=Path("semantic"),
        auth_enabled=True,
        auth_principals={
            "question_agent": {
                "role": "viewer",
                "token_hash": token_hash(viewer_token),
                "object_scope": ["line_01"],
            },
            "semantic_owner": {"role": "semantic_owner", "token_hash": token_hash(owner_token)},
            "line_operator": {
                "role": "operator",
                "token_hash": token_hash(operator_token),
                "object_scope": ["line_01"],
            },
            "platform_admin": {"role": "admin", "token_hash": token_hash(admin_token)},
        },
    )
    viewer_headers = {"Authorization": f"Bearer {viewer_token}"}
    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    operator_headers = {"Authorization": f"Bearer {operator_token}"}
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    with TestClient(create_app(settings)) as client:
        health = client.get("/api/v1/health")
        unauthenticated = client.post("/api/v1/query/ask", json={"question": "一号线 OEE"})
        query = client.post(
            "/api/v1/query/ask",
            json={"question": "一号线 OEE"},
            headers=viewer_headers,
        )
        forbidden_object = client.post(
            "/api/v1/query/ask",
            json={"question": "华东工厂 OEE"},
            headers=viewer_headers,
        )
        viewer_backup = client.post("/api/v1/system/backups", headers=viewer_headers)
        viewer_export = client.get("/api/v1/exports/objects.csv", headers=viewer_headers)
        owner_export = client.get("/api/v1/exports/objects.csv", headers=owner_headers)
        scoped_ingestion = client.post(
            "/api/v1/ingestion/events",
            headers=operator_headers,
            json=[
                {
                    "event_type": "maintenance",
                    "object_id": "east_plant",
                    "occurred_at": "2026-08-20T08:00:00Z",
                }
            ],
        )
        owner_backup = client.post("/api/v1/system/backups", headers=owner_headers)
        viewer_audit = client.get("/api/v1/system/audit-events", headers=viewer_headers)
        audit = client.get("/api/v1/system/audit-events", headers=admin_headers)
    assert health.status_code == 200
    assert unauthenticated.status_code == 401
    assert query.status_code == 200
    assert forbidden_object.status_code == 403
    assert viewer_backup.status_code == 403
    assert viewer_export.status_code == 403
    assert owner_export.status_code == 200
    assert scoped_ingestion.status_code == 403
    assert owner_backup.status_code == 200
    assert viewer_audit.status_code == 403
    assert {item["principal"] for item in audit.json()["items"]} >= {
        "question_agent",
        "semantic_owner",
    }


def test_new_metric_is_candidate_before_evaluated_publication(tmp_path: Path) -> None:
    proposal = {
        "key": "first_pass_yield",
        "kind": "metric",
        "label": "一次合格率",
        "description": "首次检验合格数量占投入数量的比例",
        "domain": "manufacturing.quality",
        "owner": "quality-management",
        "aliases": ["FPY"],
        "unit": "%",
        "dimensions": ["production_line", "day"],
        "expression": "first_pass_good / input_count * 100",
    }
    with make_client(tmp_path) as client:
        candidate = client.post("/api/v1/governance/asset-candidates", json=proposal)
        change_id = candidate.json()["change_id"]
        before = client.get("/api/v1/semantics/overview")
        client.post(
            f"/api/v1/governance/changes/{change_id}/decision",
            json={"action": "start_review", "actor": "quality_owner"},
        )
        evaluation = client.post("/api/v1/governance/evaluations")
        approved = client.post(
            f"/api/v1/governance/changes/{change_id}/decision",
            json={"action": "approve", "actor": "quality_owner"},
        )
        published = client.post(
            f"/api/v1/governance/changes/{change_id}/decision",
            json={"action": "publish", "actor": "semantic_owner"},
        )
        after = client.get("/api/v1/semantics/overview")
    assert candidate.status_code == 200
    assert candidate.json()["status"] == "candidate"
    assert "first_pass_yield" not in {item["key"] for item in before.json()["assets"]}
    assert evaluation.json()["passed"] is True, evaluation.text
    assert approved.status_code == 200, approved.text
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"
    assert "first_pass_yield" in {item["key"] for item in after.json()["assets"]}


def test_yaml_configuration_is_overridden_by_environment(tmp_path: Path, monkeypatch) -> None:
    configuration = tmp_path / "fathom.yaml"
    configuration.write_text(
        "storage_profile: lite\nduckdb_threads: 2\nenable_vector_search: false\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FATHOM_DUCKDB_THREADS", "4")
    loaded = load_settings(configuration)
    assert loaded.storage_profile == "lite"
    assert loaded.duckdb_threads == 4
    assert loaded.config_file == configuration


def test_model_gateway_never_returns_api_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        SecretStore,
        "save",
        lambda self, provider_key, secret: f"keyring://model/{provider_key}",
    )
    payload = {
        "key": "reasoner",
        "name": "主推理模型",
        "provider_type": "openai_compatible",
        "base_url": "https://model.example.com/v1",
        "api_mode": "auto",
        "default_model": "reasoner-v1",
        "api_key": "must-never-be-returned",
        "parameters": {"temperature": 0.0, "max_output_tokens": 2048},
        "enabled": True,
    }
    with make_client(tmp_path) as client:
        saved = client.put("/api/v1/model-gateway/providers/reasoner", json=payload)
        listed = client.get("/api/v1/model-gateway/providers")
        routes = client.get("/api/v1/model-gateway/routes")
    assert saved.status_code == 200
    assert "api_key" not in saved.json()
    assert "must-never-be-returned" not in saved.text
    assert listed.json()["items"][0]["has_secret"] is True
    assert {route["key"] for route in routes.json()["items"]} >= {
        "planner",
        "semantic_extractor",
        "explainer",
        "vision",
        "embedding",
    }


def test_model_gateway_validates_parameter_bounds(tmp_path: Path) -> None:
    payload = {
        "key": "unsafe_randomness",
        "name": "Invalid",
        "provider_type": "openai_compatible",
        "base_url": "https://model.example.com/v1",
        "api_mode": "chat_completions",
        "default_model": "model",
        "parameters": {"temperature": 9},
        "enabled": True,
    }
    with make_client(tmp_path) as client:
        response = client.put("/api/v1/model-gateway/providers/unsafe_randomness", json=payload)
    assert response.status_code == 422


def test_model_gateway_uses_current_ca_bundle_and_explicit_user_agent(
    tmp_path: Path, monkeypatch
) -> None:
    captured_requests: list[tuple[str, str | None, ssl.SSLContext]] = []

    class FakeResponse:
        def __init__(self, payload: dict) -> None:
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _limit: int) -> bytes:
            return json.dumps(self.payload).encode()

    def fake_urlopen(request, *, timeout, context):
        captured_requests.append((request.full_url, request.get_header("User-agent"), context))
        if request.full_url.endswith("/models"):
            return FakeResponse({"data": [{"id": "reasoner-v1"}]})
        return FakeResponse({"choices": [{"message": {"content": "FATHOM_OK"}}]})

    monkeypatch.setattr("fathom.application.model_gateway.urllib.request.urlopen", fake_urlopen)
    provider = {
        "key": "tls_reasoner",
        "name": "TLS Reasoner",
        "provider_type": "openai_compatible",
        "base_url": "https://model.example.com/v1",
        "api_mode": "chat_completions",
        "default_model": "reasoner-v1",
        "enabled": True,
    }
    with make_client(tmp_path) as client:
        client.put("/api/v1/model-gateway/providers/tls_reasoner", json=provider)
        result = client.post("/api/v1/model-gateway/providers/tls_reasoner/probe")
    assert result.json()["status"] == "ready"
    assert all(user_agent == "FATHOM/0.1" for _, user_agent, _ in captured_requests)
    assert all(isinstance(context, ssl.SSLContext) for _, _, context in captured_requests)


def test_multimodal_inspection_uses_governed_object_context(tmp_path: Path, monkeypatch) -> None:
    provider = {
        "key": "vision_provider",
        "name": "视觉模型",
        "provider_type": "openai",
        "base_url": "https://model.example.com/v1",
        "api_mode": "chat_completions",
        "default_model": "vision-model",
        "capabilities": ["text", "vision"],
        "parameters": {"temperature": 0.1, "max_output_tokens": 512},
        "enabled": True,
    }
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'vision.db'}",
        semantic_directory=Path("semantic"),
    )
    with TestClient(create_app(settings)) as client:
        saved = client.put("/api/v1/model-gateway/providers/vision_provider", json=provider)
        routed = client.put(
            "/api/v1/model-gateway/routes/vision",
            json={"role": "vision", "provider_key": "vision_provider"},
        )
        monkeypatch.setattr(
            client.app.state.model_gateway_service,
            "_post_json",
            lambda record, path, payload: {
                "choices": [{"message": {"content": "识别到液压机，压力表读数异常；需人工复核。"}}],
                "usage": {"total_tokens": 120},
            },
        )
        inspected = client.post(
            "/api/v1/multimodal/inspect",
            params={"object_id": "equipment_press_01"},
            files={"file": ("press.png", b"fake-image", "image/png")},
        )
    assert saved.status_code == 200
    assert routed.status_code == 200
    assert inspected.status_code == 200, inspected.text
    assert inspected.json()["object_id"] == "equipment_press_01"
    assert "液压机" in inspected.json()["analysis"]
    assert "不自动修改" in inspected.json()["note"]


def test_mcp_exposes_and_calls_certified_tools(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        initialized = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        tools = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        called = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "fathom.ask_data",
                    "arguments": {"question": "为什么一号线昨天订单达成率下降？"},
                },
            },
        )
    assert initialized.json()["result"]["protocolVersion"] == "2025-11-25"
    assert {tool["name"] for tool in tools.json()["result"]["tools"]} == {
        "fathom.ask_data",
        "fathom.get_object_context",
        "fathom.search_semantics",
    }
    structured = called.json()["result"]["structuredContent"]
    assert structured["status"] == "completed"
    assert structured["trace_id"]


def test_agent_mesh_and_a2a_discovery(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        mesh = client.get("/api/v1/agent-mesh/overview")
        card = client.get("/.well-known/agent-card.json")
        gateway = client.get("/api/v1/agent-gateway/capabilities")
    assert mesh.status_code == 200
    assert len(mesh.json()["agents"]) >= 10
    assert {flow["key"] for flow in mesh.json()["flows"]} >= {
        "trusted_qa",
        "guided_onboarding",
        "adaptive_diagnosis",
    }
    assert card.json()["protocolVersion"] == "0.3.0"
    assert {protocol["key"] for protocol in gateway.json()["protocols"]} >= {
        "openapi",
        "mcp",
        "a2a",
    }
    a2a = next(protocol for protocol in gateway.json()["protocols"] if protocol["key"] == "a2a")
    assert a2a["status"] == "ready"
    assert a2a["methods"] == ["message/send"]


def test_a2a_message_send_returns_evidence_and_trace(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.post(
            "/a2a",
            json={
                "jsonrpc": "2.0",
                "id": "query-1",
                "method": "message/send",
                "params": {
                    "message": {
                        "kind": "message",
                        "role": "user",
                        "messageId": "message-1",
                        "contextId": "factory-session",
                        "parts": [
                            {
                                "kind": "text",
                                "text": "为什么一号线昨天订单达成率下降？",
                            }
                        ],
                        "metadata": {"scope": {"factory": "demo"}},
                    }
                },
            },
        )
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["kind"] == "message"
    assert result["contextId"] == "factory-session"
    assert result["metadata"]["traceId"]
    assert result["parts"][1]["kind"] == "data"
    assert result["parts"][1]["data"]["evidence"]


def test_a2a_rejects_unsupported_method_and_empty_message(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        unsupported = client.post(
            "/a2a",
            json={"jsonrpc": "2.0", "id": 1, "method": "tasks/get", "params": {}},
        )
        empty = client.post(
            "/a2a",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "message/send",
                "params": {"message": {"kind": "message", "parts": []}},
            },
        )
    assert unsupported.json()["error"]["code"] == -32601
    assert empty.json()["error"]["code"] == -32602


def test_agent_mesh_runtime_executes_and_persists_trusted_flow(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        executed = client.post(
            "/api/v1/agent-mesh/runs",
            json={
                "flow_key": "trusted_qa",
                "question": "为什么一号线昨天订单达成率下降？",
            },
        )
        fetched = client.get(f"/api/v1/agent-mesh/runs/{executed.json()['run_id']}")
        listed = client.get("/api/v1/agent-mesh/runs")
    assert executed.status_code == 200
    assert executed.json()["status"] == "completed"
    assert executed.json()["trace_id"]
    assert len(executed.json()["receipts"]) == 5
    assert all(receipt["status"] == "completed" for receipt in executed.json()["receipts"])
    assert fetched.json()["run_id"] == executed.json()["run_id"]
    assert listed.json()["items"][0]["run_id"] == executed.json()["run_id"]


def test_agent_mesh_runtime_requires_flow_inputs(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        missing_question = client.post("/api/v1/agent-mesh/runs", json={"flow_key": "trusted_qa"})
        unknown_flow = client.post("/api/v1/agent-mesh/runs", json={"flow_key": "unknown"})
    assert missing_question.status_code == 422
    assert unknown_flow.status_code == 422


def test_onn_object_instances_expose_relational_context(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        instances = client.get("/api/v1/ontology/instances", params={"object_type": "equipment"})
        context = client.get("/api/v1/ontology/instances/line_01/context")
        via_mcp = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 9,
                "method": "tools/call",
                "params": {
                    "name": "fathom.get_object_context",
                    "arguments": {"object_id": "line_01"},
                },
            },
        )
    assert instances.json()["total"] == 2
    assert context.json()["object"]["label"] == "一号生产线"
    assert {relation["relation"] for relation in context.json()["relations"]} >= {
        "plant_contains_line",
        "line_contains_equipment",
        "work_order_runs_on_line",
    }
    assert via_mcp.json()["result"]["structuredContent"]["object"]["object_id"] == "line_01"
