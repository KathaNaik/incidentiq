"""Semantic correlation, tested with a stub provider.

No test here loads a model or touches the network: every vector is authored inline, so
the tests assert what the *scoring* does with a similarity, not what a particular
embedding believes.
"""

import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.correlation import CorrelationTicket, correlate
from app.correlation.models import Component
from app.correlation.rules import (
    CORRELATION_VERSION,
    SEMANTIC_CEILING,
    SEMANTIC_CORRELATION_VERSION,
    SEMANTIC_FLOOR,
)
from app.correlation.semantic import SemanticSimilarity, calibrate, cosine_similarity
from app.embeddings import EmbeddingCache, EmbeddingError, content_key, embedding_text
from app.embeddings.provider import EmbeddingProvider

START = datetime(2026, 8, 24, 9, 0, tzinfo=UTC)


class StubProvider:
    """Returns a fixed vector per text, and records what it was asked to embed."""

    identity = "stub:v1"
    dimensions = 3

    def __init__(self, vectors: dict[str, tuple[float, ...]] | None = None) -> None:
        self.vectors = vectors or {}
        self.seen: list[str] = []
        self.calls = 0

    def embed(self, text: str) -> tuple[float, ...]:
        return self.embed_many([text])[0]

    def embed_many(self, texts):
        self.calls += 1
        self.seen.extend(texts)
        return tuple(self.vectors.get(text, (1.0, 0.0, 0.0)) for text in texts)


class BrokenProvider:
    identity = "broken:v1"
    dimensions = 3

    def embed(self, text):
        raise EmbeddingError("provider is unavailable")

    def embed_many(self, texts):
        raise EmbeddingError("provider is unavailable")


def ticket(id: str, title: str, description: str = "", minutes: float = 0.0, **kwargs):
    return CorrelationTicket(
        id=id,
        title=title,
        description=description,
        created_at=START + timedelta(minutes=minutes),
        **kwargs,
    )


def similarity_over(tickets, vectors: dict[str, tuple[float, ...]]):
    """Builds a stub similarity keyed by each ticket's canonical embedding text."""
    provider = StubProvider(
        {embedding_text(t): vectors[t.id] for t in tickets if t.id in vectors}
    )
    return SemanticSimilarity(provider)


# --- canonical text and leakage ------------------------------------------------------


def test_embedding_text_is_title_and_description_only() -> None:
    assert embedding_text(ticket("T", "Sync failed", "No rows arrived.")) == (
        "Sync failed\n\nNo rows arrived."
    )
    assert embedding_text(ticket("T", "  Sync failed  ")) == "Sync failed"


def test_service_is_not_embedded() -> None:
    """Service already scores as its own signal; embedding it too would double-count
    the agreement that caused false merges in the deterministic baseline."""
    with_service = ticket("T", "Sync failed", "No rows.", service_id="svc-connector")
    without = ticket("T", "Sync failed", "No rows.")

    assert embedding_text(with_service) == embedding_text(without)


