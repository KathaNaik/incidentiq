"""The bounded investigation workflow.

    candidate -> deterministic evidence -> historical precedent -> operational signals
             -> one structured model call -> validation -> result

Straight through, once. No agent loop, no tool selection by the model, no follow-up
turns: the evidence a given incident yields is decided by code, so two runs over the same
incident see the same evidence and a failure is reproducible. If the model wants
something it was not given, the correct output is to say so in `missing_evidence` — which
is exactly what a next investigation step is for.
"""

import logging
from collections.abc import Sequence
from datetime import UTC, datetime

from app.correlation.models import CandidateIncident, CorrelationTicket
from app.investigation.evidence import EvidenceRegistry, build_registry
from app.investigation.models import (
    InvestigationResult,
    InvestigationRun,
)
from app.investigation.prompt import PROMPT_VERSION, SYSTEM_PROMPT, build_user_message
from app.investigation.provider import InvestigationModel
from app.investigation.rules import INVESTIGATION_VERSION
from app.investigation.tools import (
    OperationsFixtures,
    get_error_summary,
    get_recent_deployments,
    get_service_health,
)
from app.investigation.validate import validate_output
from app.retrieval import HistoricalIndex, query_from_tickets
from app.retrieval.rules import DEFAULT_K

logger = logging.getLogger(__name__)


def collect_evidence(
    *,
    candidate: CandidateIncident,
    tickets: Sequence[CorrelationTicket],
    operations: OperationsFixtures,
    index: HistoricalIndex | None,
    historical_k: int = 3,
) -> EvidenceRegistry:
    """Everything the investigator gets to see, gathered deterministically."""
    members = [ticket for ticket in tickets if ticket.id in set(candidate.ticket_ids)]

    historical = ()
    if index is not None and members:
        historical = index.search(
            query_from_tickets(members), k=min(historical_k, DEFAULT_K)
        ).hits

    return build_registry(
        candidate=candidate,
        tickets=members,
        deployments=get_recent_deployments(
            operations, candidate.service_id, candidate.first_seen
        ),
        health=get_service_health(operations, candidate.service_id, candidate.first_seen),
        errors=get_error_summary(operations, candidate.service_id, candidate.first_seen),
        historical=historical,
    )


def investigate(
    *,
    candidate: CandidateIncident,
    registry: EvidenceRegistry,
    model: InvestigationModel,
) -> InvestigationResult:
    """One model call over fixed evidence, then validation."""
    summary = (
        f"{candidate.ticket_count} correlated tickets on "
        f"{candidate.service_id or 'an unidentified service'}, first seen "
        f"{candidate.first_seen.isoformat()}, correlation confidence "
        f"{candidate.confidence.value}."
    )
    user_message = build_user_message(incident_summary=summary, registry=registry)

    started_at = datetime.now(UTC)
    response = model.investigate(SYSTEM_PROMPT, user_message)
    output = validate_output(response.output, registry)

    # Enough to debug a bad investigation: what model, what prompt, what evidence, how
    # long, how many tokens. Deliberately not the prompt text or the evidence content.
    logger.info(
        "investigation completed",
        extra={
            "incident_id": candidate.id,
            "model": response.model,
            "prompt_version": PROMPT_VERSION,
            "evidence_count": len(registry),
            "latency_ms": response.latency_ms,
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "reasoning_tokens": response.reasoning_tokens,
            "abstained": output.abstain,
            "hypothesis_count": len(output.hypotheses),
        },
    )

    return InvestigationResult(
        incident_id=candidate.id,
        version=INVESTIGATION_VERSION,
        output=output,
        evidence=registry.items,
        run=InvestigationRun(
            model=response.model,
            prompt_version=PROMPT_VERSION,
            evidence_ids=registry.ids,
            latency_ms=response.latency_ms,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            reasoning_tokens=response.reasoning_tokens,
            started_at=started_at,
        ),
    )
