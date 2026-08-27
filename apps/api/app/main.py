"""FastAPI application entry point.

Run locally with:  uv run uvicorn app.main:app --reload --port 8001
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, get_settings
from app.routers import (
    correlation,
    dataset,
    evals,
    health,
    incidents,
    retrieval,
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

    if settings.cors_allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_allow_origins),
            # POST is needed for /triage, which classifies text the caller supplies.
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
        )

    app.include_router(health.router)
    app.include_router(dataset.router)
    app.include_router(services.router)
    app.include_router(tickets.router)
    app.include_router(incidents.router)
    app.include_router(triage.router)
    app.include_router(correlation.router)
    app.include_router(retrieval.router)
    app.include_router(evals.router)
    return app


app = create_app()
