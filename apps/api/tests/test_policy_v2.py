"""Action-specific policy: the matrix that `action-policy-v1` could not separate.

Every case here is authored, deterministic, and offline. The operations fixtures are
built locally rather than added to the shipped Northstar demo data — a policy test needs
a service whose worker ran out of memory, and the demo does not, so inventing one here
keeps the test honest without inventing an incident for the product.

The recurring shape of these tests is one question: *given a service that is genuinely
broken, does the evidence support this particular action?* v1 answered by counting
evidence kinds and said yes to all of it.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.actions import evaluate_action_policy, evaluate_action_policy_v2
from app.actions.mechanisms import (
    RESTART_ADDRESSABLE,
    RESTART_CONTRAINDICATED,
    FailureMechanism,
    mechanism_of,
)
from app.actions.models import PolicyDecision
from app.actions.rules import ACTIVE_ACTIONS_VERSION, DEPLOYMENT_BLAST_WINDOW
from app.investigation.models import (
    EvidenceItem,
    EvidenceKind,
    Hypothesis,
    InvestigationOutput,
    NextStepAction,
    RecommendedNextStep,
    RemediationAction,
    RemediationRecommendation,
    RiskLevel,
)
from app.investigation.tools import (
    DeploymentRecord,
    ErrorSummary,
    OperationsFixtures,
    ServiceHealthSnapshot,
)

ONSET = datetime(2026, 8, 25, 13, 0, tzinfo=UTC)
SERVICE = "svc-test"


# --- builders -------------------------------------------------------------------------


def ev(
    evidence_id: str,
    kind: EvidenceKind,
    source_id: str,
    observed_at: datetime | None = None,
) -> EvidenceItem:
    return EvidenceItem(
        id=evidence_id,
        kind=kind,
        summary="authored policy case",
        source_id=source_id,
        provenance="authored test fixture",
        observed_at=observed_at,
    )


CORRELATION = ev("correlation:cand-P", EvidenceKind.CORRELATION, "cand-P", ONSET)


def operations(
    *,
    health_status: str = "degraded",
    health_at: datetime | None = None,
    error_codes: tuple[str, ...] = (),
    deployed_at: datetime | None = None,
    deployment_id: str = "DEP-P01",
) -> OperationsFixtures:
    """A minimal operational world containing exactly what a case needs."""
    deployments = (
        (
            DeploymentRecord(
                id=deployment_id,
                service_id=SERVICE,
                version="1.0.0",
                deployed_at=deployed_at,
                status="succeeded",
                change_summary="authored",
            ),
        )
        if deployed_at
        else ()
    )
    return OperationsFixtures(
        deployments=deployments,
        health=(
            ServiceHealthSnapshot(
                service_id=SERVICE,
                observed_at=health_at or ONSET + timedelta(minutes=10),
                status=health_status,
                signals=("authored signal",),
            ),
        ),
        errors=tuple(
            ErrorSummary(
                service_id=SERVICE,
                code=code,
                count=10,
                first_seen=ONSET,
                last_seen=ONSET + timedelta(minutes=30),
                sample_message="authored",
            )
            for code in error_codes
        ),
    )


def investigation(*, abstain: bool = False) -> InvestigationOutput:
    return InvestigationOutput(
        abstain=abstain,
        abstain_reason="authored" if abstain else None,
        hypotheses=()
        if abstain
        else (Hypothesis(summary="authored", confidence=0.8, supporting_evidence_ids=()),),
        missing_evidence=("authored",) if abstain else (),
        recommended_next_step=RecommendedNextStep(
            action_type=NextStepAction.INSPECT_LOGS,
            description="authored",
            rationale="authored",
        ),
        remediation=None,
    )


def decide(
    action: RemediationAction,
    evidence: tuple[EvidenceItem, ...],
    ops: OperationsFixtures,
    *,
    abstain: bool = False,
    service_id: str | None = SERVICE,
):
    recommendation = RemediationRecommendation(
        action_type=action,
        description="authored",
        risk=RiskLevel.LOW,
        supporting_evidence_ids=tuple(item.id for item in evidence),
    )
    return evaluate_action_policy_v2(
        recommendation=recommendation,
        investigation=investigation(abstain=abstain),
        evidence=evidence,
        operations=ops,
        service_id=service_id,
    )


def failed(decision) -> set[str]:
    return {reason.check for reason in decision.reasons if not reason.passed}


# --- rollback matrix ------------------------------------------------------------------


def test_rollback_valid_case_is_eligible() -> None:
    """1. Release, then degradation, then errors on the changed service."""
    ops = operations(
        error_codes=("ERR_SYNC_STALLED",), deployed_at=ONSET - timedelta(minutes=8)
    )
    evidence = (
        CORRELATION,
        ev("deployment:DEP-P01", EvidenceKind.DEPLOYMENT, "DEP-P01", ONSET - timedelta(minutes=8)),
        ev("health:svc-test", EvidenceKind.HEALTH, SERVICE, ONSET + timedelta(minutes=10)),
        ev("error:ERR_SYNC_STALLED", EvidenceKind.ERROR, "ERR_SYNC_STALLED", ONSET),
    )
    decision = decide(RemediationAction.ROLLBACK_DEPLOYMENT, evidence, ops)

    assert decision.eligible
    assert decision.decision is PolicyDecision.ELIGIBLE_FOR_APPROVAL
    assert decision.effective_risk is RiskLevel.HIGH, "risk comes from policy, not the model"
    assert decision.validated_target.deployment_id == "DEP-P01"


def test_rollback_blocked_when_deployment_long_predates_the_incident() -> None:
    """2. A release four days ago did not break something this afternoon."""
    old = ONSET - timedelta(days=4)
    ops = operations(error_codes=("ERR_SYNC_STALLED",), deployed_at=old)
    evidence = (
        CORRELATION,
        ev("deployment:DEP-P01", EvidenceKind.DEPLOYMENT, "DEP-P01", old),
        ev("health:svc-test", EvidenceKind.HEALTH, SERVICE, ONSET + timedelta(minutes=10)),
        ev("error:ERR_SYNC_STALLED", EvidenceKind.ERROR, "ERR_SYNC_STALLED", ONSET),
    )
    decision = decide(RemediationAction.ROLLBACK_DEPLOYMENT, evidence, ops)

    assert not decision.eligible
    assert "deployment_precedes_incident" in failed(decision)


def test_rollback_blocked_when_service_was_already_degraded_before_the_release() -> None:
    """3. The change cannot have caused what was already happening."""
    deployed = ONSET - timedelta(minutes=30)
    ops = operations(
        error_codes=("ERR_SYNC_STALLED",),
        deployed_at=deployed,
        health_at=deployed - timedelta(hours=1),
    )
    evidence = (
        CORRELATION,
        ev("deployment:DEP-P01", EvidenceKind.DEPLOYMENT, "DEP-P01", deployed),
        ev("health:svc-test", EvidenceKind.HEALTH, SERVICE, deployed - timedelta(hours=1)),
        ev("error:ERR_SYNC_STALLED", EvidenceKind.ERROR, "ERR_SYNC_STALLED", ONSET),
    )
    decision = decide(RemediationAction.ROLLBACK_DEPLOYMENT, evidence, ops)

    assert not decision.eligible
    assert "degradation_follows_deployment" in failed(decision)


def test_rollback_blocked_when_the_error_points_at_a_dependency() -> None:
    """4. Rolling back our code does not fix somebody else's outage."""
    ops = operations(
        error_codes=("ERR_UPSTREAM_TIMEOUT",), deployed_at=ONSET - timedelta(minutes=8)
    )
    evidence = (
        CORRELATION,
        ev("deployment:DEP-P01", EvidenceKind.DEPLOYMENT, "DEP-P01", ONSET - timedelta(minutes=8)),
        ev("health:svc-test", EvidenceKind.HEALTH, SERVICE, ONSET + timedelta(minutes=10)),
        ev("error:ERR_UPSTREAM_TIMEOUT", EvidenceKind.ERROR, "ERR_UPSTREAM_TIMEOUT", ONSET),
    )
    decision = decide(RemediationAction.ROLLBACK_DEPLOYMENT, evidence, ops)

    assert not decision.eligible
    assert "no_conflicting_dominant_cause" in failed(decision)


