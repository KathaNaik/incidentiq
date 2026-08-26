"""Provenance of the records being served."""

from fastapi import APIRouter

from app.dependencies import RepositoryDep
from app.schemas import DatasetInfo

router = APIRouter(tags=["dataset"])


@router.get("/dataset", response_model=DatasetInfo)
def get_dataset(repository: RepositoryDep) -> DatasetInfo:
    """Identifies the dataset behind every other endpoint.

    Every record served today comes from a fabricated fixture set, and the UI labels it
    as such using this response rather than a hard-coded string.
    """
    return DatasetInfo(name=repository.dataset_name, synthetic=True)
