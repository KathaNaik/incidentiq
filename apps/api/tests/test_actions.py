"""The approval workflow: policy, state machine, execution, idempotency, audit."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.actions import (
    ActionRepository,
    ActionStatus,
    ActionType,
    ActorType,
    AuditEventType,
    ConcurrentModificationError,
    InvalidTransitionError,
    approve_action,
    assert_transition,
    evaluate_action_policy,
    execute_action,
    propose_action,
    reject_action,
)
from app.actions.executors import ExecutorError, execute as run_executor
from app.actions.models import ActionTarget, PolicyDecision
from app.actions.rules import DEMO_ACTOR_ID
from app.config import get_settings
from app.investigation import load_operations
from app.investigation.models import RemediationAction, RiskLevel
from evaluation.policy import (
    CORRELATION,
    DEPLOYMENT,
    ERROR,
    GHOST_DEPLOYMENT,
    HEALTH,
    HISTORICAL,
    _investigation,
    _remediation,
)

OPERATIONS = load_operations(get_settings().fixtures_dir)


def strong_investigation():
    return _investigation(
        remediation=_remediation(
            RemediationAction.ROLLBACK_DEPLOYMENT,
            (DEPLOYMENT.id, HEALTH.id, ERROR.id),
        ),
        evidence=(CORRELATION, DEPLOYMENT, HEALTH, ERROR),
    )


def propose(repository: ActionRepository, investigation=None, **kwargs):
    return propose_action(
        investigation=investigation or strong_investigation(),
        operations=OPERATIONS,
        repository=repository,
        service_id=kwargs.pop("service_id", "svc-auth"),
        **kwargs,
    )


# --- policy ---------------------------------------------------------------------------


def test_strong_evidence_is_eligible_and_risk_comes_from_policy() -> None:
    """The model called this low risk. Policy does not take its word for it."""
    investigation = strong_investigation()
    assert investigation.output.remediation.risk is RiskLevel.LOW

    decision = evaluate_action_policy(
        recommendation=investigation.output.remediation,
        investigation=investigation.output,
        evidence=investigation.evidence,
        operations=OPERATIONS,
        service_id="svc-auth",
    )

    assert decision.eligible
    assert decision.decision is PolicyDecision.ELIGIBLE_FOR_APPROVAL
    assert decision.effective_risk is RiskLevel.HIGH
    assert decision.required_approvals == 1
    assert decision.validated_target.deployment_id == "DEP-2041"


def test_invented_target_cannot_be_approved() -> None:
    investigation = _investigation(
        remediation=_remediation(
            RemediationAction.ROLLBACK_DEPLOYMENT, (GHOST_DEPLOYMENT.id, HEALTH.id)
        ),
        evidence=(GHOST_DEPLOYMENT, HEALTH),
    )

    decision = evaluate_action_policy(
        recommendation=investigation.output.remediation,
        investigation=investigation.output,
        evidence=investigation.evidence,
        operations=OPERATIONS,
        service_id="svc-auth",
    )

    assert not decision.eligible
    assert decision.validated_target is None
    assert any(r.check == "target_exists" and not r.passed for r in decision.reasons)


def test_precedent_alone_is_not_enough() -> None:
    investigation = _investigation(
        remediation=_remediation(RemediationAction.ROLLBACK_DEPLOYMENT, (HISTORICAL.id,)),
        evidence=(HISTORICAL,),
    )

    decision = evaluate_action_policy(
        recommendation=investigation.output.remediation,
        investigation=investigation.output,
        evidence=investigation.evidence,
        operations=OPERATIONS,
        service_id="svc-auth",
    )

    assert not decision.eligible
    assert any(r.check == "independent_evidence" and not r.passed for r in decision.reasons)


def test_abstaining_investigation_cannot_produce_an_action() -> None:
    investigation = _investigation(
        remediation=_remediation(
            RemediationAction.ROLLBACK_DEPLOYMENT, (DEPLOYMENT.id, HEALTH.id, ERROR.id)
        ),
        abstain=True,
        evidence=(DEPLOYMENT, HEALTH, ERROR),
    )

    decision = evaluate_action_policy(
        recommendation=investigation.output.remediation,
        investigation=investigation.output,
        evidence=investigation.evidence,
        operations=OPERATIONS,
        service_id="svc-auth",
    )

    assert not decision.eligible


def test_evidence_the_investigation_never_had_is_refused() -> None:
    investigation = _investigation(
        remediation=_remediation(
            RemediationAction.ROLLBACK_DEPLOYMENT, ("deployment:MADE-UP", HEALTH.id)
        ),
        evidence=(DEPLOYMENT, HEALTH),
    )

    decision = evaluate_action_policy(
        recommendation=investigation.output.remediation,
        investigation=investigation.output,
        evidence=investigation.evidence,
        operations=OPERATIONS,
        service_id="svc-auth",
    )

    assert not decision.eligible
    assert any(r.check == "evidence_exists" and not r.passed for r in decision.reasons)


def test_resolved_incident_blocks_action() -> None:
    investigation = strong_investigation()

    decision = evaluate_action_policy(
        recommendation=investigation.output.remediation,
        investigation=investigation.output,
        evidence=investigation.evidence,
        operations=OPERATIONS,
        incident_status="resolved",
        service_id="svc-auth",
    )

    assert not decision.eligible


def test_action_type_without_an_executor_is_refused() -> None:
    """The investigator's vocabulary is wider than what this system can perform."""
    investigation = _investigation(
        remediation=_remediation(
            RemediationAction.SCALE_SERVICE, (DEPLOYMENT.id, HEALTH.id)
        ),
        evidence=(DEPLOYMENT, HEALTH),
    )

    decision = evaluate_action_policy(
        recommendation=investigation.output.remediation,
        investigation=investigation.output,
        evidence=investigation.evidence,
        operations=OPERATIONS,
        service_id="svc-auth",
    )

    assert not decision.eligible
    assert any(r.check == "allowed_action_type" and not r.passed for r in decision.reasons)


