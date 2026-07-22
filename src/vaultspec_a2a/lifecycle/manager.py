"""Process-lifecycle operations over the registry.

The verbs the operator CLI exposes - ``list``/``attach``/``kill``/``rebuild``/
``rerun``/``resume``/``reap`` - orchestrated here over the file-per-process
registry and the committed ``procs.toml``. This module owns the side-effecting
primitives (Windows tree-kill, command-template rendering, detached spawn, git
build-sha capture) and the verb logic that composes them; the CLI in
``vaultspec_a2a.cli`` is a thin formatter over the structured results returned
here, so the lifecycle behaviour is testable without a terminal.

Kill discipline is Windows-first: ``taskkill /T /F /PID`` fells the
whole process tree by pid (a bare ``terminate`` orphans grandchildren on
Windows); POSIX falls back to ``SIGTERM`` then ``SIGKILL``. A kill is an OS
action, not a registry write - once the pid is dead the record is freely
removable, so ``kill`` never has to fight another owner's live claim.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..authoring.discovery import SERVICE_JSON_ENV as _ENGINE_SERVICE_JSON_ENV
from ..control.config import GATEWAY_URL_ENV, INTERNAL_TOKEN_ENV, WORKER_URL_ENV
from .procs_config import ProcsConfig, ProcsConfigError, load_procs_config
from .registry import (
    NAME_ENV,
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
    from typing import IO, Any

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
_KILL_POLL_INTERVAL = 0.1
_KILL_ESCALATION_WAIT = 5.0

# A spawned process's redirect file is a raw append-mode file, not a Python
# logging handler, so it cannot rotate on its own — a long-lived dev instance
# (gateway-dev/worker-dev/engine-dev, restarted many times via resume/rerun onto
# the SAME log_path) would otherwise grow it forever. Checked once at spawn time
# (research: lifecycle/manager.py:200-241 appends unbounded); 10 MiB is generous
# headroom for a single boot's worth of stdout+stderr while still bounding the
# pathological case.
SPAWN_LOG_CAP_BYTES = 10 * 1024 * 1024


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


def _confirm_terminated(pid: int, *, timeout: float = 10.0) -> bool:
    """Poll until *pid* is no longer a live process; ``False`` if it survives.

    A bounded confirmation that a felled generation actually terminated, so a
    replacement is never spawned while the old process is still alive on the same
    port. Returns ``False`` when the pid is still alive at the deadline (a kill
    that did not take), so the caller can refuse rather than overlap generations.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _is_pid_alive(pid):
            return True
        time.sleep(0.05)
    return not _is_pid_alive(pid)


def tree_kill(pid: int, *, timeout: float = 10.0) -> bool:
    """Kill *pid* and its whole process tree, returning ``True`` once it is dead.

    Windows uses ``taskkill /T /F /PID`` (a bare terminate orphans grandchildren
    on Windows). POSIX has no whole-tree signal, so it snapshots the descendants
    before signalling anything - killing the root first would sever the parent
    links the walk needs - and escalates ``SIGTERM`` then ``SIGKILL`` across the
    root and that snapshot. A pid that is already dead is a success. The call
    blocks up to *timeout* seconds for the tree to disappear before reporting.
    """
    if pid <= 0 or not _is_pid_alive(pid):
        return True
    targets = [pid]
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

        from ..utils.process import posix_descendant_pids

        targets = [pid, *posix_descendant_pids(pid)]
        _signal_all(targets, signal.SIGTERM)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _any_pid_alive(targets):
            return True
        time.sleep(_KILL_POLL_INTERVAL)
    if sys.platform != "win32":
        import signal

        _signal_all(targets, signal.SIGKILL)
        # SIGKILL is immediate but not instantaneous: give the kernel a bounded
        # window to tear the processes down before reporting the outcome.
        kill_deadline = time.monotonic() + _KILL_ESCALATION_WAIT
        while time.monotonic() < kill_deadline:
            if not _any_pid_alive(targets):
                return True
            time.sleep(_KILL_POLL_INTERVAL)
    return not _any_pid_alive(targets)


