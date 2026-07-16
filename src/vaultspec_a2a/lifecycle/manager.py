"""Process-lifecycle operations over the registry (dev-process-registry ADR).

The verbs the operator CLI exposes - ``list``/``attach``/``kill``/``rebuild``/
``rerun``/``resume``/``reap`` - orchestrated here over the file-per-process
registry and the committed ``procs.toml``. This module owns the side-effecting
primitives (Windows tree-kill, command-template rendering, detached spawn, git
build-sha capture) and the verb logic that composes them; the CLI in
``vaultspec_a2a.cli`` is a thin formatter over the structured results returned
here, so the lifecycle behaviour is testable without a terminal.

Kill discipline is Windows-first per the ADR: ``taskkill /T /F /PID`` fells the
whole process tree by pid (a bare ``terminate`` orphans grandchildren on
Windows); POSIX falls back to ``SIGTERM`` then ``SIGKILL``. A kill is an OS
action, not a registry write - once the pid is dead the record is freely
removable, so ``kill`` never has to fight another owner's live claim.
"""

from __future__ import annotations

import contextlib
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .procs_config import ProcsConfig, ProcsConfigError, load_procs_config
from .registry import (
    ProcRecord,
    StalenessState,
    classify_record,
    list_records,
    now_ms,
    read_record,
    record_path,
    remove_record,
    write_record,
)

if TYPE_CHECKING:
    from pathlib import Path
    from typing import IO

    from .procs_config import RoleConfig

__all__ = [
    "LifecycleError",
    "ProcVerdict",
    "attach",
    "default_owner",
    "endpoint_for",
    "kill",
    "list_verdicts",
    "reap",
    "rebuild",
    "render_command",
    "rerun",
    "resolve",
    "resume",
    "spawn",
    "tree_kill",
]

_OWNER_ENV = "VAULTSPEC_PROCS_OWNER"
_KILL_POLL_INTERVAL = 0.1


class LifecycleError(RuntimeError):
    """A lifecycle verb could not complete (unknown record, role, or command)."""


@dataclass(frozen=True, slots=True)
class ProcVerdict:
    """A record paired with its liveness classification and endpoint."""

    record: ProcRecord
    state: StalenessState
    endpoint: str


def default_owner() -> str:
    """The owner label stamped on CLI-spawned records.

    Honours ``VAULTSPEC_PROCS_OWNER`` (a session or agent label) so concurrent
    operators claim distinct ownership; falls back to a process-scoped label.
    """
    return os.environ.get(_OWNER_ENV) or f"cli-{os.getpid()}"


def endpoint_for(record: ProcRecord) -> str:
    """The loopback endpoint a consumer attaches to for *record*."""
    return f"http://127.0.0.1:{record.port}"


def _is_pid_alive(pid: int) -> bool:
    from .discovery import is_pid_alive

    return is_pid_alive(pid)


def tree_kill(pid: int, *, timeout: float = 10.0) -> bool:
    """Kill *pid* and its whole process tree, returning ``True`` once it is dead.

    Windows uses ``taskkill /T /F /PID`` (the ADR's tree-kill discipline: a bare
    terminate orphans grandchildren). POSIX escalates ``SIGTERM`` then
    ``SIGKILL``. A pid that is already dead is a success. The call blocks up to
    *timeout* seconds for the process to disappear before reporting.
    """
    if pid <= 0 or not _is_pid_alive(pid):
        return True
    if sys.platform == "win32":
        with contextlib.suppress(OSError):
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
    else:
        import signal

        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _is_pid_alive(pid):
            return True
        time.sleep(_KILL_POLL_INTERVAL)
    if sys.platform != "win32":
        import signal

        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(pid, signal.SIGKILL)
        time.sleep(_KILL_POLL_INTERVAL)
    return not _is_pid_alive(pid)


def render_command(template: list[str], *, port: int, workspace: str) -> list[str]:
    """Substitute the ``{port}`` and ``{workspace}`` tokens in a command template."""
    return [
        arg.replace("{port}", str(port)).replace("{workspace}", workspace)
        for arg in template
    ]


