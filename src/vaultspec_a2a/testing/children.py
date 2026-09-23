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
from typing import TYPE_CHECKING

import psutil

from .progress import ProgressDeadline, ProgressStalledError
from .session_root import session_scratch_dir

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

__all__ = [
    "DEFAULT_IDLE_WINDOW_S",
    "await_child",
    "child_tree_progress",
    "file_size_fingerprint",
    "measured_child_startup_s",
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
        started = time.monotonic()
        subprocess.run(
            [sys.executable, "-c", _STARTUP_PROBE], check=True, capture_output=True
        )
        _measured_startup_s = max(time.monotonic() - started, 0.01)
    return _measured_startup_s


def await_child(
    process: subprocess.Popen[bytes],
    *,
    what: str,
    idle_window_s: float = DEFAULT_IDLE_WINDOW_S,
    fingerprint: Callable[[], object] | None = None,
    diagnostic: Callable[[], str] | None = None,
) -> int:
    """Wait for *process* to exit, failing on a stall and never on slowness.

    *what* names the child in a failure. *fingerprint* adds a caller-observable
    progress signal - typically the size of the file the child writes - to the
    tree's own CPU and membership signals; *diagnostic* supplies the context a
    stall report should carry, such as the output captured so far. A wedged
    child is REAPED as a tree before :class:`~.progress.ProgressStalledError` is
    raised, so a failed wait never leaves a process holding its ports, its
    handles, and its share of the machine.
    """
    deadline = ProgressDeadline(idle_window_s=idle_window_s)
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
        except ProgressStalledError as stalled:
            from ..utils import kill_pid_tree_async

            asyncio.run(kill_pid_tree_async(process.pid))
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=5.0)
            context = "" if diagnostic is None else f"\n{diagnostic()}"
            raise ProgressStalledError(
                f"{what} (pid {process.pid}) made no progress: {stalled}{context}"
            ) from stalled
        time.sleep(_POLL_INTERVAL_S)


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
    worktree, never in the system temporary directory.
    """
    capture = session_scratch_dir("child-output-")
    try:
        return _run_captured(
            command, capture, what=what, idle_window_s=idle_window_s, env=env, cwd=cwd
        )
    finally:
        # The files delete themselves; the directory that held them does not.
        with contextlib.suppress(OSError):
            capture.rmdir()


def _run_captured(
    command: list[str],
    capture: Path,
    *,
    what: str,
    idle_window_s: float,
    env: Mapping[str, str] | None,
    cwd: os.PathLike[str] | str | None,
) -> subprocess.CompletedProcess[str]:
    """Run *command* with its output captured into files under *capture*."""
    with (
        tempfile.TemporaryFile(dir=capture) as out,
        tempfile.TemporaryFile(dir=capture) as err,
    ):
        process = subprocess.Popen(
            command,
            stdout=out,
            stderr=err,
            env=None if env is None else dict(env),
            cwd=cwd,
        )

        def _written() -> object:
            return (os.fstat(out.fileno()).st_size, os.fstat(err.fileno()).st_size)

        returncode = await_child(
            process, what=what, idle_window_s=idle_window_s, fingerprint=_written
        )
        out.seek(0)
        err.seek(0)
        return subprocess.CompletedProcess(
            command,
            returncode,
            out.read().decode("utf-8", errors="replace"),
            err.read().decode("utf-8", errors="replace"),
        )
