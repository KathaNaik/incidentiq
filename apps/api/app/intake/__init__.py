"""Runtime ticket intake.

A previously unseen report arrives, is validated and persisted, is triaged by the
deterministic baseline, and is offered to the candidate incidents that are still open.
No model is called: intake is fast, free, and predictable, and investigation stays an
explicit operator decision.
"""

from app.intake.models import (
    CorrelationDecision,
    CorrelationOutcome,
    CreateTicketRequest,
    RuntimeTicket,
    TicketIntakeResult,
    TicketSource,
    TriageSummary,
)
from app.intake.rules import INTAKE_VERSION, LIVE_CORRELATION_MODE
from app.intake.service import DuplicateTicketError, IntakeError, TicketIntake

__all__ = [
    "INTAKE_VERSION",
    "LIVE_CORRELATION_MODE",
    "CorrelationDecision",
    "CorrelationOutcome",
    "CreateTicketRequest",
    "DuplicateTicketError",
    "IntakeError",
    "RuntimeTicket",
    "TicketIntake",
    "TicketIntakeResult",
    "TicketSource",
    "TriageSummary",
]
