"""Typed triage output.

Every field here is produced by explicit rules. Nothing is a model output, and the
`signals` attached to a result are the actual matches that produced the scores — not a
narrative written after the fact.
"""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.domain.models import TicketPriority


class IssueType(StrEnum):
    """Deliberately small, and deliberately *not* a restatement of the service.

    There is no `authentication` member: Northstar already has an Authentication
    service, and a ticket classified as service=Authentication, issue=authentication
    carries no information beyond the service. What matters operationally is whether
    auth is *down*, *slow*, or *denying someone who should have access* — availability,
    performance, permissions.
    """

    AVAILABILITY = "availability"
    PERFORMANCE = "performance"
    DATA_QUALITY = "data_quality"
    CONFIGURATION = "configuration"
    PERMISSIONS = "permissions"
    INTEGRATION = "integration"
    UNKNOWN = "unknown"


class PredictionStatus(StrEnum):
    CLASSIFIED = "classified"
    # Two or more candidates too close to separate. Reported rather than broken by
    # coin flip: a triage tool that guesses is worse than one that says it cannot tell.
    AMBIGUOUS = "ambiguous"
    # No rule matched at all.
    UNKNOWN = "unknown"
    # No evidence either way, so a documented fallback was used.
    DEFAULT = "default"


class SignalType(StrEnum):
    SERVICE_TERM = "service_term"
    ISSUE_TERM = "issue_term"
    SCOPE = "scope"
    OUTAGE = "outage"
    URGENCY = "urgency"
    DEGRADATION = "degradation"
    LOCALIZED = "localized"
    INTENT = "intent"


SourceField = Literal["title", "description"]


class TriageModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TriageSignal(TriageModel):
    """One rule match, kept structured so an operator can audit the decision."""

    signal_type: SignalType
    matched_text: str
    # Canonical meaning of the match, e.g. "all_users" for both "everyone" and
    # "all users", so explanations group rather than list synonyms.
    normalized_value: str
    weight: float
    source_field: SourceField
    # What the signal contributed to: "service:svc-auth", "issue_type:availability",
    # or "priority".
    target: str


class ScoredCandidate(TriageModel):
    value: str
    score: float


class TriagePrediction(TriageModel):
    value: str | None
    status: PredictionStatus
    score: float
    # Distance to the runner-up. Small margins are what `ambiguous` is made of.
    margin: float
    candidates: tuple[ScoredCandidate, ...]
    explanation: str


class TriageResult(TriageModel):
    ticket_id: str | None
    version: str
    service: TriagePrediction
    issue_type: TriagePrediction
    priority: TriagePrediction
    signals: tuple[TriageSignal, ...]


class TriageInput(TriageModel):
    """Free text as it arrives. The only thing triage is allowed to see."""

    ticket_id: str | None = None
    title: str
    description: str = ""


__all__ = [
    "IssueType",
    "PredictionStatus",
    "ScoredCandidate",
    "SignalType",
    "SourceField",
    "TicketPriority",
    "TriageInput",
    "TriagePrediction",
    "TriageResult",
    "TriageSignal",
]