def test_rollback_blocked_on_historical_precedent_alone() -> None:
    """5. A past incident is about the past. It names no deployment to undo."""
    ops = operations(error_codes=("ERR_SYNC_STALLED",), deployed_at=ONSET - timedelta(minutes=8))
    evidence = (
        CORRELATION,
        ev("historical:NS-HIST-1", EvidenceKind.HISTORICAL, "NS-HIST-1"),
    )
    decision = decide(RemediationAction.ROLLBACK_DEPLOYMENT, evidence, ops)

    assert not decision.eligible
    assert "target_exists" in failed(decision)


def test_rollback_blocked_when_the_investigation_abstained() -> None:
    """6. An unexplained incident justifies no consequential action."""
    ops = operations(error_codes=("ERR_SYNC_STALLED",), deployed_at=ONSET - timedelta(minutes=8))
    evidence = (
        CORRELATION,
        ev("deployment:DEP-P01", EvidenceKind.DEPLOYMENT, "DEP-P01", ONSET - timedelta(minutes=8)),
        ev("health:svc-test", EvidenceKind.HEALTH, SERVICE, ONSET + timedelta(minutes=10)),
        ev("error:ERR_SYNC_STALLED", EvidenceKind.ERROR, "ERR_SYNC_STALLED", ONSET),
    )
    decision = decide(RemediationAction.ROLLBACK_DEPLOYMENT, evidence, ops, abstain=True)

    assert not decision.eligible
    assert "investigation_committed" in failed(decision)


