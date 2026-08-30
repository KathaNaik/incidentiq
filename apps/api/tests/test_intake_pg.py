"""Runtime ticket intake, against a real PostgreSQL.

Intake is persistence, so most of what is worth asserting only exists in the database:
the unique constraint behind idempotency, membership that survives a restart, a decision
recorded at the moment it was made. A fake would be asserting itself.

"Restart" is simulated the only honest way — a new repository over a new session.
"""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, text

pytestmark = pytest.mark.pg

from app.config import get_settings  # noqa: E402

DATABASE_URL = os.environ.get("DATABASE_URL") or get_settings().database_url
if not DATABASE_URL:  # pragma: no cover - environment dependent
    pytest.skip("no DATABASE_URL", allow_module_level=True)

from app.correlation.rules import CORRELATION_VERSION  # noqa: E402
from app.db.engine import get_engine  # noqa: E402
from app.db.models import CandidateIncidentRow, CorrelationDecisionRow, TicketRow  # noqa: E402
from app.db.ticket_store import SqlRepository  # noqa: E402
from app.fixtures import load_dataset  # noqa: E402
from app.intake import (  # noqa: E402
    CorrelationOutcome,
    CreateTicketRequest,
    DuplicateTicketError,
    IntakeError,
    TicketIntake,
    TicketSource,
)
from app.triage.rules import TRIAGE_VERSION  # noqa: E402

# In the past on purpose: a reported time in the future is refused, and a test that
# drifts into the future as the calendar moves is a test that fails for no reason.
BASE = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)
SERVICES = frozenset(s.id for s in load_dataset(get_settings().fixtures_dir).services)


@pytest.fixture
def clean():
    """An empty intake world. Investigations and actions are left alone."""
    engine = get_engine()
    with engine.begin() as connection:
        connection.execute(delete(CorrelationDecisionRow))
        connection.execute(text("UPDATE tickets SET candidate_id = NULL"))
        connection.execute(delete(CandidateIncidentRow))
        connection.execute(delete(TicketRow))
    return engine


@pytest.fixture
def intake(clean) -> TicketIntake:
    return TicketIntake(known_services=SERVICES)


def at(minutes: float) -> datetime:
    return BASE + timedelta(minutes=minutes)


def request(
    external_id: str,
    title: str,
    description: str = "",
    minutes: float = 0,
    service: str | None = None,
) -> CreateTicketRequest:
    return CreateTicketRequest(
        external_id=external_id,
        title=title,
        description=description,
        created_at=at(minutes),
        reported_service_id=service,
    )


AUTH = (
    "SSO sign-in returns invalid assertion for the whole team",
    "Nobody on our workspace can sign in through their identity provider. "
    "Every attempt returns an invalid assertion error.",
)
AUTH_DUP = (
    "SSO sign-in returns invalid assertion for our whole team",
    "Nobody on our workspace can sign in through their identity provider. "
    "Every attempt returns an invalid assertion error at all.",
)


# --- intake ---------------------------------------------------------------------------


def test_a_submitted_ticket_is_persisted_with_its_provenance(intake) -> None:
    result = intake.submit(request("EXT-1", *AUTH))

    assert result.ticket.source is TicketSource.API
    assert result.ticket.external_id == "EXT-1"
    assert result.ticket.created_at == at(0)
    # Received later than observed: we were told after it happened.
    assert result.ticket.received_at >= result.ticket.created_at

    reread = SqlRepository(load_dataset(get_settings().fixtures_dir)).ticket_row(
        result.ticket.id
    )
    assert reread is not None
    assert reread.title == AUTH[0]
    assert reread.source == "api"


def test_received_at_never_overwrites_the_reported_time(intake) -> None:
    """A report filed late describes an old event.

    If arrival time replaced observation time, every backfilled ticket would look like
    fresh activity and would drag incident onset forward with it.
    """
    observed = datetime(2026, 8, 18, 8, 0, tzinfo=UTC)
    result = intake.submit(
        CreateTicketRequest(
            external_id="EXT-LATE", title="Filed days later", created_at=observed
        )
    )

    assert result.ticket.created_at == observed
    assert result.ticket.received_at > observed


def test_naive_timestamps_are_normalised_to_utc(intake) -> None:
    result = intake.submit(
        CreateTicketRequest(
            external_id="EXT-NAIVE",
            title="No timezone supplied",
            created_at=datetime(2026, 8, 20, 9, 0),
        )
    )
    assert result.ticket.created_at == BASE


def test_an_empty_submission_is_refused(intake) -> None:
    with pytest.raises(IntakeError, match="title"):
        intake.submit(CreateTicketRequest(external_id="EXT-EMPTY", title="   "))


