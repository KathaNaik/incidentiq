"""The action workflow.

    model recommendation
      -> system proposes an action
      -> system evaluates policy
      -> human approves or rejects
      -> system executes (simulated)

Four boundaries, four distinct actors, and every crossing written to the audit trail.
The two human steps are separate on purpose: approving something and running it are
different decisions, and collapsing them would remove the operator's last chance to stop.
"""

import uuid
from datetime import UTC, datetime

from app.actions.executors import ExecutorError, execute as run_executor
from app.actions.machine import assert_transition
from app.actions.models import (
    Action,
    ActionPolicyDecision,
    ActionStatus,
    ActionType,
    ActorType,
    Approval,
    AuditEvent,
    AuditEventType,
)
from app.actions.policy_v2 import evaluate_action_policy_v2
from app.actions.repository import ActionRepository
from app.actions.rules import DEMO_ACTOR_ID
from app.investigation.models import InvestigationResult
from app.investigation.tools import OperationsFixtures

SYSTEM_ACTOR_ID = "incidentiq:system"
MODEL_ACTOR_PREFIX = "model:"


class ActionWorkflowError(RuntimeError):
    """The workflow refused a request."""


def propose_action(
    *,
    investigation: InvestigationResult,
    operations: OperationsFixtures,
    repository: ActionRepository,
    incident_status: str | None = None,
    service_id: str | None = None,
    investigation_run_id: str | None = None,
) -> Action:
    """Turns a model recommendation into an action, then runs policy over it.

    `investigation_run_id` ties the action to the exact run that recommended it. It is
    never repointed afterwards: re-investigating the incident tomorrow must not silently
    re-attribute an action a human already approved to a run that did not propose it.

    The action is created by the *system*, not the model: the model produced a
    recommendation, and this function decides whether that recommendation becomes
    something a person could act on.
    """
    recommendation = investigation.output.remediation
    if recommendation is None:
        raise ActionWorkflowError(
            "this investigation recommended no remediation, so there is nothing to propose"
        )

    now = datetime.now(UTC)
    action_id = f"act-{uuid.uuid4().hex[:12]}"

    repository.record(
        AuditEvent(
            id=_event_id(),
            incident_id=investigation.incident_id,
            action_id=action_id,
            investigation_run_id=investigation_run_id,
            event_type=AuditEventType.RECOMMENDATION_RECEIVED,
            actor_type=ActorType.MODEL,
            actor_id=f"{MODEL_ACTOR_PREFIX}{investigation.run.model}",
            occurred_at=now,
            details={
                "action_type": recommendation.action_type.value,
                "model_stated_risk": recommendation.risk.value,
                "cited_evidence": ", ".join(recommendation.supporting_evidence_ids),
                "prompt_version": investigation.run.prompt_version,
            },
        )
    )

    policy = evaluate_action_policy_v2(
        recommendation=recommendation,
        investigation=investigation.output,
        evidence=investigation.evidence,
        operations=operations,
        incident_status=incident_status,
        service_id=service_id,
    )

    action_type = _action_type_or_none(recommendation.action_type.value)
    action = Action(
        id=action_id,
        incident_id=investigation.incident_id,
        investigation_run_id=investigation_run_id,
        # An unsupported action type still gets recorded, as a rejected proposal — the
        # operator should see what was recommended and why it went nowhere.
        action_type=action_type or ActionType.RESTART_SERVICE,
        target=policy.validated_target
        or _placeholder_target(service_id, recommendation),
        status=ActionStatus.PROPOSED,
        risk=policy.effective_risk,
        created_at=now,
        recommendation_summary=recommendation.description,
        recommendation_evidence_ids=recommendation.supporting_evidence_ids,
        policy=policy,
    )
    repository.add(action)
    _audit(repository, action, AuditEventType.ACTION_PROPOSED, ActorType.SYSTEM, SYSTEM_ACTOR_ID)

    target_status = (
        ActionStatus.AWAITING_APPROVAL if policy.eligible else ActionStatus.POLICY_REJECTED
    )
    assert_transition(action.status, target_status)
    action = repository.replace(
        action.model_copy(update={"status": target_status}),
        expected_status=ActionStatus.PROPOSED,
    )
    _audit(
        repository,
        action,
        AuditEventType.POLICY_EVALUATED,
        ActorType.SYSTEM,
        SYSTEM_ACTOR_ID,
        {
            "decision": policy.decision.value,
            "eligible": str(policy.eligible).lower(),
            "effective_risk": policy.effective_risk.value,
            "failed_checks": ", ".join(
                reason.check for reason in policy.reasons if not reason.passed
            )
            or "none",
        },
    )
    return action


def approve_action(
    *, action_id: str, repository: ActionRepository, actor_id: str = DEMO_ACTOR_ID,
    reason: str | None = None,
) -> Action:
    """Records an explicit human approval.

    Nothing auto-approves — not low risk, not high model confidence, not a demo flag.
    """
    return _decide(
        action_id=action_id,
        repository=repository,
        approved=True,
        actor_id=actor_id,
        reason=reason,
    )


