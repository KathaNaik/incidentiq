import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.correlation import CorrelationTicket, correlate
from app.schemas import EvalReportResponse
from evaluation.correlation import (
    _pair_stats,
    _same_event,
    load_golden_cases,
    load_golden_labels,
    run_golden,
    run_polaris,
)
from ingestion.errors import IngestionError

GOLDEN_DIR = get_settings().correlation_evals_dir
REPORT_PATH = GOLDEN_DIR / "golden-deterministic-correlation-v1.json"
START = datetime(2026, 8, 24, 9, 0, tzinfo=UTC)


def test_cases_and_labels_live_in_separate_files() -> None:
    cases = load_golden_cases(GOLDEN_DIR)
    labels = load_golden_labels(GOLDEN_DIR)

    assert 20 <= len(cases) <= 30
    assert {case.id for case in cases} == set(labels)
    # The ticket model has no field ground truth could ride in on.
    assert "event" not in json.dumps(cases[0].model_dump(mode="json"))


def test_unlabelled_case_is_rejected(tmp_path: Path) -> None:
    cases = json.loads((GOLDEN_DIR / "correlation_cases.json").read_text("utf-8"))
    labels = json.loads((GOLDEN_DIR / "correlation_labels.json").read_text("utf-8"))
    labels["records"] = labels["records"][:-1]
    (tmp_path / "correlation_cases.json").write_text(json.dumps(cases), "utf-8")
    (tmp_path / "correlation_labels.json").write_text(json.dumps(labels), "utf-8")

    with pytest.raises(IngestionError, match="unlabelled correlation cases"):
        run_golden(tmp_path)


def test_pair_statistics_count_only_shared_non_null_events() -> None:
    result = correlate(
        [
            CorrelationTicket(
                id=name,
                title="Warehouse sync stopped working",
                description="Connector sync stopped working, no rows arrive.",
                created_at=START + timedelta(minutes=offset),
                service_id="svc-connector",
            )
            for name, offset in (("A", 0), ("B", 5), ("C", 10))
        ]
    )
    assert result.candidates, "expected the three to group for this test to mean anything"

    perfect = _pair_stats(result, {"A": "E1", "B": "E1", "C": "E1"})
    assert perfect["precision"] == 1.0
    assert perfect["recall"] == 1.0

    mixed = _pair_stats(result, {"A": "E1", "B": "E1", "C": "E2"})
    assert mixed["true_positive"] == 1
    assert mixed["precision"] == pytest.approx(1 / 3)

    # Two tickets that belong to no incident are not "the same incident".
    assert not _same_event({"A": None, "B": None}, "A", "B")


def test_golden_report_prefers_precision_and_shows_its_failures() -> None:
    report = run_golden(GOLDEN_DIR)

    metrics = {metric.name: metric for metric in report.metrics}
    assert set(metrics) == {
        "pairwise_precision",
        "pairwise_recall",
        "pairwise_f1",
        "false_merge_rate",
        "singleton_accuracy",
        "event_recovery_rate",
    }
    # The baseline is tuned to avoid inventing incidents; if this ever drops, the
    # trade-off has silently changed.
    assert metrics["pairwise_precision"].accuracy >= 0.9
    assert metrics["false_merge_rate"].accuracy == 0.0
    for failure in report.failures:
        assert failure.signals, "a failure without its signals explains nothing"
        assert failure.text


def test_golden_report_is_reproducible() -> None:
    assert run_golden(GOLDEN_DIR).metrics == run_golden(GOLDEN_DIR).metrics


def test_committed_report_matches_the_api_schema() -> None:
    report = EvalReportResponse.model_validate(json.loads(REPORT_PATH.read_text("utf-8")))

    assert report.version == "deterministic-correlation-v1"


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", "utf-8")


