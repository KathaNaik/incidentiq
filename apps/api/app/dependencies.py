"""Shared FastAPI dependencies."""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from app.config import get_settings
from app.fixtures import load_dataset
from app.repository import InMemoryRepository, Repository


@lru_cache
def get_repository() -> Repository:
    """The process-wide repository.

    Fixtures are read once at first use; the dataset is immutable, so there is nothing
    to invalidate. Tests substitute their own repository with
    `app.dependency_overrides[get_repository]`.
    """
    return InMemoryRepository(load_dataset(get_settings().fixtures_dir))


RepositoryDep = Annotated[Repository, Depends(get_repository)]
