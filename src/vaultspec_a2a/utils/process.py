"""Async process-tree termination, platform-aware and dependency-free.

The single async "kill this pid and its whole tree" escalation shared by the
worker-management shutdown and the ACP subprocess reaper. It works by PID (never a
process handle), so a ``subprocess.Popen`` caller and an
``asyncio.subprocess.Process`` caller both use it and each keeps its own final
wait/reap bookkeeping.

Windows fells the whole tree with ``taskkill /T /F`` because a bare
``terminate()`` only kills the immediate process and orphans grandchildren
(node.exe under a cmd.exe shim, an engine a worker spawned). POSIX has no
equivalent call, so it snapshots the descendant set from the parent-pid map
BEFORE it signals anything, then escalates ``SIGTERM`` then ``SIGKILL`` across
the whole snapshot; signalling only the root would leave the same orphans
Windows avoids. Liveness on POSIX also has to discount a zombie, which answers
signal 0 for as long as its parent has not reaped it (see :func:`pid_is_live`).
This module imports nothing from the rest of the package by design, so any layer
can depend on it without an import cycle.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import subprocess
import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "ProcessContainment",
    "ProcessContainmentError",
    "kill_pid_tree_async",
    "listener_belongs_to",
    "pid_is_live",
    "port_listener_pid",
    "posix_descendant_pids",
    "posix_parent_map",
]

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 0.1
_PS_TIMEOUT = 5.0

# Windows Job Object constants (winnt.h). A job created with
# KILL_ON_JOB_CLOSE terminates every assigned process when the job is terminated
# OR when the last handle to it is closed, so an owner that crashes still reaps
# the whole contained tree.
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOBOBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9  # JobObjectExtendedLimitInformation
_JOBOBJECT_BASIC_ACCOUNTING_INFORMATION_CLASS = 1  # JobObjectBasicAccountingInformation
_PROCESS_TERMINATE = 0x0001
_PROCESS_SET_QUOTA = 0x0100


def pid_is_live(pid: int) -> bool:
    """Whether *pid* is a live process on this machine.

    The single liveness probe behind every kill path and staleness verdict in the
    package. Windows queries the process exit code; POSIX probes with signal 0 and
    then rules out a zombie (see :func:`_posix_pid_is_zombie`).
    """
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        process_query = 0x1000  # PROCESS_QUERY_LIMITED_INFORMATION
        still_active = 259  # STILL_ACTIVE
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(process_query, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Another user owns it, so it cannot be an unreaped child of ours: it exists.
        return True
    return not _posix_pid_is_zombie(pid)


def _posix_pid_is_zombie(pid: int) -> bool:
    """Whether *pid* has exited but has not yet been reaped by its parent.

    A signal-0 probe is an existence test, not a liveness test: on POSIX an exited
    child keeps its pid slot until its parent waits on it, and a zombie answers
    signal 0 exactly like a running process. Without this distinction every caller
    that kills a process it spawned waits out its full SIGTERM/SIGKILL escalation
    against a process that is already dead and then reports failure, because the
    reap only happens later in the caller's own ``wait()``. Windows has no
    equivalent state, which is why the defect is POSIX-only.

    A zombie runs no code, holds no port, and owns no handle, so every caller here
    is right to read it as gone.
    """
    if sys.platform == "win32":  # pragma: no cover - Windows has no zombie state
        return False
    if _is_exited_child(pid):
        return True
    return _proc_stat_state(pid) in {"Z", "X"}


def _is_exited_child(pid: int) -> bool:
    """Whether *pid* is a child of this process that has exited and awaits a reap.

    Uses ``waitid`` with ``WNOWAIT``, which reports the exit WITHOUT consuming it,
    so the owner (a ``subprocess.Popen``, an asyncio child watcher) still collects
    the real exit status afterwards. ``ChildProcessError`` means *pid* is not our
    child at all, which this probe reports as "not a zombie we can see" and leaves
    to :func:`_proc_stat_state`.
    """
    if sys.platform == "win32":  # pragma: no cover - POSIX-only wait semantics
        return False
    waitid = getattr(os, "waitid", None)
    if waitid is None:  # pragma: no cover - waitid is absent on some POSIX hosts
        return False
    try:
        return waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None
    except (ChildProcessError, OSError, ValueError):
        return False


def _proc_stat_state(pid: int) -> str:
    """The single-letter ``/proc`` state of *pid*, or ``""`` where it is unreadable.

    Covers the zombie that is NOT our child (a reparented grandchild whose new
    parent has not reaped it yet), which ``waitid`` cannot see. Hosts without
    ``/proc`` simply report no state and fall back to the signal-0 result.
    """
    try:
        with open(f"/proc/{pid}/stat", encoding="ascii", errors="replace") as handle:
            line = handle.read()
    except OSError:
        return ""
    # The comm field is parenthesised and may itself contain spaces and
    # parentheses, so the state is the first token after the LAST ')'.
    _, _, rest = line.rpartition(")")
    fields = rest.split()
    return fields[0] if fields else ""


def posix_parent_map() -> dict[int, int]:
    """A ``{pid: parent pid}`` map of every process on this POSIX host.

    Read from ``/proc`` where it exists (Linux), otherwise from ``ps``, which is
    POSIX-specified and covers the hosts without a ``procfs``.
    """
    if sys.platform == "win32":  # pragma: no cover - Windows walks no parent map
        return {}
    mapping = _proc_parent_map()
    return mapping if mapping else _ps_parent_map()


def _proc_parent_map() -> dict[int, int]:
    mapping: dict[int, int] = {}
    try:
        entries = os.listdir("/proc")
    except OSError:
        return {}
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat", encoding="ascii", errors="replace") as fh:
                line = fh.read()
        except OSError:
            # The process exited between the listing and the read: not an error.
            continue
        # State and parent pid are the first two tokens after the parenthesised
        # comm field, which may itself contain spaces and parentheses.
        fields = line.rpartition(")")[2].split()
        if len(fields) < 2 or not fields[1].lstrip("-").isdigit():
            continue
        mapping[int(entry)] = int(fields[1])
    return mapping


def _ps_parent_map() -> dict[int, int]:
    try:
        completed = subprocess.run(
            ["ps", "-A", "-o", "pid=,ppid="],
            capture_output=True,
            text=True,
            timeout=_PS_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    mapping: dict[int, int] = {}
    for line in completed.stdout.splitlines():
        parts = line.split()
        if len(parts) < 2 or not parts[0].isdigit() or not parts[1].isdigit():
            continue
        mapping[int(parts[0])] = int(parts[1])
    return mapping


def posix_descendant_pids(pid: int) -> list[int]:
    """Every descendant of *pid* on POSIX, as a snapshot taken before any signal.

    The POSIX counterpart of ``taskkill /T``: POSIX has no "signal this process and
    everything below it" call, and a bare ``SIGTERM`` to a parent leaves its
    children running and reparented to init. The walk must therefore happen BEFORE
    the root is signalled, because killing the root severs exactly the parent links
    a later walk would need. Like ``taskkill /T`` this is a snapshot, so a
    descendant spawned after the walk is not covered.
    """
    if sys.platform == "win32":  # pragma: no cover - Windows fells the tree natively
        return []
    children: dict[int, list[int]] = {}
    for child, parent in posix_parent_map().items():
        children.setdefault(parent, []).append(child)
    descendants: list[int] = []
    seen = {pid}
    frontier = list(children.get(pid, ()))
    while frontier:
        current = frontier.pop()
        if current in seen:
            continue
        seen.add(current)
        descendants.append(current)
        frontier.extend(children.get(current, ()))
    return descendants


def listener_belongs_to(port: int, root_pid: int) -> bool:
    """``False`` only when *port*'s LISTENER is positively outside *root_pid*'s tree.

    A readiness probe that a port is bound cannot tell our freshly spawned server
    apart from a stranger that happens to hold the same port - an un-reaped orphan
    of a felled generation, or a foreign racer on a fixed resume/rerun port. This
    confirms the pid listening on the loopback port is *root_pid* itself or a
    descendant of it, so readiness passes on OUR process and not a stranger's.

    It fails safe: when the listener pid or the ancestry cannot be resolved (no
    ``netstat``/``/proc``/``lsof``, or an unreadable parent map) it returns
    ``True`` and degrades to the bare bound-port signal, so a normal boot is never
    falsely failed. It returns ``False`` only when a listener pid is resolved AND
    positively shown to descend from a different root.
    """
    listener_pid = port_listener_pid(port)
    if listener_pid is None:
        return True
    return _pid_in_tree(root_pid, listener_pid)


def port_listener_pid(port: int) -> int | None:
    """Best-effort pid LISTENING on loopback *port*; ``None`` when unresolved.

    Platform-aware and dependency-free: ``netstat`` on Windows, ``/proc/net`` then
    ``lsof`` on POSIX. Returns ``None`` (never a guess) when no owner can be read,
    so callers degrade rather than misattribute a port to the wrong process.
    """
    if sys.platform == "win32":
        return _netstat_listener_pid(port)
    proc_pid = _proc_listener_pid(port)
    if proc_pid is not None:
        return proc_pid
    return _lsof_listener_pid(port)


def _pid_in_tree(root_pid: int, candidate_pid: int) -> bool:
    """``True`` when *candidate_pid* is *root_pid* or descends from it.

    Degrades to ``True`` on an unresolved parent map (candidate is not the root
    but ancestry cannot be walked), so a legitimate descendant listener is never
    falsely rejected; returns ``False`` only on a resolved map that positively
    fails to reach the root.
    """
    if candidate_pid == root_pid:
        return True
    parents = _parent_map()
    if not parents:
        return True
    seen: set[int] = set()
    current = candidate_pid
    while current > 1 and current not in seen:
        seen.add(current)
        parent = parents.get(current)
        if parent is None:
            return False
        if parent == root_pid:
            return True
        current = parent
    return False


def _parent_map() -> dict[int, int]:
    """A ``{pid: parent pid}`` map for this host, cross-platform; empty on failure."""
    if sys.platform == "win32":
        return _win_parent_map()
    return posix_parent_map()


def _win_parent_map() -> dict[int, int]:
    """Windows ``{pid: parent pid}`` via a single CIM query; empty on any failure.

    Windows fells trees with ``taskkill /T`` and keeps no parent map for
    termination, but the readiness owner-check needs one to confirm a listener pid
    descends from the process we spawned.
    """
    try:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "Get-CimInstance Win32_Process | ForEach-Object "
                '{ "$($_.ProcessId) $($_.ParentProcessId)" }',
            ],
            capture_output=True,
            text=True,
            timeout=_PS_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    mapping: dict[int, int] = {}
    for line in completed.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            mapping[int(parts[0])] = int(parts[1])
    return mapping


def _netstat_listener_pid(port: int) -> int | None:
    try:
        completed = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True,
            text=True,
            timeout=_PS_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    for line in completed.stdout.splitlines():
        parts = line.split()
        # Columns: Proto  Local Address  Foreign Address  State  PID
        if len(parts) < 5 or parts[0].upper() != "TCP":
            continue
        if parts[3].upper() != "LISTENING":
            continue
        if _addr_port(parts[1]) != port:
            continue
        if parts[4].isdigit():
            return int(parts[4])
    return None


_TCP_LISTEN_STATE = "0A"


def _proc_listener_pid(port: int) -> int | None:
    inode = _proc_listen_inode(port)
    if inode is None:
        return None
    return _proc_pid_for_socket_inode(inode)


def _proc_listen_inode(port: int) -> str | None:
    for path in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(path, encoding="ascii", errors="replace") as handle:
                next(handle, None)  # header row
                for line in handle:
                    fields = line.split()
                    if len(fields) < 10 or fields[3] != _TCP_LISTEN_STATE:
                        continue
                    _, sep, hexport = fields[1].partition(":")
                    if not sep:
                        continue
                    try:
                        if int(hexport, 16) != port:
                            continue
                    except ValueError:
                        continue
                    return fields[9]
        except OSError:
            continue
    return None


def _proc_pid_for_socket_inode(inode: str) -> int | None:
    target = f"socket:[{inode}]"
    try:
        entries = os.listdir("/proc")
    except OSError:
        return None
    for entry in entries:
        if not entry.isdigit():
            continue
        fd_dir = f"/proc/{entry}/fd"
        try:
            fds = os.listdir(fd_dir)
        except OSError:
            continue
        for fd in fds:
            try:
                if os.readlink(f"{fd_dir}/{fd}") == target:
                    return int(entry)
            except OSError:
                continue
    return None


def _lsof_listener_pid(port: int) -> int | None:
    try:
        completed = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            capture_output=True,
            text=True,
            timeout=_PS_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    for token in completed.stdout.split():
        if token.isdigit():
            return int(token)
    return None


def _addr_port(addr: str) -> int | None:
    """The port of a ``host:port`` local-address column, or ``None``.

    Accepts IPv4 (``127.0.0.1:8123``) and IPv6 (``[::]:8123``) forms by reading
    only the final ``:``-delimited field, so any bound host with the right port
    matches - a wildcard ``0.0.0.0``/``[::]`` listener serves loopback too.
    """
    _, sep, port_s = addr.rpartition(":")
    if not sep or not port_s.isdigit():
        return None
    return int(port_s)


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


async def _await_pid_gone(pid: int, *, timeout: float) -> bool:
    """Poll until *pid* is gone or *timeout* elapses; return whether it is gone."""
    return await _await_pids_gone([pid], timeout=timeout)


async def _await_pids_gone(pids: list[int], *, timeout: float) -> bool:
    """Poll until every pid is gone or *timeout* elapses; report whether all are."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if not any(pid_is_live(pid) for pid in pids):
            return True
        await asyncio.sleep(_POLL_INTERVAL)
    return not any(pid_is_live(pid) for pid in pids)


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
    try:
        returncode = await asyncio.wait_for(killer.wait(), timeout=timeout)
        return returncode == 0 or not pid_is_live(pid)
    except TimeoutError:
        killer.kill()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(killer.wait(), timeout=1.0)
        return False


