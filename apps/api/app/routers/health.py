"""Liveness endpoint.

This reports only that the API process is serving requests. As dependencies are added,
readiness of those dependencies belongs in a separate endpoint — do not quietly widen
`/health` into a dependency check.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.config import Settings, get_settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str


@router.get("/health", response_model=HealthResponse)
def read_health(
    settings: Annotated[Settings, Depends(get_settings)],
) -> HealthResponse:
    return HealthResponse(status="ok", service=settings.service_name)
