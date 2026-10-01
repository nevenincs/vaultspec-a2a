"""Pure dispatch-failure classification — no I/O, no database.

Consolidates the inconsistent failure policies previously scattered
across thread_service, message_service, cancel_service, and
permission_service into a single authoritative lookup.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "FailureType",
    "classify_dispatch_failure",
    "evaluate_dispatch_failure",
]


class FailureType(StrEnum):
    """Typed dispatch failure categories.

    Each value corresponds to a ``DispatchOutcome.failure_type`` string
    produced by :func:`safe_dispatch`.  Route handlers use these to map
    failures to HTTP status codes without string parsing.
    """

    CIRCUIT_OPEN = "circuit_open"
    AT_CAPACITY = "at_capacity"
    UNREACHABLE = "unreachable"
    REJECTED = "rejected"

    # Domain rejections (thread-level, not dispatch-level)
    NOT_FOUND = "not_found"
    TERMINAL = "terminal"
    INPUT_REQUIRED = "input_required"
    CONFLICT = "conflict"
    # A run whose current turn has not finished. Distinct from CONFLICT, which
    # means the supplied idempotency key is already bound to different content:
    # this one is about the run's occupancy and nothing was reserved, so a caller
    # reconciles from run-status rather than resending under a new key.
    RUN_BUSY = "run_busy"
    # A stored run whose metadata names no active project. Distinct from the
    # dispatch failures above: nothing was attempted and no worker was involved,
    # so it carries the same status as the equivalent refusal at run creation
    # rather than a transport error.
    NO_ACTIVE_PROJECT = "no_active_project"
    INCOMPATIBLE_STATE = "incompatible_state"
    CREDENTIALS_REQUIRED = "credentials_required"
    DEADLINE_EXCEEDED = "deadline_exceeded"


@dataclass(frozen=True, slots=True)
class FailureAction:
    """Describes how the caller should react to a dispatch failure."""

    should_mark_failed: bool
    """Whether the thread should transition to FAILED status."""

    is_circuit_open: bool
    """Whether the caller should surface a 503 / circuit-open error."""


_POLICY: dict[str, FailureAction] = {
    # An open circuit, a saturated worker and an unreachable one are all
    # conditions that pass. The accepted work stays alive for the retry the
    # recovery coordinator already scheduled, so none of them may move the run
    # to a failed status: doing so quarantines a run that nothing is wrong with
    # and strands work that was going to be delivered.
    FailureType.CIRCUIT_OPEN: FailureAction(
        should_mark_failed=False, is_circuit_open=True
    ),
    FailureType.AT_CAPACITY: FailureAction(
        should_mark_failed=False, is_circuit_open=False
    ),
    FailureType.UNREACHABLE: FailureAction(
        should_mark_failed=False, is_circuit_open=False
    ),
    FailureType.REJECTED: FailureAction(should_mark_failed=True, is_circuit_open=False),
    # The worker already holds this run's slot, so the dispatch was a duplicate
    # of work that IS being done. Failing the run here would kill the very turn
    # the refusal is reporting as alive.
    FailureType.RUN_BUSY: FailureAction(
        should_mark_failed=False, is_circuit_open=False
    ),
}

_DEFAULT = FailureAction(should_mark_failed=True, is_circuit_open=False)


def classify_dispatch_failure(failure_type: str | None) -> FailureAction:
    """Return the canonical failure action for a dispatch outcome.

    Args:
        failure_type: The ``DispatchOutcome.failure_type`` string, or None
            on success.

    Returns:
        A frozen descriptor the caller uses to decide status transitions
        and error responses.
    """
    if failure_type is None:
        return FailureAction(should_mark_failed=False, is_circuit_open=False)
    return _POLICY.get(failure_type, _DEFAULT)


def evaluate_dispatch_failure(
    failure_type: str | None,
) -> tuple[FailureAction, FailureType | None]:
    """Classify a dispatch failure and resolve its typed form together.

    Every dispatch caller (run creation, message follow-up, permission resume,
    cancel) pairs the failure-action classification with the same typed-failure
    resolution. Returning both from one call keeps those callers from deriving
    the pair differently.

    Args:
        failure_type: The ``DispatchOutcome.failure_type`` string, or None.

    Returns:
        The canonical :class:`FailureAction` and the :class:`FailureType` the
        string maps to (``None`` when there is no failure type).
    """
    return (
        classify_dispatch_failure(failure_type),
        FailureType(failure_type) if failure_type else None,
    )
