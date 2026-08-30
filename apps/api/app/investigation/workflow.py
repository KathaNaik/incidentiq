"""Running and storing an investigation.

The unit of work that used to be an HTTP handler. It exists so that "investigate this
incident" is one thing with one story — claim the incident, snapshot the evidence, call
the model once, persist the outcome — rather than logic spread between a router and a
service.

Ordering matters and is deliberate:

1. Collect evidence.
2. **Persist the run and its snapshot before calling the model.** A run that fails at the
   provider still records exactly what would have been sent, which is what makes a failed
   run worth keeping.
3. Call the model once.
4. Complete or fail the run. Either way the row is terminal and immutable afterwards.

A second concurrent request does not reach step 3: `begin` raises with the run already in
flight, and the caller returns that instead of spending another model call.
"""

import logging

from app.db.investigation_store import (
    ActiveRunExistsError,
    InvestigationRunStore,
    StoredRun,
)
from app.investigation.evidence import EvidenceRegistry
from app.investigation.models import InvestigationResult
from app.investigation.provider import InvestigationModel, InvestigationModelError
from app.investigation.prompt import build_user_message, select_prompt
from app.investigation.rules import INVESTIGATION_VERSION
from app.investigation.service import DEFAULT_PROMPT_VERSION
from app.investigation.validate import (
    InvestigationValidationError,
    validate_output,
)

logger = logging.getLogger(__name__)


def run_investigation(
    *,
    incident_id: str,
    incident_summary: str,
    registry: EvidenceRegistry,
    model: InvestigationModel,
    store: InvestigationRunStore,
    provider: str,
    model_name: str,
    prompt_version: str = DEFAULT_PROMPT_VERSION,
) -> StoredRun:
    """Executes one investigation and persists it. Raises if one is already active."""
    system_prompt, prompt_version = select_prompt(prompt_version)

    # Claims the incident. Raises ActiveRunExistsError if another request got here first.
    run = store.begin(
        incident_id=incident_id,
        investigator_version=INVESTIGATION_VERSION,
        prompt_version=prompt_version,
        provider=provider,
        model=model_name,
        evidence=registry.items,
    )

    user_message = build_user_message(
        incident_summary=incident_summary, registry=registry
    )

    try:
        response = model.investigate(system_prompt, user_message)
    except InvestigationModelError as error:
        logger.warning(
            "investigation provider failed",
            extra={"incident_id": incident_id, "run_id": run.id},
        )
        return store.fail(run.id, failure_type="provider_error", message=str(error))

    try:
        output = validate_output(response.output, registry)
    except InvestigationValidationError as error:
        # The model returned something the evidence does not support. Recorded as a
        # failed run rather than discarded: "the model cited evidence that does not
        # exist" is exactly the kind of thing worth being able to look back at.
        logger.warning(
            "investigation output rejected by validation",
            extra={"incident_id": incident_id, "run_id": run.id},
        )
        return store.fail(run.id, failure_type="validation_error", message=str(error))

    logger.info(
        "investigation completed",
        extra={
            "incident_id": incident_id,
            "run_id": run.id,
            "model": response.model,
            "prompt_version": prompt_version,
            "evidence_count": len(registry),
            "latency_ms": response.latency_ms,
            "abstained": output.abstain,
        },
    )
    return store.complete(
        run.id,
        output=output,
        model=response.model,
        latency_ms=response.latency_ms,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        reasoning_tokens=response.reasoning_tokens,
    )


def current_result(store: InvestigationRunStore, incident_id: str) -> InvestigationResult | None:
    """The investigation an operator should be shown, or None if there is not one yet.

    The latest *successful* run, deliberately: a failed re-investigation must not hide the
    conclusion that is still the best available answer.
    """
    run = store.latest_successful(incident_id)
    return run.as_result() if run is not None else None


__all__ = [
    "ActiveRunExistsError",
    "current_result",
    "run_investigation",
]
