"""The Polaris feature view: what IncidentIQ could legitimately observe at intake.

This module must not import `ingestion.polaris.labels`, and a test enforces it. Nothing
here should ever need a ground-truth value.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

DATASET_ID = "VladislavMarinovich/polaris-support-tickets-v2"
LICENSE = "CC BY-SA 4.0"
SOURCE_FILE = "polaris_tickets_v2.parquet"

JOIN_KEY = "ticket_id"

FEATURE_COLUMNS = (
    "ticket_id",
    "created_at",
    "channel",
    "plan",
    "user_role",
    "reported_category",
    "subject",
    "body",
)


class PolarisFeatureRecord(BaseModel):
    """A ticket as it would arrive.

    `extra="forbid"` is the structural guard: constructing this record from a raw source
    row raises, because the row also carries labels. Feature records can only be built by
    selecting fields deliberately.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    ticket_id: str
    created_at: datetime
    channel: str
    plan: str
    user_role: str
    # The category the reporter picked. Noisy and frequently wrong — which is exactly
    # why it is a feature and `topic` is a label.
    reported_category: str
    # Empty for a meaningful share of this corpus (chat-originated tickets have no
    # subject line); that is a property of the source, not a defect.
    subject: str
    body: str
