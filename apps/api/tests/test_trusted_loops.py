import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from fathom.application.mql import MqlEngine, MqlValidationError
from fathom.config import Settings
from fathom.domains.query.models import MqlQuery
from fathom.main import create_app


def make_client(tmp_path: Path) -> TestClient:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'trusted-loops.db'}",
        semantic_directory=Path("semantic"),
    )
    return TestClient(create_app(settings))


def test_source_extraction_is_snapshot_based_and_review_only(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    connection = sqlite3.connect(source)
    connection.execute(
        "CREATE TABLE production (id INTEGER PRIMARY KEY, line TEXT, actual_quantity REAL)"
    )
    connection.commit()
    connection.close()
    payload = {
        "key": "production_db",
        "name": "生产库",
        "connector_type": "sqlite",
        "configuration": {"path": str(source)},
        "enabled": True,
    }
    with make_client(tmp_path) as client:
        assert client.put("/api/v1/data-sources/production_db", json=payload).status_code == 200
        first = client.post("/api/v1/data-sources/production_db/extract")
        second = client.post("/api/v1/data-sources/production_db/extract")
        changes = client.get("/api/v1/governance/changes?status=candidate")
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "candidates_created"
    assert first.json()["diff"]["added_tables"] == ["production"]
    assert first.json()["governance"]["created"]
    assert second.json()["status"] == "unchanged"
    assert second.json()["governance"]["created"] == []
    assert any(
        item["history"][-1]["actor"] == "guided_onboarding"
        for item in changes.json()["items"]
    )


def test_knowledge_ingest_extracts_metric_candidate_without_publishing(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        client.put(
            "/api/v1/knowledge-bases/metric.docs",
            json={"key": "metric.docs", "name": "指标口径库", "kind": "internal"},
        )
        result = client.post(
            "/api/v1/knowledge-bases/metric.docs/documents",
            json={
                "title": "良率口径",
                "content": (
                    "指标名称：一次合格率\n"
                    "公式：first_pass_count / total_count * 100\n"
                    "别名：FPY，一次通过率"
                ),
                "metadata": {"domain": "manufacturing.quality"},
            },
        )
        assets = client.get("/api/v1/semantics/assets?query=一次合格率")
    assert result.status_code == 200, result.text
    extraction = result.json()["semantic_extraction"]
    assert extraction["status"] == "candidates_created"
    assert extraction["governance"]["created"][0]["status"] == "candidate"
    assert assets.json()["total"] == 0


def test_mql_is_exposed_verified_and_rejects_unknown_dimension(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.post("/api/v1/query/ask", json={"question": "一号线 OEE 是多少？"})
        absent_date = client.post(
            "/api/v1/query/ask", json={"question": "一号线 2020-01-01 的 OEE 是多少？"}
        )
        engine = MqlEngine(client.app.state.session_factory, client.app.state.semantic_repository)
        with pytest.raises(MqlValidationError):
            engine.validate(
                MqlQuery(
                    metric="oee",
                    object_ids=["line_01"],
                    dimensions=["customer_secret"],
                )
            )
    body = response.json()
    assert body["verification_status"] == "verified"
    assert body["plan"]["mql"]["metric"] == "oee"
    assert body["data"]["compiled_query"]["template"].startswith("metric_observations.")
    assert absent_date.json()["status"] == "no_data"


def test_feedback_captures_buttons_implicit_corrections_and_external_imports(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path) as client:
        conversation = client.post(
            "/api/v1/query/conversations", json={"title": "新对话"}
        ).json()
        first = client.post(
            "/api/v1/query/ask",
            json={
                "question": "一号线 OEE 是多少？",
                "conversation_id": conversation["conversation_id"],
            },
        ).json()
        explicit = client.post(
            f"/api/v1/query/conversations/{conversation['conversation_id']}/turns/{first['turn_id']}/feedback",
            json={"rating": "dislike", "content": "时间不对，我要昨天"},
        )
        client.post(
            "/api/v1/query/ask",
            json={
                "question": "不是，我要的是昨天",
                "conversation_id": conversation["conversation_id"],
            },
        )
        client.post(
            "/api/v1/integrations/external/message-links",
            json={
                "app_id": "dify-app",
                "external_conversation_id": "dify-chat",
                "external_message_id": "dify-message",
                "conversation_id": conversation["conversation_id"],
                "turn_id": first["turn_id"],
                "trace_id": first["trace_id"],
            },
        )
        imported = client.post(
            "/api/v1/integrations/external/feedback/import",
            json={
                "app_id": "dify-app",
                "conversation_id": "dify-chat",
                "message_id": "dify-message",
                "rating": "like",
                "content": "对的",
            },
        )
        feedback = client.get("/api/v1/feedback").json()["items"]
    assert explicit.status_code == 200, explicit.text
    assert explicit.json()["category"] == "wrong_time"
    assert imported.json()["source"] == "external"
    assert {item["source"] for item in feedback} >= {"self_ui", "implicit_text", "external"}
    implicit = next(item for item in feedback if item["source"] == "implicit_text")
    assert implicit["emotion"] == "corrective"
    assert implicit["mql"]["metric"] == "oee"


def test_diagnosis_persists_evidence_ladder_and_grades_claim(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.post(
            "/api/v1/query/ask", json={"question": "为什么一号线昨天订单达成率下降？"}
        )
        body = response.json()
        run = client.get(f"/api/v1/analysis-runs/{body['analysis_run_id']}")
    assert response.status_code == 200, response.text
    assert body["analysis_run_id"].startswith("rca_")
    assert body["data"]["diagnosis"]["conclusion_level"] in {
        "driver",
        "suspected_cause",
        "verified_root_cause",
    }
    assert run.status_code == 200
    assert [step["code"] for step in run.json()["steps"]] == [
        "confirm_anomaly",
        "decompose_metric",
        "rank_contributors",
        "validate_hypothesis",
    ]
    if run.json()["conclusion_level"] != "verified_root_cause":
        assert "疑似原因" in body["answer"] or "缺少足够" in body["answer"]
