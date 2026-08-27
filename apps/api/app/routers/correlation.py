"""Correlation over ticket text.

Candidates are computed on demand and not persisted. They are proposals, and a proposal
that outlives the rules that produced it is a stale claim about the system's state; when
an operator confirms one, *that* becomes an Incident — which is a later milestone.
"""

from enum import StrEnum
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict

from app.config import Settings, get_settings
from app.correlation import CorrelationResult, CorrelationTicket, correlate
from app.correlation.semantic import SemanticSimilarity, default_similarity
from app.dependencies import RepositoryDep
from app.embeddings import EmbeddingError

router = APIRouter(tags=["correlation"])


class Mode(StrEnum):
    """Which correlation version to run.

    Deterministic is the default everywhere: semantic is opt-in, so no caller silently
    changes behaviour, and the version is stamped on every response either way.
    """

    DETERMINISTIC = "deterministic"
    SEMANTIC = "semantic"


ModeQuery = Annotated[Mode, Query(description="correlation version to run")]


def _similarity(mode: Mode, settings: Settings) -> SemanticSimilarity | None:
    if mode is Mode.DETERMINISTIC:
        return None
    return default_similarity(settings.embeddings_cache_dir)


def _run(
    tickets: list[CorrelationTicket], mode: Mode, settings: Settings
) -> CorrelationResult:
    try:
        return correlate(tickets, _similarity(mode, settings))
    except EmbeddingError as error:
        # Never degrade to the deterministic answer while claiming the semantic
        # version — an unavailable provider is a configuration problem, not a result.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
        ) from error


class CorrelationRequest(BaseModel):
    """Tickets to correlate.

    `extra="forbid"` on `CorrelationTicket` means a caller cannot smuggle a ground-truth
    field in alongside the text.
    """

    model_config = ConfigDict(extra="forbid")

    tickets: list[CorrelationTicket]


@router.post("/correlation/analyze", response_model=CorrelationResult)
def analyze(
    request: CorrelationRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    mode: ModeQuery = Mode.DETERMINISTIC,
) -> CorrelationResult:
    return _run(request.tickets, mode, settings)


@router.get("/correlation/candidates", response_model=CorrelationResult)
def candidates(
    repository: RepositoryDep,
    settings: Annotated[Settings, Depends(get_settings)],
    mode: ModeQuery = Mode.DETERMINISTIC,
) -> CorrelationResult:
    """Candidate incidents across the stored ticket set.

    Runs the same code path as `/correlation/analyze` over the Northstar tickets. The
    fixtures' hand-declared incident links are *not* consulted — the point is what the
    baseline finds on its own.
    """
    tickets = [
        CorrelationTicket(
            id=ticket.id,
            title=ticket.title,
            description=ticket.description,
            created_at=ticket.created_at,
            service_id=ticket.service_id,
            reported_by=ticket.reported_by,
        )
        for ticket in repository.list_tickets()
    ]
    return _run(tickets, mode, settings)
