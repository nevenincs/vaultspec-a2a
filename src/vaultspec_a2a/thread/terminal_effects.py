"""Pure terminal-event decision logic — no I/O, no database.

Given a terminal status and the presence of a cancel action, computes
the repair state, last applied action, and cancel finalization flag.
"""

from __future__ import annotations

from dataclasses import dataclass

from .enums import ControlActionType, RepairStatus, ThreadStatus


@dataclass(frozen=True, slots=True)
class TerminalEffects:
    """Descriptor for DB mutations after a thread-terminal event."""

    repair_status: RepairStatus
    repair_reason: None
    last_applied_action: ControlActionType | None
    should_finalize_cancel: bool


def compute_terminal_effects(
    terminal_status: ThreadStatus,
    has_cancel_action: bool,
) -> TerminalEffects:
    """Compute the repair-state effects of a terminal event.

    Args:
        terminal_status: The terminal status the thread reached.
        has_cancel_action: Whether a durable cancel action exists for the thread.

    Returns:
        A frozen descriptor the caller translates into DB writes.
    """
    is_cancelled = terminal_status == ThreadStatus.CANCELLED
    return TerminalEffects(
        repair_status=RepairStatus.HEALTHY,
        repair_reason=None,
        last_applied_action=(ControlActionType.CANCEL if is_cancelled else None),
        should_finalize_cancel=has_cancel_action and is_cancelled,
    )