# --- state machine -----------------------------------------------------------------------


def test_legal_transitions() -> None:
    assert_transition(ActionStatus.PROPOSED, ActionStatus.AWAITING_APPROVAL)
    assert_transition(ActionStatus.AWAITING_APPROVAL, ActionStatus.APPROVED)
    assert_transition(ActionStatus.APPROVED, ActionStatus.EXECUTING)
    assert_transition(ActionStatus.EXECUTING, ActionStatus.SUCCEEDED)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (ActionStatus.REJECTED, ActionStatus.EXECUTING),
        (ActionStatus.POLICY_REJECTED, ActionStatus.EXECUTING),
        (ActionStatus.SUCCEEDED, ActionStatus.APPROVED),
        (ActionStatus.AWAITING_APPROVAL, ActionStatus.EXECUTING),
        (ActionStatus.PROPOSED, ActionStatus.SUCCEEDED),
    ],
)
def test_illegal_transitions_are_refused(current, target) -> None:
    """Skipping approval, reviving a rejection, or re-approving a finished action."""
    with pytest.raises(InvalidTransitionError):
        assert_transition(current, target)


# --- workflow ----------------------------------------------------------------------------


def test_happy_path_proposes_approves_and_executes() -> None:
    repository = ActionRepository()

    action = propose(repository)
    assert action.status is ActionStatus.AWAITING_APPROVAL
    assert action.risk is RiskLevel.HIGH

    approved = approve_action(action_id=action.id, repository=repository)
    assert approved.status is ActionStatus.APPROVED
    assert approved.approval.actor_type is ActorType.HUMAN
    assert approved.approval.actor_id == DEMO_ACTOR_ID

    executed = execute_action(
        action_id=action.id, repository=repository, operations=OPERATIONS
    )
    assert executed.status is ActionStatus.SUCCEEDED
    assert executed.execution.simulated is True
    assert "Simulated rollback" in executed.execution.summary


