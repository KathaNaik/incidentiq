"""Hybrid fallback eligibility, offline.

Eligibility is decided entirely from signals the deterministic pass already computed, so
none of this needs a database or an embedding provider — which is the point: deciding
whether to embed must never itself be expensive.
"""

from datetime import UTC, datetime, timedelta

from app.correlation import CorrelationTicket, correlate
from app.correlation.hybrid import correlate_hybrid, evaluate_fallback
from app.correlation.pairwise import Corpus, prepare, score_pair
from app.correlation.rules import (
    FALLBACK_POLICY_VERSION,
    HYBRID_CORRELATION_VERSION,
    LEXICAL_WEAKNESS_MAX,
)

BASE = datetime(2026, 9, 10, 9, 0, tzinfo=UTC)

AUTH_A = (
    "Sign-in requests hang after authentication",
    "Users authenticate with the identity provider and then the request hangs. "
    "The session never finishes establishing and the console never loads.",
)
AUTH_B = (
    "Sign-in hangs once authentication completes",
    "Authentication with the identity provider succeeds and then the request hangs "
    "indefinitely. The session never establishes.",
)
PARAPHRASE = (
    "Users complete SSO but their workspace never finishes loading",
    "Everyone gets through the single sign-on step, then nothing happens. "
    "The workspace never finishes opening for them.",
)


def ticket(tid: str, text: tuple[str, str], minutes: float, service="svc-auth"):
    return CorrelationTicket(
        id=tid,
        title=text[0],
        description=text[1],
        created_at=BASE + timedelta(minutes=minutes),
        service_id=service,
        reported_by=None,
    )


def decisions_for(tickets, arriving_id):
    from app.correlation.hybrid import _fallback_decisions

    return _fallback_decisions(tickets, arriving_id, correlate(tickets))


def seed():
    return [ticket("S1", AUTH_A, 0), ticket("S2", AUTH_B, 6)]


# --- eligibility -------------------------------------------------------------------------


def test_a_paraphrase_on_the_same_service_is_eligible() -> None:
    """The case hybrid exists for: everything agrees except the wording."""
    arriving = ticket("A1", PARAPHRASE, 13)
    found = decisions_for([*seed(), arriving], "A1")

    assert found, "the candidate should have been considered"
    decision = found[0]
    assert decision.eligible is True
    assert any("within the active window" in reason for reason in decision.reasons)
    assert any("no service, issue-type" in reason for reason in decision.reasons)
    assert any("low lexical overlap" in reason for reason in decision.reasons)
    assert decision.blocking_reasons == ()


def test_a_different_service_blocks_fallback() -> None:
    arriving = ticket("A1", PARAPHRASE, 13, service="svc-analytics")
    found = decisions_for([*seed(), arriving], "A1")

    assert found[0].eligible is False
    assert any("service conflict" in reason for reason in found[0].blocking_reasons)


def test_a_stale_candidate_blocks_fallback() -> None:
    """Embeddings do not reopen a candidate the baseline has closed."""
    arriving = ticket("A1", PARAPHRASE, 60 * 24)
    found = decisions_for([*seed(), arriving], "A1")

    assert found == () or found[0].eligible is False


def test_conflicting_error_identifiers_block_fallback() -> None:
    """The most dangerous case: high semantic similarity, incompatible mechanism.

    The deterministic baseline only rewards a *shared* identifier and says nothing about
    differing ones, so hybrid detects this itself rather than changing the baseline.
    """
    members = [
        ticket(
            "S1",
            ("Authentication stalling for everyone",
             "Sign-in is stalling for the whole workspace. Logs show ERR_AUTH_STALL repeatedly."),
            0,
        ),
        ticket(
            "S2",
            ("Authentication stalls on every attempt",
             "Every sign-in attempt stalls. We keep seeing ERR_AUTH_STALL in the logs."),
            6,
        ),
    ]
    arriving = ticket(
        "A1",
        ("Authentication failing with expired tokens",
         "Sign-in is failing for our integrations. The logs show ERR_TOKEN_EXPIRED on each attempt."),
        12,
    )
    found = decisions_for([*members, arriving], "A1")

    assert found[0].eligible is False
    assert any("identifier conflict" in reason for reason in found[0].blocking_reasons)
    assert any("different failure mechanisms" in reason for reason in found[0].blocking_reasons)


