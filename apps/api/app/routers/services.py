"""Service catalogue."""

from fastapi import APIRouter

from app.dependencies import RepositoryDep
from app.domain.models import Service

router = APIRouter(tags=["services"])


@router.get("/services", response_model=list[Service])
def list_services(repository: RepositoryDep) -> list[Service]:
    """All known services, ordered by name."""
    return list(repository.list_services())
