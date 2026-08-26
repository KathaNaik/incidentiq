from datetime import UTC

import pytest

from ingestion.errors import IngestionError
from ingestion.polaris.normalize import split_row, split_rows, verify_alignment
from ingestion.sampling import sample_rows
from tests.ingestion_fixtures import POLARIS_ROW, polaris_row


def test_splits_a_source_row_into_feature_and_label_records() -> None:
    feature, label = split_row(POLARIS_ROW)

    assert feature.ticket_id == label.ticket_id == "TCK-TEST-01"
    assert feature.reported_category == "billing"
    assert label.topic == "dashboards"
    assert label.ticket_type == "bug"
    assert label.event_id == "EVT-TEST-SEV1"


def test_offsetless_source_timestamps_are_recorded_as_utc() -> None:
    feature, _ = split_row(POLARIS_ROW)

    assert feature.created_at.tzinfo is not None
    assert feature.created_at.utcoffset() == UTC.utcoffset(None)


def test_empty_subject_is_accepted_but_empty_body_is_not() -> None:
    """Chat-origin tickets in this corpus genuinely have no subject; a ticket with no
    body has nothing to retrieve or correlate on."""
    feature, _ = split_row(polaris_row("TCK-TEST-02", subject=""))
    assert feature.subject == ""

    with pytest.raises(IngestionError, match="expected non-empty text"):
        split_row(polaris_row("TCK-TEST-03", body=""))


def test_missing_ground_truth_column_fails_loudly() -> None:
    row = {key: value for key, value in POLARIS_ROW.items() if key != "event_id"}

    with pytest.raises(IngestionError, match="missing expected column"):
        split_row(row)


def test_null_and_empty_event_ids_collapse_to_none() -> None:
    _, from_null = split_row(polaris_row("TCK-TEST-04", event_id=None, event_type=None))
    _, from_empty = split_row(polaris_row("TCK-TEST-05", event_id="", event_type=""))

    assert from_null.event_id is None
    assert from_empty.event_id is None


def test_duplicate_ticket_ids_are_rejected() -> None:
    with pytest.raises(IngestionError, match="duplicate ticket_id"):
        split_rows([polaris_row("TCK-TEST-06"), polaris_row("TCK-TEST-06")])


def test_features_and_labels_stay_aligned() -> None:
    rows = [polaris_row(f"TCK-TEST-{index:02d}") for index in range(10, 20)]

    features, labels = split_rows(rows)

    assert [f.ticket_id for f in features] == [ls.ticket_id for ls in labels]


def test_misalignment_is_detected() -> None:
    features, labels = split_rows(
        [polaris_row("TCK-TEST-30"), polaris_row("TCK-TEST-31")]
    )

    with pytest.raises(IngestionError, match="misalignment"):
        verify_alignment(features, (labels[1], labels[0]))

    with pytest.raises(IngestionError, match="count mismatch"):
        verify_alignment(features, labels[:1])


def test_sampling_is_deterministic_and_keeps_the_two_views_together() -> None:
    rows = [polaris_row(f"TCK-TEST-{index:03d}") for index in range(100, 140)]

    first = sample_rows(rows, key=lambda row: row["ticket_id"], limit=5, seed=7)
    second = sample_rows(rows, key=lambda row: row["ticket_id"], limit=5, seed=7)
    other_seed = sample_rows(rows, key=lambda row: row["ticket_id"], limit=5, seed=8)

    assert [row["ticket_id"] for row in first] == [row["ticket_id"] for row in second]
    assert first != other_seed
    # Sampling happens before the split, so alignment is structural rather than lucky.
    features, labels = split_rows(first)
    assert len(features) == len(labels) == 5


def test_sampling_returns_everything_when_not_limited() -> None:
    rows = [polaris_row(f"TCK-TEST-{index:03d}") for index in range(200, 210)]

    assert sample_rows(rows, key=lambda row: row["ticket_id"], limit=None, seed=0) == rows
    assert sample_rows(rows, key=lambda row: row["ticket_id"], limit=99, seed=0) == rows
