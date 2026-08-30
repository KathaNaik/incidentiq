"""Investigation evaluation.

**Grading is programmatic.** Every metric below is computed from structure — which
evidence ids were cited, whether the output abstained, which remediation action was
named — except one: whether a hypothesis "named the right cause", which is graded by
requiring one of a small set of accepted cause terms in the leading hypothesis. That is a
proxy, and a coarse one; it is used because an LLM judge would make the evaluation depend
on the thing being evaluated, and a judge is not worth introducing until the deterministic
signals stop discriminating.

**A retrieval-only baseline runs alongside.** It answers "the most similar past
incident's root cause is the cause" with no synthesis. Without it, an investigator's
score says nothing about whether reasoning over multiple evidence sources beats
nearest-neighbour lookup.

Labels live in a separate file and are read after inference, never passed to the model.
"""

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from app.correlation import CorrelationTicket, correlate
from app.correlation.models import CandidateIncident, Confidence
from app.actions import evaluate_action_policy
from app.investigation import (
    INVESTIGATION_VERSION,
    PROMPT_VERSION,
    EvidenceRegistry,
    InvestigationModel,
    InvestigationModelError,
    InvestigationValidationError,
    collect_evidence,
    investigate,
)
from app.investigation.tools import (
    DeploymentRecord,
    ErrorSummary,
    OperationsFixtures,
    ServiceHealthSnapshot,
)
from app.retrieval import HistoricalIndex
from evaluation.models import CaseFailure, EvalReport, MetricSummary

CASES_FILE = "investigation_cases.json"
LABELS_FILE = "investigation_labels.json"
# Each eval version is a separate pair of files. A metric belongs to the version it was
# measured against, and the only way to keep that true is to never edit an older one.
EVAL_FILES = {
    "v1": ("investigation_cases.json", "investigation_labels.json"),
    "v2": ("investigation_cases_v2.json", "investigation_labels_v2.json"),
    "v3": ("investigation_cases_v3.json", "investigation_labels_v3.json"),
}
DEV_CASES_FILE = "dev_remediation_cases.json"
DEV_LABELS_FILE = "dev_remediation_labels.json"
MAX_REPORTED = 12


def load_cases(
    directory: Path, *, dev: bool = False, eval_version: str = "v1"
) -> tuple[dict, ...]:
    name = DEV_CASES_FILE if dev else EVAL_FILES[eval_version][0]
    return tuple(_payload(directory / name)["records"])


def load_labels(
    directory: Path, *, dev: bool = False, eval_version: str = "v1"
) -> dict[str, dict]:
    name = DEV_LABELS_FILE if dev else EVAL_FILES[eval_version][1]
    return {record["case_id"]: record for record in _payload(directory / name)["records"]}


def _attribution_correct(expectation: str, output) -> bool:
    """Did the model place the deployment correctly in the causal story?

    Graded from **structured output only**: which evidence ids the leading hypothesis
    cites, and which action was recommended. Both are exact.

    An earlier version of this matched keywords in the hypothesis text and scored
    "stalled workers, no release involved" as blaming a release — negation is precisely
    what keyword matching cannot do, and a metric that misreads a sentence is worse than
    no metric. Citing `deployment:DEP-3008` is unambiguous in a way that mentioning the
    word "release" is not.
    """
    leading_citations = (
        set(output.hypotheses[0].supporting_evidence_ids) if output.hypotheses else set()
    )
    blames_deployment = any(
        value.startswith("deployment:") for value in leading_citations
    )
    recommends_rollback = (
        output.remediation is not None
        and output.remediation.action_type.value == "rollback_deployment"
    )

    if expectation == "deployment_plausible":
        # The chronology supports a release as the initiating cause; saying so is correct.
        return blames_deployment or recommends_rollback
    if expectation in ("deployment_implausible", "no_deployment"):
        # The chronology rules a release out, or there is none. Blaming one is the failure
        # this metric exists to catch.
        return not blames_deployment and not recommends_rollback
    return True


