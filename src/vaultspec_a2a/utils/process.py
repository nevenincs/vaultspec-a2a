"""OS-owned containment for a spawned process and its descendants."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import subprocess
import sys
from typing import Any, TypedDict

from ._process_tree import (
    CREATE_SUSPENDED as _CREATE_SUSPENDED,
)
from ._process_tree import (
    JOB_BASIC_INFO_CLASS as _JOBOBJECT_BASIC_ACCOUNTING_INFORMATION_CLASS,
)
from ._process_tree import (
    JOB_EXTENDED_INFO_CLASS as _JOBOBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
)
from ._process_tree import (
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE as _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
)
from ._process_tree import (
    JOB_PROCESS_ID_LIST_CLASS as _JOBOBJECT_BASIC_PROCESS_ID_LIST_CLASS,
)
from ._process_tree import (
    POLL_INTERVAL as _POLL_INTERVAL,
)
from ._process_tree import (
    PROBE_DECODE_ERRORS as _PROBE_DECODE_ERRORS,
)
from ._process_tree import (
    PROBE_ENCODING as _PROBE_ENCODING,
)
from ._process_tree import (
    PROCESS_SET_QUOTA as _PROCESS_SET_QUOTA,
)
from ._process_tree import (
    PROCESS_TERMINATE as _PROCESS_TERMINATE,
)
from ._process_tree import (
    PS_TIMEOUT as _PS_TIMEOUT,
)
from ._process_tree import (
    TH32CS_SNAPTHREAD as _TH32CS_SNAPTHREAD,
)
from ._process_tree import (
    THREAD_SUSPEND_RESUME as _THREAD_SUSPEND_RESUME,
)
from ._process_tree import (
    pid_in_tree as _pid_in_tree,
)
from ._process_tree import (
    win_kernel32 as _win_kernel32,
)
from .async_cleanup import complete_cleanup

__all__ = [
    "ProcessContainment",
    "ProcessContainmentError",
]

logger = logging.getLogger(__name__)


class _SpawnKwargs(TypedDict, total=False):
    """The only platform-specific ``Popen`` keyword this facade supplies."""

    start_new_session: bool


def _posix_group_is_live(pgid: int) -> bool | None:
    """Read live membership, including orphans; unknown never means empty."""
    if sys.platform == "win32":
        return None
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    if sys.platform != "linux":
        return _ps_group_is_live(pgid)
    try:
        entries = os.listdir("/proc")
    except OSError:
        return _ps_group_is_live(pgid)
    return _proc_group_has_live_member(entries, pgid)


def _proc_group_has_live_member(entries: list[str], pgid: int) -> bool | None:
    uncertain = False
    for entry in entries:
        if not entry.isdigit():
            continue
        live = _proc_group_member_is_live(int(entry), pgid)
        if live:
            return True
        uncertain = uncertain or live is None
    return None if uncertain else False


def _proc_group_member_is_live(pid: int, pgid: int) -> bool | None:
    if sys.platform == "win32":
        return None
    try:
        if os.getpgid(pid) != pgid:
            return False
        with open(f"/proc/{pid}/stat", encoding="ascii", errors="replace") as fh:
            fields = fh.read().rpartition(")")[2].split()
    except (FileNotFoundError, ProcessLookupError):
        return False
    except OSError:
        return None
    if len(fields) < 3 or not fields[2].isdigit():
        return None
    return int(fields[2]) == pgid and fields[0] not in {"Z", "X"}


def _ps_group_is_live(pgid: int) -> bool | None:
    """Use the macOS/POSIX process table with a bounded, reaped probe."""
    try:
        completed = subprocess.run(
            ["ps", "-A", "-o", "pgid=,stat="],
            capture_output=True,
            text=True,
            encoding=_PROBE_ENCODING,
            errors=_PROBE_DECODE_ERRORS,
            timeout=_PS_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0 or not completed.stdout.strip():
        return None
    uncertain = False
    for line in completed.stdout.splitlines():
        fields = line.split()
        if len(fields) != 2 or not fields[0].isdigit():
            uncertain = True
        elif int(fields[0]) == pgid and fields[1][0] not in {"Z", "X"}:
            return True
    return None if uncertain else False


def _posix_group_process_ids(pgid: int | None) -> tuple[int, ...] | None:
    """Return a safe diagnostic snapshot of live members in an owned group."""
    if pgid is None or sys.platform == "win32":
        return None
    if sys.platform != "linux":
        return None
    try:
        entries = os.listdir("/proc")
    except OSError:
        return None
    pids: list[int] = []
    uncertain = False
    for entry in entries:
        if not entry.isdigit():
            continue
        pid = int(entry)
        live = _proc_group_member_is_live(pid, pgid)
        if live is True:
            pids.append(pid)
        elif live is None:
            uncertain = True
    return None if uncertain else tuple(sorted(pids))


async def _await_posix_group_gone(pgid: int, *, timeout: float) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    empty_observations = 0
    while True:
        # ps is bounded, but may still block for seconds on a busy host.
        if await asyncio.to_thread(_posix_group_is_live, pgid) is False:
            empty_observations += 1
            if empty_observations == 2:
                return True
        else:
            empty_observations = 0
        remaining = deadline - loop.time()
        if remaining <= 0:
            return False
        await asyncio.sleep(min(_POLL_INTERVAL, remaining))


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
    the spawn call, and :meth:`terminate` reaps the tree with bounded escalation.
    POSIX :meth:`assign` records the group established at exec. Windows owners
    that require containment before the first instruction create the root
    suspended and call :meth:`assign_suspended_process`. An unassigned
    containment owns no process identity; its caller must retain and reap the
    spawned process rather than treating this object as authority for it.
    """

    def __init__(self) -> None:
        self._pid: int | None = None
        self._pgid: int | None = None
        self._job: Any | None = None  # Windows job HANDLE (ctypes c_void_p)
        self._assigned = False
        self._termination_task: asyncio.Task[bool] | None = None

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

        kernel32 = _win_kernel32()
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
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
                raise ctypes.WinError(ctypes.get_last_error())
        except BaseException:
            kernel32.CloseHandle(job)
            raise
        return job

    def spawn_kwargs(self) -> _SpawnKwargs:
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
        raises :class:`ProcessContainmentError`; an ownership caller must reap the
        exact retained process and fail the spawn.
        """
        if sys.platform != "win32":
            if pid <= 1 or pid == os.getpid():
                raise ProcessContainmentError("Refusing to contain the cleanup owner")
            try:
                isolated = os.getpgid(pid) == pid and os.getsid(pid) == pid
            except ProcessLookupError:
                # A short-lived root can exit before assignment; the spawn still
                # established its group, which may retain live descendants.
                isolated = True
            if not isolated:
                raise ProcessContainmentError(
                    "Process was not spawned in a new session"
                )
            # start_new_session made the child a session/group leader: pgid == pid.
            self._pid = pid
            self._pgid = pid
            self._assigned = True
            return
        import ctypes
        from ctypes import wintypes

        if self._job is None:
            raise ProcessContainmentError("Windows containment has no job object")
        # This pid-only entry point is for roots already running. Owners that must
        # establish containment before the first instruction use
        # ``assign_suspended_process`` and retain the Popen process handle.
        kernel32 = _win_kernel32()
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
            self._assign_win_handle(pid, handle)
        finally:
            kernel32.CloseHandle(handle)

    def assign_process(self, process: subprocess.Popen[bytes]) -> None:
        """Bind the exact retained ``Popen`` identity to this containment.

        Windows uses the process handle owned by ``Popen`` rather than reopening
        its numeric pid, so an exit/reuse race cannot seat an unrelated process.
        POSIX uses the isolated process group established at spawn.
        """
        if sys.platform != "win32":
            self.assign(process.pid)
            return
        handle = getattr(process, "_handle", None)
        if handle is None:
            raise ProcessContainmentError("Popen has no retained Windows handle")
        self._assign_win_handle(process.pid, handle)

    def assign_suspended_process(self, process: subprocess.Popen[bytes]) -> None:
        """Atomically admit a Windows ``CREATE_SUSPENDED`` root, then run it.

        Assignment uses the exact process handle retained by ``Popen``. The only
        initial thread is resumed through documented Tool Help and thread APIs
        after Job membership succeeds, so no provider instruction or descendant
        creation can occur outside the Job. A failure leaves the root suspended or
        Job-owned for the caller to reap through the same retained handle.

        POSIX roots are already seated by ``start_new_session`` at exec and only
        need their process group recorded.
        """
        if sys.platform != "win32":
            self.assign_process(process)
            return
        self.assign_process(process)
        self._resume_suspended_win_process(process.pid)

    @staticmethod
    def suspended_creation_flag() -> int:
        """Return the Windows flag used with :meth:`assign_suspended_process`."""
        return _CREATE_SUSPENDED if sys.platform == "win32" else 0

    @staticmethod
    def _resume_suspended_win_process(pid: int) -> None:
        if sys.platform != "win32":
            return
        import ctypes
        from ctypes import wintypes

        class _ThreadEntry32(ctypes.Structure):
            _fields_ = (
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ThreadID", wintypes.DWORD),
                ("th32OwnerProcessID", wintypes.DWORD),
                ("tpBasePri", wintypes.LONG),
                ("tpDeltaPri", wintypes.LONG),
                ("dwFlags", wintypes.DWORD),
            )

        kernel32 = _win_kernel32()
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
        snapshot = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPTHREAD, 0)
        if snapshot == ctypes.c_void_p(-1).value:
            raise ProcessContainmentError(
                f"could not enumerate suspended process {pid}: "
                f"{ctypes.WinError(ctypes.get_last_error())}"
            )
        resumed = 0
        try:
            entry = _ThreadEntry32()
            entry.dwSize = ctypes.sizeof(entry)
            kernel32.Thread32First.restype = wintypes.BOOL
            kernel32.Thread32First.argtypes = (
                wintypes.HANDLE,
                ctypes.POINTER(_ThreadEntry32),
            )
            kernel32.Thread32Next.restype = wintypes.BOOL
            kernel32.Thread32Next.argtypes = (
                wintypes.HANDLE,
                ctypes.POINTER(_ThreadEntry32),
            )
            more = bool(kernel32.Thread32First(snapshot, ctypes.byref(entry)))
            while more:
                if entry.th32OwnerProcessID == pid:
                    kernel32.OpenThread.restype = wintypes.HANDLE
                    kernel32.OpenThread.argtypes = (
                        wintypes.DWORD,
                        wintypes.BOOL,
                        wintypes.DWORD,
                    )
                    thread = kernel32.OpenThread(
                        _THREAD_SUSPEND_RESUME, False, entry.th32ThreadID
                    )
                    if not thread:
                        raise ProcessContainmentError(
                            f"could not open suspended process {pid} thread: "
                            f"{ctypes.WinError(ctypes.get_last_error())}"
                        )
                    try:
                        kernel32.ResumeThread.restype = wintypes.DWORD
                        kernel32.ResumeThread.argtypes = (wintypes.HANDLE,)
                        previous = kernel32.ResumeThread(thread)
                        if previous != 1:
                            raise ProcessContainmentError(
                                f"could not resume suspended process {pid} thread"
                            )
                        resumed += 1
                    finally:
                        kernel32.CloseHandle(thread)
                more = bool(kernel32.Thread32Next(snapshot, ctypes.byref(entry)))
        finally:
            kernel32.CloseHandle(snapshot)
        if resumed != 1:
            raise ProcessContainmentError(
                f"suspended process {pid} exposed {resumed} resumable threads"
            )

    def _assign_win_handle(self, pid: int, handle: Any) -> None:
        if sys.platform != "win32" or self._job is None:
            raise ProcessContainmentError(
                f"Windows containment has no job object for process {pid}"
            )
        import ctypes
        from ctypes import wintypes

        kernel32 = _win_kernel32()
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
        self._pid = pid
        self._assigned = True

    @property
    def assigned(self) -> bool:
        """Whether a root pid is bound to this containment."""
        return self._assigned

    def is_quiescent(self) -> bool | None:
        """Return whether the owned tree is empty, or ``None`` if unknowable.

        This is an observation only: it neither releases containment nor
        changes ownership. Callers use it before accepting a root-process exit
        as proof that the complete owned tree has exited.
        """
        if self._pid is None:
            return True
        if not self._assigned:
            return None
        if sys.platform == "win32":
            if self._job is None:
                return None
            return self._win_active_processes(_win_kernel32()) == 0
        pgid = self._pgid
        if pgid is None:
            return None
        return not _posix_group_is_live(pgid)

    async def terminate(
        self, *, term_timeout: float = 10.0, kill_timeout: float = 5.0
    ) -> bool:
        """Reap the contained tree with bounded escalation; return ``True`` when gone.

        POSIX escalates ``killpg`` SIGTERM -> (wait ``term_timeout``) -> SIGKILL
        (wait ``kill_timeout``) over the owned process group. Windows terminates
        the job. An unassigned containment is empty and cannot establish that an
        independently retained root was reaped; ownership callers must handle
        that root through their retained process identity.

        A failed POSIX reap retains its group for a later retry. Windows always
        closes the kill-on-close handle as the last termination backstop; if job
        accounting failed, later calls keep reporting failure because descendant
        quiescence can no longer be verified through that closed handle.
        """
        if self._termination_task is None or self._termination_task.done():
            self._termination_task = asyncio.create_task(
                self._terminate(term_timeout=term_timeout, kill_timeout=kill_timeout)
            )
        return await complete_cleanup(self._termination_task)

    async def _terminate(self, *, term_timeout: float, kill_timeout: float) -> bool:
        try:
            result = await self._terminate_owned(
                term_timeout=term_timeout, kill_timeout=kill_timeout
            )
        finally:
            # Includes an empty, never-assigned Windows job and failed cleanup.
            self.close()
        if result:
            # A successfully emptied group can later reuse its numeric identity.
            self._pid = self._pgid = None
            self._assigned = False
        return result

    async def _terminate_owned(
        self, *, term_timeout: float, kill_timeout: float
    ) -> bool:
        if self._pid is None:
            return True
        if not self._assigned:
            raise ProcessContainmentError(
                f"Process {self._pid} is not assigned to this containment"
            )
        if sys.platform == "win32":
            return await self._terminate_win_job(kill_timeout=kill_timeout)
        return await self._terminate_posix_group(
            term_timeout=term_timeout, kill_timeout=kill_timeout
        )

    async def _terminate_win_job(self, *, kill_timeout: float) -> bool:
        """Terminate the job and wait, bounded, until it holds no live process.

        ``TerminateJobObject`` marks every assigned process for termination; the
        wait confirms the whole tree is actually gone (not just the root the
        caller separately waits on) by polling the job's active-process count -
        via the job's own accounting information, never a parent-pid tree walk -
        until it reaches zero or *kill_timeout* elapses.
        """
        if sys.platform != "win32" or self._job is None:
            return False
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
            if active is None:
                logger.warning(
                    "Could not verify process cleanup: job accounting failed"
                )
                return False
            if active == 0:
                return True
            await asyncio.sleep(_POLL_INTERVAL)
        return self._win_active_processes(kernel32) == 0

    def _win_active_processes(self, kernel32: Any) -> int | None:
        """Return the job's live-process count via its accounting information.

        An unavailable count is unknown, never proof that the job is empty.
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

        if self._job is None:
            return None
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
            return None
        return int(info.ActiveProcesses)

    def diagnostic_snapshot(self) -> str:
        """Return process identities currently owned by this containment.

        This is diagnostic-only: it never discovers descendants by parent pid
        and never includes command lines or environment values. Windows reads
        Job Object membership; POSIX names the isolated process group, whose
        members are the owned tree by construction.
        """
        if self._pid is None or not self._assigned:
            return "owned_pids=unassigned"
        if sys.platform == "win32":
            pids = self._win_job_process_ids(_win_kernel32())
        else:
            pids = _posix_group_process_ids(self._pgid)
        if pids is None:
            return "owned_pids=unknown"
        return "owned_pids=" + ",".join(str(pid) for pid in pids)

    def is_designated_child(self, pid: int) -> bool:
        """Whether *pid* is the launcher-root's direct execution identity.

        A Windows virtual-environment launcher can replace the ``Popen`` root
        with one Python child. That child must be both in the owned Job Object
        and a descendant of the retained launcher root. POSIX has no launcher
        hop here, so only the exact spawned root is valid.
        """
        if self._pid is None or not self._assigned or pid <= 1:
            return False
        if sys.platform != "win32":
            return pid == self._pid
        pids = self._win_job_process_ids(_win_kernel32())
        return bool(pids and pid in pids and _pid_in_tree(self._pid, pid) is True)

    def _query_job_pid_list(
        self, kernel32: Any, size: int, header_size: int, pointer_size: int
    ) -> tuple[tuple[int, ...] | None, int | None]:
        """Return ``(pids, retry_size)`` for one sized query attempt.

        ``pids`` is ``None`` until a usable list is decoded; ``retry_size`` is
        the buffer size the caller should retry with, or ``None`` when the
        attempt is final (a decoded list, or a failure the caller cannot
        recover from by resizing).
        """
        import ctypes
        from ctypes import wintypes

        buffer = (ctypes.c_byte * size)()
        needed = wintypes.DWORD()
        kernel32.QueryInformationJobObject.restype = wintypes.BOOL
        kernel32.QueryInformationJobObject.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        )
        if not kernel32.QueryInformationJobObject(
            self._job,
            _JOBOBJECT_BASIC_PROCESS_ID_LIST_CLASS,
            ctypes.byref(buffer),
            size,
            ctypes.byref(needed),
        ):
            retry_size = int(needed.value) if needed.value > size else None
            return None, retry_size
        assigned = wintypes.DWORD.from_buffer(buffer, 0).value
        listed = wintypes.DWORD.from_buffer(buffer, 4).value
        capacity = (size - header_size) // pointer_size
        if assigned > capacity or listed > capacity:
            return None, None
        pids = tuple(
            ctypes.c_size_t.from_buffer(
                buffer, header_size + pointer_size * index
            ).value
            for index in range(listed)
        )
        return tuple(sorted(int(pid) for pid in pids if pid)), None

    def _win_job_process_ids(self, kernel32: Any) -> tuple[int, ...] | None:
        """Read exact current Job Object membership without a parent-pid walk."""
        if self._job is None:
            return None
        import ctypes
        from ctypes import wintypes

        header_size = ctypes.sizeof(wintypes.DWORD) * 2
        pointer_size = ctypes.sizeof(ctypes.c_size_t)
        size = header_size + pointer_size * 16
        for _attempt in range(3):
            pids, retry_size = self._query_job_pid_list(
                kernel32, size, header_size, pointer_size
            )
            if pids is not None or retry_size is None:
                return pids
            size = retry_size
        return None

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
        if pgid is None or pgid != self._pid or pgid <= 1 or pgid == os.getpgrp():
            raise ProcessContainmentError("Refusing to signal an unowned process group")
        # Confirm an empty snapshot before returning: the /proc walk can
        # transiently miss a member while the root exits and is reparented.
        if (
            await asyncio.to_thread(_posix_group_is_live, pgid) is False
            and await asyncio.to_thread(_posix_group_is_live, pgid) is False
        ):
            return True
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pgid, signal.SIGTERM)
        if await _await_posix_group_gone(pgid, timeout=term_timeout):
            return True
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pgid, signal.SIGKILL)
        return await _await_posix_group_gone(pgid, timeout=kill_timeout)

    def close(self) -> None:
        """Release the OS containment handle; idempotent.

        On Windows this closes the job handle - with KILL_ON_JOB_CLOSE this also
        reaps any still-running assigned process, so it doubles as a crash-safe
        backstop. POSIX holds no handle.
        """
        if sys.platform != "win32" or self._job is None:
            return
        import ctypes

        kernel32 = _win_kernel32()
        if not kernel32.CloseHandle(self._job):
            raise ctypes.WinError(ctypes.get_last_error())
        self._job = None
