"""Pure lifecycle-guard predicates — no I/O, no database.

Determines whether delete and archive operations are permitted for a
given thread status.
"""

from __future__ import annotations

from dataclasses import dataclass

from .enums import TERMINAL_STATUSES, ThreadStatus


@dataclass(frozen=True, slots=True)
class DeleteEligibility:
    """Descriptor for whether a thread may be deleted."""

    allowed: bool
    reason: str | None


@dataclass(frozen=True, slots=True)
class ArchiveEligibility:
    """Descriptor for whether a thread may be archived."""

    allowed: bool
    already_archived: bool
    reason: str | None


def can_delete(status: str) -> DeleteEligibility:
    """Check whether a thread in the given status may be hard-deleted."""
    terminal_or_archived = {
        *(thread_status.value for thread_status in TERMINAL_STATUSES),
        ThreadStatus.ARCHIVED.value,
    }
    if status not in terminal_or_archived:
        return DeleteEligibility(
            allowed=False,
            reason=f"Cannot delete thread in {status!r} state",
        )
    return DeleteEligibility(allowed=True, reason=None)


def can_archive(status: str) -> ArchiveEligibility:
    """Check whether a thread in the given status may be archived."""
    if status == ThreadStatus.ARCHIVED:
        return ArchiveEligibility(
            allowed=True,
            already_archived=True,
            reason=None,
        )
    if status not in TERMINAL_STATUSES:
        return ArchiveEligibility(
            allowed=False,
            already_archived=False,
            reason=f"Cannot archive thread in {status!r} state",
        )
    return ArchiveEligibility(
        allowed=True,
        already_archived=False,
        reason=None,
    )
