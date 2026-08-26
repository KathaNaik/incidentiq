"""Deterministic ticket triage baseline.

Rules live in `rules.py` as data; `engine.py` only orchestrates. Nothing in this package
calls a model, and that is the point — it is the baseline an LLM-assisted approach will
have to beat on a measured metric.
"""

from app.triage.engine import triage, triage_ticket
from app.triage.models import (
    IssueType,
    PredictionStatus,
    TriageInput,
    TriagePrediction,
    TriageResult,
    TriageSignal,
)
from app.triage.rules import TRIAGE_VERSION

__all__ = [
    "IssueType",
    "PredictionStatus",
    "TRIAGE_VERSION",
    "TriageInput",
    "TriagePrediction",
    "TriageResult",
    "TriageSignal",
    "triage",
    "triage_ticket",
]
