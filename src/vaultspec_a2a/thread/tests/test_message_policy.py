from vaultspec_a2a.thread.message_policy import can_send_followup


def test_repair_needed_threads_are_not_message_eligible() -> None:
    """Follow-ups must not bypass repair-needed workflow state."""
    result = can_send_followup("repair_needed")

    assert result.allowed is False
    assert (
        result.reason
        == "Cannot send messages while thread is in 'repair_needed' repair state"
    )


def test_reconciling_threads_are_not_message_eligible() -> None:
    """Follow-ups must not race the reconciliation redispatch path."""
    result = can_send_followup("reconciling")

    assert result.allowed is False
    assert (
        result.reason
        == "Cannot send messages while thread is in 'reconciling' repair state"
    )
