import pytest

from ...thread.dispatch_policy import FailureType
from ...thread.enums import ThreadStatus
from ...thread.message_policy import can_send_followup


def test_repair_needed_threads_are_not_message_eligible() -> None:
    """Follow-ups must not bypass repair-needed workflow state."""
    result = can_send_followup("repair_needed")

    assert result.allowed is False
    assert (
        result.reason
        == "Cannot send messages while thread is in 'repair_needed' repair state"
    )
    assert result.failure_type is FailureType.TERMINAL


def test_reconciling_threads_are_not_message_eligible() -> None:
    """Follow-ups must not race the reconciliation redispatch path."""
    result = can_send_followup("reconciling")

    assert result.allowed is False
    assert (
        result.reason
        == "Cannot send messages while thread is in 'reconciling' repair state"
    )
    assert result.failure_type is FailureType.TERMINAL


@pytest.mark.parametrize(
    "status",
    [ThreadStatus.SUBMITTED, ThreadStatus.RUNNING, ThreadStatus.CANCELLING],
)
def test_a_run_that_still_owns_a_turn_refuses_as_busy(status: ThreadStatus) -> None:
    """Occupancy is its own refusal, distinct from a settled or parked run."""
    result = can_send_followup(status.value)

    assert result.allowed is False
    assert result.failure_type is FailureType.RUN_BUSY
    assert result.reason is not None


def test_a_parked_run_refuses_as_input_required_rather_than_busy() -> None:
    """A pause is answered by its own verb; a message here would orphan it."""
    result = can_send_followup(ThreadStatus.INPUT_REQUIRED.value)

    assert result.allowed is False
    assert result.failure_type is FailureType.INPUT_REQUIRED


@pytest.mark.parametrize(
    "status",
    [
        ThreadStatus.COMPLETED,
        ThreadStatus.FAILED,
        ThreadStatus.CANCELLED,
        ThreadStatus.ARCHIVED,
        ThreadStatus.DELETING,
    ],
)
def test_a_settled_run_refuses_as_terminal(status: ThreadStatus) -> None:
    """A run that is over is a different refusal from one that is occupied."""
    result = can_send_followup(status.value)

    assert result.allowed is False
    assert result.failure_type is FailureType.TERMINAL


def test_every_lifecycle_status_resolves_to_a_typed_answer() -> None:
    """No status may fall through to an untyped or silently allowed follow-up.

    The vocabulary is closed, so a new lifecycle state has to be classified here
    deliberately rather than inheriting the permissive default the old policy
    ended on.
    """
    for status in ThreadStatus:
        result = can_send_followup(status.value)
        assert result.allowed is False, status
        assert result.failure_type is not None, status
        assert result.reason, status
