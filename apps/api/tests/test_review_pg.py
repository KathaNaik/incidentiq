"""Operator correlation review, against a real PostgreSQL.

A review is almost entirely persistence: an immutable snapshot, a fingerprint that pins
it to one candidate state, a decision recorded once. None of that is observable through a
fake, so these run against the database or not at all.
"""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select, text

pytestmark = pytest.mark.pg

from app.config import get_settings  # noqa: E402

DATABASE_URL = os.environ.get("DATABASE_URL") or get_settings().database_url
if not DATABASE_URL:  # pragma: no cover - environment dependent
    pytest.skip("no DATABASE_URL", allow_module_level=True)

from app.correlation.rules import LINK_THRESHOLD  # noqa: E402
from app.db.engine import get_engine, sessionmaker_for  # noqa: E402
from app.db.models import (  # noqa: E402
    CandidateIncidentRow,
    CorrelationDecisionRow,
    CorrelationReviewRow,
    TicketRow,
)
from app.fixtures import load_dataset  # noqa: E402
from app.intake import CorrelationOutcome, CreateTicketRequest, TicketIntake  # noqa: E402
from app.review.models import (  # noqa: E402
    REVIEW_POLICY_VERSION,
    ReviewDecision,
    ReviewStatus,
)
from app.review.service import ReviewConflict, ReviewService, fingerprint  # noqa: E402

BASE = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)
SERVICES = frozenset(s.id for s in load_dataset(get_settings().fixtures_dir).services)


@pytest.fixture
def clean():
    engine = get_engine()
    with engine.begin() as connection:
        connection.execute(delete(CorrelationReviewRow))
        connection.execute(delete(CorrelationDecisionRow))
        connection.execute(text("UPDATE tickets SET candidate_id = NULL"))
        connection.execute(delete(CandidateIncidentRow))
        connection.execute(delete(TicketRow))
    return engine


@pytest.fixture
def intake(clean) -> TicketIntake:
    return TicketIntake(known_services=SERVICES)


@pytest.fixture
def reviews(clean) -> ReviewService:
    return ReviewService()


def at(minutes: float) -> datetime:
    return BASE + timedelta(minutes=minutes)


def submit(
    intake: TicketIntake,
    title: str,
    description: str,
    minutes: float,
    service: str = "svc-auth",
):
    return intake.submit(
        CreateTicketRequest(
            external_id=f"EXT-{uuid.uuid4().hex[:8]}",
            title=title,
            description=description,
            created_at=at(minutes),
            reported_service_id=service,
        )
    )


# The seed incident: two tightly-worded reports of one SSO failure.
SSO_A = (
    "SSO sign-in returns invalid assertion for the whole team",
    "Nobody on our workspace can sign in through their identity provider since about "
    "09:00 UTC. The console shows an invalid assertion immediately after the redirect "
    "back from the IdP. Direct password sign-in still works for two local accounts.",
)
SSO_B = (
    "Login loop after redirect from identity provider",
    "Reporter is bounced between the console and their IdP repeatedly and never reaches "
    "the workspace. Clearing cookies does not help. Reproduced on two browsers.",
)
# The same incident said in different words. Deterministic correlation refuses this —
# it is the case M16, M17 and M18 all failed to recover, and the reason M19 exists.
PARAPHRASE = (
    "Users complete SSO but their workspace never finishes loading",
    "Everyone gets through the single sign-on step, then nothing happens. The workspace "
    "never finishes opening for them.",
)
# Same service, different mechanism. Must not be grouped with a sign-in failure.
DIFFERENT_MECHANISM = (
    "Auth service admin console is slow to list users",
    "Loading the user directory in the admin console takes about forty seconds. "
    "Sign-in itself works fine for everyone.",
)


def seed_incident(intake: TicketIntake) -> str:
    submit(intake, *SSO_A, minutes=0)
    result = submit(intake, *SSO_B, minutes=11)
    assert result.correlation.candidate_id is not None
    return result.correlation.candidate_id


# --- eligibility ----------------------------------------------------------------------