def _payload(path: Path) -> dict:
    if not path.is_file():
        raise ValueError(f"missing investigation golden-set file: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not payload.get("synthetic"):
        raise ValueError(f"{path.name} is not marked synthetic")
    return payload


def case_operations(case: dict, shared: OperationsFixtures) -> OperationsFixtures:
    """The operational world one case is investigated against.

    A case may carry its own `operations` block. That is what makes temporal evaluation
    possible at all: evidence collection is service-scoped, so two cases on the same
    service in the shared Northstar fixtures receive byte-identical operational signals
    however differently their tickets read. IV04 and IV12 were exactly that, and no label
    adjudication could fix it — the *evidence* had to differ.

    An authored block is observational data — deployments, health readings, error
    signatures with their times. It carries no labels and never states an expected action.
    Cases without one fall back to the shared fixtures, so nothing that existed before
    changes behaviour.
    """
    block = case.get("operations")
    if not block:
        return shared
    return OperationsFixtures(
        deployments=tuple(
            DeploymentRecord.model_validate(row) for row in block.get("deployments", [])
        ),
        health=tuple(
            ServiceHealthSnapshot.model_validate(row) for row in block.get("health", [])
        ),
        errors=tuple(ErrorSummary.model_validate(row) for row in block.get("errors", [])),
    )


def case_candidate(case: dict) -> tuple[CandidateIncident, tuple[CorrelationTicket, ...]]:
    """Turns an authored case into a candidate incident plus its tickets.

    Correlation is run first so the candidate carries real correlation evidence; if the
    tickets do not group (a single ticket, or a deliberately incoherent pair) the case is
    still investigable as a one-group candidate, because an operator looking at an
    ungrouped ticket wants the same analysis.
    """
    tickets = tuple(
        CorrelationTicket(
            id=ticket["id"],
            title=ticket["title"],
            description=ticket["description"],
            created_at=ticket["created_at"],
            service_id=case.get("service_id"),
        )
        for ticket in case["tickets"]
    )

    correlated = correlate(tickets)
    if correlated.candidates:
        return correlated.candidates[0], tickets

    first = min(tickets, key=lambda ticket: (ticket.created_at, ticket.id))
    return (
        CandidateIncident(
            id=f"cand-{first.id}",
            ticket_ids=tuple(ticket.id for ticket in tickets),
            score=0.0,
            confidence=Confidence.LOW,
            first_seen=first.created_at,
            last_seen=max(ticket.created_at for ticket in tickets),
            service_id=case.get("service_id"),
            issue_type=None,
            ticket_count=len(tickets),
            distinct_reporters=None,
            supporting_signals=(),
            conflicting_signals=(),
            member_pairs=(),
        ),
        tickets,
    )


def run_baseline(
    directory: Path, operations: OperationsFixtures, index: HistoricalIndex
) -> EvalReport:
    """Retrieval-only baseline: the nearest past incident's cause, asserted as this one's.

    No synthesis, no abstention judgement — it always answers, which is precisely the
    behaviour the investigator is supposed to improve on.
    """
    cases = load_cases(directory)
    labels = load_labels(directory)

    leading_correct = 0
    abstain_correct = 0
    graded = 0
    failures: list[CaseFailure] = []

    for case in cases:
        label = labels[case["id"]]
        candidate, tickets = case_candidate(case)
        registry = collect_evidence(
            candidate=candidate,
            tickets=tickets,
            operations=case_operations(case, operations),
            index=index,
        )
        historical = [
            item for item in registry.items if item.kind.value == "historical"
        ]
        summary = historical[0].summary if historical else ""

        # The baseline never abstains: it always has a nearest neighbour.
        if label["expect_abstain"] is False:
            graded += 1
            if _mentions(summary, label["cause_terms"]):
                leading_correct += 1
        if label["expect_abstain"] is False:
            abstain_correct += 1
        elif not historical:
            abstain_correct += 1

    return EvalReport(
        suite="investigation-baseline",
        version="retrieval-only-baseline",
        generated_at=datetime.now(UTC),
        case_count=len(cases),
        metrics=(
            MetricSummary(
                name="leading_hypothesis_accuracy",
                correct=leading_correct,
                total=graded,
                accuracy=round(leading_correct / graded, 4) if graded else 0.0,
            ),
            MetricSummary(
                name="abstention_accuracy",
                correct=abstain_correct,
                total=len(cases),
                accuracy=round(abstain_correct / len(cases), 4) if cases else 0.0,
            ),
        ),
        confusion=(),
        failures=tuple(failures),
        notes=(
            "Retrieval-only: asserts the nearest historical incident's root cause with "
            "no synthesis and no abstention. The number to beat.",
        ),
    )


def run_investigation_evaluation(
    directory: Path,
    operations: OperationsFixtures,
    index: HistoricalIndex,
    model: InvestigationModel,
    prompt_version: str = PROMPT_VERSION,
    dev: bool = False,
    eval_version: str = "v1",
) -> EvalReport:
    """The authored suite against a model and a prompt version.

    `dev` runs the development set instead of the held-out one. Keeping both behind the
    same function means the metric definitions cannot drift between tuning and
    measurement.

    `eval_version` selects which held-out set. Versions are not interchangeable: eval-v3
    supplies temporal evidence that v1 and v2 runs never saw, so a v3 number and a v2
    number answer different questions and the report says which.
    """
    cases = load_cases(directory, dev=dev, eval_version=eval_version)
    labels = load_labels(directory, dev=dev, eval_version=eval_version)

    valid = 0
    remediation_expected = 0
    remediation_recommended = 0
    remediation_correct = 0
    policy_eligible_correct = 0
    recorded: list[dict] = []
    leading_correct = 0
    top3_correct = 0
    # Temporal grading. Only counted for cases whose label states an expectation, so a
    # v1/v2 case without one never silently scores as correct.
    attribution_graded = 0
    attribution_correct = 0
    graded = 0
    abstain_correct = 0
    unsupported_citations = 0
    unsupported_remediation = 0
    evidence_covered = 0
    evidence_required = 0
    latencies: list[int] = []
    input_tokens = 0
    output_tokens = 0
    failures: list[CaseFailure] = []

    for case in cases:
        label = labels[case["id"]]
        candidate, tickets = case_candidate(case)
        registry = collect_evidence(
            candidate=candidate,
            tickets=tickets,
            operations=case_operations(case, operations),
            index=index,
        )

        try:
            result = investigate(
                candidate=candidate,
                registry=registry,
                model=model,
                prompt_version=prompt_version,
            )
        except InvestigationValidationError as error:
            # Validation rejected the output. That is the guardrail working, and it is
            # also a failed case: the model produced something unusable.
            unsupported_citations += 1
            failures.append(
                _failure(case, label, "structured_output_validity", str(error), registry)
            )
            continue
        except InvestigationModelError as error:
            failures.append(
                _failure(case, label, "model_error", str(error), registry)
            )
            continue

        valid += 1
        output = result.output

        # Recorded so remediation metrics can be recomputed later without re-running
        # the model — the gap that made M8's numbers impossible to extend.
        recorded.append(
            {
                "case_id": case["id"],
                "abstain": output.abstain,
                "hypotheses": [h.summary for h in output.hypotheses],
                # Citations, not just summaries. A grading change should be recomputable
                # from the record instead of costing another held-out run.
                "leading_citations": (
                    list(output.hypotheses[0].supporting_evidence_ids)
                    if output.hypotheses
                    else []
                ),
                "remediation": (
                    output.remediation.action_type.value if output.remediation else None
                ),
                "remediation_evidence": list(
                    output.remediation.supporting_evidence_ids
                )
                if output.remediation
                else [],
            }
        )

        expectation = label.get("temporal_expectation")
        if expectation:
            attribution_graded += 1
            if _attribution_correct(expectation, output):
                attribution_correct += 1

        allowed_actions = set(label["allowed_remediation"])
        if allowed_actions:
            remediation_expected += 1
        if output.remediation is not None:
            remediation_recommended += 1
            if output.remediation.action_type.value in allowed_actions:
                remediation_correct += 1
                # A correct action is only *useful* if M9 policy would make it
                # approvable. A recommendation the control plane blocks helps nobody,
                # so it does not count toward policy-eligible recall.
                decision = evaluate_action_policy(
                    recommendation=output.remediation,
                    investigation=output,
                    evidence=result.evidence,
                    operations=case_operations(case, operations),
                    service_id=case.get("service_id"),
                )
                if decision.eligible:
                    policy_eligible_correct += 1
        latencies.append(result.run.latency_ms)
        input_tokens += result.run.input_tokens or 0
        output_tokens += result.run.output_tokens or 0

        if output.abstain == label["expect_abstain"]:
            abstain_correct += 1
        else:
            failures.append(
                _failure(
                    case,
                    label,
                    "abstention",
                    f"expected abstain={label['expect_abstain']}, got {output.abstain}",
                    registry,
                )
            )

        # A remediation outside the allowed set — or any remediation on a case that
        # should abstain — is an unsupported action.
        if output.remediation is not None:
            allowed = set(label["allowed_remediation"])
            if not allowed or output.remediation.action_type.value not in allowed:
                unsupported_remediation += 1
                failures.append(
                    _failure(
                        case,
                        label,
                        "unsupported_remediation",
                        f"recommended {output.remediation.action_type.value}, allowed "
                        f"{sorted(allowed) or 'none'}",
                        registry,
                    )
                )

        required = set(label["required_evidence_ids"])
        if required:
            evidence_required += 1
            cited = {
                value
                for hypothesis in output.hypotheses
                for value in hypothesis.supporting_evidence_ids
            }
            if required <= cited:
                evidence_covered += 1

        if not label["expect_abstain"]:
            graded += 1
            summaries = [hypothesis.summary for hypothesis in output.hypotheses]
            if summaries and _mentions(summaries[0], label["cause_terms"]):
                leading_correct += 1
            elif any(_mentions(text, label["cause_terms"]) for text in summaries[:3]):
                top3_correct += 1
            else:
                failures.append(
                    _failure(
                        case,
                        label,
                        "leading_hypothesis",
                        f"no accepted cause term in top hypotheses: "
                        f"{summaries[:3] or 'none offered'}",
                        registry,
                    )
                )

    total = len(cases)
    metrics = (
        MetricSummary(
            name="structured_output_validity",
            correct=valid,
            total=total,
            accuracy=round(valid / total, 4) if total else 0.0,
        ),
        MetricSummary(
            name="leading_hypothesis_accuracy",
            correct=leading_correct,
            total=graded,
            accuracy=round(leading_correct / graded, 4) if graded else 0.0,
        ),
        MetricSummary(
            name="top3_hypothesis_accuracy",
            correct=leading_correct + top3_correct,
            total=graded,
            accuracy=round((leading_correct + top3_correct) / graded, 4) if graded else 0.0,
        ),
        MetricSummary(
            name="abstention_accuracy",
            correct=abstain_correct,
            total=total,
            accuracy=round(abstain_correct / total, 4) if total else 0.0,
        ),
        MetricSummary(
            name="unsupported_citation_rate",
            correct=unsupported_citations,
            total=total,
            accuracy=round(unsupported_citations / total, 4) if total else 0.0,
        ),
        MetricSummary(
            name="unsupported_remediation_rate",
            correct=unsupported_remediation,
            total=total,
            accuracy=round(unsupported_remediation / total, 4) if total else 0.0,
        ),
        MetricSummary(
            name="remediation_recall",
            correct=remediation_correct,
            total=remediation_expected,
            accuracy=round(remediation_correct / remediation_expected, 4)
            if remediation_expected
            else 0.0,
        ),
        MetricSummary(
            name="policy_eligible_remediation_recall",
            correct=policy_eligible_correct,
            total=remediation_expected,
            accuracy=round(policy_eligible_correct / remediation_expected, 4)
            if remediation_expected
            else 0.0,
        ),
        MetricSummary(
            name="remediation_precision",
            correct=remediation_correct,
            total=remediation_recommended,
            accuracy=round(remediation_correct / remediation_recommended, 4)
            if remediation_recommended
            else 0.0,
        ),
        MetricSummary(
            name="required_evidence_coverage",
            correct=evidence_covered,
            total=evidence_required,
            accuracy=round(evidence_covered / evidence_required, 4)
            if evidence_required
            else 0.0,
        ),
    )

    if attribution_graded:
        # Only present when the set carries temporal expectations. A metric reported as
        # zero-of-zero on an older set would read as a result rather than an absence.
        metrics = metrics + (
            MetricSummary(
                name="deployment_attribution_accuracy",
                correct=attribution_correct,
                total=attribution_graded,
                accuracy=round(attribution_correct / attribution_graded, 4),
            ),
        )

    median_latency = sorted(latencies)[len(latencies) // 2] if latencies else 0
    return EvalReport(
        suite="investigation",
        version=prompt_version,
        generated_at=datetime.now(UTC),
        case_count=total,
        metrics=metrics,
        confusion=(),
        failures=tuple(failures[:MAX_REPORTED]),
        notes=(
            f"Model: {model.model_id}, prompt {prompt_version}, reasoning effort "
            f"medium. Median latency {median_latency} ms over {len(latencies)} calls.",
            f"Tokens: {input_tokens} in, {output_tokens} out."
            if input_tokens or output_tokens
            else "Token usage not reported by the provider.",
            "Cause-term matching is a deterministic proxy for naming the right cause "
            "family. Lower rates are better for the two 'unsupported' metrics.",
            "Authored for IncidentIQ; labels were never shown to the model.",
            "Remediation recall counts cases where an action was expected and a correct "
            "one was recommended; precision counts correct recommendations against all "
            "recommendations. Precision is 0.0 when nothing was recommended at all — "
            "read it alongside recall.",
            "Policy-eligible remediation recall counts only recommendations the M9 "
            "control plane would actually make approvable.",
            "Per-case outputs: " + "; ".join(
                f"{r['case_id']}={'abstain' if r['abstain'] else 'answer'}/"
                f"{r['remediation'] or 'no-remediation'}"
                for r in recorded
            ),
        ),
    )


def _mentions(text: str, terms: Sequence[str]) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)


def _failure(
    case: dict, label: dict, metric: str, explanation: str, registry: EvidenceRegistry
) -> CaseFailure:
    return CaseFailure(
        case_id=case["id"],
        metric=metric,
        expected=("abstain" if label["expect_abstain"] else "hypothesis"),
        predicted=None,
        status=case.get("scenario", ""),
        explanation=explanation,
        signals=tuple(item.id for item in registry.items),
        text=case["tickets"][0]["title"],
    )
