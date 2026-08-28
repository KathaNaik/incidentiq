"""Deterministic action policy.

The gate between "a model recommended this" and "a human may approve this". Every check
is a plain predicate over typed data, and every check reports itself — a rejection that
cannot be explained is not much better than an unexplained approval.

No model runs here. The reasons an operator reads are assembled from these checks.
"""

from collections.abc import Sequence

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
    MIN_EVIDENCE_KINDS,
    NON_CAUSAL_EVIDENCE_KINDS,
    REQUIRED_APPROVALS,
    REQUIRED_EVIDENCE_KINDS,
)
from app.investigation.models import (
    EvidenceItem,
    InvestigationOutput,
    RemediationRecommendation,
    RiskLevel,
)
from app.investigation.tools import OperationsFixtures


def evaluate_action_policy(
    *,
    recommendation: RemediationRecommendation,
    investigation: InvestigationOutput,
    evidence: Sequence[EvidenceItem],
    operations: OperationsFixtures,
    incident_status: str | None = None,
    service_id: str | None = None,
) -> ActionPolicyDecision:
    """Decides whether a recommendation may become an approvable action."""
    reasons: list[PolicyReason] = []

    action_type = _known_action_type(recommendation, reasons)
    abstention_ok = _check_abstention(investigation, reasons)
    incident_ok = _check_incident_status(incident_status, reasons)
    valid_ids, evidence_ok = _check_evidence_exists(recommendation, evidence, reasons)
    kinds = _kinds_of(valid_ids, evidence)

    target = None
    target_ok = False
    sufficiency_ok = False
    if action_type is not None:
        target, target_ok = _check_target(
            action_type, valid_ids, evidence, operations, service_id, reasons
        )
        sufficiency_ok = _check_evidence_sufficiency(action_type, kinds, reasons)

    risk = ACTION_RISK.get(action_type, RiskLevel.HIGH) if action_type else RiskLevel.HIGH

    eligible = all(
        (action_type is not None, abstention_ok, incident_ok, evidence_ok, target_ok, sufficiency_ok)
    )
    if eligible:
        decision = PolicyDecision.ELIGIBLE_FOR_APPROVAL
    elif evidence_ok and not sufficiency_ok and action_type is not None and target_ok:
        # Everything checks out except the weight of evidence — a materially different
        # outcome from "this is not allowed", and worth telling the operator apart.
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
        evidence_source_kinds=tuple(sorted(kinds)),
    )


def _known_action_type(
    recommendation: RemediationRecommendation, reasons: list[PolicyReason]
) -> ActionType | None:
    """The recommendation's action must be one this system can actually perform.

    The investigator's vocabulary is wider than the executor's. Recommending something
    unimplemented is not a bug in the model; making it approvable would be a bug here.
    """
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
                else f"incident is {status}; acting on it now would be a change nobody asked for"
            ),
        )
    )
    return passed


def _check_evidence_exists(
    recommendation: RemediationRecommendation,
    evidence: Sequence[EvidenceItem],
    reasons: list[PolicyReason],
) -> tuple[list[str], bool]:
    """Cited evidence must exist in the investigation's validated registry.

    M8 validation already rejected invented ids at the model boundary. This is the
    second gate, on the path that actually causes something to happen.
    """
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
        PolicyReason(check="evidence_exists", passed=passed, detail=detail)
    )
    return valid, passed


def _kinds_of(evidence_ids: Sequence[str], evidence: Sequence[EvidenceItem]) -> set[str]:
    by_id = {item.id: item for item in evidence}
    return {by_id[value].kind.value for value in evidence_ids if value in by_id}


def _check_evidence_sufficiency(
    action_type: ActionType, kinds: set[str], reasons: list[PolicyReason]
) -> bool:
    """Enough independent evidence, of the right kinds."""
    causal = kinds - NON_CAUSAL_EVIDENCE_KINDS
    minimum = MIN_EVIDENCE_KINDS.get(action_type, 2)

    if not causal:
        reasons.append(
            PolicyReason(
                check="independent_evidence",
                passed=False,
                detail=(
                    "only a similar past incident supports this; precedent is not "
                    "evidence of the current cause"
                ),
            )
        )
        return False

    enough = len(causal) >= minimum
    reasons.append(
        PolicyReason(
            check="independent_evidence",
            passed=enough,
            detail=(
                f"{len(causal)} independent evidence kinds ({', '.join(sorted(causal))})"
                if enough
                else f"{len(causal)} independent evidence kind(s) "
                f"({', '.join(sorted(causal))}); {minimum} required"
            ),
        )
    )

    required = REQUIRED_EVIDENCE_KINDS.get(action_type)
    if required:
        has_required = required <= kinds
        reasons.append(
            PolicyReason(
                check="required_evidence_kind",
                passed=has_required,
                detail=(
                    f"{', '.join(sorted(required))} evidence present"
                    if has_required
                    else f"a {action_type.value} needs {', '.join(sorted(required))} "
                    "evidence identifying what to undo"
                ),
            )
        )
        return enough and has_required
    return enough


def _check_target(
    action_type: ActionType,
    evidence_ids: Sequence[str],
    evidence: Sequence[EvidenceItem],
    operations: OperationsFixtures,
    service_id: str | None,
    reasons: list[PolicyReason],
) -> tuple[ActionTarget | None, bool]:
    """Builds the target from *evidence*, and checks it against real records.

    The target is derived here rather than taken from the model, so an invented
    deployment id has no path in: it would have to exist as cited evidence, and that
    evidence would have to match a real fixture record.
    """
    by_id = {item.id: item for item in evidence}
    cited = [by_id[value] for value in evidence_ids if value in by_id]

    if action_type is ActionType.ROLLBACK_DEPLOYMENT:
        deployment_ids = [
            item.source_id for item in cited if item.kind.value == "deployment"
        ]
        known = {record.id: record for record in operations.deployments}
        match = next((known[value] for value in deployment_ids if value in known), None)
        if match is None:
            reasons.append(
                PolicyReason(
                    check="target_exists",
                    passed=False,
                    detail=(
                        "no deployment among the cited evidence matches a known "
                        f"deployment record ({', '.join(deployment_ids) or 'none cited'})"
                    ),
                )
            )
            return None, False
        reasons.append(
            PolicyReason(
                check="target_exists",
                passed=True,
                detail=f"deployment {match.id} ({match.service_id} {match.version}) exists",
            )
        )
        return (
            ActionTarget(
                service_id=match.service_id,
                deployment_id=match.id,
                version=match.version,
            ),
            True,
        )

    # Service-scoped actions.
    known_services = {record.service_id for record in operations.health} | {
        record.service_id for record in operations.deployments
    }
    if service_id is None or service_id not in known_services:
        reasons.append(
            PolicyReason(
                check="target_exists",
                passed=False,
                detail=f"service {service_id or 'unknown'} is not a known Northstar service",
            )
        )
        return None, False

    reasons.append(
        PolicyReason(
            check="target_exists", passed=True, detail=f"service {service_id} exists"
        )
    )
    return ActionTarget(service_id=service_id), True