def test_rollback_blocked_on_a_deployment_that_does_not_exist() -> None:
    """7. A cited id that matches no record is not a target."""
    ops = operations(error_codes=("ERR_SYNC_STALLED",), deployed_at=ONSET - timedelta(minutes=8))
    evidence = (
        CORRELATION,
        ev("deployment:DEP-9999", EvidenceKind.DEPLOYMENT, "DEP-9999", ONSET),
    )
    decision = decide(RemediationAction.ROLLBACK_DEPLOYMENT, evidence, ops)

    assert not decision.eligible
    assert "target_exists" in failed(decision)


# --- restart matrix -------------------------------------------------------------------


def transient_case() -> tuple[tuple[EvidenceItem, ...], OperationsFixtures]:
    ops = operations(error_codes=("ERR_SYNC_STALLED",))
    evidence = (
        CORRELATION,
        ev("health:svc-test", EvidenceKind.HEALTH, SERVICE, ONSET + timedelta(minutes=10)),
        ev("error:ERR_SYNC_STALLED", EvidenceKind.ERROR, "ERR_SYNC_STALLED", ONSET),
    )
    return evidence, ops


def test_restart_eligible_on_wedged_runtime_state() -> None:
    """8/13. Degraded, with a stalled worker — the mechanism a restart clears."""
    evidence, ops = transient_case()
    decision = decide(RemediationAction.RESTART_SERVICE, evidence, ops)

    assert decision.eligible
    assert decision.effective_risk is RiskLevel.MEDIUM
    checks = {r.check: r.passed for r in decision.reasons}
    assert checks["transient_runtime_failure"]
    assert checks["failure_mechanism_not_excluded"]


