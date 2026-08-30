"""Deriving chronology from evidence.

Everything here is arithmetic over timestamps, which is exactly why none of it is asked
of the model. An LLM given an unordered bag of timestamped facts has to notice that
10:04 precedes 10:09 and subtract them; it will usually be right, and "usually" is not a
property to build a causal argument on. The application computes the ordering and hands
over the result.

**The onset rule, stated once.**

    Incident onset is the earliest *symptom* observation in the evidence: the first error
    signature to begin, the first degraded health reading, or the first correlated ticket
    — whichever came first.

    A deployment is never a symptom. It is a candidate cause, and a candidate cause that
    is allowed to define onset makes "the deployment preceded the incident" true by
    construction with a gap of zero. That bug was found twice: in M11, where the temporal
    check passed vacuously, and again in M13's live run. The rule below is what prevents
    it, and a regression test holds it.

Relationship derivation is deliberately narrow. Every pair of observations could be
compared, which at n observations is n² relationships nobody reads. Only comparisons that
bear on the two questions the product actually asks are derived: is this deployment a
plausible initiating cause, and did machine symptoms precede the humans reporting them.
"""

from collections.abc import Sequence
from datetime import UTC, datetime

from app.investigation.models import EvidenceItem, EvidenceKind
from app.temporal.models import (
    CausalCompatibility,
    DeploymentAttribution,
    IncidentTimeline,
    ObservationType,
    RelationshipType,
    TemporalObservation,
    TemporalRelationship,
)
from app.temporal.rules import (
    ATTRIBUTION_WINDOW,
    LOOKBACK,
    LOOKFORWARD,
    SIMULTANEITY_TOLERANCE,
    TEMPORAL_CONFIG_VERSION,
    UNHEALTHY_STATUSES,
)


