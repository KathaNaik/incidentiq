from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_health_returns_ok_status_and_service_name() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "incidentiq-api",
        "environment": "local",
    }


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


def test_production_does_not_configure_cors() -> None:
    """Same-origin in production, so a cross-origin policy would grant access nothing
    legitimate needs."""
    settings = Settings(
        environment="production", cors_allow_origins=("http://localhost:3000",)
    )
    client = TestClient(create_app(settings))

    response = client.get("/health", headers={"Origin": "http://localhost:3000"})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_readiness_reports_an_unconfigured_database() -> None:
    """Readiness is separate from liveness on purpose: a liveness probe that fails when
    the database is down asks the platform to restart a healthy container."""
    from app.config import get_settings

    app = create_app()
    # The endpoint resolves settings through Depends, so overriding the dependency is
    # what actually changes what it sees — passing them to create_app would not.
    app.dependency_overrides[get_settings] = lambda: Settings(database_url=None)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["ready"] is False
    assert body["database"] == "not_configured"


def test_an_unhandled_error_does_not_leak_its_message() -> None:
    """An exception body is how a connection string reaches somebody's browser."""
    from fastapi import APIRouter

    settings = Settings(environment="production")
    app = create_app(settings)
    router = APIRouter()

    @router.get("/boom")
    def boom() -> None:
        raise RuntimeError("postgresql://user:hunter2@db.example/incidentiq")

    app.include_router(router)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/boom")

    assert response.status_code == 500
    body = response.json()
    assert "hunter2" not in response.text
    assert "postgresql" not in response.text
    assert body["reference"]


def test_the_api_can_be_mounted_under_a_path_prefix() -> None:
    """The deployed shape: the platform passes `/api/...` through unchanged.

    Every route has to be reachable under the prefix, and the application must be
    otherwise identical — this is a mount, not a second set of routes.
    """
    client = TestClient(create_app(Settings(api_path_prefix="/api")))

    assert client.get("/api/health").status_code == 200
    assert client.get("/api/health").json()["service"] == "incidentiq-api"
    # Unprefixed paths must not answer, or the two shapes would disagree about what the
    # API's surface is.
    assert client.get("/health").status_code == 404


def test_no_prefix_is_the_local_shape() -> None:
    client = TestClient(create_app(Settings()))

    assert client.get("/health").status_code == 200
    assert client.get("/api/health").status_code == 404
