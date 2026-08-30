"""Intake contracts.

The request carries only what a reporter can legitimately know. Triage predictions,
correlation scores, candidate ids and anything resembling a model conclusion are
server-owned — accepting them would let a caller assert its own incident grouping, which
is the one thing this endpoint exists to decide.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.intake.rules import MAX_DESCRIPTION, MAX_EXTERNAL_ID, MAX_TITLE


class IntakeModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TicketSource(StrEnum):
    API = "api"
    NORTHSTAR = "northstar-authored"
    IMPORTED = "imported"
    EXTERNAL_EVAL = "external-eval"


class CorrelationOutcome(StrEnum):
    ATTACHED = "attached"
    CREATED_CANDIDATE = "created_candidate"
    UNCORRELATED = "uncorrelated"
    AMBIGUOUS = "ambiguous"
    FAILED = "failed"


class CreateTicketRequest(BaseModel):
    """What a caller may submit. `extra="forbid"` is the guard, not a convention."""

    model_config = ConfigDict(extra="forbid")

    external_id: str = Field(min_length=1, max_length=MAX_EXTERNAL_ID)
    title: str = Field(max_length=MAX_TITLE)
    description: str = Field(default="", max_length=MAX_DESCRIPTION)
    # When the reporter observed the problem — not when we were told. Optional because a
    # form submission usually means "now"; supplied explicitly when back-filling.
    created_at: datetime | None = None
    # What the reporter claims. Triage still forms its own view.
    reported_service_id: str | None = None
    reported_by: str = Field(default="unknown", min_length=1, max_length=128)


class TriageSummary(IntakeModel):
    service_id: str | None
    priority: str | None
    issue_type: str | None
    version: str
    signals: dict


class CorrelationDecision(IntakeModel):
    """Why this ticket went where it did. Derived from scoring rules, never prose."""

    ticket_id: str
    candidate_id: str | None
    outcome: CorrelationOutcome
    correlation_version: str
    score: float | None
    confidence: str | None
    created_new_candidate: bool
    supporting_signals: tuple[str, ...] = ()
    conflicting_signals: tuple[str, ...] = ()
    reason: str = ""
    # Runners-up, when the choice was close enough that the alternative matters.
    alternatives: tuple[str, ...] = ()
    # Hybrid staging. Absent for a single-strategy decision, which had no fallback stage.
    strategy: str | None = None
    deterministic_stage: dict | None = None
    fallback_stage: dict | None = None
    embedding_model: str | None = None


class RuntimeTicket(IntakeModel):
    id: str
    external_id: str | None
    source: TicketSource
    title: str
    description: str
    reported_by: str
    status: str
    created_at: datetime
    received_at: datetime
    reported_service_id: str | None
    service_id: str | None
    priority: str | None
    issue_type: str | None
    triage_version: str | None
    candidate_id: str | None


class TicketIntakeResult(IntakeModel):
    ticket: RuntimeTicket
    triage: TriageSummary
    correlation: CorrelationDecision
    candidate: dict | None
    # True when this submission was a repeat and nothing new happened.
    idempotent_replay: bool = False