def test_an_unknown_service_is_refused(intake) -> None:
    with pytest.raises(IntakeError, match="unknown service"):
        intake.submit(request("EXT-SVC", "Something broke", service="svc-imaginary"))


def test_a_caller_cannot_supply_server_owned_fields() -> None:
    """Triage, scores and candidate ids are decided here, never asserted by a caller."""
    for field in ("candidate_id", "service_id", "priority", "score", "source"):
        with pytest.raises(Exception):
            CreateTicketRequest(external_id="X", title="T", **{field: "anything"})


# --- idempotency -------------------------------------------------------------------------


def test_an_identical_resubmission_returns_the_original(intake) -> None:
    first = intake.submit(request("EXT-DUP", *AUTH))
    second = intake.submit(request("EXT-DUP", *AUTH))

    assert second.idempotent_replay is True
    assert second.ticket.id == first.ticket.id

    engine = get_engine()
    with engine.connect() as connection:
        count = connection.execute(
            text("SELECT count(*) FROM tickets WHERE external_id = 'EXT-DUP'")
        ).scalar_one()
    assert count == 1, "a retry must not create a second report"


def test_a_conflicting_resubmission_is_refused(intake) -> None:
    intake.submit(request("EXT-CONFLICT", *AUTH))

    with pytest.raises(DuplicateTicketError, match="different content"):
        intake.submit(request("EXT-CONFLICT", "A different report entirely", "Other."))


def test_idempotency_holds_across_a_new_intake_instance(intake) -> None:
    """What a restarted API has: the constraint is in the database, not in memory."""
    first = intake.submit(request("EXT-RESTART", *AUTH))
    replay = TicketIntake(known_services=SERVICES).submit(request("EXT-RESTART", *AUTH))

    assert replay.ticket.id == first.ticket.id
    assert replay.idempotent_replay is True


# --- triage ------------------------------------------------------------------------------


def test_triage_runs_on_intake_and_is_persisted(intake) -> None:
    result = intake.submit(request("EXT-TRIAGE", *AUTH))

    assert result.triage.version == TRIAGE_VERSION
    assert result.triage.service_id == "svc-auth"
    assert result.triage.signals, "the signals behind the prediction are kept"

    row = SqlRepository(load_dataset(get_settings().fixtures_dir)).ticket_row(
        result.ticket.id
    )
    assert row.triage_version == TRIAGE_VERSION
    assert row.service_id == "svc-auth"


def test_a_reported_service_is_kept_separate_from_the_predicted_one(intake) -> None:
    result = intake.submit(
        request("EXT-CLAIM", "Something is wrong", service="svc-analytics")
    )
    row = SqlRepository(load_dataset(get_settings().fixtures_dir)).ticket_row(
        result.ticket.id
    )

    assert row.reported_service_id == "svc-analytics"
    assert row.service_id == "svc-analytics", "the reporter's claim is honoured"


# --- incremental correlation ---------------------------------------------------------------


def test_a_lone_report_stays_uncorrelated(intake) -> None:
    """Being alone is a real answer, not a failure to decide."""
    result = intake.submit(request("EXT-ALONE", *AUTH))

    assert result.correlation.outcome is CorrelationOutcome.UNCORRELATED
    assert result.correlation.candidate_id is None
    assert result.candidate is None


def test_a_second_compatible_report_forms_a_candidate(intake) -> None:
    intake.submit(request("EXT-A", *AUTH, minutes=0))
    second = intake.submit(request("EXT-B", *AUTH_DUP, minutes=6))

    assert second.correlation.outcome is CorrelationOutcome.CREATED_CANDIDATE
    assert second.correlation.created_new_candidate is True
    assert second.candidate["ticket_count"] == 2
    assert second.candidate["service_id"] == "svc-auth"


def test_a_third_report_attaches_to_the_existing_candidate(intake) -> None:
    intake.submit(request("EXT-A", *AUTH, minutes=0))
    formed = intake.submit(request("EXT-B", *AUTH_DUP, minutes=6))
    third = intake.submit(
        request(
            "EXT-C",
            "SSO sign-in returns an invalid assertion for the whole team",
            "Nobody on our workspace can sign in through their identity provider. "
            "Every attempt returns an invalid assertion error now.",
            minutes=12,
        )
    )

    assert third.correlation.outcome is CorrelationOutcome.ATTACHED
    assert third.correlation.created_new_candidate is False
    assert third.correlation.candidate_id == formed.correlation.candidate_id
    assert third.candidate["ticket_count"] == 3


