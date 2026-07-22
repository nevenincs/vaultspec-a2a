"""The independent cleanup runner isolates and aggregates release failures.

Real callables only - no mocks. Each cleanup step records its own real side
effect (a flag flip, a file removal), so a step running or not running is an
observable fact rather than a stubbed call count.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from .._cleanup import run_independent_cleanups

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
async def test_every_step_runs_even_when_an_earlier_step_raises() -> None:
    """A failing cleanup step must not skip the steps after it."""
    ran: list[str] = []

    def _ok_first() -> None:
        ran.append("first")

    def _boom() -> None:
        ran.append("boom")
        raise RuntimeError("release failed")

    async def _ok_last() -> None:
        ran.append("last")

    failures = await run_independent_cleanups(
        ("first", _ok_first),
        ("boom", _boom),
        ("last", _ok_last),
    )

    # All three steps ran despite the middle one raising.
    assert ran == ["first", "boom", "last"]
    # The failure is collected under its step name, not swallowed silently.
    assert [name for name, _ in failures] == ["boom"]
    assert isinstance(failures[0][1], RuntimeError)


@pytest.mark.asyncio
async def test_a_real_file_removal_still_runs_after_a_prior_failure(
    tmp_path: Path,
) -> None:
    """The concrete hazard: a failed release must not strand a real resource.

    A failing first step (the analogue of a process-tree kill that raises) must
    not skip removing a real on-disk credential-home analogue.
    """
    home = tmp_path / "config-home"
    home.mkdir()
    (home / "credential.json").write_text("secret", encoding="utf-8")

    def _kill_raises() -> None:
        raise OSError("kill failed")

    def _remove_home() -> None:
        for child in home.iterdir():
            child.unlink()
        home.rmdir()

    failures = await run_independent_cleanups(
        ("kill", _kill_raises),
        ("remove-home", _remove_home),
    )

    # The credential home was removed even though the kill step failed.
    assert not home.exists()
    assert [name for name, _ in failures] == ["kill"]


@pytest.mark.asyncio
async def test_no_failures_returns_empty_and_awaits_async_steps() -> None:
    ran: list[str] = []

    async def _async_step() -> None:
        await asyncio.sleep(0)
        ran.append("async")

    failures = await run_independent_cleanups(
        ("sync", lambda: ran.append("sync")),
        ("async", _async_step),
    )

    assert ran == ["sync", "async"]
    assert failures == []


@pytest.mark.asyncio
async def test_cancellation_is_not_swallowed_by_a_cleanup_step() -> None:
    """A BaseException such as CancelledError propagates, not aggregated."""

    def _cancel() -> None:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await run_independent_cleanups(("cancel", _cancel))
