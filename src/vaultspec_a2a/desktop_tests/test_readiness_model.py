"""Certify the desktop readiness model against a real armed gateway over HTTP.

A real child interpreter boots the production gateway armed with the desktop
profile over a genuinely migrated app home: ordinary boot validates the seated
schema, seats the database engine, and creates the lazy worker spawner without
starting a worker. The parent then proves, over a real loopback socket, that the
unauthenticated liveness boundary discloses only the minimal alive signal (asserted
byte-for-byte), that the readiness facts are reachable only through the attach
credential, and that a cold, startable worker reads as gateway-ready yet not
execution-ready - the cold rung of the cold-to-execution ladder - on both the
authenticated liveness surface and the service-state verb.

The valid database is seated by the real ``migrate`` entrypoint in a
separate process; the gateway is a second real process. No mock, monkeypatch,
stub, skip, or expected failure is used; children are torn down in a ``finally``.
"""

from __future__ import annotations

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

if TYPE_CHECKING:
    import subprocess
    from pathlib import Path

_ATTACH = "attach-credential-readiness-1234567890abcdef"
_OWNERSHIP = "ownership-capability-readiness-fedcba0987654321"


def test_desktop_readiness_liveness_minimal_and_readiness_authenticated(
    tmp_path: Path,
) -> None:
    """Minimal liveness is public; readiness with the cold ladder is authenticated."""
    app_home = tmp_path / "app-home"
    app_home.mkdir()
    seed_credentials(app_home, attach=_ATTACH, ownership=_OWNERSHIP)
    seat_valid_database(app_home)

    log_path = tmp_path / "gateway.log"
    log_handle = log_path.open("wb")
    # A real armed desktop gateway booting the *production* lifespan: create_app
    # runs the armed credential loading, and the production lifespan validates
    # the seated schema, seats the database engine, and creates the lazy worker
    # spawner. With auto-spawn disabled the worker stays cold, which is exactly
    # the fact under test.
    script = gateway_script(log_level="warning")

    def _spawn(port: int, worker_port: int) -> subprocess.Popen[bytes]:
        return spawn_gateway(
            script=script,
            gateway_port=port,
            env=armed_gateway_env(
                app_home,
                gateway_port=port,
                worker_port=worker_port,
                # Keep the worker cold: ordinary boot must not start it, so the
                # gateway-ready yet not-execution-ready fact is observable.
                auto_spawn_worker=False,
                extra={"VAULTSPEC_REPAIR_ON_STARTUP": "false"},
            ),
            log_handle=log_handle,
        )

    proc, _port, _worker_port, base = spawn_until_ready(_spawn, log_path=log_path)
    try:
        with httpx.Client(base_url=base, timeout=5.0) as client:
            # --- Every ungated liveness surface is minimal, byte-for-byte. ---
            # Both the top-level probe and the aggregate probe must disclose only
            # the minimal alive signal - no process identity, service identity, or
            # product state. The body shape is asserted at the byte level so a
            # regression that re-adds a field cannot slip past a substring scan.
            leaks = (
                "pid",
                "generation",
                "profile",
                "worker",
                "gateway_readiness",
                "circuit",
                "backend",
                "status",
            )
            live = client.get("/health")
            assert live.status_code == 200
            assert live.content == b'{"liveness":"alive"}'
            assert live.json() == {"liveness": "alive"}
            for token in leaks:
                assert token not in live.text, token

            # --- Readiness facts are reachable only through the attach credential. ---
            assert client.get("/v1/service").status_code == 401

            # --- Authenticated readiness carries identity and the cold ladder. ---
            auth = {"Authorization": f"Bearer {_ATTACH}"}
            ready = client.get("/health", headers=auth)
            assert ready.status_code == 200
            body = ready.json()
            # Process identity is disclosed; the exact value is the real gateway
            # process, not this launcher handle (a venv python is a launcher stub
            # whose child pid differs), so identity is asserted present and
            # consistent across both authenticated surfaces below.
            gateway_pid = body["gateway_pid"]
            assert isinstance(gateway_pid, int) and gateway_pid > 0
            assert isinstance(body["generation"], str) and body["generation"]
            assert body["profile"] == "desktop"
            assert body["liveness"] == "alive"
            assert body["provider_eligibility"] in {"eligible", "ineligible"}
            # A valid database with a cold, startable worker: gateway-ready, worker
            # cold, admission deferred - gateway-ready but not execution-ready.
            assert body["gateway_readiness"] == "ready"
            assert body["worker_state"] == "cold"
            assert body["run_admission"] == "deferred"

            # --- The service-state verb serves the same readiness projection. ---
            svc = client.get("/v1/service", headers=auth)
            assert svc.status_code == 200
            readiness = svc.json()["readiness"]
            # Same real gateway process serves both authenticated surfaces.
            assert readiness["gateway_pid"] == gateway_pid
            assert readiness["gateway_readiness"] == "ready"
            assert readiness["worker_state"] == "cold"
            assert readiness["run_admission"] == "deferred"
    finally:
        # The TREE, not the handle: on Windows the virtual-environment
        # interpreter is a launcher stub, so a terminate() aimed at this handle
        # leaves the real uvicorn gateway alive holding its port and its SQLite
        # handles for the rest of the session.
        reap_gateway(proc)
        log_handle.close()
