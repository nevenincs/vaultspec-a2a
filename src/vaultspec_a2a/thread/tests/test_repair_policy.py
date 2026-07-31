"""Pure repair-policy lookups stay aligned with runtime repair transitions."""

from ...thread.enums import ControlActionType, RepairStatus
from ...thread.repair_policy import repair_state_for_action


def test_message_followup_applied_uses_applied_enum_key() -> None:
    """Applied follow-up transitions must resolve through the applied enum."""
    transition = repair_state_for_action(
        ControlActionType.MESSAGE_FOLLOWUP_APPLIED,
        "applied",
    )

    assert transition.repair_status == RepairStatus.HEALTHY
    assert transition.execution_readiness == RepairStatus.HEALTHY.value
