"""Correlation evaluation.

Inference runs over ticket text and timestamps alone. Ground truth is opened only
afterwards, by this module, to score what was already decided — the same rule the triage
suites follow, and the reason `CorrelationTicket` forbids unknown fields.

Metric choices worth stating:

- **Pairwise precision is the headline.** A false merge invents a major incident that is
  not happening; a missed correlation leaves a ticket exactly where it was. The
  thresholds are set accordingly, and false-merge rate is reported next to recall so the
  trade is never hidden.
- **"Same incident" means same *outage*.** Polaris also labels multi-month product
  launch cohorts with an `event_id`. Those tickets are topically related but they are not
  an incident, and grouping them would be a false positive in this product. The primary
  metric therefore counts only outage events as true groups; the report also carries the
  numbers under the looser definition so nothing is hidden by the choice.
"""

import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path

from app.correlation import CorrelationTicket, correlate
from app.correlation.models import CorrelationResult
from app.correlation.semantic import SemanticSimilarity
from app.correlation.pairwise import Corpus, prepare, score_pair
from evaluation.models import CaseFailure, ConfusionCell, EvalReport, MetricSummary
from ingestion.errors import IngestionError
from ingestion.io import read_jsonl
from ingestion.polaris.features import PolarisFeatureRecord
from ingestion.polaris.labels import PolarisLabelRecord

CASES_FILE = "correlation_cases.json"
LABELS_FILE = "correlation_labels.json"
FEATURES_FILE = "features.jsonl"
POLARIS_LABELS_FILE = "labels.jsonl"

INCIDENT_EVENT_TYPES = frozenset({"outage"})
MAX_REPORTED_FAILURES = 12


def load_golden_cases(directory: Path) -> tuple[CorrelationTicket, ...]:
    """The tickets, and nothing else — no expected grouping in sight."""
    payload = _payload(directory / CASES_FILE)
    return tuple(
        CorrelationTicket(
            id=record["id"],
            title=record["title"],
            description=record.get("description", ""),
            created_at=record["created_at"],
            reported_by=record.get("reported_by"),
        )
        for record in payload["records"]
    )


def load_golden_labels(directory: Path) -> dict[str, str | None]:
    payload = _payload(directory / LABELS_FILE)
    return {
        record["case_id"]: record["expected_event_id"] for record in payload["records"]
    }


