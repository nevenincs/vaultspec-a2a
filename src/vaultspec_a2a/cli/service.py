"""Service-management verbs for the dashboard-bundled runtime.

The dashboard manages a2a as a bundled service through six verbs on the
binary - ``setup``, ``start``, ``stop``, ``status``, ``restart``, and
``migrate`` - beside the existing foreground ``serve``. Everything here
composes the runtime's existing single-authority primitives rather than
opening a second code path:

- discovery: the ``service.json`` record and health probe from
  :mod:`vaultspec_a2a.lifecycle.discovery` decide liveness; nothing here
  parses records or probes ports on its own.
- process control: detached spawn and whole-tree kill come from
  :mod:`vaultspec_a2a.lifecycle.manager`.
- authentication: ``stop`` drains through the authenticated
  ``POST /admin/shutdown`` verb using the shared gateway-auth bearer
  resolution plus the receipt-bound lifecycle capability, and falls back to a
  tree kill only when the authenticated path is unavailable or hangs - the
  robust-stop contract for a machine-local owner.
- state: ``setup`` materialises the application home and initialises fresh
  stores through the desktop migration authority; ``migrate`` is the
  dashboard-spawnable upgrade step of the dashboard-owned update transaction
  (the dashboard drains, snapshots, and rolls back itself - a2a only executes
  the schema work), and ``migrate --compact`` is the operator's way to return
  the primary store's freed pages to the operating system.

Every verb is idempotent from the dashboard's perspective: starting a running
service, stopping a stopped one, and re-running setup against an initialised
home all succeed with a truthful state report instead of failing.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click
import httpx

from ..control.config import setting_env, settings
from ..control.state_layout import seal_state_home
from ..gateway_auth import gateway_auth_headers
from ..lifecycle.discovery import (
    DiscoveryState,
    another_resident_is_live,
    probe_health,
    read_resident_service,
)
from ..lifecycle.manager import spawn, tree_kill
from ..utils._process_tree import (
    PortClaim,
    classify_port_claim,
    pid_is_live,
    wait_pid_gone,
)
from ..utils.runtime_exec import self_command

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Callable

__all__ = [
    "ServiceVerbError",
    "StartOptions",
    "migrate_service",
    "register_service_commands",
    "restart_service",
    "service_status",
    "setup_service",
    "start_service",
    "stop_service",
]

_READY_TIMEOUT_SECONDS = 30.0
_STOP_TIMEOUT_SECONDS = 20.0
_SHUTDOWN_REQUEST_TIMEOUT_SECONDS = 5.0
_POLL_INTERVAL_SECONDS = 0.2
_PORT_PROBE_TIMEOUT_SECONDS = 1.0


class ServiceVerbError(RuntimeError):
    """A service-management verb could not complete."""


@dataclass(frozen=True, slots=True)
class ServiceStatus:
    """The resident gateway's observed state, bounded and JSON-serialisable.

    ``state`` is one of ``running`` (fresh record, live pid, healthy),
    ``unhealthy`` (live pid, no 200 health), ``stale`` (live pid behind a
    stale heartbeat), or ``stopped`` (no record, malformed record, or dead
    pid). The verdict composes the discovery classification with the pid and
    health probes; it never trusts the record alone.
    """

    state: str
    pid: int | None
    port: int | None
    healthy: bool
    base_url: str | None


def _resolved_app_home(app_home: Path | None) -> Path:
    return app_home if app_home is not None else settings.a2a_home


def service_status(app_home: Path | None = None) -> ServiceStatus:
    """Observe the resident gateway under *app_home* (default: the A2A home)."""
    home = _resolved_app_home(app_home)
    state, info = read_resident_service(home)
    if info is None or state is DiscoveryState.MALFORMED:
        return ServiceStatus(
            state="stopped", pid=None, port=None, healthy=False, base_url=None
        )
    base_url = f"http://127.0.0.1:{info.port}"
    if info.pid is None or not pid_is_live(info.pid):
        return ServiceStatus(
            state="stopped",
            pid=info.pid,
            port=info.port,
            healthy=False,
            base_url=base_url,
        )
    healthy = probe_health(base_url) is not None
    if state is DiscoveryState.STALE:
        verdict = "stale"
    else:
        verdict = "running" if healthy else "unhealthy"
    return ServiceStatus(
        state=verdict,
        pid=info.pid,
        port=info.port,
        healthy=healthy,
        base_url=base_url,
    )


def _desktop_arm_env(app_home: Path, capsule_root: Path) -> dict[str, str]:
    """Validate the desktop roots and return the armed child environment.

    Delegates root validation and directory materialisation to the desktop
    profile authority; failures raise its typed error unchanged so the caller
    reports the profile's own diagnosis.
    """
    from ..desktop.profile import DesktopProfile

    profile = DesktopProfile.resolve(app_home, capsule_root)
    profile.ensure()
    return {
        setting_env("desktop_app_home"): str(profile.app_home),
        setting_env("capsule_assets_root"): str(profile.capsule_assets_root),
    }


@dataclass(frozen=True, slots=True, kw_only=True)
class StartOptions:
    """How a started gateway is armed, bound, logged and gated on readiness."""

    capsule_root: Path | None = None
    host: str | None = None
    port: int | None = None
    log_path: str | None = None
    ready_timeout: float = _READY_TIMEOUT_SECONDS


def start_service(
    app_home: Path | None = None,
    options: StartOptions | None = None,
) -> ServiceStatus:
    """Start the gateway detached and wait until it is discoverably healthy.

    Idempotent: a live resident is reported as-is rather than contested (the
    runtime singleton would refuse a competitor anyway; this avoids even
    spawning one). Otherwise the existing ``serve`` path is spawned detached
    through the frozen-aware command authority, optionally desktop-armed via
    ``capsule_root``, and readiness is gated on the discovery record turning
    fresh with a live pid and an answering health endpoint. A spawn that dies
    or never becomes ready is felled and reported loudly - no half-started
    generation survives the verb.

    The readiness poll trusts the resident record rather than the spawned
    pid: on Windows a venv launcher stub means the recorded gateway pid can
    legitimately differ from the spawned child's pid.
    """
    options = options or StartOptions()
    home = _resolved_app_home(app_home)
    if another_resident_is_live(home):
        return service_status(home)
    # Pin the child's state home and project explicitly: discovery, state and
    # the singleton must land under the home THIS verb watches, and the child
    # starts outside the project's working directory (see below), so it must
    # not have to rediscover the project from where it was launched. Every
    # store then follows from the home through the one state layout, the same
    # one the desktop profile seats and setup initialises.
    seal_state_home(home)
    env: dict[str, str] = {
        setting_env("a2a_home"): str(home),
        setting_env("project_root"): str(settings.project_root),
    }
    if options.capsule_root is not None:
        env.update(_desktop_arm_env(home, options.capsule_root))
    if options.host is not None:
        env[setting_env("host")] = options.host
    if options.port is not None:
        env[setting_env("port")] = str(options.port)
    # Spawn from the home's PARENT, never from inside the home: a child whose
    # working directory sits inside the application home holds an open handle
    # on it, and the Windows directory lease the discovery publication takes
    # over the home then refuses - the gateway would boot and immediately die
    # publishing its own record.
    process: subprocess.Popen[bytes] = spawn(
        self_command("serve"),
        cwd=home.parent,
        log_path=options.log_path,
        env=env or None,
    )
    deadline = time.monotonic() + options.ready_timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            capture_hint = (
                f"see {options.log_path}"
                if options.log_path
                else "start with --log to capture output"
            )
            raise ServiceVerbError(
                f"gateway exited during startup "
                f"(exit {process.returncode}); {capture_hint}"
            )
        status = service_status(home)
        if status.state == "running":
            return status
        time.sleep(_POLL_INTERVAL_SECONDS)
    tree_kill(process.pid)
    raise ServiceVerbError(
        f"gateway pid {process.pid} did not become ready within "
        f"{options.ready_timeout:g}s; process felled and no record published"
    )


def _lifecycle_capability(app_home: Path) -> str | None:
    """Best-effort load of the receipt-bound lifecycle ownership capability.

    Present only under a dashboard-provisioned desktop home; a development
    resident has no ownership file, in which case ``stop`` proceeds without
    the capability header and relies on its kill fallback.
    """
    from ..desktop.credentials import CredentialError, load_ownership_capability
    from ..desktop.profile import derive_state_paths

    try:
        return load_ownership_capability(derive_state_paths(app_home).credentials_dir)
    except (CredentialError, OSError):
        return None


def _drain_owned_resident(
    home: Path, base_url: str, pid: int, *, timeout: float
) -> bool:
    """Ask the confirmed resident to drain; whether it then exited in *timeout*.

    Presents the attach bearer and, when this home carries one, the
    receipt-bound lifecycle capability. Reached only after the recorded process
    is confirmed to own the listener, so neither credential can land on a
    stranger.
    """
    headers = dict(gateway_auth_headers(base_url))
    capability = _lifecycle_capability(home)
    if capability is not None:
        from ..api.dependencies import LIFECYCLE_CAPABILITY_HEADER

        headers[LIFECYCLE_CAPABILITY_HEADER] = capability
    try:
        response = httpx.post(
            f"{base_url}/admin/shutdown",
            headers=headers,
            timeout=_SHUTDOWN_REQUEST_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError:
        return False
    return response.status_code == 202 and wait_pid_gone(pid, timeout=timeout)


def stop_service(
    app_home: Path | None = None,
    *,
    timeout: float = _STOP_TIMEOUT_SECONDS,
) -> ServiceStatus:
    """Stop the resident gateway: authenticated drain first, tree kill fallback.

    Idempotent: no record or a dead pid reports the stopped state without
    failing.

    A live recorded pid is not yet a resident this verb may address. The
    listener on the recorded endpoint must be held by that process or one of its
    descendants first; only then is it asked to drain through the authenticated
    ``/admin/shutdown`` verb, and only then may it be felled. When the
    authenticated path is unavailable, refused, or the process outlives
    *timeout*, the whole process tree is felled - a stop verb that can hang or
    silently fail would break the dashboard's restart contract.

    A recorded process that is alive while something ELSE holds the recorded
    endpoint is a conflict, not a target: a pid-reused record, a crashed resident
    whose port was taken, or an outright squatter all present this way, and none
    of them may receive the attach bearer or the lifecycle capability, nor be
    terminated on the strength of a record they do not match. That is reported as
    a typed failure. An endpoint nobody holds has no occupant to credential, so
    the recorded tree is felled directly.

    Raises :class:`ServiceVerbError` when the endpoint is held in conflict, or
    when the process survives even the tree kill.
    """
    home = _resolved_app_home(app_home)
    _, info = read_resident_service(home)
    if info is None or info.pid is None or not pid_is_live(info.pid):
        return service_status(home)
    claim = classify_port_claim(
        info.port, info.pid, timeout=_PORT_PROBE_TIMEOUT_SECONDS
    )
    if claim is PortClaim.OURS and _drain_owned_resident(
        home, f"http://127.0.0.1:{info.port}", info.pid, timeout=timeout
    ):
        return service_status(home)
    if claim not in (PortClaim.OURS, PortClaim.FREE):
        raise ServiceVerbError(
            f"recorded gateway pid {info.pid} does not own the listener on port "
            f"{info.port} (claim: {claim.value}); refusing to authenticate "
            "against it or fell it - resolve the conflicting process first"
        )
    if not tree_kill(info.pid):
        raise ServiceVerbError(
            f"gateway pid {info.pid} survived both the authenticated shutdown "
            "and a process-tree kill; manual intervention required"
        )
    return service_status(home)


def restart_service(
    app_home: Path | None = None,
    options: StartOptions | None = None,
    *,
    stop_timeout: float = _STOP_TIMEOUT_SECONDS,
) -> ServiceStatus:
    """Stop the resident (confirmed dead), then start ready-gated.

    The robust-restart contract: :func:`stop_service` returns only once the
    old pid is confirmed gone (or raises), so a replacement can never overlap
    a surviving generation on the same port; :func:`start_service` then
    publishes exactly one ready generation or fails loudly.
    """
    home = _resolved_app_home(app_home)
    stop_service(home, timeout=stop_timeout)
    return start_service(home, options)


def setup_service(
    app_home: Path | None = None,
    *,
    capsule_root: Path | None = None,
) -> dict[str, Any]:
    """Provision the application home and initialise fresh stores.

    Materialises the home (desktop-validated when *capsule_root* is given)
    and brings absent stores to the packaged schema head through the desktop
    migration authority. Idempotent: a home whose primary store already
    records a revision reports ``already-initialized`` instead of failing -
    upgrading an initialised home is the ``migrate`` verb, never setup.
    Returns the bounded JSON-ready result; ``status`` is ``succeeded``,
    ``already-initialized``, or ``failed``.
    """
    import asyncio

    from ..desktop.migration import initialize_fresh_stores

    home = _resolved_app_home(app_home)
    if capsule_root is not None:
        _desktop_arm_env(home, capsule_root)
    result = asyncio.run(initialize_fresh_stores(home))
    payload = result.model_dump(mode="json")
    payload["app_home"] = str(home)
    if result.status == "failed" and result.error_class == (
        "StoreAlreadyInitializedError"
    ):
        payload["status"] = "already-initialized"
    return payload


def migrate_service(
    app_home: Path | None = None,
    *,
    expect_from: str | None = None,
    expect_head: str | None = None,
    compact: bool = False,
) -> dict[str, Any]:
    """Upgrade the home's quiesced stores to the packaged schema head.

    The dashboard-spawnable migrate step of its own update transaction: the
    caller owns ordering (drain, snapshot, migrate, activate) and rollback
    (its snapshot); this verb only executes a2a's schema work through the
    desktop migration authority, refusing live or locked stores and failing
    closed on an ``expect_from``/``expect_head`` assertion mismatch. *compact*
    then truncates the primary store's write-ahead log and vacuums it, refusing
    while a service listens on a configured port. Returns the bounded JSON-ready
    result.
    """
    import asyncio

    from ..desktop.migration import migrate_stores

    home = _resolved_app_home(app_home)
    result = asyncio.run(
        migrate_stores(
            home, expect_from=expect_from, expect_head=expect_head, compact=compact
        )
    )
    payload = result.model_dump(mode="json")
    payload["app_home"] = str(home)
    return payload


# ---------------------------------------------------------------------------
# Click commands (thin formatters over the verb logic above)
# ---------------------------------------------------------------------------


def _emit_status(status: ServiceStatus) -> None:
    click.echo(json.dumps(asdict(status), indent=2, sort_keys=True))


def _launch(
    service: Callable[[Path | None, StartOptions], ServiceStatus],
    app_home: Path | None,
    options: StartOptions,
) -> None:
    """Run one ready-gated launch verb and report the state it left."""
    try:
        status = service(app_home, options)
    except Exception as exc:
        raise _service_error(exc) from exc
    _emit_status(status)


_APP_HOME_OPTION = click.option(
    "--app-home",
    type=click.Path(path_type=Path),
    default=None,
    help="Application home holding state and discovery (default: the A2A home).",
)
_CAPSULE_ROOT_OPTION = click.option(
    "--capsule-root",
    type=click.Path(path_type=Path),
    default=None,
    help="Immutable runtime-asset root; arms the desktop profile when given.",
)


@click.command("status")
@_APP_HOME_OPTION
def status_command(app_home: Path | None) -> None:
    """Report the resident gateway's state as JSON (exit 0 only when running)."""
    status = service_status(app_home)
    _emit_status(status)
    if status.state != "running":
        raise SystemExit(1)


