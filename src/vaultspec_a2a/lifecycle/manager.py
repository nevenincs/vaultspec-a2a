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

import asyncio
import contextlib
import logging
import os
import subprocess
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict, Unpack, cast

import httpx

from ..utils._process_tree import detached_spawn_kwargs, kill_pid_tree_async
from .boot import (
    OWNER_ENV,
    build_cwd_for,
    build_sha,
    default_repo,
    ensure_explicit_repo,
    read_internal_token,
    render_command,
    serve_cwd_for,
    serve_env,
)
from .errors import LifecycleError
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

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from typing import IO, Any

    from .procs_config import RoleConfig

__all__ = [
    "ProcVerdict",
    "attach",
    "default_procs_owner",
    "endpoint_for",
    "kill",
    "list_verdicts",
    "reap",
    "rebuild",
    "rerun",
    "resolve",
    "resume",
    "serve_up",
    "spawn",
    "tree_kill",
]

# The SIGKILL-escalation budget tree_kill's sync wrapper passes to the shared
# async kill primitive's kill_timeout - kept here as this synchronous surface's
# own declared second phase rather than left implicit in the async default.
_KILL_ESCALATION_WAIT = 5.0

SPAWN_LOG_CAP_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ProcVerdict:
    """A record paired with its liveness classification and endpoint."""

    record: ProcRecord
    state: StalenessState
    endpoint: str


