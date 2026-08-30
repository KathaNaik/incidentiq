"""Temporal evidence: chronology computed by the application, not by the model.

Ordering timestamps is arithmetic. Handing an LLM an unordered bag of timestamped facts
and asking it to notice which came first works most of the time, and "most of the time" is
not a foundation for a causal argument that ends in a rollback.

So the application derives the ordering, the gaps, and whether each ordering is
*consistent with* causality — and the model reasons about plausibility on top of facts it
did not have to compute.

The distinction this module refuses to blur: temporal order is necessary evidence for
causality, never sufficient proof of it. Nothing here returns "caused".
"""

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
    TEMPORAL_CONFIG_VERSION,
)
from app.temporal.timeline import (
    as_utc,
    attribute_deployments,
    build_timeline,
    derive_relationships,
    incident_onset,
    observations_from,
)

__all__ = [
    "ATTRIBUTION_WINDOW",
    "LOOKBACK",
    "LOOKFORWARD",
    "TEMPORAL_CONFIG_VERSION",
    "CausalCompatibility",
    "DeploymentAttribution",
    "IncidentTimeline",
    "ObservationType",
    "RelationshipType",
    "TemporalObservation",
    "TemporalRelationship",
    "as_utc",
    "attribute_deployments",
    "build_timeline",
    "derive_relationships",
    "incident_onset",
    "observations_from",
]