async def kill_pid_tree_async(
    pid: int, *, term_timeout: float = 10.0, kill_timeout: float = 5.0
) -> bool:
    """Kill *pid* and its process tree; return ``True`` once it is gone.

    Windows uses ``taskkill /T /F /PID`` (whole-tree force kill). POSIX snapshots
    the descendants of *pid* (:func:`posix_descendant_pids`), sends ``SIGTERM`` to
    the root and that snapshot, waits up to *term_timeout* for all of them to exit,
    then escalates to ``SIGKILL`` and waits up to *kill_timeout*. A pid that is
    already gone (or a non-positive pid) is a success. The caller keeps its own
    handle wait/reap after this returns.
    """
    if pid <= 0:
        return True
    if not pid_is_live(pid):
        return True
    if sys.platform == "win32":
        return await _win_tree_kill(pid, timeout=term_timeout + kill_timeout)
    # POSIX escalation, kept under the platform guard so the type checker narrows
    # ``signal`` to its POSIX members (``SIGKILL`` is absent on Windows).
    import signal

    targets = [pid, *posix_descendant_pids(pid)]
    _posix_signal_all(targets, signal.SIGTERM)
    if await _await_pids_gone(targets, timeout=term_timeout):
        return True
    _posix_signal_all(targets, signal.SIGKILL)
    return await _await_pids_gone(targets, timeout=kill_timeout)


