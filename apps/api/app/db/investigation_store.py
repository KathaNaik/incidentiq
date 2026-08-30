"""Durable investigation runs.

An investigation used to be a function call whose result lived as long as the HTTP
response. It is now a record: one exact invocation of one investigator against one exact
evidence snapshot, kept forever.

Three properties matter and each is enforced here rather than hoped for.

**Immutability.** Nothing updates a run that has reached `succeeded` or `failed`. A
re-investigation inserts a new row, so an action approved last week still points at the
evidence and the answer that actually justified it.

**The snapshot is the evidence.** Stored as JSONB exactly as the model was shown it, and
never reconstructed from current fixtures. If a deployment record changes tomorrow, the
run still answers "what did investigator-v2 see when it recommended this rollback".

**One active run per incident.** Enforced with a partial unique index rather than a
check-then-insert, so two simultaneous requests cannot both decide they are the first.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError

from app.db.engine import get_engine, sessionmaker_for
from app.db.models import InvestigationRunRow
from app.investigation.rules import CURRENT_EVIDENCE_SCHEMA
from app.temporal.rules import TEMPORAL_CONFIG_VERSION
from app.investigation.models import (
    EvidenceItem,
    InvestigationOutput,
    InvestigationResult,
    InvestigationRun,
)


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


ACTIVE = (RunStatus.PENDING, RunStatus.RUNNING)


class ActiveRunExistsError(RuntimeError):
    """An investigation is already in flight for this incident.

    Carries the existing run so the caller can return it instead of starting a second
    model call — a duplicate click should show what is already happening, not spend
    another eleven seconds and another set of tokens reaching a slightly different answer.
    """

    def __init__(self, run: "StoredRun") -> None:
        super().__init__(f"investigation {run.id} is already {run.status} for {run.incident_id}")
        self.run = run


@dataclass(frozen=True)
class StoredRun:
    """One persisted investigation, as the application reads it back."""

    id: str
    incident_id: str
    investigator_version: str
    prompt_version: str
    provider: str
    model: str
    status: str
    evidence_schema_version: str
    temporal_config_version: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    evidence: tuple[EvidenceItem, ...]
    output: InvestigationOutput | None
    latency_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    reasoning_tokens: int | None
    failure_type: str | None
    failure_message: str | None

    @property
    def succeeded(self) -> bool:
        return self.status == RunStatus.SUCCEEDED

    def as_result(self) -> InvestigationResult:
        """The shape the rest of the application already speaks.

        Rebuilt from the snapshot, never from current fixtures — that is the whole point
        of storing it.
        """
        if self.output is None:
            raise ValueError(f"run {self.id} has no result to render")
        return InvestigationResult(
            incident_id=self.incident_id,
            version=self.investigator_version,
            output=self.output,
            evidence=self.evidence,
            run=InvestigationRun(
                model=self.model,
                prompt_version=self.prompt_version,
                evidence_ids=tuple(item.id for item in self.evidence),
                latency_ms=self.latency_ms or 0,
                input_tokens=self.input_tokens,
                output_tokens=self.output_tokens,
                reasoning_tokens=self.reasoning_tokens,
                started_at=self.started_at or self.created_at,
            ),
        )


def new_run_id() -> str:
    return f"inv-{uuid.uuid4().hex[:12]}"


def _aware(value):
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


class InvestigationRunStore:
    def __init__(self, engine: Engine | None = None) -> None:
        self._engine = engine or get_engine()
        self._session = sessionmaker_for(self._engine)

    def begin(
        self,
        *,
        incident_id: str,
        investigator_version: str,
        prompt_version: str,
        provider: str,
        model: str,
        evidence: Sequence[EvidenceItem],
        evidence_schema_version: str = CURRENT_EVIDENCE_SCHEMA,
        temporal_config_version: str | None = TEMPORAL_CONFIG_VERSION,
    ) -> StoredRun:
        """Claims the incident and records the evidence, before the model is called.

        The snapshot is written *first* on purpose: if the provider then fails, the run
        still records exactly what would have been sent, which is what makes a failed run
        worth keeping.
        """
        with self._session.begin() as session:
            existing = session.scalars(
                select(InvestigationRunRow)
                .where(
                    InvestigationRunRow.incident_id == incident_id,
                    InvestigationRunRow.status.in_([s.value for s in ACTIVE]),
                )
                .with_for_update()
            ).first()
            if existing is not None:
                raise ActiveRunExistsError(_to_stored(existing))

            row = InvestigationRunRow(
                id=new_run_id(),
                incident_id=incident_id,
                investigator_version=investigator_version,
                prompt_version=prompt_version,
                provider=provider,
                model=model,
                status=RunStatus.RUNNING.value,
                started_at=datetime.now(UTC),
                evidence_schema_version=evidence_schema_version,
                temporal_config_version=temporal_config_version,
                evidence_snapshot=[
                    item.model_dump(mode="json") for item in evidence
                ],
            )
            try:
                session.add(row)
                session.flush()
            except IntegrityError as error:
                # The partial unique index caught a race the SELECT ... FOR UPDATE above
                # could not, because the competing transaction had not committed yet.
                session.rollback()
                raise ActiveRunExistsError(self.active(incident_id)) from error  # type: ignore[arg-type]
            return _to_stored(row)

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
        with self._session.begin() as session:
            row = self._active_row(session, run_id)
            row.status = RunStatus.SUCCEEDED.value
            row.completed_at = datetime.now(UTC)
            row.structured_result = output.model_dump(mode="json")
            row.model = model
            row.latency_ms = latency_ms
            row.input_tokens = input_tokens
            row.output_tokens = output_tokens
            row.reasoning_tokens = reasoning_tokens
            session.flush()
            return _to_stored(row)

    def fail(self, run_id: str, *, failure_type: str, message: str) -> StoredRun:
        """Records a failure and keeps the run.

        A failed re-investigation must not erase the previous successful one, and the
        failure itself is worth keeping — "the provider was down at 14:02" is an
        operational fact.
        """
        with self._session.begin() as session:
            row = self._active_row(session, run_id)
            row.status = RunStatus.FAILED.value
            row.completed_at = datetime.now(UTC)
            row.failure_type = failure_type
            row.failure_message = message[:2000]
            session.flush()
            return _to_stored(row)

    def _active_row(self, session, run_id: str) -> InvestigationRunRow:
        row = session.get(InvestigationRunRow, run_id, with_for_update=True)
        if row is None:
            raise KeyError(f"unknown investigation run: {run_id}")
        if row.status not in (RunStatus.PENDING.value, RunStatus.RUNNING.value):
            raise ValueError(
                f"investigation {run_id} is {row.status} and is immutable; "
                "a new investigation creates a new run"
            )
        return row

    # --- reads --------------------------------------------------------------------

    def get(self, run_id: str) -> StoredRun | None:
        with self._session() as session:
            row = session.get(InvestigationRunRow, run_id)
            return _to_stored(row) if row is not None else None

    def active(self, incident_id: str) -> StoredRun | None:
        return self._first(
            incident_id, statuses=[s.value for s in ACTIVE], newest_first=True
        )

    def latest_successful(self, incident_id: str) -> StoredRun | None:
        return self._first(
            incident_id, statuses=[RunStatus.SUCCEEDED.value], newest_first=True
        )

    def latest(self, incident_id: str) -> StoredRun | None:
        return self._first(incident_id, statuses=None, newest_first=True)

    def history(self, incident_id: str, *, limit: int = 20) -> tuple[StoredRun, ...]:
        with self._session() as session:
            rows = session.scalars(
                select(InvestigationRunRow)
                .where(InvestigationRunRow.incident_id == incident_id)
                .order_by(
                    InvestigationRunRow.created_at.desc(),
                    InvestigationRunRow.id.desc(),
                )
                .limit(limit)
            ).all()
            return tuple(_to_stored(row) for row in rows)

    def _first(self, incident_id: str, *, statuses, newest_first: bool):
        with self._session() as session:
            statement = select(InvestigationRunRow).where(
                InvestigationRunRow.incident_id == incident_id
            )
            if statuses is not None:
                statement = statement.where(InvestigationRunRow.status.in_(statuses))
            order = (
                (InvestigationRunRow.created_at.desc(), InvestigationRunRow.id.desc())
                if newest_first
                else (InvestigationRunRow.created_at, InvestigationRunRow.id)
            )
            row = session.scalars(statement.order_by(*order).limit(1)).first()
            return _to_stored(row) if row is not None else None


def _to_stored(row: InvestigationRunRow) -> StoredRun:
    return StoredRun(
        id=row.id,
        incident_id=row.incident_id,
        investigator_version=row.investigator_version,
        prompt_version=row.prompt_version,
        provider=row.provider,
        model=row.model,
        status=row.status,
        evidence_schema_version=row.evidence_schema_version,
        temporal_config_version=row.temporal_config_version,
        created_at=_aware(row.created_at),
        started_at=_aware(row.started_at),
        completed_at=_aware(row.completed_at),
        evidence=tuple(
            EvidenceItem.model_validate(item) for item in (row.evidence_snapshot or [])
        ),
        output=(
            InvestigationOutput.model_validate(row.structured_result)
            if row.structured_result is not None
            else None
        ),
        latency_ms=row.latency_ms,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        reasoning_tokens=row.reasoning_tokens,
        failure_type=row.failure_type,
        failure_message=row.failure_message,
    )
