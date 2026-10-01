"""Pure message-eligibility logic — no I/O, no database.

Determines whether a follow-up message may be sent to a thread
based on its current status.
"""

from __future__ import annotations

from dataclasses import dataclass

from .dispatch_policy import FailureType
from .enums import NON_ACTIVE_STATUSES, ThreadStatus

__all__ = [
    "MessageEligibility",
    "can_send_followup",
]


#: The statuses whose run still owns an unfinished turn, and the account each
#: gives of itself. A follow-up admitted here takes the run's write authority
#: from the turn that is still executing, so that turn's own completion and
#: failure are then refused as evidence of a superseded action and the run
#: quarantines instead of ending. Occupancy is therefore decided before anything
#: is reserved, which is what keeps the refusal free of side effects.
_BUSY_STATUS_REASONS: dict[str, str] = {
    ThreadStatus.SUBMITTED.value: (
        "Cannot send a follow-up message while the run's first turn is still "
        "being dispatched"
    ),
    ThreadStatus.RUNNING.value: (
        "Cannot send a follow-up message while the run's current turn is still "
        "in flight"
    ),
    ThreadStatus.CANCELLING.value: (
        "Cannot send a follow-up message while the run is cancelling"
    ),
}


@dataclass(frozen=True, slots=True)
class MessageEligibility:
    """Descriptor for whether a follow-up message may be sent."""

    allowed: bool
    reason: str | None
    failure_type: FailureType | None = None


def can_send_followup(status: str) -> MessageEligibility:
    """Check whether a thread in the given status may receive a message."""
    if status == ThreadStatus.INPUT_REQUIRED.value:
        return MessageEligibility(
            allowed=False,
            reason=(
                "Cannot send a follow-up message while the thread is paused for input"
            ),
            failure_type=FailureType.INPUT_REQUIRED,
        )
    if status in {
        ThreadStatus.REPAIR_NEEDED.value,
        ThreadStatus.RECONCILING.value,
    }:
        return MessageEligibility(
            allowed=False,
            reason=f"Cannot send messages while thread is in {status!r} repair state",
            failure_type=FailureType.TERMINAL,
        )
    busy_reason = _BUSY_STATUS_REASONS.get(status)
    if busy_reason is not None:
        return MessageEligibility(
            allowed=False,
            reason=busy_reason,
            failure_type=FailureType.RUN_BUSY,
        )
    if status in NON_ACTIVE_STATUSES:
        return MessageEligibility(
            allowed=False,
            reason=f"Cannot send messages to thread in {status!r} state",
            failure_type=FailureType.TERMINAL,
        )
    return MessageEligibility(allowed=True, reason=None)
