"""The authored triage golden set.

Cases and labels live in separate files and are loaded by separate functions. Joining
them is the evaluator's job, after inference has already run — the same discipline the
Polaris ingestion enforces, applied to our own data so the habit holds everywhere.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from ingestion.errors import IngestionError

CASES_FILE = "triage_cases.json"
LABELS_FILE = "triage_labels.json"


@dataclass(frozen=True)
class GoldenCase:
    """Exactly what triage is allowed to see."""

    id: str
    title: str
    description: str


@dataclass(frozen=True)
class GoldenLabel:
    """Ground truth. `expected_service_id` of None means: decline to name a service."""

    case_id: str
    expected_service_id: str | None
    expected_issue_type: str
    expected_priority: str
    note: str = ""


def _records(path: Path) -> list[dict]:
    if not path.is_file():
        raise IngestionError(f"missing golden-set file: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not payload.get("synthetic"):
        raise IngestionError(f"{path.name} is not marked synthetic")
    return payload["records"]


def load_cases(directory: Path) -> tuple[GoldenCase, ...]:
    return tuple(
        GoldenCase(
            id=record["id"],
            title=record["title"],
            description=record.get("description", ""),
        )
        for record in _records(directory / CASES_FILE)
    )


def load_labels(directory: Path) -> dict[str, GoldenLabel]:
    labels = {}
    for record in _records(directory / LABELS_FILE):
        label = GoldenLabel(
            case_id=record["case_id"],
            expected_service_id=record["expected_service_id"],
            expected_issue_type=record["expected_issue_type"],
            expected_priority=record["expected_priority"],
            note=record.get("note", ""),
        )
        if label.case_id in labels:
            raise IngestionError(f"duplicate golden label for {label.case_id}")
        labels[label.case_id] = label
    return labels


def load_suite(directory: Path) -> tuple[tuple[GoldenCase, ...], dict[str, GoldenLabel]]:
    """Loads both halves and checks every case has exactly one label."""
    cases = load_cases(directory)
    labels = load_labels(directory)

    case_ids = {case.id for case in cases}
    if len(case_ids) != len(cases):
        raise IngestionError("duplicate golden case id")
    if case_ids != set(labels):
        missing = sorted(case_ids - set(labels))
        extra = sorted(set(labels) - case_ids)
        raise IngestionError(
            f"golden cases and labels do not align (unlabelled: {missing}, "
            f"orphan labels: {extra})"
        )
    return cases, labels