def test_policy_rejected_action_has_no_approval_path() -> None:
    repository = ActionRepository()
    action = propose(
        repository,
        investigation=_investigation(
            remediation=_remediation(RemediationAction.ROLLBACK_DEPLOYMENT, (HISTORICAL.id,)),
            evidence=(HISTORICAL,),
        ),
    )

    assert action.status is ActionStatus.POLICY_REJECTED
    with pytest.raises(InvalidTransitionError):
        approve_action(action_id=action.id, repository=repository)


def test_execution_before_approval_is_refused() -> None:
    repository = ActionRepository()
    action = propose(repository)

    with pytest.raises(InvalidTransitionError):
        execute_action(action_id=action.id, repository=repository, operations=OPERATIONS)


def test_rejected_action_cannot_execute() -> None:
    repository = ActionRepository()
    action = propose(repository)
    reject_action(action_id=action.id, repository=repository, reason="handled manually")

    with pytest.raises(InvalidTransitionError):
        execute_action(action_id=action.id, repository=repository, operations=OPERATIONS)


def test_double_approval_is_refused() -> None:
    repository = ActionRepository()
    action = propose(repository)
    approve_action(action_id=action.id, repository=repository)

    with pytest.raises(InvalidTransitionError):
        approve_action(action_id=action.id, repository=repository)


def test_approval_after_rejection_is_refused() -> None:
    repository = ActionRepository()
    action = propose(repository)
    reject_action(action_id=action.id, repository=repository)

    with pytest.raises(InvalidTransitionError):
        approve_action(action_id=action.id, repository=repository)


def test_repeated_execution_does_not_run_the_action_twice() -> None:
    """Idempotency: the second request returns the first result, unchanged."""
    repository = ActionRepository()
    action = propose(repository)
    approve_action(action_id=action.id, repository=repository)

    first = execute_action(
        action_id=action.id, repository=repository, operations=OPERATIONS
    )
    second = execute_action(
        action_id=action.id, repository=repository, operations=OPERATIONS
    )

    assert second.execution.executed_at == first.execution.executed_at
    assert second.status is ActionStatus.SUCCEEDED
    kinds = [event.event_type for event in repository.audit_for_action(action.id)]
    assert kinds.count(AuditEventType.EXECUTION_SUCCEEDED) == 1
    assert AuditEventType.EXECUTION_SKIPPED_IDEMPOTENT in kinds


def test_stale_state_is_detected_by_compare_and_set() -> None:
    repository = ActionRepository()
    action = propose(repository)
    approve_action(action_id=action.id, repository=repository)

    with pytest.raises(ConcurrentModificationError):
        repository.replace(action, expected_status=ActionStatus.AWAITING_APPROVAL)


# --- executors ----------------------------------------------------------------------------


def test_executor_refuses_an_unknown_target() -> None:
    with pytest.raises(ExecutorError, match="no longer exists"):
        run_executor(
            ActionType.ROLLBACK_DEPLOYMENT,
            ActionTarget(service_id="svc-auth", deployment_id="DEP-0000"),
            OPERATIONS,
        )
    with pytest.raises(ExecutorError, match="not known"):
        run_executor(
            ActionType.RESTART_SERVICE, ActionTarget(service_id="svc-nope"), OPERATIONS
        )


def test_every_execution_is_marked_simulated() -> None:
    for action_type, target in (
        (ActionType.ROLLBACK_DEPLOYMENT, ActionTarget(service_id="svc-auth", deployment_id="DEP-2041")),
        (ActionType.RESTART_SERVICE, ActionTarget(service_id="svc-auth")),
        (ActionType.ROTATE_CREDENTIAL, ActionTarget(service_id="svc-connector")),
    ):
        result = run_executor(action_type, target, OPERATIONS)
        assert result.simulated is True
        assert "Simulated" in result.summary


def test_action_target_has_no_free_text_field() -> None:
    """Nothing an executor reads could carry a command; there is no field for one."""
    fields = set(ActionTarget.model_fields)
    assert fields == {"service_id", "deployment_id", "version"}
    with pytest.raises(Exception):
        ActionTarget(service_id="svc-auth", command="rm -rf /")


# --- audit ---------------------------------------------------------------------------------


