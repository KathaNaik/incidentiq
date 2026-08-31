"""Creating and deciding correlation reviews.

**Eligibility is not a new rule.** A review is created exactly when the M16 fallback gate
says a candidate is structurally plausible and the deterministic engine still declined to
attach — the same slice the embedding and classifier experiments were measured on. That
matters twice: operators are not asked about obvious cases, and the labels land precisely
where automation is weakest.

**Hard conflicts never reach an operator.** A different service, a contradictory issue
type, a conflicting error identifier, a candidate outside its window — all remain
automatically rejected. The label set is therefore *not* a random sample of tickets; it is
deliberately concentrated on ambiguous-but-plausible pairs, and that sampling bias is a
property of the data anyone training on it has to account for.

**Confirmation reuses the automatic attachment path.** There is no separate manual-attach
code with its own metadata semantics — the same candidate recomputation runs, so a
human-attached ticket and an auto-attached one leave the candidate in the same shape.

Nothing here calls a model. Review creation reads snapshots and features that the intake
path already computed.
"""

import hashlib
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import Engine, select

from app.correlation.models import CorrelationTicket
from app.correlation.rules import CORRELATION_VERSION
from app.db.engine import get_engine, sessionmaker_for
from app.db.models import CandidateIncidentRow, CorrelationReviewRow, TicketRow
from app.pairwise.features import FEATURE_SCHEMA_VERSION, extract
from app.review.models import (
    REVIEW_POLICY_VERSION,
    ConfirmReason,
    CorrelationReview,
    DecisionResult,
    RejectReason,
    ReviewDecision,
    ReviewStatus,
)

# No authentication exists in this prototype. A fixed identity is recorded rather than a
# fabricated username, and every surface that shows it says so.
DEMO_OPERATOR = "operator:demo-user"


class ReviewError(RuntimeError):
    """The review cannot be created or decided as asked."""


class ReviewConflict(ReviewError):
    """The review was already decided, or current state makes the old answer unsafe."""


def fingerprint(member_ids: Sequence[str], correlation_version: str) -> str:
    """Identity of the candidate *as reviewed*.

    Ordered member ids plus the correlation version. If the candidate gains a ticket, the
    fingerprint changes and the review is answering a question about a candidate that no
    longer exists — which is why staleness is detected by comparing this rather than by
    comparing timestamps.
    """
    digest = hashlib.sha256()
    digest.update(correlation_version.encode())
    for member_id in sorted(member_ids):
        digest.update(b"\x00")
        digest.update(member_id.encode())
    return digest.hexdigest()[:32]


def _aware(value):
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _correlation_ticket(row: TicketRow) -> CorrelationTicket:
    return CorrelationTicket(
        id=row.id,
        title=row.title,
        description=row.description,
        created_at=_aware(row.created_at),
        service_id=row.service_id,
        reported_by=None if row.reported_by == "unknown" else row.reported_by,
    )


def _ticket_snapshot(row: TicketRow) -> dict:
    return {
        "id": row.id,
        "external_id": row.external_id,
        "source": row.source,
        "title": row.title,
        "description": row.description,
        "created_at": _aware(row.created_at).isoformat(),
        "received_at": _aware(row.received_at).isoformat(),
        "service_id": row.service_id,
        "reported_service_id": row.reported_service_id,
        "priority": row.priority,
        "issue_type": row.issue_type,
        "triage_version": row.triage_version,
    }


def _candidate_snapshot(candidate: CandidateIncidentRow, members: Sequence[TicketRow]) -> dict:
    """The candidate as reviewed, including enough member text to reconstruct the pair.

    Member titles and descriptions are included deliberately: a future training run must
    be able to rebuild the decision without depending on rows that may since have moved.
    """
    return {
        "id": candidate.id,
        "title": candidate.title,
        "status": candidate.status,
        "service_id": candidate.service_id,
        "issue_type": candidate.issue_type,
        "ticket_count": candidate.ticket_count,
        "first_seen": _aware(candidate.first_seen).isoformat(),
        "last_seen": _aware(candidate.last_seen).isoformat(),
        "score": candidate.score,
        "confidence": candidate.confidence,
        "correlation_version": candidate.correlation_version,
        "members": [
            {
                "id": member.id,
                "title": member.title,
                "description": member.description,
                "created_at": _aware(member.created_at).isoformat(),
                "service_id": member.service_id,
                "issue_type": member.issue_type,
            }
            for member in sorted(members, key=lambda m: (m.created_at, m.id))
        ],
    }


