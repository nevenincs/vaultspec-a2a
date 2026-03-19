"""service group: start, stop, kill, status."""

from __future__ import annotations

__all__ = ["service"]

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import click
import httpx

_WINDOWS_DETACHED_FLAGS = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
    subprocess, "CREATE_NEW_PROCESS_GROUP", 0
)


def _runtime_dir() -> Path:
    """Return the repo-local runtime directory used for local service tracking."""
    runtime_dir = Path.cwd() / ".vault" / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    return runtime_dir


def _registry_path(runtime_dir: Path | None = None) -> Path:
    """Return the JSON registry file path for CLI-managed services.

    Args:
        runtime_dir: Optional explicit runtime directory. When ``None`` the
            default ``_runtime_dir()`` resolution is used. Pass an explicit
            path in tests to isolate registry state.
    """
    base = runtime_dir if runtime_dir is not None else _runtime_dir()
    return base / "services.json"


def _service_specs() -> dict[str, dict[str, Any]]:
    """Return the static service spec map."""
    from ..core.config import settings

    return {
        "gateway": {
            "module": "vaultspec_a2a.api.app:create_app",
            "host": settings.host,
            "port": settings.port,
            "health_path": "/health",
        },
        "worker": {
            "module": "vaultspec_a2a.worker.app:create_worker_app",
            "host": settings.worker_host,
            "port": settings.worker_port,
            "health_path": "/health",
        },
    }


def _load_registry(runtime_dir: Path | None = None) -> dict[str, Any]:
    """Load the runtime registry, returning an empty structure if missing."""
    path = _registry_path(runtime_dir)
    if not path.exists():
        return {"services": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"services": {}}


def _save_registry(registry: dict[str, Any], runtime_dir: Path | None = None) -> None:
    """Persist the runtime registry."""
    _registry_path(runtime_dir).write_text(
        json.dumps(registry, indent=2), encoding="utf-8"
    )


def _clear_service_record(service_name: str, runtime_dir: Path | None = None) -> None:
    """Remove a service entry from the registry."""
    registry = _load_registry(runtime_dir)
    registry.setdefault("services", {}).pop(service_name, None)
    _save_registry(registry, runtime_dir)


def _get_service_record(
    service_name: str, runtime_dir: Path | None = None
) -> dict[str, Any] | None:
    """Fetch a single service record from the registry."""
    return _load_registry(runtime_dir).get("services", {}).get(service_name)


