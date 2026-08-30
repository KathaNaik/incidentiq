"""Typed temporal facts.

Two ideas, kept apart deliberately.

A **TemporalObservation** is something that happened at a time: a deployment shipped, an
error signature began, health changed, a ticket arrived. It is a normalised *view* over
evidence that already exists — not a second copy of the operational world, and not a new
table. The evidence registry remains the source of truth; this is a lens for ordering it.

A **TemporalRelationship** is a comparison between two observations, computed by the
application. The model is not asked to subtract timestamps.

The distinction that matters most in this module: `CausalCompatibility` says whether an
ordering is *consistent with* one thing having caused another. It never says one thing
caused another. A deployment five minutes before the first error is temporally compatible
with being the cause and might still be irrelevant; a deployment twenty minutes after the
errors started cannot be the initiating cause, and that one *is* dispositive. Necessary
evidence, not sufficient proof — the enum names say so.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class TemporalModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ObservationType(StrEnum):
    """What kind of thing happened.

    Split into symptoms and candidate causes, because incident onset is defined from
    symptoms only — see `app.temporal.onset`.
    """

    # Candidate causes. A change we made.
    DEPLOYMENT = "deployment"

    # Symptoms. Evidence that something is wrong.
    ERROR_ONSET = "error_onset"
    HEALTH_DEGRADATION = "health_degradation"
    HEALTH_OBSERVATION = "health_observation"
    TICKET_REPORT = "ticket_report"


# Only these define when an incident started. A deployment is a candidate *cause*: letting
# it set onset makes "the deployment preceded the incident" true by construction, which is
# exactly the zero-gap bug found in M11 and fixed again here with a named rule.
SYMPTOM_TYPES = frozenset(
    {
        ObservationType.ERROR_ONSET,
        ObservationType.HEALTH_DEGRADATION,
        ObservationType.TICKET_REPORT,
    }
)


class TemporalObservation(TemporalModel):
    """One timestamped fact, normalised from existing evidence."""

    id: str
    observation_type: ObservationType
    service_id: str | None
    observed_at: datetime
    # The registry id this was derived from, so every temporal fact traces back to the
    # evidence an operator can read.
    source_evidence_id: str
    # A short, colon-free handle used to build relationship ids. The full evidence id
    # embeds an ISO timestamp for health observations, whose own colons and 95-character
    # length made composed ids unreproducible — see `app.temporal.timeline`.
    key: str
    label: str
    # Small typed extras: error code, health status, deployment version.
    attributes: dict[str, str] = Field(default_factory=dict)

    @property
    def is_symptom(self) -> bool:
        return self.observation_type in SYMPTOM_TYPES


class RelationshipType(StrEnum):
    DEPLOYMENT_PRECEDES_ERROR_ONSET = "deployment_precedes_error_onset"
    DEPLOYMENT_FOLLOWS_ERROR_ONSET = "deployment_follows_error_onset"
    DEPLOYMENT_PRECEDES_HEALTH_DEGRADATION = "deployment_precedes_health_degradation"
    DEPLOYMENT_FOLLOWS_HEALTH_DEGRADATION = "deployment_follows_health_degradation"
    DEPLOYMENT_PRECEDES_INCIDENT_ONSET = "deployment_precedes_incident_onset"
    DEPLOYMENT_FOLLOWS_INCIDENT_ONSET = "deployment_follows_incident_onset"
    ERROR_PRECEDES_FIRST_REPORT = "error_precedes_first_report"
    HEALTH_DEGRADATION_PRECEDES_FIRST_REPORT = "health_degradation_precedes_first_report"


class CausalCompatibility(StrEnum):
    """Whether an ordering is *consistent with* causality. Never a claim of causality."""

    COMPATIBLE = "temporally_compatible"
    """The candidate cause precedes the symptom, inside the attribution window."""

    INCOMPATIBLE = "temporally_incompatible"
    """The candidate cause follows the symptom. It cannot have initiated it."""

    TOO_DISTANT = "temporally_distant"
    """Correct order, but far enough apart that attribution would be a stretch."""

    NOT_APPLICABLE = "not_applicable"
    """The relationship does not bear on causality — sequencing two symptoms, say."""


class TemporalRelationship(TemporalModel):
    """One deterministic comparison between two observations."""

    id: str
    relationship_type: RelationshipType
    subject_evidence_id: str
    object_evidence_id: str
    # Positive: subject happened before object. Negative: after.
    delta_seconds: int
    compatibility: CausalCompatibility
    detail: str

    @property
    def subject_precedes(self) -> bool:
        return self.delta_seconds > 0


class DeploymentAttribution(TemporalModel):
    """Whether a deployment could, on timing alone, have initiated this incident.

    Emphatically not a root-cause verdict. It answers one narrow question — is the
    ordering consistent — and hands the answer to the investigator and to policy, both of
    which weigh it against service match, failure mechanism and precedent.
    """

    deployment_id: str
    service_id: str
    evidence_id: str
    temporally_plausible: bool
    # Positive when the deployment preceded symptom onset.
    seconds_before_onset: int
    compatibility: CausalCompatibility
    supporting_evidence_ids: tuple[str, ...] = ()
    contradicting_evidence_ids: tuple[str, ...] = ()
    detail: str = ""


class IncidentTimeline(TemporalModel):
    """The chronology of one incident, as the application computed it."""

    incident_id: str
    config_version: str
    onset_at: datetime | None
    onset_evidence_id: str | None
    onset_basis: str
    window_start: datetime | None
    window_end: datetime | None
    observations: tuple[TemporalObservation, ...]
    relationships: tuple[TemporalRelationship, ...]
    attributions: tuple[DeploymentAttribution, ...]
