"""Tests for the pure dispatch-failure policy."""

from __future__ import annotations

import pytest

from ...thread.dispatch_policy import FailureType, evaluate_dispatch_failure


def test_evaluate_returns_no_failure_for_none() -> None:
    policy, typed_failure = evaluate_dispatch_failure(None)
    assert policy.should_mark_failed is False
    assert typed_failure is None


@pytest.mark.parametrize(
    "failure",
    [
        FailureType.CIRCUIT_OPEN,
        FailureType.AT_CAPACITY,
        FailureType.UNREACHABLE,
        FailureType.REJECTED,
    ],
)
def test_evaluate_resolves_the_typed_failure(failure: FailureType) -> None:
    """The outcome string comes back as the enum member it names."""
    _policy, typed_failure = evaluate_dispatch_failure(failure.value)
    assert typed_failure is failure


def test_evaluate_refuses_an_unknown_failure_string() -> None:
    with pytest.raises(ValueError, match="not-a-failure"):
        evaluate_dispatch_failure("not-a-failure")


def test_a_rejected_dispatch_fails_the_run() -> None:
    policy, _typed_failure = evaluate_dispatch_failure(FailureType.REJECTED.value)
    assert policy.should_mark_failed is True


@pytest.mark.parametrize(
    "failure",
    [
        FailureType.CIRCUIT_OPEN,
        FailureType.AT_CAPACITY,
        FailureType.UNREACHABLE,
    ],
)
def test_a_condition_that_passes_never_fails_the_run(failure: FailureType) -> None:
    """Accepted work outlives a shut circuit, a full worker and an absent one.

    All three are retried on a schedule the dispatch never sees, so failing the
    run here would discard work that is still going to be delivered.
    """
    policy, _typed_failure = evaluate_dispatch_failure(failure.value)
    assert policy.should_mark_failed is False