def _payload(path: Path) -> dict:
    if not path.is_file():
        raise IngestionError(f"missing correlation golden-set file: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not payload.get("synthetic"):
        raise IngestionError(f"{path.name} is not marked synthetic")
    return payload


def run_golden(directory: Path, similarity: SemanticSimilarity | None = None) -> EvalReport:
    tickets = load_golden_cases(directory)
    result = correlate(tickets, similarity)

    labels = load_golden_labels(directory)
    missing = {ticket.id for ticket in tickets} - set(labels)
    if missing:
        raise IngestionError(f"unlabelled correlation cases: {sorted(missing)}")

    text = {
        ticket.id: f"{ticket.title} — {ticket.description}".strip(" —")
        for ticket in tickets
    }
    return _score(
        result,
        labels,
        tickets=tickets,
        suite="golden",
        text=text,
        notes=(
            "Authored for IncidentIQ; not derived from any external dataset.",
            "Development set: correlation weights and thresholds are tuned here.",
            "Precision is preferred over recall — a false merge is the costlier error.",
        )
        + _provider_note(similarity),
    )


def run_polaris(
    directory: Path,
    *,
    limit: int | None = None,
    similarity: SemanticSimilarity | None = None,
) -> EvalReport:
    features = list(read_jsonl(directory / FEATURES_FILE, PolarisFeatureRecord))
    if limit is not None:
        features = features[:limit]

    tickets = tuple(
        CorrelationTicket(
            id=feature.ticket_id,
            title=feature.subject,
            description=feature.body,
            created_at=feature.created_at,
        )
        for feature in features
    )
    # Inference is complete before a single label is read.
    result = correlate(tickets, similarity)

    in_scope = {ticket.id for ticket in tickets}
    records = [
        label
        for label in read_jsonl(directory / POLARIS_LABELS_FILE, PolarisLabelRecord)
        if label.ticket_id in in_scope
    ]

    incident_labels = {
        label.ticket_id: (
            label.event_id
            if label.event_id and label.event_type in INCIDENT_EVENT_TYPES
            else None
        )
        for label in records
    }
    any_event_labels = {label.ticket_id: label.event_id for label in records}

    report = _score(
        result,
        incident_labels,
        tickets=tickets,
        suite="polaris",
        text=None,
        notes=(
            "External held-out benchmark (CC BY-SA 4.0). Not committed, and no ticket "
            "text appears in this report.",
            "True grouping means same outage event. Polaris also labels multi-month "
            "product launch cohorts; those are topical, not incidents.",
            _looser_definition_note(result, any_event_labels),
        )
        + _provider_note(similarity),
    )
    return report


def _looser_definition_note(
    result: CorrelationResult, any_event_labels: dict[str, str | None]
) -> str:
    """Reports the same run scored with launch cohorts counted as true groups."""
    stats = _pair_stats(result, any_event_labels)
    return (
        "Counting every labelled event (launches included) as a true group instead: "
        f"precision {stats['precision']:.3f}, recall {stats['recall']:.3f}."
    )


def _pair_stats(result: CorrelationResult, labels: dict[str, str | None]) -> dict:
    predicted_pairs = [
        pair
        for candidate in result.candidates
        for pair in combinations(candidate.ticket_ids, 2)
    ]
    true_positive = sum(1 for a, b in predicted_pairs if same_event(labels, a, b))

    grouped = Counter(
        event for event in (labels.get(t) for t in labels) if event is not None
    )
    total_true_pairs = sum(count * (count - 1) // 2 for count in grouped.values())

    precision = true_positive / len(predicted_pairs) if predicted_pairs else 0.0
    recall = true_positive / total_true_pairs if total_true_pairs else 0.0
    f1 = (
        2 * precision * recall / (precision + recall) if precision + recall else 0.0
    )
    return {
        "predicted_pairs": len(predicted_pairs),
        "true_positive": true_positive,
        "total_true_pairs": total_true_pairs,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def same_event(labels: dict[str, str | None], a: str, b: str) -> bool:
    event_a = labels.get(a)
    return event_a is not None and event_a == labels.get(b)


def _score(
    result: CorrelationResult,
    labels: dict[str, str | None],
    *,
    tickets: tuple[CorrelationTicket, ...],
    suite: str,
    text: dict[str, str] | None,
    notes: tuple[str, ...],
) -> EvalReport:
    stats = _pair_stats(result, labels)

    # Group purity: a candidate is impure if it mixes two real events, or mixes event
    # tickets with tickets that belong to no incident at all.
    impure = [
        candidate
        for candidate in result.candidates
        if len({labels.get(t) for t in candidate.ticket_ids}) > 1
        or all(labels.get(t) is None for t in candidate.ticket_ids)
    ]
    group_count = len(result.candidates)

    # Of the tickets that belong to no incident, how many were left alone?
    grouped_ids = {t for candidate in result.candidates for t in candidate.ticket_ids}
    singletons = [t for t, event in labels.items() if event is None]
    correct_singletons = sum(1 for t in singletons if t not in grouped_ids)

    # An event counts as recovered when one pure candidate holds at least half of it.
    by_event: dict[str, set[str]] = defaultdict(set)
    for ticket_id, event in labels.items():
        if event is not None:
            by_event[event].add(ticket_id)
    multi = {e: ids for e, ids in by_event.items() if len(ids) > 1}
    recovered = sum(
        1
        for event, ids in multi.items()
        if any(
            set(candidate.ticket_ids) <= ids
            and len(candidate.ticket_ids) >= len(ids) / 2
            for candidate in result.candidates
        )
    )

    metrics = (
        MetricSummary(
            name="pairwise_precision",
            correct=stats["true_positive"],
            total=stats["predicted_pairs"],
            accuracy=round(stats["precision"], 4),
        ),
        MetricSummary(
            name="pairwise_recall",
            correct=stats["true_positive"],
            total=stats["total_true_pairs"],
            accuracy=round(stats["recall"], 4),
        ),
        MetricSummary(
            name="pairwise_f1",
            correct=stats["true_positive"],
            total=stats["predicted_pairs"] + stats["total_true_pairs"],
            accuracy=round(stats["f1"], 4),
        ),
        MetricSummary(
            name="false_merge_rate",
            correct=len(impure),
            total=group_count,
            accuracy=round(len(impure) / group_count, 4) if group_count else 0.0,
        ),
        MetricSummary(
            name="singleton_accuracy",
            correct=correct_singletons,
            total=len(singletons),
            accuracy=round(correct_singletons / len(singletons), 4) if singletons else 0.0,
        ),
        MetricSummary(
            name="event_recovery_rate",
            correct=recovered,
            total=len(multi),
            accuracy=round(recovered / len(multi), 4) if multi else 0.0,
        ),
    )

    failures = _false_merges(result, labels, text) + _missed_correlations(
        result, labels, tickets, text
    )

    confusion = tuple(
        ConfusionCell(
            expected=f"candidate:{candidate.id}",
            predicted=", ".join(
                sorted({labels.get(t) or "(no incident)" for t in candidate.ticket_ids})
            ),
            count=candidate.ticket_count,
        )
        for candidate in impure[:MAX_REPORTED_FAILURES]
    )

    return EvalReport(
        suite=suite,
        version=result.version,
        generated_at=datetime.now(UTC),
        case_count=result.ticket_count,
        metrics=metrics,
        confusion=confusion,
        failures=tuple(failures[: MAX_REPORTED_FAILURES * 2]),
        notes=notes,
    )


def _false_merges(
    result: CorrelationResult,
    labels: dict[str, str | None],
    text: dict[str, str] | None,
) -> list[CaseFailure]:
    """Pairs we grouped that do not share an incident, with the evidence we used."""
    failures: list[CaseFailure] = []
    for candidate in result.candidates:
        for pair in candidate.member_pairs:
            if same_event(labels, pair.ticket_a, pair.ticket_b):
                continue
            failures.append(
                CaseFailure(
                    case_id=f"{pair.ticket_a}+{pair.ticket_b}",
                    metric="false_merge",
                    expected="different incidents",
                    predicted=candidate.id,
                    status=candidate.confidence.value,
                    explanation=(
                        f"grouped at {pair.score} "
                        f"(content {pair.content_score}, time {pair.time_score})"
                    ),
                    signals=tuple(
                        f"{signal.component.value} {signal.score:+g}: {signal.detail}"
                        for signal in pair.signals
                    ),
                    text=_pair_text(text, pair.ticket_a, pair.ticket_b),
                )
            )
            if len(failures) >= MAX_REPORTED_FAILURES:
                return failures
    return failures


def _missed_correlations(
    result: CorrelationResult,
    labels: dict[str, str | None],
    tickets: tuple[CorrelationTicket, ...],
    text: dict[str, str] | None,
) -> list[CaseFailure]:
    """True pairs we left apart, rescored so the shortfall is visible.

    Diagnostic scores use corpus statistics over the whole evaluated set, while the run
    itself used only tickets seen so far. The components still show which evidence was
    missing, which is what this list is for.
    """
    predicted = {
        frozenset(pair)
        for candidate in result.candidates
        for pair in combinations(candidate.ticket_ids, 2)
    }
    by_event: dict[str, list[str]] = defaultdict(list)
    for ticket_id, event in labels.items():
        if event is not None:
            by_event[event].append(ticket_id)

    wanted: list[tuple[str, str]] = []
    for event in sorted(by_event):
        members = sorted(by_event[event])
        for a, b in combinations(members, 2):
            if frozenset((a, b)) not in predicted:
                wanted.append((a, b))
                break  # one example per event keeps the list readable
    wanted = wanted[:MAX_REPORTED_FAILURES]
    if not wanted:
        return []

    features = {ticket.id: prepare(ticket) for ticket in tickets}
    corpus = Corpus()
    for ticket in tickets:
        corpus.observe(features[ticket.id].tokens)

    failures = []
    for a, b in wanted:
        pair = score_pair(features[a], features[b], corpus)
        failures.append(
            CaseFailure(
                case_id=f"{a}+{b}",
                metric="missed_correlation",
                expected=labels[a],
                predicted=None,
                status="standalone",
                explanation=(
                    f"scored {pair.score} (content {pair.content_score}, "
                    f"time {pair.time_score}, {pair.minutes_apart:.0f} min apart)"
                ),
                signals=tuple(
                    f"{signal.component.value} {signal.score:+g}: {signal.detail}"
                    for signal in pair.signals
                ),
                text=_pair_text(text, a, b),
            )
        )
    return failures


def _pair_text(text: dict[str, str] | None, a: str, b: str) -> str | None:
    if text is None:
        return None
    return f"A: {text.get(a, '')}\nB: {text.get(b, '')}"


def _provider_note(similarity: SemanticSimilarity | None) -> tuple[str, ...]:
    if similarity is None:
        return ()
    return (f"Semantic signal from {similarity.identity}.",)
