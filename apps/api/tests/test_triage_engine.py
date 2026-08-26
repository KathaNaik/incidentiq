import pytest
from pydantic import ValidationError

from app.domain.models import Ticket, TicketPriority
from app.repository import InMemoryRepository
from app.triage import IssueType, PredictionStatus, TriageInput, triage, triage_ticket
from app.triage.normalize import normalize
from app.triage.rules import SERVICE_RULES


def run(title: str, description: str = ""):
    return triage(TriageInput(title=title, description=description))


def test_normalization_folds_punctuation_and_contractions() -> None:
    assert normalize("I can't log in!  (SSO)") == "i cannot log in sso"
    assert normalize("  Dashboard — slow…  ") == "dashboard slow"
    assert normalize("") == ""


def test_plural_forms_match_the_singular_vocabulary() -> None:
    """Without this, "dashboards" and "exports" match nothing at all."""
    assert run("All dashboards are blank").service.value == "svc-analytics"
    assert run("Scheduled exports failing").service.value == "svc-analytics"


def test_a_decisive_phrase_outranks_a_shared_word() -> None:
    result = run("Cannot log in to the API console")

    assert result.service.value == "svc-auth"
    assert result.service.margin > 0


def test_a_contained_phrase_does_not_double_count() -> None:
    """"log in" sits inside "cannot log in"; scoring both would inflate the match."""
    result = run("Cannot log in")

    login_signals = [s for s in result.signals if s.target == "service:svc-auth"]
    assert [s.matched_text for s in login_signals] == ["cannot log in"]


def test_evenly_matched_services_are_reported_as_ambiguous() -> None:
    result = run("Dashboard and connector both affected")

    assert result.service.status is PredictionStatus.AMBIGUOUS
    assert result.service.value is None
    assert "too close to separate" in result.service.explanation


def test_unrecognised_service_stays_null_rather_than_guessing() -> None:
    result = run("Question about our invoice", "We were charged twice this month.")

    assert result.service.status is PredictionStatus.UNKNOWN
    assert result.service.value is None
    # The issue taxonomy has its own name for "none of these"; a service id does not.
    assert result.issue_type.value == IssueType.UNKNOWN.value


def test_scope_and_outage_together_reach_critical() -> None:
    result = run(
        "Connector API is down for all customers",
        "Every resync is unavailable and this is customer facing in production.",
    )

    assert result.priority.value == TicketPriority.CRITICAL.value
    assert result.priority.score >= 6.0


def test_localized_language_lowers_priority() -> None:
    result = run(
        "Console logs me out", "Only me, on my laptop, once a day. No rush."
    )

    assert result.priority.value == TicketPriority.LOW.value


def test_one_dimension_counts_once_however_many_ways_it_is_said() -> None:
    """Restating scope three times is one fact about scope, not three."""
    once = run("Login broken", "Every user is affected.")
    thrice = run(
        "Login broken",
        "Every user is affected. The entire team is blocked. Nobody can get in.",
    )

    scope_once = [s for s in once.signals if s.signal_type.value == "scope"]
    scope_thrice = [s for s in thrice.signals if s.signal_type.value == "scope"]
    assert len(scope_thrice) > len(scope_once)
    # More phrases are reported as evidence, but scope contributes the same amount.
    assert thrice.priority.score - once.priority.score <= 2.0


def test_priority_defaults_when_nothing_matches_and_says_so() -> None:
    result = run("webhook 504")

    assert result.priority.status is PredictionStatus.DEFAULT
    assert result.priority.value == TicketPriority.MEDIUM.value
    assert "defaulted" in result.priority.explanation


def test_signals_carry_the_evidence_behind_each_prediction() -> None:
    result = run("SSO down for all users", "Nobody can sign in.")

    targets = {signal.target for signal in result.signals}
    assert "service:svc-auth" in targets
    assert "priority" in targets
    for signal in result.signals:
        assert signal.matched_text
        assert signal.normalized_value
        assert signal.source_field in ("title", "description")


def test_explanations_quote_the_rules_that_fired() -> None:
    result = run("Dashboard is completely down", "All users affected.")

    assert "Analytics Dashboard" in result.service.explanation
    assert "all users" in result.priority.explanation


def test_triage_is_deterministic() -> None:
    first = run("Sync stuck", "The warehouse connector has not moved in six hours.")
    second = run("Sync stuck", "The warehouse connector has not moved in six hours.")

    assert first.model_dump_json() == second.model_dump_json()


def test_stored_triage_fields_are_not_read_back_in() -> None:
    """A ticket already labelled `low`/`svc-analytics` must not drag the prediction:
    triage exists to produce those fields, and reading them would make every evaluation
    on triaged tickets meaningless."""
    ticket = Ticket(
        id="TKT-TEST",
        title="Cannot log in through SSO",
        description="Nobody on the team can sign in.",
        created_at="2026-08-25T10:00:00Z",
        status="open",
        reported_by="tier1-support",
        priority=TicketPriority.LOW,
        service_id="svc-analytics",
    )

    result = triage_ticket(ticket)

    assert result.service.value == "svc-auth"
    assert result.priority.value != TicketPriority.LOW.value


def test_rule_service_ids_exist_in_the_fixture_catalogue(
    repository: InMemoryRepository,
) -> None:
    """Rules name Northstar services; a renamed service must break a test, not the UI."""
    known = {service.id for service in repository.list_services()}

    assert {rule.service_id for rule in SERVICE_RULES} <= known


def test_triage_input_rejects_label_fields() -> None:
    """Nothing may hand triage the answer it is supposed to produce."""
    with pytest.raises(ValidationError):
        TriageInput(title="x", description="y", expected_priority="high")
