"""The embedding model registry and the bake-off harness.

Offline throughout: no model is loaded and no vector is computed. Model *behaviour* is
measured by `scripts/run_bakeoff.py`, which is an experiment rather than a test —
asserting a particular cosine in a unit test would be pinning a third-party model's
output, and it would fail for the right reason on the day the model changed.
"""

from datetime import UTC, datetime

import pytest

from app.correlation.models import CorrelationTicket
from app.embeddings import embedding_text
from app.embeddings.cache import content_key
from app.embeddings.local import LocalEmbeddingProvider
from app.embeddings.registry import (
    BGE_LARGE,
    BGE_SMALL,
    DEFAULT_MODEL_ID,
    GTE_BASE,
    MODELS,
    spec_for,
)
from evaluation.bakeoff import ModelResult, Pair


# --- registry ---------------------------------------------------------------------------


def test_the_baseline_is_unchanged_and_is_still_the_default() -> None:
    """Every M6/M7/M13/M16 result was measured with it, and the historical retrieval
    corpus is embedded with it. A silent change here invalidates all of them."""
    assert BGE_SMALL.model_name == "BAAI/bge-small-en-v1.5"
    assert BGE_SMALL.dimension == 384
    assert DEFAULT_MODEL_ID == "bge-small"


def test_every_registered_model_declares_its_own_dimension() -> None:
    assert {spec.id: spec.dimension for spec in MODELS.values()} == {
        "bge-small": 384,
        "gte-base": 768,
        "bge-large": 1024,
    }


def test_the_provider_reports_the_registered_dimension_not_a_constant() -> None:
    """The bug this registry exists for.

    `dimension` was a module constant while `model_name` was already a parameter, so a
    provider built for a 1024-dimension model reported 384 — a wrong shape rather than
    an error.
    """
    for spec in MODELS.values():
        assert LocalEmbeddingProvider(spec.model_name).dimensions == spec.dimension


def test_an_unknown_model_is_refused_by_name() -> None:
    with pytest.raises(KeyError, match="unknown embedding model"):
        spec_for("some-model-nobody-evaluated")


def test_identity_distinguishes_every_model() -> None:
    identities = {spec.identity for spec in MODELS.values()}
    assert len(identities) == len(MODELS)
    assert BGE_SMALL.identity == "fastembed:BAAI/bge-small-en-v1.5"


# --- cache isolation ------------------------------------------------------------------------


def test_two_models_can_never_read_each_others_vectors() -> None:
    """Cache keys fold in provider identity, so a 384-dimension vector cannot be served
    to a 1024-dimension model. Without this the failure is silent and catastrophic."""
    text = "Sign-in through the identity provider is failing for the whole workspace."
    keys = {spec.id: content_key(spec.identity, text) for spec in MODELS.values()}

    assert len(set(keys.values())) == len(MODELS), "one key per model"
    assert content_key(BGE_SMALL.identity, text) == content_key(BGE_SMALL.identity, text)


def test_the_cache_key_changes_with_the_text() -> None:
    a = content_key(BGE_SMALL.identity, "one report")
    b = content_key(BGE_SMALL.identity, "a different report")
    assert a != b


# --- canonical input --------------------------------------------------------------------------


def test_the_embedding_text_is_identical_across_models() -> None:
    """The experiment is model-only.

    Embedding text is a pure function of the ticket — it takes no model argument — so a
    challenger cannot be helped by a different representation. Asserting it here makes
    that structural fact a checked one.
    """
    ticket = CorrelationTicket(
        id="T-1",
        title="Sign-in requests hang after authentication",
        description="Users authenticate and then the request hangs.",
        created_at=datetime(2026, 9, 1, 9, 0, tzinfo=UTC),
        service_id="svc-auth",
        reported_by=None,
    )
    rendered = embedding_text(ticket)
    assert [rendered] * 3 == [embedding_text(ticket) for _ in MODELS]
    # And it carries nothing an evaluation label could hide in.
    for leak in ("expected", "root_cause", "event_id", "label", "attach"):
        assert leak not in rendered.lower()