def _ambiguous_decision(candidate_id: str):
    """The eligibility record for a candidate intake named directly.

    Used when correlation reached an *ambiguous* outcome: the structural gate never
    evaluated this pairing, because from its point of view the ticket clustered
    successfully. The reason recorded here says exactly that, rather than borrowing
    signals from a comparison nobody made.
    """
    from app.correlation.hybrid import FallbackDecision

    return FallbackDecision(
        candidate_id=candidate_id,
        eligible=True,
        reasons=(
            "two or more candidates scored within the ambiguity margin; automatic "
            "correlation declined to choose between them",
        ),
    )


class ReviewService:
    def __init__(self, engine: Engine | None = None) -> None:
        self._engine = engine or get_engine()
        self._session = sessionmaker_for(self._engine)

    # --- creation -----------------------------------------------------------------------

    def create_for_intake(
        self,
        ticket_id: str,
        window: Sequence[CorrelationTicket],
        *,
        candidate_ids: Sequence[str] | None = None,
    ) -> list[CorrelationReview]:
        """Creates reviews for candidates that could plausibly own this ticket.

        Called from intake after a ticket fails to attach automatically. Returns an empty
        list when every candidate has a hard conflict, which is the common case and is the
        reason operators are not flooded.

        Two ways the candidates are chosen:

        - **`candidate_ids` given** — intake already knows which durable incidents were
          plausible. That is the ambiguous case: the engine *did* cluster the ticket, and
          intake declined to act because a second candidate scored within
          `CANDIDATE_MARGIN`. The gate below cannot reconstruct that, because from its
          point of view the ticket clustered fine; left to itself it reads that as
          "attached automatically" and asks nobody, which is how the one report the system
          explicitly could not place became the one report no operator ever sees.
        - **`candidate_ids` omitted** — the M16 structural gate decides, which is the
          uncorrelated case it was built for.
        """
        from app.correlation import correlate
        from app.correlation.hybrid import _fallback_decisions

        deterministic = correlate(list(window))

        if candidate_ids is None:
            if any(ticket_id in c.ticket_ids for c in deterministic.candidates):
                return []  # attached automatically; nothing ambiguous to ask about
            decisions = _fallback_decisions(list(window), ticket_id, deterministic)
            eligible = [decision for decision in decisions if decision.eligible]
        else:
            by_candidate = {
                decision.candidate_id: decision
                for decision in _fallback_decisions(
                    list(window), ticket_id, deterministic
                )
            }
            # The signals are reused where the gate happened to evaluate the same
            # candidate, so a review still carries real numbers rather than blanks.
            eligible = [
                by_candidate.get(identifier) or _ambiguous_decision(identifier)
                for identifier in candidate_ids
            ]

        if not eligible:
            return []

        created: list[CorrelationReview] = []
        with self._session.begin() as session:
            ticket = session.get(TicketRow, ticket_id)
            if ticket is None:
                raise ReviewError(f"unknown ticket {ticket_id}")
            arriving = _correlation_ticket(ticket)

            for decision in eligible:
                candidate = session.get(CandidateIncidentRow, decision.candidate_id)
                if candidate is None or candidate.status != "active":
                    continue
                members = list(
                    session.scalars(
                        select(TicketRow).where(
                            TicketRow.candidate_id == candidate.id
                        )
                    ).all()
                )
                if not members:
                    continue

                member_ids = [member.id for member in members]
                mark = fingerprint(member_ids, CORRELATION_VERSION)

                # One review per (ticket, candidate, candidate state). A duplicate is not
                # an error — it means the same question was already asked.
                existing = session.scalars(
                    select(CorrelationReviewRow).where(
                        CorrelationReviewRow.ticket_id == ticket_id,
                        CorrelationReviewRow.candidate_id == candidate.id,
                        CorrelationReviewRow.candidate_fingerprint == mark,
                    )
                ).first()
                if existing is not None:
                    created.append(_to_domain(existing))
                    continue

                row = CorrelationReviewRow(
                    id=f"rev-{uuid.uuid4().hex[:12]}",
                    ticket_id=ticket_id,
                    candidate_id=candidate.id,
                    status=ReviewStatus.PENDING.value,
                    correlation_version=CORRELATION_VERSION,
                    review_policy_version=REVIEW_POLICY_VERSION,
                    feature_schema=FEATURE_SCHEMA_VERSION,
                    candidate_fingerprint=mark,
                    ticket_snapshot=_ticket_snapshot(ticket),
                    candidate_snapshot=_candidate_snapshot(candidate, members),
                    correlation_snapshot={
                        "deterministic_score": decision.deterministic_score,
                        "eligible": decision.eligible,
                        "reasons": list(decision.reasons),
                        "blocking_reasons": list(decision.blocking_reasons),
                        "correlation_version": CORRELATION_VERSION,
                        "review_policy_version": REVIEW_POLICY_VERSION,
                    },
                    feature_snapshot=extract(
                        arriving,
                        [
                            _correlation_ticket(member)
                            for member in members
                        ],
                    ),
                )
                session.add(row)
                session.flush()
                created.append(_to_domain(row))
        return created

    # --- reads ---------------------------------------------------------------------------

    def pending(self) -> list[CorrelationReview]:
        return self._list(ReviewStatus.PENDING)

    def all_reviews(self) -> list[CorrelationReview]:
        return self._list(None)

    def _list(self, status: ReviewStatus | None) -> list[CorrelationReview]:
        statement = select(CorrelationReviewRow).order_by(
            CorrelationReviewRow.created_at, CorrelationReviewRow.id
        )
        if status is not None:
            statement = statement.where(CorrelationReviewRow.status == status.value)
        with self._session() as session:
            rows = list(session.scalars(statement).all())
        # Staleness is evaluated on read so a queue never offers a question whose answer
        # would be applied to a candidate that has since changed.
        return [self._refresh(row) for row in rows]

    def get(self, review_id: str) -> CorrelationReview | None:
        with self._session() as session:
            row = session.get(CorrelationReviewRow, review_id)
        return self._refresh(row) if row is not None else None

    def _refresh(self, row: CorrelationReviewRow) -> CorrelationReview:
        """Marks a pending review stale when its candidate no longer matches."""
        if row.status != ReviewStatus.PENDING.value:
            return _to_domain(row)
        if self._current_fingerprint(row.candidate_id) == row.candidate_fingerprint:
            return _to_domain(row)

        with self._session.begin() as session:
            fresh = session.get(CorrelationReviewRow, row.id, with_for_update=True)
            if fresh is not None and fresh.status == ReviewStatus.PENDING.value:
                fresh.status = ReviewStatus.STALE.value
                session.flush()
                return _to_domain(fresh)
        return _to_domain(row)

    def _current_fingerprint(self, candidate_id: str) -> str | None:
        with self._session() as session:
            candidate = session.get(CandidateIncidentRow, candidate_id)
            if candidate is None or candidate.status != "active":
                return None
            members = session.scalars(
                select(TicketRow.id).where(TicketRow.candidate_id == candidate_id)
            ).all()
        return fingerprint(list(members), CORRELATION_VERSION)

    # --- decisions --------------------------------------------------------------------------

    def confirm(
        self, review_id: str, *, reason: str | None = None, note: str | None = None
    ) -> DecisionResult:
        """Attaches the ticket, using the same path automatic attachment uses."""
        return self._decide(
            review_id, ReviewDecision.CONFIRM_SAME_INCIDENT, reason, note
        )

    def reject(
        self, review_id: str, *, reason: str | None = None, note: str | None = None
    ) -> DecisionResult:
        """Records that this ticket does not belong to *this* candidate.

        Not that it belongs to nothing — other pending reviews for the same ticket stay
        open, because rejecting one grouping says nothing about another.
        """
        return self._decide(
            review_id, ReviewDecision.REJECT_DIFFERENT_INCIDENT, reason, note
        )

    def _decide(
        self,
        review_id: str,
        decision: ReviewDecision,
        reason: str | None,
        note: str | None,
    ) -> DecisionResult:
        confirming = decision is ReviewDecision.CONFIRM_SAME_INCIDENT
        allowed = ConfirmReason if confirming else RejectReason
        if reason is not None and reason not in {entry.value for entry in allowed}:
            raise ReviewError(
                f"unknown reason {reason!r}; expected one of "
                + ", ".join(sorted(entry.value for entry in allowed))
            )

        with self._session.begin() as session:
            # Row lock: two operators clicking at once must produce one decision, and the
            # loser must see a conflict rather than a second attachment.
            row = session.get(CorrelationReviewRow, review_id, with_for_update=True)
            if row is None:
                raise ReviewError(f"unknown review {review_id}")

            if row.status in (ReviewStatus.CONFIRMED.value, ReviewStatus.REJECTED.value):
                if row.decision == decision.value:
                    # Idempotent replay of the same decision.
                    return self._result(session, _to_domain(row), replay=True)
                raise ReviewConflict(
                    f"review {review_id} was already {row.status}; a decision is not "
                    "reopened by submitting the opposite one"
                )
            if row.status == ReviewStatus.STALE.value:
                raise ReviewConflict(
                    f"review {review_id} is stale: the candidate changed after it was "
                    "created, so this answer would apply to a different grouping"
                )

            current = self._current_fingerprint_in(session, row.candidate_id)
            if current != row.candidate_fingerprint:
                row.status = ReviewStatus.STALE.value
                session.flush()
                raise ReviewConflict(
                    f"review {review_id} is stale: the candidate changed after it was "
                    "created, so this answer would apply to a different grouping"
                )

            ticket = session.get(TicketRow, row.ticket_id, with_for_update=True)
            if ticket is None:
                raise ReviewError(f"unknown ticket {row.ticket_id}")

            superseded: list[str] = []
            attached = False
            membership = None

            if confirming:
                if ticket.candidate_id and ticket.candidate_id != row.candidate_id:
                    raise ReviewConflict(
                        f"ticket {ticket.id} is already attached to "
                        f"{ticket.candidate_id}; a report cannot belong to two incidents"
                    )
                ticket.candidate_id = row.candidate_id
                session.flush()
                self._recompute(session, row.candidate_id)
                attached = True
                members = session.scalars(
                    select(TicketRow.id).where(
                        TicketRow.candidate_id == row.candidate_id
                    )
                ).all()
                membership = {
                    "candidate_id": row.candidate_id,
                    "member_ids": sorted(members),
                    "fingerprint": fingerprint(list(members), CORRELATION_VERSION),
                }
                # A ticket cannot belong to two mutually exclusive candidates, so other
                # pending questions about it are no longer answerable.
                others = session.scalars(
                    select(CorrelationReviewRow).where(
                        CorrelationReviewRow.ticket_id == row.ticket_id,
                        CorrelationReviewRow.id != row.id,
                        CorrelationReviewRow.status == ReviewStatus.PENDING.value,
                    )
                ).all()
                for other in others:
                    other.status = ReviewStatus.STALE.value
                    superseded.append(other.id)

            row.status = (
                ReviewStatus.CONFIRMED.value if confirming else ReviewStatus.REJECTED.value
            )
            row.decision = decision.value
            row.decision_reason = reason
            row.decision_note = note
            row.actor = DEMO_OPERATOR
            row.decided_at = datetime.now(UTC)
            row.resulting_membership = membership
            session.flush()
            review = _to_domain(row)

        return self._result_after(review, attached, tuple(superseded))

    def _current_fingerprint_in(self, session, candidate_id: str) -> str | None:
        candidate = session.get(CandidateIncidentRow, candidate_id)
        if candidate is None or candidate.status != "active":
            return None
        members = session.scalars(
            select(TicketRow.id).where(TicketRow.candidate_id == candidate_id)
        ).all()
        return fingerprint(list(members), CORRELATION_VERSION)

    def _recompute(self, session, candidate_id: str) -> None:
        """Candidate metadata, derived from members.

        The same derivation automatic attachment uses — there is no separate manual path
        with different semantics, so a human-attached ticket leaves the candidate in
        exactly the shape an automatic one would.
        """
        candidate = session.get(CandidateIncidentRow, candidate_id)
        members = list(
            session.scalars(
                select(TicketRow).where(TicketRow.candidate_id == candidate_id)
            ).all()
        )
        if candidate is None or not members:
            return
        services = {m.service_id for m in members}
        issues = {m.issue_type for m in members}
        reporters = {m.reported_by for m in members if m.reported_by != "unknown"}

        candidate.ticket_count = len(members)
        candidate.first_seen = min(m.created_at for m in members)
        candidate.last_seen = max(m.created_at for m in members)
        candidate.service_id = services.pop() if len(services) == 1 else None
        candidate.issue_type = issues.pop() if len(issues) == 1 else None
        candidate.distinct_reporters = len(reporters) or None

    def _result_after(
        self, review: CorrelationReview, attached: bool, superseded: tuple[str, ...]
    ) -> DecisionResult:
        with self._session() as session:
            return self._result(
                session, review, attached=attached, superseded=superseded
            )

    def _result(
        self,
        session,
        review: CorrelationReview,
        *,
        attached: bool | None = None,
        superseded: tuple[str, ...] = (),
        replay: bool = False,
    ) -> DecisionResult:
        candidate = session.get(CandidateIncidentRow, review.candidate_id)
        payload = None
        if candidate is not None:
            payload = {
                "id": candidate.id,
                "title": candidate.title,
                "ticket_count": candidate.ticket_count,
                "first_seen": _aware(candidate.first_seen).isoformat(),
                "last_seen": _aware(candidate.last_seen).isoformat(),
                "status": candidate.status,
            }
        confirmed = review.status is ReviewStatus.CONFIRMED
        return DecisionResult(
            review=review,
            attached=confirmed if attached is None else attached,
            candidate=payload,
            # Reported, never acted on: a model call stays the operator's choice.
            investigation_stale=confirmed and self._has_investigation(review.candidate_id),
            superseded_review_ids=superseded,
        )

    def _has_investigation(self, candidate_id: str) -> bool:
        from app.db.investigation_store import InvestigationRunStore

        return InvestigationRunStore(self._engine).latest_successful(candidate_id) is not None


def _to_domain(row: CorrelationReviewRow) -> CorrelationReview:
    return CorrelationReview(
        id=row.id,
        ticket_id=row.ticket_id,
        candidate_id=row.candidate_id,
        status=ReviewStatus(row.status),
        decision=ReviewDecision(row.decision) if row.decision else None,
        decision_reason=row.decision_reason,
        decision_note=row.decision_note,
        actor=row.actor,
        correlation_version=row.correlation_version,
        review_policy_version=row.review_policy_version,
        feature_schema=row.feature_schema,
        candidate_fingerprint=row.candidate_fingerprint,
        ticket_snapshot=row.ticket_snapshot,
        candidate_snapshot=row.candidate_snapshot,
        correlation_snapshot=row.correlation_snapshot,
        feature_snapshot=row.feature_snapshot,
        created_at=_aware(row.created_at),
        decided_at=_aware(row.decided_at),
        resulting_membership=row.resulting_membership,
    )
