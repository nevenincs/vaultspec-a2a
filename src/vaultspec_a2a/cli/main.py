"""The ``vaultspec-a2a`` operator CLI (ADR R9).

A minimal operator surface restored as a thin client of the five-verb gateway —
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
import sys
from typing import Any

import click
import httpx

from ..control.config import settings

__all__ = ["main"]

_CONNECT_TIMEOUT = 10.0
_RUN_START_TIMEOUT = 30.0


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


def _request(method: str, url: str, **kwargs: Any) -> httpx.Response:
    """Issue one gateway request, turning transport errors into a clean exit."""
    try:
        return httpx.request(method, url, **kwargs)
    except httpx.HTTPError as exc:
        raise click.ClickException(
            f"could not reach the gateway at {url}: {exc}"
        ) from exc


@click.group()
def main() -> None:
    """Operator CLI for the vaultspec-a2a orchestration gateway."""


@main.command()
def serve() -> None:
    """Start the local gateway (boots the existing app; no second code path)."""
    from ..api.app import main as serve_gateway

    serve_gateway()


@main.command()
@click.option("--url", default=None, help="Gateway base URL (default: local).")
def doctor(url: str | None) -> None:
    """Report gateway health via the service-state verb."""
    resp = _request("GET", f"{_base_url(url)}/v1/service", timeout=_CONNECT_TIMEOUT)
    _emit(resp)


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
def procs() -> None:
    """Manage machine-global dev processes via the registry (dev-process-registry)."""


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


if __name__ == "__main__":
    main()
