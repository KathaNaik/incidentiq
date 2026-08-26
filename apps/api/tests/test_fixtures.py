from pathlib import Path

import pytest

from app.fixtures import FixtureError, load_dataset


def test_shipped_northstar_dataset_loads(northstar_dir: Path) -> None:
    dataset = load_dataset(northstar_dir)

    assert dataset.name == "northstar-cloud"
    assert len(dataset.services) == 3
    assert len(dataset.incidents) == 2
    assert 8 <= len(dataset.tickets) <= 12


def test_dataset_not_marked_synthetic_is_rejected(
    northstar_dir: Path, dataset_writer
) -> None:
    """An unlabelled dataset must not be servable — the UI presents whatever loads here
    as the application's data."""
    corrupted = dataset_writer(northstar_dir, **{"tickets.json": {"synthetic": False}})

    with pytest.raises(FixtureError, match="not marked synthetic"):
        load_dataset(corrupted)


def test_ticket_referencing_unknown_service_is_rejected(
    northstar_dir: Path, dataset_writer
) -> None:
    corrupted = dataset_writer(
        northstar_dir,
        **{
            "tickets.json": {
                "records": [
                    {
                        "id": "TKT-9001",
                        "title": "Orphan",
                        "description": "",
                        "created_at": "2026-08-25T10:00:00Z",
                        "status": "open",
                        "reported_by": "tier1-support",
                        "service_id": "svc-does-not-exist",
                    }
                ]
            }
        },
    )

    with pytest.raises(FixtureError, match="unknown service"):
        load_dataset(corrupted)


def test_ticket_linked_to_two_incidents_is_rejected(
    northstar_dir: Path, dataset_writer
) -> None:
    corrupted = dataset_writer(
        northstar_dir,
        **{
            "incident_tickets.json": {
                "records": [
                    {"incident_id": "INC-1042", "ticket_id": "TKT-4101"},
                    {"incident_id": "INC-1043", "ticket_id": "TKT-4101"},
                ]
            }
        },
    )

    with pytest.raises(FixtureError, match="more than one incident"):
        load_dataset(corrupted)


def test_naive_timestamp_is_rejected(northstar_dir: Path, dataset_writer) -> None:
    """Records are ordered by time across the whole dataset, so an offset-less timestamp
    is ambiguous rather than merely untidy."""
    corrupted = dataset_writer(
        northstar_dir,
        **{
            "incidents.json": {
                "records": [
                    {
                        "id": "INC-9001",
                        "title": "No offset",
                        "status": "investigating",
                        "severity": "sev3",
                        "detected_at": "2026-08-25T10:00:00",
                        "created_at": "2026-08-25T10:05:00Z",
                        "affected_service_ids": ["svc-auth"],
                    }
                ]
            }
        },
    )

    with pytest.raises(FixtureError, match="timezone offset"):
        load_dataset(corrupted)


def test_missing_file_is_reported_clearly(tmp_path: Path) -> None:
    with pytest.raises(FixtureError, match="missing fixture file"):
        load_dataset(tmp_path)
