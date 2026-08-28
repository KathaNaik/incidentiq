"""Simulated executors.

Every executor takes a typed `ActionTarget` and returns a typed `ExecutionResult`. None
of them builds a command string, calls a network service, or touches infrastructure —
there is nothing here for model text to be interpolated into, because model text never
reaches this layer.

`simulated=True` on every result, surfaced in the API and the UI. When a real integration
replaces one of these, that flag is what stops old demo output from being mistaken for a
production change.
"""

from collections.abc import Callable
from datetime import UTC, datetime

from app.actions.models import ActionTarget, ActionType, ExecutionResult
from app.investigation.tools import OperationsFixtures


class ExecutorError(RuntimeError):
    """An action could not be executed against the recorded operational state."""


def _rollback_deployment(
    target: ActionTarget, operations: OperationsFixtures
) -> ExecutionResult:
    deployment = next(
        (item for item in operations.deployments if item.id == target.deployment_id),
        None,
    )
    if deployment is None:
        raise ExecutorError(f"deployment {target.deployment_id} no longer exists")

    previous = _previous_deployment(deployment.service_id, deployment.deployed_at, operations)
    details = [
        f"Would roll {deployment.service_id} back from {deployment.version}.",
        (
            f"Previous known version: {previous.version} (deployed "
            f"{previous.deployed_at.isoformat()})."
            if previous
            else "No earlier deployment is recorded for this service."
        ),
        "No infrastructure was contacted.",
    ]
    return ExecutionResult(
        succeeded=True,
        summary=(
            f"Simulated rollback of {deployment.service_id} {deployment.version} "
            f"({deployment.id})"
        ),
        details=tuple(details),
        executed_at=datetime.now(UTC),
    )


def _restart_service(
    target: ActionTarget, operations: OperationsFixtures
) -> ExecutionResult:
    if not _service_exists(target.service_id, operations):
        raise ExecutorError(f"service {target.service_id} is not known")
    return ExecutionResult(
        succeeded=True,
        summary=f"Simulated restart of {target.service_id}",
        details=(
            f"Would perform a rolling restart of {target.service_id}.",
            "No orchestrator was contacted.",
        ),
        executed_at=datetime.now(UTC),
    )


def _rotate_credential(
    target: ActionTarget, operations: OperationsFixtures
) -> ExecutionResult:
    if not _service_exists(target.service_id, operations):
        raise ExecutorError(f"service {target.service_id} is not known")
    return ExecutionResult(
        succeeded=True,
        summary=f"Simulated credential rotation for {target.service_id}",
        details=(
            f"Would issue a new credential for {target.service_id} and revoke the "
            "previous one after a grace period.",
            "No secret store was contacted, and no credential value was generated.",
        ),
        executed_at=datetime.now(UTC),
    )


EXECUTORS: dict[ActionType, Callable[[ActionTarget, OperationsFixtures], ExecutionResult]] = {
    ActionType.ROLLBACK_DEPLOYMENT: _rollback_deployment,
    ActionType.RESTART_SERVICE: _restart_service,
    ActionType.ROTATE_CREDENTIAL: _rotate_credential,
}


def execute(
    action_type: ActionType, target: ActionTarget, operations: OperationsFixtures
) -> ExecutionResult:
    """Dispatches to the executor for an action type."""
    executor = EXECUTORS.get(action_type)
    if executor is None:
        raise ExecutorError(f"no executor is registered for {action_type.value}")
    return executor(target, operations)


def _service_exists(service_id: str, operations: OperationsFixtures) -> bool:
    return any(item.service_id == service_id for item in operations.deployments) or any(
        item.service_id == service_id for item in operations.health
    )


def _previous_deployment(service_id: str, before, operations: OperationsFixtures):
    earlier = [
        item
        for item in operations.deployments
        if item.service_id == service_id and item.deployed_at < before
    ]
    return max(earlier, key=lambda item: item.deployed_at) if earlier else None
