"""Deterministic incident correlation baseline.

Groups tickets that look like reports of one underlying incident, using time proximity,
service, issue type, IDF-weighted lexical overlap, and shared identifiers. No model, no
embeddings — the statistics are computed from the tickets in front of it.

The output is always a *candidate*: a proposal for a human to confirm. Nothing here
creates an incident.
"""

from app.correlation.engine import correlate
from app.correlation.models import (
    CandidateIncident,
    Component,
    Confidence,
    CorrelationResult,
    CorrelationSignal,
    CorrelationTicket,
    Direction,
    PairwiseScore,
)
from app.correlation.pairwise import Corpus, prepare, score_pair, time_score
from app.correlation.rules import CORRELATION_VERSION

__all__ = [
    "CORRELATION_VERSION",
    "CandidateIncident",
    "Component",
    "Confidence",
    "CorrelationResult",
    "CorrelationSignal",
    "CorrelationTicket",
    "Corpus",
    "Direction",
    "PairwiseScore",
    "correlate",
    "prepare",
    "score_pair",
    "time_score",
]
