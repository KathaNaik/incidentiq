"""FastAPI application entry point.

Run locally with:  uv run uvicorn app.main:app --reload --port 8001

In production the same app runs in a container behind Vercel, same-origin with the web
app. Two things differ there and both are deliberate: unhandled exceptions return a
generic message rather than the exception text, and CORS is not configured at all,
because same-origin requests do not need it.
"""

import logging
import os
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import Settings, get_settings

logger = logging.getLogger("incidentiq")
from app.routers import (
    actions,
    correlation,
    dataset,
    demo,
    evals,
    health,
    incidents,
    intake,
    investigation,
    retrieval,
    reviews,
    services,
    tickets,
    triage,
)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application. Explicit factory so tests can vary configuration."""
    settings = settings or get_settings()

    app = FastAPI(
        title="IncidentIQ API",
        version="0.1.0",
        summary="AI-assisted incident investigation for technical operations teams.",
    )

    _configure_logging(settings)

    # No CORS in production. The web app and the API are served from one origin there, so
    # a cross-origin policy would only be granting access nothing legitimate needs. Local
    # development is the case that genuinely needs it: Next.js on 3000, API on 8001.
    if settings.cors_allow_origins and not settings.is_production:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_allow_origins),
            # POST is needed for /triage, which classifies text the caller supplies.
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
        )

    @app.exception_handler(Exception)
    async def unhandled(request: Request, error: Exception) -> JSONResponse:
        """Turns a crash into something a caller can act on and an operator can find.

        The exception text is logged, never returned. A stack trace or a driver error in
        an HTTP body is how connection strings and internal paths end up in someone's
        browser. The reference id is the link between what the user saw and the log line.
        """
        reference = uuid.uuid4().hex[:12]
        logger.exception(
            "unhandled error ref=%s method=%s path=%s",
            reference,
            request.method,
            request.url.path,
        )
        return JSONResponse(
            status_code=500,
            content={
                "detail": (
                    "The server could not complete this request. Reference "
                    f"{reference}."
                ),
                "reference": reference,
            },
        )

    app.include_router(health.router)
    app.include_router(dataset.router)
    app.include_router(services.router)
    app.include_router(tickets.router)
    app.include_router(intake.router)
    app.include_router(reviews.router)
    app.include_router(incidents.router)
    app.include_router(triage.router)
    app.include_router(correlation.router)
    app.include_router(retrieval.router)
    app.include_router(investigation.router)
    app.include_router(actions.router)
    app.include_router(evals.router)
    app.include_router(demo.router)

    if settings.api_path_prefix:
        # Starlette's Mount strips the prefix before matching, so every route below is
        # reached at its own path and the application is identical in both shapes.
        outer = FastAPI(
            title="IncidentIQ API",
            version="0.1.0",
            docs_url=None,
            redoc_url=None,
            openapi_url=None,
        )
        outer.mount(settings.api_path_prefix, app)
        return outer

    return app


def _configure_logging(settings: Settings) -> None:
    """One-line logs to stdout, which is what the platform collects.

    Nothing here logs a secret. `DATABASE_URL` carries a password and `OPENAI_API_KEY` is
    a credential, so neither is ever formatted into a message — the readiness check
    reports *that* the database is unreachable, not the URL it failed to reach.
    """
    if logging.getLogger().handlers:
        return  # uvicorn or a test harness already configured it
    logging.basicConfig(
        level=os.environ.get("INCIDENTIQ_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


app = create_app()
