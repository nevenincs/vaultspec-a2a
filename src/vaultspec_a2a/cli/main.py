"""The ``vaultspec-a2a`` operator CLI.

A minimal operator surface restored as a thin client of the gateway whitelist —
``serve``, ``doctor`` (service-state), ``presets`` (presets-list), and
``run start``/``status``/``cancel``. There is no second code path: every command
except ``serve`` is a plain HTTP call to the same ``/v1`` endpoints the engine
uses, so operator and engine exercise one surface. ``serve`` boots the existing
gateway app; it does not reimplement it.

The target gateway defaults to the resolved local ``gateway_url`` and is
overridable with ``--url`` for operators driving a non-default bind.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click
import httpx

from ..control.config import settings
from ..control.gateway_auth import (
    read_desktop_attach_credential,
    resolve_gateway_bearer,
)
from ..utils import configure_logging, package_version, reconfigure_console_utf8

if TYPE_CHECKING:
    from ..lifecycle.singleton import RuntimeSingleton

__all__ = ["main"]

_CONNECT_TIMEOUT = 10.0
_RUN_START_TIMEOUT = 30.0
# Distinct from the generic transport/HTTP-error exit (1, see _emit) and from
# click's own usage-error exit (2), so automation can tell "gateway answered
# but is a stale resident" apart from "gateway unreachable" or "bad CLI args".
_EXIT_STALE_RESIDENT = 3


def _base_url(url: str | None) -> str:
    """Resolve the gateway base URL: explicit ``--url`` or the local default."""
    return (url or settings.gateway_url).rstrip("/")


def _emit(response: httpx.Response) -> None:
    """Print a gateway JSON response and exit non-zero on an error status."""
    try:
        body: Any = response.json()
        rendered = json.dumps(body, indent=2, sort_keys=True)
    except ValueError:
        rendered = response.text
    click.echo(rendered)
    if response.is_error:
        sys.exit(1)


# The operator credential-resolution rule lives in the shared gateway-auth
# authority so this client and the standalone MCP adapter authenticate
# identically. The alias preserves the module-local name used by existing tests.
_read_desktop_attach_credential = read_desktop_attach_credential


def _request(method: str, url: str, **kwargs: Any) -> httpx.Response:
    """Issue one authenticated gateway request or report a transport failure.

    The bearer is resolved by the shared gateway-auth authority: a configured
    token is authoritative, then the armed desktop profile's owner-scoped attach
    credential, then a matching fresh resident discovery token - the latter two
    for a loopback target only. No secret is accepted as a command-line argument
    and a remote URL never receives a machine-local credential.
    """
    token = resolve_gateway_bearer(url)

    headers = dict(kwargs.pop("headers", {}))
    if token is not None:
        headers.setdefault("Authorization", f"Bearer {token}")
    try:
        return httpx.request(method, url, headers=headers, **kwargs)
    except httpx.HTTPError as exc:
        raise click.ClickException(
            f"could not reach the gateway at {url}: {exc}"
        ) from exc


@click.group()
@click.version_option(package_version(), "--version", "-V", prog_name="vaultspec-a2a")
def main() -> None:
    """Operator CLI for the vaultspec-a2a orchestration gateway."""
    # CLI lane: human diagnostics on stderr, stdout reserved for command output
    # and --json payloads. The serve subcommand reconfigures to the service lane
    # when it boots the gateway.
    reconfigure_console_utf8()
    configure_logging("cli")


def _acquire_desktop_singleton() -> RuntimeSingleton | None:
    """Acquire the desktop runtime singleton before the gateway binds, or fail loud.

    Ordering (per the desktop profile decision): the operating-system runtime
    singleton is taken over the explicit application home *before* the listener
    binds and *before* discovery is published, so two gateways can never own one
    application home. A live foreign or unverifiable resident is an immutable
    conflict — the caller must attach to it, not start a competitor — and this
    raises a loud, non-zero ``ClickException`` carrying the classification.

    Returns the held singleton (kept alive for the gateway's lifetime and released
    on shutdown) or ``None`` when the desktop profile is not armed. The versioned
    secret-free discovery record is published by the gateway lifetime after bind,
    schema validation, and control-auth setup; it reads this held singleton for
    its owner identity. That publication seam lands with the gateway credential
    work; acquisition and ownership registration are wired here now.
    """
    if not settings.desktop_profile_armed:
        return None
    return _acquire_singleton_for_serve(settings.a2a_home)


def _acquire_singleton_for_serve(app_home: Path) -> RuntimeSingleton:
    """Take the runtime singleton over *app_home* or fail loud with the conflict.

    Factored from :func:`_acquire_desktop_singleton` so the acquisition-and-fail
    path can be exercised against a real held application home without booting the
    gateway. Registers the held singleton as this process's active owner.
    """
    from ..lifecycle.singleton import (
        SingletonConflictError,
        acquire_singleton,
        set_active_singleton,
    )

    try:
        singleton = acquire_singleton(app_home)
    except SingletonConflictError as exc:
        raise click.ClickException(str(exc)) from exc
    set_active_singleton(singleton)
    return singleton


@main.command()
def serve() -> None:
    """Start the local gateway (boots the existing app; no second code path).

    Under the desktop profile the runtime singleton is acquired before the app
    boots so the socket bind and discovery publication follow sole-ownership; it
    is released when the gateway stops.
    """
    from ..api.app import main as serve_gateway

    singleton = _acquire_desktop_singleton()
    try:
        serve_gateway()
    finally:
        if singleton is not None:
            from ..lifecycle.singleton import clear_active_singleton

            singleton.release()
            clear_active_singleton()


@dataclass(frozen=True)
class _DesktopServePlan:
    """The armed environment and re-exec argv for a desktop gateway launch."""

    env: dict[str, str]
    argv: list[str]


def _prepare_desktop_serve(
    app_home: Path,
    capsule_root: Path,
    *,
    host: str | None,
    port: int | None,
) -> _DesktopServePlan:
    """Validate the desktop roots and build the armed serve re-exec plan.

    Resolves and fail-closed validates the profile (both roots absolute and
    distinct, the capsule carrying its runtime assets, the application home
    writable or creatable), materialises the mutable-state directories, and
    returns the environment that arms the desktop profile plus the argv that
    re-execs the existing ``serve`` path. Path resolution and gateway boot stay
    with the profile authority and the gateway; this only assembles the launch.

    Raises:
        DesktopProfileError: If either root or a required capsule asset is
            invalid.
    """
    from ..desktop.profile import DesktopProfile

    profile = DesktopProfile.resolve(app_home, capsule_root)
    profile.ensure()

    env = {
        "VAULTSPEC_DESKTOP_APP_HOME": str(profile.app_home),
        "VAULTSPEC_CAPSULE_ASSETS": str(profile.capsule_assets_root),
    }
    if host is not None:
        env["VAULTSPEC_HOST"] = host
    if port is not None:
        env["VAULTSPEC_PORT"] = str(port)
    argv = [sys.executable, "-m", "vaultspec_a2a.cli.main", "serve"]
    return _DesktopServePlan(env=env, argv=argv)


@main.command("desktop-serve")
@click.option(
    "--app-home",
    required=True,
    type=click.Path(path_type=Path),
    help="Explicit absolute mutable-state root for the desktop profile.",
)
@click.option(
    "--capsule-root",
    required=True,
    type=click.Path(path_type=Path),
    help="Explicit absolute immutable capsule (runtime asset) root.",
)
@click.option("--host", default=None, help="Override the gateway bind host.")
@click.option("--port", type=int, default=None, help="Override the gateway bind port.")
def desktop_serve(
    app_home: Path,
    capsule_root: Path,
    host: str | None,
    port: int | None,
) -> None:
    """Arm the desktop profile and start the gateway via the existing serve path.

    Seats every mutable path under the explicit application home and binds the
    capsule assets root, then re-execs ``serve`` in a freshly armed interpreter
    so the gateway boots with the desktop settings in force. Compose and plain
    ``serve`` invocations are unaffected; no run-control lifecycle verb is added.
    """
    from ..desktop.profile import DesktopProfileError

    try:
        plan = _prepare_desktop_serve(app_home, capsule_root, host=host, port=port)
    except DesktopProfileError as exc:
        raise click.ClickException(str(exc)) from exc

    os.environ.update(plan.env)
    os.execv(plan.argv[0], plan.argv)


@main.command("desktop-migrate")
@click.option(
    "--descriptor",
    required=True,
    type=click.Path(path_type=Path),
    help="Path to the one-time migration transaction descriptor JSON.",
)
def desktop_migrate(descriptor: Path) -> None:
    """Run the staged-generation desktop migration authorised by a descriptor.

    Internal external-updater command: it applies the packaged Alembic upgrade,
    checkpointer setup, and state-driven-development backfill against the
    descriptor's own stores, then prints the bounded machine-readable result as
    JSON to stdout. This lifecycle verb is deliberately CLI-only and is never
    exposed on the run-control HTTP API; the exit status is zero only when the
    migration succeeds.
    """
    import asyncio

    from ..desktop.migration import run_staged_migration

    result = asyncio.run(run_staged_migration(descriptor))
    click.echo(json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True))
    if result.status != "succeeded":
        sys.exit(1)


def _emit_snapshot_failure(operation: str, exc: Exception) -> None:
    """Print a bounded machine-readable snapshot failure and exit non-zero.

    The operator-facing detail names the offending store or descriptor so a
    failed updater transaction is actionable; the exit status carries the failure
    so automation need not parse the payload.
    """
    click.echo(
        json.dumps(
            {
                "status": "failed",
                "operation": operation,
                "error_class": type(exc).__name__,
                "detail": str(exc),
            },
            indent=2,
            sort_keys=True,
        )
    )
    sys.exit(1)


@main.command("desktop-snapshot-create")
@click.option(
    "--app-home",
    required=True,
    type=click.Path(path_type=Path),
    help="Explicit absolute mutable-state root for the desktop profile.",
)
@click.option(
    "--group-id",
    required=True,
    help="Single-component identity for the new snapshot group.",
)
def desktop_snapshot_create(app_home: Path, group_id: str) -> None:
    """Capture the desktop consistency group as one committed snapshot.

    Internal external-updater command: after quiescence it captures the primary
    and checkpoint stores as one receipt-verifiable group and prints the committed
    group descriptor as JSON to stdout. It refuses a live or locked store and a
    group id that is already committed. This lifecycle verb is CLI-only and is
    never exposed on the run-control HTTP API; the exit status is zero only when
    the group commits.
    """
    from ..desktop.snapshot import SnapshotError, create_snapshot

    try:
        descriptor = create_snapshot(app_home, group_id)
    except SnapshotError as exc:
        _emit_snapshot_failure("create", exc)
        return
    click.echo(json.dumps(descriptor.model_dump(mode="json"), indent=2, sort_keys=True))


@main.command("desktop-snapshot-inspect")
@click.option(
    "--app-home",
    required=True,
    type=click.Path(path_type=Path),
    help="Explicit absolute mutable-state root for the desktop profile.",
)
@click.option(
    "--group-id",
    required=True,
    help="Identity of the committed snapshot group to inspect.",
)
def desktop_snapshot_inspect(app_home: Path, group_id: str) -> None:
    """Print a committed snapshot group's descriptor after integrity-checking it.

    Internal external-updater command: it reports a group only when its descriptor
    is committed and every captured store still matches its recorded digest, and
    prints the descriptor as JSON to stdout. An uncommitted or corrupt group makes
    the command fail closed and exit non-zero. CLI-only; never HTTP-exposed.
    """
    from ..desktop.snapshot import SnapshotError, inspect_snapshot

    try:
        descriptor = inspect_snapshot(app_home, group_id)
    except SnapshotError as exc:
        _emit_snapshot_failure("inspect", exc)
        return
    click.echo(json.dumps(descriptor.model_dump(mode="json"), indent=2, sort_keys=True))


@main.command("desktop-snapshot-restore")
@click.option(
    "--app-home",
    required=True,
    type=click.Path(path_type=Path),
    help="Explicit absolute mutable-state root for the desktop profile.",
)
@click.option(
    "--group-id",
    required=True,
    help="Identity of the committed snapshot group to restore.",
)
@click.option(
    "--resume/--no-resume",
    "resume",
    default=False,
    help="Roll forward an interrupted restore instead of refusing.",
)
def desktop_snapshot_restore(app_home: Path, group_id: str, resume: bool) -> None:
    """Restore the desktop consistency group from a committed snapshot.

    Internal external-updater command: after quiescence it restores every group
    member from its verified captured copy under a quiesced-restore marker, then
    prints a bounded JSON result to stdout. It requires the quiesced condition and
    refuses a live or locked store; an interrupted restore is refused unless
    ``--resume`` is given, which rolls it forward deterministically. CLI-only;
    never HTTP-exposed. The exit status is zero only when the group is restored.
    """
    from ..desktop.snapshot import SnapshotError, restore_snapshot

    try:
        outcome = restore_snapshot(app_home, group_id, resume=resume)
    except SnapshotError as exc:
        _emit_snapshot_failure("restore", exc)
        return
    click.echo(
        json.dumps(
            {
                "status": "succeeded",
                "operation": "restore",
                "group_id": outcome.group_id,
                "restored": [store.value for store in outcome.restored],
                "resumed": outcome.resumed,
            },
            indent=2,
            sort_keys=True,
        )
    )


def _expected_route_signature() -> list[str]:
    """Return the route signature the installed source currently defines.

    Constructs the FastAPI app without running its lifespan (no DB or process
    I/O), so this is safe to call from a thin CLI command purely to read the
    route table off the code on disk.
    """
    from ..api.app import create_app
    from ..api.routes.gateway import route_signature

    return route_signature(create_app())


@main.command()
@click.option("--url", default=None, help="Gateway base URL (default: local).")
def doctor(url: str | None) -> None:
    """Report gateway health via the service-state verb.

    Also flags a stale resident: a gateway process has no hot-reload, so a
    process started before a route landed keeps serving the old route table
    and silently 404s callers of the new one. Diffs the live ``routes``
    signature against what the installed source on this machine expects and
    adds ``stale_resident``/``missing_routes`` to the reported body. A
    resident that predates this diagnostic itself (no ``routes`` key at all)
    is reported stale outright.

    Exit code carries the diagnosis, not just the JSON body, so automation
    catches a silent stale resident without parsing the response: 0 healthy,
    1 unreachable/HTTP error (see ``_emit``), 3 reachable but stale.
    """
    resp = _request("GET", f"{_base_url(url)}/v1/service", timeout=_CONNECT_TIMEOUT)
    try:
        body: Any = resp.json()
    except ValueError:
        body = None

    stale_resident = False
    if isinstance(body, dict):
        expected = set(_expected_route_signature())
        live = set(body["routes"]) if "routes" in body else set()
        missing = sorted(expected - live) if "routes" in body else sorted(expected)
        stale_resident = bool(missing)
        body["stale_resident"] = stale_resident
        body["missing_routes"] = missing
        click.echo(json.dumps(body, indent=2, sort_keys=True))
    else:
        click.echo(resp.text)
    if resp.is_error:
        sys.exit(1)
    if stale_resident:
        sys.exit(_EXIT_STALE_RESIDENT)


@main.command()
@click.option("--url", default=None, help="Gateway base URL (default: local).")
def presets(url: str | None) -> None:
    """List available team presets via the presets-list verb."""
    resp = _request("GET", f"{_base_url(url)}/v1/presets", timeout=_CONNECT_TIMEOUT)
    _emit(resp)


@main.group()
def run() -> None:
    """Start, inspect, and cancel runs via the run-* verbs."""


@run.command("start")
@click.option("--preset", required=True, help="Team preset id.")
@click.option("--message", required=True, help="Opening message for the run.")
@click.option("--title", default=None, help="Optional run title.")
@click.option(
    "--autonomous/--supervised",
    "autonomous",
    default=None,
    help="Override the preset's autonomy default.",
)
@click.option("--url", default=None, help="Gateway base URL (default: local).")
def run_start(
    preset: str,
    message: str,
    title: str | None,
    autonomous: bool | None,
    url: str | None,
) -> None:
    """Start a run via the run-start verb."""
    body: dict[str, Any] = {"team_preset": preset, "message": message}
    if title is not None:
        body["title"] = title
    if autonomous is not None:
        body["autonomous"] = autonomous
    resp = _request(
        "POST", f"{_base_url(url)}/v1/runs", json=body, timeout=_RUN_START_TIMEOUT
    )
    _emit(resp)


@run.command("status")
@click.argument("run_id")
@click.option("--url", default=None, help="Gateway base URL (default: local).")
def run_status(run_id: str, url: str | None) -> None:
    """Fetch a run's recovery snapshot via the run-status verb."""
    resp = _request(
        "GET", f"{_base_url(url)}/v1/runs/{run_id}", timeout=_CONNECT_TIMEOUT
    )
    _emit(resp)


