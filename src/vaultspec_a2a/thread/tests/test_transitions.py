"""Tests for thread/transitions.py — state machine validation."""

from __future__ import annotations

import pytest

from ..enums import (
    ACTIVE_STATUSES,
    NON_ACTIVE_STATUSES,
    TERMINAL_STATUSES,
    InvalidTransitionError,
    ThreadStatus,
)
from ..transitions import _VALID_TRANSITIONS, validate_transition


def test_valid_transition_submitted_to_running() -> None:
    validate_transition(ThreadStatus.SUBMITTED, ThreadStatus.RUNNING)


def test_valid_transition_running_to_completed() -> None:
    validate_transition(ThreadStatus.RUNNING, ThreadStatus.COMPLETED)


def test_valid_transition_running_to_cancelled() -> None:
    validate_transition(ThreadStatus.RUNNING, ThreadStatus.CANCELLED)


def test_valid_transition_running_to_failed() -> None:
    validate_transition(ThreadStatus.RUNNING, ThreadStatus.FAILED)


def test_valid_transition_input_required_to_running() -> None:
    validate_transition(ThreadStatus.INPUT_REQUIRED, ThreadStatus.RUNNING)


def test_valid_transition_cancelling_to_cancelled() -> None:
    validate_transition(ThreadStatus.CANCELLING, ThreadStatus.CANCELLED)


def test_valid_transition_completed_to_archived() -> None:
    validate_transition(ThreadStatus.COMPLETED, ThreadStatus.ARCHIVED)


def test_same_status_is_noop() -> None:
    validate_transition(ThreadStatus.RUNNING, ThreadStatus.RUNNING)


def test_invalid_transition_archived_to_running() -> None:
    with pytest.raises(InvalidTransitionError, match=r"archived.*running"):
        validate_transition(ThreadStatus.ARCHIVED, ThreadStatus.RUNNING, thread_id="t1")


def test_invalid_transition_completed_to_running() -> None:
    with pytest.raises(InvalidTransitionError):
        validate_transition(ThreadStatus.COMPLETED, ThreadStatus.RUNNING)


def test_invalid_transition_submitted_to_archived() -> None:
    with pytest.raises(InvalidTransitionError):
        validate_transition(ThreadStatus.SUBMITTED, ThreadStatus.ARCHIVED)


def test_every_status_has_transitions_defined() -> None:
    """Every ThreadStatus member should appear as a key in _VALID_TRANSITIONS."""
    for status in ThreadStatus:
        assert status in _VALID_TRANSITIONS, f"{status} missing from transition table"


def test_discovery_statuses_explicitly_classify_the_lifecycle_vocabulary() -> None:
    """A new lifecycle state must be classified before discovery can use it."""
    assert ACTIVE_STATUSES.isdisjoint(NON_ACTIVE_STATUSES)
    assert frozenset(ThreadStatus) == ACTIVE_STATUSES | NON_ACTIVE_STATUSES


def test_no_self_loops_in_transition_table() -> None:
    """The transition table should never list a status as its own target."""
    for source, targets in _VALID_TRANSITIONS.items():
        assert source not in targets, (
            f"{source} has a self-loop in the transition table"
        )


def test_terminal_states_lead_only_to_archived_or_nothing() -> None:
    for status in TERMINAL_STATUSES:
        targets = _VALID_TRANSITIONS[status]
        assert targets <= {ThreadStatus.ARCHIVED}, (
            f"{status} should only transition to ARCHIVED, got {targets}"
        )
