"""Pure dispatch-failure classification — no I/O, no database.

Consolidates the inconsistent failure policies previously scattered
across thread_service, message_service, cancel_service, and
permission_service into a single authoritative lookup.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


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


@dataclass(frozen=True, slots=True)
class FailureAction:
    """Describes how the caller should react to a dispatch failure."""

    should_mark_failed: bool
    """Whether the thread should transition to FAILED status."""

    is_circuit_open: bool
    """Whether the caller should surface a 503 / circuit-open error."""


_POLICY: dict[str, FailureAction] = {
    FailureType.CIRCUIT_OPEN: FailureAction(
        should_mark_failed=False, is_circuit_open=True
    ),
    FailureType.AT_CAPACITY: FailureAction(
        should_mark_failed=True, is_circuit_open=False
    ),
    FailureType.UNREACHABLE: FailureAction(
        should_mark_failed=True, is_circuit_open=False
    ),
    FailureType.REJECTED: FailureAction(should_mark_failed=True, is_circuit_open=False),
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
