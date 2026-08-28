"""Typed evidence sources.

Four functions over synthetic Northstar fixtures. Each has typed inputs, typed outputs,
and deterministic behaviour, and each carries a provenance string that says the data is
synthetic — these are not Datadog, ServiceNow, or any real integration, and the UI never
implies otherwise.

They are plain functions, not model-callable tools: this milestone collects evidence
deterministically and then makes exactly one model call. The model chooses nothing about
what it gets to see.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

OPERATIONS_FILE = "operations.json"

# Every operational record in this prototype is fabricated. Shown wherever evidence is.
SYNTHETIC_PROVENANCE = "Northstar Cloud synthetic operations fixture"

# A deployment is worth surfacing if it landed within this window before the incident.
# Wide enough to catch a slow-burn regression, narrow enough that an unrelated release
# from days earlier does not present itself as a suspect.
DEPLOYMENT_LOOKBACK = timedelta(hours=6)
# Health and error signals are matched to the incident window with this tolerance.
SIGNAL_WINDOW = timedelta(hours=6)


class ToolError(RuntimeError):
    """Operational evidence could not be read."""


class OperationsModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class DeploymentRecord(OperationsModel):
    id: str
    service_id: str
    version: str
    deployed_at: datetime
    status: str
    change_summary: str


class ServiceHealthSnapshot(OperationsModel):
    service_id: str
    observed_at: datetime
    status: str
    signals: tuple[str, ...]


class ErrorSummary(OperationsModel):
    service_id: str
    code: str
    count: int
    first_seen: datetime
    last_seen: datetime
    sample_message: str


class OperationsFixtures(OperationsModel):
    deployments: tuple[DeploymentRecord, ...]
    health: tuple[ServiceHealthSnapshot, ...]
    errors: tuple[ErrorSummary, ...]


def load_operations(directory: Path) -> OperationsFixtures:
    path = directory / OPERATIONS_FILE
    if not path.is_file():
        raise ToolError(f"missing operational fixtures: {path}")

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not payload.get("synthetic"):
        raise ToolError(f"{path.name} is not marked synthetic")

    try:
        return OperationsFixtures(
            deployments=tuple(payload["deployments"]),
            health=tuple(payload["health"]),
            errors=tuple(payload["errors"]),
        )
    except (KeyError, ValidationError) as error:
        raise ToolError(f"invalid operational fixtures: {error}") from error


def get_recent_deployments(
    fixtures: OperationsFixtures, service_id: str | None, before: datetime
) -> tuple[DeploymentRecord, ...]:
    """Deployments to a service in the window before an incident began.

    Returns nothing when the service is unknown — an incident nobody could attribute to
    a service should not be handed every deployment in the estate.
    """
    if service_id is None:
        return ()
    window_start = before - DEPLOYMENT_LOOKBACK
    matched = [
        deployment
        for deployment in fixtures.deployments
        if deployment.service_id == service_id
        and window_start <= deployment.deployed_at <= before
    ]
    return tuple(sorted(matched, key=lambda item: item.deployed_at, reverse=True))


def get_service_health(
    fixtures: OperationsFixtures, service_id: str | None, around: datetime
) -> ServiceHealthSnapshot | None:
    """The health snapshot closest to the incident, within the signal window."""
    if service_id is None:
        return None
    candidates = [
        snapshot
        for snapshot in fixtures.health
        if snapshot.service_id == service_id
        and abs(snapshot.observed_at - around) <= SIGNAL_WINDOW
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda item: (abs(item.observed_at - around), item.observed_at))


def get_error_summary(
    fixtures: OperationsFixtures, service_id: str | None, around: datetime
) -> tuple[ErrorSummary, ...]:
    """Error signatures overlapping the incident window, busiest first."""
    if service_id is None:
        return ()
    window_start = around - SIGNAL_WINDOW
    window_end = around + SIGNAL_WINDOW
    matched = [
        summary
        for summary in fixtures.errors
        if summary.service_id == service_id
        and summary.first_seen <= window_end
        and summary.last_seen >= window_start
    ]
    return tuple(sorted(matched, key=lambda item: (-item.count, item.code)))
