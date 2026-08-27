from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.correlation import (
    Confidence,
    CorrelationTicket,
    Corpus,
    correlate,
    prepare,
    score_pair,
    time_score,
)
from app.correlation.entities import extract_entities
from app.correlation.models import Component, Direction
from app.correlation.rules import CONTENT_LINK_MIN, LINK_THRESHOLD, TIME_HALF_LIFE_MINUTES

START = datetime(2026, 8, 24, 9, 0, tzinfo=UTC)


def ticket(
    id: str, title: str, description: str = "", minutes: float = 0.0, **kwargs
) -> CorrelationTicket:
    return CorrelationTicket(
        id=id,
        title=title,
        description=description,
        created_at=START + timedelta(minutes=minutes),
        **kwargs,
    )


def pair_of(a: CorrelationTicket, b: CorrelationTicket):
    corpus = Corpus()
    features = [prepare(a), prepare(b)]
    for feature in features:
        corpus.observe(feature.tokens)
    return score_pair(features[0], features[1], corpus)


def component(score, name: Component):
    return next(s for s in score.signals if s.component is name)


# --- scoring components -------------------------------------------------------------


def test_time_score_decays_rather_than_switching_off() -> None:
    assert time_score(0) == 1.0
    assert time_score(TIME_HALF_LIFE_MINUTES) == pytest.approx(0.5)
    assert time_score(2 * TIME_HALF_LIFE_MINUTES) == pytest.approx(0.25)
    # Still positive far out, just negligible — no cliff edge at an arbitrary cutoff.
    assert 0 < time_score(180) < 0.01


def test_same_service_supports_and_different_services_conflict() -> None:
    same = pair_of(
        ticket("A", "Dashboard will not load", service_id="svc-analytics"),
        ticket("B", "Analytics is down", service_id="svc-analytics"),
    )
    different = pair_of(
        ticket("A", "Dashboard will not load", service_id="svc-analytics"),
        ticket("B", "Cannot log in", service_id="svc-auth"),
    )

    assert component(same, Component.SERVICE).direction is Direction.SUPPORTING
    assert component(different, Component.SERVICE).direction is Direction.CONFLICTING
    assert component(different, Component.SERVICE).score < 0


def test_unknown_service_is_neutral_not_negative() -> None:
    """Absence of evidence must not read as evidence against."""
    score = pair_of(
        ticket("A", "Something is wrong"), ticket("B", "Dashboard down", minutes=2)
    )

    assert component(score, Component.SERVICE).score == 0.0
    assert component(score, Component.SERVICE).direction is Direction.NEUTRAL


def test_permissions_and_outage_are_treated_as_different_problems() -> None:
    score = pair_of(
        ticket(
            "A",
            "Dashboard is completely down",
            "Nothing loads at all.",
            service_id="svc-analytics",
        ),
        ticket(
            "B",
            "Permission denied opening the dashboard",
            "Access denied for one analyst.",
            minutes=3,
            service_id="svc-analytics",
        ),
    )

    assert component(score, Component.ISSUE_TYPE).score < 0
    assert score.content_score < CONTENT_LINK_MIN


def test_shared_error_identifier_is_strong_evidence() -> None:
    with_code = pair_of(
        ticket("A", "Sync failing with ERR_SYNC_412", service_id="svc-connector"),
        ticket("B", "ERR_SYNC_412 on resync", minutes=4, service_id="svc-connector"),
    )
    without = pair_of(
        ticket("A", "Sync failing", service_id="svc-connector"),
        ticket("B", "Resync trouble", minutes=4, service_id="svc-connector"),
    )

    assert component(with_code, Component.ENTITY).score == 1.0
    assert "err_sync_412" in component(with_code, Component.ENTITY).values[0]
    assert component(without, Component.ENTITY).score == 0.0


def test_entity_extraction_finds_identifiers_in_raw_text() -> None:
    kinds = {entity.kind: entity.value for entity in extract_entities(
        "GA4 export hit a 502 from /api/v2/reports in us-east-1 with ERR_AUTH_17"
    )}

    assert kinds["error_code"] == "err_auth_17"
    assert kinds["http_status"] == "502"
    assert kinds["region"] == "us-east-1"
    assert kinds["endpoint"] == "/api/v2/reports"
    assert kinds["identifier"] == "ga4"


def test_a_shared_common_word_is_not_enough_to_group() -> None:
    """The heart of scenario B: three dashboard tickets, three different causes."""
    tickets = [
        ticket(
            "A",
            "Dashboard sharing permissions are not working",
            "A colleague gets a 403 opening a dashboard I shared.",
            service_id="svc-analytics",
        ),
        ticket(
            "B",
            "Dashboard is slow to render",
            "It takes about thirty seconds but it does appear.",
            minutes=7,
            service_id="svc-analytics",
        ),
        ticket(
            "C",
            "Dashboard export produced duplicate rows",
            "Every account is listed twice so the totals are double counted.",
            minutes=15,
            service_id="svc-analytics",
        ),
    ]

    result = correlate(tickets)

    assert result.candidates == ()
    assert set(result.standalone_ticket_ids) == {"A", "B", "C"}


def test_lexical_overlap_is_weighted_against_repeated_vocabulary() -> None:
    """In a corpus full of dashboards, "dashboard" stops being informative."""
    corpus = Corpus()
    common = [prepare(ticket(f"T{i}", "Dashboard issue", minutes=i)) for i in range(20)]
    for feature in common:
        corpus.observe(feature.tokens)

    rare_a = prepare(ticket("X", "Dashboard failing", "The ga4 connector broke."))
    rare_b = prepare(ticket("Y", "Dashboard failing", "Something with ga4 again."))
    corpus.observe(rare_a.tokens)

    assert corpus.idf("dashboard") < corpus.idf("ga4")
    assert score_pair(rare_a, rare_b, corpus).signals


