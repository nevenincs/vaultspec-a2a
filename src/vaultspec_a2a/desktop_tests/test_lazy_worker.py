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

The valid database is seated by the real ``migrate`` entrypoint in a
separate process; the gateway is a second real process and the worker a third,
gateway-owned one. No mock, monkeypatch, stub, skip, or expected failure is
used; every child is reaped in a ``finally`` by killing the gateway process
tree.
"""

from __future__ import annotations

import itertools
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from ..tests.gateway_boot import (
    armed_gateway_env,
    gateway_script,
    reap_gateway,
    seat_valid_database,
    seed_credentials,
    spawn_gateway,
    spawn_until_ready,
)
from ._catalog import catalog_selection

if TYPE_CHECKING:
    import subprocess

_ATTACH = "attach-credential-lazyworker-1234567890abcdef"
_OWNERSHIP = "ownership-capability-lazyworker-fedcba0987654321"
_PRESET = "mock-success-single"
_SPAWN_LINE = "Auto-spawning worker on port"

# A real armed desktop gateway booting the *production* lifespan with auto-spawn
# enabled: create_app runs the armed credential loading, mints the worker-IPC
# secret, and the gateway owns its worker spawner. The INFO variant is required,
# not incidental: its root logging handler is the only reason the one-shot spawn
# line asserted on below reaches the captured log at all.
_GATEWAY = gateway_script(log_level="info")


def _port_listening(port: int, *, timeout: float = 0.5) -> bool:
    """Return whether a real TCP connection to the loopback port succeeds."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def _worker_state(base: str, headers: dict[str, str]) -> str:
    """Read the authenticated worker lifecycle state from desktop readiness."""
    with httpx.Client(base_url=base, timeout=5.0) as client:
        body = client.get("/health", headers=headers).json()
    return body["worker_state"]


_RUN_SEQ = itertools.count(1)


def _start_run(base: str, headers: dict[str, str]) -> int:
    """Fire one authenticated mock run-start and return its status code.

    Each call blocks inside the gateway until the single-flight worker start
    reaches readiness, so parallel calls model concurrent first demand.
    """
    workspace = str(Path.cwd())
    with httpx.Client(base_url=base, timeout=60.0) as client:
        resp = client.post(
            "/v1/runs",
            headers=headers,
            json={
                "team_preset": _PRESET,
                "message": "build it",
                "autonomous": True,
                # Distinct per call: these fire concurrently and the subject is
                # that ONE worker serves several runs. A shared id would make
                # the later calls replays of the first and prove nothing about
                # concurrent demand.
                "run_id": f"lazy-worker-{next(_RUN_SEQ):02d}",
                "actor_tokens": {
                    "tokens": {"coder": "tok-coder"},
                    "engine_bearer": "bearer",
                },
                # The workspace anchors the selection, which run start
                # revalidates against the catalog served for it.
                "metadata": {"workspace_root": workspace},
                "selection": catalog_selection(
                    base, headers["Authorization"], workspace
                ),
            },
        )
    return resp.status_code


def test_idle_boot_starts_no_worker_and_concurrent_demand_starts_exactly_one(
    tmp_path: Path,
) -> None:
    """Idle armed boot starts no worker; concurrent demand starts exactly one."""
    app_home = tmp_path / "app-home"
    app_home.mkdir()
    seed_credentials(app_home, attach=_ATTACH, ownership=_OWNERSHIP)
    seat_valid_database(app_home)

    log_path = tmp_path / "gateway.log"
    log_handle = log_path.open("wb")
    auth = {"Authorization": f"Bearer {_ATTACH}"}

    def _spawn(gateway_port: int, worker_port: int) -> subprocess.Popen[bytes]:
        # The gateway owns and spawns its worker; boot must still not start it.
        return spawn_gateway(
            script=_GATEWAY,
            gateway_port=gateway_port,
            env=armed_gateway_env(
                app_home, gateway_port=gateway_port, worker_port=worker_port
            ),
            log_handle=log_handle,
        )

    proc, _gateway_port, worker_port, base = spawn_until_ready(
        _spawn, log_path=log_path
    )
    try:
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
        reap_gateway(proc)
        log_handle.close()
