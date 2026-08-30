"""Online intake evaluation.

Eight authored cases, each a small window of tickets plus one arrival, asking what
incremental correlation does with the arrival. Deliberately small: this is acceptance and
regression evidence, and no meaningful claim can be built on eight cases.

It runs the correlation baseline directly rather than the HTTP endpoint, so the measured
thing is the grouping decision itself — the same `correlate()` that live intake replays.
"""

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from dataclasses import dataclass
from pathlib import Path

from app.correlation import CorrelationTicket, correlate
from app.correlation.semantic import SemanticSimilarity
from evaluation.models import CaseFailure, EvalReport, MetricSummary

CASES_FILE = "online_cases.json"


@dataclass(frozen=True)
class Outcome:
    case_id: str
    expected: str
    actual: str
    candidate_id: str | None
    detail: str
    # Hybrid only. "deterministic" means the fast path answered without embedding.
    path: str = "deterministic"
    semantic_invoked: bool = False

    @property
    def correct(self) -> bool:
        return self.expected == self.actual


def load_online_cases(directory: Path) -> tuple[dict, ...]:
    payload = json.loads((directory / CASES_FILE).read_text(encoding="utf-8"))
    return tuple(payload["records"])


def _ticket(row: dict) -> CorrelationTicket:
    return CorrelationTicket(
        id=row["id"],
        title=row["title"],
        description=row["description"],
        created_at=row["created_at"],
        service_id=row.get("service_id"),
        reported_by=None,
    )


def evaluate_pairwise_case(case: dict, model) -> Outcome:
    """What pairwise correlation does with this case's arriving ticket.

    Same gate, same cases, same metrics as the hybrid run — only the ambiguous-slice
    scorer differs, which is what makes the two comparable.
    """
    from app.correlation.hybrid import correlate_pairwise

    seed = [_ticket(row) for row in case["seed"]]
    arriving = _ticket(case["arriving"])
    before = correlate(seed) if seed else None
    existing = {t for c in before.candidates for t in c.ticket_ids} if before else set()

    outcome = correlate_pairwise([*seed, arriving], arriving.id, model)
    if not outcome.attached:
        return Outcome(
            case_id=case["id"],
            expected=case["expected"],
            actual="uncorrelated",
            candidate_id=None,
            detail=_hybrid_detail(outcome),
            path=outcome.path,
            semantic_invoked=outcome.semantic_invoked,
        )

    group = next(c for c in outcome.result.candidates if arriving.id in c.ticket_ids)
    joined = bool(existing & {t for t in group.ticket_ids if t != arriving.id})
    return Outcome(
        case_id=case["id"],
        expected=case["expected"],
        actual="attached" if joined else "created_candidate",
        candidate_id=group.id,
        detail=_hybrid_detail(outcome),
        path=outcome.path,
        semantic_invoked=outcome.semantic_invoked,
    )


def evaluate_hybrid_case(case: dict, similarity: SemanticSimilarity | None) -> Outcome:
    """What hybrid correlation does with this case's arriving ticket.

    Records the path taken as well as the answer, because "did it attach" and "did it need
    an embedding to decide" are separate questions and the second is most of the point.
    """
    from app.correlation.hybrid import correlate_hybrid

    seed = [_ticket(row) for row in case["seed"]]
    arriving = _ticket(case["arriving"])
    before = correlate(seed) if seed else None
    existing_members = (
        {t for c in before.candidates for t in c.ticket_ids} if before else set()
    )

    outcome = correlate_hybrid([*seed, arriving], arriving.id, similarity)

    if not outcome.attached:
        return Outcome(
            case_id=case["id"],
            expected=case["expected"],
            actual="uncorrelated",
            candidate_id=None,
            detail=_hybrid_detail(outcome),
            path=outcome.path,
            semantic_invoked=outcome.semantic_invoked,
        )

    group = next(
        c for c in outcome.result.candidates if arriving.id in c.ticket_ids
    )
    joined = bool(
        existing_members & {t for t in group.ticket_ids if t != arriving.id}
    )
    return Outcome(
        case_id=case["id"],
        expected=case["expected"],
        actual="attached" if joined else "created_candidate",
        candidate_id=group.id,
        detail=_hybrid_detail(outcome),
        path=outcome.path,
        semantic_invoked=outcome.semantic_invoked,
    )


