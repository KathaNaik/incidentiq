"""PostgreSQL-backed action, approval, execution and audit state.

Implements the same interface as the in-memory `ActionRepository`, which is why
`app.actions.service` is untouched by this milestone: `approve_action` and
`execute_action` were already written against `get` / `replace(expected_status=...)` /
`record`, and derived idempotency from *persisted status* rather than a flag on an
object. Moving the store to PostgreSQL therefore makes idempotency survive a restart
without changing a line of the workflow logic.

Each method opens its own transaction. That is the unit of work the workflow actually
has — a state transition, then the audit event that describes it — and it keeps the
repository usable from a plain script as easily as from a request.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC

from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError

from app.actions.models import (
    Action,
    ActionPolicyDecision,
    ActionStatus,
    ActionTarget,
    ActionType,
    ActorType,
    Approval,
    AuditEvent,
    AuditEventType,
    ExecutionResult,
)
from app.actions.repository import ActionNotFoundError, ConcurrentModificationError
from app.db.engine import get_engine, sessionmaker_for
from app.db.models import (
    ActionRow,
    ApprovalRow,
    AuditEventRow,
    ExecutionResultRow,
)
from app.investigation.models import RiskLevel


def _aware(value):
    """PostgreSQL returns aware datetimes; SQLite variants may not. Normalise to UTC."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


class SqlActionRepository:
    """Durable action store. Same contract as the in-memory one."""

    def __init__(self, engine: Engine | None = None) -> None:
        self._engine = engine or get_engine()
        self._session = sessionmaker_for(self._engine)

    # --- actions ------------------------------------------------------------------

    def add(self, action: Action) -> Action:
        with self._session.begin() as session:
            if session.get(ActionRow, action.id) is not None:
                raise ValueError(f"action already exists: {action.id}")
            session.add(_to_row(action))
        return action

    def get(self, action_id: str) -> Action:
        with self._session() as session:
            row = session.get(ActionRow, action_id)
            if row is None:
                raise ActionNotFoundError(f"unknown action: {action_id}")
            return _to_domain(row)

    def replace(self, action: Action, *, expected_status: ActionStatus) -> Action:
        """Compare-and-set on status, inside one transaction.

        `SELECT ... FOR UPDATE` rather than a read-then-write: two requests racing on the
        same action must not both observe `approved` and both proceed to execute. The row
        lock makes the loser wait and then fail its status check, which is the outcome the
        in-memory version achieved with a mutex and this one needs to achieve across
        processes.
        """
        with self._session.begin() as session:
            row = session.get(ActionRow, action.id, with_for_update=True)
            if row is None:
                raise ActionNotFoundError(f"unknown action: {action.id}")
            if row.status != expected_status.value:
                raise ConcurrentModificationError(
                    f"action {action.id} is {row.status}, expected "
                    f"{expected_status.value}; it was changed by someone else"
                )
            _apply(row, action, session)
        return self.get(action.id)

    def for_incident(self, incident_id: str) -> tuple[Action, ...]:
        with self._session() as session:
            rows = session.scalars(
                select(ActionRow)
                .where(ActionRow.incident_id == incident_id)
                .order_by(ActionRow.created_at, ActionRow.id)
            ).all()
            return tuple(_to_domain(row) for row in rows)

    def all(self) -> tuple[Action, ...]:
        with self._session() as session:
            rows = session.scalars(
                select(ActionRow).order_by(ActionRow.created_at, ActionRow.id)
            ).all()
            return tuple(_to_domain(row) for row in rows)

    # --- audit --------------------------------------------------------------------

    def record(self, event: AuditEvent) -> AuditEvent:
        """Appends an audit event. Nothing in this class ever removes or edits one."""
        with self._session.begin() as session:
            session.add(
                AuditEventRow(
                    id=event.id,
                    incident_id=event.incident_id,
                    action_id=event.action_id,
                    investigation_run_id=event.investigation_run_id,
                    event_type=event.event_type.value,
                    actor_type=event.actor_type.value,
                    actor_id=event.actor_id,
                    occurred_at=event.occurred_at,
                    details=dict(event.details),
                )
            )
        return event

    # --- demo only ------------------------------------------------------------------

    def reset_workflow_state(self, investigation_store=None) -> int:
        """Deletes all workflow state. Demo affordance only.

        The single operation that breaks the audit trail's append-only property, so it is
        named for what it is rather than hidden behind a generic delete.

        Deleted: investigation runs and their evidence snapshots, actions, approvals,
        execution results, audit events. Approvals and executions go with their action by
        cascade; runs are deleted last because actions reference them.

        Untouched: `historical_incidents` and its vectors, and everything on disk.

        Returns the number of investigation runs removed.
        """
        from sqlalchemy import delete

        from app.db.models import InvestigationRunRow

        with self._session.begin() as session:
            session.execute(delete(AuditEventRow))
            session.execute(delete(ExecutionResultRow))
            session.execute(delete(ApprovalRow))
            session.execute(delete(ActionRow))
            removed = session.execute(delete(InvestigationRunRow)).rowcount
        return int(removed or 0)

    def audit_for_action(self, action_id: str) -> tuple[AuditEvent, ...]:
        return self._audit(AuditEventRow.action_id == action_id)

    def audit_for_incident(self, incident_id: str) -> tuple[AuditEvent, ...]:
        return self._audit(AuditEventRow.incident_id == incident_id)

    def audit(self) -> Sequence[AuditEvent]:
        return self._audit(None)

    def _audit(self, where) -> tuple[AuditEvent, ...]:
        # (occurred_at, sequence): timestamps alone are not a reliable tie-break, and an
        # audit trail that reorders between two reads is not an audit trail.
        statement = select(AuditEventRow).order_by(
            AuditEventRow.occurred_at, AuditEventRow.sequence
        )
        if where is not None:
            statement = statement.where(where)
        with self._session() as session:
            return tuple(
                AuditEvent(
                    id=row.id,
                    incident_id=row.incident_id,
                    action_id=row.action_id,
                    investigation_run_id=row.investigation_run_id,
                    event_type=AuditEventType(row.event_type),
                    actor_type=ActorType(row.actor_type),
                    actor_id=row.actor_id,
                    occurred_at=_aware(row.occurred_at),
                    details=dict(row.details or {}),
                )
                for row in session.scalars(statement).all()
            )


