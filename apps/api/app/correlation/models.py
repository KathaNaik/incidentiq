"""Typed correlation output.

A candidate is a *proposal*, never an incident. Nothing here creates an `Incident`; an
operator or a later decision layer does that. The distinction is in the names on purpose.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class Component(StrEnum):
    """The five pieces of evidence a correlation score is made of."""

    TIME = "time"
    SERVICE = "service"
    ISSUE_TYPE = "issue_type"
    LEXICAL = "lexical"
    ENTITY = "entity"


class Direction(StrEnum):
    SUPPORTING = "supporting"
    CONFLICTING = "conflicting"
    NEUTRAL = "neutral"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class CorrelationModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CorrelationTicket(CorrelationModel):
    """The only shape correlation accepts.

    `extra="forbid"` is the leakage guard: a Polaris row carrying `event_id` cannot be
    passed in at all, so ground truth has no path into inference.
    """

    id: str
    title: str
    description: str = ""
    created_at: datetime
    # What the ticket itself claims, when it says anything. Triage fills the gap.
    service_id: str | None = None
    # Used only to count how many distinct people reported the group — never scored.
    reported_by: str | None = None


class CorrelationSignal(CorrelationModel):
    """One component's contribution, with the evidence behind it."""

    component: Component
    direction: Direction
    # Component score in [-1, 1]; negative means the evidence argues against grouping.
    score: float
    weight: float
    detail: str
    values: tuple[str, ...] = ()


class PairwiseScore(CorrelationModel):
    ticket_a: str
    ticket_b: str
    # Blended score: W_TIME·time + (1 - W_TIME)·content.
    score: float
    # Kept separate because clustering treats them differently — content must hold
    # against every member, time only against the nearest one.
    content_score: float
    time_score: float
    minutes_apart: float
    signals: tuple[CorrelationSignal, ...]


class CandidateIncident(CorrelationModel):
    """A proposed grouping awaiting human confirmation."""

    id: str
    ticket_ids: tuple[str, ...]
    score: float
    confidence: Confidence
    first_seen: datetime
    last_seen: datetime
    # Only when every member agrees; a mixed group reports None rather than a guess.
    service_id: str | None
    issue_type: str | None
    ticket_count: int
    # Distinct reporters actually present on the member tickets. Not an estimate of
    # affected users — that number is not observable from tickets, so it is not invented.
    distinct_reporters: int | None
    supporting_signals: tuple[CorrelationSignal, ...]
    conflicting_signals: tuple[CorrelationSignal, ...]
    member_pairs: tuple[PairwiseScore, ...]


class CorrelationResult(CorrelationModel):
    version: str
    ticket_count: int
    candidates: tuple[CandidateIncident, ...]
    # Tickets the baseline declined to group. Being alone is a real answer.
    standalone_ticket_ids: tuple[str, ...]
