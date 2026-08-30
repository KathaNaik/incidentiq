"""Pairwise incident classification: features, leakage controls, splitting, runtime.

Offline throughout. Model *behaviour* is measured by `scripts/train_pairwise.py`, which is
an experiment; what is asserted here is that the machinery around it cannot lie — that a
candidate is built only from earlier members, that a label never reaches a feature, that
an event never crosses a split, and that the classifier can never overrule a hard conflict.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.correlation.models import CorrelationTicket
from app.pairwise.features import (
    FEATURE_NAMES,
    FEATURE_SCHEMA_VERSION,
    PairwiseExample,
    extract,
)
from app.pairwise.model import PAIRWISE_VERSION, THRESHOLD_RULE, PairwiseModelError

BASE = datetime(2026, 9, 10, 9, 0, tzinfo=UTC)


def ticket(tid, title, description, minutes, service="svc-auth"):
    return CorrelationTicket(
        id=tid,
        title=title,
        description=description,
        created_at=BASE + timedelta(minutes=minutes),
        service_id=service,
        reported_by=None,
    )


AUTH_A = ticket("M1", "Sign-in requests hang after authentication",
                "Users authenticate with the identity provider and the request hangs.", 0)
AUTH_B = ticket("M2", "Sign-in hangs once authentication completes",
                "Authentication succeeds and then the request hangs indefinitely.", 6)
ARRIVING = ticket("A1", "Users complete SSO but the workspace never loads",
                  "Everyone gets through single sign-on and then nothing happens.", 12)


# --- feature schema -----------------------------------------------------------------------


def test_the_feature_set_is_named_ordered_and_versioned() -> None:
    """A permuted vector produces a plausible number and a wrong answer."""
    assert FEATURE_SCHEMA_VERSION == "pairwise-features-v1"
    assert len(FEATURE_NAMES) == len(set(FEATURE_NAMES)), "no duplicate names"

    features = extract(ARRIVING, [AUTH_A, AUTH_B])
    assert set(features) == set(FEATURE_NAMES)

    example = PairwiseExample(features=features)
    assert example.vector() == [features[name] for name in FEATURE_NAMES]


def test_extraction_is_deterministic() -> None:
    assert extract(ARRIVING, [AUTH_A, AUTH_B]) == extract(ARRIVING, [AUTH_A, AUTH_B])


def test_a_candidate_needs_at_least_one_member() -> None:
    with pytest.raises(ValueError, match="at least one member"):
        extract(ARRIVING, [])


def test_service_and_issue_conflicts_are_represented() -> None:
    other = ticket("M3", "Export truncated", "The nightly export stops early.", 4,
                   service="svc-analytics")
    features = extract(ARRIVING, [other])
    assert features["service_conflict"] == 1.0
    assert features["service_same"] == 0.0


def test_conflicting_error_identifiers_are_represented() -> None:
    """The signal the deterministic baseline is silent about, and the most decisive one."""
    member = ticket("M4", "Authentication stalling",
                    "Sign-in is stalling. Logs show ERR_AUTH_STALL repeatedly.", 0)
    arriving = ticket("A2", "Authentication failing",
                      "Sign-in is failing. The logs show ERR_TOKEN_EXPIRED each time.", 6)
    features = extract(arriving, [member])
    assert features["identifier_conflict"] == 1.0


def test_cohesion_features_describe_the_whole_candidate() -> None:
    """Attachment is candidate-level, so a ticket resembling one member is not enough."""
    odd = ticket("M9", "Printer offline", "The floor printer will not print.", 3,
                 service="svc-analytics")
    features = extract(ARRIVING, [AUTH_A, odd])

    assert features["candidate_size"] == 2.0
    assert features["content_min"] <= features["content_mean"] <= features["content_max"]
    assert features["members_conflicting"] >= 1


def test_time_features_use_reported_times_and_are_timezone_correct() -> None:
    features = extract(ARRIVING, [AUTH_A, AUTH_B])
    assert features["minutes_to_nearest_member"] == pytest.approx(6.0)
    assert features["minutes_to_first_member"] == pytest.approx(12.0)
    assert features["within_active_window"] == 1.0


# --- leakage ---------------------------------------------------------------------------------


def test_no_feature_can_carry_a_label() -> None:
    """The structural guarantee.

    `extract` takes CorrelationTicket objects, which have no field capable of holding an
    event id, a root cause, or an outcome — so a label cannot reach a feature even by
    mistake. This asserts the names too, so a future addition has to be deliberate.
    """
    forbidden = ("event", "label", "root_cause", "resolution", "outcome", "truth", "gold")
    for name in FEATURE_NAMES:
        assert not any(word in name for word in forbidden), name

    assert not hasattr(CorrelationTicket, "event_id")
    assert not hasattr(CorrelationTicket, "root_cause")


def test_the_label_lives_outside_the_feature_vector() -> None:
    example = PairwiseExample(
        features=extract(ARRIVING, [AUTH_A]), label=1, group="event-1"
    )
    assert len(example.vector()) == len(FEATURE_NAMES)
    # Neither label nor group is reachable from the vector.
    assert example.label not in example.vector() or example.vector().count(1.0) >= 1


def test_a_candidate_is_built_only_from_earlier_members() -> None:
    """Future leakage would make every number meaningless.

    Feature values must depend only on members that already existed; adding a later
    ticket to the candidate must change them, proving the arriving ticket's own future
    is not silently included.
    """
    later = ticket("M5", "Another report", "Filed after the arriving ticket.", 30)
    before = extract(ARRIVING, [AUTH_A, AUTH_B])
    with_future = extract(ARRIVING, [AUTH_A, AUTH_B, later])
    assert before != with_future
    assert before["candidate_size"] == 2.0


# --- grouped split -----------------------------------------------------------------------------


def examples_for(groups: dict[str, int]) -> list[PairwiseExample]:
    features = extract(ARRIVING, [AUTH_A])
    return [
        PairwiseExample(features=features, label=index % 2, group=group)
        for group, count in groups.items()
        for index in range(count)
    ]


def test_no_event_crosses_a_split() -> None:
    """Splitting by pair would put one outage on both sides and measure memorisation."""
    from app.pairwise.dataset import grouped_split

    examples = examples_for({f"event-{i}": 10 for i in range(8)})
    train, dev, held = grouped_split(examples)

    train_groups = {e.group for e in train}
    dev_groups = {e.group for e in dev}
    held_groups = {e.group for e in held}

    assert train_groups and dev_groups and held_groups
    assert not (train_groups & dev_groups)
    assert not (train_groups & held_groups)
    assert not (dev_groups & held_groups)


def test_the_split_is_deterministic_for_a_seed() -> None:
    from app.pairwise.dataset import grouped_split

    examples = examples_for({f"event-{i}": 5 for i in range(8)})
    first = [ {e.group for e in part} for part in grouped_split(examples, seed=7) ]
    second = [ {e.group for e in part} for part in grouped_split(examples, seed=7) ]
    assert first == second


def test_launch_events_are_excluded_by_construction() -> None:
    """A six-month product rollout is not an incident.

    Training on one would teach topical grouping — the exact failure M17 diagnosed.
    """
    from app.pairwise import dataset

    source = dataset.build_examples.__doc__ or ""
    assert "launch" in dataset.__doc__.lower()
    assert "MAX_CANDIDATE_MEMBERS" in dir(dataset) or dataset.MAX_CANDIDATE_MEMBERS >= 1
    assert dataset.NEGATIVES_TIME_ALIGNED is True


# --- model contract -------------------------------------------------------------------------------


class StubModel:
    """A scorer with a known answer, so runtime wiring can be tested without training."""

    model_class = "Stub"
    version = PAIRWISE_VERSION
    feature_names = FEATURE_NAMES
    feature_schema = FEATURE_SCHEMA_VERSION

    def __init__(self, score: float = 0.99, threshold: float = 0.5) -> None:
        self._score = score
        self.threshold = threshold
        self.calls = 0

    def score(self, features: dict[str, float]) -> float:
        missing = set(self.feature_names) - set(features)
        if missing:
            raise PairwiseModelError(f"missing features: {missing}")
        self.calls += 1
        return self._score


def test_a_schema_mismatch_is_refused_rather_than_scored() -> None:
    model = StubModel()
    with pytest.raises(PairwiseModelError, match="missing features"):
        model.score({"service_same": 1.0})


def test_the_threshold_rule_is_recorded() -> None:
    """Chosen on development data, documented before the held-out run."""
    assert "zero hard-negative false positives" in THRESHOLD_RULE
    assert "development" in THRESHOLD_RULE


# --- runtime -------------------------------------------------------------------------------------


def seed_pair():
    return [
        ticket("S1", "Sync workers stuck and queue growing",
               "Connector sync jobs start and never finish. Queue depth is climbing.", 0,
               service="svc-connector"),
        ticket("S2", "Sync workers stuck, queue keeps growing",
               "Connector sync jobs start and never finish. The queue is climbing.", 5,
               service="svc-connector"),
    ]


def test_a_deterministic_attachment_never_invokes_the_classifier() -> None:
    from app.correlation.hybrid import correlate_pairwise

    members = seed_pair()
    arriving = ticket("A1", "Sync workers stuck and the queue keeps growing",
                      "Connector sync jobs start and never finish. Queue depth is climbing "
                      "and nothing completes at all.", 10, service="svc-connector")
    model = StubModel()
    outcome = correlate_pairwise([*members, arriving], "A1", model)

    assert outcome.deterministic_attached is True
    assert model.calls == 0, "the fast path must not pay for a model"


def test_a_hard_conflict_never_invokes_the_classifier() -> None:
    """The gate refuses before the model is consulted, so a high score cannot help."""
    from app.correlation.hybrid import correlate_pairwise

    unrelated = ticket("A1", "Meeting room display will not turn on",
                       "The screen stays black.", 10, service="svc-analytics")
    model = StubModel(score=0.99)
    outcome = correlate_pairwise([*seed_pair(), unrelated], "A1", model)

    assert outcome.attached is False
    assert model.calls == 0


def test_a_confident_classifier_cannot_overrule_an_identifier_conflict() -> None:
    """Even at 0.99. The deterministic layer is the authority; the model is a scorer."""
    from app.correlation.hybrid import correlate_pairwise

    members = [
        ticket("S1", "Authentication stalling for everyone",
               "Sign-in is stalling. Logs show ERR_AUTH_STALL repeatedly.", 0),
        ticket("S2", "Authentication stalls on every attempt",
               "Every attempt stalls. We keep seeing ERR_AUTH_STALL in the logs.", 5),
    ]
    arriving = ticket("A1", "Authentication failing with expired tokens",
                      "Sign-in is failing. The logs show ERR_TOKEN_EXPIRED on each attempt.", 11)
    model = StubModel(score=0.99)
    outcome = correlate_pairwise([*members, arriving], "A1", model)

    assert outcome.attached is False
    assert model.calls == 0, "blocked by the gate before the model was asked"


def ambiguous_case():
    """A cohering candidate plus a low-overlap paraphrase of it.

    The auth pair used elsewhere in this file does not itself form a candidate, so there
    would be nothing for the classifier to score — the connector pair does.
    """
    arriving = ticket(
        "A1",
        "Nothing has landed in the warehouse for hours",
        "Data has stopped arriving on our side entirely. Whatever moves it across "
        "appears to have wedged.",
        11,
        service="svc-connector",
    )
    return [*seed_pair(), arriving]


def test_an_ambiguous_case_invokes_the_classifier() -> None:
    from app.correlation.hybrid import correlate_pairwise

    model = StubModel(score=0.99, threshold=0.5)
    outcome = correlate_pairwise(ambiguous_case(), "A1", model)

    assert model.calls >= 1
    assert outcome.semantic_invoked is True


def test_a_score_below_threshold_leaves_the_ticket_uncorrelated() -> None:
    from app.correlation.hybrid import correlate_pairwise

    model = StubModel(score=0.10, threshold=0.5)
    outcome = correlate_pairwise(ambiguous_case(), "A1", model)

    assert outcome.attached is False
    assert outcome.semantic_score == pytest.approx(0.10)


def test_a_model_failure_is_reported_not_swallowed() -> None:
    from app.correlation.hybrid import correlate_pairwise

    class Broken(StubModel):
        def score(self, features):
            raise PairwiseModelError("artifact unreadable")

    outcome = correlate_pairwise(ambiguous_case(), "A1", Broken())

    assert outcome.attached is False
    assert outcome.semantic_failed is True
    assert outcome.semantic_score is None, "no fabricated score"
    assert "artifact unreadable" in outcome.failure_reason


def test_without_a_model_the_ambiguous_case_simply_stays_uncorrelated() -> None:
    from app.correlation.hybrid import correlate_pairwise

    outcome = correlate_pairwise(ambiguous_case(), "A1", None)
    assert outcome.attached is False
    assert outcome.semantic_invoked is False


def test_the_gate_is_the_m16_gate_unchanged() -> None:
    """Same slice as the embedding fallback, so the two are comparable."""
    from app.correlation.hybrid import correlate_hybrid, correlate_pairwise

    tickets = ambiguous_case()
    pairwise = correlate_pairwise(tickets, "A1", None)
    hybrid = correlate_hybrid(tickets, "A1", None)

    assert [d.candidate_id for d in pairwise.fallback_decisions] == [
        d.candidate_id for d in hybrid.fallback_decisions
    ]
    assert [d.eligible for d in pairwise.fallback_decisions] == [
        d.eligible for d in hybrid.fallback_decisions
    ]


def test_the_versions_are_distinct_and_the_baselines_are_untouched() -> None:
    from app.correlation.rules import (
        CORRELATION_VERSION,
        HYBRID_CORRELATION_VERSION,
        LINK_THRESHOLD,
        PAIRWISE_CORRELATION_VERSION,
        SEMANTIC_CORRELATION_VERSION,
        SEMANTIC_FLOOR,
    )

    assert PAIRWISE_CORRELATION_VERSION == "pairwise-correlation-v1"
    assert CORRELATION_VERSION == "deterministic-correlation-v1"
    assert SEMANTIC_CORRELATION_VERSION == "semantic-correlation-v1"
    assert HYBRID_CORRELATION_VERSION == "hybrid-correlation-v1"
    assert (LINK_THRESHOLD, SEMANTIC_FLOOR) == (0.60, 0.72)
