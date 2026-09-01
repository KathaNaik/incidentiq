"""Ticket intake.

**"Real intake" here means a typed runtime API and a form** — not a ServiceNow, Slack, or
email integration. Nothing in IncidentIQ talks to a third-party ticketing system, and no
part of this milestone implies one exists.

Posting a ticket runs validation, persistence, deterministic triage, and correlation
against the candidates that are still open. It does **not** call a language model.
Investigation stays an explicit operator decision, which is what keeps intake fast, free
of token cost, and predictable enough to evaluate.
"""

from typing import Annotated

from fastapi import APIRouter, Body, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict

from app.dependencies import IntakeDep, RepositoryDep
from app.intake import (
    CreateTicketRequest,
    DuplicateTicketError,
    IntakeError,
    TicketIntakeResult,
)

router = APIRouter(tags=["intake"])


class RuntimeTicketView(BaseModel):
    """A ticket with its intake metadata, for the operator-facing list and detail."""

    model_config = ConfigDict(frozen=True)

    id: str
    external_id: str | None
    source: str
    title: str
    description: str
    reported_by: str
    status: str
    created_at: str
    received_at: str
    reported_service_id: str | None
    service_id: str | None
    priority: str | None
    issue_type: str | None
    triage_version: str | None
    candidate_id: str | None
    correlation_outcome: str | None
    correlation_reason: str | None
    correlation_version: str | None
    correlation_score: float | None


def _view(row, decision) -> RuntimeTicketView:
    return RuntimeTicketView(
        id=row.id,
        external_id=row.external_id,
        source=row.source,
        title=row.title,
        description=row.description,
        reported_by=row.reported_by,
        status=row.status,
        created_at=row.created_at.isoformat(),
        received_at=row.received_at.isoformat(),
        reported_service_id=row.reported_service_id,
        service_id=row.service_id,
        priority=row.priority,
        issue_type=row.issue_type,
        triage_version=row.triage_version,
        candidate_id=row.candidate_id,
        correlation_outcome=decision.outcome if decision else None,
        correlation_reason=decision.reason if decision else None,
        correlation_version=decision.correlation_version if decision else None,
        correlation_score=decision.score if decision else None,
    )


@router.post(
    "/tickets", response_model=TicketIntakeResult, status_code=status.HTTP_201_CREATED
)
def submit_ticket(
    request: Annotated[CreateTicketRequest, Body()],
    intake: IntakeDep,
    response: Response,
) -> TicketIntakeResult:
    """Accepts one report and returns what the system did with it.

    An identical resubmission of the same `external_id` returns the original outcome with
    200 rather than 201, and correlates nothing twice. The same id with different content
    is a 409: two different reports cannot share one identity, and silently overwriting
    the first would discard something somebody filed.
    """
    try:
        result = intake.submit(request)
    except DuplicateTicketError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except IntakeError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error

    if result.idempotent_replay:
        response.status_code = status.HTTP_200_OK
    return result


@router.get("/intake/tickets", response_model=list[RuntimeTicketView])
def list_runtime_tickets(
    repository: RepositoryDep,
    service_id: str | None = Query(default=None),
    candidate_id: str | None = Query(default=None),
    uncorrelated: bool | None = Query(default=None),
    source: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
) -> list[RuntimeTicketView]:
    """Runtime tickets with triage and correlation state, newest first."""
    rows = _rows(
        repository,
        service_id=service_id,
        candidate_id=candidate_id,
        uncorrelated=uncorrelated,
        source=source,
        status=status_filter,
    )
    return [_view(row, repository.decision_for(row.id)) for row in rows]


@router.get("/intake/tickets/{ticket_id}", response_model=RuntimeTicketView)
def get_runtime_ticket(ticket_id: str, repository: RepositoryDep) -> RuntimeTicketView:
    row = getattr(repository, "ticket_row", lambda _: None)(ticket_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown ticket: {ticket_id}"
        )
    return _view(row, repository.decision_for(ticket_id))


@router.get("/intake/candidates")
def list_runtime_candidates(repository: RepositoryDep) -> list[dict]:
    """Persisted candidate incidents, with staleness relative to their latest run."""
    if not hasattr(repository, "candidates"):
        return []
    return [_candidate_view(repository, row) for row in repository.candidates()]


def _candidate_view(repository, row) -> dict:
    return {
        "id": row.id,
        "title": row.title,
        "status": row.status,
        "service_id": row.service_id,
        "issue_type": row.issue_type,
        "ticket_count": row.ticket_count,
        "first_seen": row.first_seen.isoformat(),
        "last_seen": row.last_seen.isoformat(),
        "score": row.score,
        "confidence": row.confidence,
        "distinct_reporters": row.distinct_reporters,
        "correlation_version": row.correlation_version,
        "ticket_ids": [t.id for t in repository.candidate_tickets(row.id)],
    }


def _rows(repository, **filters):
    if not hasattr(repository, "ticket_rows"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "runtime ticket intake needs PostgreSQL; start it with "
                "`docker compose up -d` and run the migrations"
            ),
        )
    return repository.ticket_rows(**filters)