def _hybrid_detail(outcome) -> str:
    if outcome.deterministic_attached:
        return f"deterministic fast path, score {outcome.deterministic_score}"
    if outcome.semantic_failed:
        return f"semantic fallback failed: {outcome.failure_reason}"
    if outcome.semantic_invoked:
        return (
            f"semantic fallback ran, score {outcome.semantic_score}"
            if outcome.semantic_score is not None
            else "semantic fallback ran, no attachment"
        )
    blocked = [
        reason
        for decision in outcome.fallback_decisions
        for reason in decision.blocking_reasons
    ]
    return (
        f"no embedding computed — {blocked[0]}"
        if blocked
        else "no candidate met the linkage thresholds"
    )


def evaluate_case(case: dict, similarity: SemanticSimilarity | None = None) -> Outcome:
    """What incremental correlation does with this case's arriving ticket."""
    seed = [_ticket(row) for row in case["seed"]]
    arriving = _ticket(case["arriving"])

    # The grouping the window had before the arrival, so "created a candidate" can be
    # told apart from "joined one that already existed".
    before = correlate(seed, similarity) if seed else None
    existing = (
        {candidate.id for candidate in before.candidates} if before else set()
    )

    after = correlate([*seed, arriving], similarity)
    group = next(
        (c for c in after.candidates if arriving.id in c.ticket_ids), None
    )

    if group is None:
        return Outcome(
            case_id=case["id"],
            expected=case["expected"],
            actual="uncorrelated",
            candidate_id=None,
            detail="no candidate met the linkage thresholds",
        )

    joined_existing = any(
        candidate_id in existing for candidate_id in (group.id,)
    ) or bool(
        existing
        and {t for t in group.ticket_ids if t != arriving.id}
        & {t for c in before.candidates for t in c.ticket_ids}
    )
    actual = "attached" if joined_existing else "created_candidate"
    return Outcome(
        case_id=case["id"],
        expected=case["expected"],
        actual=actual,
        candidate_id=group.id,
        detail=f"score {group.score}, {group.ticket_count} tickets, {group.confidence.value} confidence",
    )


def run_online_evaluation(
    directory: Path,
    similarity: SemanticSimilarity | None = None,
    *,
    hybrid: bool = False,
    pairwise=None,
) -> EvalReport:
    """Attachment behaviour over the authored online set.

    Three strategies, one dataset. Comparing them means running the same cases through
    each — a number from a different case set answers a different question.
    """
    from app.correlation.rules import HYBRID_CORRELATION_VERSION

    cases = load_online_cases(directory)
    if pairwise is not None:
        from app.correlation.rules import PAIRWISE_CORRELATION_VERSION

        outcomes = [evaluate_pairwise_case(case, pairwise) for case in cases]
        version = PAIRWISE_CORRELATION_VERSION
    elif hybrid:
        outcomes = [evaluate_hybrid_case(case, similarity) for case in cases]
        version = HYBRID_CORRELATION_VERSION
    else:
        outcomes = [evaluate_case(case, similarity) for case in cases]
        version = (
            "semantic-correlation-v1" if similarity else "deterministic-correlation-v1"
        )

    grouped = _rates(outcomes) + _slice_rates(cases, outcomes)
    if hybrid or pairwise is not None:
        grouped = grouped + _hybrid_rates(outcomes)
    failures = tuple(
        CaseFailure(
            case_id=outcome.case_id,
            metric="intake_outcome",
            expected=outcome.expected,
            predicted=outcome.actual,
            status=next(c["scenario"] for c in cases if c["id"] == outcome.case_id),
            explanation=outcome.detail,
            signals=(),
            text=next(c["note"] for c in cases if c["id"] == outcome.case_id),
        )
        for outcome in outcomes
        if not outcome.correct
    )

    return EvalReport(
        suite="intake",
        generated_at=datetime.now(UTC),
        version=version,
        case_count=len(cases),
        metrics=grouped,
        confusion=(),
        failures=failures,
        notes=(
            "Authored online-intake cases: a window of tickets plus one arrival.",
            "Eight cases. Acceptance and regression evidence, not a benchmark — no "
            "general claim should be drawn from a set this size.",
            "False attachment is the metric that matters most: inventing an incident "
            "that is not happening is worse than missing one that is.",
            f"Correlation version under test: {version}.",
            "Slices: `paraphrase` is the case deterministic correlation refuses — same "
            "incident, different words. `hard_conflict` is the opposite risk: semantic "
            "similarity would be high, and a deterministic conflict must win anyway.",
        ),
    )


