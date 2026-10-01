import pytest

from ...thread.dispatch_policy import FailureType
from ...thread.enums import ThreadStatus
from ...thread.message_policy import (
    ParkedPause,
    PauseAnswerability,
    can_send_followup,
)


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
    [ThreadStatus.SUBMITTED, ThreadStatus.RUNNING],
)
def test_a_run_executing_a_turn_admits_a_continuation_behind_it(
    status: ThreadStatus,
) -> None:
    """Occupancy is what makes a run admitting, not what refuses it.

    Admitted here never means dispatched: the turn is reserved behind the one
    executing and takes the run's write authority only at promotion.
    """
    result = can_send_followup(status.value)

    assert result.allowed is True
    assert result.failure_type is None
    assert result.reason is None


def test_a_cancelling_run_still_refuses_as_busy() -> None:
    """A run that is leaving can never promote what is queued behind it."""
    result = can_send_followup(ThreadStatus.CANCELLING.value)

    assert result.allowed is False
    assert result.failure_type is FailureType.RUN_BUSY
    assert result.reason is not None


def test_a_parked_run_refuses_as_input_required_rather_than_busy() -> None:
    """A pause is answered by its own verb; a message here would orphan it."""
    result = can_send_followup(ThreadStatus.INPUT_REQUIRED.value)

    assert result.allowed is False
    assert result.failure_type is FailureType.INPUT_REQUIRED
    # Without the pause read, the ruling still points at the authority that
    # knows which request is waiting.
    assert result.reason is not None
    assert "run-status" in result.reason


def test_a_permission_pause_names_the_permission_respond_verb() -> None:
    """The exact address, with this run and this request already in it.

    A client told only "paused for input" has two verbs to choose between and
    no way to tell which. The wrong choice is the messages route itself, which
    would start a turn and orphan the pause.
    """
    result = can_send_followup(
        ThreadStatus.INPUT_REQUIRED.value,
        parked_on=ParkedPause(run_id="run-7", permission_request_id="req-9"),
    )

    assert result.allowed is False
    assert result.failure_type is FailureType.INPUT_REQUIRED
    assert result.reason is not None
    assert "POST /v1/runs/run-7/permissions/req-9/respond" in result.reason
    assert "clarification" not in result.reason


def test_a_clarification_pause_names_the_clarification_respond_verb() -> None:
    """No permission row means the pause is an interrupt, answered elsewhere.

    The request id lives in the run's checkpoint and is disclosed on
    run-status, so the refusal names the verb and sends the caller to the
    authoritative disclosure for the id rather than inventing one.
    """
    result = can_send_followup(
        ThreadStatus.INPUT_REQUIRED.value, parked_on=ParkedPause(run_id="run-7")
    )

    assert result.allowed is False
    assert result.reason is not None
    assert "/v1/runs/run-7/clarifications/" in result.reason
    assert "run-status" in result.reason
    assert "permissions" not in result.reason


def test_an_answered_pause_being_applied_asks_for_nothing() -> None:
    """A pause that already has its answer must not be answered twice."""
    result = can_send_followup(
        ThreadStatus.INPUT_REQUIRED.value,
        parked_on=ParkedPause(
            run_id="run-7",
            permission_request_id="req-9",
            answerability=PauseAnswerability.APPLYING_ANSWER,
        ),
    )

    assert result.allowed is False
    assert result.reason is not None
    assert "req-9" in result.reason
    assert "respond" not in result.reason


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
    """No status may fall through to an untyped or silently admitted follow-up.

    Exactly two states admit one, and the set is asserted rather than the
    bare refusals: the policy still ends on a permissive default, so a new
    lifecycle state that nobody classified arrives here as admitted and is
    caught by not being one of these two. Every other state owes both a typed
    code and a sentence.
    """
    admitting = {ThreadStatus.SUBMITTED, ThreadStatus.RUNNING}
    for status in ThreadStatus:
        result = can_send_followup(status.value)
        if status in admitting:
            assert result.allowed is True, status
            assert result.failure_type is None, status
            assert result.reason is None, status
            continue
        assert result.allowed is False, status
        assert result.failure_type is not None, status
        assert result.reason, status
