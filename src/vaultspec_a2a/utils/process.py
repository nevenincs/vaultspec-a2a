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
import logging
import os
import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "ProcessContainment",
    "ProcessContainmentError",
    "kill_pid_tree_async",
]

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 0.1

# Windows Job Object constants (winnt.h). A job created with
# KILL_ON_JOB_CLOSE terminates every assigned process when the job is terminated
# OR when the last handle to it is closed, so an owner that crashes still reaps
# the whole contained tree.
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOBOBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9  # JobObjectExtendedLimitInformation
_JOBOBJECT_BASIC_ACCOUNTING_INFORMATION_CLASS = 1  # JobObjectBasicAccountingInformation
_PROCESS_TERMINATE = 0x0001
_PROCESS_SET_QUOTA = 0x0100


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