@click.command("start")
@_APP_HOME_OPTION
@_CAPSULE_ROOT_OPTION
@click.option("--host", default=None, help="Override the gateway bind host.")
@click.option("--port", type=int, default=None, help="Override the gateway bind port.")
@click.option("--log", "log_path", default=None, help="Append gateway output here.")
def start_command(
    app_home: Path | None,
    capsule_root: Path | None,
    host: str | None,
    port: int | None,
    log_path: str | None,
) -> None:
    """Start the gateway detached; block until it is discoverably healthy."""
    _launch(
        start_service,
        app_home,
        StartOptions(
            capsule_root=capsule_root, host=host, port=port, log_path=log_path
        ),
    )


@click.command("stop")
@_APP_HOME_OPTION
def stop_command(app_home: Path | None) -> None:
    """Stop the resident gateway (authenticated drain, tree-kill fallback)."""
    try:
        status = stop_service(app_home)
    except Exception as exc:
        raise _service_error(exc) from exc
    _emit_status(status)


@click.command("restart")
@_APP_HOME_OPTION
@_CAPSULE_ROOT_OPTION
@click.option("--host", default=None, help="Override the gateway bind host.")
@click.option("--port", type=int, default=None, help="Override the gateway bind port.")
@click.option("--log", "log_path", default=None, help="Append gateway output here.")
def restart_command(
    app_home: Path | None,
    capsule_root: Path | None,
    host: str | None,
    port: int | None,
    log_path: str | None,
) -> None:
    """Restart the gateway: confirmed stop, then a ready-gated start."""
    _launch(
        restart_service,
        app_home,
        StartOptions(
            capsule_root=capsule_root, host=host, port=port, log_path=log_path
        ),
    )


