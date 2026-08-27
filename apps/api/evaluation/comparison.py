"""Comparing two correlation versions on identical inputs.

Both versions see the same tickets, the same labels, and the same metric definitions;
only the signal set differs. That is what makes the deltas below attributable to
semantic similarity rather than to two systems that happen to disagree.

The slices matter more than the aggregate. A single F1 number cannot tell you whether
embeddings recovered a real incident or merged two unrelated ones, and those two
outcomes call for opposite decisions.
"""

from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from app.correlation import CorrelationTicket, correlate
from app.correlation.models import CorrelationResult, PairwiseScore
from app.correlation.pairwise import Corpus, prepare, score_pair
from app.correlation.rules import CONTENT_LINK_MIN, LINK_THRESHOLD, TIME_LINK_MIN
from app.correlation.semantic import SemanticSimilarity
from evaluation.correlation import (
    load_golden_cases,
    load_golden_labels,
    run_golden,
    same_event,
)
from evaluation.models import EvalReport

# A pair the embedding considers clearly related, used to find guardrail saves.
STRONG_SEMANTIC = 0.5
MAX_EXAMPLES_PER_SLICE = 6


class ComparisonModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class MetricDelta(ComparisonModel):
    name: str
    baseline: float
    candidate: float
    delta: float


class SliceExample(ComparisonModel):
    """One pair, and why the two versions treated it differently."""

    kind: str
    ticket_a: str
    ticket_b: str
    explanation: str
    signals: tuple[str, ...]
    text: str | None = None


class VersionComparison(ComparisonModel):
    suite: str
    baseline_version: str
    candidate_version: str
    generated_at: datetime
    ticket_count: int
    metrics: tuple[MetricDelta, ...]
    slices: tuple[SliceExample, ...]
    notes: tuple[str, ...] = ()


def compare_reports(
    baseline: EvalReport, candidate: EvalReport
) -> tuple[MetricDelta, ...]:
    """Pairs up metrics by name. Lower is better for false-merge rate, so read that row
    with its sign in mind — the table reports the raw difference either way."""
    candidate_metrics = {metric.name: metric for metric in candidate.metrics}
    return tuple(
        MetricDelta(
            name=metric.name,
            baseline=metric.accuracy,
            candidate=candidate_metrics[metric.name].accuracy,
            delta=round(candidate_metrics[metric.name].accuracy - metric.accuracy, 4),
        )
        for metric in baseline.metrics
        if metric.name in candidate_metrics
    )


def _pairs(result: CorrelationResult) -> set[frozenset[str]]:
    return {
        frozenset(pair)
        for candidate in result.candidates
        for pair in combinations(candidate.ticket_ids, 2)
    }


def compare_golden(directory: Path, similarity: SemanticSimilarity) -> VersionComparison:
    tickets = load_golden_cases(directory)
    labels = load_golden_labels(directory)

    baseline_report = run_golden(directory)
    candidate_report = run_golden(directory, similarity)

    baseline_pairs = _pairs(correlate(tickets))
    candidate_pairs = _pairs(correlate(tickets, similarity))

    text = {
        ticket.id: f"{ticket.title} — {ticket.description}".strip(" —")
        for ticket in tickets
    }
    scored = _score_all_pairs(tickets, similarity)

    slices: list[SliceExample] = []
    for pair, score in scored.items():
        a, b = sorted(pair)
        truly_together = same_event(labels, a, b)
        in_baseline = pair in baseline_pairs
        in_candidate = pair in candidate_pairs
        semantic_value = _semantic_score(score)

        kind = None
        if truly_together and in_candidate and not in_baseline:
            kind = "semantic_win"
        elif not truly_together and in_candidate and not in_baseline:
            kind = "semantic_false_merge"
        elif truly_together and in_baseline and not in_candidate:
            kind = "semantic_regression"
        elif (
            not truly_together
            and not in_candidate
            and semantic_value >= STRONG_SEMANTIC
        ):
            # The embedding thought these belonged together and something stopped it.
            if score.time_score < TIME_LINK_MIN:
                kind = "time_guardrail"
            elif score.content_score < CONTENT_LINK_MIN or any(
                signal.score < 0 for signal in score.signals
            ):
                kind = "conflict_guardrail"

        if kind is None:
            continue
        slices.append(
            SliceExample(
                kind=kind,
                ticket_a=a,
                ticket_b=b,
                explanation=(
                    f"semantic {semantic_value}, blended {score.score}, "
                    f"content {score.content_score}, time {score.time_score}, "
                    f"{score.minutes_apart:.0f} min apart "
                    f"(link threshold {LINK_THRESHOLD})"
                ),
                signals=tuple(
                    f"{signal.component.value} {signal.score:+g}: {signal.detail}"
                    for signal in score.signals
                ),
                text=f"A: {text[a]}\nB: {text[b]}",
            )
        )

    return VersionComparison(
        suite="golden",
        baseline_version=baseline_report.version,
        candidate_version=candidate_report.version,
        generated_at=datetime.now(UTC),
        ticket_count=len(tickets),
        metrics=compare_reports(baseline_report, candidate_report),
        slices=tuple(_trim(slices)),
        notes=(
            "Both versions ran on the same authored tickets with the same labels, "
            "thresholds and candidate generation.",
            f"Semantic signal from {similarity.identity}.",
            "Guardrail slices are pairs the embedding rated similar that were kept "
            "apart anyway — by the time decay or by a service/issue conflict.",
        ),
    )


def _trim(slices: list[SliceExample]) -> list[SliceExample]:
    """Caps each slice so one noisy category cannot bury the others."""
    kept: list[SliceExample] = []
    counts: dict[str, int] = {}
    for example in sorted(slices, key=lambda s: (s.kind, s.ticket_a, s.ticket_b)):
        seen = counts.get(example.kind, 0)
        if seen >= MAX_EXAMPLES_PER_SLICE:
            continue
        counts[example.kind] = seen + 1
        kept.append(example)
    return kept


def _semantic_score(score: PairwiseScore) -> float:
    for signal in score.signals:
        if signal.component.value == "semantic":
            return signal.score
    return 0.0


def _score_all_pairs(
    tickets: tuple[CorrelationTicket, ...], similarity: SemanticSimilarity
) -> dict[frozenset[str], PairwiseScore]:
    """Every pair, scored with the semantic signal, for diagnosis only.

    Corpus statistics here cover the whole set rather than growing with arrivals, so
    these numbers are close to but not identical with the ones the incremental run used.
    They are for reading why a pair went the way it did, not for scoring.
    """
    similarity.prepare(tickets)
    features = {ticket.id: prepare(ticket) for ticket in tickets}
    corpus = Corpus()
    for ticket in tickets:
        corpus.observe(features[ticket.id].tokens)

    return {
        frozenset((a.id, b.id)): score_pair(
            features[a.id], features[b.id], corpus, similarity
        )
        for a, b in combinations(tickets, 2)
    }