@run.command("cancel")
@click.argument("run_id")
@click.option("--url", default=None, help="Gateway base URL (default: local).")
def run_cancel(run_id: str, url: str | None) -> None:
    """Cancel a run via the run-cancel verb (idempotent)."""
    resp = _request(
        "POST", f"{_base_url(url)}/v1/runs/{run_id}/cancel", timeout=_CONNECT_TIMEOUT
    )
    _emit(resp)


@main.group()
def workspace() -> None:
    """Provision and verify a run workspace's agent harness."""


@workspace.command("provision")
@click.argument(
    "path",
    type=click.Path(file_okay=False, path_type=Path),
    default=".",
    required=False,
)
@click.option(
    "--verify-only",
    is_flag=True,
    help="Verify an already-provisioned workspace; skip vaultspec-core install.",
)
def workspace_provision(path: Path, verify_only: bool) -> None:
    """Install the vaultspec framework into PATH and verify its agent harness.

    Wraps ``vaultspec-core install`` plus the harness verifier and reports the
    verdict, any version skew, and each missing surface. Exits non-zero when the
    harness is incomplete so a caller can gate on provisioning.
    """
    from .provision import ProvisionError, provision_workspace

    try:
        result = provision_workspace(path, install=not verify_only)
    except ProvisionError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(result.install_summary)
    if result.version_skew is not None:
        click.echo(f"WARNING: {result.version_skew}")
    if result.harness.ready:
        click.echo(f"harness ready: {path}")
    else:
        click.echo(f"harness INCOMPLETE: {path}")
        for reason in result.harness.reasons:
            click.echo(f"  - {reason}")
        sys.exit(1)


