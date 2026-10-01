"""Tests for the pure dispatch-failure classification helpers."""

from __future__ import annotations

import pytest

from ...thread.dispatch_policy import (
    FailureType,
    classify_dispatch_failure,
    evaluate_dispatch_failure,
)


def test_evaluate_returns_no_failure_for_none() -> None:
    policy, typed_failure = evaluate_dispatch_failure(None)
    assert policy.should_mark_failed is False
    assert policy.is_circuit_open is False
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
def test_evaluate_pairs_classification_with_the_typed_failure(
    failure: FailureType,
) -> None:
    """One call yields the same action as classify plus the typed form."""
    policy, typed_failure = evaluate_dispatch_failure(failure.value)
    assert policy == classify_dispatch_failure(failure.value)
    assert typed_failure is failure


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
    assert classify_dispatch_failure(failure.value).should_mark_failed is False