def test_an_automatic_attachment_creates_no_review(intake, reviews) -> None:
    """The common case must not reach an operator."""
    seed_incident(intake)
    result = submit(
        intake,
        "SSO sign-in returns invalid assertion after IdP redirect",
        "Nobody on the workspace can sign in through their identity provider. The "
        "reporter is bounced back from the IdP and never reaches the workspace.",
        minutes=14,
    )

    assert result.correlation.outcome is CorrelationOutcome.ATTACHED
    assert reviews.pending() == []


def test_an_unrelated_ticket_creates_no_review(intake, reviews) -> None:
    """A hard conflict is rejected automatically; operators are not asked about it."""
    seed_incident(intake)
    result = submit(
        intake,
        "Meeting room display will not turn on",
        "The screen in the third floor room stays black.",
        minutes=18,
        service="svc-analytics",
    )

    assert result.correlation.outcome is not CorrelationOutcome.ATTACHED
    assert reviews.pending() == []


def test_a_low_overlap_paraphrase_creates_a_review(intake, reviews) -> None:
    """The decision boundary M19 exists to capture."""
    candidate_id = seed_incident(intake)
    result = submit(intake, *PARAPHRASE, minutes=22)

    assert result.correlation.outcome is not CorrelationOutcome.ATTACHED

    pending = reviews.pending()
    assert len(pending) == 1
    review = pending[0]
    assert review.ticket_id == result.ticket.id
    assert review.candidate_id == candidate_id
    assert review.status is ReviewStatus.PENDING
    assert review.decision is None
    assert review.review_policy_version == REVIEW_POLICY_VERSION


# --- snapshot -------------------------------------------------------------------------


def test_the_snapshot_records_the_state_the_operator_reviewed(intake, reviews) -> None:
    seed_incident(intake)
    result = submit(intake, *PARAPHRASE, minutes=22)
    review = reviews.pending()[0]

    assert review.ticket_snapshot["title"] == PARAPHRASE[0]
    assert review.ticket_snapshot["id"] == result.ticket.id

    members = review.candidate_snapshot["members"]
    assert len(members) == 2
    # Every member must predate the arriving report; a snapshot containing a ticket that
    # had not been filed yet would be a label about a state that never existed.
    assert all(m["created_at"] <= review.ticket_snapshot["created_at"] for m in members)

    # The features are the ones computed at review time, not recomputed later.
    assert review.feature_schema == "pairwise-features-v1"
    assert review.feature_snapshot["service_same"] == 1.0
    assert review.feature_snapshot["candidate_size"] == 2.0

    assert review.correlation_snapshot["deterministic_score"] < LINK_THRESHOLD


def test_the_fingerprint_pins_the_reviewed_membership(intake, reviews) -> None:
    candidate_id = seed_incident(intake)
    submit(intake, *PARAPHRASE, minutes=22)
    review = reviews.pending()[0]

    member_ids = [m["id"] for m in review.candidate_snapshot["members"]]
    assert review.candidate_fingerprint == fingerprint(
        member_ids, review.correlation_version
    )
    # Order must not matter; membership is a set.
    assert fingerprint(list(reversed(member_ids)), review.correlation_version) == (
        review.candidate_fingerprint
    )
    assert candidate_id == review.candidate_id


# --- decisions ------------------------------------------------------------------------


def test_confirming_attaches_the_ticket_once(intake, reviews) -> None:
    candidate_id = seed_incident(intake)
    result = submit(intake, *PARAPHRASE, minutes=22)
    review = reviews.pending()[0]

    decision = reviews.confirm(review.id, reason="same_symptoms")

    assert decision.attached is True
    assert decision.review.status is ReviewStatus.CONFIRMED
    assert decision.review.decision is ReviewDecision.CONFIRM_SAME_INCIDENT
    assert decision.review.decided_at is not None
    assert decision.review.actor

    session = sessionmaker_for(get_engine())
    with session() as s:
        ticket = s.get(TicketRow, result.ticket.id)
        assert ticket.candidate_id == candidate_id
        members = s.scalars(
            select(TicketRow.id).where(TicketRow.candidate_id == candidate_id)
        ).all()
        assert len(members) == 3
        assert members.count(result.ticket.id) == 1


