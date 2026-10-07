"""A cancel refusal is served by the one dispatch mapping - and only a real one.

Cancel reaches the worker through the same dispatch as every other run action,
so its outcome is served by the same status mapping rather than by a copy of its
own. These pin what the cancel verb adds on top of that mapping: the run it
names, the reason it falls back to, and the idempotent second cancel that is not
a refusal at all.
"""

from __future__ import annotations

import pytest

from ...control.action_lease import ControlActionOutcome
from ...thread.dispatch_policy import FailureType
from .._dispatch_refusals import refused_cancel


def _result(
    failure: FailureType | None,
    *,
    detail: str | None = None,
    thread_status: str | None = None,
) -> ControlActionOutcome:
    if thread_status is None:
        thread_status = "cancelling" if failure is None else "running"
    return ControlActionOutcome(
        thread_id="t-1",
        cancelled=failure is None,
        thread_status=thread_status,
        error_detail=detail,
        failure_type=failure,
    )


def test_a_not_found_failure_is_404_naming_the_run() -> None:
    """The service's own noun is not the edge's; the verb names a run."""
    refused = refused_cancel(_result(FailureType.NOT_FOUND, detail="Thread not found"))

    assert refused is not None
    assert refused.status_code == 404
    assert refused.detail == "Run not found"


def test_an_unreachable_worker_is_502() -> None:
    """A dispatch that could not be delivered is a bad gateway."""
    refused = refused_cancel(_result(FailureType.UNREACHABLE, detail="worker exploded"))

    assert refused is not None
    assert refused.status_code == 502
    assert refused.detail == "worker exploded"


def test_a_missing_error_detail_falls_back_to_a_generic_reason() -> None:
    """A 502 must carry a reason even when the service left none."""
    refused = refused_cancel(_result(FailureType.UNREACHABLE))

    assert refused is not None
    assert refused.detail == "Cancel dispatch failed"


def test_a_successful_cancel_is_not_refused() -> None:
    """No failure, no error - the route continues to its response."""
    assert refused_cancel(_result(None)) is None


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
        refused = refused_cancel(_result(FailureType.TERMINAL, thread_status=status))

        assert refused is not None
        assert refused.status_code == 409
        # A settled run is a condition of the shared refusal vocabulary, so the
        # body names it by code; the message names the state, so a caller
        # learns to re-read the run rather than to retry a request that can
        # never succeed.
        assert refused.detail["code"] == FailureType.TERMINAL.value
        assert status in refused.detail["message"]

    def test_a_dispatch_failure_is_still_a_bad_gateway(self) -> None:
        """The narrowing must not swallow the case 502 is genuinely for."""
        refused = refused_cancel(
            _result(FailureType.UNREACHABLE, thread_status="running")
        )

        assert refused is not None
        assert refused.status_code == 502

    def test_cancelling_an_already_cancelled_run_is_not_an_error(self) -> None:
        """The verb is idempotent, so the second cancel is not a failure.

        The caller asked for cancelled and the run is cancelled. Refusing here
        would fail a request purely for being the second one, which is the shape
        of an idempotent verb that is not actually idempotent.
        """
        assert (
            refused_cancel(_result(FailureType.TERMINAL, thread_status="cancelled"))
            is None
        )

    def test_a_service_supplied_reason_survives_the_conflict(self) -> None:
        """A reason the service already phrased is preferred to the generic one."""
        refused = refused_cancel(
            _result(
                FailureType.TERMINAL,
                detail="Cannot cancel thread in 'failed' state",
                thread_status="failed",
            )
        )

        assert refused is not None
        assert refused.detail["message"] == "Cannot cancel thread in 'failed' state"
