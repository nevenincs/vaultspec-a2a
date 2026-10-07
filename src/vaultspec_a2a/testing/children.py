"""Progress-based waits for real child processes.

A test that drives a real interpreter cannot bound it with a wall clock and
stay correct. The cost of starting one and importing this package spans two
orders of magnitude between an idle host and a loaded one - measured on the
development host at 0.1s idle and seconds under a concurrent suite - so any
fixed ``subprocess.run(timeout=...)`` is simultaneously too tight to survive
real load and too loose to catch a wedge promptly.

This module applies :mod:`vaultspec_a2a.testing.progress` to child processes:
a wait fails when the child STOPS MAKING PROGRESS, never because it was slow.
Progress is observed from the child TREE - accumulated CPU time and the count
of live members - plus whatever the caller can observe of the child's work (the
size of the file it writes). A child that keeps computing or keeps writing is
honestly slow and is never killed for it; one that does neither for a whole
idle window is wedged, and is reaped with a diagnostic naming what was last
seen. The per-item pytest-timeout backstop configured for the suite remains the
last-resort guard.

``measured_child_startup_s`` exists for the narrow cases where a real BOUND is
part of the proof. It measures what starting a child costs on this host right
now, so a budget derived from it is derived from the load the run is actually
under rather than from a number typed on an idle machine.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any, TypedDict, Unpack

import psutil

from ..utils import ProcessContainment, spawn_contained
from .progress import ProgressDeadline, ProgressStalledError
from .session_root import session_scratch_dir

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Mapping
    from pathlib import Path

__all__ = [
    "DEFAULT_IDLE_WINDOW_S",
    "await_child",
    "child_tree_progress",
    "file_size_fingerprint",
    "measured_child_startup_s",
    "reap_contained",
    "run_child",
]

#: The default silence a child is granted before it is judged wedged. Sized for
#: the worst observed pause of a live child on a loaded host (an import storm
#: behind a contended filesystem), not for the common case: the cost of being
#: too short is a false failure, and the cost of being too long is latency on a
#: genuine hang only.
DEFAULT_IDLE_WINDOW_S = 90.0

_POLL_INTERVAL_S = 0.25
# The probe is deliberately the CHEAPEST representative child: an interpreter
# start plus one package import that reaches no heavy dependency (harness_names
# is spelled to be importable without the settings stack). It measures how
# expensive starting a child is on this host right now - which is the quantity
# every derived budget scales with - and not how large some particular import
# graph happens to be.
_STARTUP_PROBE = "import vaultspec_a2a.testing.harness_names"

_measured_startup_s: float | None = None


def child_tree_progress(pid: int) -> tuple[float, int]:
    """Return *pid*'s tree CPU seconds and live member count.

    Both halves are progress signals. CPU time advances while the tree computes;
    the member count changes when it spawns or reaps. A tree doing neither for a
    whole idle window has stopped working, whatever it reports about itself. A
    vanished process reports ``(0.0, 0)`` rather than raising: the caller's own
    exit observation, not this, decides that a wait is over.
    """
    try:
        root = psutil.Process(pid)
        members = [root, *root.children(recursive=True)]
    except (psutil.Error, OSError):
        return (0.0, 0)
    total = 0.0
    live = 0
    for member in members:
        try:
            times = member.cpu_times()
        except (psutil.Error, OSError):
            continue
        total += times.user + times.system
        live += 1
    return (round(total, 2), live)


def measured_child_startup_s() -> float:
    """This host's current cost of starting one child interpreter.

    Measured once per process, on first demand, so the figure reflects the load
    the calling run is actually under rather than the machine at rest. Callers
    that genuinely need a BOUND derive one from this instead of from a literal:
    a budget written as a multiple of the measured cost keeps its meaning on an
    idle host and on a contended one.
    """
    global _measured_startup_s
    if _measured_startup_s is None:
        command = [sys.executable, "-c", _STARTUP_PROBE]
        containment = ProcessContainment.create()
        started = time.monotonic()
        probe = spawn_contained(
            command, containment, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        try:
            stdout, stderr = probe.communicate()
            elapsed = time.monotonic() - started
        finally:
            reap_contained(probe, containment)
        if probe.returncode != 0:
            raise subprocess.CalledProcessError(
                probe.returncode, command, stdout, stderr
            )
        _measured_startup_s = max(elapsed, 0.01)
    return _measured_startup_s


class ChildWatch(TypedDict, total=False):
    """How a wait watches one child for progress.

    Declared once so the wait and every call site name the same knobs, and so
    adding a fifth is one edit rather than two.

    *fingerprint* adds a caller-observable progress signal - typically the
    size of the file the child writes - to the tree's own CPU and membership
    signals. *diagnostic* supplies the context a stall report should carry,
    such as the output captured so far. *ceiling_s* is for a child that polls:
    a poll loop burns CPU forever, so CPU alone never calls it stalled; derive
    it from :func:`measured_child_startup_s`, never from a literal.
    """

    idle_window_s: float
    fingerprint: Callable[[], object] | None
    diagnostic: Callable[[], str] | None
    ceiling_s: float | None


def await_child(
    process: subprocess.Popen[bytes],
    containment: ProcessContainment,
    *,
    what: str,
    **watch: Unpack[ChildWatch],
) -> int:
    """Wait for *process* to exit, failing on a stall and never on slowness.

    *process* was started inside *containment* by
    :func:`~vaultspec_a2a.utils.spawn_contained`. *what* names the child in a
    failure; :class:`ChildWatch` documents what else the wait can be told to
    watch. A wedged child is REAPED through its containment, tree and all,
    before :class:`~.progress.ProgressStalledError` is raised, so a failed wait
    never leaves a process holding its ports, its handles, and its share of the
    machine.
    """
    fingerprint = watch.get("fingerprint")
    diagnostic = watch.get("diagnostic")
    ceiling_s = watch.get("ceiling_s")
    deadline = ProgressDeadline(
        idle_window_s=watch.get("idle_window_s", DEFAULT_IDLE_WINDOW_S)
    )
    started = time.monotonic()
    observed: object = None
    while True:
        returncode = process.poll()
        if returncode is not None:
            return returncode
        current = (
            child_tree_progress(process.pid),
            None if fingerprint is None else fingerprint(),
        )
        if current != observed:
            observed = current
            deadline.touch()
        try:
            deadline.check()
            if ceiling_s is not None and time.monotonic() - started > ceiling_s:
                msg = f"still running after its {ceiling_s:.0f}s ceiling"
                raise ProgressStalledError(msg)
        except ProgressStalledError as stalled:
            reaped = reap_contained(process, containment)
            context = "" if diagnostic is None else f"\n{diagnostic()}"
            unreaped = "" if reaped else " (its contained tree was not reaped)"
            raise ProgressStalledError(
                f"{what} (pid {process.pid}) made no progress: "
                f"{stalled}{unreaped}{context}"
            ) from stalled
        time.sleep(_POLL_INTERVAL_S)


def reap_contained(
    process: subprocess.Popen[Any],
    containment: ProcessContainment,
    *,
    term_timeout: float = 10.0,
    kill_timeout: float = 5.0,
) -> bool:
    """Reap *process*'s whole tree through *containment*, from any calling context.

    *process* was started inside *containment* by
    :func:`~vaultspec_a2a.utils.spawn_contained`, which held every descendant
    from the root's first instruction, so a root that already exited is no
    obstacle: what it left running is still reaped, and no kill is ever aimed at
    a recycled pid. The root's handle is then waited on. *term_timeout* and
    *kill_timeout* are the graceful and forced phases. Returns ``True`` once the
    tree is gone and the root reaped; a repeat call after that is a no-op.

    Called from a test that is itself running an event loop, ``asyncio.run``
    would refuse and leave the tree alive, so the reap then runs on a thread
    with a loop of its own.
    """

    def _terminate() -> bool:
        return asyncio.run(
            containment.terminate(term_timeout=term_timeout, kill_timeout=kill_timeout)
        )

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        reaped = _terminate()
    else:
        with ThreadPoolExecutor(max_workers=1) as reaper:
            reaped = reaper.submit(_terminate).result()
    try:
        process.wait(timeout=kill_timeout)
    except subprocess.TimeoutExpired:
        return False
    return reaped


def file_size_fingerprint(*paths: os.PathLike[str] | str) -> Callable[[], object]:
    """A progress fingerprint over the sizes of the files a child writes."""

    def _sizes() -> object:
        sizes: list[int] = []
        for path in paths:
            try:
                sizes.append(os.stat(path).st_size)
            except OSError:
                sizes.append(-1)
        return tuple(sizes)

    return _sizes


@contextlib.contextmanager
def _capture_dir() -> Generator[Path]:
    """A scratch seat for one child's captured output, removed afterwards."""
    capture = session_scratch_dir("child-output-")
    try:
        yield capture
    finally:
        # The files delete themselves; the directory that held them does not.
        with contextlib.suppress(OSError):
            capture.rmdir()