def test_restart_blocked_on_configuration_or_auth_failure() -> None:
    """9. The demo moment. A restart re-reads the same broken configuration."""
    ops = operations(error_codes=("ERR_SAML_INVALID_ASSERTION",))
    evidence = (
        CORRELATION,
        ev("health:svc-test", EvidenceKind.HEALTH, SERVICE, ONSET + timedelta(minutes=10)),
        ev("error:ERR_SAML_INVALID_ASSERTION", EvidenceKind.ERROR, "ERR_SAML_INVALID_ASSERTION", ONSET),
    )
    decision = decide(RemediationAction.RESTART_SERVICE, evidence, ops)

    assert not decision.eligible
    assert {"transient_runtime_failure", "failure_mechanism_not_excluded"} <= failed(decision)
    # v1 waved this through on two evidence kinds, which is the whole point of v2.
    v1 = evaluate_action_policy(
        recommendation=RemediationRecommendation(
            action_type=RemediationAction.RESTART_SERVICE,
            description="authored",
            risk=RiskLevel.LOW,
            supporting_evidence_ids=tuple(item.id for item in evidence),
        ),
        investigation=investigation(),
        evidence=evidence,
        operations=ops,
        service_id=SERVICE,
    )
    assert v1.eligible, "v1 is expected to allow this; that is the regression v2 fixes"


def test_restart_blocked_when_a_recent_deployment_is_implicated() -> None:
    """10. If a release caused it, rollback addresses it and restart defers it."""
    ops = operations(
        error_codes=("ERR_SYNC_STALLED",), deployed_at=ONSET - timedelta(minutes=15)
    )
    evidence = (
        CORRELATION,
        ev("deployment:DEP-P01", EvidenceKind.DEPLOYMENT, "DEP-P01", ONSET - timedelta(minutes=15)),
        ev("health:svc-test", EvidenceKind.HEALTH, SERVICE, ONSET + timedelta(minutes=10)),
        ev("error:ERR_SYNC_STALLED", EvidenceKind.ERROR, "ERR_SYNC_STALLED", ONSET),
    )
    decision = decide(RemediationAction.RESTART_SERVICE, evidence, ops)

    assert not decision.eligible
    assert "no_implicated_deployment" in failed(decision)


def test_restart_blocked_on_external_dependency_failure() -> None:
    """11. Restarting ours reconnects to something still broken."""
    ops = operations(error_codes=("ERR_UPSTREAM_TIMEOUT",))
    evidence = (
        CORRELATION,
        ev("health:svc-test", EvidenceKind.HEALTH, SERVICE, ONSET + timedelta(minutes=10)),
        ev("error:ERR_UPSTREAM_TIMEOUT", EvidenceKind.ERROR, "ERR_UPSTREAM_TIMEOUT", ONSET),
    )
    decision = decide(RemediationAction.RESTART_SERVICE, evidence, ops)

    assert not decision.eligible
    assert "failure_mechanism_not_excluded" in failed(decision)


def test_restart_blocked_on_generic_degradation_with_no_mechanism() -> None:
    """12. The central case. Degraded, and nothing says a restart is the answer."""
    ops = operations(error_codes=())
    evidence = (
        CORRELATION,
        ev("health:svc-test", EvidenceKind.HEALTH, SERVICE, ONSET + timedelta(minutes=10)),
        ev("ticket:T-1", EvidenceKind.TICKET, "T-1", ONSET),
    )
    decision = decide(RemediationAction.RESTART_SERVICE, evidence, ops)

    assert not decision.eligible
    assert "transient_runtime_failure" in failed(decision)
    assert decision.decision is PolicyDecision.REQUIRES_MORE_EVIDENCE


def test_restart_blocked_on_an_unclassified_error_code() -> None:
    """An unknown code must not satisfy restart relevance. Fail closed."""
    ops = operations(error_codes=("ERR_NOVEL_UNSEEN",))
    evidence = (
        CORRELATION,
        ev("health:svc-test", EvidenceKind.HEALTH, SERVICE, ONSET + timedelta(minutes=10)),
        ev("error:ERR_NOVEL_UNSEEN", EvidenceKind.ERROR, "ERR_NOVEL_UNSEEN", ONSET),
    )
    decision = decide(RemediationAction.RESTART_SERVICE, evidence, ops)

    assert not decision.eligible
    assert "transient_runtime_failure" in failed(decision)


