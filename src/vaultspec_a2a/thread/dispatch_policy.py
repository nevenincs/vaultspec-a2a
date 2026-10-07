"""Pure dispatch-failure vocabulary and policy — no I/O, no database."""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "FailureType",
    "evaluate_dispatch_failure",
    "resolve_failure_type",
]


class FailureType(StrEnum):
    """Typed dispatch failure categories.

    Each value corresponds to a ``_DispatchOutcome.failure_type`` string
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
    # Every attempt at the verb's durable write was refused because another
    # writer held the store's write lock throughout. Distinct from AT_CAPACITY,
    # which is the worker's own refusal: no worker was involved and nothing was
    # applied, so the caller simply retries.
    STORE_BUSY = "store_busy"


# Whether a dispatch failure of each type moves the run to FAILED. A type absent
# from the table does, so a new failure fails the run until it is judged.
_MARKS_RUN_FAILED: dict[FailureType, bool] = {
    # An open circuit, a saturated worker and an unreachable one are all
    # conditions that pass. The accepted work stays alive for the retry the
    # recovery coordinator already scheduled, so none of them may move the run
    # to a failed status: doing so quarantines a run that nothing is wrong with
    # and strands work that was going to be delivered.
    FailureType.CIRCUIT_OPEN: False,
    FailureType.AT_CAPACITY: False,
    FailureType.UNREACHABLE: False,
    FailureType.REJECTED: True,
    # The worker already holds this run's slot, so the dispatch was a duplicate
    # of work that IS being done. Failing the run here would kill the very turn
    # the refusal is reporting as alive.
    FailureType.RUN_BUSY: False,
    # A contended store wrote nothing and says nothing about the run.
    FailureType.STORE_BUSY: False,
}


def resolve_failure_type(value: str | None) -> FailureType | None:
    """Return the failure type *value* names, or ``None`` when it names none."""
    try:
        return FailureType(value)
    except ValueError:
        return None


def evaluate_dispatch_failure(
    failure_type: str | None,
) -> tuple[bool, FailureType | None]:
    """Classify a dispatch outcome and resolve its typed failure together.

    The leased delivery sequence is the one consumer: it reports the typed
    failure and acts on the policy, and getting both from one call keeps it
    from deriving the pair differently.

    Args:
        failure_type: The ``_DispatchOutcome.failure_type`` string, or None on
            success.

    Returns:
        Whether the failure moves the run to FAILED, and the
        :class:`FailureType` the string maps to (``None`` when there is no
        failure type).

    Raises:
        ValueError: If *failure_type* names no :class:`FailureType`.
    """
    if not failure_type:
        return False, None
    typed = resolve_failure_type(failure_type)
    if typed is None:
        raise ValueError(f"{failure_type!r} is not a valid FailureType")
    return _MARKS_RUN_FAILED.get(typed, True), typed
