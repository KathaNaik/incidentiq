"""Normalization for `ameau01/synthetic-it-support-tickets` (MIT).

This is an ingestion representation, not a domain model. The source carries a resolved
incident — troubleshooting correspondence, diagnostics, root cause, and resolution steps
— which is a *historical* record. IncidentIQ's `Ticket` describes a live report and has
no business growing a `root_cause` field to accommodate this source.

Root cause and resolution are grouped under `outcome` for a reason: when this corpus is
used to evaluate root-cause reasoning, the outcome is the answer key and must be withheld
from the query side. Keeping it in one nested object makes dropping it a single, obvious
operation rather than remembering four field names.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from ingestion.errors import IngestionError
from ingestion.parsing import (
    optional_text,
    parse_timestamp,
    require_columns,
    require_text,
    string_list,
)

DATASET_ID = "ameau01/synthetic-it-support-tickets"
LICENSE = "MIT"
SOURCE_FILE = "data/train.parquet"

REQUIRED_COLUMNS = (
    "record_id",
    "record_type",
    "ticket",
    "status",
    "correspondence",
    "diagnostics",
    "root_cause",
    "resolution",
)


class IngestionModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ItsmEnvironment(IngestionModel):
    os: str
    platform: str
    region: str
    user_group: str


class ItsmCorrespondenceTurn(IngestionModel):
    turn_id: int
    role: str
    event_type: str
    message: str
    timestamp: datetime


class ItsmOutcome(IngestionModel):
    """Ground truth: what actually caused the incident and how it was fixed."""

    root_cause: str
    resolution_steps: tuple[str, ...]


class ItsmRecord(IngestionModel):
    source_id: str
    record_type: str
    status: str
    priority: str
    submitted_at: datetime
    title: str
    description: str
    applications: tuple[str, ...]
    environment: ItsmEnvironment
    correspondence: tuple[ItsmCorrespondenceTurn, ...]
    diagnostics_summary: str
    observed_errors: tuple[str, ...]
    outcome: ItsmOutcome


def normalize_row(row: dict) -> ItsmRecord:
    """Maps one source row onto the normalized record.

    Deliberately dropped: `ticket.sla_plan` (no product use), `diagnostics.coverage`
    (a generation parameter), and `diagnostics.steps` (verbose per-step playbook detail
    that duplicates the correspondence). Add them back when something consumes them.
    """
    require_columns(row, REQUIRED_COLUMNS, dataset=DATASET_ID)

    source_id = require_text(row["record_id"], field="record_id")
    ticket = row["ticket"] or {}
    diagnostics = row["diagnostics"] or {}
    resolution = row["resolution"] or {}

    if not isinstance(ticket, dict) or not isinstance(diagnostics, dict):
        raise IngestionError(f"{source_id}: expected nested ticket/diagnostics objects")

    environment = ticket.get("environment") or {}
    return ItsmRecord(
        source_id=source_id,
        record_type=require_text(row["record_type"], field=f"{source_id}.record_type"),
        status=optional_text(row["status"]),
        priority=optional_text(ticket.get("priority")),
        submitted_at=parse_timestamp(
            ticket.get("submitted_at"), field=f"{source_id}.ticket.submitted_at"
        ),
        title=require_text(
            ticket.get("submitted_title"), field=f"{source_id}.ticket.submitted_title"
        ),
        description=require_text(
            ticket.get("submitted_description"),
            field=f"{source_id}.ticket.submitted_description",
        ),
        applications=string_list(
            ticket.get("applications"), field=f"{source_id}.ticket.applications"
        ),
        environment=ItsmEnvironment(
            os=optional_text(environment.get("os")),
            platform=optional_text(environment.get("platform")),
            region=optional_text(environment.get("region")),
            user_group=optional_text(environment.get("user_group")),
        ),
        correspondence=tuple(
            _normalize_turn(turn, source_id=source_id)
            for turn in (row["correspondence"] or ())
        ),
        diagnostics_summary=optional_text(diagnostics.get("summary")),
        observed_errors=string_list(
            diagnostics.get("observed_errors"),
            field=f"{source_id}.diagnostics.observed_errors",
        ),
        outcome=ItsmOutcome(
            # The corpus exists to teach retrieval what a real cause and fix look like;
            # a record without them is not usable for that and is a schema surprise.
            root_cause=require_text(row["root_cause"], field=f"{source_id}.root_cause"),
            resolution_steps=string_list(
                resolution.get("steps"), field=f"{source_id}.resolution.steps"
            ),
        ),
    )


def _normalize_turn(turn: object, *, source_id: str) -> ItsmCorrespondenceTurn:
    if not isinstance(turn, dict):
        raise IngestionError(f"{source_id}: correspondence entry is not an object")
    return ItsmCorrespondenceTurn(
        turn_id=int(turn.get("turn_id", 0)),
        role=optional_text(turn.get("role")),
        event_type=optional_text(turn.get("event_type")),
        message=optional_text(turn.get("message")),
        timestamp=parse_timestamp(
            turn.get("timestamp"), field=f"{source_id}.correspondence.timestamp"
        ),
    )


def normalize_rows(rows: list[dict]) -> tuple[ItsmRecord, ...]:
    """Normalizes every row, then checks corpus-level invariants."""
    records = tuple(normalize_row(row) for row in rows)

    seen: set[str] = set()
    for record in records:
        if record.source_id in seen:
            raise IngestionError(f"duplicate source_id in {DATASET_ID}: {record.source_id}")
        seen.add(record.source_id)

    return records
