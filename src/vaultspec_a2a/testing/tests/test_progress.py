"""Progress deadlines against real child processes and real registry records."""

from __future__ import annotations

import asyncio
import os
import sys
import time
from itertools import count
from typing import TYPE_CHECKING

import pytest

from ...lifecycle import ProcRecord, now_ms, write_record
from ...utils import ProcessContainment, reap_contained, spawn_contained
from ..progress import (
    ProgressDeadline,
    ProgressStalledError,
    ResourceDiedError,
    registry_watch,
    wait_for,
    wait_until,
    wait_until_async,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_stall_trips_after_the_idle_window() -> None:
    deadline = ProgressDeadline(idle_window_s=0.2)
    time.sleep(0.3)
    with pytest.raises(ProgressStalledError, match="no progress observed"):
        deadline.check()


def test_touch_defers_the_stall() -> None:
    deadline = ProgressDeadline(idle_window_s=0.3)
    time.sleep(0.2)
    deadline.touch()
    time.sleep(0.2)
    deadline.check()


def test_dead_owner_pid_trips_immediately(tmp_path: Path) -> None:
    """A watched record whose pid dies fails the wait at the next check."""
    containment = ProcessContainment.create()
    child = spawn_contained(
        [sys.executable, "-c", "import time; time.sleep(600)"], containment
    )
    try:
        record = ProcRecord(
            name="watched",
            role="scratch",
            pid=child.pid,
            port=0,
            last_seen_ms=now_ms(),
        )
        write_record(record, home=tmp_path)
        deadline = ProgressDeadline(
            idle_window_s=600.0,
            watches=(registry_watch("scratch", "watched", home=tmp_path),),
        )
        deadline.check()
    finally:
        reap_contained(child, containment)
    with pytest.raises(ResourceDiedError, match="dead"):
        deadline.check()


def test_frozen_heartbeat_trips_despite_a_live_pid(tmp_path: Path) -> None:
    """A heartbeating role with an ancient last_seen is a death, not a wait.

    The pid is this very test process - maximally alive - so the failure can
    only come from the heartbeat signal, per the engine precedent that a live
    process with a dead heartbeat writer must not be trusted.
    """
    record = ProcRecord(
        name="stale",
        role="gateway-dev",
        pid=os.getpid(),
        port=0,
        last_seen_ms=now_ms() - 3_600_000,
    )
    write_record(record, home=tmp_path)
    deadline = ProgressDeadline(
        idle_window_s=600.0,
        watches=(registry_watch("gateway-dev", "stale", home=tmp_path),),
    )
    with pytest.raises(ResourceDiedError, match="froze"):
        deadline.check()


def test_missing_record_is_a_death(tmp_path: Path) -> None:
    deadline = ProgressDeadline(
        idle_window_s=600.0, watches=(registry_watch("scratch", "gone", home=tmp_path),)
    )
    with pytest.raises(ResourceDiedError, match="gone"):
        deadline.check()


def test_wait_for_outlives_the_idle_window_while_progressing() -> None:
    """A slow consumer that keeps changing state is never killed for slowness.

    The wait's total duration deliberately exceeds the idle window several
    times over; only the per-iteration fingerprint change keeps it alive.
    """
    iterations = count()

    def poll() -> str | None:
        return "done" if next(iterations) >= 8 else None

    observed = count()
    deadline = ProgressDeadline(idle_window_s=0.2)
    result = wait_for(
        poll,
        deadline=deadline,
        fingerprint=lambda: next(observed),
        interval_s=0.1,
    )
    assert result == "done"


def test_wait_for_stalls_when_the_fingerprint_freezes() -> None:
    deadline = ProgressDeadline(idle_window_s=0.3)

    def never() -> str | None:
        return None

    with pytest.raises(ProgressStalledError):
        wait_for(
            never, deadline=deadline, fingerprint=lambda: "frozen", interval_s=0.05
        )


def test_stall_message_leads_with_what_the_wait_named_at_the_stall() -> None:
    """The text is read when the wait stalls, so it can carry the last value seen."""
    polls = count(1)
    last_seen = 0

    def never() -> str | None:
        nonlocal last_seen
        last_seen = next(polls)
        return None

    with pytest.raises(
        ProgressStalledError, match=r"^polled \d+ times: no progress observed"
    ) as stalled:
        wait_for(
            never,
            deadline=ProgressDeadline(idle_window_s=0.2),
            interval_s=0.05,
            stalled=lambda: f"polled {last_seen} times",
        )
    assert f"polled {last_seen} times:" in str(stalled.value)


def test_wait_until_returns_once_the_condition_holds() -> None:
    polls = count()
    wait_until(
        lambda: next(polls) >= 3,
        deadline=ProgressDeadline(idle_window_s=5.0),
        interval_s=0.01,
    )
    assert next(polls) >= 4


def test_wait_until_stall_names_what_it_waited_for() -> None:
    with pytest.raises(ProgressStalledError, match="the flag never rose: no progress"):
        wait_until(
            lambda: False,
            deadline=ProgressDeadline(idle_window_s=0.2),
            interval_s=0.05,
            stalled=lambda: "the flag never rose",
        )


@pytest.mark.asyncio
async def test_wait_until_async_yields_to_the_task_that_changes_the_state() -> None:
    flag = asyncio.Event()
    setter = asyncio.get_running_loop().call_later(0.05, flag.set)
    try:
        await wait_until_async(
            flag.is_set,
            deadline=ProgressDeadline(idle_window_s=5.0),
            interval_s=0.01,
        )
    finally:
        setter.cancel()
    assert flag.is_set()


@pytest.mark.asyncio
async def test_wait_until_async_stall_names_what_it_waited_for() -> None:
    with pytest.raises(ProgressStalledError, match="the flag never rose: no progress"):
        await wait_until_async(
            lambda: False,
            deadline=ProgressDeadline(idle_window_s=0.2),
            interval_s=0.05,
            stalled=lambda: "the flag never rose",
        )
