"""Action-specific deterministic policy.

`action-policy-v1` asked one question of every action: *are there at least two independent
kinds of evidence?* Measuring investigator-v2 showed why that is not enough. Three
`restart_service` recommendations passed it on services that were genuinely degraded and
genuinely emitting errors — two independent kinds, every generic check green — with
nothing establishing that a restart addressed what was actually broken.

The flaw is a category error, and it is worth naming precisely:

    Evidence that a service is failing is not evidence that a specific action fixes it.

Degradation and an error signature are evidence of a *problem*. A rollback needs evidence
about a *deployment*: that one happened, that it happened before things broke, and that
the breakage followed it. A restart needs evidence about a *mechanism*: that the failure
is the kind of wedged in-process state a restart clears, and not a configuration or
credential fault that will survive it untouched.

So policy-v2 asks each action its own questions. Both paths are ordinary predicates over
typed fixture records — no rules engine, no DSL, and emphatically no model. Asking an LLM
"is a restart appropriate here?" would hand the decision back to the thing policy exists
to check.

v1 remains in `policy.py`, unchanged: the recorded M9 results are attributable to it, and
a superseded policy that quietly changes is a benchmark that lies.
"""

from collections.abc import Sequence
from datetime import timedelta

from app.actions.mechanisms import (
    RESTART_ADDRESSABLE,
    RESTART_CONTRAINDICATED,
    FailureMechanism,
    mechanism_of,
)
from app.actions.models import (
    ActionPolicyDecision,
    ActionTarget,
    ActionType,
    PolicyDecision,
    PolicyReason,
)
from app.actions.rules import (
    ACTION_RISK,
    BLOCKED_INCIDENT_STATUSES,
    DEPLOYMENT_BLAST_WINDOW,
    REQUIRED_APPROVALS,
)
from app.investigation.models import (
    EvidenceItem,
    EvidenceKind,
    InvestigationOutput,
    RemediationRecommendation,
    RiskLevel,
)
from app.investigation.tools import OperationsFixtures


def evaluate_action_policy_v2(
    *,
    recommendation: RemediationRecommendation,
    investigation: InvestigationOutput,
    evidence: Sequence[EvidenceItem],
    operations: OperationsFixtures,
    incident_status: str | None = None,
    service_id: str | None = None,
) -> ActionPolicyDecision:
    """Decides whether a recommendation may become an approvable action.

    Same signature and same result type as v1, so the control plane around it — proposal,
    approval, execution, audit — is untouched by this milestone.
    """
    reasons: list[PolicyReason] = []

    action_type = _known_action_type(recommendation, reasons)
    abstention_ok = _check_abstention(investigation, reasons)
    incident_ok = _check_incident_status(incident_status, reasons)
    valid_ids, evidence_ok = _check_evidence_exists(recommendation, evidence, reasons)

    cited = [item for item in evidence if item.id in set(valid_ids)]

    target: ActionTarget | None = None
    target_ok = False
    support_ok = False

    if action_type is ActionType.ROLLBACK_DEPLOYMENT:
        target, target_ok = _rollback_target(cited, operations, reasons)
        support_ok = _rollback_support(cited, operations, target, reasons)
    elif action_type is ActionType.RESTART_SERVICE:
        target, target_ok = _service_target(service_id, operations, reasons)
        support_ok = _restart_support(cited, operations, target, reasons)
    elif action_type is ActionType.ROTATE_CREDENTIAL:
        target, target_ok = _service_target(service_id, operations, reasons)
        support_ok = _rotate_support(cited, reasons)

    risk = ACTION_RISK.get(action_type, RiskLevel.HIGH) if action_type else RiskLevel.HIGH

    eligible = all(
        (
            action_type is not None,
            abstention_ok,
            incident_ok,
            evidence_ok,
            target_ok,
            support_ok,
        )
    )
    if eligible:
        decision = PolicyDecision.ELIGIBLE_FOR_APPROVAL
    elif action_type is not None and target_ok and evidence_ok and not support_ok:
        # The action is permitted against a real target; what is missing is evidence that
        # *this* action addresses the failure. Materially different from "not allowed",
        # and the operator should be told which it is.
        decision = PolicyDecision.REQUIRES_MORE_EVIDENCE
    else:
        decision = PolicyDecision.REJECTED_BY_POLICY

    return ActionPolicyDecision(
        eligible=eligible,
        decision=decision,
        reasons=tuple(reasons),
        effective_risk=risk,
        required_approvals=REQUIRED_APPROVALS,
        validated_target=target if eligible else None,
        validated_evidence_ids=tuple(valid_ids),
        evidence_source_kinds=tuple(sorted({item.kind.value for item in cited})),
    )


