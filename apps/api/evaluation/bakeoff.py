"""Phase 1 of the embedding bake-off: raw pair ordering.

M16 found that `bge-small` scored a pair that **must not merge** higher than genuine
paraphrases of the same incident. No threshold fixes an ordering problem — lowering the
floor to admit the paraphrase admits the false merge first. So before any correlation
strategy is run, this asks the only question that matters:

    Does this model rank same-incident pairs above operationally conflicting pairs?

The metric is **separation margin**: `min(positive) - max(dangerous negative)`. When it is
negative, no single threshold separates the slice, and threshold tuning is wasted effort.
Average cosine is deliberately not the headline — a model that scores everything higher
has not learned anything.

Pairs are drawn from the authored M16 online cases, not written for this experiment. A
pair set invented to make a model look good would measure nothing.
"""

import json
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from app.correlation.models import CorrelationTicket
from app.embeddings import embedding_text
from app.embeddings.registry import EmbeddingModelSpec


@dataclass(frozen=True)
class Pair:
    """Two tickets and what they are to each other."""

    id: str
    kind: str
    """`positive`, `dangerous_negative`, or `near_duplicate`."""

    left: CorrelationTicket
    right: CorrelationTicket
    note: str

    @property
    def is_positive(self) -> bool:
        return self.kind in ("positive", "near_duplicate")

    @property
    def is_dangerous(self) -> bool:
        return self.kind == "dangerous_negative"


@dataclass(frozen=True)
class ModelResult:
    """One model's behaviour over the pair set."""

    model_id: str
    model_name: str
    dimension: int
    scores: dict[str, float]
    pairs: tuple[Pair, ...]

    def _by(self, predicate) -> list[float]:
        return sorted(
            self.scores[pair.id] for pair in self.pairs if predicate(pair)
        )

    @property
    def positives(self) -> list[float]:
        return self._by(lambda pair: pair.kind == "positive")

    @property
    def dangerous(self) -> list[float]:
        return self._by(lambda pair: pair.is_dangerous)

    @property
    def near_duplicates(self) -> list[float]:
        return self._by(lambda pair: pair.kind == "near_duplicate")

    @property
    def separation_margin(self) -> float:
        """min(positive) − max(dangerous). Negative means no threshold separates them.

        Positives here are the *genuine paraphrases*, not the near-duplicates. A model
        that only separates near-duplicates from everything has not solved the problem
        M16 ran into — near-duplicates already attach deterministically.
        """
        if not self.positives or not self.dangerous:
            return 0.0
        return round(min(self.positives) - max(self.dangerous), 4)

    @property
    def ordering_accuracy(self) -> tuple[int, int]:
        """Over every (positive, dangerous) pairing, how often is the positive higher?"""
        wins = total = 0
        for positive in self.positives:
            for negative in self.dangerous:
                total += 1
                wins += positive > negative
        return wins, total

    def summary(self) -> dict:
        wins, total = self.ordering_accuracy
        return {
            "model_id": self.model_id,
            "model_name": self.model_name,
            "dimension": self.dimension,
            "positive_min": min(self.positives) if self.positives else None,
            "positive_max": max(self.positives) if self.positives else None,
            "positive_mean": round(statistics.mean(self.positives), 4)
            if self.positives
            else None,
            "positive_median": round(statistics.median(self.positives), 4)
            if self.positives
            else None,
            "dangerous_min": min(self.dangerous) if self.dangerous else None,
            "dangerous_max": max(self.dangerous) if self.dangerous else None,
            "dangerous_mean": round(statistics.mean(self.dangerous), 4)
            if self.dangerous
            else None,
            "dangerous_median": round(statistics.median(self.dangerous), 4)
            if self.dangerous
            else None,
            "near_duplicate_min": min(self.near_duplicates)
            if self.near_duplicates
            else None,
            "near_duplicate_max": max(self.near_duplicates)
            if self.near_duplicates
            else None,
            "separation_margin": self.separation_margin,
            "ordering_accuracy": round(wins / total, 4) if total else None,
            "ordering_wins": wins,
            "ordering_comparisons": total,
            "separable": self.separation_margin > 0,
            "scores": dict(sorted(self.scores.items())),
        }


