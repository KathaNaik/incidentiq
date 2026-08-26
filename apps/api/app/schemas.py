"""HTTP response shapes that differ from the stored records.

Anything the API returns unchanged (Service, Ticket) is served as its domain model
directly. Only aggregated or resolved shapes appear here, so a computed value never
becomes a stored field by accident.
"""

from collections.abc import Sequence
from datetime import datetime

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


class EvalMetric(BaseModel):
    name: str
    correct: int
    total: int
    accuracy: float
    abstained: int
    majority_baseline: float | None = None


class EvalConfusionCell(BaseModel):
    expected: str
    predicted: str
    count: int


class EvalFailure(BaseModel):
    case_id: str
    metric: str
    expected: str | None
    predicted: str | None
    status: str
    explanation: str
    signals: tuple[str, ...]
    text: str | None = None


class EvalReportResponse(BaseModel):
    """The API's view of an evaluation artifact produced by the offline harness.

    Deliberately a separate declaration from `evaluation.models.EvalReport`: the runtime
    API does not import the evaluation package, which reads ground truth. A test
    validates the committed artifact against this model so the two cannot drift apart
    unnoticed.
    """

    suite: str
    version: str
    generated_at: datetime
    case_count: int
    metrics: tuple[EvalMetric, ...]
    confusion: tuple[EvalConfusionCell, ...]
    failures: tuple[EvalFailure, ...]
    notes: tuple[str, ...] = ()


class IncidentDetail(Incident):
    """An incident with the tickets it explains."""

    tickets: tuple[Ticket, ...]

    @classmethod
    def build(cls, incident: Incident, tickets: Sequence[Ticket]) -> "IncidentDetail":
        return cls.model_validate({**incident.model_dump(), "tickets": tuple(tickets)})
