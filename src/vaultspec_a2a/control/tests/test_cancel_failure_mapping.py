"""Both cancel edges must map a failure to the same status - and the right one.

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

from ...control.cancel_service import (
    CancelResult,
    raise_for_cancel_failure,
)
from ...thread.dispatch_policy import FailureType


def _result(
    failure: FailureType | None,
    *,
    detail: str | None = None,
    thread_status: str | None = None,
) -> CancelResult:
    if thread_status is None:
        thread_status = "cancelling" if failure is None else "running"
    return CancelResult(
        action_id=None,
        thread_id="t-1",
        cancelled=failure is None,
        thread_status=thread_status,
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
    for failure in (
        FailureType.NOT_FOUND,
        FailureType.UNREACHABLE,
        FailureType.TERMINAL,
    ):
        statuses: list[int] = []
        for noun in ("Thread", "Run"):
            try:
                raise_for_cancel_failure(_result(failure), resource_noun=noun)
            except HTTPException as exc:
                statuses.append(exc.status_code)
        assert statuses[0] == statuses[1], failure


class TestSettledRunIsNotAnUpstreamFailure:
    """A run's own state forbidding the verb is a 409, never a bad gateway.

    The distinction these pin is the one ``FailureType`` already draws and the
    HTTP mapping used to discard: a DISPATCH failure could not deliver the
    request, a DOMAIN rejection never tried because the run had already settled.
    Reporting the second as 502 told callers their infrastructure was broken when
    the truth was that their run had finished - observed live, where a cancel
    issued against a run that had just failed answered 502 three times over.
    """

    @pytest.mark.parametrize("status", ["failed", "completed", "archived", "deleting"])
    def test_a_run_settled_another_way_is_a_conflict(self, status: str) -> None:
        with pytest.raises(HTTPException) as raised:
            raise_for_cancel_failure(
                _result(FailureType.TERMINAL, thread_status=status),
                resource_noun="Run",
            )

        assert raised.value.status_code == 409
        # The refusal names the state, so a caller learns to re-read the run
        # rather than to retry a request that can never succeed.
        assert status in str(raised.value.detail)

    def test_a_dispatch_failure_is_still_a_bad_gateway(self) -> None:
        """The narrowing must not swallow the case 502 is genuinely for."""
        with pytest.raises(HTTPException) as raised:
            raise_for_cancel_failure(
                _result(FailureType.UNREACHABLE, thread_status="running"),
                resource_noun="Run",
            )

        assert raised.value.status_code == 502

    def test_cancelling_an_already_cancelled_run_is_not_an_error(self) -> None:
        """The verb is idempotent, so the second cancel is not a failure.

        The caller asked for cancelled and the run is cancelled. Raising here
        would fail a request purely for being the second one, which is the shape
        of an idempotent verb that is not actually idempotent.
        """
        raise_for_cancel_failure(
            _result(FailureType.TERMINAL, thread_status="cancelled"),
            resource_noun="Run",
        )

    def test_a_service_supplied_reason_survives_the_conflict(self) -> None:
        """A reason the service already phrased is preferred to the generic one."""
        with pytest.raises(HTTPException) as raised:
            raise_for_cancel_failure(
                _result(
                    FailureType.TERMINAL,
                    detail="Cannot cancel thread in 'failed' state",
                    thread_status="failed",
                ),
                resource_noun="Run",
            )

        assert raised.value.detail == "Cannot cancel thread in 'failed' state"