def reject_action(
    *, action_id: str, repository: ActionRepository, actor_id: str = DEMO_ACTOR_ID,
    reason: str | None = None,
) -> Action:
    return _decide(
        action_id=action_id,
        repository=repository,
        approved=False,
        actor_id=actor_id,
        reason=reason,
    )


def _decide(
    *,
    action_id: str,
    repository: ActionRepository,
    approved: bool,
    actor_id: str,
    reason: str | None,
) -> Action:
    action = repository.get(action_id)
    target_status = ActionStatus.APPROVED if approved else ActionStatus.REJECTED
    # Raises on a second approval, on approving something policy rejected, and on
    # approving something already executed.
    assert_transition(action.status, target_status)

    approval = Approval(
        id=f"apr-{uuid.uuid4().hex[:12]}",
        action_id=action.id,
        approved=approved,
        actor_type=ActorType.HUMAN,
        actor_id=actor_id,
        decided_at=datetime.now(UTC),
        reason=reason,
    )
    updated = repository.replace(
        action.model_copy(update={"status": target_status, "approval": approval}),
        expected_status=ActionStatus.AWAITING_APPROVAL,
    )
    _audit(
        repository,
        updated,
        AuditEventType.APPROVAL_GRANTED if approved else AuditEventType.APPROVAL_REJECTED,
        ActorType.HUMAN,
        actor_id,
        {"reason": reason} if reason else {},
    )
    return updated


def execute_action(
    *,
    action_id: str,
    repository: ActionRepository,
    operations: OperationsFixtures,
    actor_id: str = DEMO_ACTOR_ID,
) -> Action:
    """Runs the simulated action. Idempotent on an already-executed action.

    Execution is attributed to the *system*: a human asked for it, the system did it.
    The model appears nowhere in this path.
    """
    action = repository.get(action_id)

    # Idempotency: a repeated request returns the existing outcome instead of running
    # the side effect twice. Recorded, so a duplicate is visible rather than silent.
    if action.status in (ActionStatus.SUCCEEDED, ActionStatus.FAILED):
        _audit(
            repository,
            action,
            AuditEventType.EXECUTION_SKIPPED_IDEMPOTENT,
            ActorType.SYSTEM,
            SYSTEM_ACTOR_ID,
            {"existing_status": action.status.value},
        )
        return action

    assert_transition(action.status, ActionStatus.EXECUTING)
    action = repository.replace(
        action.model_copy(update={"status": ActionStatus.EXECUTING}),
        expected_status=ActionStatus.APPROVED,
    )
    _audit(
        repository,
        action,
        AuditEventType.EXECUTION_STARTED,
        ActorType.SYSTEM,
        SYSTEM_ACTOR_ID,
        {"requested_by": actor_id},
    )

    try:
        result = run_executor(action.action_type, action.target, operations)
    except ExecutorError as error:
        failed = repository.replace(
            action.model_copy(update={"status": ActionStatus.FAILED}),
            expected_status=ActionStatus.EXECUTING,
        )
        _audit(
            repository,
            failed,
            AuditEventType.EXECUTION_FAILED,
            ActorType.SYSTEM,
            SYSTEM_ACTOR_ID,
            {"error": str(error)},
        )
        return failed

    final_status = ActionStatus.SUCCEEDED if result.succeeded else ActionStatus.FAILED
    assert_transition(ActionStatus.EXECUTING, final_status)
    executed = repository.replace(
        action.model_copy(update={"status": final_status, "execution": result}),
        expected_status=ActionStatus.EXECUTING,
    )
    _audit(
        repository,
        executed,
        AuditEventType.EXECUTION_SUCCEEDED
        if result.succeeded
        else AuditEventType.EXECUTION_FAILED,
        ActorType.SYSTEM,
        SYSTEM_ACTOR_ID,
        {"simulated": "true", "summary": result.summary},
    )
    return executed


def _audit(
    repository: ActionRepository,
    action: Action,
    event_type: AuditEventType,
    actor_type: ActorType,
    actor_id: str,
    details: dict[str, str] | None = None,
) -> None:
    repository.record(
        AuditEvent(
            id=_event_id(),
            incident_id=action.incident_id,
            action_id=action.id,
            event_type=event_type,
            actor_type=actor_type,
            actor_id=actor_id,
            occurred_at=datetime.now(UTC),
            details=details or {},
        )
    )


def _event_id() -> str:
    return f"aud-{uuid.uuid4().hex[:12]}"


def _action_type_or_none(value: str) -> ActionType | None:
    try:
        return ActionType(value)
    except ValueError:
        return None


def _placeholder_target(service_id: str | None, recommendation):
    from app.actions.models import ActionTarget

    return ActionTarget(service_id=service_id or "unknown")
