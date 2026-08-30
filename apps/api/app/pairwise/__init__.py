"""Direct pairwise incident classification.

M17 established that whole-ticket cosine measures topical resemblance rather than incident
identity. This models the decision directly — *does this arriving ticket belong to this
candidate* — with a small supervised classifier over the structured signals the
deterministic engine already computes.

It is a **scorer, never the authority**. The M16 eligibility gate decides whether it runs
at all, and hard conflicts and complete-link cohesion can each refuse an attachment it
scored highly.
"""

from app.pairwise.features import (
    FEATURE_NAMES,
    FEATURE_SCHEMA_VERSION,
    PairwiseExample,
    extract,
)
from app.pairwise.model import (
    PAIRWISE_VERSION,
    THRESHOLD_RULE,
    PairwiseModelError,
    TrainedModel,
    load,
)

__all__ = [
    "FEATURE_NAMES",
    "FEATURE_SCHEMA_VERSION",
    "PAIRWISE_VERSION",
    "THRESHOLD_RULE",
    "PairwiseExample",
    "PairwiseModelError",
    "TrainedModel",
    "extract",
    "load",
]
