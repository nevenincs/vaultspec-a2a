"""service group: start, stop, kill, status."""

from __future__ import annotations

__all__ = ["service"]

import click


@click.group()
def service() -> None:
    """Manage backend and worker processes."""


@service.command()
@click.argument(
    "target",
    required=False,
    default=None,
    type=click.Choice(["backend", "worker"], case_sensitive=False),
)
@click.option("--host", default=None, help="Bind host (default: from settings).")
@click.option("--port", default=None, type=int, help="Bind port (default: from settings).")
@click.option("--log-level", default=None, help="Uvicorn log level.")
def start(
    target: str | None,
    host: str | None,
    port: int | None,
    log_level: str | None,
) -> None:
    """Start backend or worker. Bare = start backend (worker auto-spawns via settings)."""
    import uvicorn

    from ..core.config import settings

    level = (log_level or settings.log_level.value).lower()

    if target is None or target == "backend":
        uvicorn.run(
            "vaultspec_a2a.api.app:create_app",
            factory=True,
            host=host or settings.host,
            port=port or settings.port,
            log_level=level,
        )
    elif target == "worker":
        uvicorn.run(
            "vaultspec_a2a.worker.app:create_worker_app",
            factory=True,
            host="127.0.0.1",
            port=port or settings.worker_port,
            log_level=level,
        )


@service.command()
@click.argument(
    "target",
    required=False,
    default=None,
    type=click.Choice(["backend", "worker"], case_sensitive=False),
)
def stop(target: str | None) -> None:
    """Gracefully stop backend and/or worker. Bare = stop both."""
    import httpx

    from ..core.config import settings

    # Backend shutdown is at /api/admin/shutdown (router prefix="/api").
    # Worker has no shutdown endpoint — use the same path as a best-effort.
    targets = (
        [(target, settings.port if target == "backend" else settings.worker_port)]
        if target
        else [("backend", settings.port), ("worker", settings.worker_port)]
    )
    for name, port in targets:
        try:
            httpx.post(f"http://127.0.0.1:{port}/api/admin/shutdown", timeout=5.0)
            click.echo(f"{name.capitalize()} shutdown initiated (port {port}).")
        except (httpx.ConnectError, httpx.ConnectTimeout):
            click.echo(f"{name.capitalize()} not running (port {port}).")
        except httpx.HTTPError as exc:
            click.echo(f"{name.capitalize()} shutdown failed: {exc}", err=True)


@service.command()
@click.argument("target", type=click.Choice(["backend", "worker"], case_sensitive=False))
def kill(target: str) -> None:
    """Force-kill a process by port."""
    import subprocess

    from ..core.config import settings

    port = settings.port if target == "backend" else settings.worker_port
    result = subprocess.run(
        [
            "powershell", "-Command",
            f"(Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue).OwningProcess",
        ],
        capture_output=True, text=True, check=False,
    )
    pids = set(result.stdout.strip().split("\n")) - {"", "0"}
    if not pids:
        click.echo(f"No process found on port {port}.")
        return
    for pid in pids:
        subprocess.run(["taskkill", "/F", "/PID", pid.strip()], check=False)
    click.echo(f"{target.capitalize()} killed (port {port}).")


@service.command()
def status() -> None:
    """Check if backend and worker are running."""
    import httpx

    from ..core.config import settings

    # Backend health is at /internal/health, worker at /health.
    checks = [
        ("backend", settings.port, "/internal/health"),
        ("worker", settings.worker_port, "/health"),
    ]
    for name, port, path in checks:
        try:
            resp = httpx.get(f"http://127.0.0.1:{port}{path}", timeout=2.0)
            click.echo(f"{name.capitalize()}: running (port {port}, HTTP {resp.status_code})")
        except (httpx.ConnectError, httpx.ConnectTimeout):
            click.echo(f"{name.capitalize()}: stopped (port {port})")
