"""Splits raw Polaris rows into aligned feature and label records.

This is the only module that sees both views. It is the seam: everything downstream reads
one artifact or the other, never a row containing both.
"""

from ingestion.errors import IngestionError
from ingestion.parsing import (
    optional_text,
    parse_timestamp,
    require_columns,
    require_text,
)
from ingestion.polaris.features import (
    DATASET_ID,
    FEATURE_COLUMNS,
    JOIN_KEY,
    PolarisFeatureRecord,
)
from ingestion.polaris.labels import LABEL_COLUMNS, PolarisLabelRecord


def _nullable(value: object) -> str | None:
    """Upstream uses both null and empty string for 'no event'; collapse to one."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def split_row(row: dict) -> tuple[PolarisFeatureRecord, PolarisLabelRecord]:
    require_columns(row, FEATURE_COLUMNS + LABEL_COLUMNS, dataset=DATASET_ID)

    ticket_id = require_text(row[JOIN_KEY], field=JOIN_KEY)

    feature = PolarisFeatureRecord(
        ticket_id=ticket_id,
        # Source timestamps carry no offset. The corpus is generated on a single
        # timeline, so we record them as UTC explicitly rather than leaving them naive.
        created_at=parse_timestamp(
            row["created_at"], field=f"{ticket_id}.created_at", assume_utc=True
        ),
        channel=optional_text(row["channel"]),
        plan=optional_text(row["plan"]),
        user_role=optional_text(row["user_role"]),
        reported_category=optional_text(row["reported_category"]),
        subject=optional_text(row["subject"]),
        # The ticket text is the entire point of the corpus; an empty body would make
        # the record useless for retrieval or correlation.
        body=require_text(row["body"], field=f"{ticket_id}.body"),
    )

    label = PolarisLabelRecord(
        ticket_id=ticket_id,
        topic=optional_text(row["topic"]),
        ticket_type=optional_text(row["type"]),
        priority=optional_text(row["priority"]),
        routing=optional_text(row["routing"]),
        sentiment=optional_text(row["sentiment"]),
        event_id=_nullable(row["event_id"]),
        event_type=_nullable(row["event_type"]),
    )

    return feature, label


def split_rows(
    rows: list[dict],
) -> tuple[tuple[PolarisFeatureRecord, ...], tuple[PolarisLabelRecord, ...]]:
    """Splits every row and checks that the two artifacts stay aligned."""
    features: list[PolarisFeatureRecord] = []
    labels: list[PolarisLabelRecord] = []

    seen: set[str] = set()
    for row in rows:
        feature, label = split_row(row)
        if feature.ticket_id in seen:
            raise IngestionError(f"duplicate {JOIN_KEY} in {DATASET_ID}: {feature.ticket_id}")
        seen.add(feature.ticket_id)
        features.append(feature)
        labels.append(label)

    verify_alignment(tuple(features), tuple(labels))
    return tuple(features), tuple(labels)


def verify_alignment(
    features: tuple[PolarisFeatureRecord, ...], labels: tuple[PolarisLabelRecord, ...]
) -> None:
    """Every feature record has exactly one label record, in the same position.

    Misalignment would silently score predictions against another ticket's answer, which
    looks like a plausible metric rather than a bug.
    """
    if len(features) != len(labels):
        raise IngestionError(
            f"feature/label count mismatch: {len(features)} features, {len(labels)} labels"
        )
    for feature, label in zip(features, labels, strict=True):
        if feature.ticket_id != label.ticket_id:
            raise IngestionError(
                f"feature/label misalignment at {feature.ticket_id}: "
                f"label belongs to {label.ticket_id}"
            )