def test_confirming_twice_is_idempotent(intake, reviews) -> None:
    candidate_id = seed_incident(intake)
    submit(intake, *PARAPHRASE, minutes=22)
    review = reviews.pending()[0]

    first = reviews.confirm(review.id)
    second = reviews.confirm(review.id)

    assert first.review.decided_at == second.review.decided_at

    session = sessionmaker_for(get_engine())
    with session() as s:
        members = s.scalars(
            select(TicketRow.id).where(TicketRow.candidate_id == candidate_id)
        ).all()
        assert len(members) == 3


def test_rejecting_leaves_the_candidate_untouched(intake, reviews) -> None:
    candidate_id = seed_incident(intake)
    result = submit(intake, *PARAPHRASE, minutes=22)
    review = reviews.pending()[0]

    decision = reviews.reject(review.id, reason="different_mechanism", note="Not this.")

    assert decision.attached is False
    assert decision.review.status is ReviewStatus.REJECTED
    assert decision.review.decision is ReviewDecision.REJECT_DIFFERENT_INCIDENT
    assert decision.review.decision_note == "Not this."

    session = sessionmaker_for(get_engine())
    with session() as s:
        assert s.get(TicketRow, result.ticket.id).candidate_id is None
        members = s.scalars(
            select(TicketRow.id).where(TicketRow.candidate_id == candidate_id)
        ).all()
        assert len(members) == 2


def test_a_decided_review_cannot_be_decided_again(intake, reviews) -> None:
    seed_incident(intake)
    submit(intake, *PARAPHRASE, minutes=22)
    review = reviews.pending()[0]

    reviews.confirm(review.id)
    with pytest.raises(ReviewConflict):
        reviews.reject(review.id)


# --- the label the export depends on --------------------------------------------------


def test_the_decision_carries_the_northstar_label(intake, reviews) -> None:
    seed_incident(intake)
    submit(intake, *PARAPHRASE, minutes=22)
    confirmed = reviews.confirm(reviews.pending()[0].id).review

    seed = submit(intake, *DIFFERENT_MECHANISM, minutes=40)
    assert seed  # a second review to reject

    assert confirmed.label == 1


# --- the defect this milestone exposed ------------------------------------------------


@pytest.mark.xfail(
    reason=(
        "Confirming a low-overlap paraphrase makes it a durable member of the candidate. "
        "_upsert_candidate then reconciles any later grouping onto an existing candidate "
        "by membership *overlap*, so a ticket that clusters with the paraphrase alone "
        "inherits the whole incident without ever clearing linkage against its other "
        "members. Measured: the different-mechanism ticket scores 0.405 against the "
        "original members and is correctly refused, but attaches at 0.639 once the "
        "paraphrase is confirmed. Fixing this changes deterministic-correlation-v1 "
        "attach semantics, which six milestones of evaluations depend on."
    ),
    strict=True,
)
def test_confirming_does_not_widen_the_candidate(intake, reviews) -> None:
    """An operator confirming one pair must not silently admit a third ticket.

    The operator answered exactly one question: is this paraphrase the same incident?
    Nothing in that decision authorises a different failure mechanism to join.
    """
    candidate_id = seed_incident(intake)
    submit(intake, *PARAPHRASE, minutes=22)
    reviews.confirm(reviews.pending()[0].id, reason="same_symptoms")

    result = submit(intake, *DIFFERENT_MECHANISM, minutes=28)

    assert result.correlation.outcome is not CorrelationOutcome.ATTACHED, (
        "a performance complaint auto-joined a sign-in incident because the "
        "operator-confirmed paraphrase bridged them"
    )

    session = sessionmaker_for(get_engine())
    with session() as s:
        members = s.scalars(
            select(TicketRow.id).where(TicketRow.candidate_id == candidate_id)
        ).all()
        assert len(members) == 3
