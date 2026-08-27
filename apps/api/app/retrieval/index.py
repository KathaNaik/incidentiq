"""In-memory retrieval index over the historical corpus.

745 records at 384 dimensions is about 1 MB of floats. A vector database would add an
operational dependency to search a list that fits in L3 cache, so the index is a list of
vectors and the search is a loop.

Vectors come from the M6 embedding cache, which is already keyed by provider and model
identity and refuses to serve vectors written by a different model. That is the whole of
the "stale index" protection — there is no second artifact to go stale.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from app.correlation.semantic import cosine_similarity
from app.embeddings import EmbeddingCache, EmbeddingProvider
from app.retrieval.corpus import CorpusError
from app.retrieval.models import (
    HistoricalIncident,
    MatchSignal,
    RetrievalHit,
    RetrievalQuery,
    RetrievalResult,
)
from app.retrieval.rules import (
    DEFAULT_K,
    MAX_K,
    RETRIEVAL_VERSION,
    STRONG_MATCH_SCORE,
    SERVICE_STOP_WORDS,
    W_ERROR,
    W_SERVICE,
    W_SIMILARITY,
)
from app.retrieval.text import index_text, query_text


def _tokens(values: Sequence[str]) -> frozenset[str]:
    """Normalized words, so `svc-connector` and `Connector API` can meet."""
    words: set[str] = set()
    for value in values:
        for word in value.lower().replace("-", " ").replace("_", " ").split():
            if len(word) > 2 and word not in SERVICE_STOP_WORDS:
                words.add(word)
    return frozenset(words)


@dataclass(frozen=True)
class _Entry:
    incident: HistoricalIncident
    vector: tuple[float, ...]
    service_tokens: frozenset[str]
    error_tokens: frozenset[str]


class HistoricalIndex:
    """Embeds the corpus once, then answers top-K queries from memory."""

    def __init__(
        self,
        provider: EmbeddingProvider,
        cache: EmbeddingCache | None = None,
    ) -> None:
        self._provider = provider
        self._cache = cache
        self._entries: list[_Entry] = []

    @property
    def size(self) -> int:
        return len(self._entries)

    @property
    def provider_identity(self) -> str:
        return self._provider.identity

    def build(self, records: Sequence[HistoricalIncident]) -> None:
        """Embeds every record, reusing cached vectors where they exist."""
        texts = [index_text(record) for record in records]

        vectors: list[tuple[float, ...] | None] = []
        pending: list[tuple[int, str]] = []
        for position, text in enumerate(texts):
            cached = self._cache.get(text) if self._cache else None
            vectors.append(cached)
            if cached is None:
                pending.append((position, text))

        if pending:
            fresh = self._provider.embed_many([text for _, text in pending])
            for (position, text), vector in zip(pending, fresh, strict=True):
                vectors[position] = vector
                if self._cache:
                    self._cache.put(text, vector)
            if self._cache:
                self._cache.save()

        self._entries = [
            _Entry(
                incident=record,
                vector=vector,
                service_tokens=_tokens(record.services),
                error_tokens=_tokens(record.observed_errors),
            )
            for record, vector in zip(records, vectors, strict=True)
            if vector is not None
        ]

    def search(
        self,
        query: RetrievalQuery,
        *,
        k: int = DEFAULT_K,
        exclude: frozenset[str] = frozenset(),
        rerank: bool = True,
    ) -> RetrievalResult:
        """Top-K historical incidents for the current situation.

        `exclude` removes records from consideration — the evaluation uses it to hold
        out the record a query was derived from, so the measurement is precedent
        retrieval rather than finding the document you started from.
        """
        if not self._entries:
            raise CorpusError("retrieval index is empty; build it before searching")
        if k < 1 or k > MAX_K:
            raise ValueError(f"k must be between 1 and {MAX_K}, got {k}")

        text = query_text(query)
        vector = self._provider.embed(text)

        query_services = _tokens(query.services)
        query_errors = _tokens(query.error_identifiers)

        scored: list[tuple[float, float, list[MatchSignal], _Entry]] = []
        for entry in self._entries:
            if entry.incident.id in exclude:
                continue

            similarity = cosine_similarity(vector, entry.vector)
            signals = [
                MatchSignal(
                    kind="semantic",
                    detail=f"symptom similarity {similarity:.3f}",
                    contribution=round(W_SIMILARITY * similarity, 4),
                )
            ]
            score = W_SIMILARITY * similarity

            if rerank:
                shared_services = query_services & entry.service_tokens
                if shared_services:
                    score += W_SERVICE
                    signals.append(
                        MatchSignal(
                            kind="service",
                            detail=f"shared service terms: {', '.join(sorted(shared_services))}",
                            contribution=W_SERVICE,
                            values=tuple(sorted(shared_services)),
                        )
                    )
                shared_errors = query_errors & entry.error_tokens
                if shared_errors:
                    score += W_ERROR
                    signals.append(
                        MatchSignal(
                            kind="error_identifier",
                            detail=f"shared error terms: {', '.join(sorted(shared_errors))}",
                            contribution=W_ERROR,
                            values=tuple(sorted(shared_errors)),
                        )
                    )

            scored.append((round(min(1.0, score), 6), similarity, signals, entry))

        # Ties break on id so the same corpus and query always produce the same order.
        scored.sort(key=lambda row: (-row[0], row[3].incident.id))

        top = scored[0][0] if scored else 0.0
        return RetrievalResult(
            version=RETRIEVAL_VERSION,
            provider=self._provider.identity,
            corpus_size=len(self._entries) - len(exclude & self._ids()),
            query_text=text,
            strong_match=top >= STRONG_MATCH_SCORE,
            hits=tuple(
                RetrievalHit(
                    rank=position,
                    incident=entry.incident,
                    score=score,
                    similarity=round(similarity, 6),
                    signals=tuple(signals),
                )
                for position, (score, similarity, signals, entry) in enumerate(
                    scored[:k], start=1
                )
            ),
        )

    def _ids(self) -> frozenset[str]:
        return frozenset(entry.incident.id for entry in self._entries)