def as_utc(value: datetime) -> datetime:
    """Normalises to timezone-aware UTC.

    A naive datetime is treated as UTC rather than rejected: fixtures and JSON round-trips
    produce them, and every timestamp in this system is UTC by convention. Comparing an
    aware and a naive datetime raises in Python, so normalising at the boundary is what
    keeps the ordering code free of defensive checks.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def observations_from(evidence: Sequence[EvidenceItem]) -> tuple[TemporalObservation, ...]:
    """A normalised temporal view over the evidence registry.

    A view, not a copy: `source_evidence_id` points back at the registry item, and nothing
    here is persisted separately. Evidence without a timestamp is skipped — a historical
    precedent has an `occurred_at` from years ago that would only pollute the ordering.
    """
    observations: list[TemporalObservation] = []

    for item in evidence:
        if item.observed_at is None:
            continue
        when = as_utc(item.observed_at)

        if item.kind is EvidenceKind.DEPLOYMENT:
            observations.append(
                TemporalObservation(
                    id=f"obs:deployment:{item.source_id}",
                    key=item.source_id,
                    observation_type=ObservationType.DEPLOYMENT,
                    service_id=item.service_id,
                    observed_at=when,
                    source_evidence_id=item.id,
                    label=f"Deployment {item.source_id}",
                    attributes={"deployment_id": item.source_id},
                )
            )
        elif item.kind is EvidenceKind.ERROR:
            observations.append(
                TemporalObservation(
                    id=f"obs:error:{item.source_id}",
                    key=item.source_id,
                    observation_type=ObservationType.ERROR_ONSET,
                    service_id=item.service_id,
                    observed_at=when,
                    source_evidence_id=item.id,
                    label=f"{item.source_id} first seen",
                    attributes={"error_code": item.source_id},
                )
            )
        elif item.kind is EvidenceKind.HEALTH:
            status = item.attributes.get("status", "unknown")
            degraded = status in UNHEALTHY_STATUSES
            observations.append(
                TemporalObservation(
                    id=f"obs:health:{item.source_id}@{when.isoformat()}",
                    key=f"{item.source_id}@{when.strftime('%d%H%M')}",
                    observation_type=(
                        ObservationType.HEALTH_DEGRADATION
                        if degraded
                        else ObservationType.HEALTH_OBSERVATION
                    ),
                    service_id=item.service_id or item.source_id,
                    observed_at=when,
                    source_evidence_id=item.id,
                    label=f"{item.source_id} health {status}",
                    attributes={"status": status},
                )
            )
        elif item.kind is EvidenceKind.TICKET:
            observations.append(
                TemporalObservation(
                    id=f"obs:ticket:{item.source_id}",
                    key=item.source_id,
                    observation_type=ObservationType.TICKET_REPORT,
                    service_id=item.service_id,
                    observed_at=when,
                    source_evidence_id=item.id,
                    label=f"Report {item.source_id}",
                    attributes={"ticket_id": item.source_id},
                )
            )

    observations.sort(key=lambda entry: (entry.observed_at, entry.id))
    return tuple(observations)


def incident_onset(
    observations: Sequence[TemporalObservation],
) -> tuple[TemporalObservation | None, str]:
    """The earliest symptom, and a sentence explaining which and why.

    Deployments are excluded by `is_symptom`, which is the whole point of the rule.
    """
    symptoms = [entry for entry in observations if entry.is_symptom]
    if not symptoms:
        return None, (
            "no symptom observation is available, so incident onset is undefined; "
            "deployments are candidate causes and never define onset"
        )

    earliest = min(symptoms, key=lambda entry: (entry.observed_at, entry.id))
    kind = {
        ObservationType.ERROR_ONSET: "error signature onset",
        ObservationType.HEALTH_DEGRADATION: "service health degradation",
        ObservationType.TICKET_REPORT: "first correlated report",
    }[earliest.observation_type]
    return earliest, (
        f"earliest symptom is {kind} at {earliest.observed_at.isoformat()} "
        f"({earliest.label}); deployments are excluded from this rule because a "
        "candidate cause that defines onset precedes the incident by construction"
    )


def _classify(delta_seconds: int) -> CausalCompatibility:
    """Ordering to causal compatibility. Never to causation."""
    tolerance = int(SIMULTANEITY_TOLERANCE.total_seconds())
    if delta_seconds <= -tolerance:
        # The candidate cause happened after the symptom.
        return CausalCompatibility.INCOMPATIBLE
    if delta_seconds < tolerance:
        # Inside clock-skew and observation-interval noise: not an ordering.
        return CausalCompatibility.NOT_APPLICABLE
    if delta_seconds > ATTRIBUTION_WINDOW.total_seconds():
        return CausalCompatibility.TOO_DISTANT
    return CausalCompatibility.COMPATIBLE


def _humanise(seconds: int) -> str:
    magnitude = abs(seconds)
    if magnitude < 90:
        return f"{magnitude}s"
    minutes = magnitude / 60
    if minutes < 90:
        return f"{minutes:.0f}m"
    return f"{minutes / 60:.1f}h"


def _relationship(
    subject: TemporalObservation,
    obj: TemporalObservation,
    *,
    precedes_type: RelationshipType,
    follows_type: RelationshipType,
    causal: bool,
) -> TemporalRelationship:
    delta = int((obj.observed_at - subject.observed_at).total_seconds())
    precedes = delta > 0
    kind = precedes_type if precedes else follows_type
    compatibility = (
        _classify(delta) if causal else CausalCompatibility.NOT_APPLICABLE
    )

    if precedes:
        detail = f"{subject.label} preceded {obj.label} by {_humanise(delta)}"
    elif delta == 0:
        detail = f"{subject.label} and {obj.label} share a timestamp"
    else:
        detail = f"{subject.label} followed {obj.label} by {_humanise(delta)}"

    if compatibility is CausalCompatibility.INCOMPATIBLE:
        detail += "; it cannot have initiated this incident"
    elif compatibility is CausalCompatibility.TOO_DISTANT:
        detail += (
            f"; beyond the {int(ATTRIBUTION_WINDOW.total_seconds() // 60)}m attribution "
            "window"
        )

    return TemporalRelationship(
        # Built from short keys rather than full evidence ids. Composing two evidence ids
        # produced 111-character strings containing an embedded ISO timestamp — colons
        # inside a colon-delimited id — and the model truncated one in the eval-v3 run.
        # Validation caught it, which is the guardrail working; an id a careful reader
        # cannot copy exactly is still a bad id.
        id=f"temporal:{kind.value}:{subject.key}:{obj.key}",
        relationship_type=kind,
        subject_evidence_id=subject.source_evidence_id,
        object_evidence_id=obj.source_evidence_id,
        delta_seconds=delta,
        compatibility=compatibility,
        detail=detail,
    )


def derive_relationships(
    observations: Sequence[TemporalObservation],
    onset: TemporalObservation | None,
) -> tuple[TemporalRelationship, ...]:
    """The small set of comparisons that bear on the questions the product asks.

    Not every pair: n observations would give n² relationships, most of them noise. Two
    questions justify a comparison — could this deployment have initiated the incident,
    and did machine symptoms precede the people reporting them.
    """
    deployments = [
        entry
        for entry in observations
        if entry.observation_type is ObservationType.DEPLOYMENT
    ]
    errors = [
        entry
        for entry in observations
        if entry.observation_type is ObservationType.ERROR_ONSET
    ]
    degradations = [
        entry
        for entry in observations
        if entry.observation_type is ObservationType.HEALTH_DEGRADATION
    ]
    reports = [
        entry
        for entry in observations
        if entry.observation_type is ObservationType.TICKET_REPORT
    ]
    first_report = min(reports, key=lambda e: (e.observed_at, e.id)) if reports else None

    relationships: list[TemporalRelationship] = []

    for deployment in deployments:
        for error in errors:
            relationships.append(
                _relationship(
                    deployment,
                    error,
                    precedes_type=RelationshipType.DEPLOYMENT_PRECEDES_ERROR_ONSET,
                    follows_type=RelationshipType.DEPLOYMENT_FOLLOWS_ERROR_ONSET,
                    causal=True,
                )
            )
        for degradation in degradations:
            relationships.append(
                _relationship(
                    deployment,
                    degradation,
                    precedes_type=RelationshipType.DEPLOYMENT_PRECEDES_HEALTH_DEGRADATION,
                    follows_type=RelationshipType.DEPLOYMENT_FOLLOWS_HEALTH_DEGRADATION,
                    causal=True,
                )
            )
        # The onset relationship only earns its place when onset is not already covered
        # above. Onset is usually the first error or the first degradation, and emitting
        # "deployment preceded onset by 3m" beside "deployment preceded that same error by
        # 3m" is the same fact twice in different words.
        already_related = onset is not None and any(
            entry.source_evidence_id == onset.source_evidence_id
            for entry in errors + degradations
        )
        if onset is not None and not already_related:
            relationships.append(
                _relationship(
                    deployment,
                    onset,
                    precedes_type=RelationshipType.DEPLOYMENT_PRECEDES_INCIDENT_ONSET,
                    follows_type=RelationshipType.DEPLOYMENT_FOLLOWS_INCIDENT_ONSET,
                    causal=True,
                )
            )

    # Machine symptoms versus human reports. Not a causal question — customers noticing is
    # not caused by the error in the sense a rollback would address — but it tells an
    # operator whether monitoring saw this before the customers did.
    if first_report is not None:
        for error in errors:
            relationships.append(
                _relationship(
                    error,
                    first_report,
                    precedes_type=RelationshipType.ERROR_PRECEDES_FIRST_REPORT,
                    follows_type=RelationshipType.ERROR_PRECEDES_FIRST_REPORT,
                    causal=False,
                )
            )
        for degradation in degradations:
            relationships.append(
                _relationship(
                    degradation,
                    first_report,
                    precedes_type=RelationshipType.HEALTH_DEGRADATION_PRECEDES_FIRST_REPORT,
                    follows_type=RelationshipType.HEALTH_DEGRADATION_PRECEDES_FIRST_REPORT,
                    causal=False,
                )
            )

    relationships.sort(key=lambda entry: entry.id)
    return tuple(relationships)


def attribute_deployments(
    observations: Sequence[TemporalObservation],
    onset: TemporalObservation | None,
    relationships: Sequence[TemporalRelationship],
) -> tuple[DeploymentAttribution, ...]:
    """Whether each deployment could, on timing alone, have initiated the incident.

    Four conditions, all necessary and none sufficient: the deployment is on the affected
    service, it precedes symptom onset, the gap is inside the attribution window, and no
    symptom clearly predates it. Failing any of them makes the deployment implausible as
    the *initiating* cause; passing all of them makes it a candidate and nothing more.
    """
    deployments = [
        entry
        for entry in observations
        if entry.observation_type is ObservationType.DEPLOYMENT
    ]
    symptoms = [entry for entry in observations if entry.is_symptom]
    attributions: list[DeploymentAttribution] = []

    for deployment in deployments:
        if onset is None:
            attributions.append(
                DeploymentAttribution(
                    deployment_id=deployment.attributes.get("deployment_id", ""),
                    service_id=deployment.service_id or "unknown",
                    evidence_id=deployment.source_evidence_id,
                    temporally_plausible=False,
                    seconds_before_onset=0,
                    compatibility=CausalCompatibility.NOT_APPLICABLE,
                    detail=(
                        "no symptom observation establishes when the incident began, so "
                        "this deployment cannot be placed relative to it"
                    ),
                )
            )
            continue

        delta = int((onset.observed_at - deployment.observed_at).total_seconds())
        compatibility = _classify(delta)

        # Symptoms that clearly predate the deployment contradict it as the initiating
        # cause, whatever the onset arithmetic says on its own.
        tolerance = int(SIMULTANEITY_TOLERANCE.total_seconds())
        earlier_symptoms = [
            entry
            for entry in symptoms
            if (deployment.observed_at - entry.observed_at).total_seconds() >= tolerance
        ]
        contradicting = tuple(
            sorted({entry.source_evidence_id for entry in earlier_symptoms})
        )

        supporting = tuple(
            sorted(
                {
                    relationship.id
                    for relationship in relationships
                    if relationship.subject_evidence_id == deployment.source_evidence_id
                    and relationship.compatibility is CausalCompatibility.COMPATIBLE
                }
            )
        )

        plausible = (
            compatibility is CausalCompatibility.COMPATIBLE and not contradicting
        )

        if contradicting:
            detail = (
                f"{len(contradicting)} symptom observation(s) predate this deployment; "
                "it cannot be what started the incident"
            )
        elif compatibility is CausalCompatibility.INCOMPATIBLE:
            detail = (
                f"deployed {_humanise(delta)} after symptom onset; it cannot be what "
                "started the incident"
            )
        elif compatibility is CausalCompatibility.TOO_DISTANT:
            detail = (
                f"deployed {_humanise(delta)} before symptom onset, beyond the "
                f"{int(ATTRIBUTION_WINDOW.total_seconds() // 60)}m attribution window"
            )
        elif compatibility is CausalCompatibility.NOT_APPLICABLE:
            detail = "deployed at effectively the same time as symptom onset"
        else:
            detail = (
                f"deployed {_humanise(delta)} before symptom onset, and no symptom "
                "predates it — timing is consistent with it having initiated this "
                "incident, which is not the same as evidence that it did"
            )

        attributions.append(
            DeploymentAttribution(
                deployment_id=deployment.attributes.get("deployment_id", ""),
                service_id=deployment.service_id or "unknown",
                evidence_id=deployment.source_evidence_id,
                temporally_plausible=plausible,
                seconds_before_onset=delta,
                compatibility=compatibility,
                supporting_evidence_ids=supporting,
                contradicting_evidence_ids=contradicting,
                detail=detail,
            )
        )

    attributions.sort(key=lambda entry: entry.deployment_id)
    return tuple(attributions)


def build_timeline(
    *, incident_id: str, evidence: Sequence[EvidenceItem]
) -> IncidentTimeline:
    """The whole chronology for one incident, computed deterministically."""
    observations = observations_from(evidence)
    onset, basis = incident_onset(observations)
    relationships = derive_relationships(observations, onset)
    attributions = attribute_deployments(observations, onset, relationships)

    window_start = onset.observed_at - LOOKBACK if onset else None
    window_end = onset.observed_at + LOOKFORWARD if onset else None

    return IncidentTimeline(
        incident_id=incident_id,
        config_version=TEMPORAL_CONFIG_VERSION,
        onset_at=onset.observed_at if onset else None,
        onset_evidence_id=onset.source_evidence_id if onset else None,
        onset_basis=basis,
        window_start=window_start,
        window_end=window_end,
        observations=observations,
        relationships=relationships,
        attributions=attributions,
    )
