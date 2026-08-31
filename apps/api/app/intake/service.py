"""Ticket intake: validate, persist, triage, correlate.

The whole point of this module is that **it does not implement correlation**. A second
scoring implementation would drift from the one M5 and M6 measured, and the number that
was evaluated would stop describing the system that runs. So intake replays the active
window through `correlate()` — the same function, same thresholds, same guardrails — and
reads off where the new ticket landed.

That is what "incremental" means here. The engine already processes tickets
chronologically and only offers each one to candidates that are still open; feeding it a
window rather than all history is the only difference, and at Northstar scale the window
is tens of tickets.

**Transaction shape.** The ticket and its triage are committed first, on their own. If
correlation then fails, the report still exists and says so, rather than a submitted
ticket vanishing because a grouping decision could not be made. Correlation and candidate
membership are then written in a second transaction that either completes or leaves the
ticket uncorrelated — never half-attached.

**No model is called.** Triage is the deterministic baseline and correlation is
arithmetic. Investigation stays explicit, which is what keeps intake fast, free, and
predictable.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError

from app.correlation import CorrelationTicket, correlate
from app.correlation.models import CandidateIncident
from app.correlation.rules import CORRELATION_VERSION
from app.db.engine import get_engine, sessionmaker_for
from app.db.models import CandidateIncidentRow, CorrelationDecisionRow, TicketRow
from app.intake.models import (
    CorrelationDecision,
    CorrelationOutcome,
    CreateTicketRequest,
    RuntimeTicket,
    TicketIntakeResult,
    TicketSource,
    TriageSummary,
)
from app.correlation.rules import FALLBACK_POLICY_VERSION
from app.intake.rules import (
    CANDIDATE_MARGIN,
    FUTURE_TOLERANCE,
    LIVE_CORRELATION_MODE,
    REPLAY_WINDOW,
    RESERVED_SOURCES,
)
from app.triage import TriageInput, triage
from app.triage.rules import TRIAGE_VERSION


class IntakeError(ValueError):
    """The submission cannot be accepted. Surfaced as a 4xx with a plain reason."""


class DuplicateTicketError(IntakeError):
    """An external id was reused with a different payload.

    Distinct from an identical replay, which is a success. Silently overwriting the
    earlier ticket would discard a report somebody filed.
    """


def _aware(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class TicketIntake:
    def __init__(
        self,
        engine: Engine | None = None,
        known_services: frozenset[str] = frozenset(),
        strategy: str = LIVE_CORRELATION_MODE,
        similarity_factory=None,
    ) -> None:
        self._engine = engine or get_engine()
        self._session = sessionmaker_for(self._engine)
        self._known_services = known_services
        self._strategy = strategy
        # A factory, not a provider: nothing is constructed — and certainly nothing
        # embedded — unless a candidate actually passes fallback eligibility.
        self._similarity_factory = similarity_factory

    # --- intake ---------------------------------------------------------------------

    def submit(self, request: CreateTicketRequest) -> TicketIntakeResult:
        """Accepts one report and returns what the system did with it."""
        self._validate(request)

        existing = self._existing(request)
        if existing is not None:
            return existing

        ticket_row = self._persist(request)
        decision, candidate = self._correlate(ticket_row.id)
        return self._result(ticket_row.id, decision, candidate)

    def _validate(self, request: CreateTicketRequest) -> None:
        if not request.title.strip() and not request.description.strip():
            raise IntakeError("a ticket needs a title or a description")
        if not request.title.strip():
            raise IntakeError("a ticket needs a title")
        if not request.external_id.strip():
            raise IntakeError("external_id cannot be blank")
        if request.external_id.strip() in RESERVED_SOURCES:
            raise IntakeError("external_id must not impersonate a source name")
        if (
            request.reported_service_id
            and self._known_services
            and request.reported_service_id not in self._known_services
        ):
            raise IntakeError(
                f"unknown service {request.reported_service_id!r}; omit it if the "
                "reporter did not identify one"
            )
        created = _aware(request.created_at)
        if created > datetime.now(UTC) + FUTURE_TOLERANCE:
            raise IntakeError(
                "created_at is in the future by more than clock skew allows; a report "
                "cannot describe something that has not happened"
            )

    def _existing(self, request: CreateTicketRequest) -> TicketIntakeResult | None:
        """Idempotency, keyed on external id.

        An identical resubmission returns the original outcome and correlates nothing a
        second time. A *different* payload under the same key is a conflict, because the
        caller is describing two different reports with one identity.
        """
        with self._session() as session:
            row = session.scalars(
                select(TicketRow).where(TicketRow.external_id == request.external_id)
            ).first()
            if row is None:
                return None
            if row.title != request.title or row.description != request.description:
                raise DuplicateTicketError(
                    f"external_id {request.external_id!r} already exists with different "
                    "content; use a new external_id for a new report"
                )
            ticket_id = row.id

        decision = self._stored_decision(ticket_id)
        candidate = self._candidate_of(ticket_id)
        result = self._result(ticket_id, decision, candidate)
        return result.model_copy(update={"idempotent_replay": True})

    def _persist(self, request: CreateTicketRequest) -> TicketRow:
        """Ticket and triage, committed together and before correlation is attempted."""
        prediction = triage(
            TriageInput(
                ticket_id=request.external_id,
                title=request.title,
                description=request.description,
            )
        )
        created = _aware(request.created_at)
        row = TicketRow(
            id=f"TKT-{uuid.uuid4().hex[:10].upper()}",
            external_id=request.external_id,
            source=TicketSource.API.value,
            title=request.title.strip(),
            description=request.description.strip(),
            reported_by=request.reported_by,
            status="open",
            created_at=created,
            received_at=datetime.now(UTC),
            reported_service_id=request.reported_service_id,
            # The reporter's claim wins when they made one; triage fills the gap.
            service_id=request.reported_service_id or _value(prediction.service),
            priority=_value(prediction.priority),
            issue_type=_value(prediction.issue_type),
            triage_version=TRIAGE_VERSION,
            triage_signals=_signals(prediction),
        )
        try:
            with self._session.begin() as session:
                session.add(row)
        except IntegrityError as error:
            # Lost a race on the unique external id. The winner's ticket is the one that
            # exists, so return it rather than failing the caller.
            replay = self._existing(request)
            if replay is not None:
                return self._row(replay.ticket.id)
            raise DuplicateTicketError(str(error)) from error
        return row

    # --- correlation ------------------------------------------------------------------

    def _correlate(self, ticket_id: str) -> tuple[CorrelationDecision, dict | None]:
        """Replays the active window through the correlation baseline.

        Wrapped: a correlation failure leaves the ticket persisted and uncorrelated with
        the reason recorded, rather than losing a report over a grouping decision.
        """
        try:
            decision, candidate, window = self._run_correlation(ticket_id)
            if window is not None:
                # After the transaction, so the locks are released and the ticket is
                # already durable. Review capture is supplementary; it must never be
                # able to cost somebody their report.
                self._open_reviews(ticket_id, window)
            return decision, candidate
        except Exception as error:  # noqa: BLE001 - the ticket must survive any failure
            decision = CorrelationDecision(
                ticket_id=ticket_id,
                candidate_id=None,
                outcome=CorrelationOutcome.FAILED,
                correlation_version=CORRELATION_VERSION,
                score=None,
                confidence=None,
                created_new_candidate=False,
                reason=f"correlation failed: {error}",
            )
            self._record(decision)
            return decision, None

    def _run_correlation(self, ticket_id: str):
        """Returns (decision, candidate, window-needing-review-or-None)."""
        with self._session.begin() as session:
            # SELECT ... FOR UPDATE on the arriving ticket serialises intake for the
            # window it belongs to, so two near-simultaneous related reports cannot each
            # decide they are the first and create separate candidates.
            arriving = session.get(TicketRow, ticket_id, with_for_update=True)
            if arriving is None:
                raise IntakeError(f"unknown ticket {ticket_id}")

            window_start = arriving.created_at - REPLAY_WINDOW
            rows = session.scalars(
                select(TicketRow)
                .where(
                    TicketRow.created_at >= window_start,
                    TicketRow.created_at <= arriving.created_at,
                )
                .order_by(TicketRow.created_at, TicketRow.id)
                .with_for_update()
            ).all()

            window = [_to_correlation_ticket(row) for row in rows]
            if self._strategy == "hybrid":
                result, group, staging = self._hybrid(window, ticket_id)
            else:
                result = correlate(window)
                group = next(
                    (c for c in result.candidates if ticket_id in c.ticket_ids), None
                )
                staging = {}

            if group is None:
                # The ticket did not attach. Whether that is worth an operator's time is
                # decided after this transaction commits — creating a review here would
                # open a second transaction while this one still holds FOR UPDATE locks
                # on the same rows, and wait on itself forever.
                needs_review = True
                decision = CorrelationDecision(
                    ticket_id=ticket_id,
                    candidate_id=None,
                    outcome=CorrelationOutcome.UNCORRELATED,
                    correlation_version=result.version,
                    score=None,
                    confidence=None,
                    created_new_candidate=False,
                    reason=staging.get("reason")
                    or (
                        "no active candidate met the linkage thresholds; the ticket "
                        "stands on its own, which is a valid operational state"
                    ),
                    **staging.get("fields", {}),
                )
                arriving.candidate_id = None
                self._record(decision, session=session)
                return decision, None, window if needs_review else None

            # Ambiguity: another group in the same window is nearly as good a home.
            alternatives = _close_alternatives(result.candidates, group)
            if alternatives:
                decision = CorrelationDecision(
                    ticket_id=ticket_id,
                    candidate_id=None,
                    outcome=CorrelationOutcome.AMBIGUOUS,
                    correlation_version=result.version,
                    score=group.score,
                    confidence=group.confidence.value,
                    created_new_candidate=False,
                    reason=(
                        f"{len(alternatives) + 1} candidates scored within "
                        f"{CANDIDATE_MARGIN} of each other; attaching to one would be "
                        "inventing certainty"
                    ),
                    alternatives=alternatives,
                    **staging.get("fields", {}),
                )
                arriving.candidate_id = None
                self._record(decision, session=session)
                return decision, None, None

            row, created_new = self._upsert_candidate(session, group)

            for member_id in group.ticket_ids:
                member = session.get(TicketRow, member_id)
                if member is not None:
                    member.candidate_id = row.id
            self._recompute(session, row, group)

            decision = CorrelationDecision(
                ticket_id=ticket_id,
                candidate_id=row.id,
                outcome=(
                    CorrelationOutcome.CREATED_CANDIDATE
                    if created_new
                    else CorrelationOutcome.ATTACHED
                ),
                correlation_version=result.version,
                score=group.score,
                confidence=group.confidence.value,
                created_new_candidate=created_new,
                supporting_signals=tuple(s.detail for s in group.supporting_signals),
                conflicting_signals=tuple(s.detail for s in group.conflicting_signals),
                reason=(
                    f"grouped with {group.ticket_count - 1} other report(s) at score "
                    f"{group.score} ({group.confidence.value} confidence)"
                ),
                **staging.get("fields", {}),
            )
            self._record(decision, session=session)
            session.flush()
            candidate = _candidate_payload(row)
        return decision, candidate, None

    def _hybrid(self, window, ticket_id: str):
        """Deterministic first, semantic only where the gate says it could help.

        The similarity provider is constructed lazily here so that a submission which
        never reaches fallback costs nothing at all — not even a model load.
        """
        from app.correlation.hybrid import correlate_hybrid

        similarity = self._similarity_factory() if self._similarity_factory else None
        outcome = correlate_hybrid(window, ticket_id, similarity)

        result = outcome.result if outcome.result is not None else correlate(window)
        group = (
            next((c for c in result.candidates if ticket_id in c.ticket_ids), None)
            if outcome.attached
            else None
        )

        fields = {
            "strategy": outcome.version,
            "deterministic_stage": {
                "attached": outcome.deterministic_attached,
                "candidate_id": outcome.deterministic_candidate_id,
                "score": outcome.deterministic_score,
            },
            "fallback_stage": {
                "semantic_invoked": outcome.semantic_invoked,
                "semantic_score": outcome.semantic_score,
                "failed": outcome.semantic_failed,
                "policy_version": FALLBACK_POLICY_VERSION,
                "decisions": [
                    {
                        "candidate_id": decision.candidate_id,
                        "eligible": decision.eligible,
                        "reasons": list(decision.reasons),
                        "blocking_reasons": list(decision.blocking_reasons),
                    }
                    for decision in outcome.fallback_decisions
                ],
            },
            "embedding_model": outcome.embedding_model,
        }
        reason = None
        if outcome.semantic_failed:
            # The ticket survives. It is not attached, the failure is named, and nothing
            # falls back to a deterministic attachment the deterministic stage refused.
            reason = f"semantic fallback failed — {outcome.failure_reason}"
        return result, group, {"fields": fields, "reason": reason}

    def _open_reviews(self, ticket_id: str, window) -> list:
        """Creates reviews for plausible candidates, if any.

        Deliberately defensive: a review is supplementary data capture, and failing to
        create one must never cost the operator their ticket. The failure is surfaced by
        the empty queue rather than by a lost report.
        """
        try:
            from app.review import ReviewService

            return ReviewService(self._engine).create_for_intake(ticket_id, window)
        except Exception:  # noqa: BLE001 - review capture never blocks intake
            return []

    def _upsert_candidate(
        self, session, group: CandidateIncident
    ) -> tuple[CandidateIncidentRow, bool]:
        """Finds the persisted candidate this grouping continues, or starts one.

        Matched by **membership overlap**, not by id. The engine derives its id from the
        earliest member, so a back-dated report arriving later would otherwise rename the
        candidate an operator is already looking at. Any existing candidate sharing a
        ticket with this grouping is the same incident, and keeps its identity.
        """
        existing = session.scalars(
            select(CandidateIncidentRow)
            .join(TicketRow, TicketRow.candidate_id == CandidateIncidentRow.id)
            .where(TicketRow.id.in_(group.ticket_ids))
            .order_by(CandidateIncidentRow.created_at)
        ).first()
        if existing is not None:
            return existing, False

        row = CandidateIncidentRow(
            id=group.id,
            correlation_version=CORRELATION_VERSION,
            status="active",
            title=_title(group),
            service_id=group.service_id,
            issue_type=group.issue_type,
            ticket_count=group.ticket_count,
            first_seen=group.first_seen,
            last_seen=group.last_seen,
            score=group.score,
            confidence=group.confidence.value,
            distinct_reporters=group.distinct_reporters,
            signals={
                "supporting": [s.detail for s in group.supporting_signals],
                "conflicting": [s.detail for s in group.conflicting_signals],
            },
        )
        session.add(row)
        session.flush()
        return row, True

    def _recompute(self, session, row: CandidateIncidentRow, group: CandidateIncident) -> None:
        """Derives metadata from members. Never increments a counter.

        A count that is added to and a membership that is written separately drift apart
        the first time anything fails halfway.
        """
        members = session.scalars(
            select(TicketRow).where(TicketRow.candidate_id == row.id)
        ).all()
        if not members:
            return
        services = {m.service_id for m in members}
        issues = {m.issue_type for m in members}
        reporters = {m.reported_by for m in members if m.reported_by != "unknown"}

        row.ticket_count = len(members)
        row.first_seen = min(m.created_at for m in members)
        row.last_seen = max(m.created_at for m in members)
        row.service_id = services.pop() if len(services) == 1 else None
        row.issue_type = issues.pop() if len(issues) == 1 else None
        row.score = group.score
        row.confidence = group.confidence.value
        row.distinct_reporters = len(reporters) or None
        row.title = _title(group, service_id=row.service_id, issue_type=row.issue_type)
        row.signals = {
            "supporting": [s.detail for s in group.supporting_signals],
            "conflicting": [s.detail for s in group.conflicting_signals],
        }

    # --- persistence helpers -----------------------------------------------------------

    def _record(self, decision: CorrelationDecision, session=None) -> None:
        row = CorrelationDecisionRow(
            id=f"cdc-{uuid.uuid4().hex[:12]}",
            ticket_id=decision.ticket_id,
            candidate_id=decision.candidate_id,
            outcome=decision.outcome.value,
            correlation_version=decision.correlation_version,
            triage_version=TRIAGE_VERSION,
            score=decision.score,
            confidence=decision.confidence,
            created_new_candidate=decision.created_new_candidate,
            supporting_signals=list(decision.supporting_signals),
            conflicting_signals=list(decision.conflicting_signals),
            reason=decision.reason,
            alternatives=list(decision.alternatives),
            strategy=decision.strategy,
            deterministic_stage=decision.deterministic_stage,
            fallback_stage=decision.fallback_stage,
            embedding_model=decision.embedding_model,
        )
        if session is not None:
            session.add(row)
            return
        with self._session.begin() as own:
            own.add(row)

    def _stored_decision(self, ticket_id: str) -> CorrelationDecision:
        with self._session() as session:
            row = session.scalars(
                select(CorrelationDecisionRow)
                .where(CorrelationDecisionRow.ticket_id == ticket_id)
                .order_by(CorrelationDecisionRow.decided_at.desc())
            ).first()
            if row is None:
                return CorrelationDecision(
                    ticket_id=ticket_id,
                    candidate_id=None,
                    outcome=CorrelationOutcome.UNCORRELATED,
                    correlation_version=CORRELATION_VERSION,
                    score=None,
                    confidence=None,
                    created_new_candidate=False,
                    reason="no correlation decision was recorded for this ticket",
                )
            return CorrelationDecision(
                ticket_id=row.ticket_id,
                candidate_id=row.candidate_id,
                outcome=CorrelationOutcome(row.outcome),
                correlation_version=row.correlation_version,
                score=row.score,
                confidence=row.confidence,
                created_new_candidate=row.created_new_candidate,
                supporting_signals=tuple(row.supporting_signals or ()),
                conflicting_signals=tuple(row.conflicting_signals or ()),
                reason=row.reason,
                alternatives=tuple(row.alternatives or ()),
                strategy=row.strategy,
                deterministic_stage=row.deterministic_stage,
                fallback_stage=row.fallback_stage,
                embedding_model=row.embedding_model,
            )

    def _candidate_of(self, ticket_id: str) -> dict | None:
        with self._session() as session:
            ticket = session.get(TicketRow, ticket_id)
            if ticket is None or ticket.candidate_id is None:
                return None
            row = session.get(CandidateIncidentRow, ticket.candidate_id)
            return _candidate_payload(row) if row else None

    def _row(self, ticket_id: str) -> TicketRow:
        with self._session() as session:
            row = session.get(TicketRow, ticket_id)
            if row is None:
                raise IntakeError(f"unknown ticket {ticket_id}")
            return row

    def _result(
        self, ticket_id: str, decision: CorrelationDecision, candidate: dict | None
    ) -> TicketIntakeResult:
        row = self._row(ticket_id)
        return TicketIntakeResult(
            ticket=_to_runtime(row),
            triage=TriageSummary(
                service_id=row.service_id,
                priority=row.priority,
                issue_type=row.issue_type,
                version=row.triage_version or TRIAGE_VERSION,
                signals=row.triage_signals or {},
            ),
            correlation=decision,
            candidate=candidate,
        )


# --- helpers ---------------------------------------------------------------------------


def _value(prediction) -> str | None:
    """A triage prediction's value, or None when it abstained."""
    value = getattr(prediction, "value", None)
    return None if value in (None, "unknown") else value


