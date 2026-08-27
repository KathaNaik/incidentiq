"""Building a retrieval query from what is happening now.

One function, so there is a single answer to "what does the system know when it goes
looking for precedent". Everything it uses is derived from ticket text at investigation
time: the reporters' words, the service triage identified, the issue type, and error
identifiers extracted by the same code correlation uses.

Nothing here can reach a root cause or a resolution — those exist only on historical
records, and `RetrievalQuery` has no field to hold one.
"""

from collections.abc import Sequence

from app.correlation.entities import extract_entities
from app.correlation.models import CorrelationTicket
from app.retrieval.models import RetrievalQuery
from app.triage import TriageInput, triage
from app.triage.models import IssueType

# Identifier kinds worth carrying into retrieval. Hostnames and endpoints are dropped:
# they are specific to one deployment and would match nothing across corpora.
USEFUL_ENTITY_KINDS = frozenset({"error_code", "http_status", "identifier", "region"})


def query_from_tickets(tickets: Sequence[CorrelationTicket]) -> RetrievalQuery:
    """Turns the tickets of a candidate incident into one retrieval query."""
    if not tickets:
        raise ValueError("a retrieval query needs at least one ticket")

    ordered = sorted(tickets, key=lambda ticket: (ticket.created_at, ticket.id))

    fragments: list[str] = []
    services: list[str] = []
    errors: list[str] = []
    issue_types: list[str] = []

    for ticket in ordered:
        fragments.append(
            f"{ticket.title.strip()}. {ticket.description.strip()}".strip(". ")
        )

        result = triage(
            TriageInput(
                ticket_id=ticket.id, title=ticket.title, description=ticket.description
            )
        )
        service = ticket.service_id or result.service.value
        if service and service not in services:
            services.append(service)
        if result.issue_type.value != IssueType.UNKNOWN.value:
            issue_types.append(result.issue_type.value)

        for entity in extract_entities(f"{ticket.title} {ticket.description}"):
            if entity.kind in USEFUL_ENTITY_KINDS and entity.value not in errors:
                errors.append(entity.value)

    # The most common issue type across the group, or nothing when the group disagrees.
    issue_type = None
    if issue_types:
        ranked = sorted(set(issue_types), key=lambda value: (-issue_types.count(value), value))
        if issue_types.count(ranked[0]) > len(issue_types) / 2:
            issue_type = ranked[0]

    return RetrievalQuery(
        text="\n".join(fragment for fragment in fragments if fragment),
        services=tuple(services),
        error_identifiers=tuple(errors),
        issue_type=issue_type,
    )
