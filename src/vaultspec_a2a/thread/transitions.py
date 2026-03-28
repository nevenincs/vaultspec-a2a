"""Thread lifecycle state machine — valid status transitions.

Pure Layer 1 module: imports only from ``thread.enums``.
"""

from __future__ import annotations

from .enums import InvalidTransitionError, ThreadStatus

_VALID_TRANSITIONS: dict[ThreadStatus, frozenset[ThreadStatus]] = {
    ThreadStatus.SUBMITTED: frozenset(
        {
            ThreadStatus.RUNNING,
            ThreadStatus.INPUT_REQUIRED,
            ThreadStatus.CANCELLING,
            ThreadStatus.CANCELLED,
            ThreadStatus.FAILED,
            ThreadStatus.RECONCILING,
            ThreadStatus.REPAIR_NEEDED,
        }
    ),
    ThreadStatus.RUNNING: frozenset(
        {
            ThreadStatus.INPUT_REQUIRED,
            ThreadStatus.CANCELLING,
            ThreadStatus.CANCELLED,
            ThreadStatus.COMPLETED,
            ThreadStatus.FAILED,
            ThreadStatus.RECONCILING,
            ThreadStatus.REPAIR_NEEDED,
        }
    ),
    ThreadStatus.INPUT_REQUIRED: frozenset(
        {
            ThreadStatus.RUNNING,
            ThreadStatus.CANCELLING,
            ThreadStatus.CANCELLED,
            ThreadStatus.COMPLETED,
            ThreadStatus.FAILED,
            ThreadStatus.RECONCILING,
            ThreadStatus.REPAIR_NEEDED,
        }
    ),
    ThreadStatus.CANCELLING: frozenset(
        {
            ThreadStatus.CANCELLED,
            ThreadStatus.FAILED,
            ThreadStatus.RECONCILING,
            ThreadStatus.REPAIR_NEEDED,
        }
    ),
    ThreadStatus.RECONCILING: frozenset(
        {
            ThreadStatus.SUBMITTED,
            ThreadStatus.RUNNING,
            ThreadStatus.INPUT_REQUIRED,
            ThreadStatus.CANCELLING,
            ThreadStatus.CANCELLED,
            ThreadStatus.COMPLETED,
            ThreadStatus.FAILED,
            ThreadStatus.REPAIR_NEEDED,
        }
    ),
    ThreadStatus.REPAIR_NEEDED: frozenset(
        {
            ThreadStatus.RECONCILING,
            ThreadStatus.RUNNING,
            ThreadStatus.INPUT_REQUIRED,
            ThreadStatus.CANCELLING,
            ThreadStatus.CANCELLED,
            ThreadStatus.FAILED,
        }
    ),
    ThreadStatus.COMPLETED: frozenset({ThreadStatus.ARCHIVED}),
    ThreadStatus.FAILED: frozenset({ThreadStatus.ARCHIVED}),
    ThreadStatus.CANCELLED: frozenset({ThreadStatus.ARCHIVED}),
    ThreadStatus.ARCHIVED: frozenset(),
}


def validate_transition(
    current: ThreadStatus,
    target: ThreadStatus,
    *,
    thread_id: str = "",
) -> None:
    """Raise ``InvalidTransitionError`` if *current* → *target* is not allowed."""
    if current == target:
        return
    allowed = _VALID_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise InvalidTransitionError(
            f"Cannot transition thread {thread_id} from "
            f"{current.value!r} to {target.value!r}"
        )