def _signals(result) -> dict:
    """The evidence behind the triage prediction, kept so it stays explicable.

    Both halves matter: the matched phrases say *why*, and the per-dimension status says
    whether the classifier committed or abstained — a `default` priority is not the same
    claim as a `classified` one.
    """
    return {
        "matched": [
            {
                "type": signal.signal_type.value,
                "text": signal.matched_text,
                "value": signal.normalized_value,
                "weight": signal.weight,
            }
            for signal in result.signals
        ],
        "status": {
            dimension: getattr(result, dimension).status.value
            for dimension in ("service", "issue_type", "priority")
        },
    }


def _to_correlation_ticket(row: TicketRow) -> CorrelationTicket:
    return CorrelationTicket(
        id=row.id,
        title=row.title,
        description=row.description,
        created_at=row.created_at,
        service_id=row.service_id,
        reported_by=None if row.reported_by == "unknown" else row.reported_by,
    )


def _to_runtime(row: TicketRow) -> RuntimeTicket:
    return RuntimeTicket(
        id=row.id,
        external_id=row.external_id,
        source=TicketSource(row.source),
        title=row.title,
        description=row.description,
        reported_by=row.reported_by,
        status=row.status,
        created_at=row.created_at,
        received_at=row.received_at,
        reported_service_id=row.reported_service_id,
        service_id=row.service_id,
        priority=row.priority,
        issue_type=row.issue_type,
        triage_version=row.triage_version,
        candidate_id=row.candidate_id,
    )