@main.group()
def procs() -> None:
    """Manage machine-global dev processes via the registry."""


def _lifecycle_error(exc: Exception) -> click.ClickException:
    from ..lifecycle.manager import LifecycleError
    from ..lifecycle.procs_config import ProcsConfigError

    if isinstance(exc, (LifecycleError, ProcsConfigError)):
        return click.ClickException(str(exc))
    raise exc


@procs.command("list")
def procs_list() -> None:
    """List every registered process with its liveness verdict and endpoint."""
    from ..lifecycle.manager import list_verdicts

    verdicts = list_verdicts()
    if not verdicts:
        click.echo("no registered processes")
        return
    for verdict in verdicts:
        rec = verdict.record
        click.echo(
            f"{verdict.state.value.upper():5} {rec.role}-{rec.name} "
            f"pid={rec.pid} {verdict.endpoint} owner={rec.owner or '-'}"
        )


@procs.command("attach")
@click.argument("name")
def procs_attach(name: str) -> None:
    """Verify a process is live on its recorded port and print its endpoint."""
    from ..lifecycle.manager import attach

    try:
        verdict = attach(name)
    except Exception as exc:
        raise _lifecycle_error(exc) from exc
    click.echo(verdict.endpoint)


@procs.command("kill")
@click.argument("name")
def procs_kill(name: str) -> None:
    """Tree-kill a process and remove its record."""
    from ..lifecycle.manager import kill

    try:
        record = kill(name)
    except Exception as exc:
        raise _lifecycle_error(exc) from exc
    click.echo(f"killed {record.role}-{record.name} (pid {record.pid})")


