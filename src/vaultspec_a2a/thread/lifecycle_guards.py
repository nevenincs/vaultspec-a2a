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
    if status == ThreadStatus.RUNNING.value:
        return DeleteEligibility(
            allowed=False,
            reason="Cannot delete a RUNNING thread — cancel it first",
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
