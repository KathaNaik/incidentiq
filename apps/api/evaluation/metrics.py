"""Metric computation.

Deliberately plain arithmetic: counts, accuracy, and a confusion table. Nothing here
should be clever enough to hide a mistake.
"""

from collections import Counter

from evaluation.models import ConfusionCell, MetricSummary

# What a declined prediction looks like in a confusion table.
ABSTAINED = "(abstained)"


def accuracy(
    name: str,
    pairs: list[tuple[str | None, str | None]],
    *,
    majority_baseline: float | None = None,
) -> MetricSummary:
    """Scores (expected, predicted) pairs.

    A prediction of None means the system declined. That counts as correct only when
    declining was the expected answer — abstaining is right when the ticket genuinely
    does not say, and wrong when the answer was there to be found.
    """
    correct = sum(1 for expected, predicted in pairs if expected == predicted)
    abstained = sum(1 for _, predicted in pairs if predicted is None)
    total = len(pairs)
    return MetricSummary(
        name=name,
        correct=correct,
        total=total,
        accuracy=round(correct / total, 4) if total else 0.0,
        abstained=abstained,
        majority_baseline=majority_baseline,
    )


def confusion(
    metric: str, pairs: list[tuple[str | None, str | None]]
) -> tuple[ConfusionCell, ...]:
    """Expected/predicted counts, worst offenders first."""
    counter = Counter(
        (expected or ABSTAINED, predicted or ABSTAINED)
        for expected, predicted in pairs
        if expected != predicted
    )
    cells = [
        ConfusionCell(expected=f"{metric}:{expected}", predicted=predicted, count=count)
        for (expected, predicted), count in counter.items()
    ]
    return tuple(
        sorted(cells, key=lambda cell: (-cell.count, cell.expected, cell.predicted))
    )


def majority_share(values: list[str]) -> float:
    """Share of the most common label — the accuracy of guessing it every time."""
    if not values:
        return 0.0
    return round(Counter(values).most_common(1)[0][1] / len(values), 4)