# --- clustering ---------------------------------------------------------------------


def test_a_clear_shared_incident_becomes_one_candidate() -> None:
    tickets = [
        ticket(
            "A",
            "Warehouse sync stopped working",
            "The connector sync stopped working after 09:00 and no rows arrive.",
            service_id="svc-connector",
        ),
        ticket(
            "B",
            "Connector sync stopped working",
            "Sync stopped working this morning, no rows have arrived since.",
            minutes=6,
            service_id="svc-connector",
        ),
        ticket(
            "C",
            "Sync stopped working for our warehouse",
            "No rows arrive; the connector sync stopped working around 09:00.",
            minutes=11,
            service_id="svc-connector",
        ),
    ]

    result = correlate(tickets)

    assert len(result.candidates) == 1
    assert result.candidates[0].ticket_ids == ("A", "B", "C")
    assert result.candidates[0].ticket_count == 3


def test_chaining_cannot_drag_an_unrelated_ticket_into_a_group() -> None:
    """A–B similar, B–C similar, A–C not. Complete linkage keeps C out."""
    a = ticket(
        "A",
        "Warehouse sync stopped working",
        "The connector sync stopped working and no rows arrive.",
        service_id="svc-connector",
    )
    b = ticket(
        "B",
        "Connector sync stopped working",
        "Sync stopped working, no rows arriving.",
        minutes=5,
        service_id="svc-connector",
    )
    c = ticket(
        "C",
        "Permission denied writing to the warehouse",
        "The service account is not authorized on the analytics schema.",
        minutes=10,
        service_id="svc-connector",
    )

    result = correlate([a, b, c])

    grouped = {t for candidate in result.candidates for t in candidate.ticket_ids}
    assert grouped == {"A", "B"}
    assert "C" in result.standalone_ticket_ids


def test_a_quiet_gap_ends_a_candidate() -> None:
    """Two identical incidents hours apart are two candidates, not one."""
    morning = [
        ticket(
            f"AM{i}",
            "Dashboards stopped loading",
            "Nothing renders in any dashboard.",
            minutes=i * 5,
            service_id="svc-analytics",
        )
        for i in range(2)
    ]
    evening = [
        ticket(
            f"PM{i}",
            "Dashboards stopped loading",
            "Nothing renders in any dashboard.",
            minutes=400 + i * 5,
            service_id="svc-analytics",
        )
        for i in range(2)
    ]

    result = correlate(morning + evening)

    assert len(result.candidates) == 2
    assert {c.ticket_ids for c in result.candidates} == {("AM0", "AM1"), ("PM0", "PM1")}


def test_weak_evidence_leaves_tickets_alone() -> None:
    tickets = [
        ticket("A", "Something is off with the connector", "Not sure what."),
        ticket("B", "Connector issue", "Having trouble.", minutes=18),
    ]

    result = correlate(tickets)

    assert result.candidates == ()
    assert result.standalone_ticket_ids == ("A", "B")


def test_output_is_deterministic_regardless_of_input_order() -> None:
    tickets = [
        ticket(
            "A",
            "Warehouse sync stopped working",
            "Connector sync stopped working, no rows.",
            service_id="svc-connector",
        ),
        ticket(
            "B",
            "Connector sync stopped working",
            "Sync stopped working, no rows arriving.",
            minutes=5,
            service_id="svc-connector",
        ),
        ticket("C", "How do I add a user?", minutes=9),
    ]

    forward = correlate(tickets)
    backward = correlate(list(reversed(tickets)))

    assert forward.model_dump_json() == backward.model_dump_json()


def test_candidates_report_the_evidence_and_observable_scope_only() -> None:
    tickets = [
        ticket(
            "A",
            "Warehouse sync stopped working",
            "Connector sync stopped working, no rows arrive.",
            service_id="svc-connector",
            reported_by="tier1-support",
        ),
        ticket(
            "B",
            "Connector sync stopped working",
            "Sync stopped working, no rows arriving.",
            minutes=5,
            service_id="svc-connector",
            reported_by="customer-success",
        ),
    ]

    candidate = correlate(tickets).candidates[0]

    assert candidate.supporting_signals
    assert candidate.confidence in set(Confidence)
    assert candidate.score >= LINK_THRESHOLD - 0.05
    assert candidate.first_seen < candidate.last_seen
    # Two named reporters, counted — not an invented number of affected users.
    assert candidate.distinct_reporters == 2


def test_reporters_are_unknown_rather_than_guessed() -> None:
    tickets = [
        ticket(
            "A",
            "Warehouse sync stopped working",
            "Connector sync stopped working, no rows.",
            service_id="svc-connector",
        ),
        ticket(
            "B",
            "Connector sync stopped working",
            "Sync stopped working, no rows arriving.",
            minutes=5,
            service_id="svc-connector",
        ),
    ]

    assert correlate(tickets).candidates[0].distinct_reporters is None


def test_correlation_input_rejects_ground_truth_fields() -> None:
    """A Polaris row carrying event_id cannot be passed into correlation at all."""
    with pytest.raises(ValidationError):
        CorrelationTicket(
            id="T-1", title="x", created_at=START, event_id="EVT-1", event_type="outage"
        )