# --- bake-off metrics ---------------------------------------------------------------------------


def pair(pair_id: str, kind: str) -> Pair:
    ticket = CorrelationTicket(
        id=pair_id,
        title="t",
        description="d",
        created_at=datetime(2026, 9, 1, 9, 0, tzinfo=UTC),
        service_id="svc-auth",
        reported_by=None,
    )
    return Pair(id=pair_id, kind=kind, left=ticket, right=ticket, note="")


def result(scores: dict[str, float], kinds: dict[str, str]) -> ModelResult:
    return ModelResult(
        model_id="test",
        model_name="test",
        dimension=8,
        scores=scores,
        pairs=tuple(pair(pid, kinds[pid]) for pid in scores),
    )


def test_a_negative_separation_margin_means_no_threshold_works() -> None:
    """The M16 finding, as a computation.

    A dangerous negative scoring above the weakest true paraphrase means any floor low
    enough to admit the paraphrase admits the false merge first.
    """
    model = result(
        {"p1": 0.70, "p2": 0.74, "n1": 0.80},
        {"p1": "positive", "p2": "positive", "n1": "dangerous_negative"},
    )

    assert model.separation_margin == pytest.approx(-0.10)
    assert model.summary()["separable"] is False


def test_a_positive_margin_means_a_threshold_exists() -> None:
    model = result(
        {"p1": 0.85, "p2": 0.88, "n1": 0.60},
        {"p1": "positive", "p2": "positive", "n1": "dangerous_negative"},
    )

    assert model.separation_margin == pytest.approx(0.25)
    assert model.summary()["separable"] is True


def test_ordering_accuracy_counts_every_positive_negative_comparison() -> None:
    model = result(
        {"p1": 0.90, "p2": 0.50, "n1": 0.60, "n2": 0.40},
        {
            "p1": "positive",
            "p2": "positive",
            "n1": "dangerous_negative",
            "n2": "dangerous_negative",
        },
    )

    # p1 beats both; p2 beats only n2. Three of four.
    assert model.ordering_accuracy == (3, 4)
    assert model.summary()["ordering_accuracy"] == pytest.approx(0.75)


def test_near_duplicates_are_excluded_from_the_margin() -> None:
    """They already attach deterministically.

    Letting them into the positive set would make every model look separable while the
    paraphrases — the cases that actually need help — stayed unrecovered.
    """
    model = result(
        {"p1": 0.70, "dup": 0.99, "n1": 0.80},
        {"p1": "positive", "dup": "near_duplicate", "n1": "dangerous_negative"},
    )

    assert model.positives == [0.70], "the anchor is not a positive"
    assert model.near_duplicates == [0.99]
    assert model.separation_margin < 0


def test_a_uniformly_higher_scoring_model_is_not_automatically_better() -> None:
    """Guards the trap: absolute cosine says nothing, ordering says everything."""
    low = result(
        {"p1": 0.40, "n1": 0.30}, {"p1": "positive", "n1": "dangerous_negative"}
    )
    high = result(
        {"p1": 0.90, "n1": 0.95}, {"p1": "positive", "n1": "dangerous_negative"}
    )

    assert low.separation_margin > 0 and high.separation_margin < 0
    assert low.summary()["positive_mean"] < high.summary()["positive_mean"]


# --- the pair set --------------------------------------------------------------------------------


def test_the_pair_set_comes_from_the_authored_cases() -> None:
    """Not written for this experiment. A pair set invented to flatter a model measures
    nothing, so every pair is drawn from the M16 online cases."""
    from app.config import get_settings
    from evaluation.bakeoff import build_pairs

    directory = get_settings().evals_dir.parent / "intake"
    pairs = build_pairs(directory)

    assert len(pairs) >= 10
    assert sum(1 for p in pairs if p.kind == "positive") >= 4
    assert sum(1 for p in pairs if p.is_dangerous) >= 5
    assert sum(1 for p in pairs if p.kind == "near_duplicate") >= 1
    # Every pair traces back to an authored case id.
    for entry in pairs:
        assert entry.id.split(":")[0].startswith(("ON", "PR"))
