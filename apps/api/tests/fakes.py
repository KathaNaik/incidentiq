"""In-memory stand-ins for the durable stores.

These exist so the fast suite stays fast and offline. They are **fakes, not equivalents**:
the real duplicate-run protection is a PostgreSQL partial unique index and the real
execution-once guarantee is a unique constraint, and neither can be reproduced here. Both
are covered by `test_persistence_pg.py`, which runs against a real database.

`FakeInvestigationRunStore` is checked against the real store's behaviour in that suite,
so the two cannot drift silently.
"""

from collections.abc import Sequence
from datetime import UTC, datetime

from app.db.investigation_store import (
    ActiveRunExistsError,
    RunStatus,
    StoredRun,
    new_run_id,
)
from app.investigation.models import EvidenceItem, InvestigationOutput


class FakeInvestigationRunStore:
    """Mirrors `InvestigationRunStore` over a dict."""

    def __init__(self) -> None:
        self._runs: dict[str, StoredRun] = {}

    def begin(
        self,
        *,
        incident_id: str,
        investigator_version: str,
        prompt_version: str,
        provider: str,
        model: str,
        evidence: Sequence[EvidenceItem],
    ) -> StoredRun:
        active = self.active(incident_id)
        if active is not None:
            raise ActiveRunExistsError(active)
        now = datetime.now(UTC)
        run = StoredRun(
            id=new_run_id(),
            incident_id=incident_id,
            investigator_version=investigator_version,
            prompt_version=prompt_version,
            provider=provider,
            model=model,
            status=RunStatus.RUNNING.value,
            created_at=now,
            started_at=now,
            completed_at=None,
            evidence=tuple(evidence),
            output=None,
            latency_ms=None,
            input_tokens=None,
            output_tokens=None,
            reasoning_tokens=None,
            failure_type=None,
            failure_message=None,
        )
        self._runs[run.id] = run
        return run

    def complete(
        self,
        run_id: str,
        *,
        output: InvestigationOutput,
        model: str,
        latency_ms: int,
        input_tokens: int | None,
        output_tokens: int | None,
        reasoning_tokens: int | None,
    ) -> StoredRun:
        run = self._mutable(run_id)
        updated = _replace(
            run,
            status=RunStatus.SUCCEEDED.value,
            completed_at=datetime.now(UTC),
            output=output,
            model=model,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            reasoning_tokens=reasoning_tokens,
        )
        self._runs[run_id] = updated
        return updated

    def fail(self, run_id: str, *, failure_type: str, message: str) -> StoredRun:
        run = self._mutable(run_id)
        updated = _replace(
            run,
            status=RunStatus.FAILED.value,
            completed_at=datetime.now(UTC),
            failure_type=failure_type,
            failure_message=message[:2000],
        )
        self._runs[run_id] = updated
        return updated

    def _mutable(self, run_id: str) -> StoredRun:
        run = self._runs.get(run_id)
        if run is None:
            raise KeyError(f"unknown investigation run: {run_id}")
        if run.status not in (RunStatus.PENDING.value, RunStatus.RUNNING.value):
            raise ValueError(
                f"investigation {run_id} is {run.status} and is immutable; "
                "a new investigation creates a new run"
            )
        return run

    def get(self, run_id: str) -> StoredRun | None:
        return self._runs.get(run_id)

    def active(self, incident_id: str) -> StoredRun | None:
        return self._first(
            incident_id, {RunStatus.PENDING.value, RunStatus.RUNNING.value}
        )

    def latest_successful(self, incident_id: str) -> StoredRun | None:
        return self._first(incident_id, {RunStatus.SUCCEEDED.value})

    def latest(self, incident_id: str) -> StoredRun | None:
        return self._first(incident_id, None)

    def history(self, incident_id: str, *, limit: int = 20) -> tuple[StoredRun, ...]:
        runs = [run for run in self._runs.values() if run.incident_id == incident_id]
        runs.sort(key=lambda run: (run.created_at, run.id), reverse=True)
        return tuple(runs[:limit])

    def _first(self, incident_id: str, statuses: set[str] | None) -> StoredRun | None:
        runs = [
            run
            for run in self._runs.values()
            if run.incident_id == incident_id
            and (statuses is None or run.status in statuses)
        ]
        if not runs:
            return None
        return max(runs, key=lambda run: (run.created_at, run.id))


def _replace(run: StoredRun, **changes) -> StoredRun:
    values = {
        field: getattr(run, field)
        for field in StoredRun.__dataclass_fields__
    }
    values.update(changes)
    return StoredRun(**values)
