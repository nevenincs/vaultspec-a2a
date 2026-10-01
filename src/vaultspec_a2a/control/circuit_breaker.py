"""Worker circuit breaker.

Tracks worker TRANSPORT health and rejects requests when the worker is down.
Protocol-agnostic: callers are responsible for translating a ``False`` return
from ``pre_dispatch()`` into the appropriate HTTP/WS error.

What it does not track is admission. A worker that answers a dispatch - even to
refuse it for capacity or because the request cannot be served - has proved the
transport works, so those outcomes settle the breaker as healthy rather than
counting toward the failure run that opens it. Feeding them in made a saturated
worker indistinguishable from an absent one, and one burst of backpressure then
rejected every run's control answers for the whole recovery window.
"""

from __future__ import annotations

import logging
import time

__all__ = ["WorkerCircuitBreaker"]

logger = logging.getLogger(__name__)


class WorkerCircuitBreaker:
    """Track worker transport health and reject requests when the worker is down.

    States:
    - CLOSED: dispatches flow normally.  Consecutive failures are counted.
    - OPEN: all dispatches are rejected.  After ``recovery_timeout``
      seconds, transitions to HALF_OPEN.
    - HALF_OPEN: exactly ONE probe dispatch is admitted, and no other dispatch
      is admitted until that probe settles.  Success closes the circuit; failure
      re-opens it.
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
        self._probe_in_flight = False

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
        """Reserve the right to dispatch, admitting one half-open probe at a time.

        Returns ``True`` if the dispatch may proceed, ``False`` if the caller
        should reject the request.  When ``False`` is returned the caller can use
        ``rejection_detail`` for the error message.

        A caller that receives ``True`` owns whatever it reserved and must settle
        it exactly once, through ``record_success``, ``record_failure``,
        ``record_refusal``, or ``release_probe`` on an abandoned attempt.
        """
        if self.state == "open":
            return False
        if self.state == "half_open":
            # The recovery window is over but the worker is still unproven. One
            # request tests it; admitting the rest would send the same flood
            # that opened the circuit at a worker that has answered nothing yet.
            if self._probe_in_flight:
                return False
            self._probe_in_flight = True
        return True

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
        self._close("dispatch succeeded")

    def record_refusal(self) -> None:
        """Record a dispatch the worker ANSWERED with a refusal.

        Capacity backpressure and semantic refusals are admission outcomes, not
        transport faults: the worker received the request and replied to it. That
        reply is the same evidence of a working transport a success carries, so
        it settles an in-flight probe and clears the consecutive-failure run,
        while the caller applies whatever retry policy the refusal deserves.
        """
        self._close("worker answered with a refusal")

    def record_failure(self) -> None:
        """Record a failed dispatch — may open the circuit."""
        self._probe_in_flight = False
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._failure_threshold:
            if self._state != "open":
                logger.warning(
                    "Worker circuit breaker OPEN after %d consecutive failures",
                    self._consecutive_failures,
                )
            self._state = "open"
            self._opened_at = time.monotonic()

    def release_probe(self) -> None:
        """Give back an admitted probe that settled no outcome.

        A dispatch abandoned before it produced either a reply or a transport
        error - cancelled, or failed in the caller - proved nothing about the
        worker. Without this the half-open state would hold a probe no one owns
        and admit nothing until the process restarted.
        """
        self._probe_in_flight = False

    def force_open(self) -> None:
        """Force the circuit open immediately (used by watchdog on crash)."""
        if self._state != "open":
            logger.warning("Worker circuit breaker forced OPEN by watchdog")
        self._probe_in_flight = False
        self._consecutive_failures = self._failure_threshold
        self._state = "open"
        self._opened_at = time.monotonic()

    def _close(self, reason: str) -> None:
        """Settle any in-flight probe and return the circuit to closed."""
        if self._state != "closed":
            logger.info("Worker circuit breaker CLOSED (%s)", reason)
        self._probe_in_flight = False
        self._consecutive_failures = 0
        self._state = "closed"