def _ticket(row: dict) -> CorrelationTicket:
    return CorrelationTicket(
        id=row["id"],
        title=row["title"],
        description=row["description"],
        created_at=row["created_at"],
        service_id=row.get("service_id"),
        reported_by=None,
    )


def build_pairs(directory: Path) -> tuple[Pair, ...]:
    """The pair set, assembled from the authored online cases.

    Each case already contains a seed group and an arriving ticket with a known expected
    outcome; that is exactly a labelled pair. Nothing is written specially for this.
    """
    payload = json.loads((directory / "online_cases.json").read_text(encoding="utf-8"))
    cases = {case["id"]: case for case in payload["records"]}

    pairs: list[Pair] = []

    def add(case_id: str, kind: str, note: str, seed_index: int = 0) -> None:
        case = cases[case_id]
        seed = _ticket(case["seed"][seed_index])
        arriving = _ticket(case["arriving"])
        pairs.append(
            Pair(
                id=f"{case_id}:{seed.id}",
                kind=kind,
                left=arriving,
                right=seed,
                note=note,
            )
        )

    # Positives: genuine same-incident pairs the deterministic baseline refused.
    add("PR01", "positive", "true paraphrase, auth incident", 0)
    add("PR01", "positive", "true paraphrase, auth incident, second member", 1)
    add("PR02", "positive", "true paraphrase, connector incident", 0)
    add("PR02", "positive", "true paraphrase, connector incident, second member", 1)

    # Near-duplicates: what already attaches deterministically. Included as a sanity
    # anchor — a model that cannot separate these is broken, not merely unhelpful.
    add("ON08", "near_duplicate", "near-verbatim duplicate report", 0)

    # Dangerous negatives: pairs that must never merge.
    add("PR03", "dangerous_negative", "permissions request against an availability incident", 0)
    add("PR04", "dangerous_negative", "conflicting error identifiers on one service", 0)
    add("PR04", "dangerous_negative", "conflicting error identifiers, second member", 1)
    add("PR06", "dangerous_negative", "unrelated service and problem", 0)
    add("ON03", "dangerous_negative", "shared vocabulary, different service and failure", 0)
    add("ON07", "dangerous_negative", "same service, unrelated problem", 0)

    return tuple(pairs)


def score_pairs(spec: EmbeddingModelSpec, pairs: Sequence[Pair], cache_dir: Path | None) -> ModelResult:
    """Raw cosine for every pair under one model.

    The embedding text is `embedding_text` unchanged — the same canonical input M16 used.
    Changing it would make this a text experiment rather than a model experiment.
    """
    from app.correlation.semantic import cosine_similarity
    from app.embeddings import EmbeddingCache, LocalEmbeddingProvider

    provider = LocalEmbeddingProvider(spec.model_name)
    cache = EmbeddingCache(cache_dir, provider) if cache_dir else None

    texts: dict[str, str] = {}
    for pair in pairs:
        for ticket in (pair.left, pair.right):
            texts[ticket.id] = embedding_text(ticket)

    vectors: dict[str, tuple[float, ...]] = {}
    pending = {}
    for ticket_id, text in texts.items():
        cached = cache.get(text) if cache else None
        if cached is not None:
            vectors[ticket_id] = cached
        else:
            pending[ticket_id] = text

    if pending:
        ids = list(pending)
        computed = provider.embed_many([pending[i] for i in ids])
        for ticket_id, vector in zip(ids, computed, strict=True):
            vectors[ticket_id] = vector
            if cache:
                cache.put(pending[ticket_id], vector)
        if cache:
            cache.save()

    scores = {
        pair.id: round(
            cosine_similarity(vectors[pair.left.id], vectors[pair.right.id]), 4
        )
        for pair in pairs
    }
    return ModelResult(
        model_id=spec.id,
        model_name=spec.model_name,
        dimension=spec.dimension,
        scores=scores,
        pairs=tuple(pairs),
    )
