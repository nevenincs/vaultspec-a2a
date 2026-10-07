"""Pure repair-state policy — no I/O, no database.

The single authority for the repair state every control-plane event moves a
run into: each step of a control action, a run's proven terminal, and the
failures that hand a run to reconciliation or to an operator. A run's
execution readiness is not part of this policy because it is never decided on
its own: it is the repair status, read as whether the run is fit to resume.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from .enums import ControlActionType, RepairStatus, ThreadStatus

__all__ = [
    "ACTION_QUARANTINED_TRANSITION",
    "DISPATCH_FAILED_TRANSITION",
    "RECONCILIATION_REQUIRED_TRANSITION",
    "RepairPhase",
    "RepairTransition",
    "repair_state_for_action",
    "terminal_repair_transition",
]


class RepairPhase(StrEnum):
    """Which step of a control action a transition records."""

    REQUESTED = "requested"
    APPLIED = "applied"


@dataclass(frozen=True, slots=True)
class RepairTransition:
    """The repair state one control-plane event moves a run into.

    *action* is the control action the event records, as the run's last
    requested or last applied action according to *phase*; an event that is
    not a step of a control action records neither. *reason* is the account
    the event leaves when its caller has none of its own.
    """

    repair_status: RepairStatus
    action: ControlActionType | None = None
    phase: RepairPhase | None = None
    reason: str | None = None


_ACTION_TRANSITIONS: Final[tuple[RepairTransition, ...]] = (
    RepairTransition(
        repair_status=RepairStatus.HEALTHY,
        action=ControlActionType.INGEST,
        phase=RepairPhase.REQUESTED,
    ),
    RepairTransition(
        repair_status=RepairStatus.HEALTHY,
        action=ControlActionType.INGEST,
        phase=RepairPhase.APPLIED,
    ),
    RepairTransition(
        repair_status=RepairStatus.PAUSED_RESUMABLE,
        action=ControlActionType.PERMISSION_REQUEST_CREATED,
        phase=RepairPhase.APPLIED,
        reason="Worker reported a pending permission request",
    ),
    RepairTransition(
        repair_status=RepairStatus.PAUSED_RESUMABLE,
        action=ControlActionType.PERMISSION_RESPONSE_SUBMITTED,
        phase=RepairPhase.REQUESTED,
    ),
    RepairTransition(
        repair_status=RepairStatus.HEALTHY,
        action=ControlActionType.PERMISSION_RESPONSE_APPLIED,
        phase=RepairPhase.APPLIED,
    ),
    RepairTransition(
        repair_status=RepairStatus.HEALTHY,
        action=ControlActionType.MESSAGE_FOLLOWUP_REQUESTED,
        phase=RepairPhase.REQUESTED,
    ),
    RepairTransition(
        repair_status=RepairStatus.HEALTHY,
        action=ControlActionType.MESSAGE_FOLLOWUP_APPLIED,
        phase=RepairPhase.APPLIED,
    ),
    RepairTransition(
        repair_status=RepairStatus.CANCEL_PENDING,
        action=ControlActionType.CANCEL,
        phase=RepairPhase.REQUESTED,
    ),
    # A settled cancellation: the one terminal recorded as an applied action.
    RepairTransition(
        repair_status=RepairStatus.HEALTHY,
        action=ControlActionType.CANCEL,
        phase=RepairPhase.APPLIED,
    ),
)

_REPAIR_MAP: Final = {
    (transition.action, transition.phase): transition
    for transition in _ACTION_TRANSITIONS
}

#: A completed or failed turn settles repair back to healthy and leaves the
#: run's action record as it stood.
_RUN_SETTLED_TRANSITION: Final = RepairTransition(repair_status=RepairStatus.HEALTHY)

#: Worker dispatch failed outright, so nothing can move the run without an
#: operator.
DISPATCH_FAILED_TRANSITION: Final = RepairTransition(
    repair_status=RepairStatus.OPERATOR_INTERVENTION_REQUIRED,
    reason="Worker dispatch failed",
)

#: An accepted action that can never be applied was quarantined; the run waits
#: for an operator rather than for a redrive that cannot succeed.
ACTION_QUARANTINED_TRANSITION: Final = RepairTransition(
    repair_status=RepairStatus.OPERATOR_INTERVENTION_REQUIRED,
)

#: The checkpoint does not prove the run's current action, so the run is held
#: for reconciliation against it.
RECONCILIATION_REQUIRED_TRANSITION: Final = RepairTransition(
    repair_status=RepairStatus.NEEDS_RECONCILIATION,
)


def repair_state_for_action(
    action_type: ControlActionType,
    phase: RepairPhase,
) -> RepairTransition:
    """Look up the repair transition one step of a control action makes.

    Raises:
        KeyError: If the (action_type, phase) pair is not mapped.
    """
    return _REPAIR_MAP[(action_type, phase)]


def terminal_repair_transition(status: ThreadStatus) -> RepairTransition:
    """Return the repair transition a proven terminal *status* settles into.

    Every terminal returns repair to healthy. A cancellation is the one
    terminal recorded as the run's last applied action; a completed or failed
    turn leaves that record as it stood.
    """
    if status is ThreadStatus.CANCELLED:
        return repair_state_for_action(ControlActionType.CANCEL, RepairPhase.APPLIED)
    return _RUN_SETTLED_TRANSITION