def _candidate_payload(row: CandidateIncidentRow) -> dict:
    return {
        "id": row.id,
        "title": row.title,
        "status": row.status,
        "service_id": row.service_id,
        "issue_type": row.issue_type,
        "ticket_count": row.ticket_count,
        "first_seen": row.first_seen.isoformat(),
        "last_seen": row.last_seen.isoformat(),
        "score": row.score,
        "confidence": row.confidence,
        "correlation_version": row.correlation_version,
    }


def _title(
    group: CandidateIncident,
    *,
    service_id: str | None = None,
    issue_type: str | None = None,
) -> str:
    """A deterministic name. No model is asked to title an incident.

    Built from what the members agree on. When they agree on nothing, the name says the
    service is mixed rather than picking one member's wording and implying consensus.
    """
    service = service_id if service_id is not None else group.service_id
    issue = issue_type if issue_type is not None else group.issue_type
    subject = service.removeprefix("svc-").replace("-", " ").title() if service else "Multi-service"
    kind = issue.replace("_", " ") if issue else "unclassified"
    return f"{subject} {kind} incident"


def _close_alternatives(
    candidates: Sequence[CandidateIncident], chosen: CandidateIncident
) -> tuple[str, ...]:
    """Other groupings in this window that scored within the margin of the chosen one."""
    return tuple(
        sorted(
            candidate.id
            for candidate in candidates
            if candidate.id != chosen.id
            and abs(candidate.score - chosen.score) < CANDIDATE_MARGIN
            and candidate.service_id == chosen.service_id
            and chosen.service_id is not None
        )
    )