@procs.command("rebuild")
@click.argument("name")
def procs_rebuild(name: str) -> None:
    """Run the role's build command from procs.toml."""
    from ..lifecycle.manager import rebuild

    try:
        sha = rebuild(name)
    except Exception as exc:
        raise _lifecycle_error(exc) from exc
    click.echo(f"rebuilt {name}" + (f" @ {sha}" if sha else ""))


@procs.command("rerun")
@click.argument("name")
def procs_rerun(name: str) -> None:
    """Kill, rebuild, and restart a process on the same port and workspace."""
    from ..lifecycle.manager import rerun

    try:
        record = rerun(name)
    except Exception as exc:
        raise _lifecycle_error(exc) from exc
    click.echo(f"reran {record.role}-{record.name} (pid {record.pid})")


@procs.command("resume")
@click.argument("name")
def procs_resume(name: str) -> None:
    """Restart a died record's process on its original port and workspace."""
    from ..lifecycle.manager import resume

    try:
        record = resume(name)
    except Exception as exc:
        raise _lifecycle_error(exc) from exc
    click.echo(f"resumed {record.role}-{record.name} (pid {record.pid})")


@procs.command("reap")
def procs_reap() -> None:
    """Kill and clear every stale or dead record."""
    from ..lifecycle.manager import reap

    reaped = reap()
    if not reaped:
        click.echo("nothing to reap")
        return
    for record in reaped:
        click.echo(f"reaped {record.role}-{record.name} (pid {record.pid})")


