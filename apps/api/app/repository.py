"""Read access to IncidentIQ records.

`Repository` is the boundary the API depends on. `InMemoryRepository` is today's
implementation, built from a validated fixture `Dataset`; swapping it for a database
implementation later means writing a new class, not editing callers.

Ordering is defined here rather than left to insertion order, so responses are stable
across restarts and independent of how the fixture files happen to be written.
"""

from collections.abc import Sequence
from typing import Protocol

from app.domain.models import Incident, IncidentTicket, Service, Ticket
from app.fixtures import Dataset


class Repository(Protocol):
    """Read-only access to services, tickets, incidents, and their links."""

    @property
    def dataset_name(self) -> str: ...

    def list_services(self) -> Sequence[Service]: ...

    def list_tickets(self) -> Sequence[Ticket]: ...

    def get_ticket(self, ticket_id: str) -> Ticket | None: ...

    def list_incidents(self) -> Sequence[Incident]: ...

    def get_incident(self, incident_id: str) -> Incident | None: ...

    def list_tickets_for_incident(self, incident_id: str) -> Sequence[Ticket]: ...

    def get_incident_id_for_ticket(self, ticket_id: str) -> str | None: ...

    def count_tickets_by_incident(self) -> dict[str, int]: ...


class InMemoryRepository:
    """Repository backed by an already-validated in-memory dataset."""

    def __init__(self, dataset: Dataset) -> None:
        self._dataset_name = dataset.name
        self._services = tuple(sorted(dataset.services, key=lambda s: s.name))
        # Newest first: an operator opening either list is looking at what is happening
        # now. Id breaks ties so the order is total.
        self._tickets = tuple(
            sorted(dataset.tickets, key=lambda t: (t.created_at, t.id), reverse=True)
        )
        self._incidents = tuple(
            sorted(dataset.incidents, key=lambda i: (i.detected_at, i.id), reverse=True)
        )
        self._links: tuple[IncidentTicket, ...] = dataset.incident_tickets

        self._tickets_by_id = {ticket.id: ticket for ticket in self._tickets}
        self._incidents_by_id = {incident.id: incident for incident in self._incidents}
        self._incident_id_by_ticket_id = {
            link.ticket_id: link.incident_id for link in self._links
        }

    @property
    def dataset_name(self) -> str:
        return self._dataset_name

    def list_services(self) -> Sequence[Service]:
        return self._services

    def list_tickets(self) -> Sequence[Ticket]:
        return self._tickets

    def get_ticket(self, ticket_id: str) -> Ticket | None:
        return self._tickets_by_id.get(ticket_id)

    def list_incidents(self) -> Sequence[Incident]:
        return self._incidents

    def get_incident(self, incident_id: str) -> Incident | None:
        return self._incidents_by_id.get(incident_id)

    def list_tickets_for_incident(self, incident_id: str) -> Sequence[Ticket]:
        """Tickets linked to an incident, in the same order as `list_tickets`."""
        ticket_ids = {
            link.ticket_id for link in self._links if link.incident_id == incident_id
        }
        return tuple(ticket for ticket in self._tickets if ticket.id in ticket_ids)

    def get_incident_id_for_ticket(self, ticket_id: str) -> str | None:
        return self._incident_id_by_ticket_id.get(ticket_id)

    def count_tickets_by_incident(self) -> dict[str, int]:
        counts = {incident.id: 0 for incident in self._incidents}
        for link in self._links:
            counts[link.incident_id] += 1
        return counts
