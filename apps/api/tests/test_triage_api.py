from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.dependencies import get_repository
from app.main import create_app
from app.repository import InMemoryRepository


def test_triage_endpoint_classifies_supplied_text(client: TestClient) -> None:
    response = client.post(
        "/triage",
        json={
            "title": "Cannot log in through SSO",
            "description": "Every user on the team is blocked.",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["service"]["value"] == "svc-auth"
    assert body["version"] == "deterministic-v1"
    assert body["signals"], "a prediction must ship the evidence behind it"


def test_triage_endpoint_requires_a_title(client: TestClient) -> None:
    assert client.post("/triage", json={"description": "no title"}).status_code == 422


def test_stored_ticket_can_be_triaged(client: TestClient) -> None:
    response = client.get("/tickets/TKT-4103/triage")

    assert response.status_code == 200
    assert response.json()["ticket_id"] == "TKT-4103"


def test_triage_of_unknown_ticket_returns_404(client: TestClient) -> None:
    response = client.get("/tickets/TKT-0000/triage")

    assert response.status_code == 404
    assert "TKT-0000" in response.json()["detail"]


def test_evaluation_artifact_is_served(client: TestClient) -> None:
    response = client.get("/evals/triage")

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == "deterministic-v1"
    assert body["suite"] == "golden"
    assert {metric["name"] for metric in body["metrics"]} == {
        "service",
        "issue_type",
        "priority",
    }


def test_missing_evaluation_artifact_explains_how_to_produce_one(
    tmp_path: Path, repository: InMemoryRepository
) -> None:
    settings = Settings(evals_dir=tmp_path)
    app = create_app(settings)
    app.dependency_overrides[get_repository] = lambda: repository
    app.dependency_overrides[get_settings] = lambda: settings

    with TestClient(app) as client:
        response = client.get("/evals/triage")

    assert response.status_code == 404
    assert "evaluate_triage.py" in response.json()["detail"]
