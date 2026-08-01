"""A failing watchdog tick must not end the watchdog, or end it silently.

``run`` guarded only ``asyncio.CancelledError``, so the first tick to raise ended
the supervisor for the life of the gateway. The spawn a recovery performs is the
most likely thing in a tick to raise, which made the failure mode circular: the
watchdog died precisely when it was needed, leaving the worker unsupervised with
the circuit breaker held open by the cycle that died. Nothing observed the task -
the lifespan creates it and never looks at it again until shutdown, where
``gather(..., return_exceptions=True)`` discards the stored exception - so the
gateway went on reporting a supervised worker it was no longer supervising.

Real objects throughout: a real breaker, a real spawner, a real state machine,
and a real HTTP probe against a dead port. The fault is injected the way
production would suffer it, by putting a value of the wrong type on the shared
app state the heartbeat route writes - ``_heartbeat_stale`` then raises a genuine
``TypeError`` inside the real tick, rather than a tick being replaced by
something that raises.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import subprocess
import sys
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from ...control.circuit_breaker import WorkerCircuitBreaker
from ...control.config import settings
from ...control.worker_management import (
    LazyWorkerSpawner,
    WorkerState,
    WorkerWatchdog,
)
from ...tests.gateway_boot import free_port

if TYPE_CHECKING:
    from collections.abc import Iterator

_POLL = 0.05
"""A poll interval short enough that several ticks fit in a test's patience."""


_LOGGER_NAME = "vaultspec_a2a.control.worker_management"


class _Collector(logging.Handler):
    """A real handler that keeps the records the watchdog emits."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextlib.contextmanager
def _captured() -> Iterator[list[logging.LogRecord]]:
    """Collect the watchdog's own log records, attached to its own logger.

    Attached directly rather than through ``caplog`` so the assertion is about
    what this module's logger emitted, not about what survived the root handler
    configuration a test session happens to be running under.
    """
    logger = logging.getLogger(_LOGGER_NAME)
    handler = _Collector()
    original_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        yield handler.records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(original_level)


@contextlib.contextmanager
def _fast_polling() -> Iterator[None]:
    """Shorten the watchdog poll interval; a real attribute swap, restored after."""
    original = settings.watchdog_poll_interval_seconds
    settings.watchdog_poll_interval_seconds = _POLL
    try:
        yield
    finally:
        settings.watchdog_poll_interval_seconds = original


def _unsupervised_watchdog(
    heartbeat_ts: object,
) -> tuple[WorkerWatchdog, WorkerState, SimpleNamespace]:
    """A watchdog over an adopted worker on a dead port, with *heartbeat_ts* on state.

    ``auto_spawn=False`` with an adopted (process-less) worker is the shape that
    reconciles purely from the HTTP probe, so a tick that survives is observable
    as a status transition without any process being spawned.
    """
    port = free_port()
    spawner = LazyWorkerSpawner(
        worker_url=f"http://127.0.0.1:{port}", worker_port=port, auto_spawn=False
    )
    # The real production method that marks an adopted worker: spawned, no handle.
    spawner.replace_process(None)
    worker_state = WorkerState()
    breaker = WorkerCircuitBreaker(failure_threshold=3, recovery_timeout=30)
    app_state = SimpleNamespace(worker_last_heartbeat_ts=heartbeat_ts)
    watchdog = WorkerWatchdog(spawner, breaker, worker_state, app_state)
    return watchdog, worker_state, app_state


async def _await_record(
    records: list[logging.LogRecord], needle: str, *, timeout: float
) -> list[logging.LogRecord]:
    """Wait for the watchdog to log *needle*, returning every matching record.

    Waiting on the watchdog's own output rather than on a fixed sleep: the first
    health probe against a dead port costs more than a poll interval, so a timed
    window can expire before a single tick has run and assert about nothing.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        matched = [r for r in records if needle in r.getMessage()]
        if matched:
            return matched
        await asyncio.sleep(_POLL / 2)
    return []


