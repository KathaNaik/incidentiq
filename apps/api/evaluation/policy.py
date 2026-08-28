"""Action-policy evaluation.

Policy is deterministic business logic, so unlike the model suites this one should score
100%. Anything less is a bug, not a limitation — which is exactly why it is worth
measuring separately from the investigator: a model that recommends badly is tolerable
if policy refuses to act on it, and that claim needs evidence.

Cases are authored in code rather than JSON because each one constructs a small
investigation and evidence set; a fixture format would obscure what is being tested.
"""

from datetime import UTC, datetime

from app.actions import (
    ActionRepository,
    ActionStatus,
    InvalidTransitionError,
    approve_action,
    evaluate_action_policy,
    execute_action,
    propose_action,
    reject_action,
)
from app.actions.models import PolicyDecision
from app.investigation.models import (
    EvidenceItem,
    EvidenceKind,
    Hypothesis,
    InvestigationOutput,
    InvestigationResult,
    InvestigationRun,
    NextStepAction,
    RecommendedNextStep,
    RemediationAction,
    RemediationRecommendation,
    RiskLevel,
)
from app.investigation.tools import OperationsFixtures
from evaluation.models import CaseFailure, EvalReport, MetricSummary

NOW = datetime(2026, 8, 24, 9, 30, tzinfo=UTC)


def _evidence(
    evidence_id: str,
    kind: EvidenceKind,
    source_id: str,
    observed_at: datetime | None = None,
) -> EvidenceItem:
    return EvidenceItem(
        id=evidence_id,
        kind=kind,
        summary="evidence",
        source_id=source_id,
        provenance="Northstar Cloud synthetic operations fixture",
        observed_at=observed_at,
    )


# Timestamps match the real Northstar records these stand in for, because action-policy-v2
# reasons about ordering: a deployment is only a suspect if it shipped before the trouble
# started. Undated evidence makes that unanswerable, and policy fails closed rather than
# assuming the ordering it needs.
ONSET = datetime(2026, 8, 24, 9, 0, tzinfo=UTC)

CORRELATION = _evidence("correlation:cand-TEST", EvidenceKind.CORRELATION, "cand-TEST", ONSET)
DEPLOYMENT = _evidence(
    "deployment:DEP-2041",
    EvidenceKind.DEPLOYMENT,
    "DEP-2041",
    datetime(2026, 8, 24, 8, 52, tzinfo=UTC),
)
HEALTH = _evidence(
    "health:svc-auth@x",
    EvidenceKind.HEALTH,
    "svc-auth",
    datetime(2026, 8, 24, 9, 10, tzinfo=UTC),
)
ERROR = _evidence(
    "error:ERR_SAML_INVALID_ASSERTION",
    EvidenceKind.ERROR,
    "ERR_SAML_INVALID_ASSERTION",
    datetime(2026, 8, 24, 9, 2, tzinfo=UTC),
)
HISTORICAL = _evidence("historical:NS-HIST-0002", EvidenceKind.HISTORICAL, "NS-HIST-0002")
GHOST_DEPLOYMENT = _evidence("deployment:DEP-9999", EvidenceKind.DEPLOYMENT, "DEP-9999")


def _investigation(
    *,
    remediation: RemediationRecommendation | None,
    abstain: bool = False,
    evidence: tuple[EvidenceItem, ...],
    incident_id: str = "cand-TEST",
) -> InvestigationResult:
    return InvestigationResult(
        incident_id=incident_id,
        version="investigation-v1",
        output=InvestigationOutput(
            hypotheses=()
            if abstain
            else (
                Hypothesis(
                    summary="The deployment introduced a validation regression.",
                    confidence=0.8,
                    supporting_evidence_ids=(evidence[0].id,),
                ),
            ),
            missing_evidence=("logs",) if abstain else (),
            recommended_next_step=RecommendedNextStep(
                action_type=NextStepAction.INSPECT_LOGS,
                description="Inspect validation logs.",
                rationale="Confirms the failure mode.",
            ),
            remediation=remediation,
            abstain=abstain,
        ),
        evidence=evidence,
        run=InvestigationRun(
            model="stub", prompt_version="investigation-v1",
            evidence_ids=tuple(item.id for item in evidence),
            latency_ms=1, started_at=NOW,
        ),
    )


