"""Historical incident retrieval contracts.

A `HistoricalIncident` is *knowledge*: a resolved case with a known cause and fix. It is
deliberately not a `Ticket` or an `Incident` — a live report has no root cause, and
putting one on it would invite code to read an answer that does not exist yet.

Root cause and resolution live in `outcome`, mirroring the ingestion representation, so
that "retrieve on symptoms, show the outcome afterwards" is a structural property rather
than a convention someone has to remember.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Provenance(StrEnum):
    """Where a historical record came from. Always shown with the record."""

    # Authored by us for the Northstar demo. Original synthetic content.
    NORTHSTAR = "northstar-authored"
    # ameau01/synthetic-it-support-tickets (MIT). Synthetic, externally sourced.
    ITSM = "itsm-mit"


class RetrievalModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class HistoricalOutcome(RetrievalModel):
    """What the incident turned out to be, and what fixed it.

    Never part of the indexed text. Retrieval matches symptoms; this is what the operator
    reads *after* a match, and what makes the match worth surfacing.
    """

    root_cause: str
    resolution_steps: tuple[str, ...] = ()


class HistoricalIncident(RetrievalModel):
    id: str
    title: str
    # The reported symptoms — what an operator would have seen at the time.
    summary: str
    # Applications or services involved, as the source recorded them.
    services: tuple[str, ...] = ()
    # Error strings and identifiers observed during diagnosis.
    observed_errors: tuple[str, ...] = ()
    occurred_at: datetime | None = None
    provenance: Provenance
    outcome: HistoricalOutcome


class RetrievalQuery(RetrievalModel):
    """What is happening now, in the words available at investigation time.

    `extra="forbid"` again: there is no field on this model that could carry a root
    cause, a resolution, or an evaluation label, so none can reach the query text.
    """

    # Free text from the current tickets: titles and descriptions.
    text: str = Field(min_length=1)
    # Predicted or reported service ids, and error identifiers extracted from the
    # current tickets. Used for reranking, never as the answer.
    services: tuple[str, ...] = ()
    error_identifiers: tuple[str, ...] = ()
    issue_type: str | None = None


class MatchSignal(RetrievalModel):
    """One reason a historical incident ranked where it did."""

    kind: str
    detail: str
    contribution: float
    values: tuple[str, ...] = ()


class RetrievalHit(RetrievalModel):
    rank: int
    incident: HistoricalIncident
    # Final ranking score after reranking, in [0, 1].
    score: float
    # Cosine similarity before reranking, kept so the two are separable.
    similarity: float
    signals: tuple[MatchSignal, ...]


class RetrievalResult(RetrievalModel):
    version: str
    provider: str
    # How many records were searched — context for how meaningful a top-K is.
    corpus_size: int
    query_text: str
    hits: tuple[RetrievalHit, ...]
    # False when even the best hit is below the strong-match threshold: the corpus has
    # nothing that looks like this incident, and saying so is more useful than
    # presenting the nearest rows as precedent.
    strong_match: bool
