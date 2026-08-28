"""Action, approval, and audit contracts.

The model's authority ends at a *recommendation*. Everything in this module belongs to
the application: which actions exist, whether one may be proposed, who may approve it,
what states it can move through, and what gets written down. That separation is the
point of the milestone — an LLM cannot reach any of it.

Execution here is **simulated**. Nothing calls a cloud provider, an orchestrator, or a
real deployment system, and every surface says so.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.investigation.models import RiskLevel


class ActionType(StrEnum):
    """Actions IncidentIQ can simulate.

    Narrower than the set the investigator may recommend: the model can suggest
    `scale_service` or `disable_feature_flag`, and policy will refuse to make those
    actionable because no executor exists. A recommendation is not a capability.
    """

    ROLLBACK_DEPLOYMENT = "rollback_deployment"
    RESTART_SERVICE = "restart_service"
    ROTATE_CREDENTIAL = "rotate_credential"


class ActionStatus(StrEnum):
    PROPOSED = "proposed"
    POLICY_REJECTED = "policy_rejected"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class PolicyDecision(StrEnum):
    ELIGIBLE_FOR_APPROVAL = "eligible_for_approval"
    REJECTED_BY_POLICY = "rejected_by_policy"
    REQUIRES_MORE_EVIDENCE = "requires_more_evidence"


class ActorType(StrEnum):
    """Who did a thing. Kept precise on purpose.

    The model recommends. The system proposes, evaluates policy, and executes. A human
    approves or rejects. Execution is never attributed to the model, and a test enforces
    that.
    """

    MODEL = "model"
    SYSTEM = "system"
    HUMAN = "human"


class AuditEventType(StrEnum):
    RECOMMENDATION_RECEIVED = "recommendation_received"
    ACTION_PROPOSED = "action_proposed"
    POLICY_EVALUATED = "policy_evaluated"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_REJECTED = "approval_rejected"
    EXECUTION_STARTED = "execution_started"
    EXECUTION_SUCCEEDED = "execution_succeeded"
    EXECUTION_FAILED = "execution_failed"
    EXECUTION_SKIPPED_IDEMPOTENT = "execution_skipped_idempotent"


class ActionModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ActionTarget(ActionModel):
    """What an action operates on.

    Typed fields only — there is no free-form string an executor interpolates anywhere.
    A model cannot smuggle a command through here because there is nowhere to put one.
    """

    service_id: str
    deployment_id: str | None = None
    version: str | None = None


class PolicyReason(ActionModel):
    """One check, and how it came out. Rendered directly in the UI.

    `evidence_ids` names the evidence the check actually consulted, so a rejection can be
    traced to the signals that caused it rather than asserted. Empty for checks that read
    no evidence — the abstention gate reads the investigation, not the registry.
    """

    check: str
    passed: bool
    detail: str
    evidence_ids: tuple[str, ...] = ()


class ActionPolicyDecision(ActionModel):
    eligible: bool
    decision: PolicyDecision
    reasons: tuple[PolicyReason, ...]
    # Assigned by policy from the action type, not taken from the model's word for it.
    effective_risk: RiskLevel
    required_approvals: int
    validated_target: ActionTarget | None
    validated_evidence_ids: tuple[str, ...]
    evidence_source_kinds: tuple[str, ...]


class Approval(ActionModel):
    id: str
    action_id: str
    approved: bool
    actor_type: ActorType
    actor_id: str
    decided_at: datetime
    reason: str | None = None


class ExecutionResult(ActionModel):
    """The outcome of a simulated execution.

    `simulated` is always true in this prototype and is surfaced everywhere the result
    is. When a real integration exists, this is the field that stops a demo recording
    from being mistaken for production.
    """

    simulated: bool = True
    succeeded: bool
    summary: str
    details: tuple[str, ...] = ()
    executed_at: datetime


class Action(ActionModel):
    id: str
    incident_id: str
    action_type: ActionType
    target: ActionTarget
    status: ActionStatus
    risk: RiskLevel
    created_at: datetime
    # What the model said, kept for the audit trail — the action is the system's, the
    # recommendation was the model's.
    recommendation_summary: str
    recommendation_evidence_ids: tuple[str, ...]
    policy: ActionPolicyDecision
    approval: Approval | None = None
    execution: ExecutionResult | None = None


class AuditEvent(ActionModel):
    id: str
    incident_id: str
    action_id: str | None
    event_type: AuditEventType
    actor_type: ActorType
    actor_id: str
    occurred_at: datetime
    # Structured metadata, enough to reconstruct the decision. Never prompts, never
    # reasoning content, never credentials.
    details: dict[str, str] = Field(default_factory=dict)