# ---------------------------------------------------------------------------
# ProcessContainment — OS-owned containment for a spawned root and its tree
# ---------------------------------------------------------------------------


def _win_job_structures() -> tuple[Any, int]:
    """Build a KILL_ON_JOB_CLOSE extended-limit-information payload for a job.

    Kept behind a function so the ctypes structure classes are only defined on
    Windows, where ``ctypes.wintypes`` and the job APIs exist. Returns the filled
    structure instance and its byte size for ``SetInformationJobObject``.
    """
    import ctypes

    class _JobObjectBasicLimitInformation(ctypes.Structure):
        _fields_ = (
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", ctypes.c_uint32),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", ctypes.c_uint32),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", ctypes.c_uint32),
            ("SchedulingClass", ctypes.c_uint32),
        )

    class _IoCounters(ctypes.Structure):
        _fields_ = tuple(
            (name, ctypes.c_uint64)
            for name in (
                "ReadOperationCount",
                "WriteOperationCount",
                "OtherOperationCount",
                "ReadTransferCount",
                "WriteTransferCount",
                "OtherTransferCount",
            )
        )

    class _JobObjectExtendedLimitInformation(ctypes.Structure):
        _fields_ = (
            ("BasicLimitInformation", _JobObjectBasicLimitInformation),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        )

    info = _JobObjectExtendedLimitInformation()
    info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    return info, ctypes.sizeof(info)


