"""The one place a ticket becomes embedding input.

Everything that embeds a ticket calls `embedding_text`. Centralizing it means the
question "could a label reach the model?" has exactly one place to look.

**Title and description only.** Service is deliberately excluded even though it is
available at runtime: it already scores as its own correlation signal, and folding it
into the embedded text would double-count service agreement — which is the exact failure
mode the deterministic baseline showed on Polaris, where same-service tickets from
different incidents were merged.
"""

from app.correlation.models import CorrelationTicket


def embedding_text(ticket: CorrelationTicket) -> str:
    """Canonical text for one ticket.

    Only fields present on `CorrelationTicket`, whose model forbids unknown fields — so
    a Polaris row carrying `event_id`, `topic`, `routing` or a ground-truth priority
    cannot be constructed, let alone embedded.
    """
    title = ticket.title.strip()
    description = ticket.description.strip()
    if not description:
        return title
    return f"{title}\n\n{description}"