def test_an_unrelated_report_does_not_join(intake) -> None:
    intake.submit(request("EXT-A", *AUTH, minutes=0))
    intake.submit(request("EXT-B", *AUTH_DUP, minutes=6))
    unrelated = intake.submit(
        request(
            "EXT-PRINTER",
            "Office printer on floor three is offline",
            "The shared printer will not accept jobs and shows offline on its panel.",
            minutes=10,
        )
    )

    assert unrelated.correlation.outcome is CorrelationOutcome.UNCORRELATED
    assert unrelated.correlation.candidate_id is None


def test_the_same_wording_outside_the_active_window_does_not_attach(intake) -> None:
    """A day later is a different incident, however similar the words."""
    intake.submit(request("EXT-A", *AUTH, minutes=0))
    intake.submit(request("EXT-B", *AUTH_DUP, minutes=6))
    late = intake.submit(request("EXT-LATE", *AUTH, minutes=60 * 24))

    assert late.correlation.outcome is CorrelationOutcome.UNCORRELATED


def test_the_decision_records_why(intake) -> None:
    intake.submit(request("EXT-A", *AUTH, minutes=0))
    second = intake.submit(request("EXT-B", *AUTH_DUP, minutes=6))

    assert second.correlation.correlation_version == CORRELATION_VERSION
    assert second.correlation.score is not None
    assert second.correlation.confidence in ("low", "medium", "high")
    assert second.correlation.reason


# --- candidate metadata --------------------------------------------------------------------


def test_candidate_metadata_is_derived_from_members_not_incremented(intake) -> None:
    intake.submit(request("EXT-A", *AUTH, minutes=0))
    intake.submit(request("EXT-B", *AUTH_DUP, minutes=6))
    third = intake.submit(
        request(
            "EXT-C",
            "SSO sign-in returns an invalid assertion for the whole team",
            "Nobody on our workspace can sign in through their identity provider. "
            "Every attempt returns an invalid assertion error now.",
            minutes=12,
        )
    )
    candidate_id = third.correlation.candidate_id

    repository = SqlRepository(load_dataset(get_settings().fixtures_dir))
    row = repository.candidate(candidate_id)
    members = repository.candidate_tickets(candidate_id)

    assert row.ticket_count == len(members)
    assert row.first_seen == min(m.created_at for m in members)
    assert row.last_seen == max(m.created_at for m in members)
    assert row.service_id == "svc-auth"
    assert row.title == "Auth integration incident" or row.title.startswith("Auth")


def test_the_candidate_title_is_deterministic_and_not_model_written(intake) -> None:
    intake.submit(request("EXT-A", *AUTH, minutes=0))
    second = intake.submit(request("EXT-B", *AUTH_DUP, minutes=6))

    title = second.candidate["title"]
    assert "Auth" in title
    assert title == SqlRepository(
        load_dataset(get_settings().fixtures_dir)
    ).candidate(second.correlation.candidate_id).title


# --- durability ------------------------------------------------------------------------------


def test_membership_and_decisions_survive_a_restart(intake) -> None:
    intake.submit(request("EXT-A", *AUTH, minutes=0))
    second = intake.submit(request("EXT-B", *AUTH_DUP, minutes=6))
    candidate_id = second.correlation.candidate_id

    # New repository, new session: what a restarted API sees.
    repository = SqlRepository(load_dataset(get_settings().fixtures_dir))
    members = repository.candidate_tickets(candidate_id)
    decision = repository.decision_for(second.ticket.id)

    assert len(members) == 2
    assert decision is not None
    assert decision.correlation_version == CORRELATION_VERSION
    assert decision.triage_version == TRIAGE_VERSION
    assert decision.outcome == "created_candidate"


def test_uncorrelated_tickets_are_listed_as_such(intake) -> None:
    intake.submit(request("EXT-ALONE", *AUTH))
    repository = SqlRepository(load_dataset(get_settings().fixtures_dir))

    assert [row.external_id for row in repository.ticket_rows(uncorrelated=True)] == [
        "EXT-ALONE"
    ]
    assert repository.ticket_rows(uncorrelated=False) == []


def test_no_model_is_called_during_intake(intake, monkeypatch) -> None:
    """Intake must stay free of token cost and provider latency."""
    import app.investigation.provider as provider

    def explode(*args, **kwargs):
        raise AssertionError("intake must not call a language model")

    monkeypatch.setattr(provider.OpenAIInvestigationModel, "investigate", explode)
    result = intake.submit(request("EXT-NOLLM", *AUTH))
    assert result.ticket.id
