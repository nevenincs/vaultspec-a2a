"""Pure cancel-eligibility logic — no I/O, no database.

Determines whether a cancel operation is permitted for a thread
based on its current status.
"""

from __future__ import annotations

from dataclasses import dataclass

from .enums import ThreadStatus
from .transitions import VALID_TRANSITIONS

__all__ = [
    "CancelEligibility",
    "can_cancel",
]

# Read off the lifecycle rather than restated beside it: a cancel is admitted
# exactly where a run can still enter CANCELLING, and on a run already there,
# whose repeat cancel replays the one in flight.
_CANCELLABLE_STATUS_VALUES: frozenset[str] = frozenset(
    {ThreadStatus.CANCELLING.value}
    | {
        status.value
        for status, targets in VALID_TRANSITIONS.items()
        if ThreadStatus.CANCELLING in targets
    }
)


@dataclass(frozen=True, slots=True)
class CancelEligibility:
    """Descriptor for whether a thread may be cancelled."""

    allowed: bool
    already_cancelled: bool
    reason: str | None


def can_cancel(status: str) -> CancelEligibility:
    """Check whether a thread in the given status may be cancelled."""
    if status not in _CANCELLABLE_STATUS_VALUES:
        return CancelEligibility(
            allowed=False,
            already_cancelled=status == ThreadStatus.CANCELLED.value,
            reason=f"Cannot cancel thread in {status!r} state",
        )
    return CancelEligibility(allowed=True, already_cancelled=False, reason=None)