class ProcessContainmentError(RuntimeError):
    """Raised when an owned root cannot be assigned to its OS containment."""


class ProcessContainment:
    """An operating-system-owned containment for a spawned root and its tree.

    Two backends, one contract - reap the whole tree without walking it by
    parent pid:

    - **POSIX**: the root is spawned into a new session and process group
      (``start_new_session=True`` -> ``setsid``), so the root's process-group id
      equals its pid and every descendant that does not itself ``setsid`` stays
      in that group. Termination signals the group with ``killpg`` (SIGTERM then
      SIGKILL), never a per-pid tree walk.
    - **Windows**: a Job Object created with ``KILL_ON_JOB_CLOSE`` owns the root;
      ``TerminateJobObject`` fells every assigned process at once, and closing the
      last handle (e.g. on owner crash) also reaps the job. No ``taskkill /T``
      parent-pid discovery.

    Lifecycle: :meth:`create` builds the containment, :meth:`spawn_kwargs` feeds
    the spawn call, :meth:`assign` binds the just-spawned pid before it does
    descendant work, and :meth:`terminate` reaps the tree with bounded
    escalation. An unassigned containment falls back to a per-pid tree kill so a
    spawn is never left unreapable, and the fallback is logged.
    """

    def __init__(self) -> None:
        self._pid: int | None = None
        self._pgid: int | None = None
        self._job: Any | None = None  # Windows job HANDLE (ctypes c_void_p)
        self._assigned = False

    @classmethod
    def create(cls) -> ProcessContainment:
        """Build a containment; on Windows this creates the KILL_ON_JOB_CLOSE job.

        A Windows job-creation failure is fatal to containment and raises; POSIX
        needs no OS object until a pid is assigned.
        """
        self = cls()
        if sys.platform == "win32":
            self._job = self._create_win_job()
        return self

    @staticmethod
    def _create_win_job() -> Any:
        if sys.platform != "win32":
            raise OSError("job objects require Windows")
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            raise ctypes.WinError(ctypes.get_last_error())
        info, size = _win_job_structures()
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.SetInformationJobObject.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        )
        if not kernel32.SetInformationJobObject(
            job,
            _JOBOBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
            ctypes.byref(info),
            size,
        ):
            err = ctypes.get_last_error()
            kernel32.CloseHandle(job)
            raise ctypes.WinError(err)
        return job

    def spawn_kwargs(self) -> Mapping[str, Any]:
        """Return spawn kwargs that seat the root in its containment at spawn.

        POSIX seats the root in a new session/process group at fork; Windows
        assigns after spawn (see :meth:`assign`), so it contributes no spawn-time
        kwargs here.
        """
        if sys.platform == "win32":
            return {}
        return {"start_new_session": True}

    def assign(self, pid: int) -> None:
        """Bind *pid* to the containment before the root does descendant work.

        POSIX records the new process group (its id equals the session leader's
        pid). Windows assigns the process to the job. A Windows assignment failure
        raises :class:`ProcessContainmentError`; the caller may downgrade to the
        per-pid fallback rather than fail the spawn.
        """
        self._pid = pid
        if sys.platform != "win32":
            # start_new_session made the child a session/group leader: pgid == pid.
            self._pgid = pid
            self._assigned = True
            return
        import ctypes
        from ctypes import wintypes

        if self._job is None:
            raise ProcessContainmentError("Windows containment has no job object")
        # Assign-after-spawn window (documented reliance, not silence): the root is
        # created, then opened and assigned here, so a descendant the root forks in
        # the microseconds between CreateProcess and AssignProcessToJobObject would
        # not join the job. In practice the owned roots never fork that fast: the
        # worker assigns nothing until its asyncio loop and single-flight startup
        # run (seconds later); the provider CLI does Node/handshake init before it
        # launches an MCP server; a terminal command's first act is not a
        # microsecond-latency grandchild. Boot/init latency covers the window.
        # The structural close is the OS-native atomic path - creating the process
        # already in the job (PROC_THREAD_ATTRIBUTE_JOB_LIST via a STARTUPINFOEX
        # attribute list) - which stdlib ``subprocess`` cannot pass. The considered
        # alternatives are disproportionate or unsound here: CREATE_SUSPENDED plus
        # resume needs a thread handle ``Popen`` does not expose (or the
        # undocumented ``NtResumeProcess``); a stdin-gated trampoline that ``execv``s
        # the real command escapes the job on Windows (which has no true ``execv``),
        # and one that spawns it as a child would need a full stdio proxy for the
        # ACP provider. KILL_ON_JOB_CLOSE still reaps everything that did join the
        # job, and the per-pid fallback backstops a wholly failed assignment.
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        handle = kernel32.OpenProcess(
            _PROCESS_TERMINATE | _PROCESS_SET_QUOTA, False, pid
        )
        if not handle:
            raise ProcessContainmentError(
                f"could not open process {pid} to assign it to the job: "
                f"{ctypes.WinError(ctypes.get_last_error())}"
            )
        try:
            kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
            kernel32.AssignProcessToJobObject.argtypes = (
                wintypes.HANDLE,
                wintypes.HANDLE,
            )
            if not kernel32.AssignProcessToJobObject(self._job, handle):
                raise ProcessContainmentError(
                    f"could not assign process {pid} to the job: "
                    f"{ctypes.WinError(ctypes.get_last_error())}"
                )
        finally:
            kernel32.CloseHandle(handle)
        self._assigned = True

    @property
    def assigned(self) -> bool:
        """Whether a root pid is bound to this containment."""
        return self._assigned

    async def terminate(
        self, *, term_timeout: float = 10.0, kill_timeout: float = 5.0
    ) -> bool:
        """Reap the contained tree with bounded escalation; return ``True`` when gone.

        POSIX escalates ``killpg`` SIGTERM -> (wait ``term_timeout``) -> SIGKILL
        (wait ``kill_timeout``) over the owned process group. Windows terminates
        the job. An unassigned containment (assignment failed or never ran) falls
        back to the per-pid tree kill so the root is never left unreapable, logging
        the downgrade.
        """
        if not self._assigned or self._pid is None:
            if self._pid is not None:
                logger.warning(
                    "Process %d has no OS containment; falling back to a per-pid"
                    " tree kill (containment assignment did not complete)",
                    self._pid,
                )
                result = await kill_pid_tree_async(
                    self._pid, term_timeout=term_timeout, kill_timeout=kill_timeout
                )
                self.close()
                return result
            return True
        if sys.platform == "win32":
            result = await self._terminate_win_job(kill_timeout=kill_timeout)
            self.close()
            return result
        result = await self._terminate_posix_group(
            term_timeout=term_timeout, kill_timeout=kill_timeout
        )
        self.close()
        return result

    async def _terminate_win_job(self, *, kill_timeout: float) -> bool:
        """Terminate the job and wait, bounded, until it holds no live process.

        ``TerminateJobObject`` marks every assigned process for termination; the
        wait confirms the whole tree is actually gone (not just the root the
        caller separately waits on) by polling the job's active-process count -
        via the job's own accounting information, never a parent-pid tree walk -
        until it reaches zero or *kill_timeout* elapses.
        """
        if sys.platform != "win32" or self._job is None:
            return True
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.TerminateJobObject.restype = wintypes.BOOL
        kernel32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
        # A non-zero exit code marks the tree as force-terminated. A failed call is
        # non-fatal: closing the KILL_ON_JOB_CLOSE handle still reaps the job.
        kernel32.TerminateJobObject(self._job, 1)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + kill_timeout
        while loop.time() < deadline:
            active = self._win_active_processes(kernel32)
            if active == 0:
                return True
            await asyncio.sleep(_POLL_INTERVAL)
        return self._win_active_processes(kernel32) == 0

    def _win_active_processes(self, kernel32: Any) -> int:
        """Return the job's live-process count via its accounting information.

        Returns 0 when the count cannot be read (the job handle is gone), so a
        query failure resolves as "empty" rather than hanging the bounded wait.
        """
        import ctypes
        from ctypes import wintypes

        class _JobObjectBasicAccountingInformation(ctypes.Structure):
            _fields_ = (
                ("TotalUserTime", ctypes.c_int64),
                ("TotalKernelTime", ctypes.c_int64),
                ("ThisPeriodTotalUserTime", ctypes.c_int64),
                ("ThisPeriodTotalKernelTime", ctypes.c_int64),
                ("TotalPageFaultCount", ctypes.c_uint32),
                ("TotalProcesses", ctypes.c_uint32),
                ("ActiveProcesses", ctypes.c_uint32),
                ("TotalTerminatedProcesses", ctypes.c_uint32),
            )

        info = _JobObjectBasicAccountingInformation()
        kernel32.QueryInformationJobObject.restype = wintypes.BOOL
        kernel32.QueryInformationJobObject.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.c_void_p,
        )
        if not kernel32.QueryInformationJobObject(
            self._job,
            _JOBOBJECT_BASIC_ACCOUNTING_INFORMATION_CLASS,
            ctypes.byref(info),
            ctypes.sizeof(info),
            None,
        ):
            return 0
        return int(info.ActiveProcesses)

    async def _terminate_posix_group(
        self, *, term_timeout: float, kill_timeout: float
    ) -> bool:
        # Kept under the platform guard so the type checker narrows ``signal`` and
        # ``os.killpg`` to their POSIX members (absent on Windows). Only ever
        # reached on POSIX via :meth:`terminate`.
        if sys.platform == "win32":  # pragma: no cover - Windows uses the job path
            return True
        import signal

        pgid = self._pgid
        pid = self._pid
        if pgid is None or pid is None:
            return True
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pgid, signal.SIGTERM)
        if await _await_pid_gone(pid, timeout=term_timeout):
            return True
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pgid, signal.SIGKILL)
        return await _await_pid_gone(pid, timeout=kill_timeout)

    def close(self) -> None:
        """Release the OS containment handle; idempotent.

        On Windows this closes the job handle - with KILL_ON_JOB_CLOSE this also
        reaps any still-running assigned process, so it doubles as a crash-safe
        backstop. POSIX holds no handle.
        """
        if sys.platform != "win32" or self._job is None:
            return
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        with contextlib.suppress(Exception):
            kernel32.CloseHandle(self._job)
        self._job = None
