"""The Polaris label view: ground truth, for scoring only.

Nothing in this module may be read by runtime code, feature construction, embedding text,
or a prompt. It exists so evaluation can compare a prediction against an answer that the
predictor never saw.

`event_id` is the correlation answer key: tickets sharing one are reports of the same
underlying service event. Feeding it into clustering would score a system that was handed
the answer.
"""

from pydantic import BaseModel, ConfigDict

# Same key as the feature view; the two artifacts align on it and nothing else.
JOIN_KEY = "ticket_id"

LABEL_COLUMNS = (
    "ticket_id",
    "topic",
    "type",
    "priority",
    "routing",
    "sentiment",
    "event_id",
    "event_type",
)


class PolarisLabelRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ticket_id: str
    topic: str
    # `type` upstream; renamed to avoid shadowing the builtin at every call site.
    ticket_type: str
    priority: str
    routing: str
    sentiment: str
    # Null for tickets that belong to no service event — most of the corpus.
    event_id: str | None
    event_type: str | None


def label_only_fields() -> frozenset[str]:
    """Label fields excluding the join key.

    Derived from the model rather than hard-coded, so a label added later is covered by
    the leakage tests without anyone remembering to update a list.
    """
    return frozenset(PolarisLabelRecord.model_fields) - {JOIN_KEY}
