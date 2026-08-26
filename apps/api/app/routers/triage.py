"""Deterministic triage.

Results are computed on demand and not persisted: the rules are pure, so a stored result
would only be a cache that goes stale the moment `rules.py` changes.
"""

from fastapi import APIRouter, HTTPException, status

from app.dependencies import RepositoryDep
from app.triage import TriageInput, TriageResult, triage, triage_ticket

router = APIRouter(tags=["triage"])


@router.post("/triage", response_model=TriageResult)
def triage_text(request: TriageInput) -> TriageResult:
    """Triages arbitrary ticket text."""
    return triage(request)


@router.get("/tickets/{ticket_id}/triage", response_model=TriageResult)
def triage_stored_ticket(ticket_id: str, repository: RepositoryDep) -> TriageResult:
    """Triages a stored ticket from its text.

    The ticket's recorded service and priority are not consulted — this endpoint shows
    what the baseline would say about the ticket as it arrived.
    """
    ticket = repository.get_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown ticket: {ticket_id}",
        )
    return triage_ticket(ticket)