def default_procs_owner() -> str:
    """The owner label stamped on CLI-spawned registry records.

    Honours ``VAULTSPEC_PROCS_OWNER`` (a session or agent label) so concurrent
    operators claim distinct ownership; falls back to a process-scoped label.

    This is a *registry* label, not an operating-system principal: it identifies
    the session or agent that claimed a :class:`~.registry.ProcRecord`, and it
    changes with the process. The desktop runtime singleton's owner identity is a
    different concept with a different lifetime -
    :func:`~.singleton.default_owner`.
    """
    return os.environ.get(OWNER_ENV) or f"cli-{os.getpid()}"


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

    A thin synchronous wrapper over :func:`~..utils.process.kill_pid_tree_async`,
    the single asynchronous escalation this project owns (Windows
    ``taskkill /T /F``; POSIX snapshot-then-``SIGTERM``-then-``SIGKILL``) - this
    module used to carry an independent ~70-line synchronous copy of that same
    algorithm, which is exactly the duplication a shared kill primitive exists to
    prevent. Every caller here bottoms out in a Click CLI command or a pytest
    fixture, never a running event loop, so ``asyncio.run`` is safe at every call
    site.

    *timeout* maps onto the async primitive's ``term_timeout`` - the SIGTERM/
    graceful-wait budget - and :data:`_KILL_ESCALATION_WAIT` is passed
    explicitly as ``kill_timeout`` (the SIGKILL-escalation budget) rather than
    left to the async default, so this seam states its own second phase instead
    of silently inheriting whatever the async side happens to default to.
    """
    return asyncio.run(
        kill_pid_tree_async(
            pid, term_timeout=timeout, kill_timeout=_KILL_ESCALATION_WAIT
        )
    )


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
    flags = detached_spawn_kwargs()
    try:
        return subprocess.Popen(
            command,
            cwd=str(cwd),
            stdout=stdout,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=flags.creationflags,
            start_new_session=flags.start_new_session,
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
    cwd = build_cwd_for(record)
    result = subprocess.run(role.build, cwd=str(cwd), check=False)
    if result.returncode != 0:
        raise LifecycleError(
            f"build for {record.role}-{record.name} failed "
            f"(exit {result.returncode}): {' '.join(role.build)}"
        )
    sha = build_sha(cwd)
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
    ensure_explicit_repo(role, record.repo, f"{record.role}-{record.name}")
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
        cwd = build_cwd_for(record)
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


class _ServeUpOptions(TypedDict, total=False):
    workspace: str
    repo: str
    build_repo: str
    engine_service_json: str
    internal_token_file: str
    gateway_url: str
    worker_url: str
    owner: str | None
    log_path: str | None
    ready_timeout: float
    home: Path | None
    config: ProcsConfig | None


def _serve_config(options: _ServeUpOptions) -> ProcsConfig:
    configured = options.get("config")
    return configured if configured is not None else load_procs_config()


def _serve_owner(options: _ServeUpOptions) -> str:
    owner = options.get("owner")
    return owner if owner is not None else default_procs_owner()


def serve_up(
    role: str,
    name: str,
    **options: Unpack[_ServeUpOptions],
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

    resolved_config = _serve_config(options)
    role_cfg = resolved_config.role(role)
    if not role_cfg.serve:
        raise LifecycleError(f"role {role!r} declares no serve command in procs.toml")
    ensure_explicit_repo(role_cfg, options.get("repo", ""), f"{role}-{name}")
    owner_label = _serve_owner(options)
    cwd = _Path(options.get("repo", "")) if options.get("repo", "") else default_repo()
    # The build tree captured for rebuild/rerun; the boot build_sha reflects it, not
    # the serve tree, when a role's build and serve repos differ (engine-dev).
    build_cwd = (
        _Path(options.get("build_repo", "")) if options.get("build_repo", "") else cwd
    )
    max_attempts = role_cfg.band.end - role_cfg.band.start + 1
    held: list[PortReservation] = []
    try:
        for _ in range(max_attempts):
            reservation = reserve_port(
                role, role_cfg, home=options.get("home"), config=resolved_config
            )
            held.append(reservation)
            command = render_command(
                role_cfg.serve,
                port=reservation.port,
                workspace=options.get("workspace", ""),
            )
            child_env = serve_env(
                role_cfg,
                port=reservation.port,
                workspace=options.get("workspace", ""),
                name=name,
                owner=owner_label,
                engine_service_json=options.get("engine_service_json", ""),
                internal_token_file=options.get("internal_token_file", ""),
                gateway_url=options.get("gateway_url", ""),
                worker_url=options.get("worker_url", ""),
            )
            process = spawn(
                command, cwd=cwd, log_path=options.get("log_path"), env=child_env
            )
            if _await_listener(
                reservation.port,
                process,
                timeout=options.get("ready_timeout", 20.0),
                health_probe=_health_probe_for(
                    role_cfg, reservation.port, options.get("internal_token_file", "")
                ),
            ):
                stamp = now_ms()
                record = ProcRecord(
                    name=name,
                    role=role,
                    pid=process.pid,
                    port=reservation.port,
                    repo=str(cwd) if options.get("repo", "") else "",
                    build_repo=options.get("build_repo", ""),
                    workspace=options.get("workspace", ""),
                    build_sha=build_sha(build_cwd),
                    command=command,
                    started_at_ms=stamp,
                    last_seen_ms=stamp,
                    log_path=options.get("log_path"),
                    owner=owner_label,
                    engine_service_json=options.get("engine_service_json", ""),
                    internal_token_file=options.get("internal_token_file", ""),
                    gateway_url=options.get("gateway_url", ""),
                    worker_url=options.get("worker_url", ""),
                )
                try:
                    commit_reservation(reservation, record, home=options.get("home"))
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
            #
            # Logged, not just retried. A boot that fails on every band port used to
            # produce a structured log with no error and no warning in it: the
            # per-attempt failures were silent and the terminal one reached only the
            # caller's stderr as a traceback, so the file an operator actually reads
            # recorded a clean boot sequence for a gateway that never came up.
            logger.warning(
                "band port did not yield a live listener; trying the next",
                extra={
                    "role": role,
                    "proc_name": name,
                    "port": reservation.port,
                    "child_pid": process.pid,
                    "ready_timeout_s": options.get("ready_timeout", 20.0),
                },
            )
            tree_kill(process.pid)
        detail = (
            f"could not bring up {role}-{name}: no band port yielded a live listener"
        )
        # Logged BEFORE the raise, because the raise is what the caller may turn into
        # a bare traceback on stderr - and stderr is not the lane an operator greps.
        logger.error(
            detail,
            extra={
                "role": role,
                "proc_name": name,
                "band_start": role_cfg.band.start,
                "band_end": role_cfg.band.end,
                "attempts": max_attempts,
            },
        )
        raise LifecycleError(detail)
    finally:
        _release_held_reservations(held)


def _release_held_reservations(held: list[PortReservation]) -> None:
    for reservation in held:
        release_reservation(reservation)


def _worker_auth_headers(
    *, is_worker: bool, internal_token_file: str, label: str
) -> dict[str, str]:
    """The bearer header a worker's private ``status`` probe presents, if any.

    A gateway probe (the public ``ready`` fact) never carries this header; only a
    worker boot with a token file on record does, so a credentialed probe is never
    sent to a listener whose role has no such file.
    """
    if not (is_worker and internal_token_file):
        return {}
    token = read_internal_token(internal_token_file, label=label)
    return {"Authorization": f"Bearer {token}"}


def _health_payload_is_ready(payload: object, *, is_gateway: bool) -> bool:
    """Whether a parsed ``/health`` JSON body proves THIS role is ready."""
    if not isinstance(payload, dict):
        return False
    body = cast("dict[str, object]", payload)
    if is_gateway:
        return body.get("service") == "gateway" and body.get("ready") is True
    return body.get("service") == "worker" and body.get("status") == "ok"


def _probe_health(
    port: int, *, headers: dict[str, str], is_gateway: bool, request_timeout: float
) -> bool:
    """One bounded ``GET /health``, reduced to a readiness bool."""
    try:
        response = httpx.get(
            f"http://127.0.0.1:{port}/health",
            headers=headers,
            timeout=request_timeout,
        )
    except httpx.HTTPError:
        return False
    if response.status_code != 200:
        return False
    try:
        payload = response.json()
    except ValueError:
        return False
    return _health_payload_is_ready(payload, is_gateway=is_gateway)


def _health_probe_for(
    role_cfg: RoleConfig,
    port: int,
    internal_token_file: str,
) -> Callable[[float], bool] | None:
    """Return the bounded HTTP readiness probe required by an A2A serve role.

    The committed role environment identifies the two A2A HTTP servers without
    making arbitrary registry roles pretend to expose an HTTP surface. Gateway
    readiness is the public ``ready`` fact; worker readiness is its private
    ``status`` fact and therefore presents the paired IPC credential when one
    was supplied for the boot.
    """
    is_gateway = "VAULTSPEC_PORT" in role_cfg.env
    is_worker = "VAULTSPEC_WORKER_PORT" in role_cfg.env
    if not (is_gateway or is_worker):
        return None

    headers = _worker_auth_headers(
        is_worker=is_worker,
        internal_token_file=internal_token_file,
        label=role_cfg.name,
    )

    def _probe(request_timeout: float) -> bool:
        return _probe_health(
            port,
            headers=headers,
            is_gateway=is_gateway,
            request_timeout=request_timeout,
        )

    return _probe


class _UnresolvedOwnershipLogger:
    """Emits the ownership-unresolved warning at most once per ``_await_listener`` call.

    A racer or orphan can hold *port* through many poll iterations; logging on
    every iteration would flood the log with the same fact, so each outcome is
    reported once per await, on its first occurrence.
    """

    def __init__(self, port: int, pid: int) -> None:
        self._port = port
        self._pid = pid
        self._reported = False

    def bound_port_fallback(self) -> None:
        """A generic (non-HTTP) role accepted readiness on bound-port signal alone."""
        if self._reported:
            return
        logger.warning(
            "Readiness accepted port %d on the bound-port signal "
            "alone: the listening pid could not be resolved, so it "
            "was not confirmed to belong to pid %d. Ownership is "
            "unverified for this boot; an orphan or a racer "
            "holding the port would read as ready.",
            self._port,
            self._pid,
        )
        self._reported = True

    def probe_withheld(self) -> None:
        """An A2A role withheld its HTTP probe pending resolved ownership."""
        if self._reported:
            return
        logger.warning(
            "Readiness withheld on port %d: the listening pid could "
            "not be resolved, so it was not confirmed to belong to "
            "pid %d; the HTTP health probe was skipped.",
            self._port,
            self._pid,
        )
        self._reported = True


def _listener_ready(
    port: int,
    process: subprocess.Popen[Any],
    *,
    deadline: float,
    health_probe: Callable[[float], bool] | None,
    unresolved_logger: _UnresolvedOwnershipLogger,
) -> bool:
    """One poll iteration's readiness verdict for *port*; ``False`` keeps waiting.

    Does not accept a bound port until the listening pid is confirmed to be the
    child or a descendant of it
    (:func:`~vaultspec_a2a.utils.process.listener_belongs_to`). A foreign holder
    of the port - an un-reaped orphan of a felled generation, or a racer on a
    fixed resume/rerun port - therefore never reads as our process being ready.
    """
    from ..utils._process_tree import ListenerOwnership, classify_listener_ownership

    if not _port_is_bound(port):
        return False
    ownership = classify_listener_ownership(port, process.pid)
    if ownership is ListenerOwnership.CONFIRMED:
        if health_probe is None:
            return True
        return health_probe(max(deadline - time.monotonic(), 0.001))
    if ownership is ListenerOwnership.UNRESOLVED:
        if health_probe is None:
            # Generic roles remain listener-only. Failing a legitimate boot
            # because a pid could not be read would change their settled
            # readiness contract, so retain the bound-port fallback while
            # reporting that ownership was unverified.
            unresolved_logger.bound_port_fallback()
            return True
        # A2A readiness is an HTTP claim, and a credentialed worker probe must
        # never be sent to a listener whose owner is unknown. Keep waiting
        # until the deadline so serve_up refuses to publish a record rather
        # than masking unresolved ownership as ours.
        unresolved_logger.probe_withheld()
    return False


def _await_listener(
    port: int,
    process: subprocess.Popen[Any],
    *,
    timeout: float,
    health_probe: Callable[[float], bool] | None = None,
) -> bool:
    """Wait for a live listener on *port* that OUR child owns.

    Returns ``False`` if the spawned child dies first, and does not accept a bound
    port until the listening pid is confirmed to be the child or a descendant of
    it (:func:`~vaultspec_a2a.utils.process.listener_belongs_to`). A foreign holder
    of the port - an un-reaped orphan of a felled generation, or a racer on a
    fixed resume/rerun port - therefore never reads as our process being ready, so
    a record is not published pointing at a listener we do not own. An A2A HTTP
    role additionally must satisfy *health_probe* within the same deadline.
    """
    deadline = time.monotonic() + timeout
    unresolved_logger = _UnresolvedOwnershipLogger(port, process.pid)
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        if _listener_ready(
            port,
            process,
            deadline=deadline,
            health_probe=health_probe,
            unresolved_logger=unresolved_logger,
        ):
            return True
        time.sleep(0.1)
    return False


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
    ensure_explicit_repo(role, record.repo, f"{record.role}-{record.name}")
    command = render_command(role.serve, port=record.port, workspace=record.workspace)
    child_env = serve_env(
        role,
        port=record.port,
        workspace=record.workspace,
        name=record.name,
        owner=record.owner or default_procs_owner(),
        engine_service_json=record.engine_service_json,
        internal_token_file=record.internal_token_file,
        gateway_url=record.gateway_url,
        worker_url=record.worker_url,
    )
    cwd = serve_cwd_for(record)
    process = spawn(command, cwd=cwd, log_path=record.log_path or None, env=child_env)
    if not _await_listener(
        record.port,
        process,
        timeout=ready_timeout,
        health_probe=_health_probe_for(role, record.port, record.internal_token_file),
    ):
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
        build_sha=build_sha(build_cwd_for(record)) or record.build_sha,
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
