"""Exporting reviewed decisions as Northstar-native training data.

**These labels are not interchangeable with Polaris event labels.** Polaris says "these
tickets share an event" across days and hundreds of reports. These say "an operator, shown
this ticket and this candidate as they stood, judged them the same incident" — which is
the question the runtime actually asks, and the mismatch M18 ran into.

**Raw record and training row are separated deliberately.** The review keeps everything
needed to reconstruct and audit the decision: who, when, what they saw. The training row
keeps only features that existed *before* the decision, plus the target. Anything produced
by or after the decision — the actor, the timestamp, the resulting membership, the note —
is provenance, and letting provenance into a feature vector is how a model learns to
predict its own training process.

**Sampling bias, stated plainly.** Reviews are created only for the ambiguous slice: pairs
the M16 gate found structurally plausible and deterministic correlation still declined.
Hard conflicts never reach an operator. So this is not a random sample of ticket pairs — it
is concentrated on exactly the hard cases, which is what makes it valuable and also what
makes its base rate meaningless.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.pairwise.features import FEATURE_NAMES, FEATURE_SCHEMA_VERSION
from app.review.models import CorrelationReview, ReviewStatus

EXPORT_SCHEMA_VERSION = "northstar-correlation-labels-v1"
SOURCE = "northstar_operator_review"

# Fields that must never appear inside a training row's feature payload. Each exists on
# the review — that is the point of the raw record — and each would leak either the
# decision itself or something only knowable afterwards.
FORBIDDEN_FEATURE_KEYS = frozenset(
    {
        "actor",
        "decision",
        "decision_at",
        "decided_at",
        "decision_reason",
        "decision_note",
        "label",
        "same_incident",
        "resulting_membership",
        "status",
        "root_cause",
        "resolution",
        "event_id",
        "investigation",
    }
)


@dataclass(frozen=True)
class RejectedRecord:
    review_id: str
    reason: str


@dataclass(frozen=True)
class ExportResult:
    rows: list[dict]
    rejected: list[RejectedRecord]
    confirmed: int
    rejected_label: int

    @property
    def count(self) -> int:
        return len(self.rows)

    @property
    def positive_rate(self) -> float | None:
        return round(self.confirmed / self.count, 4) if self.count else None


def _validate(review: CorrelationReview) -> str | None:
    """Why this review cannot become a training row, or None if it can.

    Corrupt records are excluded and named rather than repaired. Silently fixing history
    would produce a dataset that describes something nobody decided.
    """
    if not review.decided:
        return f"status is {review.status.value}; only decided reviews are labels"
    if review.status is ReviewStatus.STALE:
        return "stale: the candidate changed after the operator was asked"
    if not review.ticket_snapshot:
        return "missing ticket snapshot"
    if not review.candidate_snapshot:
        return "missing candidate snapshot"
    if not review.feature_snapshot:
        return "missing feature snapshot"
    if review.feature_schema != FEATURE_SCHEMA_VERSION:
        return (
            f"feature schema {review.feature_schema!r} does not match this build's "
            f"{FEATURE_SCHEMA_VERSION!r}"
        )
    missing = set(FEATURE_NAMES) - set(review.feature_snapshot)
    if missing:
        return f"feature snapshot is missing {', '.join(sorted(missing))}"
    leaked = FORBIDDEN_FEATURE_KEYS & set(review.feature_snapshot)
    if leaked:
        return f"feature snapshot contains forbidden keys: {', '.join(sorted(leaked))}"

    members = review.candidate_snapshot.get("members") or []
    if not members:
        return "candidate snapshot has no members"
    ticket_time = review.ticket_snapshot.get("created_at")
    if ticket_time and any(
        member.get("created_at", "") > ticket_time for member in members
    ):
        return (
            "candidate snapshot contains a member created after the arriving ticket; "
            "the candidate must be the state that existed before it"
        )
    if review.decided_at and review.created_at and review.decided_at < review.created_at:
        return "decided before it was created"
    return None


def to_training_row(review: CorrelationReview) -> dict:
    """One supervised example.

    `features` holds only the decision-time vector. Everything identifying or dating the
    decision sits outside it, in `provenance`, where a training pipeline has to reach for
    it deliberately rather than sweep it in.
    """
    return {
        "review_id": review.id,
        "same_incident": review.label,
        "decision": review.decision.value if review.decision else None,
        "feature_schema": review.feature_schema,
        "features": {name: review.feature_snapshot[name] for name in FEATURE_NAMES},
        # Grouping key for a future split: the candidate a pair was judged against.
        "group": review.candidate_id,
        "provenance": {
            "ticket_id": review.ticket_id,
            "candidate_id": review.candidate_id,
            "candidate_fingerprint": review.candidate_fingerprint,
            "correlation_version": review.correlation_version,
            "review_policy_version": review.review_policy_version,
            "decided_at": review.decided_at.isoformat() if review.decided_at else None,
            "actor": review.actor,
            "decision_reason": review.decision_reason,
            "source": SOURCE,
        },
    }


def build_export(reviews: Sequence[CorrelationReview]) -> ExportResult:
    """Validated training rows, deterministically ordered."""
    rows: list[dict] = []
    rejected: list[RejectedRecord] = []
    confirmed = negative = 0

    for review in sorted(reviews, key=lambda r: (r.decided_at or r.created_at, r.id)):
        problem = _validate(review)
        if problem:
            if review.status is not ReviewStatus.PENDING:
                rejected.append(RejectedRecord(review_id=review.id, reason=problem))
            continue
        rows.append(to_training_row(review))
        if review.label == 1:
            confirmed += 1
        else:
            negative += 1

    return ExportResult(
        rows=rows, rejected=rejected, confirmed=confirmed, rejected_label=negative
    )


def write_jsonl(result: ExportResult, path: Path) -> dict:
    """Writes rows plus a header describing what they are.

    JSONL because it is the plainest thing that streams and diffs; nothing here needs a
    columnar format at this size.
    """
    header = {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "feature_schema": FEATURE_SCHEMA_VERSION,
        "source": SOURCE,
        "generated_at": datetime.now(UTC).isoformat(),
        "record_count": result.count,
        "confirmed": result.confirmed,
        "rejected": result.rejected_label,
        "positive_rate": result.positive_rate,
        "excluded": len(result.rejected),
        "note": (
            "Operator decisions at IncidentIQ's ambiguous correlation boundary. NOT "
            "interchangeable with Polaris event labels: these answer 'should this ticket "
            "join this candidate, given what the candidate looked like then', which is "
            "the runtime's question. Reviews exist only for pairs the structural gate "
            "found plausible and automation declined, so this is deliberately not a "
            "random sample and its base rate carries no information."
        ),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps({"header": header}) + "\n")
        for row in result.rows:
            handle.write(json.dumps(row) + "\n")
    return header
