"""Core domain model.

These Pydantic models are both the internal representation and, where the wire shape
matches, the HTTP response shape. Computed/aggregated response shapes live in
`app.schemas` so aggregation never leaks into stored records.

Models are frozen and reject unknown fields: fixture typos should fail loudly at load
time rather than silently produce a record with a missing field.
"""

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field


class TicketStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"


class TicketPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IncidentStatus(StrEnum):
    INVESTIGATING = "investigating"
    IDENTIFIED = "identified"
    MONITORING = "monitoring"
    RESOLVED = "resolved"


class IncidentSeverity(StrEnum):
    SEV1 = "sev1"
    SEV2 = "sev2"
    SEV3 = "sev3"


def _require_utc(value: datetime) -> datetime:
    """Timestamps are compared and ordered across records, so naive values are rejected."""
    if value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone offset")
    return value


Timestamp = Annotated[datetime, AfterValidator(_require_utc)]
Identifier = Annotated[str, Field(min_length=1)]


class DomainModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Service(DomainModel):
    """A technical service or product capability that tickets and incidents refer to."""

    id: Identifier
    name: Annotated[str, Field(min_length=1)]
    description: str


class Ticket(DomainModel):
    """A single report from a user or an automated monitor."""

    id: Identifier
    title: Annotated[str, Field(min_length=1)]
    description: str
    created_at: Timestamp
    status: TicketStatus
    reported_by: Annotated[str, Field(min_length=1)]
    # Both are unknown for a ticket that has not been triaged yet, which is the normal
    # state on arrival — not an error.
    priority: TicketPriority | None = None
    service_id: Identifier | None = None


class Incident(DomainModel):
    """A technical event that may explain many tickets."""

    id: Identifier
    title: Annotated[str, Field(min_length=1)]
    status: IncidentStatus
    severity: IncidentSeverity
    # When impact began or was first observed, versus when IncidentIQ recorded it. The
    # two differ in practice, and time-to-detect depends on keeping them apart.
    detected_at: Timestamp
    created_at: Timestamp
    affected_service_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]


class IncidentTicket(DomainModel):
    """Association between an incident and a ticket it explains.

    A separate record rather than a field on either side: a ticket's membership is a
    judgement that will later be produced by correlation, with its own provenance and
    confidence. Keeping it here means adding those fields never touches Ticket.
    """

    incident_id: Identifier
    ticket_id: Identifier
