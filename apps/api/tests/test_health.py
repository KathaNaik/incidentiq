from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_health_returns_ok_status_and_service_name() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "incidentiq-api"}


def test_health_is_reachable_from_the_local_web_origin() -> None:
    """The web app calls /health from the browser, so a CORS regression breaks the
    frontend/backend boundary while the endpoint itself still looks healthy."""
    client = TestClient(create_app())

    response = client.get("/health", headers={"Origin": "http://localhost:3000"})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_unlisted_origin_is_not_granted_access() -> None:
    settings = Settings(cors_allow_origins=("http://localhost:3000",))
    client = TestClient(create_app(settings))

    response = client.get("/health", headers={"Origin": "http://evil.example"})

    assert "access-control-allow-origin" not in response.headers
