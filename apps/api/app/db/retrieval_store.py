"""Historical retrieval over pgvector.

This replaces the in-memory index as the application's retrieval path. The reason is not
speed — the in-memory search answered in about 40 ms over 751 records and was never a
bottleneck. The reasons are architectural:

- PostgreSQL is now required for durable workflow state regardless, so this consolidates
  two persistence stories into one.
- Vectors survive a restart. The application no longer spends ~75 s rebuilding a corpus
  index on cold start, and no longer holds every vector in memory to answer one query.
- Inserting a new historical incident becomes an INSERT rather than a rebuild.
- Ranking and metadata filtering happen in one query, close to the data.

**The ranking is unchanged, deliberately.** M7 scores
`0.80·cosine + 0.08·service_overlap + 0.12·error_overlap`, not raw cosine, so a naive
"ORDER BY embedding <=> query" would have quietly changed what the product returns. The
whole expression is computed in SQL instead: pgvector supplies the cosine term, and the
overlap terms become array intersections over tokens normalised at import time by the
*same* Python function the in-memory index used. Ties break on id, as before.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Engine, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.types import Text

from app.db.engine import get_engine, sessionmaker_for
from app.embeddings import EmbeddingProvider
from app.retrieval.index import _tokens
from app.retrieval.models import (
    HistoricalIncident,
    HistoricalOutcome,
    MatchSignal,
    Provenance,
    RetrievalHit,
    RetrievalQuery,
    RetrievalResult,
)
from app.retrieval.rules import (
    DEFAULT_K,
    MAX_K,
    RETRIEVAL_VERSION,
    STRONG_MATCH_SCORE,
    W_ERROR,
    W_SERVICE,
    W_SIMILARITY,
)
from app.retrieval.text import query_text


class RetrievalStoreError(RuntimeError):
    """The corpus is missing or unusable."""


@dataclass(frozen=True)
class RetrievalFilters:
    """Structured narrowing, applied before ranking.

    Present because the capability is the point of moving into SQL, not because the
    product filters today: the default retrieval passes none of these, so ranking
    behaviour is identical to M7.
    """

    provenance: tuple[str, ...] = ()
    services: tuple[str, ...] = ()


# One statement does the whole of M7's scoring.
#
#   1 - (embedding <=> :vector)   cosine similarity; pgvector's <=> is cosine distance
#   service_tokens && :services   array overlap, the SQL form of a set intersection
#
# Ordered by score then id so the same corpus and query always produce the same order.
_SEARCH = text(
    """
    WITH scored AS (
        SELECT
            id, source_record_id, provenance, title, summary, services,
            observed_errors, occurred_at, root_cause, resolution_steps,
            service_tokens, error_tokens,
            1 - (embedding <=> :vector) AS similarity,
            (service_tokens && :service_tokens) AS service_hit,
            (error_tokens && :error_tokens) AS error_hit
        FROM historical_incidents
        WHERE (:provenance_count = 0 OR provenance = ANY(:provenance))
          AND (:filter_service_count = 0 OR service_tokens && :filter_services)
          AND (:exclude_count = 0 OR NOT (id = ANY(:exclude)))
    )
    SELECT *,
           LEAST(1.0,
                 :w_similarity * similarity
                 + CASE WHEN service_hit THEN :w_service ELSE 0 END
                 + CASE WHEN error_hit THEN :w_error ELSE 0 END
           ) AS score
    FROM scored
    ORDER BY score DESC, id ASC
    LIMIT :k
    """
).bindparams(
    bindparam("service_tokens", type_=ARRAY(Text)),
    bindparam("error_tokens", type_=ARRAY(Text)),
    bindparam("provenance", type_=ARRAY(Text)),
    bindparam("filter_services", type_=ARRAY(Text)),
    bindparam("exclude", type_=ARRAY(Text)),
)


class PgVectorHistoricalIndex:
    """The application's historical retrieval, backed by PostgreSQL."""

    def __init__(
        self, provider: EmbeddingProvider, engine: Engine | None = None
    ) -> None:
        self._provider = provider
        self._engine = engine or get_engine()
        self._session = sessionmaker_for(self._engine)

    @property
    def provider_identity(self) -> str:
        return self._provider.identity

    @property
    def size(self) -> int:
        with self._session() as session:
            return int(
                session.execute(
                    text("SELECT count(*) FROM historical_incidents")
                ).scalar_one()
            )

    def search(
        self,
        query: RetrievalQuery,
        *,
        k: int = DEFAULT_K,
        exclude: frozenset[str] = frozenset(),
        rerank: bool = True,
        filters: RetrievalFilters | None = None,
    ) -> RetrievalResult:
        """Top-K historical incidents for the current situation."""
        if k < 1 or k > MAX_K:
            raise ValueError(f"k must be between 1 and {MAX_K}, got {k}")

        size = self.size
        if size == 0:
            raise RetrievalStoreError(
                "historical_incidents is empty; run "
                "`scripts/import_historical.py` to populate it"
            )

        # Symptoms only. `query_text` is the single place a query is built, and
        # RetrievalQuery has no field that could carry a root cause or a resolution.
        rendered = query_text(query)
        vector = list(self._provider.embed(rendered))

        filters = filters or RetrievalFilters()
        # rerank=False zeroes the overlap weights rather than taking a different code
        # path, so the ablation the evaluation uses cannot drift from the real ranking.
        params = {
            "vector": str(vector),
            "service_tokens": sorted(_tokens(query.services)) if rerank else [],
            "error_tokens": sorted(_tokens(query.error_identifiers)) if rerank else [],
            "w_similarity": W_SIMILARITY,
            "w_service": W_SERVICE if rerank else 0.0,
            "w_error": W_ERROR if rerank else 0.0,
            "provenance": list(filters.provenance),
            "provenance_count": len(filters.provenance),
            "filter_services": sorted(_tokens(filters.services)),
            "filter_service_count": len(filters.services),
            "exclude": sorted(exclude),
            "exclude_count": len(exclude),
            "k": k,
        }

        with self._session() as session:
            rows = session.execute(_SEARCH, params).mappings().all()

        hits = tuple(
            RetrievalHit(
                rank=position,
                incident=_to_incident(row),
                score=round(float(row["score"]), 6),
                similarity=round(float(row["similarity"]), 6),
                signals=_signals(row, rerank=rerank),
            )
            for position, row in enumerate(rows, start=1)
        )
        return RetrievalResult(
            version=RETRIEVAL_VERSION,
            provider=self._provider.identity,
            corpus_size=size - len(exclude),
            query_text=rendered,
            strong_match=bool(hits) and hits[0].score >= STRONG_MATCH_SCORE,
            hits=hits,
        )


