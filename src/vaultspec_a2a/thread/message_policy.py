"""Pure message-eligibility logic — no I/O, no database.

Determines whether a follow-up message may be sent to a thread
based on its current status.
"""

from __future__ import annotations

from dataclasses import dataclass

from .dispatch_policy import FailureType
from .enums import NON_ACTIVE_STATUSES, ThreadStatus

#: Only the verb. ``MessageEligibility`` is this module's return type and is
#: read through the call rather than imported anywhere, so publishing its name
#: would advertise a surface nothing consumes.
__all__ = ["can_send_followup"]


#: The statuses whose run still owns an unfinished turn and can take a
#: continuation behind it. A follow-up admitted here does NOT take the run's
#: write authority from the turn already executing: it is reserved as a
#: waiting turn and acquires authority only when the executing turn's terminal
#: checkpoint evidence promotes it.
_ADMITTING_STATUSES: frozenset[str] = frozenset(
    {ThreadStatus.SUBMITTED.value, ThreadStatus.RUNNING.value}
)

#: The one occupied status that still refuses. A cancelling run is leaving, so
#: a turn queued behind it would wait for a promotion that can never come.
_CANCELLING_REASON = "Cannot send a follow-up message while the run is cancelling"


@dataclass(frozen=True, slots=True)
class MessageEligibility:
    """Descriptor for whether a follow-up message may be sent.

    ``allowed`` means the run can take the turn as a QUEUED continuation
    behind the one it is running, never as an immediate dispatch: no lifecycle
    state hands a follow-up the run's write authority on arrival.
    """

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
    if status in _ADMITTING_STATUSES:
        return MessageEligibility(allowed=True, reason=None)
    if status == ThreadStatus.CANCELLING.value:
        return MessageEligibility(
            allowed=False,
            reason=_CANCELLING_REASON,
            failure_type=FailureType.RUN_BUSY,
        )
    if status in NON_ACTIVE_STATUSES:
        return MessageEligibility(
            allowed=False,
            reason=f"Cannot send messages to thread in {status!r} state",
            failure_type=FailureType.TERMINAL,
        )
    # Deliberately permissive, and deliberately NOT where the admitting states
    # are served: an unclassified status reaching here is indistinguishable
    # from an admitted one, which is exactly what the closed-vocabulary test
    # catches. Classify a new lifecycle state above rather than here.
    return MessageEligibility(allowed=True, reason=None)