@click.command("setup")
@_APP_HOME_OPTION
@_CAPSULE_ROOT_OPTION
def setup_command(app_home: Path | None, capsule_root: Path | None) -> None:
    """Provision the application home and initialise fresh stores (idempotent)."""
    try:
        payload = setup_service(app_home, capsule_root=capsule_root)
    except Exception as exc:
        raise _service_error(exc) from exc
    click.echo(json.dumps(payload, indent=2, sort_keys=True))
    if payload["status"] == "failed":
        raise SystemExit(1)


@click.command("migrate")
@_APP_HOME_OPTION
@click.option(
    "--expect-from",
    default=None,
    help="Refuse unless the primary store is at this Alembic revision.",
)
@click.option(
    "--expect-head",
    default=None,
    help="Refuse unless the packaged Alembic head is this revision.",
)
@click.option(
    "--compact",
    is_flag=True,
    default=False,
    help=(
        "After migrating, truncate the primary store's write-ahead log and run "
        "VACUUM; refused while a service listens on a configured port."
    ),
)
def migrate_command(
    app_home: Path | None,
    expect_from: str | None,
    expect_head: str | None,
    compact: bool,
) -> None:
    """Migrate quiesced stores to the packaged head (dashboard-spawnable)."""
    try:
        payload = migrate_service(
            app_home, expect_from=expect_from, expect_head=expect_head, compact=compact
        )
    except Exception as exc:
        raise _service_error(exc) from exc
    click.echo(json.dumps(payload, indent=2, sort_keys=True))
    if payload["status"] != "succeeded":
        raise SystemExit(1)


def _service_error(exc: Exception) -> click.ClickException:
    """Convert expected verb failures to loud, typed CLI errors."""
    from ..desktop.profile import DesktopProfileError

    if isinstance(exc, (ServiceVerbError, DesktopProfileError)):
        return click.ClickException(str(exc))
    raise exc


def register_service_commands(group: click.Group) -> None:
    """Attach the service-management verbs to the operator CLI group."""
    group.add_command(status_command)
    group.add_command(start_command)
    group.add_command(stop_command)
    group.add_command(restart_command)
    group.add_command(setup_command)
    group.add_command(migrate_command)
