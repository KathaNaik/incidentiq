"""Action workflow endpoints.

Approve and execute are deliberately separate endpoints. Collapsing them would remove
the operator's second look — the moment between "yes, that is the right fix" and "yes,
do it now" — which is exactly the control this milestone exists to demonstrate.

There is no authentication. Every human decision is attributed to a fixed demo actor,
and the response says so.
"""

from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.actions import (
    Action,
    ActionNotFoundError,
    ActionRepository,
    ActionWorkflowError,
    AuditEvent,
    ConcurrentModificationError,
    InvalidTransitionError,
    approve_action,
    execute_action,
    propose_action,
    reject_action,
)
from app.actions.rules import DEMO_ACTOR_ID
from app.config import Settings, get_settings
from app.dependencies import ActionRepositoryDep
from app.investigation import InvestigationResult, ToolError, load_operations

router = APIRouter(tags=["actions"])


class ProposeActionRequest(BaseModel):
    """An investigation result, handed back for the system to act on.

    The client returns the investigation it was shown rather than a hand-built action:
    the action's shape is derived from validated evidence here, so a caller cannot name
    its own target or cite evidence the investigation never had.
    """

    model_config = ConfigDict(extra="forbid")

    investigation: InvestigationResult
    incident_status: str | None = None
    service_id: str | None = None


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=500)


class ActorNote(BaseModel):
    """Attached to every mutation response so the prototype's limits stay visible."""

    actor_id: str = DEMO_ACTOR_ID
    note: str = (
        "This prototype has no authentication. Every human decision is recorded "
        "against a fixed demo actor."
    )


class ActionResponse(BaseModel):
    action: Action
    actor: ActorNote = ActorNote()


def _operations(settings: Settings):
    try:
        return load_operations(settings.fixtures_dir)
    except ToolError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
        ) from error


def _fetch(repository: ActionRepository, action_id: str) -> Action:
    try:
        return repository.get(action_id)
    except ActionNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown action: {action_id}"
        ) from error


@router.post("/incidents/{incident_id}/actions", response_model=ActionResponse)
def propose(
    incident_id: str,
    request: Annotated[ProposeActionRequest, Body()],
    repository: ActionRepositoryDep,
    settings: Annotated[Settings, Depends(get_settings)],
) -> ActionResponse:
    """Proposes an action from an investigation's remediation recommendation.

    Always returns 200 when a recommendation exists, including when policy rejects it —
    a refused recommendation is a result the operator should see, not an error.
    """
    if request.investigation.incident_id != incident_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"investigation belongs to {request.investigation.incident_id}, "
                f"not {incident_id}"
            ),
        )

    try:
        action = propose_action(
            investigation=request.investigation,
            operations=_operations(settings),
            repository=repository,
            incident_status=request.incident_status,
            service_id=request.service_id,
        )
    except ActionWorkflowError as error:
        raise HTTPException(
            status_code=422, detail=str(error)
        ) from error
    return ActionResponse(action=action)


@router.get("/incidents/{incident_id}/actions", response_model=list[Action])
def list_for_incident(incident_id: str, repository: ActionRepositoryDep) -> list[Action]:
    return list(repository.for_incident(incident_id))


@router.get("/actions/{action_id}", response_model=Action)
def get_action(action_id: str, repository: ActionRepositoryDep) -> Action:
    return _fetch(repository, action_id)


@router.post("/actions/{action_id}/approve", response_model=ActionResponse)
def approve(
    action_id: str, repository: ActionRepositoryDep, request: DecisionRequest | None = None
) -> ActionResponse:
    _fetch(repository, action_id)
    try:
        action = approve_action(
            action_id=action_id,
            repository=repository,
            reason=request.reason if request else None,
        )
    except (InvalidTransitionError, ConcurrentModificationError) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        ) from error
    return ActionResponse(action=action)


@router.post("/actions/{action_id}/reject", response_model=ActionResponse)
def reject(
    action_id: str, repository: ActionRepositoryDep, request: DecisionRequest | None = None
) -> ActionResponse:
    _fetch(repository, action_id)
    try:
        action = reject_action(
            action_id=action_id,
            repository=repository,
            reason=request.reason if request else None,
        )
    except (InvalidTransitionError, ConcurrentModificationError) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        ) from error
    return ActionResponse(action=action)


@router.post("/actions/{action_id}/execute", response_model=ActionResponse)
def execute(
    action_id: str,
    repository: ActionRepositoryDep,
    settings: Annotated[Settings, Depends(get_settings)],
) -> ActionResponse:
    """Runs the simulated action.

    Idempotent: repeating this against an action that already ran returns the existing
    result rather than performing the side effect again.
    """
    _fetch(repository, action_id)
    try:
        action = execute_action(
            action_id=action_id,
            repository=repository,
            operations=_operations(settings),
        )
    except (InvalidTransitionError, ConcurrentModificationError) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        ) from error
    return ActionResponse(action=action)


@router.get("/actions/{action_id}/audit", response_model=list[AuditEvent])
def action_audit(action_id: str, repository: ActionRepositoryDep) -> list[AuditEvent]:
    _fetch(repository, action_id)
    return list(repository.audit_for_action(action_id))


@router.get("/incidents/{incident_id}/audit", response_model=list[AuditEvent])
def incident_audit(incident_id: str, repository: ActionRepositoryDep) -> list[AuditEvent]:
    return list(repository.audit_for_incident(incident_id))
