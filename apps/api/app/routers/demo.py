"""Demo controls.

One endpoint, and it exists for a specific reason: action state lives in process memory,
so a walkthrough that approves and executes the hero rollback leaves the next walkthrough
looking at a completed action. Resetting means restarting the API, which is a poor thing
to do halfway through a demonstration.

This is **not** administration tooling. It clears action and audit state and nothing
else — fixtures, evaluation artifacts and every recorded run are files on disk and are
untouched. It refuses to run in a production environment rather than trusting the caller
not to press it.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict

from app.actions import evaluate_action_policy_v2
from app.actions.models import ActionPolicyDecision
from app.config import Settings, get_settings
from app.dependencies import ActionRepositoryDep, InvestigationStoreDep
from app.investigation import InvestigationResult, load_operations
from app.investigation.models import (
    RemediationAction,
    RemediationRecommendation,
    RiskLevel,
)

router = APIRouter(tags=["demo"])


class DemoResetResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    reset: bool
    cleared_actions: int
    cleared_audit_events: int
    cleared_investigations: int
    note: str


@router.post("/demo/reset", response_model=DemoResetResponse)
def reset_demo_state(
    settings: Annotated[Settings, Depends(get_settings)],
    repository: ActionRepositoryDep,
    store: InvestigationStoreDep,
) -> DemoResetResponse:
    """Clears workflow state so the walkthrough can be repeated.

    **Exactly what this deletes**, now that the state is durable:

    - actions, and the approvals and execution results attached to them
    - audit events
    - investigation runs, including their evidence snapshots

    **What it does not touch**: the historical corpus and its vectors (re-importing 751
    records to run a demo twice would be absurd), the Northstar fixtures, the evaluation
    artifacts, and the embedding cache. All of those are inputs or records of past
    measurements, not workflow state.

    Investigation runs *are* cleared, deliberately. Leaving them would open the
    walkthrough on a completed investigation, and "click Run AI investigation" is the
    step being demonstrated.

    This is the one operation in the system that breaks the audit trail's append-only
    property. It is isolated here rather than exposed as a general delete, and the API
    refuses it outside development.
    """
    if settings.environment == "production":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "demo reset is disabled outside development; it discards audit events "
                "and investigation records, which is never correct against real data"
            ),
        )

    actions = len(repository.all())
    events = len(repository.audit())
    investigations = repository.reset_workflow_state(store)

    return DemoResetResponse(
        reset=True,
        cleared_actions=actions,
        cleared_audit_events=events,
        cleared_investigations=investigations,
        note=(
            "Cleared actions, approvals, executions, audit events and investigation "
            "runs. The historical corpus, its vectors, the Northstar fixtures and every "
            "evaluation artifact were not touched."
        ),
    )


class PolicyProbeRequest(BaseModel):
    """An investigation, plus an action to ask policy about.

    The investigation is the real one the operator was shown; only the action type is
    hypothetical.
    """

    model_config = ConfigDict(frozen=True)

    investigation: InvestigationResult
    action_type: Literal["restart_service", "rollback_deployment", "rotate_credential"]
    service_id: str | None = None


class PolicyProbeResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    action_type: str
    hypothetical: bool
    policy: ActionPolicyDecision
    note: str


@router.post("/demo/policy-probe", response_model=PolicyProbeResponse)
def policy_probe(
    request: PolicyProbeRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> PolicyProbeResponse:
    """Asks policy what it *would* decide about an action nobody recommended.

    This exists so the rejection path can be demonstrated. The interesting policy
    behaviour is what it refuses, and on the Northstar fixtures the model correctly
    recommends a rollback — so the refusal never appears without asking for it.

    It creates no action, records no audit event, and cannot lead to an execution. The
    response is labelled `hypothetical` and the caller is required to say so in the UI:
    a fabricated model recommendation presented as real would be exactly the kind of
    demo dishonesty this project avoids elsewhere.
    """
    if settings.environment == "production":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="policy probing is a development affordance and is disabled here",
        )

    result = request.investigation
    recommendation = RemediationRecommendation(
        action_type=RemediationAction(request.action_type),
        description=f"hypothetical {request.action_type} for policy demonstration",
        risk=RiskLevel.LOW,
        supporting_evidence_ids=tuple(item.id for item in result.evidence),
    )
    decision = evaluate_action_policy_v2(
        recommendation=recommendation,
        investigation=result.output,
        evidence=result.evidence,
        operations=load_operations(settings.fixtures_dir),
        service_id=request.service_id,
    )
    return PolicyProbeResponse(
        action_type=request.action_type,
        hypothetical=True,
        policy=decision,
        note=(
            "No model recommended this action. Policy was asked directly what it would "
            "decide, against the same evidence. Nothing was proposed, approved or run."
        ),
    )
