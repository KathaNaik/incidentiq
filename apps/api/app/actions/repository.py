"""Action and audit storage.

**Prototype-local and in-memory.** Action state lives in the API process and is lost on
restart; the audit trail goes with it. That is a real limitation, stated here rather than
discovered later, and it is the reason this milestone does not claim a durable audit log.

What production would need, and this deliberately does not have: transactional
persistence, so a crash between "executing" and "succeeded" cannot lose the outcome; and
row-level locking or optimistic versioning, so two concurrent approvals of the same
action cannot both win. The compare-and-set below narrows that window inside one process
but does not close it across many.
"""

import threading
from collections.abc import Sequence

from app.actions.models import Action, ActionStatus, AuditEvent


class ActionNotFoundError(KeyError):
    """No action with that id."""


class ConcurrentModificationError(RuntimeError):
    """The action changed underneath a caller that expected a particular state."""


class ActionRepository:
    """In-memory action store with a compare-and-set update."""

    def __init__(self) -> None:
        self._actions: dict[str, Action] = {}
        self._audit: list[AuditEvent] = []
        # Guards the read-modify-write in `replace`. Single-process only.
        self._lock = threading.Lock()

    # --- actions ---------------------------------------------------------------------

    def add(self, action: Action) -> Action:
        with self._lock:
            if action.id in self._actions:
                raise ConcurrentModificationError(f"action {action.id} already exists")
            self._actions[action.id] = action
        return action

    def get(self, action_id: str) -> Action:
        action = self._actions.get(action_id)
        if action is None:
            raise ActionNotFoundError(action_id)
        return action

    def replace(self, action: Action, *, expected_status: ActionStatus) -> Action:
        """Writes a new version of an action, refusing if it moved in the meantime.

        This is what makes a duplicate approve or execute request safe: the second one
        finds a status it did not expect and is rejected rather than re-running.
        """
        with self._lock:
            current = self._actions.get(action.id)
            if current is None:
                raise ActionNotFoundError(action.id)
            if current.status is not expected_status:
                raise ConcurrentModificationError(
                    f"action {action.id} is {current.status.value}, expected "
                    f"{expected_status.value}"
                )
            self._actions[action.id] = action
        return action

    def for_incident(self, incident_id: str) -> tuple[Action, ...]:
        return tuple(
            sorted(
                (a for a in self._actions.values() if a.incident_id == incident_id),
                key=lambda item: (item.created_at, item.id),
            )
        )

    def all(self) -> tuple[Action, ...]:
        return tuple(sorted(self._actions.values(), key=lambda item: item.created_at))

    # --- audit -----------------------------------------------------------------------

    def record(self, event: AuditEvent) -> AuditEvent:
        """Appends an audit event. Nothing in this class ever removes or edits one."""
        with self._lock:
            self._audit.append(event)
        return event

    def audit_for_action(self, action_id: str) -> tuple[AuditEvent, ...]:
        return tuple(
            event for event in self._audit if event.action_id == action_id
        )

    def audit_for_incident(self, incident_id: str) -> tuple[AuditEvent, ...]:
        return tuple(
            event for event in self._audit if event.incident_id == incident_id
        )

    def reset(self) -> None:
        """Discards all actions and audit events.

        Only the demo reset calls this. Audit events are append-only everywhere else —
        `record` never removes or edits one — and that property is the point of the audit
        trail, so the one method that breaks it is named plainly rather than hidden
        behind a general-purpose delete.
        """
        with self._lock:
            self._actions.clear()
            self._audit.clear()

    def reset_workflow_state(self, investigation_store=None) -> int:
        """Demo affordance. Mirrors the durable store's signature.

        The in-memory investigation store used by the fast tests is a plain dict, so
        clearing it is best-effort — the durable path is what the demo actually runs.
        """
        self.reset()
        runs = getattr(investigation_store, "_runs", None)
        removed = len(runs) if runs is not None else 0
        if runs is not None:
            runs.clear()
        return removed

    def audit(self) -> Sequence[AuditEvent]:
        return tuple(self._audit)
