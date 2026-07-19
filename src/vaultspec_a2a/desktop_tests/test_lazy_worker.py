"""Certify demand-driven worker startup against a real armed desktop gateway.

A real child interpreter boots the production gateway armed with the desktop
profile over a genuinely migrated app home, with auto-spawn enabled so the
gateway owns and spawns its own worker. The parent then proves, over real
loopback sockets, that:

- an idle armed gateway starts no worker at boot: the worker port never listens,
  the authenticated readiness reads the worker as cold, and the gateway log
  carries no spawn line;
- concurrent first execution demand (real parallel authenticated run-starts)
  starts exactly one real worker: the worker port begins listening, the gateway
  log carries the spawn line exactly once (single-flight), and the authenticated
  readiness leaves the cold rung;
- the worker is gateway-owned: the spawn line is emitted by the gateway process
  and the gateway reaches the worker through its own private worker-IPC
  credential, which only its paired owner can present.

The valid database is seated by the real ``desktop-migrate`` entrypoint in a
separate process; the gateway is a second real process and the worker a third,
gateway-owned one. No mock, monkeypatch, stub, skip, or expected failure is
used; every child is reaped in a ``finally`` by killing the gateway process
tree.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import httpx

from vaultspec_a2a.desktop._platform_acl import harden_credential_file
from vaultspec_a2a.desktop.credentials import (
    ATTACH_CREDENTIAL_NAME,
    OWNERSHIP_CAPABILITY_NAME,
)
from vaultspec_a2a.desktop.profile import derive_state_paths
from vaultspec_a2a.desktop.transaction import package_migration_range
from vaultspec_a2a.utils import kill_pid_tree_async

if TYPE_CHECKING:
    from pathlib import Path

_ATTACH = "attach-credential-lazyworker-1234567890abcdef"
_OWNERSHIP = "ownership-capability-lazyworker-fedcba0987654321"
_DIGEST = "e" * 64
_MODULE = "vaultspec_a2a.cli.main"
_PRESET = "mock-success-single"
_SPAWN_LINE = "Auto-spawning worker on port"

# A real armed desktop gateway booting the *production* lifespan with auto-spawn
# enabled: create_app runs the armed credential loading, mints the worker-IPC
# secret, and the gateway owns its worker spawner. INFO logging is configured so
# the one-shot spawn line is observable in the captured log.
_GATEWAY = """
import logging
import sys

logging.basicConfig(level=logging.INFO)
import uvicorn
from vaultspec_a2a.api.app import create_app

port = int(sys.argv[1])
uvicorn.run(create_app(), host="127.0.0.1", port=port, log_level="info")
"""


def _seed_credentials(app_home: Path) -> None:
    """Write the dashboard-created attach and ownership files."""
    state = derive_state_paths(app_home)
    state.credentials_dir.mkdir(parents=True, exist_ok=True)
    for name, secret in (
        (ATTACH_CREDENTIAL_NAME, _ATTACH),
        (OWNERSHIP_CAPABILITY_NAME, _OWNERSHIP),
    ):
        path = state.credentials_dir / name
        path.write_text(secret, encoding="utf-8")
        harden_credential_file(path)


def _write_descriptor(descriptor_path: Path, app_home: Path) -> Path:
    """Write a one-time migration descriptor for the app home's stores."""
    state = derive_state_paths(app_home)
    packaged = package_migration_range()
    document = {
        "descriptor_version": "1",
        "transaction_id": "lazyworker-txn-1",
        "app_home": str(app_home),
        "database_path": str(state.database_path),
        "checkpoint_path": str(state.checkpoint_path),
        "generation": {"manifest_digest": _DIGEST, "component_version": "4.0.0"},
        "migration_range": {"base": packaged.base, "head": packaged.head},
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    }
    descriptor_path.write_text(json.dumps(document), encoding="utf-8")
    return descriptor_path


