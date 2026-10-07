"""Gateway and worker boots shared by the desktop ownership certifications.

Both certifications boot a real gateway through the production ``serve`` verb,
drive its first demand so it spawns the worker it owns, and start a second real
worker that no gateway spawned. They differ only in what they read off the two
workers, so the boot, the demand and the stranger are built here once.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, cast

import httpx

from ..control.config import setting_env
from ..testing import (
    DEFAULT_ATTACH_CREDENTIAL,
    ProgressDeadline,
    armed_gateway_env,
    booted_gateway,
    broker_gateway_env,
    gateway_run_verbs,
    seat_app_home,
    spawn_logged,
    status_and_json,
    wait_for,
)
from ..utils import bearer_header
from ..utils.runtime_exec import module_command

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from ..testing import WatchedProcess

__all__ = ["prepare_run", "serve_gateway", "spawn_stray_worker", "worker_health"]


@contextmanager
def serve_gateway(
    tmp_path: Path, *, auto_spawn: bool, desktop: bool = True
) -> Generator[tuple[Path, int, int, str]]:
    """Boot a real gateway through ``serve`` with an explicit execution profile.

    Yields ``(app_home, gateway_port, worker_port, base)``. The gateway process
    handle is deliberately not yielded: on Windows the virtual-environment
    interpreter is a launcher stub, so the spawned handle's pid is the launcher
    and not the gateway, and every ownership assertion reads the published
    records instead.
    """
    app_home = tmp_path / "app-home"
    seat_app_home(app_home)
    env = (
        armed_gateway_env(app_home, auto_spawn_worker=auto_spawn)
        if desktop
        else broker_gateway_env(
            app_home,
            gateway_token=DEFAULT_ATTACH_CREDENTIAL,
            auto_spawn_worker=auto_spawn,
        )
    )
    with booted_gateway(env, log_path=tmp_path / "gateway.log", script=None) as gateway:
        yield app_home, gateway.gateway_port, gateway.worker_port, gateway.base_url


def prepare_run(base: str, run_id: str) -> tuple[int, dict[str, Any]]:
    """Drive one authenticated prepare, which spawns the gateway-owned worker."""
    return status_and_json(gateway_run_verbs(base).prepare(run_id))


def spawn_stray_worker(
    app_home: Path,
    *,
    gateway_port: int,
    worker_port: int,
    secret: str,
    log_path: Path,
) -> WatchedProcess:
    """Start a real production worker that no gateway spawned.

    It holds the gateway-minted IPC *secret* over the same application home and
    derives the same gateway URL, so it matches the gateway's own worker on every
    credential and addressing fact. The two pairing variables are cleared so an
    inherited value from the test host cannot forge the evidence at issue.
    """
    env = armed_gateway_env(app_home, auto_spawn_worker=False)(
        gateway_port, worker_port
    )
    env["VAULTSPEC_A2A_INTERNAL_TOKEN"] = secret
    env.pop(setting_env("gateway_lifetime_id"), None)
    env.pop(setting_env("worker_generation"), None)
    return spawn_logged(
        module_command("vaultspec_a2a.worker"),
        name="stray worker",
        env=env,
        log_path=log_path,
    )


def worker_health(port: int, secret: str, *, timeout: float = 60.0) -> dict[str, Any]:
    """Await one real worker's authenticated health body on *port*."""
    last: object = None

    def _health() -> dict[str, Any] | None:
        nonlocal last
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(
                    f"http://127.0.0.1:{port}/health", headers=bearer_header(secret)
                )
        except httpx.HTTPError as exc:
            last = repr(exc)
            return None
        if resp.status_code != 200:
            last = resp.status_code
            return None
        body = resp.json()
        assert isinstance(body, dict), body
        return cast("dict[str, Any]", body)

    return wait_for(
        _health,
        deadline=ProgressDeadline(idle_window_s=timeout),
        interval_s=0.25,
        stalled=lambda: f"worker on port {port} never served health (last: {last})",
    )
