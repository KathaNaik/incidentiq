"""Liveness and readiness.

Two endpoints, deliberately. `/health` reports only that the process is serving
requests — a liveness probe that fails because the database is unreachable asks the
platform to restart a container that is working perfectly, which turns a database blip
into an outage. `/ready` is where dependency state belongs.

Neither runs the embedding model. A health check that loads 67 MB of ONNX to prove it
could would be the most expensive request the service serves.
"""

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy import text

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    environment: str


class ReadyResponse(BaseModel):
    """Readiness, plus enough detail to tell *which* dependency is unhappy."""

    ready: bool
    service: str
    environment: str
    database: Literal["ok", "unreachable", "not_configured"]
    #: The migration the database is actually at, and the one this build expects. A
    #: mismatch is reported rather than repaired — migrating on startup would have every
    #: scaled instance racing to alter the same schema.
    schema_revision: str | None = None
    expected_revision: str | None = None
    schema_current: bool | None = None
    detail: str | None = None


@router.get("/health", response_model=HealthResponse)
def read_health(
    settings: Annotated[Settings, Depends(get_settings)],
) -> HealthResponse:
    """Liveness. Touches nothing."""
    return HealthResponse(
        status="ok", service=settings.service_name, environment=settings.environment
    )


@router.get("/ready", response_model=ReadyResponse)
def read_ready(
    settings: Annotated[Settings, Depends(get_settings)], response: Response
) -> ReadyResponse:
    """Readiness: is the database reachable, and is its schema the one this build expects?

    Returns 503 when it is not, so a deployment that would fail on its first real request
    says so on a cheap one instead.
    """
    if not settings.database_url:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadyResponse(
            ready=False,
            service=settings.service_name,
            environment=settings.environment,
            database="not_configured",
            detail="DATABASE_URL is not set",
        )

    expected = _expected_revision()

    try:
        from app.db.engine import get_engine

        with get_engine().connect() as connection:
            actual = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar()
    except Exception as error:
        # Deliberately not echoed to the caller: a connection error carries the host and
        # sometimes the user of the database.
        logger.error("readiness check failed: %s", type(error).__name__)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadyResponse(
            ready=False,
            service=settings.service_name,
            environment=settings.environment,
            database="unreachable",
            expected_revision=expected,
            detail="could not reach the database or read its schema version",
        )

    current = expected is None or actual == expected
    if not current:
        logger.error(
            "schema mismatch: database at %s, build expects %s — run `uv run alembic "
            "upgrade head` against this database",
            actual,
            expected,
        )
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadyResponse(
        ready=current,
        service=settings.service_name,
        environment=settings.environment,
        database="ok",
        schema_revision=actual,
        expected_revision=expected,
        schema_current=current,
        detail=None
        if current
        else "database schema is behind this build; run alembic upgrade head",
    )


def _expected_revision() -> str | None:
    """The head revision this build ships, read from the migration scripts.

    Returns None rather than raising if Alembic's config is not present — readiness
    should not fail because a packaging detail changed.
    """
    try:
        from pathlib import Path

        from alembic.config import Config
        from alembic.script import ScriptDirectory

        root = Path(__file__).resolve().parents[2]
        config = Config(str(root / "alembic.ini"))
        config.set_main_option("script_location", str(root / "alembic"))
        heads = ScriptDirectory.from_config(config).get_heads()
        return heads[0] if len(heads) == 1 else None
    except Exception:  # pragma: no cover - packaging dependent
        logger.warning("could not determine expected migration revision")
        return None