def test_audit_records_the_whole_chain_in_order() -> None:
    repository = ActionRepository()
    action = propose(repository)
    approve_action(action_id=action.id, repository=repository)
    execute_action(action_id=action.id, repository=repository, operations=OPERATIONS)

    events = repository.audit_for_action(action.id)
    assert [event.event_type for event in events] == [
        AuditEventType.RECOMMENDATION_RECEIVED,
        AuditEventType.ACTION_PROPOSED,
        AuditEventType.POLICY_EVALUATED,
        AuditEventType.APPROVAL_GRANTED,
        AuditEventType.EXECUTION_STARTED,
        AuditEventType.EXECUTION_SUCCEEDED,
    ]
    times = [event.occurred_at for event in events]
    assert times == sorted(times)


def test_actor_attribution_is_precise() -> None:
    """The model recommends. The system proposes and executes. A human approves.

    Execution attributed to the model would misrepresent who did what, which is the
    whole reason this milestone exists.
    """
    repository = ActionRepository()
    action = propose(repository)
    approve_action(action_id=action.id, repository=repository)
    execute_action(action_id=action.id, repository=repository, operations=OPERATIONS)

    by_type = {
        event.event_type: event for event in repository.audit_for_action(action.id)
    }
    assert by_type[AuditEventType.RECOMMENDATION_RECEIVED].actor_type is ActorType.MODEL
    assert by_type[AuditEventType.ACTION_PROPOSED].actor_type is ActorType.SYSTEM
    assert by_type[AuditEventType.POLICY_EVALUATED].actor_type is ActorType.SYSTEM
    assert by_type[AuditEventType.APPROVAL_GRANTED].actor_type is ActorType.HUMAN
    assert by_type[AuditEventType.EXECUTION_SUCCEEDED].actor_type is ActorType.SYSTEM

    # The model appears nowhere in approval or execution.
    for event_type in (
        AuditEventType.APPROVAL_GRANTED,
        AuditEventType.EXECUTION_STARTED,
        AuditEventType.EXECUTION_SUCCEEDED,
    ):
        assert by_type[event_type].actor_type is not ActorType.MODEL


def test_audit_stores_no_prompt_or_credential_material() -> None:
    repository = ActionRepository()
    action = propose(repository)
    approve_action(action_id=action.id, repository=repository)

    for event in repository.audit_for_action(action.id):
        blob = " ".join(event.details.values()).lower()
        for forbidden in ("sk-", "api_key", "system prompt", "reasoning"):
            assert forbidden not in blob


def test_rejection_is_audited() -> None:
    repository = ActionRepository()
    action = propose(repository)
    reject_action(action_id=action.id, repository=repository, reason="rolling forward")

    kinds = [event.event_type for event in repository.audit_for_action(action.id)]
    assert AuditEventType.APPROVAL_REJECTED in kinds
    assert AuditEventType.EXECUTION_STARTED not in kinds


# --- API --------------------------------------------------------------------------------------


def _propose_via_api(client: TestClient):
    investigation = strong_investigation()
    return client.post(
        f"/incidents/{investigation.incident_id}/actions",
        json={
            "investigation_run_id": seed_run(client, investigation),
            "service_id": "svc-auth",
        },
    )


def test_full_workflow_over_http(client: TestClient) -> None:
    proposed = _propose_via_api(client)
    assert proposed.status_code == 200
    body = proposed.json()
    action_id = body["action"]["id"]
    assert body["action"]["status"] == "awaiting_approval"
    assert body["actor"]["actor_id"] == DEMO_ACTOR_ID
    assert "no authentication" in body["actor"]["note"]

    # Executing before approval is refused at the API boundary too.
    assert client.post(f"/actions/{action_id}/execute").status_code == 409

    approved = client.post(f"/actions/{action_id}/approve", json={"reason": "confirmed"})
    assert approved.status_code == 200
    assert approved.json()["action"]["status"] == "approved"

    executed = client.post(f"/actions/{action_id}/execute")
    assert executed.status_code == 200
    assert executed.json()["action"]["status"] == "succeeded"
    assert executed.json()["action"]["execution"]["simulated"] is True

    again = client.post(f"/actions/{action_id}/execute")
    assert again.status_code == 200
    assert (
        again.json()["action"]["execution"]["executed_at"]
        == executed.json()["action"]["execution"]["executed_at"]
    )

    audit = client.get(f"/actions/{action_id}/audit")
    assert audit.status_code == 200
    assert len(audit.json()) >= 6


