"""Historical incident retrieval.

Given what is happening now, find resolved incidents that looked like it. The result is
*evidence for an operator* — a set of past cases with their known causes and fixes. The
system does not claim any of them explains the current incident; nothing here reasons.
"""

from app.retrieval.corpus import CorpusError, load_corpus, load_itsm, load_northstar
from app.retrieval.index import HistoricalIndex
from app.retrieval.models import (
    HistoricalIncident,
    HistoricalOutcome,
    MatchSignal,
    Provenance,
    RetrievalHit,
    RetrievalQuery,
    RetrievalResult,
)
from app.retrieval.query import query_from_tickets
from app.retrieval.rules import DEFAULT_K, RETRIEVAL_VERSION
from app.retrieval.text import index_text, query_text

__all__ = [
    "DEFAULT_K",
    "RETRIEVAL_VERSION",
    "CorpusError",
    "HistoricalIncident",
    "HistoricalIndex",
    "HistoricalOutcome",
    "MatchSignal",
    "Provenance",
    "RetrievalHit",
    "RetrievalQuery",
    "RetrievalResult",
    "index_text",
    "load_corpus",
    "load_itsm",
    "load_northstar",
    "query_from_tickets",
    "query_text",
]