def _to_row(action: Action) -> ActionRow:
    policy = action.policy
    return ActionRow(
        id=action.id,
        incident_id=action.incident_id,
        investigation_run_id=action.investigation_run_id,
        action_type=action.action_type.value,
        status=action.status.value,
        target=action.target.model_dump(mode="json"),
        model_stated_risk=None,
        effective_risk=action.risk.value,
        policy_version=_policy_version(),
        policy_decision=policy.model_dump(mode="json"),
        recommendation_summary=action.recommendation_summary,
        recommendation_evidence_ids=list(action.recommendation_evidence_ids),
        validated_evidence_ids=list(policy.validated_evidence_ids),
        created_at=action.created_at,
    )


def _apply(row: ActionRow, action: Action, session) -> None:
    """Writes a changed action onto its row, including the child records.

    Approval and execution are separate rows with unique constraints on `action_id`, so
    a second approval or a second execution result is refused by the database rather than
    by the caller remembering not to write one.
    """
    row.status = action.status.value
    row.target = action.target.model_dump(mode="json")
    row.effective_risk = action.risk.value
    row.policy_decision = action.policy.model_dump(mode="json")
    row.validated_evidence_ids = list(action.policy.validated_evidence_ids)
    if action.investigation_run_id is not None:
        row.investigation_run_id = action.investigation_run_id

    if action.approval is not None and row.approval is None:
        session.add(
            ApprovalRow(
                id=action.approval.id,
                action_id=action.id,
                approved=action.approval.approved,
                actor_type=action.approval.actor_type.value,
                actor_id=action.approval.actor_id,
                decided_at=action.approval.decided_at,
                reason=action.approval.reason,
            )
        )

    if action.execution is not None and row.execution is None:
        try:
            session.add(
                ExecutionResultRow(
                    id=f"exe-{uuid.uuid4().hex[:12]}",
                    action_id=action.id,
                    simulated=action.execution.simulated,
                    succeeded=action.execution.succeeded,
                    summary=action.execution.summary,
                    details=list(action.execution.details),
                    executed_at=action.execution.executed_at,
                )
            )
            session.flush()
        except IntegrityError as error:  # pragma: no cover - guarded by status checks
            raise ConcurrentModificationError(
                f"action {action.id} already has an execution result"
            ) from error


def _to_domain(row: ActionRow) -> Action:
    return Action(
        id=row.id,
        incident_id=row.incident_id,
        investigation_run_id=row.investigation_run_id,
        action_type=ActionType(row.action_type),
        target=ActionTarget.model_validate(row.target),
        status=ActionStatus(row.status),
        risk=RiskLevel(row.effective_risk),
        created_at=_aware(row.created_at),
        recommendation_summary=row.recommendation_summary,
        recommendation_evidence_ids=tuple(row.recommendation_evidence_ids or ()),
        policy=ActionPolicyDecision.model_validate(row.policy_decision),
        approval=(
            Approval(
                id=row.approval.id,
                action_id=row.approval.action_id,
                approved=row.approval.approved,
                actor_type=ActorType(row.approval.actor_type),
                actor_id=row.approval.actor_id,
                decided_at=_aware(row.approval.decided_at),
                reason=row.approval.reason,
            )
            if row.approval is not None
            else None
        ),
        execution=(
            ExecutionResult(
                simulated=row.execution.simulated,
                succeeded=row.execution.succeeded,
                summary=row.execution.summary,
                details=tuple(row.execution.details or ()),
                executed_at=_aware(row.execution.executed_at),
            )
            if row.execution is not None
            else None
        ),
    )


def _policy_version() -> str:
    from app.actions.rules import ACTIVE_ACTIONS_VERSION

    return ACTIVE_ACTIONS_VERSION