def _is_pid_running(pid: int) -> bool:
    """Return True if the PID is alive."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _probe_health(host: str, port: int, path: str) -> tuple[bool, int | None]:
    """Probe the HTTP health endpoint for a tracked service."""
    try:
        resp = httpx.get(f"http://{host}:{port}{path}", timeout=2.0)
    except (httpx.ConnectError, httpx.ConnectTimeout):
        return False, None
    except httpx.HTTPError:
        return False, None
    return resp.is_success, resp.status_code


def _service_status(
    service_name: str, runtime_dir: Path | None = None
) -> dict[str, Any]:
    """Compute the tracked runtime status for one local service."""
    spec = _service_specs()[service_name]
    record = _get_service_record(service_name, runtime_dir)
    if record is None:
        return {
            "service": service_name,
            "status": "stopped",
            "tracked": False,
            "host": spec["host"],
            "port": spec["port"],
            "pid": None,
            "http_status": None,
            "message": "not tracked by vaultspec service",
        }

    pid = int(record["pid"])
    running = _is_pid_running(pid)
    healthy, http_status = _probe_health(
        str(record["host"]),
        int(record["port"]),
        spec["health_path"],
    )
    if not running:
        status = "pid-stale"
        message = "tracked PID is no longer running"
    elif healthy:
        status = "running-healthy"
        message = "service is responding to health checks"
    else:
        status = "running-unhealthy"
        message = "process is running but health endpoint is unavailable"
    return {
        "service": service_name,
        "status": status,
        "tracked": True,
        "host": record["host"],
        "port": record["port"],
        "pid": pid,
        "http_status": http_status,
        "message": message,
        "started_at": record.get("started_at"),
        "log_path": record.get("log_path"),
    }


def _write_service_record(
    service_name: str,
    *,
    pid: int,
    host: str,
    port: int,
    log_path: Path,
    runtime_dir: Path | None = None,
) -> None:
    """Store the service runtime metadata."""
    registry = _load_registry(runtime_dir)
    registry.setdefault("services", {})[service_name] = {
        "pid": pid,
        "host": host,
        "port": port,
        "started_at": time.time(),
        "launch_mode": "local-process",
        "log_path": str(log_path),
    }
    _save_registry(registry, runtime_dir)


def _spawn_service(service_name: str, host: str, port: int, log_level: str) -> int:
    """Start a service in the background and persist its runtime metadata."""
    spec = _service_specs()[service_name]
    rd = _runtime_dir()
    log_path = rd / f"{service_name}.log"
    with log_path.open("ab") as log_file:
        kwargs: dict[str, Any] = {
            "stdout": log_file,
            "stderr": subprocess.STDOUT,
            "stdin": subprocess.DEVNULL,
            "close_fds": True,
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = _WINDOWS_DETACHED_FLAGS
        else:
            kwargs["start_new_session"] = True
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                spec["module"],
                "--factory",
                "--host",
                host,
                "--port",
                str(port),
                "--log-level",
                log_level,
            ],
            **kwargs,
        )
    _write_service_record(
        service_name,
        pid=process.pid,
        host=host,
        port=port,
        log_path=log_path,
    )
    return process.pid


def _terminate_pid(pid: int, force: bool = False) -> None:
    """Stop a tracked process without relying on platform shell commands."""
    if not _is_pid_running(pid):
        return
    if sys.platform == "win32":
        sig = signal.SIGTERM if force else signal.CTRL_BREAK_EVENT
        try:
            os.kill(pid, sig)
            return
        except OSError:
            if not force:
                os.kill(pid, signal.SIGTERM)
                return
            raise
    os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)


def _graceful_http_shutdown(host: str, port: int, shutdown_path: str) -> bool:
    """Attempt a graceful HTTP shutdown.  Returns True if the request succeeded."""
    try:
        resp = httpx.post(
            f"http://{host}:{port}{shutdown_path}",
            timeout=5.0,
        )
        return resp.is_success
    except httpx.HTTPError:
        return False


def _stop_service(
    service_name: str, *, force: bool = False, runtime_dir: Path | None = None
) -> str:
    """Stop a tracked local service and clear its runtime record."""
    record = _get_service_record(service_name, runtime_dir)
    if record is None:
        return "not-tracked"
    pid = int(record["pid"])
    if not _is_pid_running(pid):
        _clear_service_record(service_name, runtime_dir)
        return "pid-stale"
    # Attempt a graceful HTTP shutdown before resorting to OS signals.
    # The worker exposes /admin/shutdown (no /api prefix); the gateway
    # exposes /api/admin/shutdown.  Each service uses its own path.
    if service_name == "worker":
        shutdown_path = "/admin/shutdown"
    else:
        shutdown_path = "/api/admin/shutdown"
    _graceful_http_shutdown(str(record["host"]), int(record["port"]), shutdown_path)
    _terminate_pid(pid, force=force)
    deadline = time.time() + 10.0
    while time.time() < deadline:
        if not _is_pid_running(pid):
            _clear_service_record(service_name, runtime_dir)
            return "stopped"
        time.sleep(0.2)
    if force:
        _clear_service_record(service_name, runtime_dir)
        return "stopped"
    _terminate_pid(pid, force=True)
    _clear_service_record(service_name, runtime_dir)
    return "forced"


@click.group()
def service() -> None:
    """Manage local gateway and worker processes.

    This command group only manages CLI-started local processes.
    Docker-managed services are out of scope.
    """


@service.command()
@click.argument(
    "target",
    required=False,
    default="all",
    type=click.Choice(["gateway", "worker", "all"], case_sensitive=False),
)
@click.option("--host", default=None, help="Bind host override for a single service.")
@click.option(
    "--port", default=None, type=int, help="Bind port override for a single service."
)
@click.option("--log-level", default=None, help="Uvicorn log level override.")
def start(
    target: str,
    host: str | None,
    port: int | None,
    log_level: str | None,
) -> None:
    """Start one or more local services in the background."""
    from ..core.config import settings

    target = target.lower()
    level = (log_level or settings.log_level.value).lower()
    targets = ["gateway", "worker"] if target == "all" else [target]
    if target == "all" and (host is not None or port is not None):
        raise click.UsageError("--host/--port overrides are only valid for one service")

    for service_name in targets:
        spec = _service_specs()[service_name]
        status = _service_status(service_name)
        if status["status"] in {"running-healthy", "running-unhealthy"}:
            click.echo(
                f"{service_name}: already tracked "
                f"(pid={status['pid']}, status={status['status']})"
            )
            continue
        if status["status"] == "pid-stale":
            _clear_service_record(service_name)

        bind_host = host or str(spec["host"])
        bind_port = int(port or spec["port"])
        pid = _spawn_service(service_name, bind_host, bind_port, level)
        click.echo(
            f"{service_name}: started local process pid={pid} on http://{bind_host}:{bind_port}"
        )


@service.command()
@click.argument(
    "target",
    required=False,
    default="all",
    type=click.Choice(["gateway", "worker", "all"], case_sensitive=False),
)
def stop(target: str) -> None:
    """Stop one or more tracked local services."""
    target = target.lower()
    targets = ["gateway", "worker"] if target == "all" else [target]
    for service_name in targets:
        result = _stop_service(service_name, force=False)
        click.echo(f"{service_name}: {result}")


@service.command()
@click.argument(
    "target",
    required=False,
    default="all",
    type=click.Choice(["gateway", "worker", "all"], case_sensitive=False),
)
def kill(target: str) -> None:
    """Force-stop one or more tracked local services."""
    target = target.lower()
    targets = ["gateway", "worker"] if target == "all" else [target]
    for service_name in targets:
        result = _stop_service(service_name, force=True)
        click.echo(f"{service_name}: {result}")


@service.command()
@click.option("--json", "emit_json", is_flag=True, help="Emit machine-readable JSON.")
def status(emit_json: bool) -> None:
    """Report tracked local service status.

    Services started outside `vaultspec service` are intentionally not treated
    as managed by this command.
    """
    statuses = [_service_status("gateway"), _service_status("worker")]
    if emit_json:
        click.echo(json.dumps({"services": statuses}, indent=2))
        return
    for item in statuses:
        click.echo(
            f"{item['service']}: {item['status']} "
            f"(tracked={item['tracked']}, pid={item['pid']}, port={item['port']})"
        )
