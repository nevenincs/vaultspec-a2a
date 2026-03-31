"""Pure repair-state lookup — no I/O, no database.

Provides a single authoritative mapping from control action type and
phase (requested vs applied) to the expected repair state.  Previously
these mappings were scattered across 7 functions in
``control/repair_transitions.py``.
"""

from __future__ import annotations

from dataclasses import dataclass

from .enums import ControlActionType, RepairStatus


@dataclass(frozen=True, slots=True)
class RepairTransition:
    """Descriptor for the repair-state mutation of a control action."""

    repair_status: RepairStatus
    execution_readiness: str


_REPAIR_MAP: dict[tuple[ControlActionType, str], RepairTransition] = {
    # ingest
    (ControlActionType.INGEST, "requested"): RepairTransition(
        repair_status=RepairStatus.HEALTHY,
        execution_readiness=RepairStatus.HEALTHY.value,
    ),
    (ControlActionType.INGEST, "applied"): RepairTransition(
        repair_status=RepairStatus.HEALTHY,
        execution_readiness=RepairStatus.HEALTHY.value,
    ),
    # permission response
    (ControlActionType.PERMISSION_RESPONSE_SUBMITTED, "requested"): RepairTransition(
        repair_status=RepairStatus.PAUSED_RESUMABLE,
        execution_readiness=RepairStatus.PAUSED_RESUMABLE.value,
    ),
    (ControlActionType.PERMISSION_RESPONSE_SUBMITTED, "applied"): RepairTransition(
        repair_status=RepairStatus.HEALTHY,
        execution_readiness=RepairStatus.HEALTHY.value,
    ),
    # message followup
    (ControlActionType.MESSAGE_FOLLOWUP_REQUESTED, "requested"): RepairTransition(
        repair_status=RepairStatus.HEALTHY,
        execution_readiness=RepairStatus.HEALTHY.value,
    ),
    (ControlActionType.MESSAGE_FOLLOWUP_REQUESTED, "applied"): RepairTransition(
        repair_status=RepairStatus.HEALTHY,
        execution_readiness=RepairStatus.HEALTHY.value,
    ),
    # cancel
    (ControlActionType.CANCEL, "requested"): RepairTransition(
        repair_status=RepairStatus.CANCEL_PENDING,
        execution_readiness=RepairStatus.CANCEL_PENDING.value,
    ),
}


def repair_state_for_action(
    action_type: ControlActionType,
    phase: str,
) -> RepairTransition:
    """Look up the expected repair state for a control-action transition.

    Args:
        action_type: The control action type.
        phase: ``"requested"`` or ``"applied"``.

    Returns:
        A frozen descriptor with repair_status and execution_readiness.

    Raises:
        KeyError: If the (action_type, phase) pair is not mapped.
    """
    return _REPAIR_MAP[(action_type, phase)]
