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
    directory: Path, similarity: SemanticSimilarity | None = None
) -> EvalReport:
    """Attachment behaviour over the authored online set."""
    cases = load_online_cases(directory)
    outcomes = [evaluate_case(case, similarity) for case in cases]
    version = "semantic-correlation-v1" if similarity else "deterministic-correlation-v1"

    grouped = _rates(outcomes)
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
        ),
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