def _any_pid_alive(pids: list[int]) -> bool:
    return any(_is_pid_alive(pid) for pid in pids)


def _signal_all(pids: list[int], signal_number: int) -> None:
    """Send *signal_number* to each pid, skipping any that is not ours to signal."""
    own_pid = os.getpid()
    for target in pids:
        if target <= 1 or target == own_pid:
            continue
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            os.kill(target, signal_number)


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


def _rotate_log_if_over_cap(
    log_path: Path, *, cap_bytes: int = SPAWN_LOG_CAP_BYTES
) -> None:
    """Rotate *log_path* to a ``.1`` sibling when it is at or over *cap_bytes*.

    A single-generation rotation (overwriting any prior ``.1``): simple, matches
    the "one prior boot's worth of context" value these redirect files carry, and
    needs no background thread the way a full ``RotatingFileHandler`` would for a
    plain subprocess-redirect file. A missing file is a no-op (nothing to rotate).
    """
    try:
        if log_path.stat().st_size < cap_bytes:
            return
    except OSError:
        return
    rotated = log_path.with_name(f"{log_path.name}.1")
    with contextlib.suppress(OSError):
        rotated.unlink(missing_ok=True)
        log_path.rename(rotated)


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
    Output is appended to *log_path* when given, else discarded — rotated to a
    ``.1`` sibling first when the existing file is already at the size cap, so a
    dev instance restarted many times onto the same log_path (``resume``/
    ``rerun``) never grows it without bound. *env*, when given, is overlaid on
    the inherited environment (not a replacement) so a serve command inherits
    PATH and the venv while picking up its injected port/config vars.
    """
    if not command:
        raise LifecycleError("cannot spawn an empty command")
    if log_path is not None:
        from pathlib import Path as _Path

        _rotate_log_if_over_cap(_Path(log_path))
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


def _delete_record_log(record: ProcRecord) -> None:
    """Delete *record*'s runtime log file, if any, once its process is gone.

    A killed/reaped record's process no longer exists to append to it and no
    resume/rerun is pending in the same call, so the file is a pure orphan from
    this point on (research: kill/reap removed the registry record and process
    but left the log behind indefinitely). Best-effort: a missing or unremovable
    file must not fail the kill/reap it is cleaning up after.
    """
    if not record.log_path:
        return
    from pathlib import Path as _Path

    with contextlib.suppress(OSError):
        _Path(record.log_path).unlink(missing_ok=True)


def kill(name: str, *, home: Path | None = None) -> ProcRecord:
    """Tree-kill the named process, remove its record, and delete its runtime log.

    The kill is an OS action; once the pid is dead the record is unconditionally
    removed (a dead record fights no owner) and its ``log_path`` file (if any)
    deleted, since nothing will append to it again. Returns the killed record.
    """
    record = resolve(name, home=home)
    if not tree_kill(record.pid):
        raise LifecycleError(
            f"failed to kill {record.role}-{record.name} pid {record.pid}"
        )
    remove_record(record.role, record.name, home=home)
    _delete_record_log(record)
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
    cwd = _build_cwd_for(record)
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
    name: str,
    *,
    home: Path | None = None,
    config: ProcsConfig | None = None,
    ready_timeout: float = 20.0,
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
    # The main is confirmed dead above; fell any orphan tree it left and confirm
    # termination before spawning, so the replacement generation cannot overlap a
    # surviving old-tree member on the same port.
    tree_kill(record.pid)
    if not _confirm_terminated(record.pid):
        raise LifecycleError(
            f"resume could not confirm {record.role}-{record.name} pid "
            f"{record.pid} terminated; refusing to spawn an overlapping "
            "replacement (record left unchanged)"
        )
    return _start_from_record(
        record, home=home, config=config, ready_timeout=ready_timeout
    )


def rerun(
    name: str,
    *,
    home: Path | None = None,
    config: ProcsConfig | None = None,
    ready_timeout: float = 20.0,
) -> ProcRecord:
    """Kill, rebuild (when the role declares a build), and restart on the same port.

    The full cycle: fell the running tree, rebuild the artifact, re-spawn serve,
    and re-register with the new pid and build SHA on the original port/workspace.
    """
    record = resolve(name, home=home)
    resolved_config = config if config is not None else load_procs_config()
    role = resolved_config.role(record.role)
    # Refuse a data-seating role with no explicit repo BEFORE any side effect, so a
    # rerun cannot kill the running process and then decline to restart it - serve_up
    # and resume both guard before acting, and rerun must match that ordering.
    _ensure_explicit_repo(role, record.repo, f"{record.role}-{record.name}")
    tree_kill(record.pid)
    if not _confirm_terminated(record.pid):
        # The old tree did not confirm dead: refuse to spawn a replacement that
        # could overlap the surviving old generation on the same port. The record
        # is left unchanged - no new generation is published.
        raise LifecycleError(
            f"rerun could not confirm {record.role}-{record.name} pid "
            f"{record.pid} terminated; refusing to spawn an overlapping "
            "replacement (record left unchanged)"
        )
    if role.build:
        cwd = _build_cwd_for(record)
        result = subprocess.run(role.build, cwd=str(cwd), check=False)
        if result.returncode != 0:
            raise LifecycleError(
                f"rebuild for {record.role}-{record.name} failed "
                f"(exit {result.returncode})"
            )
    return _start_from_record(
        record, home=home, config=resolved_config, ready_timeout=ready_timeout
    )


def reap(
    *, home: Path | None = None, config: ProcsConfig | None = None
) -> list[ProcRecord]:
    """Kill every stale/dead record's orphan, clear it, and delete its runtime log.

    A ``DEAD`` record's pid is already gone; a ``STALE`` record's pid is alive but
    past its heartbeat window - both are orphans the operator no longer wants, so
    the tree is felled (no-op when already dead), the record removed, and its
    ``log_path`` file (if any) deleted since nothing will append to it again.
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
        _delete_record_log(record)
        reaped.append(record)
    return reaped