@pytest.fixture
def fake_polaris(tmp_path: Path) -> Path:
    """An authored stand-in corpus: two tickets from one outage, one unrelated."""
    _write_jsonl(
        tmp_path / "features.jsonl",
        [
            {
                "ticket_id": f"T-{index}",
                "created_at": (START + timedelta(minutes=offset)).isoformat(),
                "channel": "email",
                "plan": "growth",
                "user_role": "admin",
                "reported_category": "connectors",
                "subject": subject,
                "body": body,
            }
            for index, (offset, subject, body) in enumerate(
                (
                    (0, "Warehouse sync stopped working", "No rows arrive at all."),
                    (
                        6,
                        "Connector sync stopped working",
                        "Sync stopped working, no rows arriving.",
                    ),
                    (900, "How do I rename a dashboard?", "Cannot find the setting."),
                ),
                start=1,
            )
        ],
    )
    _write_jsonl(
        tmp_path / "labels.jsonl",
        [
            {
                "ticket_id": ticket_id,
                "topic": "connectors",
                "ticket_type": "bug",
                "priority": "high",
                "routing": "tier2",
                "sentiment": "neutral",
                "event_id": event_id,
                "event_type": event_type,
            }
            for ticket_id, event_id, event_type in (
                ("T-1", "EVT-OUT", "outage"),
                ("T-2", "EVT-OUT", "outage"),
                ("T-3", None, None),
            )
        ],
    )
    return tmp_path


def test_external_benchmark_scores_against_hidden_events(fake_polaris: Path) -> None:
    report = run_polaris(fake_polaris)

    metrics = {metric.name: metric for metric in report.metrics}
    assert metrics["pairwise_precision"].accuracy == 1.0
    assert metrics["pairwise_recall"].accuracy == 1.0
    assert metrics["singleton_accuracy"].accuracy == 1.0


def test_external_benchmark_report_carries_no_ticket_text(fake_polaris: Path) -> None:
    report = run_polaris(fake_polaris)

    for failure in report.failures:
        assert failure.text is None
    assert "rename a dashboard" not in report.model_dump_json()


def test_launch_cohorts_are_not_counted_as_incidents(tmp_path: Path) -> None:
    """A six-month product launch is topical, not an incident. Grouping those tickets
    would be a false positive, so the primary metric must not reward it."""
    _write_jsonl(
        tmp_path / "features.jsonl",
        [
            {
                "ticket_id": f"L-{index}",
                "created_at": (START + timedelta(minutes=index * 5)).isoformat(),
                "channel": "email",
                "plan": "growth",
                "user_role": "admin",
                "reported_category": "connectors",
                "subject": "Warehouse sync stopped working",
                "body": "Connector sync stopped working, no rows arrive.",
            }
            for index in (1, 2)
        ],
    )
    _write_jsonl(
        tmp_path / "labels.jsonl",
        [
            {
                "ticket_id": f"L-{index}",
                "topic": "connectors",
                "ticket_type": "feature",
                "priority": "low",
                "routing": "tier1",
                "sentiment": "neutral",
                "event_id": "launch_widget",
                "event_type": "launch",
            }
            for index in (1, 2)
        ],
    )

    report = run_polaris(tmp_path)
    metrics = {metric.name: metric for metric in report.metrics}

    # The pair was grouped, but a launch is not an incident, so it counts against us.
    assert metrics["pairwise_precision"].accuracy == 0.0
    assert any("launch" in note for note in report.notes)


def test_correlation_endpoints(client: TestClient) -> None:
    response = client.get("/correlation/candidates")
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == "deterministic-correlation-v1"
    assert body["ticket_count"] > 0

    analyze = client.post(
        "/correlation/analyze",
        json={
            "tickets": [
                {
                    "id": "X1",
                    "title": "Warehouse sync stopped working",
                    "description": "Connector sync stopped working, no rows arrive.",
                    "created_at": "2026-08-24T09:00:00Z",
                    "service_id": "svc-connector",
                },
                {
                    "id": "X2",
                    "title": "Connector sync stopped working",
                    "description": "Sync stopped working, no rows arriving.",
                    "created_at": "2026-08-24T09:05:00Z",
                    "service_id": "svc-connector",
                },
            ]
        },
    )
    assert analyze.status_code == 200
    assert analyze.json()["candidates"][0]["ticket_ids"] == ["X1", "X2"]


def test_correlation_endpoint_refuses_ground_truth_in_the_payload(
    client: TestClient,
) -> None:
    response = client.post(
        "/correlation/analyze",
        json={
            "tickets": [
                {
                    "id": "X1",
                    "title": "Sync down",
                    "created_at": "2026-08-24T09:00:00Z",
                    "event_id": "EVT-1",
                }
            ]
        },
    )

    assert response.status_code == 422


def test_correlation_evaluation_is_served(client: TestClient) -> None:
    response = client.get("/evals/correlation")

    assert response.status_code == 200
    assert response.json()["version"] == "deterministic-correlation-v1"