def _signals(row, *, rerank: bool) -> tuple[MatchSignal, ...]:
    similarity = float(row["similarity"])
    signals = [
        MatchSignal(
            kind="semantic",
            detail=f"symptom similarity {similarity:.3f}",
            contribution=round(W_SIMILARITY * similarity, 4),
        )
    ]
    if rerank and row["service_hit"]:
        signals.append(
            MatchSignal(
                kind="service",
                detail="shared service terms",
                contribution=W_SERVICE,
                values=tuple(sorted(row["service_tokens"] or ())),
            )
        )
    if rerank and row["error_hit"]:
        signals.append(
            MatchSignal(
                kind="error_identifier",
                detail="shared error terms",
                contribution=W_ERROR,
                values=tuple(sorted(row["error_tokens"] or ())),
            )
        )
    return tuple(signals)


def _to_incident(row) -> HistoricalIncident:
    return HistoricalIncident(
        id=row["id"],
        title=row["title"],
        summary=row["summary"],
        services=tuple(row["services"] or ()),
        observed_errors=tuple(row["observed_errors"] or ()),
        occurred_at=row["occurred_at"],
        provenance=Provenance(row["provenance"]),
        outcome=HistoricalOutcome(
            root_cause=row["root_cause"],
            resolution_steps=tuple(row["resolution_steps"] or ()),
        ),
    )


def historical_row_values(
    incident: HistoricalIncident,
    *,
    indexed_text: str,
    vector: Sequence[float],
    provider_identity: str,
) -> dict:
    """One historical record, ready to upsert.

    Tokens are normalised here with the same function the in-memory index used, so the
    reranking terms mean exactly what they meant before they moved into SQL.
    """
    provider, _, model = provider_identity.partition(":")
    return {
        "id": incident.id,
        "source_record_id": incident.id,
        "provenance": incident.provenance.value,
        "title": incident.title,
        "summary": incident.summary,
        "services": list(incident.services),
        "observed_errors": list(incident.observed_errors),
        "occurred_at": incident.occurred_at,
        "root_cause": incident.outcome.root_cause,
        "resolution_steps": list(incident.outcome.resolution_steps),
        "indexed_text": indexed_text,
        "embedding": list(vector),
        "embedding_provider": provider or provider_identity,
        "embedding_model": model or provider_identity,
        "service_tokens": sorted(_tokens(incident.services)),
        "error_tokens": sorted(_tokens(incident.observed_errors)),
    }