# --- checks shared by every action ---------------------------------------------------


def _known_action_type(
    recommendation: RemediationRecommendation, reasons: list[PolicyReason]
) -> ActionType | None:
    try:
        action_type = ActionType(recommendation.action_type.value)
    except ValueError:
        reasons.append(
            PolicyReason(
                check="allowed_action_type",
                passed=False,
                detail=(
                    f"{recommendation.action_type.value} has no executor in this "
                    "system, so it cannot be made actionable"
                ),
            )
        )
        return None
    reasons.append(
        PolicyReason(
            check="allowed_action_type",
            passed=True,
            detail=f"{action_type.value} is a supported action",
        )
    )
    return action_type


def _check_abstention(
    investigation: InvestigationOutput, reasons: list[PolicyReason]
) -> bool:
    passed = not investigation.abstain
    reasons.append(
        PolicyReason(
            check="investigation_committed",
            passed=passed,
            detail=(
                "the investigation reached a conclusion"
                if passed
                else "the investigation abstained; an unexplained incident cannot "
                "justify a consequential action"
            ),
        )
    )
    return passed


def _check_incident_status(status: str | None, reasons: list[PolicyReason]) -> bool:
    passed = status is None or status not in BLOCKED_INCIDENT_STATUSES
    reasons.append(
        PolicyReason(
            check="incident_actionable",
            passed=passed,
            detail=(
                f"incident status {status or 'open'} accepts actions"
                if passed
                else f"incident is {status}; acting on it now would be a change "
                "nobody asked for"
            ),
        )
    )
    return passed


def _check_evidence_exists(
    recommendation: RemediationRecommendation,
    evidence: Sequence[EvidenceItem],
    reasons: list[PolicyReason],
) -> tuple[list[str], bool]:
    known = {item.id for item in evidence}
    cited = list(recommendation.supporting_evidence_ids)
    unknown = sorted(set(cited) - known)
    valid = [value for value in cited if value in known]

    passed = bool(valid) and not unknown
    detail = (
        f"all {len(valid)} cited evidence ids exist"
        if passed
        else f"cited evidence not present in this investigation: {', '.join(unknown)}"
        if unknown
        else "the recommendation cites no evidence from this investigation"
    )
    reasons.append(
        PolicyReason(
            check="evidence_exists",
            passed=passed,
            detail=detail,
            evidence_ids=tuple(valid),
        )
    )
    return valid, passed


# --- targets --------------------------------------------------------------------------


def _rollback_target(
    cited: Sequence[EvidenceItem],
    operations: OperationsFixtures,
    reasons: list[PolicyReason],
) -> tuple[ActionTarget | None, bool]:
    """The deployment to undo, derived from cited evidence and matched to a real record.

    Built here rather than read from the model, so an invented deployment id has no route
    in: it must appear as validated evidence *and* match a fixture.
    """
    deployments = {record.id: record for record in operations.deployments}
    candidates = [
        item
        for item in cited
        if item.kind is EvidenceKind.DEPLOYMENT and item.source_id in deployments
    ]
    if not candidates:
        named = [item.source_id for item in cited if item.kind is EvidenceKind.DEPLOYMENT]
        reasons.append(
            PolicyReason(
                check="target_exists",
                passed=False,
                detail=(
                    "no cited deployment matches a known deployment record "
                    f"({', '.join(named) or 'none cited'})"
                ),
            )
        )
        return None, False

    item = candidates[0]
    match = deployments[item.source_id]
    reasons.append(
        PolicyReason(
            check="target_exists",
            passed=True,
            detail=f"deployment {match.id} ({match.service_id} {match.version}) exists",
            evidence_ids=(item.id,),
        )
    )
    return (
        ActionTarget(
            service_id=match.service_id, deployment_id=match.id, version=match.version
        ),
        True,
    )


