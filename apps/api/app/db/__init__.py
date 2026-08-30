"""Durable operational state.

PostgreSQL holds what the product is *stateful* about: investigation runs and the exact
evidence each one saw, actions and the policy decision that gated them, approvals,
execution results, audit events, and the historical corpus with its vectors.

What deliberately stays on disk:

- **Northstar fixtures.** Authored demo input, versioned with the code.
- **Evaluation artifacts.** A benchmark result is a record of a measurement that already
  happened. Putting it in a mutable database would invite it to change.
- **The embedding cache.** A derived artifact keyed by model identity, and a cache that
  survives a database reset is exactly what makes re-import cheap.
"""

from app.db.engine import (
    DatabaseNotConfiguredError,
    dispose_engine,
    get_engine,
    session_scope,
    sessionmaker_for,
)
from app.db.models import (
    Base,
    HistoricalIncidentRow,
    InvestigationRunRow,
    ActionRow,
    ApprovalRow,
    AuditEventRow,
    ExecutionResultRow,
)

__all__ = [
    "ActionRow",
    "ApprovalRow",
    "AuditEventRow",
    "Base",
    "DatabaseNotConfiguredError",
    "ExecutionResultRow",
    "HistoricalIncidentRow",
    "InvestigationRunRow",
    "dispose_engine",
    "get_engine",
    "session_scope",
    "sessionmaker_for",
]
