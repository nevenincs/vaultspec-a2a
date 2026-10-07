"""Serve every refused run action through one status mapping.

Run-start, follow-up messages, permission and clarification answers, and cancel
all reach the worker through the same dispatch, so they all meet the same typed
outcome vocabulary, :class:`~vaultspec_a2a.thread.dispatch_policy.FailureType`.
This module is the only place that vocabulary becomes an HTTP status. Deriving
the status per verb is what let one busy or saturated worker read as a conflict
on one verb, a retryable outage on a second and an internal gateway fault on a
third. The mapping is a ``match`` over every member, so a member added to the
vocabulary fails the type check here until it is given a status.

The verbs' published ``responses`` are derived from the same mapping, so a
status a verb can serve is a status it declares.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, assert_never

from fastapi import HTTPException

from ..control.action_lease import RUN_NOT_FOUND, ControlActionOutcome
from ..thread.dispatch_policy import FailureType
from .schemas.gateway import RunMessageRefusalCode, RunMessageRefusalDetail

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

__all__ = [
    "CODED_REFUSALS",
    "DISPATCH_FAILURES",
    "refusal_responses",
    "refused_dispatch",
    "refused_outcome",
]


@dataclass(frozen=True, slots=True)
class _ServedRefusal:
    """One served status, with what it tells a client to do next."""

    status_code: int
    description: str


_NOT_FOUND = _ServedRefusal(404, "No such run.")
# Each says the run cannot take the work now and nothing was applied, so they
# share one status and are told apart by the typed code in the body rather than
# by parsing the message.
_REFUSED = _ServedRefusal(
    409,
    "The run cannot take this action now and nothing was applied. A condition "
    "in the shared refusal vocabulary carries its typed code; re-read "
    "run-status before acting again.",
)
# The same status the run-creation seam returns for the same missing invariant,
# so one rule reads identically at every entry point.
_UNSITED = _ServedRefusal(
    422, "The run carries no active project, so the action cannot be sited."
)
_UPSTREAM = _ServedRefusal(
    502,
    "The worker could not be reached, refused the dispatch outright, or failed "
    "inside itself. Reconcile from run-status.",
)
# The router's own token refusal shares this status, and a verb that names the
# status replaces the router-wide description, so it is restated here.
_UNAVAILABLE = _ServedRefusal(
    503,
    "Gateway service token is not configured, the worker is saturated or shut "
    "out by the failure breaker, or another writer held the store's write lock "
    "for the whole of this write; nothing was applied, so retry later.",
)

#: Every condition a dispatch can end in. A refusing worker may name any member
#: of the vocabulary and the gateway adopts it, so a verb that dispatches can be
#: refused with any of them.
DISPATCH_FAILURES: frozenset[FailureType] = frozenset(FailureType)

#: The conditions a refusal body names by code: the closed subset the published
#: contract carries, rather than every failure the gateway knows.
CODED_REFUSALS: frozenset[FailureType] = frozenset(
    FailureType(code.value) for code in RunMessageRefusalCode
)


def _served(failure_type: FailureType) -> _ServedRefusal:
    """Return the one served status for *failure_type*."""
    match failure_type:
        case FailureType.NOT_FOUND:
            return _NOT_FOUND
        case (
            FailureType.INPUT_REQUIRED
            | FailureType.TERMINAL
            | FailureType.CONFLICT
            | FailureType.INCOMPATIBLE_STATE
            | FailureType.RUN_BUSY
            | FailureType.QUEUE_FULL
            | FailureType.DEADLINE_EXCEEDED
        ):
            return _REFUSED
        case FailureType.NO_ACTIVE_PROJECT:
            return _UNSITED
        case (
            FailureType.UNREACHABLE
            | FailureType.REJECTED
            | FailureType.CREDENTIALS_REQUIRED
        ):
            return _UPSTREAM
        case (
            FailureType.CIRCUIT_OPEN | FailureType.AT_CAPACITY | FailureType.STORE_BUSY
        ):
            return _UNAVAILABLE
        case _:
            assert_never(failure_type)


def refused_dispatch(failure_type: FailureType, detail: str | None) -> HTTPException:
    """Serve one dispatch outcome the same way whichever verb met it.

    A condition in the closed refusal vocabulary is served as a typed body, so
    a consumer matches the code rather than the sentence; every other condition
    carries the sentence alone.
    """
    status_code = _served(failure_type).status_code
    if failure_type in CODED_REFUSALS:
        body = RunMessageRefusalDetail(
            code=RunMessageRefusalCode(failure_type.value),
            # The served field is bounded, and the detail is composed upstream
            # from worker text; truncating here keeps an over-long message a
            # refusal rather than a validation fault inside the error path.
            message=(detail or "The run cannot take this now")[:1024],
        )
        return HTTPException(
            status_code=status_code, detail=body.model_dump(mode="json")
        )
    return HTTPException(status_code=status_code, detail=detail)


def refused_outcome(outcome: ControlActionOutcome) -> HTTPException | None:
    """Serve a run-control outcome's refusal, or ``None`` when the verb holds.

    Every run-control verb ends in the same record, so one reading serves them
    all. A guard a verb applied before anything was dispatched names its own
    status, because it is about this request rather than about reaching the
    worker; everything that got as far as a dispatch carries only its typed
    failure and is served by the shared mapping. A run that is not there is
    served as such whichever service phrased it.

    A terminal outcome that is also applied is not a refusal. Cancelling a run
    that is already cancelled leaves the state the caller asked for in force, so
    the verb answers with the run's status rather than failing a second cancel
    purely for being second.
    """
    if outcome.error_status_code is not None:
        return HTTPException(
            status_code=outcome.error_status_code, detail=outcome.error_detail
        )
    failure_type = outcome.failure_type
    if failure_type is None or (
        failure_type is FailureType.TERMINAL and outcome.applied
    ):
        return None
    if failure_type is FailureType.NOT_FOUND:
        return refused_dispatch(failure_type, RUN_NOT_FOUND)
    return refused_dispatch(failure_type, outcome.error_detail)


def refusal_responses(
    reachable: Iterable[FailureType],
    described: Mapping[int, dict[str, Any]] | None = None,
) -> dict[int | str, dict[str, Any]]:
    """Declare every status *reachable* is served with, beside a verb's own.

    A ``described`` entry wins for the status it names, so a verb says what that
    status means on it, and may declare statuses of its own; every other status
    the mapping serves for a member of *reachable* is declared with its shared
    description, in status order so the published contract is stable.

    422 is left to FastAPI, which already declares it on every verb that takes a
    parameter: declaring it here would replace the validation-error schema it
    publishes for the same status.
    """
    shared = {
        served.status_code: served.description
        for served in map(_served, reachable)
        if served.status_code != 422
    }
    responses: dict[int | str, dict[str, Any]] = {
        status_code: {"description": shared[status_code]}
        for status_code in sorted(shared)
    }
    if described is not None:
        responses.update(described.items())
    return responses
