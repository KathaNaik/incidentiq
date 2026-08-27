"""Typed evaluation output.

An eval report is an artifact: it records which version was measured, on what, and every
case it got wrong. A number without the failures behind it is not useful for deciding
whether to reach for a model.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class EvalModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class MetricSummary(EvalModel):
    name: str
    correct: int
    total: int
    accuracy: float
    # Predictions that declined to commit (ambiguous or unknown). Counted separately
    # because abstaining is a designed outcome, not the same failure as being wrong.
    # Not every metric has a notion of abstaining; those report zero.
    abstained: int = 0
    # What a trivial always-predict-the-most-common-label system would score. Without
    # it an accuracy figure means very little.
    majority_baseline: float | None = None


class ConfusionCell(EvalModel):
    expected: str
    predicted: str
    count: int


class CaseFailure(EvalModel):
    case_id: str
    metric: str
    expected: str | None
    predicted: str | None
    status: str
    explanation: str
    signals: tuple[str, ...]
    # Populated only for cases we authored. Reports covering licensed corpora carry no
    # source text, so the artifact never becomes a partial copy of the dataset.
    text: str | None = None


class EvalReport(EvalModel):
    suite: str
    version: str
    generated_at: datetime
    case_count: int
    metrics: tuple[MetricSummary, ...]
    confusion: tuple[ConfusionCell, ...]
    failures: tuple[CaseFailure, ...]
    notes: tuple[str, ...] = ()
