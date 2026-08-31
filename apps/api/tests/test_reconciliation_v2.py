"""deterministic-correlation-v2: safe candidate reconciliation.

v1 let membership overlap answer two questions at once. Deciding which durable candidate
a recomputed cluster *is* was correct; concluding that everything in the cluster therefore
belonged to that candidate was not. These tests hold both halves apart.

The scenario throughout is the one the M19 acceptance run surfaced:

    A, B   two SSO reports that correlate automatically
    C      a low-overlap paraphrase of the same incident, refused automatically and
           attached by an operator through review
    D      an unrelated performance complaint on the same service
    E      a genuine later SSO report

Measured under v1, with C confirmed: D scored 0.4054 and 0.4577 against A and B — the
members it would be joining — and 0.6369 against C alone. The cluster {C, D} overlapped
the candidate at C, so D inherited the incident. v2 refuses it.
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

from app.correlation.rules import CORRELATION_VERSION, CORRELATION_VERSION_V2  # noqa: E402
from app.db.engine import get_engine, sessionmaker_for  # noqa: E402
from app.db.models import (  # noqa: E402
    CandidateIncidentRow,
    CorrelationDecisionRow,
    CorrelationReviewRow,
    TicketRow,
)
from app.fixtures import load_dataset  # noqa: E402
from app.intake import CorrelationOutcome, CreateTicketRequest, TicketIntake  # noqa: E402
from app.review.service import ReviewService  # noqa: E402

BASE = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)
SERVICES = frozenset(s.id for s in load_dataset(get_settings().fixtures_dir).services)

A = (
    "SSO sign-in returns invalid assertion for the whole team",
    "Nobody on our workspace can sign in through their identity provider since about "
    "09:00 UTC. The console shows an invalid assertion immediately after the redirect "
    "back from the IdP. Direct password sign-in still works for two local accounts.",
)
B = (
    "Login loop after redirect from identity provider",
    "Reporter is bounced between the console and their IdP repeatedly and never reaches "
    "the workspace. Clearing cookies does not help. Reproduced on two browsers.",
)
C_PARAPHRASE = (
    "Users complete SSO but their workspace never finishes loading",
    "Everyone gets through the single sign-on step, then nothing happens. The workspace "
    "never finishes opening for them.",
)
C2_PARAPHRASE = (
    "Nobody can get into the product this morning",
    "Staff say they are stuck at the door and cannot reach anything inside.",
)
D_UNRELATED = (
    "Auth service admin console is slow to list users",
    "Loading the user directory in the admin console takes about forty seconds. "
    "Sign-in itself works fine for everyone.",
)
E_GENUINE = (
    "Invalid assertion error signing in through the identity provider",
    "Our whole team cannot sign in through the identity provider. The console returns "
    "an invalid assertion right after the redirect back from the IdP.",
)
HARD_CONFLICT = (
    "Meeting room display will not turn on",
    "The screen in the third floor room stays black.",
)


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
def reviews(clean) -> ReviewService:
    return ReviewService()


def intake_v1(clean) -> TicketIntake:
    return TicketIntake(known_services=SERVICES, reconciliation="v1")


def intake_v2(clean) -> TicketIntake:
    return TicketIntake(known_services=SERVICES, reconciliation="v2")


def submit(intake: TicketIntake, body, minutes: float, service: str = "svc-auth"):
    return intake.submit(
        CreateTicketRequest(
            external_id=f"EXT-{uuid.uuid4().hex[:8]}",
            title=body[0],
            description=body[1],
            created_at=BASE + timedelta(minutes=minutes),
            reported_service_id=service,
        )
    )


def members_of(candidate_id: str) -> list[str]:
    with sessionmaker_for(get_engine())() as session:
        return sorted(
            session.scalars(
                select(TicketRow.id).where(TicketRow.candidate_id == candidate_id)
            ).all()
        )


def confirmed_incident(intake: TicketIntake, reviews: ReviewService) -> str:
    """A, B correlated automatically; C attached by an operator."""
    submit(intake, A, 0)
    seeded = submit(intake, B, 11)
    candidate_id = seeded.correlation.candidate_id
    assert candidate_id is not None

    paraphrase = submit(intake, C_PARAPHRASE, 22)
    assert paraphrase.correlation.outcome is not CorrelationOutcome.ATTACHED

    pending = [r for r in reviews.pending() if r.ticket_id == paraphrase.ticket.id]
    assert len(pending) == 1
    reviews.confirm(pending[0].id, reason="same_symptoms")
    assert len(members_of(candidate_id)) == 3
    return candidate_id


# --- the defect -----------------------------------------------------------------------


def test_v1_reproduces_the_false_merge(clean, reviews) -> None:
    """Historical behavior, preserved deliberately so the fix is demonstrable."""
    intake = intake_v1(clean)
    candidate_id = confirmed_incident(intake, reviews)

    result = submit(intake, D_UNRELATED, 28)

    assert result.correlation.outcome is CorrelationOutcome.ATTACHED
    assert result.correlation.candidate_id == candidate_id
    assert len(members_of(candidate_id)) == 4


def test_v2_refuses_the_unrelated_ticket(clean, reviews) -> None:
    """The primary regression: a confirmation must not vouch for a stranger."""
    intake = intake_v2(clean)
    candidate_id = confirmed_incident(intake, reviews)

    result = submit(intake, D_UNRELATED, 28)

    assert result.correlation.outcome is not CorrelationOutcome.ATTACHED
    assert result.correlation.candidate_id is None
    assert len(members_of(candidate_id)) == 3


def test_v2_still_admits_a_genuine_later_report(clean, reviews) -> None:
    """The patch must not freeze a candidate the moment an operator touches it.

    Complete linkage against the *full* membership would refuse this — E scores 0.5366
    against the paraphrase. Admission is judged against the automatically established
    members, where E scores 0.6256.
    """
    intake = intake_v2(clean)
    candidate_id = confirmed_incident(intake, reviews)

    result = submit(intake, E_GENUINE, 30)

    assert result.correlation.outcome is CorrelationOutcome.ATTACHED
    assert result.correlation.candidate_id == candidate_id
    assert len(members_of(candidate_id)) == 4


# --- what must not change -------------------------------------------------------------


def test_v2_leaves_the_confirmed_member_in_place(clean, reviews) -> None:
    """A confirmed ticket is evidence inside the incident, not second-class data."""
    intake = intake_v2(clean)
    candidate_id = confirmed_incident(intake, reviews)
    confirmed = members_of(candidate_id)

    submit(intake, D_UNRELATED, 28)

    assert members_of(candidate_id) == confirmed


def test_v2_keeps_the_candidate_id_stable(clean, reviews) -> None:
    """Fixing a false merge must not fragment candidates.

    The confirmation and the later automatic member both land on the candidate the
    operator was already looking at; no replacement candidate is created.
    """
    intake = intake_v2(clean)
    candidate_id = confirmed_incident(intake, reviews)

    grown = submit(intake, E_GENUINE, 30)

    assert grown.correlation.candidate_id == candidate_id
    with sessionmaker_for(get_engine())() as session:
        assert session.scalars(select(CandidateIncidentRow.id)).all() == [candidate_id]


def test_refusing_a_ticket_creates_no_candidate_for_it(clean, reviews) -> None:
    """A refused ticket is left standalone, not given an incident of its own."""
    intake = intake_v2(clean)
    candidate_id = confirmed_incident(intake, reviews)

    submit(intake, D_UNRELATED, 28)

    with sessionmaker_for(get_engine())() as session:
        assert session.scalars(select(CandidateIncidentRow.id)).all() == [candidate_id]


def test_a_refused_ticket_can_make_a_later_report_ambiguous(clean, reviews) -> None:
    """A consequence of v2 worth stating plainly rather than discovering later.

    Under v1 the unrelated ticket was absorbed, so it never competed for anything. Under
    v2 it stays standalone, and the stateless engine still finds it clusters with the
    confirmed paraphrase. A later genuine report can then sit within `CANDIDATE_MARGIN`
    of two groupings and be called ambiguous instead of attaching.

    That is the existing ambiguity guard behaving as designed: it declines to invent
    certainty and routes the ticket to an operator. It is a weaker outcome than attaching,
    but it is a safe one, and it is not a silent merge.
    """
    intake = intake_v2(clean)
    confirmed_incident(intake, reviews)
    submit(intake, D_UNRELATED, 28)

    result = submit(intake, E_GENUINE, 30)

    assert result.correlation.outcome is CorrelationOutcome.AMBIGUOUS
    assert result.correlation.candidate_id is None
    # The unrelated ticket is what it is competing with — and neither of them was
    # silently merged into the incident.
    assert len(result.correlation.alternatives) >= 1


def test_v2_still_attaches_a_near_duplicate(clean) -> None:
    intake = intake_v2(clean)
    submit(intake, A, 0)
    seeded = submit(intake, B, 11)

    result = submit(intake, E_GENUINE, 14)

    assert result.correlation.outcome is CorrelationOutcome.ATTACHED
    assert result.correlation.candidate_id == seeded.correlation.candidate_id


def test_v2_still_rejects_a_hard_conflict(clean) -> None:
    intake = intake_v2(clean)
    submit(intake, A, 0)
    submit(intake, B, 11)

    result = submit(intake, HARD_CONFLICT, 18, service="svc-analytics")

    assert result.correlation.outcome is not CorrelationOutcome.ATTACHED


def test_a_rejected_review_does_not_change_later_correlation(clean, reviews) -> None:
    """Rejection records a label and nothing else."""
    intake = intake_v2(clean)
    submit(intake, A, 0)
    seeded = submit(intake, B, 11)
    candidate_id = seeded.correlation.candidate_id

    paraphrase = submit(intake, C_PARAPHRASE, 22)
    pending = [r for r in reviews.pending() if r.ticket_id == paraphrase.ticket.id]
    reviews.reject(pending[0].id, reason="different_mechanism")

    assert members_of(candidate_id) == sorted(members_of(candidate_id))
    assert len(members_of(candidate_id)) == 2

    # The automatic core is untouched, so a genuine report still attaches exactly as it
    # would have without the review ever existing.
    result = submit(intake, E_GENUINE, 30)
    assert result.correlation.outcome is CorrelationOutcome.ATTACHED
    assert result.correlation.candidate_id == candidate_id


def test_more_confirmations_do_not_progressively_weaken_admission(clean, reviews) -> None:
    """Two manual members must be no more persuasive than one — that is, not at all."""
    intake = intake_v2(clean)
    candidate_id = confirmed_incident(intake, reviews)

    second = submit(intake, C2_PARAPHRASE, 25)
    pending = [r for r in reviews.pending() if r.ticket_id == second.ticket.id]
    if pending:
        reviews.confirm(pending[0].id, reason="same_symptoms")
        assert len(members_of(candidate_id)) == 4

    result = submit(intake, D_UNRELATED, 28)

    assert result.correlation.outcome is not CorrelationOutcome.ATTACHED
    assert result.ticket.id not in members_of(candidate_id)


# --- versioning -----------------------------------------------------------------------


def test_each_strategy_stamps_its_own_version(clean) -> None:
    v1 = intake_v1(clean)
    submit(v1, A, 0)
    first = submit(v1, B, 11)
    assert first.correlation.correlation_version == CORRELATION_VERSION

    v2 = TicketIntake(known_services=SERVICES, reconciliation="v2")
    second = submit(v2, E_GENUINE, 14)
    assert second.correlation.correlation_version == CORRELATION_VERSION_V2

    # The earlier row keeps the version it was decided under.
    with sessionmaker_for(get_engine())() as session:
        stored = session.scalars(
            select(CorrelationDecisionRow.correlation_version).where(
                CorrelationDecisionRow.ticket_id == first.ticket.id
            )
        ).all()
    assert stored == [CORRELATION_VERSION]


def test_v2_calls_no_model(clean, reviews, monkeypatch) -> None:
    """Reconciliation is arithmetic. No embeddings, no classifier, no OpenAI."""
    import app.embeddings as embeddings

    def explode(*args, **kwargs):  # pragma: no cover - the point is that it never runs
        raise AssertionError("v2 reconciliation must not embed anything")

    monkeypatch.setattr(embeddings.LocalEmbeddingProvider, "embed_many", explode)

    intake = intake_v2(clean)
    confirmed_incident(intake, reviews)
    submit(intake, D_UNRELATED, 28)
    submit(intake, E_GENUINE, 30)