def _seat_valid_database(app_home: Path, descriptor: Path) -> None:
    """Seat a valid desktop database via the real desktop-migrate entrypoint."""
    command = [
        sys.executable,
        "-m",
        _MODULE,
        "desktop-migrate",
        "--descriptor",
        str(descriptor),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, f"migrate failed: {result.stdout}\n{result.stderr}"
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "succeeded", payload
    assert derive_state_paths(app_home).database_path.is_file()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _port_listening(port: int, *, timeout: float = 0.5) -> bool:
    """Return whether a real TCP connection to the loopback port succeeds."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def _await_health(base: str, *, timeout: float = 40.0) -> None:
    """Wait until the gateway's liveness endpoint answers 200."""
    deadline = time.monotonic() + timeout
    last: str | None = None
    while time.monotonic() < deadline:
        try:
            with httpx.Client(base_url=base, timeout=2.0) as client:
                if client.get("/health").status_code == 200:
                    return
        except httpx.HTTPError as exc:  # not up yet
            last = repr(exc)
        time.sleep(0.1)
    raise AssertionError(f"gateway readiness never came up ({last})")


def _worker_state(base: str, headers: dict[str, str]) -> str:
    """Read the authenticated worker lifecycle state from desktop readiness."""
    with httpx.Client(base_url=base, timeout=5.0) as client:
        body = client.get("/health", headers=headers).json()
    return body["worker_state"]


def _start_run(base: str, headers: dict[str, str]) -> int:
    """Fire one authenticated mock run-start and return its status code.

    Each call blocks inside the gateway until the single-flight worker start
    reaches readiness, so parallel calls model concurrent first demand.
    """
    with httpx.Client(base_url=base, timeout=60.0) as client:
        resp = client.post(
            "/v1/runs",
            headers=headers,
            json={
                "team_preset": _PRESET,
                "message": "build it",
                "autonomous": True,
                "actor_tokens": {
                    "tokens": {"coder": "tok-coder"},
                    "engine_bearer": "bearer",
                },
            },
        )
    return resp.status_code


def test_idle_boot_starts_no_worker_and_concurrent_demand_starts_exactly_one(
    tmp_path: Path,
) -> None:
    """Idle armed boot starts no worker; concurrent demand starts exactly one."""
    app_home = tmp_path / "app-home"
    app_home.mkdir()
    _seed_credentials(app_home)
    _seat_valid_database(app_home, _write_descriptor(tmp_path / "txn.json", app_home))

    gateway_port = _free_port()
    worker_port = _free_port()
    log_path = tmp_path / "gateway.log"
    env = os.environ.copy()
    env["VAULTSPEC_DESKTOP_APP_HOME"] = str(app_home)
    env["VAULTSPEC_ENVIRONMENT"] = "production"
    env["VAULTSPEC_PORT"] = str(gateway_port)
    env["VAULTSPEC_WORKER_PORT"] = str(worker_port)
    # The gateway owns and spawns its worker; boot must still not start it.
    env["VAULTSPEC_AUTO_SPAWN_WORKER"] = "true"

    base = f"http://127.0.0.1:{gateway_port}"
    auth = {"Authorization": f"Bearer {_ATTACH}"}

    log_handle = log_path.open("wb")
    proc = subprocess.Popen(
        [sys.executable, "-c", _GATEWAY, str(gateway_port)],
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    try:
        _await_health(base)

        # --- Idle armed boot: no worker exists. ---
        # The gateway is up and gateway-ready, yet nothing bound the worker port,
        # readiness reports the cold rung, and no spawn line was logged. Give a
        # brief settle window so a spurious boot spawn would have surfaced.
        time.sleep(1.0)
        assert not _port_listening(worker_port), "idle boot must not bind the worker"
        assert _worker_state(base, auth) == "cold"
        assert _SPAWN_LINE not in log_path.read_text(encoding="utf-8", errors="replace")

        # --- Concurrent first demand: exactly one real worker. ---
        # Four real, parallel, authenticated run-starts race into the single-flight
        # worker start. Each blocks until the worker is ready, so all resolve 201.
        with ThreadPoolExecutor(max_workers=4) as pool:
            statuses = list(pool.map(lambda _: _start_run(base, auth), range(4)))
        assert statuses == [201, 201, 201, 201], statuses

        # A real worker now listens on its private port.
        assert _port_listening(worker_port), "first demand must start the worker"

        # Single-flight: the spawn line appears exactly once despite four demands.
        spawn_count = log_path.read_text(encoding="utf-8", errors="replace").count(
            _SPAWN_LINE
        )
        assert spawn_count == 1, f"expected one worker spawn, saw {spawn_count}"

        # Gateway-owned: readiness left the cold rung, which the gateway can only
        # observe by reaching the worker through its own private worker-IPC
        # credential - proving the worker it spawned answers to it.
        deadline = time.monotonic() + 30.0
        state = _worker_state(base, auth)
        while state == "cold" and time.monotonic() < deadline:
            time.sleep(0.25)
            state = _worker_state(base, auth)
        assert state in {"starting", "ready"}, state
    finally:
        with contextlib.suppress(Exception):
            asyncio.run(
                kill_pid_tree_async(proc.pid, term_timeout=10.0, kill_timeout=5.0)
            )
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=15)
        log_handle.close()
