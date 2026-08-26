import pytest

from ingestion.errors import IngestionError
from ingestion.itsm import normalize_row, normalize_rows
from tests.ingestion_fixtures import ITSM_ROW


def test_normalizes_a_source_row_into_the_ingestion_record() -> None:
    record = normalize_row(ITSM_ROW)

    assert record.source_id == "INC-TEST-0001"
    assert record.title.startswith("VPN client")
    assert record.priority == "high"
    assert record.applications == ("VPN Client", "Network Access Control")
    assert record.environment.region == "emea"
    assert len(record.correspondence) == 2
    assert record.observed_errors == ("IKE_SA rekey timeout", "tunnel teardown code 21")
    assert record.submitted_at.tzinfo is not None


def test_ground_truth_is_grouped_under_outcome() -> None:
    """Root cause and resolution are the answer key when this corpus scores root-cause
    reasoning. Grouping them means a future eval drops one attribute, not four fields."""
    record = normalize_row(ITSM_ROW)

    assert record.outcome.root_cause.startswith("One gateway")
    assert len(record.outcome.resolution_steps) == 2
    assert not hasattr(record, "root_cause")


def test_upstream_schema_change_fails_loudly() -> None:
    row = {key: value for key, value in ITSM_ROW.items() if key != "root_cause"}

    with pytest.raises(IngestionError, match="missing expected column"):
        normalize_row(row)


def test_record_without_a_root_cause_is_rejected() -> None:
    """A historical record with no cause cannot serve the purpose we ingest it for."""
    with pytest.raises(IngestionError, match="root_cause"):
        normalize_row({**ITSM_ROW, "root_cause": "   "})


def test_unparseable_timestamp_is_rejected() -> None:
    row = {**ITSM_ROW, "ticket": {**ITSM_ROW["ticket"], "submitted_at": "18/11/2025"}}

    with pytest.raises(IngestionError, match="could not parse timestamp"):
        normalize_row(row)


def test_duplicate_source_ids_are_rejected() -> None:
    with pytest.raises(IngestionError, match="duplicate source_id"):
        normalize_rows([ITSM_ROW, dict(ITSM_ROW)])


def test_normalization_is_deterministic() -> None:
    first = normalize_rows([ITSM_ROW])
    second = normalize_rows([ITSM_ROW])

    assert first[0].model_dump_json() == second[0].model_dump_json()
