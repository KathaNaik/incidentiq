"""Ticket reads."""

from fastapi import APIRouter, HTTPException, status

from app.dependencies import RepositoryDep
from app.domain.models import Ticket
from app.schemas import TicketDetail

router = APIRouter(tags=["tickets"])


@router.get("/tickets", response_model=list[Ticket])
def list_tickets(repository: RepositoryDep) -> list[Ticket]:
    """All tickets, newest first."""
    return list(repository.list_tickets())


@router.get("/tickets/{ticket_id}", response_model=TicketDetail)
def get_ticket(ticket_id: str, repository: RepositoryDep) -> TicketDetail:
    ticket = repository.get_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown ticket: {ticket_id}",
        )
    return TicketDetail.build(ticket, repository.get_incident_id_for_ticket(ticket_id))