def run_child(
    command: list[str],
    *,
    what: str,
    idle_window_s: float = DEFAULT_IDLE_WINDOW_S,
    env: Mapping[str, str] | None = None,
    cwd: os.PathLike[str] | str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run *command* to completion under :func:`await_child`, capturing text.

    The captured-output equivalent of ``subprocess.run(..., capture_output=True,
    text=True)`` with a progress-based wait in place of a wall-clock timeout.
    Output is captured to temporary FILES rather than pipes, for two reasons: a
    child that fills a pipe buffer would wedge behind a reader this wait does
    not run, and a file's growing size is the caller-observable progress signal
    the wait reads. The files land in this session's own scratch seat inside the
    worktree, never in the system temporary directory. The child runs inside its
    own containment, whose whole tree is reaped once the child exits, so nothing
    it left running outlives the call.
    """
    with (
        _capture_dir() as capture,
        tempfile.TemporaryFile(dir=capture) as out,
        tempfile.TemporaryFile(dir=capture) as err,
    ):
        containment = ProcessContainment.create()
        process = spawn_contained(
            command,
            containment,
            stdout=out,
            stderr=err,
            env=None if env is None else dict(env),
            cwd=cwd,
        )

        def _written() -> object:
            return (
                os.fstat(out.fileno()).st_size,
                os.fstat(err.fileno()).st_size,
            )

        try:
            returncode = await_child(
                process,
                containment,
                what=what,
                idle_window_s=idle_window_s,
                fingerprint=_written,
            )
        finally:
            reap_contained(process, containment)
        out.seek(0)
        err.seek(0)
        return subprocess.CompletedProcess(
            command,
            returncode,
            out.read().decode("utf-8", errors="replace"),
            err.read().decode("utf-8", errors="replace"),
        )