def _service_target(
    service_id: str | None,
    operations: OperationsFixtures,
    reasons: list[PolicyReason],
) -> tuple[ActionTarget | None, bool]:
    known = {record.service_id for record in operations.health} | {
        record.service_id for record in operations.deployments
    }
    if service_id is None or service_id not in known:
        reasons.append(
            PolicyReason(
                check="target_exists",
                passed=False,
                detail=(
                    f"service {service_id or 'unknown'} is not a known Northstar service"
                ),
            )
        )
        return None, False
    reasons.append(
        PolicyReason(
            check="target_exists", passed=True, detail=f"service {service_id} exists"
        )
    )
    return ActionTarget(service_id=service_id), True


# --- rollback: is this incident actually attributable to that deployment? --------------


def _rollback_support(
    cited: Sequence[EvidenceItem],
    operations: OperationsFixtures,
    target: ActionTarget | None,
    reasons: list[PolicyReason],
) -> bool:
    """Rollback needs a causal story about a deployment, not a coincidence in time.

    Three things must hold together: the deployment came *before* the trouble, within a
    window where blame is plausible; the service degraded *after* it; and the errors on
    that service are not pointing somewhere a rollback cannot reach.
    """
    if target is None or target.deployment_id is None:
        return False

    deployment = next(
        record for record in operations.deployments if record.id == target.deployment_id
    )
    service = deployment.service_id

    onset = _incident_onset(cited)
    deployment_item = next(
        (item for item in cited if item.source_id == deployment.id), None
    )

    # 1. Temporal ordering, with a window. A deployment four days earlier is not the
    #    reason something broke this afternoon, however tempting the story.
    if onset is None:
        timing_ok = False
        timing_detail = "no incident onset time is available to compare the deployment to"
    elif deployment.deployed_at > onset:
        timing_ok = False
        timing_detail = (
            f"deployment {deployment.id} happened after the incident began "
            f"({deployment.deployed_at.isoformat()} > {onset.isoformat()}); "
            "it cannot be the cause"
        )
    else:
        gap = onset - deployment.deployed_at
        timing_ok = gap <= DEPLOYMENT_BLAST_WINDOW
        minutes = int(gap.total_seconds() // 60)
        timing_detail = (
            f"deployment preceded incident onset by {_humanise(minutes)}"
            if timing_ok
            else (
                f"deployment preceded incident onset by {_humanise(minutes)}, beyond the "
                f"{_humanise(int(DEPLOYMENT_BLAST_WINDOW.total_seconds() // 60))} "
                "window in which a deployment is a plausible cause"
            )
        )
    reasons.append(
        PolicyReason(
            check="deployment_precedes_incident",
            passed=timing_ok,
            detail=timing_detail,
            evidence_ids=tuple(
                filter(None, (deployment_item.id if deployment_item else None,))
            ),
        )
    )

    # 2. Degradation after the deployment. A service that was already unhealthy before
    #    the change was not broken by the change.
    health, health_ids = _cited_health(cited, operations, service)
    degraded_after = [
        record
        for record in health
        if record.status != "healthy" and record.observed_at >= deployment.deployed_at
    ]
    degraded_before = [
        record
        for record in health
        if record.status != "healthy" and record.observed_at < deployment.deployed_at
    ]
    if degraded_after and not degraded_before:
        health_ok, health_detail = True, (
            f"{service} health degraded after the deployment"
        )
    elif degraded_after and degraded_before:
        health_ok, health_detail = False, (
            f"{service} was already degraded before {deployment.id}; the deployment "
            "did not start this"
        )
    else:
        health_ok, health_detail = False, (
            f"no degraded health reading for {service} after the deployment"
        )
    reasons.append(
        PolicyReason(
            check="degradation_follows_deployment",
            passed=health_ok,
            detail=health_detail,
            evidence_ids=health_ids,
        )
    )

    # 3. A technical symptom on the changed service. Rolling back on ticket complaints
    #    alone means undoing a release because users were unhappy in the same hour.
    errors, error_ids = _cited_errors(cited, operations, service)
    symptom_ok = bool(errors)
    reasons.append(
        PolicyReason(
            check="error_symptom_on_changed_service",
            passed=symptom_ok,
            detail=(
                f"{service} is emitting {', '.join(sorted(r.code for r in errors))}"
                if symptom_ok
                else f"no error signature recorded on {service} to attribute to the release"
            ),
            evidence_ids=error_ids,
        )
    )

    # 4. No dominant cause pointing elsewhere. An external dependency outage is not
    #    fixed by rolling back our own code, whatever else lines up.
    mechanisms = {mechanism_of(record.code) for record in errors}
    conflicting = mechanisms & {FailureMechanism.EXTERNAL_DEPENDENCY}
    no_conflict = not conflicting
    reasons.append(
        PolicyReason(
            check="no_conflicting_dominant_cause",
            passed=no_conflict,
            detail=(
                "no evidence points to a cause a rollback would not address"
                if no_conflict
                else "the error signature points to "
                f"{', '.join(sorted(m.value for m in conflicting))}, which a rollback "
                "of this service would not address"
            ),
            evidence_ids=error_ids,
        )
    )

    return timing_ok and health_ok and symptom_ok and no_conflict


# --- restart: does a restart address what is actually failing? ------------------------


def _restart_support(
    cited: Sequence[EvidenceItem],
    operations: OperationsFixtures,
    target: ActionTarget | None,
    reasons: list[PolicyReason],
) -> bool:
    """Restart needs a mechanism a restart clears — not merely a broken service.

    This is the check `action-policy-v1` was missing. Degradation plus an error code met
    its generic bar, which is how three unsupported restarts became approvable.
    """
    if target is None:
        return False
    service = target.service_id

    # 1. The service is actually unhealthy right now. Restarting a healthy service is
    #    an outage we caused ourselves.
    health, health_ids = _cited_health(cited, operations, service)
    degraded = [record for record in health if record.status != "healthy"]
    degraded_ok = bool(degraded)
    reasons.append(
        PolicyReason(
            check="service_degraded",
            passed=degraded_ok,
            detail=(
                f"{service} health reads {degraded[0].status}"
                if degraded_ok
                else f"{service} is not reported unhealthy; a restart would cause the "
                "only disruption here"
            ),
            evidence_ids=health_ids,
        )
    )

    errors, error_ids = _cited_errors(cited, operations, service)
    mechanisms = {record.code: mechanism_of(record.code) for record in errors}

    # 2. The positive signal. Something must indicate wedged runtime state — a stalled
    #    worker, a missed heartbeat, exhausted memory. "Degraded" on its own is the
    #    absence of this, not a weak form of it.
    addressable = {
        code: mech for code, mech in mechanisms.items() if mech in RESTART_ADDRESSABLE
    }
    relevance_ok = bool(addressable)
    reasons.append(
        PolicyReason(
            check="transient_runtime_failure",
            passed=relevance_ok,
            detail=(
                f"{', '.join(sorted(addressable))} indicates "
                f"{', '.join(sorted({m.value for m in addressable.values()}))} state, "
                "which a restart clears"
                if relevance_ok
                else "nothing indicates the wedged process state a restart addresses; "
                "a degraded service and an error code do not by themselves make a "
                "restart the right action"
            ),
            evidence_ids=error_ids,
        )
    )

    # 3. Contraindications. A restart reloads the same configuration and re-reads the
    #    same credentials, so those failures come straight back — having cost an outage.
    blocked = {
        code: mech for code, mech in mechanisms.items() if mech in RESTART_CONTRAINDICATED
    }
    mechanism_ok = not blocked
    reasons.append(
        PolicyReason(
            check="failure_mechanism_not_excluded",
            passed=mechanism_ok,
            detail=(
                "no configuration, credential, permission, data or dependency failure "
                "is implicated"
                if mechanism_ok
                else f"{', '.join(sorted(blocked))} indicates "
                f"{', '.join(sorted({m.value for m in blocked.values()}))}, which "
                "survives a restart untouched"
            ),
            evidence_ids=error_ids,
        )
    )

    # 4. A recent deployment that explains the degradation makes rollback the correct
    #    action, and a restart the one that hides the problem until it recurs.
    onset = _incident_onset(cited)
    implicated = [
        record
        for record in operations.deployments
        if record.service_id == service
        and onset is not None
        and record.deployed_at <= onset
        and onset - record.deployed_at <= DEPLOYMENT_BLAST_WINDOW
    ]
    deployment_ok = not implicated
    reasons.append(
        PolicyReason(
            check="no_implicated_deployment",
            passed=deployment_ok,
            detail=(
                "no recent deployment explains this degradation"
                if deployment_ok
                else f"{implicated[0].id} shipped shortly before onset; if that caused "
                "this, a rollback addresses it and a restart only defers it"
            ),
            evidence_ids=tuple(
                item.id
                for item in cited
                if item.kind is EvidenceKind.DEPLOYMENT
                and item.source_id in {record.id for record in implicated}
            ),
        )
    )

    return degraded_ok and relevance_ok and mechanism_ok and deployment_ok


def _rotate_support(cited: Sequence[EvidenceItem], reasons: list[PolicyReason]) -> bool:
    """Credential rotation needs a credential failure.

    No executor implements rotation in this prototype, so this exists to keep the action
    explicit rather than silently generic. It requires the mechanism it claims to fix.
    """
    error_ids = tuple(item.id for item in cited if item.kind is EvidenceKind.ERROR)
    codes = [item.source_id for item in cited if item.kind is EvidenceKind.ERROR]
    implicated = [
        code
        for code in codes
        if mechanism_of(code)
        in {FailureMechanism.AUTHENTICATION, FailureMechanism.CONFIGURATION}
    ]
    passed = bool(implicated)
    reasons.append(
        PolicyReason(
            check="credential_failure_implicated",
            passed=passed,
            detail=(
                f"{', '.join(sorted(implicated))} indicates a credential or trust failure"
                if passed
                else "no credential or trust failure is implicated, so rotating one "
                "addresses nothing observed here"
            ),
            evidence_ids=error_ids,
        )
    )
    return passed


# --- helpers ---------------------------------------------------------------------------


def _cited_errors(
    cited: Sequence[EvidenceItem], operations: OperationsFixtures, service: str
):
    """Error records the recommendation actually cited, matched to real records.

    Reading `operations.errors` directly would let a recommendation citing nothing but a
    past incident inherit the whole service's error picture — the recommendation would be
    judged on evidence it never claimed. Policy scores the case that was made.
    """
    ids = {
        item.source_id: item.id for item in cited if item.kind is EvidenceKind.ERROR
    }
    records = [
        record
        for record in operations.errors
        if record.service_id == service and record.code in ids
    ]
    return records, tuple(ids[record.code] for record in records)


def _cited_health(
    cited: Sequence[EvidenceItem], operations: OperationsFixtures, service: str
):
    """Health snapshots the recommendation cited, matched to real records."""
    ids = tuple(
        item.id
        for item in cited
        if item.kind is EvidenceKind.HEALTH and item.source_id == service
    )
    records = (
        [record for record in operations.health if record.service_id == service]
        if ids
        else []
    )
    return records, ids


# Evidence that dates the *symptom*. A deployment is the suspected cause and must never
# set the onset time: letting it do so makes "the deployment came before the trouble"
# trivially true with a gap of zero, which is a check that always passes.
ONSET_KINDS = frozenset(
    {
        EvidenceKind.CORRELATION,
        EvidenceKind.TICKET,
        EvidenceKind.HEALTH,
        EvidenceKind.ERROR,
    }
)


def _incident_onset(cited: Sequence[EvidenceItem]):
    """When the trouble started, from evidence rather than wall-clock now.

    Correlation evidence carries the candidate's first-seen time and is preferred. Failing
    that, the earliest dated *symptom* stands in. Returning None when nothing qualifies is
    deliberate: the temporal checks then fail rather than guess, so an undated case cannot
    buy itself a rollback.
    """
    correlation = [
        item.observed_at
        for item in cited
        if item.kind is EvidenceKind.CORRELATION and item.observed_at is not None
    ]
    if correlation:
        return min(correlation)
    symptoms = [
        item.observed_at
        for item in cited
        if item.kind in ONSET_KINDS and item.observed_at is not None
    ]
    return min(symptoms) if symptoms else None


def _humanise(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes}m"
    hours, rest = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h{rest:02d}m" if rest else f"{hours}h"
    days, rest_hours = divmod(hours, 24)
    return f"{days}d{rest_hours}h" if rest_hours else f"{days}d"


__all__ = ["evaluate_action_policy_v2", "DEPLOYMENT_BLAST_WINDOW", "timedelta"]
