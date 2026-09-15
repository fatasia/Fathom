from pathlib import Path

from fastapi.testclient import TestClient
from fathom.config import Settings
from fathom.main import create_app


def test_development_restart_preserves_existing_facts(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'preserved.db'}"
    with TestClient(create_app(Settings(environment="test", database_url=database_url))) as client:
        original = client.get("/api/v1/ontology/instances").json()
        answer = client.post(
            "/api/v1/query/ask", json={"question": "一号线 OEE 是多少？"}
        ).json()

    with TestClient(
        create_app(Settings(environment="development", database_url=database_url))
    ) as client:
        assert client.get("/api/v1/ontology/instances").json() == original
        repeated = client.post(
            "/api/v1/query/ask", json={"question": "一号线 OEE 是多少？"}
        ).json()
        assert repeated["data"] == answer["data"]