async def _await_status(state: WorkerState, expected: str, *, timeout: float) -> bool:
    """Wait for the watchdog to reconcile *state* to *expected*."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if state.worker_status == expected:
            return True
        await asyncio.sleep(_POLL / 2)
    return False


@pytest.mark.asyncio
async def test_a_raising_tick_does_not_end_the_watchdog() -> None:
    """The defect: one raising tick used to be the last tick.

    A wrong-typed heartbeat makes every tick raise before it can reconcile
    anything, so the status stays where the constructor left it. Repairing the
    state mid-flight is the discriminating step - only a watchdog that is still
    polling can notice, so the later transition proves the loop outlived the
    failures rather than merely that the task object still exists.
    """
    watchdog, worker_state, app_state = _unsupervised_watchdog("not-a-timestamp")

    with _captured() as records, _fast_polling():
        task = asyncio.create_task(watchdog.run())
        try:
            # Wait for a tick to actually fail before asserting anything about
            # what surviving one means.
            failures = await _await_record(
                records, "watchdog tick failed", timeout=15.0
            )
            assert failures, "no tick raised, so this test proved nothing"
            assert not task.done(), "the watchdog ended on a raising tick"
            assert worker_state.worker_status == "pending", (
                "a tick reconciled status despite raising"
            )

            # Repair the fault. A live watchdog reconciles on its next poll.
            app_state.worker_last_heartbeat_ts = None
            reconciled = await _await_status(worker_state, "down", timeout=15.0)
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    assert reconciled, (
        "the watchdog never reconciled after the fault cleared; it stopped "
        "polling when a tick raised"
    )
    assert all(r.levelno >= logging.ERROR for r in failures), (
        "a dead-supervisor signal was logged below ERROR"
    )
    assert any(r.exc_info is not None for r in failures), (
        "the tick failure was logged without its traceback, leaving nothing to "
        "diagnose it from"
    )


@pytest.mark.asyncio
async def test_cancellation_remains_the_quiet_way_to_stop_the_watchdog() -> None:
    """Shutdown must stay silent: cancellation is expected, not a failure.

    The widened guard must not turn the ordinary shutdown path into a critical
    log, or the signal that a watchdog really died would be worthless.
    """
    watchdog, worker_state, _app_state = _unsupervised_watchdog(None)

    with _fast_polling():
        task = asyncio.create_task(watchdog.run())
        assert await _await_status(worker_state, "down", timeout=3.0), (
            "the watchdog never ran a healthy tick"
        )
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    assert task.done()


@pytest.mark.asyncio
async def test_a_restart_cycle_that_raises_still_stamps_the_cooldown() -> None:
    """A raising cycle must leave a cooldown stamp, or containment becomes a spin.

    Keeping the loop alive across a raising tick is only safe if a persistently
    failing recovery is still rate-limited. The stamp used to be written after
    the restart returned, so a cycle that raised skipped it and the gate saw no
    prior cycle - the next poll would retry at the poll interval instead of the
    cooldown. Here a real restart cycle is entered against a real crashed worker
    and cancelled during its real backoff sleep, which is the shutdown-mid-restart
    case as well as the general raise.
    """
    crashed = subprocess.Popen([sys.executable, "-c", "raise SystemExit(3)"])
    crashed.wait(timeout=30)
    port = free_port()
    spawner = LazyWorkerSpawner(
        worker_url=f"http://127.0.0.1:{port}", worker_port=port, auto_spawn=True
    )
    # An owned worker that has already exited: the commonest restart trigger.
    spawner.replace_process(crashed)
    worker_state = WorkerState()
    breaker = WorkerCircuitBreaker(failure_threshold=3, recovery_timeout=30)
    watchdog = WorkerWatchdog(
        spawner, breaker, worker_state, SimpleNamespace(worker_last_heartbeat_ts=None)
    )
    assert watchdog._restart_cooldown_elapsed() is True, (
        "a watchdog that has never restarted should not be gated"
    )

    with _fast_polling():
        task = asyncio.create_task(watchdog.run())
        # The tick detects the crash and enters the restart cycle, which opens
        # with a backoff sleep far longer than this wait - so cancelling below
        # lands inside the cycle rather than after it.
        entered = await _await_status(worker_state, "restarting", timeout=5.0)
        assert entered, "the watchdog never entered a restart cycle"
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    assert watchdog._last_restart_cycle_ts is not None, (
        "a restart cycle that raised left no cooldown stamp; the next poll would "
        "retry immediately instead of waiting out the cooldown"
    )
    assert watchdog._restart_cooldown_elapsed() is False, (
        "the stamp did not actually engage the inter-cycle cooldown gate"
    )
