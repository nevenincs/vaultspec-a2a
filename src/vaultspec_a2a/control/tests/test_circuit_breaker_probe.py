"""The breaker admits one recovery probe and counts only transport health.

Pure logic against the real class: no worker is involved because the questions
here are what the breaker counts and how many callers it lets past while the
worker is unproven.
"""

from __future__ import annotations

import time

from ..circuit_breaker import WorkerCircuitBreaker


def _open_breaker() -> WorkerCircuitBreaker:
    """Return a breaker that is already open and immediately eligible to probe."""
    breaker = WorkerCircuitBreaker(failure_threshold=2, recovery_timeout=0.0)
    breaker.force_open()
    return breaker


def test_half_open_admits_one_caller_until_the_probe_settles() -> None:
    """The recovery window ends the wait, not the caution."""
    breaker = _open_breaker()
    assert breaker.state == "half_open"

    assert breaker.pre_dispatch() is True
    assert breaker.pre_dispatch() is False
    assert breaker.pre_dispatch() is False


def test_a_successful_probe_reopens_the_circuit_to_everyone() -> None:
    breaker = _open_breaker()
    assert breaker.pre_dispatch() is True

    breaker.record_success()

    assert breaker.state == "closed"
    assert breaker.pre_dispatch() is True
    assert breaker.pre_dispatch() is True


def test_a_failed_probe_shuts_the_circuit_again() -> None:
    """A real recovery window, waited out for real, then closed again by failure."""
    breaker = WorkerCircuitBreaker(failure_threshold=2, recovery_timeout=0.2)
    breaker.force_open()
    assert breaker.state == "open"

    time.sleep(0.25)
    assert breaker.state == "half_open"
    assert breaker.pre_dispatch() is True

    breaker.record_failure()

    assert breaker.state == "open"
    assert breaker.pre_dispatch() is False


def test_an_answered_refusal_settles_the_probe_without_counting_a_failure() -> None:
    """A worker that replies has proved the transport, whatever the reply said."""
    breaker = _open_breaker()
    assert breaker.pre_dispatch() is True

    breaker.record_refusal()

    assert breaker.state == "closed"
    assert breaker.pre_dispatch() is True


def test_refusals_never_accumulate_toward_opening_the_circuit() -> None:
    """Backpressure is not evidence of a broken worker, however much of it there is."""
    breaker = WorkerCircuitBreaker(failure_threshold=2, recovery_timeout=30.0)

    for _ in range(10):
        assert breaker.pre_dispatch() is True
        breaker.record_refusal()

    assert breaker.state == "closed"


def test_a_refusal_between_failures_breaks_the_consecutive_run() -> None:
    """The threshold counts CONSECUTIVE failures, and an answer interrupts them."""
    breaker = WorkerCircuitBreaker(failure_threshold=2, recovery_timeout=30.0)

    breaker.record_failure()
    breaker.record_refusal()
    breaker.record_failure()

    assert breaker.state == "closed"


def test_an_abandoned_probe_is_returned_rather_than_held() -> None:
    """A dispatch that settled nothing must not strand the recovery slot."""
    breaker = _open_breaker()
    assert breaker.pre_dispatch() is True
    assert breaker.pre_dispatch() is False

    breaker.release_probe()

    assert breaker.pre_dispatch() is True


def test_forcing_the_circuit_open_reclaims_an_in_flight_probe() -> None:
    breaker = WorkerCircuitBreaker(failure_threshold=2, recovery_timeout=0.0)
    breaker.force_open()
    assert breaker.pre_dispatch() is True

    breaker.force_open()

    assert breaker.state == "half_open"
    assert breaker.pre_dispatch() is True
