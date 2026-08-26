import json
from pathlib import Path

import pytest

from app.config import get_settings
from app.schemas import EvalReportResponse
from evaluation.golden import load_cases, load_labels, load_suite
from evaluation.metrics import accuracy, confusion, majority_share
from evaluation.runner import run_golden, run_polaris
from ingestion.errors import IngestionError

GOLDEN_DIR = get_settings().fixtures_dir.parents[1] / "evals" / "golden"
REPORT_PATH = get_settings().evals_dir / "golden-deterministic-v1.json"


def test_golden_cases_and_labels_load_from_separate_files() -> None:
    """Input and ground truth are never one object, so inference cannot see an answer
    by reaching through the case it was handed."""
    cases = load_cases(GOLDEN_DIR)
    labels = load_labels(GOLDEN_DIR)

    assert 20 <= len(cases) <= 30
    assert {case.id for case in cases} == set(labels)
    case_fields = set(vars(cases[0]))
    assert not case_fields & {"expected_service_id", "expected_priority"}


def test_unlabelled_case_is_rejected(tmp_path: Path) -> None:
    cases = json.loads((GOLDEN_DIR / "triage_cases.json").read_text("utf-8"))
    labels = json.loads((GOLDEN_DIR / "triage_labels.json").read_text("utf-8"))
    labels["records"] = labels["records"][:-1]
    (tmp_path / "triage_cases.json").write_text(json.dumps(cases), "utf-8")
    (tmp_path / "triage_labels.json").write_text(json.dumps(labels), "utf-8")

    with pytest.raises(IngestionError, match="do not align"):
        load_suite(tmp_path)


def test_accuracy_counts_abstention_separately_from_being_wrong() -> None:
    summary = accuracy(
        "service", [("svc-auth", "svc-auth"), ("svc-auth", None), (None, None)]
    )

    assert summary.correct == 2  # the declined-and-expected-to-decline case counts
    assert summary.abstained == 2
    assert summary.total == 3
    assert summary.accuracy == round(2 / 3, 4)


def test_confusion_reports_only_mistakes_worst_first() -> None:
    cells = confusion(
        "priority",
        [("low", "medium"), ("low", "medium"), ("high", "low"), ("low", "low")],
    )

    assert [(cell.expected, cell.predicted, cell.count) for cell in cells] == [
        ("priority:low", "medium", 2),
        ("priority:high", "low", 1),
    ]


def test_majority_share_is_the_number_to_beat() -> None:
    assert majority_share(["low", "low", "low", "high"]) == 0.75
    assert majority_share([]) == 0.0


def test_golden_run_produces_metrics_and_inspectable_failures() -> None:
    report = run_golden(GOLDEN_DIR)

    assert report.suite == "golden"
    assert {metric.name for metric in report.metrics} == {
        "service",
        "issue_type",
        "priority",
    }
    for failure in report.failures:
        assert failure.expected != failure.predicted
        assert failure.explanation
        # Our own cases, so the text is safe to include — and needed to read a failure.
        assert failure.text


def test_golden_run_is_reproducible() -> None:
    first = run_golden(GOLDEN_DIR)
    second = run_golden(GOLDEN_DIR)

    assert first.metrics == second.metrics
    assert first.failures == second.failures


def test_committed_artifact_matches_the_api_schema() -> None:
    """The API declares its own view of the artifact rather than importing the
    evaluation package. This is what stops the two drifting apart."""
    report = EvalReportResponse.model_validate(
        json.loads(REPORT_PATH.read_text("utf-8"))
    )

    assert report.version == "deterministic-v1"
    assert report.case_count > 0


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", "utf-8")


@pytest.fixture
def fake_polaris(tmp_path: Path) -> Path:
    """A stand-in corpus we authored, so the test needs no download."""
    _write_jsonl(
        tmp_path / "features.jsonl",
        [
            {
                "ticket_id": "T-1",
                "created_at": "2024-05-01T10:00:00Z",
                "channel": "email",
                "plan": "growth",
                "user_role": "admin",
                "reported_category": "connectors",
                "subject": "Connector is down for all customers",
                "body": "Every sync is unavailable and this is customer facing.",
            },
            {
                "ticket_id": "T-2",
                "created_at": "2024-05-01T11:00:00Z",
                "channel": "chat",
                "plan": "starter",
                "user_role": "analyst",
                "reported_category": "dashboards",
                "subject": "",
                "body": "How do I rename a dashboard?",
            },
        ],
    )
    _write_jsonl(
        tmp_path / "labels.jsonl",
        [
            {
                "ticket_id": "T-1",
                "topic": "connectors",
                "ticket_type": "outage",
                "priority": "critical",
                "routing": "tier2",
                "sentiment": "angry",
                "event_id": "EVT-1",
                "event_type": "outage",
            },
            {
                "ticket_id": "T-2",
                "topic": "dashboards",
                "ticket_type": "how_to",
                "priority": "high",
                "routing": "tier1",
                "sentiment": "neutral",
                "event_id": None,
                "event_type": None,
            },
        ],
    )
    return tmp_path


def test_external_benchmark_scores_priority_against_a_majority_reference(
    fake_polaris: Path,
) -> None:
    report = run_polaris(fake_polaris)

    assert report.case_count == 2
    (metric,) = report.metrics
    assert metric.name == "priority"
    assert metric.majority_baseline is not None


def test_external_benchmark_report_carries_no_source_text(fake_polaris: Path) -> None:
    """The report is an artifact about our system, not a partial copy of a licensed
    corpus. T-2 is deliberately a failure, so there is something to check."""
    report = run_polaris(fake_polaris)

    assert report.failures, "expected at least one failure to inspect"
    for failure in report.failures:
        assert failure.text is None
    serialized = report.model_dump_json()
    assert "How do I rename a dashboard" not in serialized


def test_external_benchmark_never_scores_a_ticket_against_another_ticket(
    fake_polaris: Path,
) -> None:
    report = run_polaris(fake_polaris)
    failures = {failure.case_id: failure for failure in report.failures}

    # T-2 is a how-to labelled high upstream; our baseline says low. The pairing must
    # be by id, not by position.
    assert failures["T-2"].expected == "high"
