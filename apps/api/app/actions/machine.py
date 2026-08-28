"""Action state transitions.

One function, one table. Every state change goes through here, so an illegal transition
is impossible rather than merely unreachable through the UI — a hidden button is not a
control.
"""

from app.actions.models import ActionStatus
from app.actions.rules import LEGAL_TRANSITIONS


class InvalidTransitionError(RuntimeError):
    """An action was asked to move somewhere the state graph does not allow."""


def assert_transition(current: ActionStatus, target: ActionStatus) -> None:
    allowed = LEGAL_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise InvalidTransitionError(
            f"cannot move an action from {current.value} to {target.value}"
            + (
                f"; from {current.value} it may only become "
                f"{', '.join(sorted(state.value for state in allowed))}"
                if allowed
                else f"; {current.value} is terminal"
            )
        )


def is_terminal(status: ActionStatus) -> bool:
    return not LEGAL_TRANSITIONS.get(status, frozenset())
