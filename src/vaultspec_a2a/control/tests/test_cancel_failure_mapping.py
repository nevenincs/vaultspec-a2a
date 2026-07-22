"""Both cancel edges must map a failure to the same status.

The internal thread-cancel route and the versioned run-cancel verb each turned a
cancel outcome into an HTTP error inline and identically. Two copies of one
status mapping drift: a later edit to one edge silently gives the same underlying
failure a different status on the other. The mapping is shared now, and these
assert the property that sharing protects - same failure, same status, only the
resource noun differs.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from vaultspec_a2a.control.cancel_service import (
    CancelResult,
    raise_for_cancel_failure,
)
from vaultspec_a2a.thread.dispatch_policy import FailureType


def _result(failure: FailureType | None, *, detail: str | None = None) -> CancelResult:
    return CancelResult(
        action_id=None,
        thread_id="t-1",
        cancelled=failure is None,
        thread_status="cancelling" if failure is None else "running",
        error_detail=detail,
        failure_type=failure,
    )


@pytest.mark.parametrize("noun", ["Thread", "Run"])
def test_a_not_found_failure_is_404_naming_the_resource(noun: str) -> None:
    """The status is shared; the noun is the caller's own vocabulary."""
    with pytest.raises(HTTPException) as raised:
        raise_for_cancel_failure(_result(FailureType.NOT_FOUND), resource_noun=noun)

    assert raised.value.status_code == 404
    assert raised.value.detail == f"{noun} not found"


@pytest.mark.parametrize("noun", ["Thread", "Run"])
def test_any_other_failure_is_502(noun: str) -> None:
    """A dispatch failure that is not not-found is a bad-gateway on both edges."""
    with pytest.raises(HTTPException) as raised:
        raise_for_cancel_failure(
            _result(FailureType.UNREACHABLE, detail="worker exploded"),
            resource_noun=noun,
        )

    assert raised.value.status_code == 502
    assert raised.value.detail == "worker exploded"


def test_a_missing_error_detail_falls_back_to_a_generic_reason() -> None:
    """A 502 must carry a reason even when the service left none."""
    with pytest.raises(HTTPException) as raised:
        raise_for_cancel_failure(_result(FailureType.UNREACHABLE), resource_noun="Run")

    assert raised.value.detail == "Cancel dispatch failed"


def test_a_successful_cancel_does_not_raise() -> None:
    """No failure, no error - the route continues to its response."""
    raise_for_cancel_failure(_result(None), resource_noun="Thread")


def test_the_two_edges_agree_on_status_for_the_same_failure() -> None:
    """The property the shared mapper exists to hold: same failure, same status."""
    for failure in (FailureType.NOT_FOUND, FailureType.UNREACHABLE):
        statuses = []
        for noun in ("Thread", "Run"):
            try:
                raise_for_cancel_failure(_result(failure), resource_noun=noun)
            except HTTPException as exc:
                statuses.append(exc.status_code)
        assert statuses[0] == statuses[1], failure
