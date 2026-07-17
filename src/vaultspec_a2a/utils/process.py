"""Async process-tree termination, platform-aware and dependency-free.

The single async "kill this pid and its whole tree" escalation shared by the
worker-management shutdown and the ACP subprocess reaper. It works by PID (never a
process handle), so a ``subprocess.Popen`` caller and an
``asyncio.subprocess.Process`` caller both use it and each keeps its own final
wait/reap bookkeeping.

Windows fells the whole tree with ``taskkill /T /F`` because a bare
``terminate()`` only kills the immediate process and orphans grandchildren
(node.exe under a cmd.exe shim, an engine a worker spawned). POSIX escalates
``SIGTERM`` then ``SIGKILL``. This module imports nothing from the rest of the
package by design, so any layer can depend on it without an import cycle.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys

__all__ = ["kill_pid_tree_async"]

_POLL_INTERVAL = 0.1


def _pid_alive(pid: int) -> bool:
    """Whether *pid* is still a live process (POSIX ``signal-0`` probe)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


async def _await_pid_gone(pid: int, *, timeout: float) -> bool:
    """Poll until *pid* is gone or *timeout* elapses; return whether it is gone."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if not _pid_alive(pid):
            return True
        await asyncio.sleep(_POLL_INTERVAL)
    return not _pid_alive(pid)


async def _win_tree_kill(pid: int, *, timeout: float) -> bool:
    try:
        killer = await asyncio.create_subprocess_exec(
            "taskkill",
            "/T",
            "/F",
            "/PID",
            str(pid),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError:
        return False
    # ``taskkill /F`` is authoritative; bound the wait so a wedged taskkill cannot
    # hang the caller. The caller's own handle wait confirms the reap.
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(killer.wait(), timeout=timeout)
    return True


async def kill_pid_tree_async(
    pid: int, *, term_timeout: float = 10.0, kill_timeout: float = 5.0
) -> bool:
    """Kill *pid* and its process tree; return ``True`` once it is gone.

    Windows uses ``taskkill /T /F /PID`` (whole-tree force kill). POSIX sends
    ``SIGTERM``, waits up to *term_timeout* for the process to exit, then escalates
    to ``SIGKILL`` and waits up to *kill_timeout*. A pid that is already gone (or a
    non-positive pid) is a success. The caller keeps its own handle wait/reap after
    this returns.
    """
    if pid <= 0:
        return True
    if sys.platform == "win32":
        return await _win_tree_kill(pid, timeout=term_timeout + kill_timeout)
    # POSIX escalation, kept under the platform guard so the type checker narrows
    # ``signal`` to its POSIX members (``SIGKILL`` is absent on Windows).
    import signal

    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.kill(pid, signal.SIGTERM)
    if await _await_pid_gone(pid, timeout=term_timeout):
        return True
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.kill(pid, signal.SIGKILL)
    return await _await_pid_gone(pid, timeout=kill_timeout)
