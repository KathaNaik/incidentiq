import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.dependencies import (
    get_action_repository,
    get_investigation_store,
    get_repository,
)
from app.fixtures import load_dataset
from app.main import create_app
from app.repository import InMemoryRepository


@pytest.fixture(scope="session")
def northstar_dir() -> Path:
    """The real committed fixture dataset.

    Tests run against it deliberately: if the shipped fixtures stop satisfying the
    domain's invariants, that is a failure worth catching here.
    """
    return get_settings().fixtures_dir


@pytest.fixture
def repository(northstar_dir: Path) -> InMemoryRepository:
    return InMemoryRepository(load_dataset(northstar_dir))


@pytest.fixture
def client(repository: InMemoryRepository) -> Iterator[TestClient]:
    """An API client with the durable stores replaced by in-memory fakes.

    The fast suite must not need a database running. Contract-level behaviour is tested
    here; the guarantees that are genuinely PostgreSQL's — the partial unique index that
    prevents two concurrent investigations, the unique constraint that makes execution
    idempotent across a restart — are tested in `test_persistence_pg.py` against a real
    one, because a fake asserting them would be asserting itself.
    """
    from app.actions import ActionRepository
    from tests.fakes import FakeInvestigationRunStore

    app = create_app()
    app.dependency_overrides[get_repository] = lambda: repository
    actions = ActionRepository()
    runs = FakeInvestigationRunStore()
    app.dependency_overrides[get_action_repository] = lambda: actions
    app.dependency_overrides[get_investigation_store] = lambda: runs
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def dataset_writer(tmp_path: Path):
    """Writes a dataset directory seeded from the real fixtures, with edits applied.

    Used to prove the loader rejects malformed data without shipping broken fixtures.
    """

    def write(source: Path, **overrides: dict) -> Path:
        target = tmp_path / "dataset"
        target.mkdir(exist_ok=True)
        for name in (
            "services.json",
            "tickets.json",
            "incidents.json",
            "incident_tickets.json",
        ):
            payload = json.loads((source / name).read_text(encoding="utf-8"))
            payload.update(overrides.get(name, {}))
            (target / name).write_text(json.dumps(payload), encoding="utf-8")
        return target

    return write
