"""Shared FastAPI dependencies."""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from typing import TYPE_CHECKING

from app.config import get_settings
from app.fixtures import load_dataset
from app.repository import InMemoryRepository, Repository

if TYPE_CHECKING:
    from app.intake import TicketIntake
    from app.db.action_store import SqlActionRepository
    from app.db.investigation_store import InvestigationRunStore
    from app.db.retrieval_store import PgVectorHistoricalIndex


@lru_cache
def get_repository() -> Repository:
    """The process-wide repository.

    Tickets come from PostgreSQL since M15 — they arrive at runtime, so they are runtime
    state. Services and incidents stay fixture-backed: nothing creates a service at
    runtime, and a mutable table for authored configuration would only invite drift.

    Falls back to the pure in-memory repository when no database is configured, so the
    read-only parts of the product still run without one.
    """
    from app.db.engine import DatabaseNotConfiguredError

    dataset = load_dataset(get_settings().fixtures_dir)
    try:
        from app.db.ticket_store import SqlRepository

        return SqlRepository(dataset)
    except DatabaseNotConfiguredError:
        return InMemoryRepository(dataset)


@lru_cache
def get_intake() -> "TicketIntake":
    """Runtime ticket intake."""
    from app.intake import TicketIntake

    dataset = load_dataset(get_settings().fixtures_dir)
    return TicketIntake(
        known_services=frozenset(service.id for service in dataset.services)
    )


RepositoryDep = Annotated[Repository, Depends(get_repository)]
IntakeDep = Annotated["TicketIntake", Depends(get_intake)]


@lru_cache
def get_retrieval_index() -> "PgVectorHistoricalIndex":
    """Historical retrieval, backed by PostgreSQL and pgvector.

    Nothing is built here. The vectors are already in the database, so process start
    costs one embedding-model load rather than a corpus index rebuild, and a restart
    costs nothing at all.

    The in-memory `HistoricalIndex` remains in `app.retrieval.index` as a reference
    implementation for regression comparison and offline evaluation. It is not reachable
    from any request path — there is one runtime retrieval implementation, not two that
    something might choose between.
    """
    from app.db.retrieval_store import PgVectorHistoricalIndex
    from app.embeddings import LocalEmbeddingProvider

    return PgVectorHistoricalIndex(LocalEmbeddingProvider())


RetrievalIndexDep = Annotated["PgVectorHistoricalIndex", Depends(get_retrieval_index)]


@lru_cache
def get_action_repository() -> "SqlActionRepository":
    """The durable action store.

    Actions, approvals, execution results and audit events live in PostgreSQL, so they
    survive a restart — and so does execution idempotency, which was already derived from
    persisted status rather than an in-memory flag.
    """
    from app.db.action_store import SqlActionRepository

    return SqlActionRepository()


ActionRepositoryDep = Annotated["SqlActionRepository", Depends(get_action_repository)]


@lru_cache
def get_investigation_store() -> "InvestigationRunStore":
    """Durable investigation runs."""
    from app.db.investigation_store import InvestigationRunStore

    return InvestigationRunStore()


InvestigationStoreDep = Annotated[
    "InvestigationRunStore", Depends(get_investigation_store)
]
