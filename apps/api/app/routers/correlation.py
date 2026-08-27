"""Correlation over ticket text.

Candidates are computed on demand and not persisted. They are proposals, and a proposal
that outlives the rules that produced it is a stale claim about the system's state; when
an operator confirms one, *that* becomes an Incident — which is a later milestone.
"""

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from app.correlation import CorrelationResult, CorrelationTicket, correlate
from app.dependencies import RepositoryDep

router = APIRouter(tags=["correlation"])


class CorrelationRequest(BaseModel):
    """Tickets to correlate.

    `extra="forbid"` on `CorrelationTicket` means a caller cannot smuggle a ground-truth
    field in alongside the text.
    """

    model_config = ConfigDict(extra="forbid")

    tickets: list[CorrelationTicket]


@router.post("/correlation/analyze", response_model=CorrelationResult)
def analyze(request: CorrelationRequest) -> CorrelationResult:
    return correlate(request.tickets)


@router.get("/correlation/candidates", response_model=CorrelationResult)
def candidates(repository: RepositoryDep) -> CorrelationResult:
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
    return correlate(tickets)
