"""Pure message-eligibility logic — no I/O, no database.

Determines whether a follow-up message may be sent to a thread
based on its current status.
"""

from __future__ import annotations

from dataclasses import dataclass

from .enums import NON_ACTIVE_STATUSES, ThreadStatus


@dataclass(frozen=True, slots=True)
class MessageEligibility:
    """Descriptor for whether a follow-up message may be sent."""

    allowed: bool
    reason: str | None


def can_send_followup(status: str) -> MessageEligibility:
    """Check whether a thread in the given status may receive a message."""
    if status == ThreadStatus.INPUT_REQUIRED.value:
        return MessageEligibility(
            allowed=False,
            reason=(
                "Cannot send a follow-up message while the thread is paused for input"
            ),
        )
    if status in {
        ThreadStatus.REPAIR_NEEDED.value,
        ThreadStatus.RECONCILING.value,
    }:
        return MessageEligibility(
            allowed=False,
            reason=f"Cannot send messages while thread is in {status!r} repair state",
        )
    if status in NON_ACTIVE_STATUSES:
        return MessageEligibility(
            allowed=False,
            reason=f"Cannot send messages to thread in {status!r} state",
        )
    return MessageEligibility(allowed=True, reason=None)