def _remediation(
    action: RemediationAction, evidence_ids: tuple[str, ...]
) -> RemediationRecommendation:
    return RemediationRecommendation(
        action_type=action,
        description="Roll back the deployment.",
        risk=RiskLevel.LOW,  # deliberately understated; policy assigns its own
        supporting_evidence_ids=evidence_ids,
    )


def run_policy_evaluation(operations: OperationsFixtures) -> EvalReport:
    """Ten authored cases over the policy and the workflow it guards."""
    results: list[tuple[str, bool, str]] = []
    failures: list[CaseFailure] = []

    def check(case_id: str, description: str, passed: bool, detail: str) -> None:
        results.append((case_id, passed, description))
        if not passed:
            failures.append(
                CaseFailure(
                    case_id=case_id,
                    metric="policy",
                    expected=description,
                    predicted=None,
                    status="policy_case_failed",
                    explanation=detail,
                    signals=(),
                    text=description,
                )
            )

    # 1 — valid rollback: deployment + health + error, investigation committed.
    valid = _investigation(
        remediation=_remediation(
            RemediationAction.ROLLBACK_DEPLOYMENT,
            (DEPLOYMENT.id, HEALTH.id, ERROR.id),
        ),
        evidence=(DEPLOYMENT, HEALTH, ERROR),
    )
    decision = _policy(valid, operations, "svc-auth")
    check(
        "P01",
        "valid rollback is eligible for approval",
        decision.eligible and decision.decision is PolicyDecision.ELIGIBLE_FOR_APPROVAL,
        f"decision={decision.decision.value}",
    )
    check(
        "P01b",
        "policy assigns rollback high risk regardless of the model's claim",
        decision.effective_risk is RiskLevel.HIGH,
        f"effective_risk={decision.effective_risk.value}",
    )

    # 2 — rollback naming a deployment that does not exist.
    ghost = _investigation(
        remediation=_remediation(
            RemediationAction.ROLLBACK_DEPLOYMENT,
            (GHOST_DEPLOYMENT.id, HEALTH.id),
        ),
        evidence=(GHOST_DEPLOYMENT, HEALTH),
    )
    decision = _policy(ghost, operations, "svc-auth")
    check(
        "P02",
        "rollback of a nonexistent deployment is refused",
        not decision.eligible,
        f"decision={decision.decision.value}",
    )

    # 3 — supported only by a similar past incident.
    precedent_only = _investigation(
        remediation=_remediation(
            RemediationAction.ROLLBACK_DEPLOYMENT, (HISTORICAL.id,)
        ),
        evidence=(HISTORICAL,),
    )
    decision = _policy(precedent_only, operations, "svc-auth")
    check(
        "P03",
        "precedent alone does not justify a consequential action",
        not decision.eligible,
        f"decision={decision.decision.value}",
    )

    # 4 — remediation while the investigation abstained.
    abstaining = _investigation(
        remediation=_remediation(
            RemediationAction.ROLLBACK_DEPLOYMENT,
            (DEPLOYMENT.id, HEALTH.id, ERROR.id),
        ),
        abstain=True,
        evidence=(DEPLOYMENT, HEALTH, ERROR),
    )
    decision = _policy(abstaining, operations, "svc-auth")
    check(
        "P04",
        "an abstaining investigation cannot produce an approvable action",
        not decision.eligible
        and any(r.check == "investigation_committed" and not r.passed for r in decision.reasons),
        f"decision={decision.decision.value}",
    )

    # 5 — valid restart on a known service.
    restart = _investigation(
        remediation=_remediation(
            RemediationAction.RESTART_SERVICE, (HEALTH.id, ERROR.id)
        ),
        evidence=(HEALTH, ERROR),
    )
    decision = _policy(restart, operations, "svc-auth")
    check(
        "P05",
        "valid restart is eligible and rated medium risk",
        decision.eligible and decision.effective_risk is RiskLevel.MEDIUM,
        f"eligible={decision.eligible} risk={decision.effective_risk.value}",
    )

    # 6 — incident already resolved.
    decision = evaluate_action_policy(
        recommendation=valid.output.remediation,
        investigation=valid.output,
        evidence=valid.evidence,
        operations=operations,
        incident_status="resolved",
        service_id="svc-auth",
    )
    check(
        "P06",
        "no action against an already-resolved incident",
        not decision.eligible,
        f"decision={decision.decision.value}",
    )

    # 7 — an action type with no executor.
    unsupported = _investigation(
        remediation=_remediation(
            RemediationAction.DISABLE_FEATURE_FLAG, (DEPLOYMENT.id, HEALTH.id)
        ),
        evidence=(DEPLOYMENT, HEALTH),
    )
    decision = _policy(unsupported, operations, "svc-auth")
    check(
        "P07",
        "a recommended action with no executor is refused",
        not decision.eligible,
        f"decision={decision.decision.value}",
    )

    # 8, 9, 10 — the workflow itself.
    repository = ActionRepository()
    action = propose_action(
        investigation=valid, operations=operations, repository=repository,
        service_id="svc-auth",
    )
    approved = approve_action(action_id=action.id, repository=repository)
    executed = execute_action(
        action_id=action.id, repository=repository, operations=operations
    )
    check(
        "P10",
        "approved valid action executes and succeeds",
        executed.status is ActionStatus.SUCCEEDED and executed.execution is not None,
        f"status={executed.status.value}",
    )
    check(
        "P10b",
        "execution is labelled simulated",
        executed.execution is not None and executed.execution.simulated,
        "execution result missing the simulated flag",
    )

    repeat = execute_action(
        action_id=action.id, repository=repository, operations=operations
    )
    check(
        "P08",
        "a repeated execute does not run the action twice",
        repeat.execution is not None
        and executed.execution is not None
        and repeat.execution.executed_at == executed.execution.executed_at,
        "the second execute produced a new execution result",
    )

    rejected_repo = ActionRepository()
    rejected_action = propose_action(
        investigation=valid, operations=rejected_repo and operations,
        repository=rejected_repo, service_id="svc-auth",
    )
    reject_action(action_id=rejected_action.id, repository=rejected_repo)
    try:
        execute_action(
            action_id=rejected_action.id, repository=rejected_repo, operations=operations
        )
        blocked = False
    except InvalidTransitionError:
        blocked = True
    check("P09", "a rejected action cannot be executed", blocked, "execution was allowed")

    # Also confirm approving something policy refused is impossible.
    refused_repo = ActionRepository()
    refused = propose_action(
        investigation=precedent_only, operations=operations, repository=refused_repo,
        service_id="svc-auth",
    )
    try:
        approve_action(action_id=refused.id, repository=refused_repo)
        approvable = True
    except InvalidTransitionError:
        approvable = False
    check(
        "P03b",
        "a policy-rejected action has no approval path",
        not approvable and refused.status is ActionStatus.POLICY_REJECTED,
        f"status={refused.status.value}",
    )

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    unsafe_allowed = sum(
        1
        for case_id, ok, _ in results
        if case_id in {"P02", "P03", "P04", "P06", "P07", "P09", "P03b"} and not ok
    )
    valid_blocked = sum(
        1 for case_id, ok, _ in results if case_id in {"P01", "P05", "P10"} and not ok
    )

    return EvalReport(
        suite="action-policy",
        version="action-policy-v1",
        generated_at=datetime.now(UTC),
        case_count=total,
        metrics=(
            MetricSummary(
                name="policy_cases_passed",
                correct=passed,
                total=total,
                accuracy=round(passed / total, 4) if total else 0.0,
            ),
            MetricSummary(
                name="unsafe_action_allowed_rate",
                correct=unsafe_allowed,
                total=7,
                accuracy=round(unsafe_allowed / 7, 4),
            ),
            MetricSummary(
                name="valid_action_blocked_rate",
                correct=valid_blocked,
                total=3,
                accuracy=round(valid_blocked / 3, 4),
            ),
        ),
        confusion=(),
        failures=tuple(failures),
        notes=(
            "Policy is deterministic business logic; anything below 100% is a defect, "
            "not a limitation.",
            "Lower is better for both rate metrics — they count failures, not successes.",
            "Authored for IncidentIQ; no external dataset is involved.",
        ),
    )


def _policy(investigation: InvestigationResult, operations, service_id: str):
    return evaluate_action_policy(
        recommendation=investigation.output.remediation,
        investigation=investigation.output,
        evidence=investigation.evidence,
        operations=operations,
        service_id=service_id,
    )