def _read_internal_token(token_file: str, *, label: str) -> str:
    """Read the internal-IPC token from *token_file*, failing loudly on a bad file.

    The record carries only the PATH (never the secret), so the token is read at
    boot. A role that declares a token file but whose file is missing, unreadable,
    or empty is refused with :class:`LifecycleError` rather than silently booting
    with no token - a silent empty-token fallback would reintroduce the invisible
    gateway/worker mismatch this pairing exists to close.
    """
    from pathlib import Path as _Path

    try:
        token = _Path(token_file).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise LifecycleError(
            f"{label}: internal token file {token_file!r} is unreadable: {exc}"
        ) from exc
    if not token:
        raise LifecycleError(f"{label}: internal token file {token_file!r} is empty")
    return token


def _serve_env(
    role_cfg: RoleConfig,
    *,
    port: int,
    workspace: str,
    name: str,
    owner: str,
    engine_service_json: str = "",
    internal_token_file: str = "",
    gateway_url: str = "",
    worker_url: str = "",
) -> dict[str, str]:
    """The env overlay for a boot: the role's rendered port/config vars plus identity.

    Carrying the managed name and owner into the child means a serve process that
    self-registers (a gateway/worker booted on a band port) converges onto THIS
    record - same ``(role, name)`` and owner - and refreshes it, instead of writing
    a second, foreign-owned record that the owner-check would then refuse.

    A recorded *engine_service_json* is injected under
    :data:`_ENGINE_SERVICE_JSON_ENV` so the worker's engine discovery no longer
    depends on the booting shell having exported it - the reseat-strands-worker gap.
    *internal_token_file* (a PATH, read here) is injected as the internal-IPC token,
    *gateway_url* as the paired gateway URL (worker -> gateway), and *worker_url* as
    the paired worker URL (gateway -> worker dispatch), so a procs-managed gateway-dev
    and worker-dev agree on all of them instead of leaning on shell state. Empty
    values inject nothing, matching the prior behaviour for records predating them.
    """
    env = render_env(role_cfg.env, port=port, workspace=workspace)
    env[NAME_ENV] = name
    env[_OWNER_ENV] = owner
    if engine_service_json:
        env[_ENGINE_SERVICE_JSON_ENV] = engine_service_json
    if internal_token_file:
        env[INTERNAL_TOKEN_ENV] = _read_internal_token(
            internal_token_file, label=f"{role_cfg.name}-{name}"
        )
    if gateway_url:
        env[GATEWAY_URL_ENV] = gateway_url
    if worker_url:
        env[WORKER_URL_ENV] = worker_url
    return env


