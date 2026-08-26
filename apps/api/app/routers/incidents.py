"""Incident reads."""

from fastapi import APIRouter, HTTPException, status

from app.dependencies import RepositoryDep
from app.schemas import IncidentDetail, IncidentSummary

router = APIRouter(tags=["incidents"])


@router.get("/incidents", response_model=list[IncidentSummary])
def list_incidents(repository: RepositoryDep) -> list[IncidentSummary]:
    """All incidents, most recently detected first, with their ticket counts."""
    counts = repository.count_tickets_by_incident()
    return [
        IncidentSummary.build(incident, counts.get(incident.id, 0))
        for incident in repository.list_incidents()
    ]


@router.get("/incidents/{incident_id}", response_model=IncidentDetail)
def get_incident(incident_id: str, repository: RepositoryDep) -> IncidentDetail:
    incident = repository.get_incident(incident_id)
    if incident is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown incident: {incident_id}",
        )
    return IncidentDetail.build(
        incident, repository.list_tickets_for_incident(incident_id)
    )
