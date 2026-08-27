"""The one place a ticket becomes embedding input.

Everything that embeds a ticket calls `embedding_text`. Centralizing it means the
question "could a label reach the model?" has exactly one place to look.

**Title and description only.** Service is deliberately excluded even though it is
available at runtime: it already scores as its own correlation signal, and folding it
into the embedded text would double-count service agreement — which is the exact failure
mode the deterministic baseline showed on Polaris, where same-service tickets from
different incidents were merged.
"""

from typing import Protocol


class EmbeddableTicket(Protocol):
    """The minimum a ticket must expose to be embedded.

    Structural rather than an import of `CorrelationTicket`: the embedding layer sits
    below correlation and must not depend on it — importing upward creates a cycle, and
    it would also let a future field on the correlation model silently become embedding
    input.
    """

    @property
    def title(self) -> str: ...

    @property
    def description(self) -> str: ...


def embedding_text(ticket: EmbeddableTicket) -> str:
    """Canonical text for one ticket.

    Only the two fields above. Callers pass models that forbid unknown fields, so a
    Polaris row carrying `event_id`, `topic`, `routing` or a ground-truth priority
    cannot be constructed, let alone embedded — and even if one could, nothing but the
    title and description would be read.
    """
    title = ticket.title.strip()
    description = ticket.description.strip()
    if not description:
        return title
    return f"{title}\n\n{description}"