def serve_up(
    role: str,
    name: str,
    *,
    workspace: str = "",
    repo: str = "",
    build_repo: str = "",
    engine_service_json: str = "",
    internal_token_file: str = "",
    gateway_url: str = "",
    worker_url: str = "",
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
    _ensure_explicit_repo(role_cfg, repo, f"{role}-{name}")
    owner_label = owner if owner is not None else default_owner()
    cwd = _Path(repo) if repo else _default_repo()
    # The build tree captured for rebuild/rerun; the boot build_sha reflects it, not
    # the serve tree, when a role's build and serve repos differ (engine-dev).
    build_cwd = _Path(build_repo) if build_repo else cwd
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
                engine_service_json=engine_service_json,
                internal_token_file=internal_token_file,
                gateway_url=gateway_url,
                worker_url=worker_url,
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
                    build_repo=build_repo,
                    workspace=workspace,
                    build_sha=_build_sha(build_cwd),
                    command=command,
                    started_at_ms=stamp,
                    last_seen_ms=stamp,
                    log_path=log_path,
                    owner=owner_label,
                    engine_service_json=engine_service_json,
                    internal_token_file=internal_token_file,
                    gateway_url=gateway_url,
                    worker_url=worker_url,
                )
                try:
                    commit_reservation(reservation, record, home=home)
                except BaseException:
                    # The process is up and ready and OWNED by us, but committing
                    # its claiming record failed - reap the complete owned tree
                    # before propagating so a commit failure after readiness never
                    # leaks a ready-but-unowned process.
                    tree_kill(process.pid)
                    raise
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
    port: int, process: subprocess.Popen[Any], *, timeout: float
) -> bool:
    """Wait for a live listener on *port* that OUR child owns.

    Returns ``False`` if the spawned child dies first, and does not accept a bound
    port until the listening pid is confirmed to be the child or a descendant of
    it (:func:`~vaultspec_a2a.utils.process.listener_belongs_to`). A foreign holder
    of the port - an un-reaped orphan of a felled generation, or a racer on a
    fixed resume/rerun port - therefore never reads as our process being ready, so
    a record is not published pointing at a listener we do not own. The owner check
    fails safe: when the listening pid cannot be resolved it degrades to the bare
    bound-port signal rather than stalling a legitimate boot.
    """
    from ..utils.process import listener_belongs_to

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        if _port_is_bound(port) and listener_belongs_to(port, process.pid):
            return True
        time.sleep(0.1)
    return False


def _default_repo() -> Path:
    """The repo root a serve command runs in when a record carries no explicit repo."""
    from ..control.config import settings

    return settings.project_root


