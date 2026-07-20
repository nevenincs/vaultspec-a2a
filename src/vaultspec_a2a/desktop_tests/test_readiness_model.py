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

The valid database is seated by the real ``desktop-migrate`` entrypoint in a
separate process; the gateway is a second real process. No mock, monkeypatch,
stub, skip, or expected failure is used; children are torn down in a ``finally``.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
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

if TYPE_CHECKING:
    from pathlib import Path

_ATTACH = "attach-credential-readiness-1234567890abcdef"
_OWNERSHIP = "ownership-capability-readiness-fedcba0987654321"
_DIGEST = "d" * 64
_MODULE = "vaultspec_a2a.cli.main"

# A real armed desktop gateway booting the *production* lifespan: create_app runs
# the armed credential loading, and the production lifespan validates the seated
# schema, seats the database engine, and creates the lazy worker spawner. With
# auto-spawn disabled the worker stays cold, which is exactly the fact under test.
_GATEWAY = """
import sys
import uvicorn
from vaultspec_a2a.api.app import create_app

port = int(sys.argv[1])
uvicorn.run(create_app(), host="127.0.0.1", port=port, log_level="warning")
"""


def _seed_credentials(app_home: Path) -> Path:
    """Write the dashboard-created attach and ownership files; return creds dir."""
    state = derive_state_paths(app_home)
    state.credentials_dir.mkdir(parents=True, exist_ok=True)
    for name, secret in (
        (ATTACH_CREDENTIAL_NAME, _ATTACH),
        (OWNERSHIP_CAPABILITY_NAME, _OWNERSHIP),
    ):
        path = state.credentials_dir / name
        path.write_text(secret, encoding="utf-8")
        harden_credential_file(path)
    return state.credentials_dir


def _write_descriptor(descriptor_path: Path, app_home: Path) -> Path:
    """Write a one-time migration descriptor for the app home's stores."""
    state = derive_state_paths(app_home)
    packaged = package_migration_range()
    document = {
        "descriptor_version": "1",
        "transaction_id": "readiness-txn-1",
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
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, f"migrate failed: {result.stdout}\n{result.stderr}"
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "succeeded", payload
    assert derive_state_paths(app_home).database_path.is_file()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


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


def test_desktop_readiness_liveness_minimal_and_readiness_authenticated(
    tmp_path: Path,
) -> None:
    """Minimal liveness is public; readiness with the cold ladder is authenticated."""
    app_home = tmp_path / "app-home"
    app_home.mkdir()
    _seed_credentials(app_home)
    _seat_valid_database(app_home, _write_descriptor(tmp_path / "txn.json", app_home))

    port = _free_port()
    log_path = tmp_path / "gateway.log"
    env = os.environ.copy()
    env["VAULTSPEC_DESKTOP_APP_HOME"] = str(app_home)
    env["VAULTSPEC_ENVIRONMENT"] = "production"
    env["VAULTSPEC_PORT"] = str(port)
    # Keep the worker cold: ordinary boot must not start it, so the gateway-ready
    # yet not-execution-ready fact is observable.
    env["VAULTSPEC_AUTO_SPAWN_WORKER"] = "false"
    env["VAULTSPEC_REPAIR_ON_STARTUP"] = "false"

    log_handle = log_path.open("wb")
    proc = subprocess.Popen(
        [sys.executable, "-c", _GATEWAY, str(port)],
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        _await_health(base)

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
            for path in ("/health", "/api/health"):
                live = client.get(path)
                assert live.status_code == 200, path
                assert live.content == b'{"liveness":"alive"}', path
                assert live.json() == {"liveness": "alive"}, path
                for token in leaks:
                    assert token not in live.text, (path, token)

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
        proc.terminate()
        try:
            proc.wait(timeout=25)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive teardown
            proc.kill()
            proc.wait(timeout=25)
        log_handle.close()
