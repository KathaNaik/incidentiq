"""Validation of model output.

This is where the guarantees live. The prompt asks the model to behave; this module
decides whether the output is allowed to reach an operator. Everything checked here is
checked in code precisely because a system prompt cannot enforce it.

Rejection is the default for a violation, not repair: silently deleting a bad citation
would leave a hypothesis standing on evidence it no longer has.
"""

from app.investigation.evidence import EvidenceRegistry
from app.investigation.models import InvestigationOutput


class InvestigationValidationError(ValueError):
    """Model output violated a rule the system guarantees."""


def validate_output(
    output: InvestigationOutput, registry: EvidenceRegistry
) -> InvestigationOutput:
    """Checks output against the registry and the product's rules.

    Returns the output with hypotheses ordered by confidence, so ranking is a property
    of the result rather than a request the model may or may not have honoured.
    """
    _check_citations(output, registry)
    _check_abstention(output)
    _check_hypotheses(output)

    ordered = tuple(
        sorted(output.hypotheses, key=lambda item: (-item.confidence, item.summary))
    )
    return output.model_copy(update={"hypotheses": ordered})


def _check_citations(output: InvestigationOutput, registry: EvidenceRegistry) -> None:
    """Every cited id must be evidence this investigation actually supplied.

    An id the model invented means a claim with nothing behind it — the failure mode
    this whole design exists to prevent.
    """
    cited: list[str] = []
    for hypothesis in output.hypotheses:
        cited.extend(hypothesis.supporting_evidence_ids)
        cited.extend(hypothesis.conflicting_evidence_ids)
    if output.remediation is not None:
        cited.extend(output.remediation.supporting_evidence_ids)

    unknown = registry.unknown(cited)
    if unknown:
        raise InvestigationValidationError(
            f"output cites evidence that was not supplied: {', '.join(unknown)}"
        )


def _check_abstention(output: InvestigationOutput) -> None:
    """Abstaining and recommending a consequential action are mutually exclusive."""
    if output.abstain and output.remediation is not None:
        raise InvestigationValidationError(
            "output abstains but still recommends remediation; an investigation that "
            "cannot identify a cause cannot justify acting on one"
        )
    if output.abstain and not output.missing_evidence:
        raise InvestigationValidationError(
            "output abstains without saying what evidence is missing"
        )


def _check_hypotheses(output: InvestigationOutput) -> None:
    if not output.abstain and not output.hypotheses:
        raise InvestigationValidationError(
            "output neither abstains nor offers a hypothesis"
        )
    for hypothesis in output.hypotheses:
        if not hypothesis.supporting_evidence_ids:
            raise InvestigationValidationError(
                f"hypothesis {hypothesis.summary!r} cites no supporting evidence"
            )
