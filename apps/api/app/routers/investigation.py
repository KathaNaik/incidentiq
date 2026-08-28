"""AI investigation.

Recommends; never executes. There is no endpoint here that changes the state of
anything — approval and execution are Milestone 9, and shipping a working "apply this
rollback" button before the approval boundary exists would be exactly backwards.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.config import Settings, get_settings
from app.correlation import CorrelationTicket, correlate
from app.correlation.semantic import default_similarity
from app.dependencies import RepositoryDep, RetrievalIndexDep
from app.embeddings import EmbeddingError
from app.investigation import (
    InvestigationModelError,
    InvestigationResult,
    InvestigationValidationError,
    OpenAIInvestigationModel,
    collect_evidence,
    investigate,
    load_operations,
)
from app.investigation.rules import HISTORICAL_EVIDENCE_K
from app.investigation.tools import ToolError
from app.routers.correlation import Mode

router = APIRouter(tags=["investigation"])


@router.post(
    "/correlation/candidates/{candidate_id}/investigate",
    response_model=InvestigationResult,
)
def investigate_candidate(
    candidate_id: str,
    repository: RepositoryDep,
    index: RetrievalIndexDep,
    settings: Annotated[Settings, Depends(get_settings)],
    mode: Mode = Mode.DETERMINISTIC,
) -> InvestigationResult:
    """Investigates one candidate incident over deterministically collected evidence."""
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
        correlated = correlate(tickets, similarity)
        operations = load_operations(settings.fixtures_dir)
    except (EmbeddingError, ToolError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
        ) from error

    candidate = next(
        (item for item in correlated.candidates if item.id == candidate_id), None
    )
    if candidate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown candidate incident: {candidate_id}",
        )

    registry = collect_evidence(
        candidate=candidate,
        tickets=tickets,
        operations=operations,
        index=index,
        historical_k=HISTORICAL_EVIDENCE_K,
    )

    try:
        return investigate(
            candidate=candidate,
            registry=registry,
            model=OpenAIInvestigationModel(
                settings.investigation_model, settings.openai_api_key
            ),
        )
    except InvestigationModelError as error:
        # No credentials, or the provider failed. Never substitute a fabricated
        # investigation — an absent model is a configuration problem, not a finding.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
        ) from error
    except InvestigationValidationError as error:
        # The model produced something that broke a system guarantee. Refusing is the
        # correct outcome; an operator gets nothing rather than an ungrounded claim.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"the model returned an investigation that failed validation: {error}",
        ) from error
