"""Seed the authored Northstar tickets into PostgreSQL.

    uv run python scripts/seed_tickets.py

Safe to re-run: tickets are keyed by their authored id, so a second run updates in place
rather than duplicating, and candidate membership is recomputed from scratch rather than
appended to.

**Distinct from `POST /demo/reset`.** Reset clears workflow state — actions, approvals,
audit events, investigations. This seeds operational input. Running reset does not
un-seed tickets, and running this does not clear an investigation.

Provenance is preserved: these rows carry `source = northstar-authored`, so an authored
demo fixture is never mistaken for something an operator submitted through the API.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.dialects.postgresql import insert  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.correlation import CorrelationTicket, correlate  # noqa: E402
from app.correlation.rules import CORRELATION_VERSION  # noqa: E402
from app.db.engine import get_engine, session_scope  # noqa: E402
from app.db.models import CandidateIncidentRow, CorrelationDecisionRow, TicketRow  # noqa: E402
from app.fixtures import load_dataset  # noqa: E402
from app.intake.models import TicketSource  # noqa: E402
from app.intake.service import _title  # noqa: E402
from app.triage import TriageInput, triage  # noqa: E402
from app.triage.rules import TRIAGE_VERSION  # noqa: E402


def main() -> int:
    settings = get_settings()
    started = time.perf_counter()
    dataset = load_dataset(settings.fixtures_dir)

    rows = []
    for ticket in dataset.tickets:
        prediction = triage(
            TriageInput(
                ticket_id=ticket.id, title=ticket.title, description=ticket.description
            )
        )
        rows.append(
            {
                "id": ticket.id,
                # No external id: these did not arrive through the intake API, and giving
                # them one would let a caller "resubmit" an authored fixture.
                "external_id": None,
                "source": TicketSource.NORTHSTAR.value,
                "title": ticket.title,
                "description": ticket.description,
                "reported_by": ticket.reported_by,
                "status": ticket.status.value,
                "created_at": ticket.created_at,
                "received_at": ticket.created_at,
                "reported_service_id": ticket.service_id,
                "service_id": ticket.service_id or _value(prediction.service),
                "priority": (ticket.priority.value if ticket.priority else None)
                or _value(prediction.priority),
                "issue_type": _value(prediction.issue_type),
                "triage_version": TRIAGE_VERSION,
                "triage_signals": {},
            }
        )

    with session_scope() as session:
        statement = insert(TicketRow).values(rows)
        session.execute(
            statement.on_conflict_do_update(
                index_elements=[TicketRow.id],
                set_={
                    column: statement.excluded[column]
                    for column in rows[0]
                    if column not in ("id", "candidate_id")
                },
            )
        )

    # Candidates are rebuilt from the seeded tickets rather than merged into whatever
    # exists, so seeding twice cannot leave a candidate holding stale membership.
    with session_scope() as session:
        seeded_ids = [row["id"] for row in rows]
        session.execute(
            delete(CorrelationDecisionRow).where(
                CorrelationDecisionRow.ticket_id.in_(seeded_ids)
            )
        )
        for ticket in session.scalars(
            select(TicketRow).where(TicketRow.id.in_(seeded_ids))
        ):
            ticket.candidate_id = None
        session.flush()
        # Remove candidates left with no members at all.
        orphans = session.scalars(
            select(CandidateIncidentRow).where(
                ~CandidateIncidentRow.id.in_(
                    select(TicketRow.candidate_id).where(TicketRow.candidate_id.isnot(None))
                )
            )
        ).all()
        for orphan in orphans:
            session.delete(orphan)

    with session_scope() as session:
        tickets = session.scalars(
            select(TicketRow)
            .where(TicketRow.source == TicketSource.NORTHSTAR.value)
            .order_by(TicketRow.created_at, TicketRow.id)
        ).all()
        result = correlate(
            [
                CorrelationTicket(
                    id=row.id,
                    title=row.title,
                    description=row.description,
                    created_at=row.created_at,
                    service_id=row.service_id,
                    reported_by=row.reported_by,
                )
                for row in tickets
            ]
        )
        by_id = {row.id: row for row in tickets}
        for group in result.candidates:
            candidate = session.get(CandidateIncidentRow, group.id)
            if candidate is None:
                candidate = CandidateIncidentRow(id=group.id)
                session.add(candidate)
            candidate.correlation_version = CORRELATION_VERSION
            candidate.status = "active"
            candidate.title = _title(group)
            candidate.service_id = group.service_id
            candidate.issue_type = group.issue_type
            candidate.ticket_count = group.ticket_count
            candidate.first_seen = group.first_seen
            candidate.last_seen = group.last_seen
            candidate.score = group.score
            candidate.confidence = group.confidence.value
            candidate.distinct_reporters = group.distinct_reporters
            candidate.signals = {
                "supporting": [s.detail for s in group.supporting_signals],
                "conflicting": [s.detail for s in group.conflicting_signals],
            }
            for ticket_id in group.ticket_ids:
                if ticket_id in by_id:
                    by_id[ticket_id].candidate_id = group.id

        # Counts come from actual membership, not from the seeded grouping.
        #
        # Seeding only re-correlates authored reports, but a candidate on a live database
        # can also hold reports submitted through the API — including ones an operator
        # attached by hand. Taking the count from the group would quietly undercount those
        # and leave the dashboard disagreeing with the membership underneath it.
        session.flush()
        for candidate in session.scalars(select(CandidateIncidentRow)).all():
            members = session.scalars(
                select(TicketRow).where(TicketRow.candidate_id == candidate.id)
            ).all()
            if not members:
                continue
            candidate.ticket_count = len(members)
            candidate.first_seen = min(m.created_at for m in members)
            candidate.last_seen = max(m.created_at for m in members)

    # Ask about the reports correlation could not place on its own.
    #
    # Without this, the review queue on a fresh deployment is empty and stays empty until
    # somebody hand-types a paraphrase — which hides the product's actual answer to its
    # own hardest case. The authored SSO incident is exactly that case: five reports a
    # human calls one outage, described in vocabulary that barely overlaps, of which
    # deterministic correlation groups two. The other three are plausible-but-undecided,
    # which is what review exists for.
    #
    # No new eligibility rule is introduced. This calls the same ReviewService the runtime
    # intake path calls, so the gate that decides "worth an operator's time" is the one
    # that was measured, and hard conflicts are still refused silently.
    reviews_opened = _open_reviews_for_seeded()

    with session_scope() as session:
        total = len(session.scalars(select(TicketRow)).all())
        candidates = session.scalars(select(CandidateIncidentRow)).all()
        uncorrelated = len(
            session.scalars(
                select(TicketRow).where(TicketRow.candidate_id.is_(None))
            ).all()
        )

    print(f"seeded in {time.perf_counter() - started:.2f}s")
    print(f"  tickets: {total} total, {uncorrelated} uncorrelated")
    print(f"  candidates: {len(candidates)}")
    print(f"  reviews awaiting an operator: {reviews_opened}")
    for candidate in sorted(candidates, key=lambda c: c.first_seen):
        print(
            f"    {candidate.id}  {candidate.title}  "
            f"{candidate.ticket_count} tickets  {candidate.confidence}"
        )
    get_engine().dispose()
    return 0


def _open_reviews_for_seeded() -> int:
    """Raises a review for each seeded report that plausibly belongs to a candidate.

    Idempotent like the rest of seeding: a review is keyed by ticket, candidate and the
    candidate's membership fingerprint, so re-running finds the existing one rather than
    asking the same question twice.

    Failures here are reported, not raised. Seeding operational input must not fail
    because a supplementary question could not be recorded.
    """
    from app.review import ReviewService
    from app.review.service import ReviewError

    service = ReviewService()
    opened = 0

    with session_scope() as session:
        window = [
            CorrelationTicket(
                id=row.id,
                title=row.title,
                description=row.description,
                created_at=row.created_at,
                service_id=row.service_id,
                reported_by=row.reported_by,
            )
            for row in session.scalars(
                select(TicketRow)
                .where(TicketRow.source == TicketSource.NORTHSTAR.value)
                .order_by(TicketRow.created_at, TicketRow.id)
            ).all()
        ]
        unplaced = [
            row.id
            for row in session.scalars(
                select(TicketRow).where(
                    TicketRow.source == TicketSource.NORTHSTAR.value,
                    TicketRow.candidate_id.is_(None),
                )
            ).all()
        ]

    for ticket_id in unplaced:
        try:
            opened += len(service.create_for_intake(ticket_id, window))
        except ReviewError as error:  # pragma: no cover - reported, never fatal
            print(f"  note: could not raise a review for {ticket_id}: {error}")

    return opened


def _value(prediction) -> str | None:
    value = getattr(prediction, "value", None)
    return None if value in (None, "unknown") else value


if __name__ == "__main__":
    raise SystemExit(main())
