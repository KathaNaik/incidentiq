"""The two canonical texts: what gets indexed, and what gets asked.

Both live here so the leakage question has one place to look, exactly like
`app.embeddings.text` for correlation.

**Index text is symptoms only** — title, reported summary, observed errors, services.
Root cause and resolution are excluded, and that is the central design decision of this
milestone: if the answer were embedded, retrieval would match answers to answers, the
evaluation would flatter itself, and a real incoming incident (which has no answer yet)
would retrieve worse than the benchmark suggested.

Diagnostics narrative is excluded for the same reason. In the external corpus it
routinely restates the conclusion ("...continued to lock due to stale cached
credentials..."), which is a cause wearing a symptom's clothes.
"""

from app.retrieval.models import HistoricalIncident, RetrievalQuery


def index_text(incident: HistoricalIncident) -> str:
    """What a historical record is embedded as.

    Mirrors the shape of a live query — a title, a description of symptoms, and the
    error strings someone would quote — so the two are comparable.
    """
    parts = [incident.title.strip(), incident.summary.strip()]
    if incident.services:
        parts.append("Services: " + ", ".join(incident.services))
    if incident.observed_errors:
        parts.append("Errors: " + ", ".join(incident.observed_errors))
    return "\n\n".join(part for part in parts if part)


def query_text(query: RetrievalQuery) -> str:
    """What the current situation is embedded as.

    Built only from what is observable while the incident is still open: the reporters'
    words, the services triage identified, and error identifiers extracted from the
    ticket text.
    """
    parts = [query.text.strip()]
    if query.services:
        parts.append("Services: " + ", ".join(query.services))
    if query.error_identifiers:
        parts.append("Errors: " + ", ".join(query.error_identifiers))
    return "\n\n".join(part for part in parts if part)