def test_restart_blocked_on_a_healthy_service() -> None:
    """Restarting something that works is the only outage in the room."""
    ops = operations(health_status="healthy", error_codes=("ERR_SYNC_STALLED",))
    evidence = (
        CORRELATION,
        ev("health:svc-test", EvidenceKind.HEALTH, SERVICE, ONSET + timedelta(minutes=10)),
        ev("error:ERR_SYNC_STALLED", EvidenceKind.ERROR, "ERR_SYNC_STALLED", ONSET),
    )
    decision = decide(RemediationAction.RESTART_SERVICE, evidence, ops)

    assert not decision.eligible
    assert "service_degraded" in failed(decision)


def test_restart_blocked_when_the_investigation_abstained() -> None:
    """14."""
    evidence, ops = transient_case()
    decision = decide(RemediationAction.RESTART_SERVICE, evidence, ops, abstain=True)

    assert not decision.eligible
    assert "investigation_committed" in failed(decision)


def test_restart_blocked_on_an_unknown_service() -> None:
    """15."""
    evidence, ops = transient_case()
    decision = decide(RemediationAction.RESTART_SERVICE, evidence, ops, service_id="svc-ghost")

    assert not decision.eligible
    assert "target_exists" in failed(decision)


def test_restart_blocked_on_precedent_alone() -> None:
    """A similar past incident restarted a service. That is not this incident."""
    ops = operations(error_codes=("ERR_SYNC_STALLED",))
    evidence = (CORRELATION, ev("historical:NS-HIST-1", EvidenceKind.HISTORICAL, "NS-HIST-1"))
    decision = decide(RemediationAction.RESTART_SERVICE, evidence, ops)

    assert not decision.eligible


# --- rotate_credential ------------------------------------------------------------------


def test_rotate_credential_requires_a_credential_failure() -> None:
    ops = operations(error_codes=("ERR_SYNC_STALLED",))
    evidence = (
        CORRELATION,
        ev("health:svc-test", EvidenceKind.HEALTH, SERVICE, ONSET),
        ev("error:ERR_SYNC_STALLED", EvidenceKind.ERROR, "ERR_SYNC_STALLED", ONSET),
    )
    decision = decide(RemediationAction.ROTATE_CREDENTIAL, evidence, ops)

    assert not decision.eligible
    assert "credential_failure_implicated" in failed(decision)


def test_rotate_credential_is_eligible_on_an_auth_failure() -> None:
    ops = operations(error_codes=("ERR_TOKEN_EXPIRED",))
    evidence = (
        CORRELATION,
        ev("health:svc-test", EvidenceKind.HEALTH, SERVICE, ONSET),
        ev("error:ERR_TOKEN_EXPIRED", EvidenceKind.ERROR, "ERR_TOKEN_EXPIRED", ONSET),
    )
    decision = decide(RemediationAction.ROTATE_CREDENTIAL, evidence, ops)

    assert decision.eligible


# --- structure and determinism ----------------------------------------------------------


def test_every_check_reports_the_evidence_it_read() -> None:
    """A rejection an operator cannot trace to evidence is barely better than none."""
    evidence, ops = transient_case()
    decision = decide(RemediationAction.RESTART_SERVICE, evidence, ops)

    known = {item.id for item in evidence}
    evidence_bearing = [r for r in decision.reasons if r.evidence_ids]
    assert evidence_bearing, "at least the substantive checks must cite evidence"
    for reason in decision.reasons:
        assert set(reason.evidence_ids) <= known, reason.check


def test_policy_is_deterministic() -> None:
    evidence, ops = transient_case()
    first = decide(RemediationAction.RESTART_SERVICE, evidence, ops)
    second = decide(RemediationAction.RESTART_SERVICE, evidence, ops)
    assert first == second


