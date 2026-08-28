"""Human-approved remediation.

The boundary between what a model recommends and what a system does. Policy decides
whether a recommendation may become an action, a person approves it, a person asks for
it to run, and the system runs a simulated executor. Every crossing is audited, and no
step here involves a language model.
"""

from app.actions.executors import ExecutorError, execute
from app.actions.machine import InvalidTransitionError, assert_transition, is_terminal
from app.actions.models import (
    Action,
    ActionPolicyDecision,
    ActionStatus,
    ActionTarget,
    ActionType,
    ActorType,
    Approval,
    AuditEvent,
    AuditEventType,
    ExecutionResult,
    PolicyDecision,
    PolicyReason,
)
from app.actions.policy import evaluate_action_policy
from app.actions.policy_v2 import evaluate_action_policy_v2
from app.actions.repository import (
    ActionNotFoundError,
    ActionRepository,
    ConcurrentModificationError,
)
from app.actions.rules import (
    ACTION_RISK,
    ACTIONS_VERSION,
    ACTIVE_ACTIONS_VERSION,
    DEMO_ACTOR_ID,
)
from app.actions.service import (
    ActionWorkflowError,
    approve_action,
    execute_action,
    propose_action,
    reject_action,
)

__all__ = [
    "ACTIONS_VERSION",
    "ACTIVE_ACTIONS_VERSION",
    "ACTION_RISK",
    "DEMO_ACTOR_ID",
    "Action",
    "ActionNotFoundError",
    "ActionPolicyDecision",
    "ActionRepository",
    "ActionStatus",
    "ActionTarget",
    "ActionType",
    "ActionWorkflowError",
    "ActorType",
    "Approval",
    "AuditEvent",
    "AuditEventType",
    "ConcurrentModificationError",
    "ExecutionResult",
    "ExecutorError",
    "InvalidTransitionError",
    "PolicyDecision",
    "PolicyReason",
    "approve_action",
    "assert_transition",
    "evaluate_action_policy",
    "evaluate_action_policy_v2",
    "execute",
    "execute_action",
    "is_terminal",
    "propose_action",
    "reject_action",
]
