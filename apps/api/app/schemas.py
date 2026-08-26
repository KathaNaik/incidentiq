"""HTTP response shapes that differ from the stored records.

Anything the API returns unchanged (Service, Ticket) is served as its domain model
directly. Only aggregated or resolved shapes appear here, so a computed value never
becomes a stored field by accident.
"""

from collections.abc import Sequence

from pydantic import BaseModel

from app.domain.models import Incident, Ticket


class DatasetInfo(BaseModel):
    """Provenance of the records this API is serving.

    The frontend surfaces this so nobody mistakes fabricated development data for real
    operational data.
    """

    name: str
    synthetic: bool


class TicketDetail(Ticket):
    """A ticket plus the incident it currently belongs to, if any."""

    incident_id: str | None = None

    @classmethod
    def build(cls, ticket: Ticket, incident_id: str | None) -> "TicketDetail":
        return cls.model_validate({**ticket.model_dump(), "incident_id": incident_id})


class IncidentSummary(Incident):
    """An incident as it appears in a list, with the size of its ticket cluster."""

    ticket_count: int

    @classmethod
    def build(cls, incident: Incident, ticket_count: int) -> "IncidentSummary":
        return cls.model_validate(
            {**incident.model_dump(), "ticket_count": ticket_count}
        )


class IncidentDetail(Incident):
    """An incident with the tickets it explains."""

    tickets: tuple[Ticket, ...]

    @classmethod
    def build(cls, incident: Incident, tickets: Sequence[Ticket]) -> "IncidentDetail":
        return cls.model_validate({**incident.model_dump(), "tickets": tuple(tickets)})
