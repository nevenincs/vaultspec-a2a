"""Pure cancel-eligibility logic — no I/O, no database.

Determines whether a cancel operation is permitted for a thread
based on its current status.
"""

from __future__ import annotations

from dataclasses import dataclass

from .enums import NON_ACTIVE_STATUSES, ThreadStatus


@dataclass(frozen=True, slots=True)
class CancelEligibility:
    """Descriptor for whether a thread may be cancelled."""

    allowed: bool
    already_cancelled: bool
    reason: str | None


def can_cancel(status: str) -> CancelEligibility:
    """Check whether a thread in the given status may be cancelled."""
    if status in NON_ACTIVE_STATUSES:
        return CancelEligibility(
            allowed=False,
            already_cancelled=status == ThreadStatus.CANCELLED.value,
            reason=f"Cannot cancel thread in {status!r} state",
        )
    return CancelEligibility(allowed=True, already_cancelled=False, reason=None)
