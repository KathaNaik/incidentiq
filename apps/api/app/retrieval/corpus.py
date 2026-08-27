"""Loading the historical corpus.

Two sources, and every record says which one it came from:

- **Northstar** — authored by us, committed, part of the demo.
- **ITSM** — `ameau01/synthetic-it-support-tickets` (MIT), normalized by the ingestion
  layer, never committed. Present only after the download and preprocess scripts run.

The two are never blended into one anonymous pile: `provenance` travels with each record
and is displayed wherever a record is shown, so a demo audience can tell what is ours
from what is borrowed.
"""

import json
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from app.retrieval.models import HistoricalIncident, HistoricalOutcome, Provenance

NORTHSTAR_FILE = "historical_incidents.json"
ITSM_RECORDS_FILE = "records.jsonl"


class CorpusError(RuntimeError):
    """The historical corpus is missing or malformed."""


def load_northstar(directory: Path) -> tuple[HistoricalIncident, ...]:
    """Authored historical incidents for the Northstar demo."""
    path = directory / NORTHSTAR_FILE
    if not path.is_file():
        raise CorpusError(f"missing authored historical incidents: {path}")

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not payload.get("synthetic"):
        raise CorpusError(f"{path.name} is not marked synthetic")

    try:
        return tuple(
            HistoricalIncident(provenance=Provenance.NORTHSTAR, **record)
            for record in payload["records"]
        )
    except ValidationError as error:
        raise CorpusError(f"invalid authored historical incident: {error}") from error


def load_itsm(directory: Path) -> tuple[HistoricalIncident, ...]:
    """The external corpus, adapted from the ingestion representation.

    Only the observable half of each record becomes searchable text; the outcome is
    carried alongside for display. See `app.retrieval.text` for why.
    """
    path = directory / ITSM_RECORDS_FILE
    if not path.is_file():
        return ()

    records: list[HistoricalIncident] = []
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                records.append(
                    HistoricalIncident(
                        id=row["source_id"],
                        title=row["title"],
                        summary=row["description"],
                        services=tuple(row.get("applications", ())),
                        observed_errors=tuple(row.get("observed_errors", ())),
                        occurred_at=row.get("submitted_at"),
                        provenance=Provenance.ITSM,
                        outcome=HistoricalOutcome(
                            root_cause=row["outcome"]["root_cause"],
                            resolution_steps=tuple(
                                row["outcome"].get("resolution_steps", ())
                            ),
                        ),
                    )
                )
            except (json.JSONDecodeError, KeyError, ValidationError) as error:
                raise CorpusError(f"{path.name} line {number}: {error}") from error
    return tuple(records)


def load_corpus(
    northstar_dir: Path, itsm_dir: Path, *, include_itsm: bool = True
) -> tuple[HistoricalIncident, ...]:
    """Both sources, with ids checked for collisions across them."""
    records = list(load_northstar(northstar_dir))
    if include_itsm:
        records.extend(load_itsm(itsm_dir))

    seen: set[str] = set()
    for record in records:
        if record.id in seen:
            raise CorpusError(f"duplicate historical incident id: {record.id}")
        seen.add(record.id)
    return tuple(records)


def family_of(incident_id: str) -> str:
    """The root-cause family an external record belongs to.

    External record ids look like `INC-ALP-0042`, where `INC-ALP` groups every record
    sharing one underlying failure pattern. Used **only** by the evaluation as ground
    truth — it is not part of any indexed text, query, or score.
    """
    return incident_id.rsplit("-", 1)[0]


def families(records: Sequence[HistoricalIncident]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for record in records:
        grouped.setdefault(family_of(record.id), []).append(record.id)
    return grouped
