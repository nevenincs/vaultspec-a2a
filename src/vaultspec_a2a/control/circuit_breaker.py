"""Worker circuit breaker.

Tracks worker dispatch health and rejects requests when the worker is down.
Protocol-agnostic: callers are responsible for translating a ``False`` return
from ``pre_dispatch()`` into the appropriate HTTP/WS error.
"""

from __future__ import annotations

import logging
import time

__all__ = ["WorkerCircuitBreaker"]

logger = logging.getLogger(__name__)


class WorkerCircuitBreaker:
    """Track worker dispatch health and reject requests when the worker is down.

    States:
    - CLOSED: dispatches flow normally.  Consecutive failures are counted.
    - OPEN: all dispatches are rejected.  After ``recovery_timeout``
      seconds, transitions to HALF_OPEN.
    - HALF_OPEN: a single probe dispatch is allowed through.  Success closes
      the circuit; failure re-opens it.
    """

    def __init__(
        self,
        failure_threshold: int,
        recovery_timeout: float,
    ) -> None:
        """Initialise circuit breaker with failure threshold and recovery timeout."""
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._consecutive_failures = 0
        self._state: str = "closed"  # closed | open | half_open
        self._opened_at: float = 0.0

    @property
    def state(self) -> str:
        """Current circuit state, with automatic half-open promotion."""
        if (
            self._state == "open"
            and (time.monotonic() - self._opened_at) >= self._recovery_timeout
        ):
            self._state = "half_open"
        return self._state

    def pre_dispatch(self) -> bool:
        """Check whether a dispatch is allowed.

        Returns ``True`` if the dispatch may proceed, ``False`` if the circuit
        is open and the caller should reject the request.  When ``False`` is
        returned the caller can use ``rejection_detail`` for the error message.
        """
        # half_open: allow one probe through (don't block)
        return self.state != "open"

    @property
    def rejection_detail(self) -> str:
        """Human-readable reason for the rejection.

        Valid after ``pre_dispatch`` returns ``False``.
        """
        return (
            "Worker circuit breaker OPEN — "
            f"{self._consecutive_failures} consecutive dispatch failures. "
            f"Retrying in {self._recovery_timeout}s."
        )

    def record_success(self) -> None:
        """Record a successful dispatch — closes the circuit."""
        if self._state != "closed":
            logger.info("Worker circuit breaker CLOSED (dispatch succeeded)")
        self._consecutive_failures = 0
        self._state = "closed"

    def record_failure(self) -> None:
        """Record a failed dispatch — may open the circuit."""
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._failure_threshold:
            if self._state != "open":
                logger.warning(
                    "Worker circuit breaker OPEN after %d consecutive failures",
                    self._consecutive_failures,
                )
            self._state = "open"
            self._opened_at = time.monotonic()

    def force_open(self) -> None:
        """Force the circuit open immediately (used by watchdog on crash)."""
        if self._state != "open":
            logger.warning("Worker circuit breaker forced OPEN by watchdog")
        self._consecutive_failures = self._failure_threshold
        self._state = "open"
        self._opened_at = time.monotonic()
