"""Shared FastAPI dependencies."""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from typing import TYPE_CHECKING

from app.config import get_settings
from app.fixtures import load_dataset
from app.repository import InMemoryRepository, Repository

if TYPE_CHECKING:
    from app.actions import ActionRepository
    from app.retrieval import HistoricalIndex


@lru_cache
def get_repository() -> Repository:
    """The process-wide repository.

    Fixtures are read once at first use; the dataset is immutable, so there is nothing
    to invalidate. Tests substitute their own repository with
    `app.dependency_overrides[get_repository]`.
    """
    return InMemoryRepository(load_dataset(get_settings().fixtures_dir))


RepositoryDep = Annotated[Repository, Depends(get_repository)]


@lru_cache
def get_retrieval_index() -> "HistoricalIndex":
    """The historical index, built once per process.

    Building embeds the corpus, which is slow the first time and fast afterwards because
    the vectors are cached on disk. Tests substitute a stub-backed index through
    `app.dependency_overrides`.
    """
    from app.embeddings import EmbeddingCache, LocalEmbeddingProvider
    from app.retrieval import HistoricalIndex, load_corpus

    settings = get_settings()
    provider = LocalEmbeddingProvider()
    index = HistoricalIndex(
        provider, EmbeddingCache(settings.embeddings_cache_dir, provider)
    )
    index.build(load_corpus(settings.fixtures_dir, settings.itsm_processed_dir))
    return index


RetrievalIndexDep = Annotated["HistoricalIndex", Depends(get_retrieval_index)]


@lru_cache
def get_action_repository() -> "ActionRepository":
    """The process-wide action store.

    In-memory and prototype-local: action state and the audit trail are lost when the
    API restarts. See `app.actions.repository` for what production would need instead.
    """
    from app.actions import ActionRepository

    return ActionRepository()


ActionRepositoryDep = Annotated["ActionRepository", Depends(get_action_repository)]
