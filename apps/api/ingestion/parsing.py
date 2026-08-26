"""Shared parsing and validation helpers for source rows."""

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime

from ingestion.errors import IngestionError


def require_columns(
    row: Mapping[str, object], required: Iterable[str], *, dataset: str
) -> None:
    """Fails loudly when the upstream schema no longer carries what we depend on."""
    missing = [column for column in required if column not in row]
    if missing:
        raise IngestionError(
            f"{dataset}: source row is missing expected column(s) {missing}. "
            "The upstream schema may have changed; update the adapter deliberately "
            "rather than dropping the field."
        )


def parse_timestamp(value: object, *, field: str, assume_utc: bool = False) -> datetime:
    """Parses an ISO-8601 timestamp.

    `assume_utc` attaches UTC to an offset-less value. That is an assumption about the
    source, so it is passed in explicitly at each call site rather than applied silently
    everywhere.
    """
    if not isinstance(value, str) or not value.strip():
        raise IngestionError(f"{field}: expected an ISO-8601 timestamp, got {value!r}")

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise IngestionError(f"{field}: could not parse timestamp {value!r}") from error

    if parsed.tzinfo is None:
        if not assume_utc:
            raise IngestionError(f"{field}: timestamp {value!r} has no timezone offset")
        return parsed.replace(tzinfo=UTC)
    return parsed


def require_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IngestionError(f"{field}: expected non-empty text, got {value!r}")
    return value


def optional_text(value: object) -> str:
    """Empty and missing text collapse to an empty string — both mean 'nothing here'."""
    return value if isinstance(value, str) else ""


def string_list(value: object, *, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise IngestionError(f"{field}: expected a list, got {type(value).__name__}")
    return tuple(str(item) for item in value)