@procs.command("up")
@click.argument("role")
@click.argument("name")
@click.option(
    "--workspace", default="", help="Workspace path recorded for the process."
)
@click.option(
    "--repo", default="", help="Repo dir to serve from (default: project root)."
)
@click.option(
    "--build-repo",
    "build_repo",
    default="",
    help="Repo dir to build from when it differs from --repo (e.g. the engine "
    "cargo workspace). Recorded per process; defaults to --repo.",
)
@click.option(
    "--engine-service-json",
    "engine_service_json",
    default="",
    help="Path to the engine's service.json (VAULTSPEC_ENGINE_SERVICE_JSON) for a "
    "worker's engine discovery. Recorded per process and re-injected on "
    "resume/rerun so an engine reseat cannot strand the worker.",
)
@click.option(
    "--internal-token-file",
    "internal_token_file",
    default="",
    help="Path to a file holding the internal-IPC token. Recorded per process (the "
    "PATH, never the token) and read at boot to inject VAULTSPEC_INTERNAL_TOKEN, so "
    "a procs-managed gateway-dev and worker-dev share one token. Boot fails loudly "
    "if the file is missing or empty.",
)
@click.option(
    "--gateway-url",
    "gateway_url",
    default="",
    help="Paired gateway base URL (VAULTSPEC_GATEWAY_URL) a worker heartbeats to. "
    "Recorded per process so the worker targets the dev gateway rather than "
    "auto-deriving the owner's resident gateway.",
)
@click.option(
    "--worker-url",
    "worker_url",
    default="",
    help="Paired worker base URL (VAULTSPEC_WORKER_URL) a gateway dispatches to. "
    "Recorded per process so the gateway targets the dev worker rather than "
    "auto-deriving the owner's resident worker (port 18001).",
)
@click.option(
    "--log", "log_path", default=None, help="Append process output to this file."
)
def procs_up(
    role: str,
    name: str,
    workspace: str,
    repo: str,
    build_repo: str,
    engine_service_json: str,
    internal_token_file: str,
    gateway_url: str,
    worker_url: str,
    log_path: str | None,
) -> None:
    """Allocate a band port, boot the role's serve command, and register it.

    The race-free boot verb: reserves a band port, spawns ROLE's serve command
    from procs.toml, waits for a live listener, then registers the process. Two
    concurrent same-band boots can never collide on a port. ``--build-repo``
    captures a build tree distinct from the serve tree (engine-dev) into the
    record so rebuild/rerun run cargo where the workspace actually lives.
    ``--engine-service-json`` pins a worker's engine discovery file into the
    record so resume/rerun reproduce it rather than leaning on shell state.
    ``--internal-token-file`` and ``--gateway-url`` pin the worker<->gateway
    pairing (shared IPC token and target gateway) into the record so both agree.
    """
    from ..lifecycle.manager import endpoint_for, serve_up

    try:
        record = serve_up(
            role,
            name,
            workspace=workspace,
            repo=repo,
            build_repo=build_repo,
            engine_service_json=engine_service_json,
            internal_token_file=internal_token_file,
            gateway_url=gateway_url,
            worker_url=worker_url,
            log_path=log_path,
        )
    except Exception as exc:
        raise _lifecycle_error(exc) from exc
    click.echo(
        f"up {record.role}-{record.name} pid={record.pid} {endpoint_for(record)}"
    )


@procs.command("allocate")
@click.argument("role")
def procs_allocate(role: str) -> None:
    """Reserve and print the next free band port for ROLE (marker held ~30s).

    For callers that boot their own process: prints a band port with an exclusive
    reservation so a concurrent allocator cannot pick the same one. Register the
    process (or let the reservation lapse) once bound.
    """
    from ..lifecycle.manager import _load_config_or_empty
    from ..lifecycle.registry import reserve_port

    config = _load_config_or_empty()
    try:
        role_cfg = config.role(role)
        reservation = reserve_port(role, role_cfg, config=config)
    except Exception as exc:
        raise _lifecycle_error(exc) from exc
    click.echo(str(reservation.port))


if __name__ == "__main__":
    main()
