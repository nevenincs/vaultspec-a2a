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
    PortReservation,
    ProcRecord,
    StalenessState,
    classify_record,
    commit_reservation,
    list_records,
    now_ms,
    read_record,
    record_path,
    release_reservation,
    remove_record,
    reserve_port,
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
    "render_env",
    "rerun",
    "resolve",
    "resume",
    "serve_up",
    "spawn",
    "tree_kill",
]

_OWNER_ENV = "VAULTSPEC_PROCS_OWNER"
_NAME_ENV = "VAULTSPEC_PROCS_NAME"
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


def _subst(value: str, *, port: int, workspace: str) -> str:
    """Substitute the ``{python}``/``{port}``/``{workspace}`` tokens in a value.

    ``{python}`` resolves to :data:`sys.executable` - the interpreter of the
    serving process - so a role that shells ``python`` always runs the SAME venv
    interpreter (with ``vaultspec_a2a`` installed), never whatever bare ``python``
    a PATH lookup would otherwise resolve to (a uv-managed base interpreter).
    """
    return (
        value.replace("{python}", sys.executable)
        .replace("{port}", str(port))
        .replace("{workspace}", workspace)
    )


def render_command(template: list[str], *, port: int, workspace: str) -> list[str]:
    """Substitute the ``{python}``/``{port}``/``{workspace}`` tokens in a command."""
    return [_subst(arg, port=port, workspace=workspace) for arg in template]


def render_env(
    env_template: dict[str, str], *, port: int, workspace: str
) -> dict[str, str]:
    """Substitute the ``{port}``/``{workspace}`` tokens in each env-var value.

    A role whose serve reads its port from the environment (the a2a gateway from
    ``VAULTSPEC_PORT``, the worker from ``VAULTSPEC_WORKER_PORT``) declares an
    ``env`` table in procs.toml; the boot verb renders it into the child's
    environment rather than passing a ``--port`` flag the command does not accept.
    """
    return {
        key: _subst(value, port=port, workspace=workspace)
        for key, value in env_template.items()
    }


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
    command: list[str],
    *,
    cwd: Path,
    log_path: str | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.Popen[bytes]:
    """Start *command* detached from the CLI so it outlives the invocation.

    Windows gets a new process group (``CREATE_NEW_PROCESS_GROUP``) so a later
    ``taskkill /T`` fells the whole tree by pid; POSIX gets its own session.
    Output is appended to *log_path* when given, else discarded. *env*, when given,
    is overlaid on the inherited environment (not a replacement) so a serve command
    inherits PATH and the venv while picking up its injected port/config vars.
    """
    if not command:
        raise LifecycleError("cannot spawn an empty command")
    log_handle = open(log_path, "ab") if log_path is not None else None  # noqa: SIM115
    stdout: IO[bytes] | int = (
        log_handle if log_handle is not None else subprocess.DEVNULL
    )
    child_env = {**os.environ, **env} if env is not None else None
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
            env=child_env,
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


def _serve_env(
    role_cfg: RoleConfig, *, port: int, workspace: str, name: str, owner: str
) -> dict[str, str]:
    """The env overlay for a boot: the role's rendered port/config vars plus identity.

    Carrying the managed name and owner into the child means a serve process that
    self-registers (a gateway/worker booted on a band port) converges onto THIS
    record - same ``(role, name)`` and owner - and refreshes it, instead of writing
    a second, foreign-owned record that the owner-check would then refuse.
    """
    env = render_env(role_cfg.env, port=port, workspace=workspace)
    env[_NAME_ENV] = name
    env[_OWNER_ENV] = owner
    return env


def serve_up(
    role: str,
    name: str,
    *,
    workspace: str = "",
    repo: str = "",
    owner: str | None = None,
    log_path: str | None = None,
    ready_timeout: float = 20.0,
    home: Path | None = None,
    config: ProcsConfig | None = None,
) -> ProcRecord:
    """Boot a role's serve command on a freshly-allocated band port and register it.

    The race-free, collision-tolerant allocate-and-claim the registry was missing:
    reserve a band port (``O_EXCL`` marker, so two concurrent same-band boots can
    never collide), spawn the role's serve command on it, wait for a live listener,
    then commit the claiming record and drop the marker. If the child dies (e.g.
    ``EADDRINUSE`` from a non-registry racer) or never binds within *ready_timeout*,
    the port is felled and released and the NEXT band port is tried - failed
    reservations are held (not released) across the loop so each attempt gets a
    fresh port. Raises :class:`LifecycleError` when the role has no serve command or
    no band port yields a listener; :class:`RuntimeError` when the band is exhausted.
    """
    from pathlib import Path as _Path

    resolved_config = config if config is not None else load_procs_config()
    role_cfg = resolved_config.role(role)
    if not role_cfg.serve:
        raise LifecycleError(f"role {role!r} declares no serve command in procs.toml")
    owner_label = owner if owner is not None else default_owner()
    cwd = _Path(repo) if repo else _default_repo()
    max_attempts = role_cfg.band.end - role_cfg.band.start + 1
    held: list[PortReservation] = []
    try:
        for _ in range(max_attempts):
            reservation = reserve_port(
                role, role_cfg, home=home, config=resolved_config
            )
            held.append(reservation)
            command = render_command(
                role_cfg.serve, port=reservation.port, workspace=workspace
            )
            child_env = _serve_env(
                role_cfg,
                port=reservation.port,
                workspace=workspace,
                name=name,
                owner=owner_label,
            )
            process = spawn(command, cwd=cwd, log_path=log_path, env=child_env)
            if _await_listener(reservation.port, process, timeout=ready_timeout):
                stamp = now_ms()
                record = ProcRecord(
                    name=name,
                    role=role,
                    pid=process.pid,
                    port=reservation.port,
                    repo=str(cwd) if repo else "",
                    workspace=workspace,
                    build_sha=_build_sha(cwd),
                    command=command,
                    started_at_ms=stamp,
                    last_seen_ms=stamp,
                    log_path=log_path,
                    owner=owner_label,
                )
                commit_reservation(reservation, record, home=home)
                held.remove(reservation)
                return record
            # The child never bound (a racer took the port, or it crashed): fell it
            # and try the next band port. Keep the reservation held so reserve_port
            # skips this port on the next pass.
            tree_kill(process.pid)
        raise LifecycleError(
            f"could not bring up {role}-{name}: no band port yielded a live listener"
        )
    finally:
        for reservation in held:
            release_reservation(reservation)


def _await_listener(
    port: int, process: subprocess.Popen[bytes], *, timeout: float
) -> bool:
    """Wait for a live listener on *port*; return ``False`` if the child dies first."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        if _port_is_bound(port):
            return True
        time.sleep(0.1)
    return False


def _default_repo() -> Path:
    """The repo root a serve command runs in when a record carries no explicit repo."""
    from ..control.config import settings

    return settings.project_root


def _cwd_for(record: ProcRecord) -> Path:
    """The dir a role's build/serve runs in: the record's repo, else the root."""
    from pathlib import Path as _Path

    if record.repo:
        return _Path(record.repo)
    return _default_repo()


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
    child_env = _serve_env(
        role,
        port=record.port,
        workspace=record.workspace,
        name=record.name,
        owner=record.owner or default_owner(),
    )
    cwd = _cwd_for(record)
    process = spawn(command, cwd=cwd, log_path=record.log_path or None, env=child_env)
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
