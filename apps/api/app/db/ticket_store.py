"""Tickets and candidates, read from PostgreSQL.

`SqlRepository` implements the same `Repository` protocol the API has always depended on,
so the endpoints did not change when ticket state moved into the database — that Protocol
was the designed swap point.

Services and incidents stay fixture-backed. They are authored demo configuration, not
runtime state: nothing creates a service at runtime, and putting them in a mutable table
would invite drift with no benefit. Tickets moved because tickets *arrive*.
"""

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import Engine, select

from app.db.engine import get_engine, sessionmaker_for
from app.db.models import CandidateIncidentRow, CorrelationDecisionRow, TicketRow
from app.domain.models import Incident, IncidentTicket, Service, Ticket
from app.fixtures import Dataset
from app.repository import InMemoryRepository


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def to_domain(row: TicketRow) -> Ticket:
    """A runtime row as the domain `Ticket` every existing caller expects."""
    return Ticket(
        id=row.id,
        title=row.title,
        description=row.description,
        created_at=_aware(row.created_at),
        status=row.status,
        reported_by=row.reported_by,
        priority=row.priority,
        service_id=row.service_id,
    )


class SqlRepository:
    """Tickets from PostgreSQL; services and incidents from the authored fixtures."""

    def __init__(self, dataset: Dataset, engine: Engine | None = None) -> None:
        self._fixtures = InMemoryRepository(dataset)
        self._engine = engine or get_engine()
        self._session = sessionmaker_for(self._engine)

    @property
    def dataset_name(self) -> str:
        return self._fixtures.dataset_name

    def list_services(self) -> Sequence[Service]:
        return self._fixtures.list_services()

    def list_incidents(self) -> Sequence[Incident]:
        return self._fixtures.list_incidents()

    def get_incident(self, incident_id: str) -> Incident | None:
        return self._fixtures.get_incident(incident_id)

    def list_tickets_for_incident(self, incident_id: str) -> Sequence[Ticket]:
        return self._fixtures.list_tickets_for_incident(incident_id)

    def get_incident_id_for_ticket(self, ticket_id: str) -> str | None:
        return self._fixtures.get_incident_id_for_ticket(ticket_id)

    def count_tickets_by_incident(self) -> dict[str, int]:
        return self._fixtures.count_tickets_by_incident()

    # --- tickets, now durable ---------------------------------------------------------

    def list_tickets(self) -> Sequence[Ticket]:
        with self._session() as session:
            rows = session.scalars(
                select(TicketRow).order_by(TicketRow.created_at.desc(), TicketRow.id)
            ).all()
            return [to_domain(row) for row in rows]

    def get_ticket(self, ticket_id: str) -> Ticket | None:
        with self._session() as session:
            row = session.get(TicketRow, ticket_id)
            return to_domain(row) if row else None

    # --- intake-aware reads -------------------------------------------------------------

    def ticket_rows(
        self,
        *,
        service_id: str | None = None,
        candidate_id: str | None = None,
        uncorrelated: bool | None = None,
        source: str | None = None,
        status: str | None = None,
    ) -> list[TicketRow]:
        """Runtime rows with their intake metadata, filtered by the obvious things."""
        statement = select(TicketRow).order_by(
            TicketRow.created_at.desc(), TicketRow.id
        )
        if service_id:
            statement = statement.where(TicketRow.service_id == service_id)
        if candidate_id:
            statement = statement.where(TicketRow.candidate_id == candidate_id)
        if uncorrelated is True:
            statement = statement.where(TicketRow.candidate_id.is_(None))
        if uncorrelated is False:
            statement = statement.where(TicketRow.candidate_id.isnot(None))
        if source:
            statement = statement.where(TicketRow.source == source)
        if status:
            statement = statement.where(TicketRow.status == status)
        with self._session() as session:
            return list(session.scalars(statement).all())

    def ticket_row(self, ticket_id: str) -> TicketRow | None:
        with self._session() as session:
            return session.get(TicketRow, ticket_id)

    def decision_for(self, ticket_id: str) -> CorrelationDecisionRow | None:
        with self._session() as session:
            return session.scalars(
                select(CorrelationDecisionRow)
                .where(CorrelationDecisionRow.ticket_id == ticket_id)
                .order_by(CorrelationDecisionRow.decided_at.desc())
            ).first()

    def candidates(self) -> list[CandidateIncidentRow]:
        with self._session() as session:
            return list(
                session.scalars(
                    select(CandidateIncidentRow).order_by(
                        CandidateIncidentRow.first_seen.desc()
                    )
                ).all()
            )

    def candidate(self, candidate_id: str) -> CandidateIncidentRow | None:
        with self._session() as session:
            return session.get(CandidateIncidentRow, candidate_id)

    def candidate_tickets(self, candidate_id: str) -> list[TicketRow]:
        with self._session() as session:
            return list(
                session.scalars(
                    select(TicketRow)
                    .where(TicketRow.candidate_id == candidate_id)
                    .order_by(TicketRow.created_at, TicketRow.id)
                ).all()
            )

    def last_evidence_at(self, candidate_id: str) -> datetime | None:
        """The newest member's reported time.

        Reported, not received: a report filed late describes an old event, and treating
        arrival time as evidence time would make every backfilled ticket look like fresh
        activity.
        """
        rows = self.candidate_tickets(candidate_id)
        return max((_aware(row.created_at) for row in rows), default=None)
