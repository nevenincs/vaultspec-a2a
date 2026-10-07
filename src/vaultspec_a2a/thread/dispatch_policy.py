"""Pure dispatch-failure vocabulary and policy — no I/O, no database."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "FailureType",
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
    # A busy run whose continuation queue is already spent, per run or across
    # the service. Distinct from RUN_BUSY, which is now the answer only for a
    # run that admits no continuation at all: this one says the run would have
    # taken the turn and has nowhere to put it, so the caller retries once the
    # waiting turn has run rather than reconciling anything.
    QUEUE_FULL = "queue_full"
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


_POLICY: dict[FailureType, FailureAction] = {
    # An open circuit, a saturated worker and an unreachable one are all
    # conditions that pass. The accepted work stays alive for the retry the
    # recovery coordinator already scheduled, so none of them may move the run
    # to a failed status: doing so quarantines a run that nothing is wrong with
    # and strands work that was going to be delivered.
    FailureType.CIRCUIT_OPEN: FailureAction(should_mark_failed=False),
    FailureType.AT_CAPACITY: FailureAction(should_mark_failed=False),
    FailureType.UNREACHABLE: FailureAction(should_mark_failed=False),
    FailureType.REJECTED: FailureAction(should_mark_failed=True),
    # The worker already holds this run's slot, so the dispatch was a duplicate
    # of work that IS being done. Failing the run here would kill the very turn
    # the refusal is reporting as alive.
    FailureType.RUN_BUSY: FailureAction(should_mark_failed=False),
}

_DEFAULT = FailureAction(should_mark_failed=True)

_NO_FAILURE = FailureAction(should_mark_failed=False)


def evaluate_dispatch_failure(
    failure_type: str | None,
) -> tuple[FailureAction, FailureType | None]:
    """Classify a dispatch outcome and resolve its typed failure together.

    The leased delivery sequence is the one consumer: it reports the typed
    failure and acts on the policy, and getting both from one call keeps it
    from deriving the pair differently.

    Args:
        failure_type: The ``DispatchOutcome.failure_type`` string, or None on
            success.

    Returns:
        The :class:`FailureAction` the failure calls for and the
        :class:`FailureType` the string maps to (``None`` when there is no
        failure type).

    Raises:
        ValueError: If *failure_type* names no :class:`FailureType`.
    """
    if not failure_type:
        return _NO_FAILURE, None
    typed = FailureType(failure_type)
    return _POLICY.get(typed, _DEFAULT), typed
