"""Triage evaluation suites.

Two suites, for two different jobs:

- **golden** — 25 cases we authored, with expected service, issue type, and priority.
  This is the development set: rules are iterated against it.
- **polaris** — the external benchmark. Priority only, and treated as held-out. The
  triage system sees the feature view; labels are opened afterwards, by the evaluator.

In both, inference runs before any label is read. The predictions are computed from case
text alone, then joined to ground truth by id.
"""

from datetime import UTC, datetime
from pathlib import Path

from app.triage import TRIAGE_VERSION, TriageInput, triage
from app.triage.models import TriageResult
from evaluation.golden import load_suite
from evaluation.metrics import accuracy, confusion, majority_share
from evaluation.models import CaseFailure, EvalReport
from ingestion.io import read_jsonl
from ingestion.polaris.features import PolarisFeatureRecord
from ingestion.polaris.labels import PolarisLabelRecord
from ingestion.sampling import sample_rows

FEATURES_FILE = "features.jsonl"
LABELS_FILE = "labels.jsonl"


def run_golden(directory: Path) -> EvalReport:
    cases, labels = load_suite(directory)

    # Inference first, on text only.
    predictions = {
        case.id: triage(
            TriageInput(
                ticket_id=case.id, title=case.title, description=case.description
            )
        )
        for case in cases
    }

    pairs_by_metric: dict[str, list[tuple[str | None, str | None]]] = {
        "service": [],
        "issue_type": [],
        "priority": [],
    }
    failures: list[CaseFailure] = []

    for case in cases:
        label = labels[case.id]
        result = predictions[case.id]
        text = f"{case.title} — {case.description}".strip(" —")

        for metric, expected, prediction in (
            ("service", label.expected_service_id, result.service),
            ("issue_type", label.expected_issue_type, result.issue_type),
            ("priority", label.expected_priority, result.priority),
        ):
            pairs_by_metric[metric].append((expected, prediction.value))

            if expected != prediction.value:
                failures.append(
                    CaseFailure(
                        case_id=case.id,
                        metric=metric,
                        expected=expected,
                        predicted=prediction.value,
                        status=prediction.status.value,
                        explanation=prediction.explanation,
                        signals=_signal_summary(result, metric),
                        text=text,
                    )
                )

    return EvalReport(
        suite="golden",
        version=TRIAGE_VERSION,
        generated_at=datetime.now(UTC),
        case_count=len(cases),
        metrics=tuple(
            accuracy(metric, pairs) for metric, pairs in pairs_by_metric.items()
        ),
        confusion=tuple(
            cell
            for metric, pairs in pairs_by_metric.items()
            for cell in confusion(metric, pairs)
        ),
        failures=tuple(failures),
        notes=(
            "Authored by us for IncidentIQ; not derived from any external dataset.",
            "Development set: triage rules are iterated against these cases.",
            "Expected service null means a correct system declines to name one.",
        ),
    )


def run_polaris(
    directory: Path, *, limit: int | None = None, seed: int = 0
) -> EvalReport:
    """Scores priority against the external benchmark.

    Only `priority` is measured. Polaris `topic` has no authentication value and six of
    its eight values have no Northstar equivalent, so mapping it onto our service
    taxonomy would produce a number that looks like service accuracy without being one.
    """
    features = list(read_jsonl(directory / FEATURES_FILE, PolarisFeatureRecord))
    if limit is not None:
        chosen = {
            row["ticket_id"]
            for row in sample_rows(
                [{"ticket_id": feature.ticket_id} for feature in features],
                key=lambda row: str(row["ticket_id"]),
                limit=limit,
                seed=seed,
            )
        }
        features = [feature for feature in features if feature.ticket_id in chosen]

    # Inference happens here, with no label in scope.
    predictions: dict[str, TriageResult] = {
        feature.ticket_id: triage(
            TriageInput(
                ticket_id=feature.ticket_id,
                title=feature.subject,
                description=feature.body,
            )
        )
        for feature in features
    }

    # Only now are labels opened.
    labels = {
        label.ticket_id: label
        for label in read_jsonl(directory / LABELS_FILE, PolarisLabelRecord)
        if label.ticket_id in predictions
    }

    pairs: list[tuple[str | None, str | None]] = []
    failures: list[CaseFailure] = []
    for ticket_id, result in predictions.items():
        label = labels.get(ticket_id)
        if label is None:
            continue
        pairs.append((label.priority, result.priority.value))
        if label.priority != result.priority.value and len(failures) < 40:
            failures.append(
                CaseFailure(
                    case_id=ticket_id,
                    metric="priority",
                    expected=label.priority,
                    predicted=result.priority.value,
                    status=result.priority.status.value,
                    explanation=result.priority.explanation,
                    signals=_signal_summary(result, "priority"),
                    # No ticket text: this corpus is CC BY-SA and the report must not
                    # become a partial copy of it.
                    text=None,
                )
            )

    return EvalReport(
        suite="polaris",
        version=TRIAGE_VERSION,
        generated_at=datetime.now(UTC),
        case_count=len(pairs),
        metrics=(
            accuracy(
                "priority",
                pairs,
                majority_baseline=majority_share(
                    [label.priority for label in labels.values()]
                ),
            ),
        ),
        confusion=confusion("priority", pairs),
        failures=tuple(failures),
        notes=(
            "External held-out benchmark (CC BY-SA 4.0). Not committed, and no source "
            "text appears in this report.",
            "Priority only: Polaris topic does not map onto the Northstar service "
            "taxonomy without inventing a correspondence that is not there.",
            "Failure list truncated to the first 40 cases.",
        ),
    )


def _signal_summary(result: TriageResult, metric: str) -> tuple[str, ...]:
    """The matched rules behind one prediction, as readable strings."""
    prefix = "priority" if metric == "priority" else f"{metric}:"
    return tuple(
        f"{signal.signal_type.value} {signal.matched_text!r} "
        f"({signal.weight:+g}, {signal.source_field}) -> {signal.target}"
        for signal in result.signals
        if signal.target.startswith(prefix)
    )
