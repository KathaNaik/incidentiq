"""Investigation contracts.

The shape of this module is the safety design. The model returns hypotheses that cite
evidence *by id*; application code then checks every id against a registry it built
itself. A claim the model cannot ground in supplied evidence does not survive validation,
which is why the schema carries ids rather than prose descriptions of evidence.

Confidence here is the model's own stated confidence. It is not a calibrated
probability, and nothing in this codebase treats it as one.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class EvidenceKind(StrEnum):
    TICKET = "ticket"
    CORRELATION = "correlation"
    DEPLOYMENT = "deployment"
    HEALTH = "health"
    ERROR = "error"
    HISTORICAL = "historical"
    # Derived by the application from the timestamps on the evidence above. Not an
    # observation — a computed relationship between observations.
    TEMPORAL = "temporal"


class NextStepAction(StrEnum):
    """What the investigator can suggest doing next. Investigation only — nothing here
    changes the state of a system."""

    INSPECT_LOGS = "inspect_logs"
    INSPECT_SERVICE_HEALTH = "inspect_service_health"
    INSPECT_DEPLOYMENT = "inspect_deployment"
    CONTACT_TEAM = "contact_team"
    GATHER_TICKET_DETAIL = "gather_ticket_detail"
    NO_ACTION = "no_action"


class RemediationAction(StrEnum):
    """Consequential actions the investigator may *recommend*.

    Nothing executes them in this milestone. The set is closed so a model cannot invent
    an action the product has no notion of.
    """

    ROLLBACK_DEPLOYMENT = "rollback_deployment"
    RESTART_SERVICE = "restart_service"
    ROTATE_CREDENTIAL = "rotate_credential"
    SCALE_SERVICE = "scale_service"
    DISABLE_FEATURE_FLAG = "disable_feature_flag"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class InvestigationModelBase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# --- evidence ------------------------------------------------------------------------


class EvidenceItem(InvestigationModelBase):
    """One fact the investigator is allowed to reason from.

    `summary` is what the model sees. `provenance` says where it came from and is shown
    to the operator — every operational signal in this prototype is synthetic, and the
    UI says so rather than implying a live integration.
    """

    id: str
    kind: EvidenceKind
    summary: str
    source_id: str
    provenance: str
    # Typed structure alongside the prose summary. The summary is what the model reads;
    # these are what application code reads, so deriving chronology never means parsing
    # a sentence this system wrote earlier. Optional so evidence snapshots recorded
    # before M14 still validate — they were produced without them.
    service_id: str | None = None
    attributes: dict[str, str] = Field(default_factory=dict)
    observed_at: datetime | None = None


class EvidenceReference(InvestigationModelBase):
    evidence_id: str


# --- model output ---------------------------------------------------------------------


class Hypothesis(InvestigationModelBase):
    summary: str = Field(min_length=1)
    # The model's own confidence. Not calibrated; labelled as such everywhere it is shown.
    confidence: float = Field(ge=0.0, le=1.0)
    supporting_evidence_ids: tuple[str, ...] = ()
    conflicting_evidence_ids: tuple[str, ...] = ()


class RecommendedNextStep(InvestigationModelBase):
    action_type: NextStepAction
    description: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


class RemediationRecommendation(InvestigationModelBase):
    action_type: RemediationAction
    description: str = Field(min_length=1)
    risk: RiskLevel
    supporting_evidence_ids: tuple[str, ...] = Field(min_length=1)


class InvestigationOutput(InvestigationModelBase):
    """Exactly what the model is asked to produce.

    Kept separate from `InvestigationResult` so that model output and system-added
    metadata (timings, evidence supplied, validation verdict) never get confused for one
    another.
    """

    hypotheses: tuple[Hypothesis, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    recommended_next_step: RecommendedNextStep
    remediation: RemediationRecommendation | None = None
    # The model's own judgement that the evidence does not support a conclusion.
    abstain: bool
    abstain_reason: str | None = None


# --- system result ----------------------------------------------------------------------


class InvestigationRun(InvestigationModelBase):
    """Observability for one investigation. No prompt text, no secrets."""

    model: str
    prompt_version: str
    evidence_ids: tuple[str, ...]
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    # Reported by reasoning models. The count only — reasoning content is never
    # requested, returned, or logged.
    reasoning_tokens: int | None = None
    started_at: datetime


class InvestigationResult(InvestigationModelBase):
    incident_id: str
    version: str
    output: InvestigationOutput
    evidence: tuple[EvidenceItem, ...]
    run: InvestigationRun
