"""Operator correlation review.

M18 showed that borrowed labels do not fit the product's decision. This captures labels at
exactly the boundary IncidentIQ asks about — *should this ticket join this candidate, given
what the candidate looked like at the time* — by putting the ambiguous slice to a human and
freezing the state they answered against.

It produces data. It trains nothing.
"""

from app.review.models import (
    REVIEW_POLICY_VERSION,
    ConfirmReason,
    CorrelationReview,
    DecisionRequest,
    DecisionResult,
    RejectReason,
    ReviewDecision,
    ReviewStatus,
)
from app.review.service import (
    DEMO_OPERATOR,
    ReviewConflict,
    ReviewError,
    ReviewService,
    fingerprint,
)

__all__ = [
    "DEMO_OPERATOR",
    "REVIEW_POLICY_VERSION",
    "ConfirmReason",
    "CorrelationReview",
    "DecisionRequest",
    "DecisionResult",
    "RejectReason",
    "ReviewConflict",
    "ReviewDecision",
    "ReviewError",
    "ReviewService",
    "ReviewStatus",
]