def test_api_reports_a_policy_rejection_as_a_result_not_an_error(
    client: TestClient,
) -> None:
    investigation = _investigation(
        remediation=_remediation(RemediationAction.ROLLBACK_DEPLOYMENT, (HISTORICAL.id,)),
        evidence=(HISTORICAL,),
    )
    response = client.post(
        f"/incidents/{investigation.incident_id}/actions",
        json={
            "investigation_run_id": seed_run(client, investigation),
            "service_id": "svc-auth",
        },
    )

    assert response.status_code == 200
    action = response.json()["action"]
    assert action["status"] == "policy_rejected"
    assert action["policy"]["eligible"] is False
    assert any(not reason["passed"] for reason in action["policy"]["reasons"])

    assert client.post(f"/actions/{action['id']}/approve").status_code == 409


def seed_run(client: TestClient, investigation) -> str:
    """Stores an investigation as a completed run and returns its id.

    Actions are proposed from a *stored* run since M13 — the API no longer accepts model
    output from a client — so an HTTP test has to put one in the store first.
    """
    from app.dependencies import get_investigation_store
    from app.investigation.rules import INVESTIGATION_VERSION

    store = client.app.dependency_overrides[get_investigation_store]()
    run = store.begin(
        incident_id=investigation.incident_id,
        investigator_version=INVESTIGATION_VERSION,
        prompt_version=investigation.run.prompt_version,
        provider="openai",
        model=investigation.run.model,
        evidence=investigation.evidence,
    )
    store.complete(
        run.id,
        output=investigation.output,
        model=investigation.run.model,
        latency_ms=investigation.run.latency_ms,
        input_tokens=investigation.run.input_tokens,
        output_tokens=investigation.run.output_tokens,
        reasoning_tokens=None,
    )
    return run.id


def test_api_rejects_a_mismatched_incident(client: TestClient) -> None:
    run_id = seed_run(client, strong_investigation())
    response = client.post(
        "/incidents/cand-OTHER/actions", json={"investigation_run_id": run_id}
    )

    assert response.status_code == 400


def test_api_refuses_an_unknown_investigation_run(client: TestClient) -> None:
    """A client cannot invent a run to act on, nor hand over its own model output."""
    response = client.post(
        "/incidents/cand-TEST/actions", json={"investigation_run_id": "inv-nope"}
    )

    assert response.status_code == 404


def test_api_404s_for_unknown_actions(client: TestClient) -> None:
    assert client.get("/actions/act-nope").status_code == 404
    assert client.post("/actions/act-nope/approve").status_code == 404
    assert client.post("/actions/act-nope/execute").status_code == 404
    assert client.get("/actions/act-nope/audit").status_code == 404


def test_investigation_without_remediation_cannot_propose(client: TestClient) -> None:
    """The current model behaviour: no recommendation means nothing to approve."""
    investigation = _investigation(remediation=None, evidence=(DEPLOYMENT, HEALTH))
    run_id = seed_run(client, investigation)
    response = client.post(
        f"/incidents/{investigation.incident_id}/actions",
        json={"investigation_run_id": run_id},
    )

    assert response.status_code == 422
    assert "recommended no remediation" in response.json()["detail"]


def test_a_proposed_action_names_the_run_that_recommended_it(client: TestClient) -> None:
    """The linkage an auditor needs: which exact model run proposed this rollback."""
    investigation = strong_investigation()
    run_id = seed_run(client, investigation)
    response = client.post(
        f"/incidents/{investigation.incident_id}/actions",
        json={"investigation_run_id": run_id},
    )

    assert response.status_code == 200
    assert response.json()["action"]["investigation_run_id"] == run_id
