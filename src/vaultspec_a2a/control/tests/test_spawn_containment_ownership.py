"""The spawn path must not leak its OS containment or strand its process.

The armed desktop gateway allocates a ``ProcessContainment`` - on Windows a real
job-object handle - before it spawns the worker, and hands it to the spawn. Three
of the spawn's exits returned without ever touching it: an owned worker adopted,
and the two port-conflict refusals. Adoption is not an error path - it fires
whenever an armed gateway restarts while its worker survives - so the leak was
one handle per dispatch, unbounded, with no circuit breaker in front of it.

These drive the real seams. Real loopback HTTP servers present real pairing
evidence, so the adoption and conflict verdicts are reached through the actual
classifier rather than asserted about. Real process trees with real grandchildren
cover the reap. The leak itself is measured with the process's real open-handle
count, which is what makes those tests discriminating: the return-value contract
alone goes green against the defect, because the caller already dropped its stale
reference - it was the handle behind that reference that leaked, not the
reference. On POSIX ``create`` allocates no OS object at all, which is asserted
rather than skipped, and the portable contract tests carry the invariant there.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from typing import TYPE_CHECKING

import pytest

from ...control.config import settings
from ...control.worker_management import (
    GATEWAY_LIFETIME_ID,
    LazyWorkerSpawner,
    _await_worker_ready,
    _spawn_worker_owned,
)
from ...utils.process import ProcessContainment
from .test_unready_worker_reap import _await_gone, _force_cleanup, _spawn_tree
from .test_worker_provenance import _worker_like

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

# Enough iterations that a one-handle-per-call leak is unmistakable against the
# ordinary churn of a loopback HTTP request (sockets, threads), and a tolerance
# well under one-per-iteration so the assertion cannot pass on a real leak.
_LEAK_ITERATIONS = 40
_LEAK_TOLERANCE = 10


@contextlib.contextmanager
def _armed_desktop(app_home: Path) -> Iterator[None]:
    """Arm the desktop profile for the duration of the block.

    ``desktop_profile_armed`` is a read-only property derived from
    ``desktop_app_home``, so arming means setting the field the property reads -
    a real attribute swap on the live settings object, restored on exit, which is
    the sanctioned seam used across this suite.
    """
    original = settings.desktop_app_home
    settings.desktop_app_home = app_home
    try:
        assert settings.desktop_profile_armed is True
        yield
    finally:
        settings.desktop_app_home = original


def _owned_body(generation: int) -> dict[str, object]:
    """A health body whose pairing evidence classifies as OWNED for *generation*."""
    return {
        "status": "ok",
        "service": "worker",
        "paired_gateway_lifetime": GATEWAY_LIFETIME_ID,
        "worker_generation": str(generation),
    }


def _foreign_body() -> dict[str, object]:
    """A health body from a worker another gateway process spawned."""
    return {
        "status": "ok",
        "service": "worker",
        "paired_gateway_lifetime": "0" * 32,
        "worker_generation": "1",
    }


def _open_handle_count() -> int:
    """Return this process's live OS handle count (Windows only).

    The direct measure of the leaked resource: a job object that is never closed
    is one more handle held by the gateway process for the rest of its life.
    """
    if sys.platform != "win32":
        raise RuntimeError("Windows handle counts are unavailable")
    import ctypes
    from ctypes import WinDLL, get_last_error, wintypes

    kernel32 = WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.GetProcessHandleCount.restype = wintypes.BOOL
    kernel32.GetProcessHandleCount.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
    )
    count = wintypes.DWORD()
    if not kernel32.GetProcessHandleCount(
        kernel32.GetCurrentProcess(), ctypes.byref(count)
    ):
        raise OSError(get_last_error())
    return int(count.value)


# ---------------------------------------------------------------------------
# The ownership contract, portable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_adopted_worker_hands_back_no_containment_to_own(
    tmp_path: Path,
) -> None:
    """The adoption exit: an owned worker is adopted and nothing is left to own.

    The spawn returns no process because the worker is already running, so the
    containment it was handed contains nothing. Handing it back would give the
    caller a handle with no tree - the stale reference the old caller had to
    remember to drop, and did, while the handle behind it stayed open.
    """
    with _worker_like(_owned_body(1)) as (url, port, _flag), _armed_desktop(tmp_path):
        process, containment = await _spawn_worker_owned(url, port, generation=1)

    assert process is None
    assert containment is None


@pytest.mark.asyncio
async def test_an_unevictable_occupant_hands_back_no_containment_to_own(
    tmp_path: Path,
) -> None:
    """The conflict exit: a foreign occupant refuses the spawn, and owns nothing.

    A worker paired to a different gateway lifetime classifies as FOREIGN, which
    authorizes neither adoption nor eviction, so the spawn refuses the port. The
    refusal must not cost a handle either - a port held by someone else is a
    standing condition, retried on every dispatch.
    """
    with _worker_like(_foreign_body()) as (url, port, _flag), _armed_desktop(tmp_path):
        process, containment = await _spawn_worker_owned(url, port, generation=1)

    assert process is None
    assert containment is None


def test_posix_containment_holds_no_handle_to_leak() -> None:
    """States the platform boundary the handle-count tests rely on.

    POSIX containment is a process group recorded at spawn, not an OS object held
    by this process, so there is nothing for the leak to accumulate. This is why
    the resource tests below are Windows-only - a bounded platform fact, asserted
    here rather than left as an unexplained gate.
    """
    containment = ProcessContainment.create()
    try:
        held = containment._job is not None
    finally:
        containment.close()
    assert held is (sys.platform == "win32")


# ---------------------------------------------------------------------------
# The leak itself
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="the containment holds an OS handle only on Windows; the POSIX "
    "boundary is asserted by test_posix_containment_holds_no_handle_to_leak",
)
@pytest.mark.asyncio
async def test_repeated_adoption_does_not_accumulate_job_handles(
    tmp_path: Path,
) -> None:
    """The defect, measured: adoption in a loop must not grow the handle count.

    An armed gateway that restarts while its worker survives takes this path on
    every dispatch. Each one allocated a job object and returned without closing
    it, so the count grew by one per call for the life of the process. The
    return-value assertions above pass against that defect; this one does not.
    """
    with _worker_like(_owned_body(1)) as (url, port, _flag), _armed_desktop(tmp_path):
        # Warm up first: the first calls through httpx and the loopback server
        # legitimately open connections and threads that persist.
        for _ in range(5):
            await _spawn_worker_owned(url, port, generation=1)

        before = _open_handle_count()
        for _ in range(_LEAK_ITERATIONS):
            await _spawn_worker_owned(url, port, generation=1)
        growth = _open_handle_count() - before

    assert growth <= _LEAK_TOLERANCE, (
        f"{_LEAK_ITERATIONS} adoptions grew the handle count by {growth}; "
        "the containment allocated for each spawn is not being released"
    )


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="the containment holds an OS handle only on Windows; the POSIX "
    "boundary is asserted by test_posix_containment_holds_no_handle_to_leak",
)
def test_replacing_the_worker_handle_releases_the_containment_it_drops() -> None:
    """The watchdog's handle slot has one owner, so a replaced handle is closed.

    ``replace_process`` is the only place the spawner's reference to a
    containment is dropped. The restart path reaches it after shutting the old
    worker down - but only when that worker was still running, and the commonest
    restart trigger is the opposite case, a worker that already exited. Its
    handle would otherwise be overwritten with nothing left to close it.
    """
    spawner = LazyWorkerSpawner(
        worker_url="http://127.0.0.1:9", worker_port=9, auto_spawn=False
    )
    try:
        for _ in range(5):
            spawner.replace_process(None, ProcessContainment.create())

        before = _open_handle_count()
        for _ in range(_LEAK_ITERATIONS):
            spawner.replace_process(None, ProcessContainment.create())
        growth = _open_handle_count() - before
    finally:
        spawner.replace_process(None)

    assert growth <= _LEAK_TOLERANCE, (
        f"{_LEAK_ITERATIONS} handle replacements grew the handle count by "
        f"{growth}; the outgoing containment is not being released"
    )


# ---------------------------------------------------------------------------
# The raised spawn
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_cancelled_readiness_wait_reaps_the_worker_tree(
    tmp_path: Path,
) -> None:
    """A raise past a live spawn must not strand it.

    Cancellation during the readiness wait is the realistic case - the gateway
    shuts down while a worker is starting. At that moment the process handle
    exists only in the frame being unwound, so nothing else can ever reach it:
    without a reap the worker and its descendants outlive the gateway holding the
    worker port, and the next spawn refuses that port as an unidentified
    occupant, wedging the band rather than merely leaking a process.

    The grandchildren are what make this discriminating - felling only the root
    would pass any parent-only assertion.
    """
    containment = ProcessContainment.create()
    process, child_pids = _spawn_tree(containment)
    try:
        task = asyncio.create_task(
            _await_worker_ready(
                process,
                containment,
                # Nothing answers here, so the wait stays in its poll loop.
                worker_url="http://127.0.0.1:9",
                worker_port=9,
                generation=1,
                worker_command=["python", "-c", "<stand-in worker>"],
                stderr_log_path=tmp_path / "worker.stderr.log",
            )
        )
        # Let the wait reach its first poll before cancelling it, so the
        # cancellation lands inside the region the guard covers.
        await asyncio.sleep(0.3)
        assert not task.done(), "the readiness wait returned before it was cancelled"
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert process.poll() is not None, (
            "the worker root outlived the cancelled readiness wait"
        )
        survivors = _await_gone(child_pids)
        assert not survivors, (
            f"worker descendants outlived the cancelled readiness wait: {survivors}"
        )
    finally:
        await _force_cleanup([process.pid, *child_pids])