def _slice_rates(
    cases: Sequence[dict], outcomes: Sequence[Outcome]
) -> tuple[MetricSummary, ...]:
    """Per-slice accuracy.

    The aggregate hides the thing worth knowing: a strategy can score well overall while
    failing every paraphrase, because paraphrases are a minority of any realistic set.
    """
    by_slice: dict[str, list[Outcome]] = {}
    labels = {case["id"]: case.get("slice", "baseline") for case in cases}
    for outcome in outcomes:
        by_slice.setdefault(labels[outcome.case_id], []).append(outcome)

    metrics = []
    for name in sorted(by_slice):
        rows = by_slice[name]
        correct = sum(1 for row in rows if row.correct)
        metrics.append(
            MetricSummary(
                name=f"{name}_slice_accuracy",
                correct=correct,
                total=len(rows),
                accuracy=round(correct / len(rows), 4) if rows else 0.0,
            )
        )
    return tuple(metrics)


def _hybrid_rates(outcomes: Sequence[Outcome]) -> tuple[MetricSummary, ...]:
    """What hybrid cost, and whether the fallback earned it."""
    invoked = [o for o in outcomes if o.semantic_invoked]
    # The fast path is "answered without computing an embedding" — which includes a
    # correct rejection, not only an attachment. Counting attachments alone understated
    # it badly, and the whole claim of hybrid is about how rarely embeddings are needed.
    fast = [o for o in outcomes if not o.semantic_invoked]
    fallback_correct = sum(1 for o in invoked if o.correct)
    fallback_false = sum(
        1 for o in invoked if o.expected == "uncorrelated" and o.actual != "uncorrelated"
    )

    def metric(name: str, correct: int, total: int) -> MetricSummary:
        return MetricSummary(
            name=name,
            correct=correct,
            total=total,
            accuracy=round(correct / total, 4) if total else 0.0,
        )

    return (
        # Lower is better: every invocation is an embedding somebody waited for.
        metric("semantic_fallback_invocation_rate", len(invoked), len(outcomes)),
        metric("deterministic_fast_path_rate", len(fast), len(outcomes)),
        metric("fallback_success_rate", fallback_correct, len(invoked)),
        # Lower is better.
        metric("fallback_false_attachment_rate", fallback_false, len(invoked)),
    )


def _rates(outcomes: Sequence[Outcome]) -> tuple[MetricSummary, ...]:
    should_group = [o for o in outcomes if o.expected in ("attached", "created_candidate")]
    should_not = [o for o in outcomes if o.expected == "uncorrelated"]
    grouped_wrongly = [o for o in should_not if o.actual != "uncorrelated"]
    missed = [o for o in should_group if o.actual == "uncorrelated"]

    def metric(name: str, correct: int, total: int) -> MetricSummary:
        return MetricSummary(
            name=name,
            correct=correct,
            total=total,
            accuracy=round(correct / total, 4) if total else 0.0,
        )

    return (
        metric(
            "correct_outcome_rate",
            sum(1 for o in outcomes if o.correct),
            len(outcomes),
        ),
        metric(
            "correct_attachment_rate",
            sum(1 for o in should_group if o.correct),
            len(should_group),
        ),
        # Lower is better. A false attachment asserts an incident that is not happening.
        metric("false_attachment_rate", len(grouped_wrongly), len(should_not)),
        # Lower is better. A miss leaves a real report on its own.
        metric("missed_attachment_rate", len(missed), len(should_group)),
        metric(
            "correct_uncorrelated_rate",
            sum(1 for o in should_not if o.correct),
            len(should_not),
        ),
        metric(
            "candidate_creation_accuracy",
            sum(
                1
                for o in outcomes
                if o.expected == "created_candidate" and o.correct
            ),
            sum(1 for o in outcomes if o.expected == "created_candidate"),
        ),
    )
