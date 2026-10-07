"""Process introspection, loopback port probes and detached process-tree kills.

Every "is this pid alive", "wait until these pids are gone", "which processes
descend from this one", "how much CPU has this tree used", "when did this
process start" and "is something listening on this loopback port, and is it
ours" question in the package is answered here, each in a blocking and an
event-loop form where callers need both.
This is the only module that inspects processes, and psutil is its one backend:
it covers every supported host, reads a zombie as the exited process it is, and
walks descendants with a guard against a reused parent pid. The start identity is
the one read psutil does not serve (see :func:`process_start_identity`).

The single async "kill this pid and its whole tree" escalation is for detached
processes, which have no containment; an owned tree is reaped through its
:class:`~vaultspec_a2a.utils.process.ProcessContainment` instead. It works by PID
(never a process handle), so a ``subprocess.Popen`` caller and an
``asyncio.subprocess.Process`` caller both use it and each keeps its own final
wait/reap bookkeeping.

Windows fells the whole tree with ``taskkill /T /F`` because a bare
``terminate()`` only kills the immediate process and orphans grandchildren
(node.exe under a cmd.exe shim, an engine a worker spawned). POSIX has no
equivalent call, so it snapshots the descendant set BEFORE it signals anything,
then escalates ``SIGTERM`` then ``SIGKILL`` across the whole snapshot; signalling
only the root would leave the same orphans Windows avoids. Only the shared
cancellation helper is imported from the package, so any layer can depend on this
module without an import cycle.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import psutil

from .async_cleanup import complete_cleanup

__all__ = [
    "POLL_INTERVAL",
    "ListenerOwnership",
    "classify_listener_ownership",
    "descendant_pids",
    "detached_spawn_kwargs",
    "kill_pid_tree_async",
    "pid_is_live",
    "port_has_listener",
    "port_has_listener_async",
    "process_group_members",
    "process_start_identity",
    "tree_cpu_usage",
    "wait_pid_gone",
    "wait_pid_gone_async",
    "win_kernel32",
]

POLL_INTERVAL = 0.1
_LOOPBACK_HOST = "127.0.0.1"

# A POSIX process that has exited but is not yet reaped by its parent reads as a
# zombie (briefly "dead" on Linux). It runs no code, holds no port and owns no
# handle, so every caller here is right to read it as gone.
_EXITED_STATUSES = frozenset({psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD})


@dataclass(frozen=True, slots=True)
class _DetachedSpawnFlags:
    """The ``subprocess.Popen`` flag pair that detaches a child from this process."""

    creationflags: int
    start_new_session: bool


def detached_spawn_kwargs() -> _DetachedSpawnFlags:
    """Return the flags that detach a spawned child from this process.

    Windows gets a new process group (``CREATE_NEW_PROCESS_GROUP``); POSIX gets a
    new session (``start_new_session=True``). This is the bare flag decision only
    - it carries no containment or teardown of its own, unlike
    :class:`ProcessContainment`'s Job-Object-backed containment, which a caller
    that also needs whole-tree reaping without a per-pid walk should use instead.
    A caller that only needs the child to survive this process's exit (killing it
    later by pid or pid-tree) wants this narrower flag pair.

    Both fields are always populated (with the inactive platform's neutral value)
    rather than returned as a sparse mapping, so a caller passes both explicitly
    to ``subprocess.Popen`` - splatting a dict of kwargs into ``Popen`` defeats its
    overloaded constructor's static resolution.
    """
    if sys.platform == "win32":
        return _DetachedSpawnFlags(
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP, start_new_session=False
        )
    return _DetachedSpawnFlags(creationflags=0, start_new_session=True)


def pid_is_live(pid: int) -> bool:
    """Whether *pid* is a live process on this machine.

    The single liveness probe behind every kill path and staleness verdict in the
    package. An exited POSIX child that its parent has not reaped answers a
    signal-0 probe exactly like a running one; reading its state instead keeps
    every caller that kills its own child from waiting out a whole escalation
    against a process that is already dead. A process that exists but cannot be
    inspected (another user's, say) reads as live, so no staleness verdict or
    kill confirmation rests on a read that failed.
    """
    if pid <= 0:
        return False
    try:
        return psutil.Process(pid).status() not in _EXITED_STATUSES
    except psutil.NoSuchProcess:
        return False
    except (psutil.Error, OSError):
        return True


def _all_gone(pids: tuple[int, ...]) -> bool:
    return not any(pid_is_live(pid) for pid in pids)


def wait_pid_gone(*pids: int, timeout: float) -> bool:
    """Block until every one of *pids* is gone; ``False`` if any outlives *timeout*.

    The single "confirm it actually died" poll, so a caller that felled a tree
    never starts a replacement while the old generation still runs. Liveness is
    :func:`pid_is_live`, which reads an unreaped zombie as gone, so a caller still
    holding the child's handle need not reap it first.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _all_gone(pids):
            return True
        time.sleep(POLL_INTERVAL)
    return _all_gone(pids)


async def wait_pid_gone_async(*pids: int, timeout: float) -> bool:
    """The event-loop form of :func:`wait_pid_gone`, yielding between polls."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if _all_gone(pids):
            return True
        await asyncio.sleep(POLL_INTERVAL)
    return _all_gone(pids)


def _tree_members(root_pid: int) -> list[psutil.Process]:
    """*root_pid* and every live descendant still reachable from it.

    Raises :class:`psutil.Error` when the root is gone or cannot be read. The walk
    drops any candidate that started before the root, so a reused pid in the
    host's parent map never adopts an unrelated older process; a descendant
    whose intermediate parent already exited is unreachable and is not listed.
    """
    root = psutil.Process(root_pid)
    return [root, *root.children(recursive=True)]


def descendant_pids(pid: int) -> list[int]:
    """Every live descendant of *pid*; empty when it has none or cannot be read.

    A snapshot: a descendant started after the walk is not covered. The POSIX
    counterpart of ``taskkill /T`` takes it BEFORE the root is signalled, because
    killing the root severs exactly the parent links the walk reads. An
    unreadable tree reads as empty, so a kill falls back to the root alone and a
    check that needs a descendant fails closed.
    """
    if pid <= 0:
        return []
    try:
        return [member.pid for member in _tree_members(pid)[1:]]
    except (psutil.Error, OSError):
        return []


def tree_cpu_usage(pid: int) -> tuple[float, int] | None:
    """Cumulative CPU seconds and live member count of *pid*'s process tree.

    Both halves are progress signals for a caller watching a child: CPU time
    advances while the tree computes, and the member count changes when it
    spawns or reaps. ``None`` when the root is gone or cannot be read; a member
    that exits or cannot be read mid-walk is left out of both figures.
    """
    if pid <= 0:
        return None
    try:
        members = _tree_members(pid)
    except (psutil.Error, OSError):
        return None
    total = 0.0
    live = 0
    for member in members:
        try:
            times = member.cpu_times()
        except (psutil.Error, OSError):
            continue
        total += times.user + times.system
        live += 1
    return total, live


def process_group_members(pgid: int) -> tuple[int, ...] | None:
    """Every live member of POSIX process group *pgid*; ``None`` when unknown.

    A membership read, not a descendant walk, so it still counts an orphan the
    group's leader no longer parents. A zombie member is not live. A member that
    cannot be read makes the answer unknown, never empty. Windows has no process
    groups, so it is always unknown there.
    """
    if sys.platform == "win32":
        return None
    try:
        pids = psutil.pids()
    except (psutil.Error, OSError):
        return None
    members: list[int] = []
    uncertain = False
    for pid in pids:
        if pid <= 0:
            continue
        try:
            if os.getpgid(pid) != pgid:
                continue
            if psutil.Process(pid).status() in _EXITED_STATUSES:
                continue
        except (ProcessLookupError, psutil.NoSuchProcess):
            continue
        except (psutil.Error, OSError):
            uncertain = True
            continue
        members.append(pid)
    return None if uncertain else tuple(sorted(members))


def process_start_identity(pid: int) -> str | None:
    """The kernel's start stamp for *pid*, or ``None`` where it cannot be read.

    Clock-independent, so a recorded value stays comparable across wall-clock
    adjustments, across processes and across A2A generations: the creation
    ``FILETIME`` from ``GetProcessTimes`` on Windows and the ``starttime``
    clock-tick count since boot from ``/proc/<pid>/stat`` on Linux. psutil's
    ``create_time()`` is not used because it is derived from the wall clock on
    Linux and macOS. Other hosts, notably macOS, return ``None``.
    """
    if pid <= 0:
        return None
    if sys.platform == "win32":
        return _windows_start_identity(pid)
    if sys.platform.startswith("linux"):
        return _linux_start_identity(pid)
    return None


def _windows_start_identity(pid: int) -> str | None:
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    process_query = 0x1000  # PROCESS_QUERY_LIMITED_INFORMATION
    filetime = ctypes.POINTER(wintypes.FILETIME)
    kernel32 = win_kernel32()
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel32.GetProcessTimes.argtypes = (
        wintypes.HANDLE,
        filetime,
        filetime,
        filetime,
        filetime,
    )
    handle = kernel32.OpenProcess(process_query, False, pid)
    if not handle:
        return None
    try:
        creation = wintypes.FILETIME()
        exit_time = wintypes.FILETIME()
        kernel_time = wintypes.FILETIME()
        user_time = wintypes.FILETIME()
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        ):
            return None
        return f"{creation.dwHighDateTime}:{creation.dwLowDateTime}"
    finally:
        kernel32.CloseHandle(handle)


def _linux_start_identity(pid: int) -> str | None:
    try:
        with open(f"/proc/{pid}/stat", encoding="ascii", errors="replace") as handle:
            line = handle.read()
    except OSError:
        return None
    # comm (field 2) is parenthesised and may itself contain spaces and
    # parentheses, so the fields after the LAST ')' start at the state (field 3).
    # starttime is field 22 -> index 19 of that tail.
    _, sep, tail = line.rpartition(")")
    fields = tail.split()
    if not sep or len(fields) < 20:
        return None
    return fields[19]


def port_has_listener(port: int, *, timeout: float) -> bool:
    """Return ``True`` when a loopback ``connect`` to *port* is accepted.

    The single connect-probe primitive: a successful ``connect_ex`` to
    ``127.0.0.1:port`` proves a live listener is accepting there. It is the ONLY
    reliable "is this port taken" signal on Windows, where a plain ``bind``
    succeeds even when another process already serves the port (no
    ``SO_EXCLUSIVEADDRUSE``); a caller that must also catch a bound-but-not-yet-
    listening port pairs this with a bind-probe. *timeout* is required rather than
    defaulted because a readiness poll (fast) and a liveness check (patient) want
    different budgets.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((_LOOPBACK_HOST, port)) == 0


async def port_has_listener_async(port: int, *, timeout: float) -> bool:
    """The event-loop form of :func:`port_has_listener`.

    A refused connection and one that does not complete within *timeout* both
    read as no listener.
    """
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(_LOOPBACK_HOST, port), timeout=timeout
        )
        writer.close()
        await writer.wait_closed()
    except (OSError, TimeoutError):
        return False
    return True


class ListenerOwnership(StrEnum):
    """How much an ownership probe actually established about a port."""

    CONFIRMED = "confirmed"
    """The root or one of its descendants holds a TCP listener on the port."""

    OUTSIDE = "outside"
    """The root's whole tree was read and none of it listens on the port."""

    UNRESOLVED = "unresolved"
    """Part of the root's tree could not be read, so ownership was not established."""


def classify_listener_ownership(port: int, root_pid: int) -> ListenerOwnership:
    """Classify whether *root_pid*'s own tree holds the TCP listener on *port*.

    The only "is this listener ours" gate. It reads the TCP sockets of the root
    and each of its descendants, never the host socket table, so it needs no
    elevation and a squatter that answers like ours still reads as ``OUTSIDE``.
    It says nothing about whether anything listens on *port* at all; the
    caller's connect probe establishes that.

    A root that is already gone owns nothing, so it is ``OUTSIDE``. A tree member
    whose sockets cannot be read leaves the verdict ``UNRESOLVED`` unless another
    member confirms the listener. Reporting that apart from ``CONFIRMED`` is what
    lets a caller say ownership was not established instead of passing the port
    off as ours.
    """
    if root_pid <= 0:
        return ListenerOwnership.OUTSIDE
    try:
        members = _tree_members(root_pid)
    except psutil.NoSuchProcess:
        return ListenerOwnership.OUTSIDE
    except (psutil.Error, OSError):
        return ListenerOwnership.UNRESOLVED
    unreadable = False
    for member in members:
        try:
            connections = member.net_connections(kind="tcp")
        except psutil.NoSuchProcess:
            # It exited during the walk, so it cannot be holding the port.
            continue
        except (psutil.Error, OSError):
            unreadable = True
            continue
        if any(
            connection.status == psutil.CONN_LISTEN
            and connection.laddr
            and connection.laddr.port == port
            for connection in connections
        ):
            return ListenerOwnership.CONFIRMED
    if unreadable:
        return ListenerOwnership.UNRESOLVED
    return ListenerOwnership.OUTSIDE


def _posix_signal_all(pids: list[int], signal_number: int) -> None:
    """Send *signal_number* to each pid, skipping any that is not safe to signal."""
    own_pid = os.getpid()
    for target in pids:
        # pid 1 is init and a signal to it is never ours to send; signalling
        # ourselves would fell the very process doing the killing.
        if target <= 1 or target == own_pid:
            continue
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            os.kill(target, signal_number)


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
    return await complete_cleanup(_wait_for_tree_killer(killer, pid, timeout=timeout))


async def _wait_for_tree_killer(
    killer: asyncio.subprocess.Process, pid: int, *, timeout: float
) -> bool:
    """Bound and join the helper, including when its owner is cancelled."""
    try:
        returncode = await asyncio.wait_for(killer.wait(), timeout=timeout)
        return returncode == 0 or not pid_is_live(pid)
    except TimeoutError:
        return False
    finally:
        if killer.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                killer.kill()
            await asyncio.wait_for(killer.wait(), timeout=1.0)


async def kill_pid_tree_async(
    pid: int, *, term_timeout: float = 10.0, kill_timeout: float = 5.0
) -> bool:
    """Kill *pid* and its process tree; return ``True`` once it is gone.

    Windows uses ``taskkill /T /F /PID`` (whole-tree force kill). POSIX snapshots
    the descendants of *pid* (:func:`descendant_pids`), sends ``SIGTERM`` to the
    root and that snapshot, waits up to *term_timeout* for all of them to exit,
    then escalates to ``SIGKILL`` and waits up to *kill_timeout*. A pid that is
    already gone (or a non-positive pid) is a success. The caller keeps its own
    handle wait/reap after this returns.
    """
    return await complete_cleanup(
        _kill_pid_tree(pid, term_timeout=term_timeout, kill_timeout=kill_timeout)
    )


async def _kill_pid_tree(pid: int, *, term_timeout: float, kill_timeout: float) -> bool:
    if pid <= 0:
        return True
    if not pid_is_live(pid):
        return True
    if sys.platform == "win32":
        return await _win_tree_kill(pid, timeout=term_timeout + kill_timeout)
    # POSIX escalation, kept under the platform guard so the type checker narrows
    # ``signal`` to its POSIX members (``SIGKILL`` is absent on Windows).
    import signal

    targets = [pid, *descendant_pids(pid)]
    _posix_signal_all(targets, signal.SIGTERM)
    if await wait_pid_gone_async(*targets, timeout=term_timeout):
        return True
    _posix_signal_all(targets, signal.SIGKILL)
    return await wait_pid_gone_async(*targets, timeout=kill_timeout)


def win_kernel32() -> Any:
    """Load native handle release with pointer-sized arguments on every caller."""
    if sys.platform != "win32":
        raise OSError("kernel32 requires Windows")
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    return kernel32