def _build_sha(cwd: Path) -> str | None:
    """Best-effort short git SHA of *cwd*'s HEAD, or ``None`` outside a repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    sha = result.stdout.strip()
    return sha or None


def spawn(
    command: list[str], *, cwd: Path, log_path: str | None = None
) -> subprocess.Popen[bytes]:
    """Start *command* detached from the CLI so it outlives the invocation.

    Windows gets a new process group (``CREATE_NEW_PROCESS_GROUP``) so a later
    ``taskkill /T`` fells the whole tree by pid; POSIX gets its own session.
    Output is appended to *log_path* when given, else discarded.
    """
    if not command:
        raise LifecycleError("cannot spawn an empty command")
    log_handle = open(log_path, "ab") if log_path is not None else None  # noqa: SIM115
    stdout: IO[bytes] | int = (
        log_handle if log_handle is not None else subprocess.DEVNULL
    )
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
        start_new_session = False
    else:
        creationflags = 0
        start_new_session = True
    try:
        return subprocess.Popen(
            command,
            cwd=str(cwd),
            stdout=stdout,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            start_new_session=start_new_session,
        )
    finally:
        if log_handle is not None:
            log_handle.close()


def resolve(name: str, *, home: Path | None = None) -> ProcRecord:
    """Find the single record named *name* across all roles.

    Raises :class:`LifecycleError` when no record matches, or when the name is
    ambiguous across roles (the caller must then qualify with ``<role>-<name>``).
    """
    matches = [rec for rec in list_records(home) if rec.name == name]
    if not matches:
        # Accept a fully-qualified <role>-<name> too, for disambiguation.
        for rec in list_records(home):
            if f"{rec.role}-{rec.name}" == name:
                return rec
        raise LifecycleError(f"no registry record named {name!r}")
    if len(matches) > 1:
        roles = ", ".join(sorted(f"{r.role}-{r.name}" for r in matches))
        raise LifecycleError(
            f"name {name!r} is ambiguous across roles; qualify one of: {roles}"
        )
    return matches[0]


def _role_of(record: ProcRecord, config: ProcsConfig) -> RoleConfig | None:
    return config.roles.get(record.role)


def list_verdicts(
    *, home: Path | None = None, config: ProcsConfig | None = None
) -> list[ProcVerdict]:
    """Enumerate every record with its liveness verdict and endpoint."""
    resolved_config = config if config is not None else _load_config_or_empty()
    now = now_ms()
    verdicts: list[ProcVerdict] = []
    for record in list_records(home):
        role = _role_of(record, resolved_config) if resolved_config else None
        state = classify_record(record, role, now=now)
        verdicts.append(
            ProcVerdict(record=record, state=state, endpoint=endpoint_for(record))
        )
    return verdicts


def _load_config_or_empty() -> ProcsConfig:
    try:
        return load_procs_config()
    except ProcsConfigError:
        return ProcsConfig(resident={}, roles={})


def attach(name: str, *, home: Path | None = None) -> ProcVerdict:
    """Verify the named process is live on its recorded port and return its endpoint.

    Raises :class:`LifecycleError` when the pid is dead or the port is not bound,
    so an operator never attaches to a stale record.
    """
    record = resolve(name, home=home)
    if not _is_pid_alive(record.pid):
        raise LifecycleError(
            f"{record.role}-{record.name} pid {record.pid} is not alive"
        )
    if not _port_is_bound(record.port):
        raise LifecycleError(
            f"{record.role}-{record.name} pid {record.pid} is alive but port "
            f"{record.port} is not accepting connections"
        )
    config = _load_config_or_empty()
    role = _role_of(record, config)
    state = classify_record(record, role)
    return ProcVerdict(record=record, state=state, endpoint=endpoint_for(record))


def kill(name: str, *, home: Path | None = None) -> ProcRecord:
    """Tree-kill the named process and remove its record.

    The kill is an OS action; once the pid is dead the record is unconditionally
    removed (a dead record fights no owner). Returns the killed record.
    """
    record = resolve(name, home=home)
    if not tree_kill(record.pid):
        raise LifecycleError(
            f"failed to kill {record.role}-{record.name} pid {record.pid}"
        )
    remove_record(record.role, record.name, home=home)
    return record


def rebuild(
    name: str, *, home: Path | None = None, config: ProcsConfig | None = None
) -> str | None:
    """Run the role's build command from ``procs.toml``; return the new build SHA.

    Blocks on the build. Raises :class:`LifecycleError` when the role declares no
    build command or the build exits non-zero.
    """
    record = resolve(name, home=home)
    resolved_config = config if config is not None else load_procs_config()
    role = resolved_config.role(record.role)
    if not role.build:
        raise LifecycleError(
            f"role {record.role!r} declares no build command in procs.toml"
        )
    cwd = _cwd_for(record)
    result = subprocess.run(role.build, cwd=str(cwd), check=False)
    if result.returncode != 0:
        raise LifecycleError(
            f"build for {record.role}-{record.name} failed "
            f"(exit {result.returncode}): {' '.join(role.build)}"
        )
    sha = _build_sha(cwd)
    if read_record(record_path(record.role, record.name, home=home)) is not None:
        from dataclasses import replace

        write_record(replace(record, build_sha=sha), home=home)
    return sha


def resume(
    name: str, *, home: Path | None = None, config: ProcsConfig | None = None
) -> ProcRecord:
    """Restart a died record's process on its original port and workspace.

    Refuses when the process is still alive (nothing to resume). Re-spawns the
    role's serve command, then rewrites the record with the new pid and a fresh
    started/last-seen stamp, preserving port, workspace, and owner.
    """
    record = resolve(name, home=home)
    if _is_pid_alive(record.pid):
        raise LifecycleError(
            f"{record.role}-{record.name} pid {record.pid} is still alive; "
            "nothing to resume (use rerun to cycle it)"
        )
    return _start_from_record(record, home=home, config=config)


def rerun(
    name: str, *, home: Path | None = None, config: ProcsConfig | None = None
) -> ProcRecord:
    """Kill, rebuild (when the role declares a build), and restart on the same port.

    The full cycle: fell the running tree, rebuild the artifact, re-spawn serve,
    and re-register with the new pid and build SHA on the original port/workspace.
    """
    record = resolve(name, home=home)
    resolved_config = config if config is not None else load_procs_config()
    role = resolved_config.role(record.role)
    tree_kill(record.pid)
    if role.build:
        cwd = _cwd_for(record)
        result = subprocess.run(role.build, cwd=str(cwd), check=False)
        if result.returncode != 0:
            raise LifecycleError(
                f"rebuild for {record.role}-{record.name} failed "
                f"(exit {result.returncode})"
            )
    return _start_from_record(record, home=home, config=resolved_config)


def reap(
    *, home: Path | None = None, config: ProcsConfig | None = None
) -> list[ProcRecord]:
    """Kill every stale/dead record's orphan and clear it; return the reaped records.

    A ``DEAD`` record's pid is already gone; a ``STALE`` record's pid is alive but
    past its heartbeat window - both are orphans the operator no longer wants, so
    the tree is felled (no-op when already dead) and the record removed.
    """
    resolved_config = config if config is not None else _load_config_or_empty()
    reaped: list[ProcRecord] = []
    now = now_ms()
    for record in list_records(home):
        role = _role_of(record, resolved_config)
        state = classify_record(record, role, now=now)
        if state is StalenessState.LIVE:
            continue
        tree_kill(record.pid)
        remove_record(record.role, record.name, home=home)
        reaped.append(record)
    return reaped


def _cwd_for(record: ProcRecord) -> Path:
    """The dir a role's build/serve runs in: the record's repo, else the root."""
    from pathlib import Path as _Path

    from ..control.config import settings

    if record.repo:
        return _Path(record.repo)
    return settings.project_root


def _start_from_record(
    record: ProcRecord,
    *,
    home: Path | None,
    config: ProcsConfig | None,
) -> ProcRecord:
    """Spawn the role's serve command and re-register *record* with the new pid."""
    from dataclasses import replace

    resolved_config = config if config is not None else load_procs_config()
    role = resolved_config.role(record.role)
    if not role.serve:
        raise LifecycleError(
            f"role {record.role!r} declares no serve command in procs.toml"
        )
    command = render_command(role.serve, port=record.port, workspace=record.workspace)
    cwd = _cwd_for(record)
    process = spawn(command, cwd=cwd, log_path=record.log_path or None)
    stamp = now_ms()
    updated = replace(
        record,
        pid=process.pid,
        command=command,
        build_sha=_build_sha(cwd) or record.build_sha,
        started_at_ms=stamp,
        last_seen_ms=stamp,
    )
    write_record(updated, home=home)
    return updated


def _port_is_bound(port: int, *, timeout: float = 1.0) -> bool:
    """Return ``True`` when something is accepting connections on *port*.

    A connect probe, not a bind probe: on Windows ``SO_REUSEADDR`` lets a second
    socket bind a port another is already listening on, so a bind cannot tell a
    held port from a free one. A successful loopback connect proves a live
    listener - exactly what ``attach`` must verify.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex(("127.0.0.1", port)) == 0
