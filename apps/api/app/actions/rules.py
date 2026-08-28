"""Action policy constants.

Two tables and a transition map. All of it deterministic, all of it in one file, none of
it produced by a model.
"""

from datetime import timedelta

from app.actions.models import ActionStatus, ActionType
from app.investigation.models import RiskLevel

ACTIONS_VERSION = "action-policy-v1"

# The policy in force. v1 is kept intact so the recorded M9 numbers stay attributable to
# the code that produced them; v2 is what runs.
ACTIONS_VERSION_V2 = "action-policy-v2"
ACTIVE_ACTIONS_VERSION = ACTIONS_VERSION_V2

# How long after a deployment it remains a plausible cause. Beyond this a release and an
# incident are two things that happened on the same day. Two hours is a judgement call
# for this prototype's fixtures, not a law of operations — it is one constant, in one
# place, so it can be argued with.
DEPLOYMENT_BLAST_WINDOW = timedelta(hours=2)

# Prototype identity. There is no authentication in this milestone, and the actor id
# says so plainly rather than implying a signed-in user.
DEMO_ACTOR_ID = "operator:demo-user"

# Risk is assigned by the application from the action type, never taken from the model's
# self-assessment. A model that rates its own rollback "low" does not get a cheaper path.
ACTION_RISK: dict[ActionType, RiskLevel] = {
    ActionType.ROLLBACK_DEPLOYMENT: RiskLevel.HIGH,
    ActionType.RESTART_SERVICE: RiskLevel.MEDIUM,
    ActionType.ROTATE_CREDENTIAL: RiskLevel.HIGH,
}

# Every consequential action needs one human approval in this milestone. Nothing is
# auto-approved on low risk or high model confidence.
REQUIRED_APPROVALS = 1

# --- superseded by action-policy-v2 ---------------------------------------------------
#
# The generic threshold below is what v1 enforced. Measuring investigator-v2 showed it
# passing three restarts on services that were merely degraded: two independent kinds was
# a bar about the *quantity* of evidence when the question was about its *relevance*.
# Kept because policy-v1's recorded results are only meaningful alongside the constants
# that produced them. `policy_v2.py` asks each action its own questions instead.

# Distinct evidence *kinds* required before an action is eligible. Two independent kinds
# for anything consequential: one signal can be a coincidence, and the point of policy
# is to refuse a plausible story with a single source behind it.
MIN_EVIDENCE_KINDS: dict[ActionType, int] = {
    ActionType.ROLLBACK_DEPLOYMENT: 2,
    ActionType.RESTART_SERVICE: 2,
    ActionType.ROTATE_CREDENTIAL: 2,
}

# A past incident that looked similar is not causal evidence about this one. It may
# support an action alongside operational signals; it may never be the whole case.
NON_CAUSAL_EVIDENCE_KINDS = frozenset({"historical"})

# Rollback specifically needs the deployment it intends to undo.
REQUIRED_EVIDENCE_KINDS: dict[ActionType, frozenset[str]] = {
    ActionType.ROLLBACK_DEPLOYMENT: frozenset({"deployment"}),
}

# Incident statuses an action may still be taken against. Acting on something already
# resolved is at best noise and at worst a fresh outage.
BLOCKED_INCIDENT_STATUSES = frozenset({"resolved"})

# The legal state graph. Anything not listed here is refused, so an invalid transition
# is impossible rather than merely hidden by the UI.
LEGAL_TRANSITIONS: dict[ActionStatus, frozenset[ActionStatus]] = {
    ActionStatus.PROPOSED: frozenset(
        {ActionStatus.AWAITING_APPROVAL, ActionStatus.POLICY_REJECTED}
    ),
    ActionStatus.AWAITING_APPROVAL: frozenset(
        {ActionStatus.APPROVED, ActionStatus.REJECTED}
    ),
    ActionStatus.APPROVED: frozenset({ActionStatus.EXECUTING}),
    ActionStatus.EXECUTING: frozenset({ActionStatus.SUCCEEDED, ActionStatus.FAILED}),
    # Terminal.
    ActionStatus.POLICY_REJECTED: frozenset(),
    ActionStatus.REJECTED: frozenset(),
    ActionStatus.SUCCEEDED: frozenset(),
    ActionStatus.FAILED: frozenset(),
}