def _ensure_explicit_repo(role_cfg: RoleConfig, repo: str, label: str) -> None:
    """Refuse to serve a data-seating role from an implicit default cwd.

    A role that declares ``require_repo`` (engine-dev seats its data store from its
    serve cwd) must be booted and resumed with an explicit repo, never defaulted to
    the project root - defaulting there once seated a dev engine's store on top of
    the resident engine's live store. Raises :class:`LifecycleError` when no repo is
    given, so the silent-root fallback is impossible rather than merely discouraged.
    """
    if role_cfg.require_repo and not repo:
        raise LifecycleError(
            f"role {role_cfg.name!r} requires an explicit repo (it seats data from "
            f"its serve cwd); {label} carries none - pass an explicit repo rather "
            "than defaulting to the project root"
        )


def _serve_cwd_for(record: ProcRecord) -> Path:
    """The dir a role's SERVE command runs in: the record's repo, else the root."""
    from pathlib import Path as _Path

    if record.repo:
        return _Path(record.repo)
    return _default_repo()


def _build_cwd_for(record: ProcRecord) -> Path:
    """The dir a role's BUILD command runs in.

    A role whose build tree differs from its serve tree (engine-dev builds the
    cargo workspace in the dashboard repo but serves the wrapper script from the
    a2a repo) captures the build tree in ``build_repo`` at boot; it falls back to
    the serve repo when unset, so single-tree roles need no extra field.
    """
    from pathlib import Path as _Path

    if record.build_repo:
        return _Path(record.build_repo)
    return _serve_cwd_for(record)


def _start_from_record(
    record: ProcRecord,
    *,
    home: Path | None,
    config: ProcsConfig | None,
    ready_timeout: float = 20.0,
) -> ProcRecord:
    """Spawn the role's serve command and re-register *record* with the new pid.

    Verifies the respawned process reaches readiness (a live listener on its
    original port) BEFORE the record is published, mirroring ``serve_up``'s
    spawn -> await-listener -> commit-or-reap discipline. A spawn that dies or
    never binds within *ready_timeout* is felled and the failure raised, so a
    failed resume/rerun never publishes a record pointing at a dead pid: the
    prior generation stays the last committed state and exactly one new
    generation is committed, only once it is ready.
    """
    from dataclasses import replace

    resolved_config = config if config is not None else load_procs_config()
    role = resolved_config.role(record.role)
    if not role.serve:
        raise LifecycleError(
            f"role {record.role!r} declares no serve command in procs.toml"
        )
    _ensure_explicit_repo(role, record.repo, f"{record.role}-{record.name}")
    command = render_command(role.serve, port=record.port, workspace=record.workspace)
    child_env = _serve_env(
        role,
        port=record.port,
        workspace=record.workspace,
        name=record.name,
        owner=record.owner or default_owner(),
        engine_service_json=record.engine_service_json,
        internal_token_file=record.internal_token_file,
        gateway_url=record.gateway_url,
        worker_url=record.worker_url,
    )
    cwd = _serve_cwd_for(record)
    process = spawn(command, cwd=cwd, log_path=record.log_path or None, env=child_env)
    if not _await_listener(record.port, process, timeout=ready_timeout):
        # The respawn died or never bound its port: fell the process tree and
        # refuse to publish. The prior record generation remains the last
        # committed state - a failed resume/rerun is atomic, not a half-published
        # dead pid.
        tree_kill(process.pid)
        raise LifecycleError(
            f"resume of {record.role}-{record.name} spawned pid {process.pid} "
            f"but it never became ready on port {record.port} within "
            f"{ready_timeout:g}s; process felled and record left unchanged"
        )
    stamp = now_ms()
    updated = replace(
        record,
        pid=process.pid,
        command=command,
        build_sha=_build_sha(_build_cwd_for(record)) or record.build_sha,
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
    listener - exactly what ``attach`` must verify. Delegates to the shared
    :func:`~vaultspec_a2a.lifecycle.discovery.port_has_listener` primitive.
    """
    from .discovery import port_has_listener

    return port_has_listener(port, timeout=timeout)
