"""Loading and validation of on-disk fixture datasets.

A dataset is a directory of JSON files, each an envelope carrying its records:

    {"dataset": "northstar-cloud", "synthetic": true, "records": [...]}

The `synthetic` flag is mandatory and must be true. IncidentIQ ships fabricated data for
development and demos; requiring the file to say so keeps an unlabelled dataset from
quietly becoming the thing the UI presents as real.

Referential integrity is checked here, at the ingestion boundary, so nothing downstream
has to defend against a ticket pointing at a service that does not exist.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, TypeAdapter, ValidationError

from app.domain.models import Incident, IncidentTicket, Service, Ticket

ModelT = TypeVar("ModelT", bound=BaseModel)

SERVICES_FILE = "services.json"
TICKETS_FILE = "tickets.json"
INCIDENTS_FILE = "incidents.json"
INCIDENT_TICKETS_FILE = "incident_tickets.json"


class FixtureError(ValueError):
    """A fixture dataset is missing, malformed, or internally inconsistent."""


@dataclass(frozen=True)
class Dataset:
    """A validated, internally consistent set of records."""

    name: str
    services: tuple[Service, ...]
    tickets: tuple[Ticket, ...]
    incidents: tuple[Incident, ...]
    incident_tickets: tuple[IncidentTicket, ...]


class _Envelope(BaseModel):
    dataset: str
    synthetic: bool
    records: list[dict]


def _read_envelope(path: Path) -> _Envelope:
    if not path.is_file():
        raise FixtureError(f"missing fixture file: {path}")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        envelope = _Envelope.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as error:
        raise FixtureError(f"invalid fixture file {path.name}: {error}") from error

    if not envelope.synthetic:
        raise FixtureError(
            f"{path.name} is not marked synthetic; IncidentIQ only loads fixture data "
            "that declares itself fabricated"
        )
    return envelope


def _parse(path: Path, model: type[ModelT]) -> tuple[str, tuple[ModelT, ...]]:
    envelope = _read_envelope(path)
    adapter = TypeAdapter(tuple[model, ...])  # type: ignore[valid-type]
    try:
        records = adapter.validate_python(envelope.records)
    except ValidationError as error:
        raise FixtureError(f"invalid records in {path.name}: {error}") from error
    return envelope.dataset, records


def _unique_ids(records: Sequence[Service | Ticket | Incident], label: str) -> set[str]:
    ids: set[str] = set()
    for record in records:
        if record.id in ids:
            raise FixtureError(f"duplicate {label} id: {record.id}")
        ids.add(record.id)
    return ids


def load_dataset(directory: Path) -> Dataset:
    """Loads and validates the fixture dataset in `directory`.

    Raises FixtureError on anything inconsistent — a missing file, an unlabelled dataset,
    a duplicate id, or a reference to a record that does not exist.
    """
    dataset_names: set[str] = set()

    name, services = _parse(directory / SERVICES_FILE, Service)
    dataset_names.add(name)
    name, tickets = _parse(directory / TICKETS_FILE, Ticket)
    dataset_names.add(name)
    name, incidents = _parse(directory / INCIDENTS_FILE, Incident)
    dataset_names.add(name)
    name, incident_tickets = _parse(directory / INCIDENT_TICKETS_FILE, IncidentTicket)
    dataset_names.add(name)

    if len(dataset_names) != 1:
        raise FixtureError(f"files disagree on dataset name: {sorted(dataset_names)}")

    service_ids = _unique_ids(services, "service")
    ticket_ids = _unique_ids(tickets, "ticket")
    incident_ids = _unique_ids(incidents, "incident")

    for ticket in tickets:
        if ticket.service_id is not None and ticket.service_id not in service_ids:
            raise FixtureError(
                f"ticket {ticket.id} references unknown service {ticket.service_id}"
            )

    for incident in incidents:
        for service_id in incident.affected_service_ids:
            if service_id not in service_ids:
                raise FixtureError(
                    f"incident {incident.id} references unknown service {service_id}"
                )

    linked_tickets: dict[str, str] = {}
    for link in incident_tickets:
        if link.incident_id not in incident_ids:
            raise FixtureError(f"link references unknown incident {link.incident_id}")
        if link.ticket_id not in ticket_ids:
            raise FixtureError(f"link references unknown ticket {link.ticket_id}")
        # One ticket, at most one incident: a ticket reports a single experience of a
        # single failure. Revisit only if a real case needs a ticket in two incidents.
        existing = linked_tickets.get(link.ticket_id)
        if existing == link.incident_id:
            raise FixtureError(
                f"duplicate incident-ticket link: {link.incident_id} -> {link.ticket_id}"
            )
        if existing is not None:
            raise FixtureError(
                f"ticket {link.ticket_id} is linked to more than one incident: "
                f"{existing} and {link.incident_id}"
            )
        linked_tickets[link.ticket_id] = link.incident_id

    return Dataset(
        name=dataset_names.pop(),
        services=services,
        tickets=tickets,
        incidents=incidents,
        incident_tickets=incident_tickets,
    )