def test_ground_truth_cannot_reach_the_embedding_input() -> None:
    """Not "we remembered not to include it" — there is no field to include."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        CorrelationTicket(
            id="T",
            title="Sync failed",
            created_at=START,
            event_id="EVT-1",
            event_type="outage",
            topic="connectors",
            routing="tier2",
        )

    text = embedding_text(ticket("T", "Sync failed", "No rows arrived."))
    for label in ("EVT-1", "outage", "connectors", "tier2"):
        assert label not in text


def test_only_canonical_text_is_sent_to_the_provider() -> None:
    tickets = [ticket("A", "Sync failed", "No rows.", service_id="svc-connector")]
    provider = StubProvider()

    SemanticSimilarity(provider).prepare(tickets)

    assert provider.seen == ["Sync failed\n\nNo rows."]


# --- similarity ---------------------------------------------------------------------


def test_cosine_similarity() -> None:
    assert cosine_similarity((1.0, 0.0), (1.0, 0.0)) == pytest.approx(1.0)
    assert cosine_similarity((1.0, 0.0), (0.0, 1.0)) == pytest.approx(0.0)
    assert cosine_similarity((1.0, 0.0), (-1.0, 0.0)) == pytest.approx(-1.0)
    assert cosine_similarity((3.0, 4.0), (3.0, 4.0)) == pytest.approx(1.0)
    # A zero vector has no direction; report no similarity rather than dividing by zero.
    assert cosine_similarity((0.0, 0.0), (1.0, 0.0)) == 0.0

    with pytest.raises(ValueError, match="length mismatch"):
        cosine_similarity((1.0,), (1.0, 0.0))


def test_calibration_maps_the_useful_band_onto_zero_to_one() -> None:
    """Raw cosine is useless as a signal here: this family of models scores unrelated
    support tickets around 0.6, so without a floor every pair gets a constant bonus."""
    assert calibrate(SEMANTIC_FLOOR) == 0.0
    assert calibrate(SEMANTIC_FLOOR - 0.2) == 0.0
    assert calibrate(SEMANTIC_CEILING) == 1.0
    assert calibrate(SEMANTIC_CEILING + 0.2) == 1.0
    midpoint = (SEMANTIC_FLOOR + SEMANTIC_CEILING) / 2
    assert calibrate(midpoint) == pytest.approx(0.5, abs=0.01)


def test_missing_embedding_raises_rather_than_scoring_zero() -> None:
    """A silent zero would read as "unrelated" and quietly disable the signal."""
    similarity = SemanticSimilarity(StubProvider())

    with pytest.raises(KeyError):
        similarity.cosine("never-prepared", "also-not")


def test_provider_failure_propagates() -> None:
    with pytest.raises(EmbeddingError, match="unavailable"):
        SemanticSimilarity(BrokenProvider()).prepare([ticket("A", "Sync failed")])


# --- scoring integration -------------------------------------------------------------


def test_semantic_signal_appears_only_in_the_semantic_version() -> None:
    tickets = [
        ticket("A", "Warehouse sync stopped working", "No rows.", service_id="svc-connector"),
        ticket("B", "Connector sync stopped working", "No rows.", minutes=5, service_id="svc-connector"),
    ]
    vectors = {"A": (1.0, 0.0, 0.0), "B": (1.0, 0.0, 0.0)}

    baseline = correlate(tickets)
    semantic = correlate(tickets, similarity_over(tickets, vectors))

    assert baseline.version == CORRELATION_VERSION
    assert semantic.version == SEMANTIC_CORRELATION_VERSION
    baseline_components = {
        signal.component
        for candidate in baseline.candidates
        for pair in candidate.member_pairs
        for signal in pair.signals
    }
    semantic_components = {
        signal.component
        for candidate in semantic.candidates
        for pair in candidate.member_pairs
        for signal in pair.signals
    }
    assert Component.SEMANTIC not in baseline_components
    assert Component.SEMANTIC in semantic_components


def test_semantic_signal_is_inspectable() -> None:
    tickets = [
        ticket("A", "Warehouse sync stopped working", "No rows.", service_id="svc-connector"),
        ticket("B", "Connector sync stopped working", "No rows.", minutes=5, service_id="svc-connector"),
    ]
    result = correlate(
        tickets, similarity_over(tickets, {"A": (1.0, 0.0, 0.0), "B": (1.0, 0.0, 0.0)})
    )

    signal = next(
        s
        for pair in result.candidates[0].member_pairs
        for s in pair.signals
        if s.component is Component.SEMANTIC
    )
    assert signal.score == 1.0
    assert signal.weight > 0
    assert "cosine" in signal.detail
    assert signal.values == ("stub:v1",)


def test_semantic_similarity_alone_cannot_merge_across_a_service_conflict() -> None:
    """Identical vectors, different services — the deterministic conflict still wins."""
    tickets = [
        ticket("A", "Cannot open the console", "Nothing works.", service_id="svc-auth"),
        ticket("B", "Cannot open the console", "Nothing works.", minutes=3, service_id="svc-analytics"),
    ]

    result = correlate(
        tickets, similarity_over(tickets, {"A": (1.0, 0.0, 0.0), "B": (1.0, 0.0, 0.0)})
    )

    assert result.candidates == ()


def test_semantic_similarity_alone_cannot_merge_across_a_time_gap() -> None:
    """Identical text and identical vectors, five hours apart, stay separate."""
    tickets = [
        ticket("A", "OAuth sign-in unavailable", "Refusing every attempt.", service_id="svc-auth"),
        ticket("B", "OAuth sign-in unavailable", "Refusing every attempt.", minutes=300, service_id="svc-auth"),
    ]

    result = correlate(
        tickets, similarity_over(tickets, {"A": (1.0, 0.0, 0.0), "B": (1.0, 0.0, 0.0)})
    )

    assert result.candidates == ()


def test_low_similarity_does_not_veto_otherwise_strong_evidence() -> None:
    """Dissimilar text is weak evidence of anything; conflicts do the vetoing."""
    tickets = [
        ticket("A", "Sync failing with ERR_SYNC_412", "Aborts every run.", service_id="svc-connector"),
        ticket("B", "ERR_SYNC_412 on manual resync", "Returns immediately.", minutes=4, service_id="svc-connector"),
    ]
    orthogonal = {"A": (1.0, 0.0, 0.0), "B": (0.0, 1.0, 0.0)}

    result = correlate(tickets, similarity_over(tickets, orthogonal))

    assert result.candidates, "shared identifier and timing should still carry this"


def test_semantic_output_is_deterministic_for_fixed_vectors() -> None:
    tickets = [
        ticket("A", "Warehouse sync stopped working", "No rows.", service_id="svc-connector"),
        ticket("B", "Connector sync stopped working", "No rows.", minutes=5, service_id="svc-connector"),
        ticket("C", "How do I add a user?", minutes=9),
    ]
    vectors = {"A": (1.0, 0.0, 0.0), "B": (0.9, 0.1, 0.0), "C": (0.0, 0.0, 1.0)}

    first = correlate(tickets, similarity_over(tickets, vectors))
    second = correlate(list(reversed(tickets)), similarity_over(tickets, vectors))

    assert first.model_dump_json() == second.model_dump_json()


def test_deterministic_baseline_is_untouched_by_this_milestone() -> None:
    """The comparison is only meaningful if the baseline still behaves as it did."""
    tickets = [
        ticket("A", "Warehouse sync stopped working", "Connector sync stopped working, no rows arrive.", service_id="svc-connector"),
        ticket("B", "Connector sync stopped working", "Sync stopped working, no rows arriving.", minutes=5, service_id="svc-connector"),
        ticket("C", "Permission denied writing to the warehouse", "The service account is not authorized.", minutes=10, service_id="svc-connector"),
    ]

    result = correlate(tickets)

    assert result.version == CORRELATION_VERSION
    assert [c.ticket_ids for c in result.candidates] == [("A", "B")]
    assert "C" in result.standalone_ticket_ids


# --- cache ---------------------------------------------------------------------------


def test_cache_avoids_recomputing_and_survives_a_restart(tmp_path: Path) -> None:
    tickets = [ticket("A", "Sync failed", "No rows.")]
    provider = StubProvider({embedding_text(tickets[0]): (0.6, 0.8, 0.0)})
    cache = EmbeddingCache(tmp_path, provider)

    SemanticSimilarity(provider, cache).prepare(tickets)
    assert provider.calls == 1
    assert cache.size == 1

    # A fresh cache object reads the files back; the provider is not called again.
    reopened = EmbeddingCache(tmp_path, provider)
    SemanticSimilarity(provider, reopened).prepare(tickets)
    assert provider.calls == 1
    assert reopened.get(embedding_text(tickets[0])) == pytest.approx((0.6, 0.8, 0.0))


def test_cache_key_covers_provider_identity() -> None:
    assert content_key("stub:v1", "text") != content_key("stub:v2", "text")
    assert content_key("stub:v1", "text") == content_key("stub:v1", "text")


def test_cache_refuses_vectors_from_a_different_model(tmp_path: Path) -> None:
    """Stale vectors would silently invalidate an evaluation, so this is an error."""
    first = StubProvider()
    cache = EmbeddingCache(tmp_path, first)
    cache.put("text", (1.0, 0.0, 0.0))
    cache.save()

    class OtherModel(StubProvider):
        identity = "stub:v2"

    # A different identity writes to its own files, so the mismatch is only reachable
    # by pointing one identity at another's index.
    index = next(tmp_path.glob("*.index.json"))
    payload = json.loads(index.read_text())
    payload["identity"] = "stub:v2"
    index.write_text(json.dumps(payload))

    with pytest.raises(EmbeddingError, match="was written by"):
        EmbeddingCache(tmp_path, first)


def test_cache_rejects_a_wrong_sized_vector(tmp_path: Path) -> None:
    cache = EmbeddingCache(tmp_path, StubProvider())

    with pytest.raises(EmbeddingError, match="3-dimensional"):
        cache.put("text", (1.0, 0.0))


def test_provider_protocol_is_satisfied_by_the_stub() -> None:
    assert isinstance(StubProvider(), EmbeddingProvider)


# --- API -----------------------------------------------------------------------------


def test_correlation_mode_defaults_to_deterministic(client: TestClient) -> None:
    """The existing endpoint must not silently become semantic."""
    response = client.get("/correlation/candidates")

    assert response.status_code == 200
    assert response.json()["version"] == CORRELATION_VERSION


def test_unknown_correlation_mode_is_rejected(client: TestClient) -> None:
    assert client.get("/correlation/candidates?mode=magic").status_code == 422


def test_unavailable_provider_reports_a_configuration_error(
    client: TestClient, monkeypatch
) -> None:
    """Semantic mode must fail loudly rather than quietly returning baseline results."""
    import app.routers.correlation as router

    monkeypatch.setattr(
        router, "default_similarity", lambda _: SemanticSimilarity(BrokenProvider())
    )
    response = client.get("/correlation/candidates?mode=semantic")

    assert response.status_code == 503
    assert "unavailable" in response.json()["detail"]


def test_versioned_evaluation_artifacts_are_served(client: TestClient) -> None:
    deterministic = client.get("/evals/correlation?version=deterministic")
    semantic = client.get("/evals/correlation?version=semantic")
    comparison = client.get("/evals/correlation/comparison")

    assert deterministic.json()["version"] == CORRELATION_VERSION
    assert semantic.json()["version"] == SEMANTIC_CORRELATION_VERSION
    assert comparison.status_code == 200
    body = comparison.json()
    assert body["baseline_version"] == CORRELATION_VERSION
    assert body["candidate_version"] == SEMANTIC_CORRELATION_VERSION
    assert {metric["name"] for metric in body["metrics"]} >= {
        "pairwise_precision",
        "pairwise_recall",
        "false_merge_rate",
    }


def test_weight_sets_are_normalized() -> None:
    """Both versions must sum their content weights to 1.0, or their scores are not
    comparable and the thresholds mean different things."""
    from app.correlation import rules

    deterministic = (
        rules.W_SERVICE + rules.W_ISSUE + rules.W_LEXICAL + rules.W_ENTITY
    )
    semantic = (
        rules.W_SERVICE_SEMANTIC
        + rules.W_ISSUE_SEMANTIC
        + rules.W_LEXICAL_SEMANTIC
        + rules.W_ENTITY_SEMANTIC
        + rules.W_SEMANTIC
    )

    assert math.isclose(deterministic, 1.0)
    assert math.isclose(semantic, 1.0)