def test_invented_evidence_ids_are_refused() -> None:
    evidence, ops = transient_case()
    recommendation = RemediationRecommendation(
        action_type=RemediationAction.RESTART_SERVICE,
        description="authored",
        risk=RiskLevel.LOW,
        supporting_evidence_ids=("error:MADE_UP",),
    )
    decision = evaluate_action_policy_v2(
        recommendation=recommendation,
        investigation=investigation(),
        evidence=evidence,
        operations=ops,
        service_id=SERVICE,
    )
    assert not decision.eligible
    assert "evidence_exists" in failed(decision)


def test_resolved_incidents_do_not_accept_actions() -> None:
    evidence, ops = transient_case()
    recommendation = RemediationRecommendation(
        action_type=RemediationAction.RESTART_SERVICE,
        description="authored",
        risk=RiskLevel.LOW,
        supporting_evidence_ids=tuple(item.id for item in evidence),
    )
    decision = evaluate_action_policy_v2(
        recommendation=recommendation,
        investigation=investigation(),
        evidence=evidence,
        operations=ops,
        service_id=SERVICE,
        incident_status="resolved",
    )
    assert not decision.eligible
    assert "incident_actionable" in failed(decision)


# --- the mechanism table ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "mechanism"),
    [
        ("ERR_SYNC_STALLED", FailureMechanism.TRANSIENT_RUNTIME),
        ("ERR_WORKER_OOM", FailureMechanism.TRANSIENT_RUNTIME),
        ("ERR_SAML_INVALID_ASSERTION", FailureMechanism.CONFIGURATION),
        ("401", FailureMechanism.AUTHENTICATION),
        ("403", FailureMechanism.PERMISSIONS),
        ("ERR_EXPORT_TRUNCATED", FailureMechanism.DATA_QUALITY),
        ("ERR_UPSTREAM_TIMEOUT", FailureMechanism.EXTERNAL_DEPENDENCY),
        ("ERR_WHO_KNOWS", FailureMechanism.UNKNOWN),
    ],
)
def test_error_codes_map_to_failure_mechanisms(code: str, mechanism) -> None:
    assert mechanism_of(code) is mechanism


def test_only_transient_runtime_justifies_a_restart() -> None:
    """The table is the policy. If this widens, it should be a deliberate edit."""
    assert RESTART_ADDRESSABLE == {FailureMechanism.TRANSIENT_RUNTIME}
    assert FailureMechanism.UNKNOWN not in RESTART_ADDRESSABLE
    assert FailureMechanism.UNKNOWN not in RESTART_CONTRAINDICATED
    assert not (RESTART_ADDRESSABLE & RESTART_CONTRAINDICATED)


def test_the_active_policy_is_v2() -> None:
    assert ACTIVE_ACTIONS_VERSION == "action-policy-v2"
    assert DEPLOYMENT_BLAST_WINDOW == timedelta(hours=2)


def test_a_deployment_cannot_set_the_incident_onset_it_is_blamed_for() -> None:
    """Otherwise "the release came first" is true by construction, gap zero.

    With only the deployment dated, there is nothing establishing when the trouble
    actually began, and the temporal check must fail rather than pass vacuously.
    """
    deployed = ONSET - timedelta(days=3)
    ops = operations(error_codes=("ERR_SYNC_STALLED",), deployed_at=deployed)
    evidence = (
        ev("deployment:DEP-P01", EvidenceKind.DEPLOYMENT, "DEP-P01", deployed),
        ev("health:svc-test", EvidenceKind.HEALTH, SERVICE, None),
        ev("error:ERR_SYNC_STALLED", EvidenceKind.ERROR, "ERR_SYNC_STALLED", None),
    )
    decision = decide(RemediationAction.ROLLBACK_DEPLOYMENT, evidence, ops)

    assert not decision.eligible
    assert "deployment_precedes_incident" in failed(decision)
    detail = next(
        r.detail for r in decision.reasons if r.check == "deployment_precedes_incident"
    )
    assert "no incident onset" in detail