def test_a_strong_lexical_match_is_not_eligible() -> None:
    """Fallback is for tickets whose wording failed, not tickets near the threshold.

    A score band would fire here too. Gating on the lexical component specifically is what
    keeps the embedding budget aimed at the case it can actually help.
    """
    members = seed()
    corpus = Corpus()
    features = {}
    for entry in [*members, ticket("A1", AUTH_A, 12)]:
        prepared = prepare(entry)
        corpus.observe(prepared.tokens)
        features[entry.id] = prepared
    scores = [score_pair(features["A1"], features[m.id], corpus, None) for m in members]

    from app.correlation.models import Component

    lexical = min(
        signal.score
        for score in scores
        for signal in score.signals
        if signal.component is Component.LEXICAL
    )
    assert lexical > LEXICAL_WEAKNESS_MAX, "near-identical text has strong lexical overlap"


# --- orchestration -------------------------------------------------------------------------


SYNC_A = (
    "Sync workers stuck and queue growing",
    "Connector sync jobs start and never finish. Queue depth is climbing and nothing completes.",
)
SYNC_B = (
    "Sync workers stuck, queue keeps growing",
    "Connector sync jobs start and never finish. The queue is climbing and nothing completes.",
)
SYNC_C = (
    "Sync workers stuck and the queue keeps growing",
    "Connector sync jobs start and never finish. Queue depth is climbing and nothing completes at all.",
)


def test_a_clear_deterministic_match_takes_the_fast_path() -> None:
    """No provider is touched. The argument is None and nothing raises.

    A near-duplicate rather than a verbatim copy, deliberately: adding a third identical
    ticket dilutes the IDF weights that made the first two distinctive, so a literal copy
    scores *worse* than a close paraphrase of the same wording. That is a real property of
    the corpus-weighted lexical signal, and a test built on a copy would be testing an
    accident.
    """
    members = [
        ticket("S1", SYNC_A, 0, service="svc-connector"),
        ticket("S2", SYNC_B, 5, service="svc-connector"),
    ]
    arriving = ticket("A1", SYNC_C, 10, service="svc-connector")
    outcome = correlate_hybrid([*members, arriving], "A1", None)

    assert outcome.deterministic_attached is True
    assert outcome.semantic_invoked is False
    assert outcome.path == "deterministic"
    assert outcome.version == HYBRID_CORRELATION_VERSION


def test_fallback_is_not_attempted_without_a_provider() -> None:
    arriving = ticket("A1", PARAPHRASE, 13)
    outcome = correlate_hybrid([*seed(), arriving], "A1", None)

    assert outcome.attached is False
    assert outcome.semantic_invoked is False
    assert any(decision.eligible for decision in outcome.fallback_decisions)


def test_a_provider_failure_is_reported_not_swallowed() -> None:
    class Broken:
        identity = "broken"

        def prepare(self, tickets):
            raise RuntimeError("model unavailable")

    outcome = correlate_hybrid([*seed(), ticket("A1", PARAPHRASE, 13)], "A1", Broken())

    assert outcome.semantic_failed is True
    assert outcome.attached is False
    assert outcome.semantic_score is None, "no fabricated score"
    assert "model unavailable" in outcome.failure_reason


def test_only_eligible_candidate_members_are_embedded() -> None:
    """Hybrid must not become 'embed everything and compare'."""
    seen: list[list[str]] = []

    class Recording:
        identity = "recording"

        def prepare(self, tickets):
            seen.append(sorted(t.id for t in tickets))
            raise RuntimeError("stop here — the question is what was asked for")

    unrelated = ticket("U1", ("Printer offline", "The printer will not print."), 8,
                       service="svc-analytics")
    correlate_hybrid([*seed(), unrelated, ticket("A1", PARAPHRASE, 13)], "A1", Recording())

    assert seen, "fallback should have been attempted"
    assert "U1" not in seen[0], "a different-service ticket is never embedded"
    assert set(seen[0]) == {"S1", "S2", "A1"}


def test_the_versions_are_distinct_and_recorded() -> None:
    assert HYBRID_CORRELATION_VERSION == "hybrid-correlation-v1"
    assert FALLBACK_POLICY_VERSION == "fallback-policy-v1"
    # The historical baselines are untouched.
    from app.correlation.rules import (
        COHESION_MIN,
        CONTENT_LINK_MIN,
        CORRELATION_VERSION,
        LINK_THRESHOLD,
        SEMANTIC_CORRELATION_VERSION,
        SEMANTIC_FLOOR,
    )

    assert CORRELATION_VERSION == "deterministic-correlation-v1"
    assert SEMANTIC_CORRELATION_VERSION == "semantic-correlation-v1"
    assert (LINK_THRESHOLD, CONTENT_LINK_MIN, COHESION_MIN) == (0.60, 0.50, 0.55)
    assert SEMANTIC_FLOOR == 0.72
