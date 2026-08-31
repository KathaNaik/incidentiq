"""Correlation review contracts.

The decision values are deliberately semantic. `approve`/`deny` would read as an
action-policy approval, which this is not — the operator is asserting whether two things
are *the same incident*, and a label that ambiguous is worth nothing later.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

REVIEW_POLICY_VERSION = "review-policy-v1"

# What a decided review means, as a training target. Kept beside the semantic values so
# the mapping is one line in one place rather than folklore in an export script.
SAME_INCIDENT = 1
DIFFERENT_INCIDENT = 0


class ReviewModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ReviewStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    STALE = "stale"
    """The candidate changed after the review was created, so the operator would be
    answering a question about a state that no longer exists."""


class ReviewDecision(StrEnum):
    CONFIRM_SAME_INCIDENT = "confirm_same_incident"
    REJECT_DIFFERENT_INCIDENT = "reject_different_incident"


class ConfirmReason(StrEnum):
    SAME_SYMPTOMS = "same_symptoms"
    SAME_MECHANISM = "same_mechanism"
    SAME_ROLLOUT_OR_OUTAGE = "same_rollout_or_outage"
    OTHER = "other"


class RejectReason(StrEnum):
    DIFFERENT_MECHANISM = "different_mechanism"
    DIFFERENT_SERVICE = "different_service"
    TIMING_INCOMPATIBLE = "timing_incompatible"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    OTHER = "other"


class DecisionRequest(BaseModel):
    """What an operator sends. The label is the decision; everything else is optional."""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = None
    note: str | None = Field(default=None, max_length=1000)


class CorrelationReview(ReviewModel):
    """One ambiguous grouping decision, with the state it was posed against."""

    id: str
    ticket_id: str
    candidate_id: str
    status: ReviewStatus
    decision: ReviewDecision | None
    decision_reason: str | None
    decision_note: str | None
    actor: str | None
    correlation_version: str
    review_policy_version: str
    feature_schema: str
    candidate_fingerprint: str
    ticket_snapshot: dict
    candidate_snapshot: dict
    correlation_snapshot: dict
    feature_snapshot: dict
    created_at: datetime
    decided_at: datetime | None
    resulting_membership: dict | None

    @property
    def decided(self) -> bool:
        return self.status in (ReviewStatus.CONFIRMED, ReviewStatus.REJECTED)

    @property
    def label(self) -> int | None:
        """The training target. None while pending or stale."""
        if self.status is ReviewStatus.CONFIRMED:
            return SAME_INCIDENT
        if self.status is ReviewStatus.REJECTED:
            return DIFFERENT_INCIDENT
        return None


class DecisionResult(ReviewModel):
    """What the decision did to operational state."""

    review: CorrelationReview
    attached: bool
    candidate: dict | None
    investigation_stale: bool
    """True when the candidate had a successful investigation that this attachment
    now post-dates. Nothing is re-run — the operator still chooses that."""

    superseded_review_ids: tuple[str, ...] = ()
    """Other pending reviews for this ticket, closed because a ticket cannot belong to
    two mutually exclusive candidates."""
