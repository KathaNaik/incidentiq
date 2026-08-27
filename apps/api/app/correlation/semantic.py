"""Semantic similarity as one correlation signal.

Cosine similarity between embedded tickets, calibrated into the same [0, 1] range the
other components use. Calibration is not optional: this model puts two unrelated English
support tickets around 0.6, so raw cosine would add a large constant to every pair and
wash out the evidence that actually distinguishes incidents.

    score = clamp((cosine - FLOOR) / (CEILING - FLOOR), 0, 1)

Below the floor the signal is 0 — "says nothing" — rather than negative. Semantic
dissimilarity is weak evidence of *anything*; vetoing merges is the job of the service,
issue-type and identifier conflicts, which mean something specific.
"""

import math
from collections.abc import Sequence
from pathlib import Path

from app.correlation.models import CorrelationTicket
from app.correlation.rules import SEMANTIC_CEILING, SEMANTIC_FLOOR
from app.embeddings import (
    EmbeddingCache,
    EmbeddingProvider,
    LocalEmbeddingProvider,
    embedding_text,
)


class SemanticSimilarity:
    """Embeds a ticket set once, then answers pairwise similarity from memory."""

    def __init__(
        self, provider: EmbeddingProvider, cache: EmbeddingCache | None = None
    ) -> None:
        self._provider = provider
        self._cache = cache
        self._vectors: dict[str, tuple[float, ...]] = {}
        # Norms are computed once per ticket rather than twice per pair. On a corpus of
        # any size the pairwise loop dominates, and recomputing a 384-element norm for
        # every comparison is most of the cost.
        self._norms: dict[str, float] = {}

    @property
    def identity(self) -> str:
        return self._provider.identity

    def prepare(self, tickets: Sequence[CorrelationTicket]) -> None:
        """Embeds every ticket that is not already cached, in one batch."""
        texts = {ticket.id: embedding_text(ticket) for ticket in tickets}

        pending: dict[str, str] = {}
        for ticket_id, text in texts.items():
            cached = self._cache.get(text) if self._cache else None
            if cached is not None:
                self._remember(ticket_id, cached)
            else:
                pending[ticket_id] = text

        if pending:
            ids = list(pending)
            vectors = self._provider.embed_many([pending[i] for i in ids])
            for ticket_id, vector in zip(ids, vectors, strict=True):
                self._remember(ticket_id, vector)
                if self._cache:
                    self._cache.put(pending[ticket_id], vector)
            if self._cache:
                self._cache.save()

    def _remember(self, ticket_id: str, vector: tuple[float, ...]) -> None:
        self._vectors[ticket_id] = vector
        self._norms[ticket_id] = math.sqrt(sum(value * value for value in vector))

    def cosine(self, a_id: str, b_id: str) -> float:
        a = self._vectors.get(a_id)
        b = self._vectors.get(b_id)
        if a is None or b is None:
            # prepare() covers every ticket the engine will score; reaching here means
            # a caller skipped it, which must not silently read as "unrelated".
            raise KeyError(f"no embedding prepared for {a_id if a is None else b_id}")

        denominator = self._norms[a_id] * self._norms[b_id]
        if denominator == 0.0:
            return 0.0
        return sum(x * y for x, y in zip(a, b, strict=True)) / denominator

    def score(self, a_id: str, b_id: str) -> tuple[float, float]:
        """Returns (calibrated score, raw cosine)."""
        raw = self.cosine(a_id, b_id)
        return calibrate(raw), raw


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Plain cosine. The model already returns unit vectors, but normalizing here keeps
    the function correct for any provider."""
    if len(a) != len(b):
        raise ValueError(f"vector length mismatch: {len(a)} vs {len(b)}")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def calibrate(cosine: float) -> float:
    """Maps raw cosine onto [0, 1] using the floor and ceiling in `rules.py`."""
    span = SEMANTIC_CEILING - SEMANTIC_FLOOR
    if span <= 0:
        raise ValueError("SEMANTIC_CEILING must exceed SEMANTIC_FLOOR")
    return round(min(1.0, max(0.0, (cosine - SEMANTIC_FLOOR) / span)), 4)


def default_similarity(cache_directory: Path | None = None) -> SemanticSimilarity:
    """The configured provider, with a disk cache when one is given.

    Constructing this does not load the model — that happens on the first embedding, so
    an unavailable provider surfaces as an `EmbeddingError` at use, with a message
    saying what to install.
    """
    provider = LocalEmbeddingProvider()
    cache = EmbeddingCache(cache_directory, provider) if cache_directory else None
    return SemanticSimilarity(provider, cache)
