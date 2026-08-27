"""Historical incident retrieval.

These endpoints return *past* incidents that resemble the current situation, with the
causes and fixes those incidents turned out to have. That is evidence for an operator to
read. Nothing here claims any of it explains what is happening now — no reasoning step
exists yet, and inventing one in the UI copy would be the same mistake as inventing one
in code.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.config import Settings, get_settings
from app.correlation import CorrelationTicket, correlate
from app.correlation.semantic import default_similarity
from app.dependencies import RepositoryDep, RetrievalIndexDep
from app.embeddings import EmbeddingError
from app.retrieval import (
    DEFAULT_K,
    CorpusError,
    RetrievalQuery,
    RetrievalResult,
    query_from_tickets,
)
from app.retrieval.rules import MAX_K
from app.routers.correlation import Mode

router = APIRouter(tags=["retrieval"])

KQuery = Annotated[int, Query(ge=1, le=MAX_K, description="how many results to return")]


def _search(index, query: RetrievalQuery, k: int) -> RetrievalResult:
    try:
        return index.search(query, k=k)
    except EmbeddingError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
        ) from error
    except CorpusError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
        ) from error


@router.post("/retrieval/historical-incidents", response_model=RetrievalResult)
def search_historical_incidents(
    query: RetrievalQuery,
    index: RetrievalIndexDep,
    k: KQuery = DEFAULT_K,
) -> RetrievalResult:
    """Historical incidents resembling a described situation."""
    return _search(index, query, k)


@router.get(
    "/correlation/candidates/{candidate_id}/similar", response_model=RetrievalResult
)
def similar_to_candidate(
    candidate_id: str,
    repository: RepositoryDep,
    index: RetrievalIndexDep,
    settings: Annotated[Settings, Depends(get_settings)],
    mode: Mode = Mode.DETERMINISTIC,
    k: KQuery = DEFAULT_K,
) -> RetrievalResult:
    """Precedent for one candidate incident.

    The query is built from the candidate's member tickets by the shared query builder,
    so the frontend never assembles retrieval text itself and there is one place where
    "what the system knows right now" is defined.
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

    try:
        similarity = (
            None
            if mode is Mode.DETERMINISTIC
            else default_similarity(settings.embeddings_cache_dir)
        )
        result = correlate(tickets, similarity)
    except EmbeddingError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
        ) from error

    candidate = next(
        (item for item in result.candidates if item.id == candidate_id), None
    )
    if candidate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown candidate incident: {candidate_id}",
        )

    members = [ticket for ticket in tickets if ticket.id in set(candidate.ticket_ids)]
    return _search(index, query_from_tickets(members), k)
