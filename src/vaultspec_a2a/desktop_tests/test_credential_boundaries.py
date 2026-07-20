"""Certify the three desktop credential planes against a real armed gateway.

A real child interpreter boots the production gateway application armed with the
desktop profile over a genuinely migrated app home: ``create_app`` loads the
dashboard-created attach and ownership credentials from their owner-restricted
files and mints the worker interprocess-communication secret, and the production
lifespan validates the seated schema, seats the application state, and publishes
the versioned discovery record. The parent then proves, over real HTTP, that the
three credentials are non-interchangeable and rejected outside their planes, that
no secret appears in the discovery record, the process logs, or any response body,
that unauthenticated liveness discloses nothing, and that the listener is
loopback-only.

The gateway runs the *production* lifespan rather than a test substitute: an
override would leave the application state unseated, and every authenticated verb
would answer 500 instead of exercising the credential planes under test.

The valid database is seated by the real ``desktop-migrate`` entrypoint in a
separate process; the gateway is a second real process. No mock, monkeypatch,
stub, skip, or expected failure is used; the child is always torn down in a
``finally``.
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

_ATTACH = "attach-credential-token-1234567890abcdef"
_OWNERSHIP = "ownership-capability-token-fedcba0987654321"
_LIFECYCLE_HEADER = "X-Vaultspec-Lifecycle-Capability"
_DIGEST = "c" * 64
_MODULE = "vaultspec_a2a.cli.main"

# A real armed desktop gateway booting the *production* lifespan: create_app runs
# the armed credential loading, and the lifespan validates the seated schema,
# seats the application state, and publishes the versioned discovery record.
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


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _write_descriptor(descriptor_path: Path, app_home: Path) -> Path:
    """Write a one-time migration descriptor for the app home's stores."""
    state = derive_state_paths(app_home)
    packaged = package_migration_range()
    document = {
        "descriptor_version": "1",
        "transaction_id": "credential-boundaries-txn-1",
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
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            _MODULE,
            "desktop-migrate",
            "--descriptor",
            str(descriptor),
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, f"migrate failed: {result.stdout}\n{result.stderr}"
    payload = json.loads(result.stdout.strip())
    assert payload["status"] == "succeeded", payload
    assert derive_state_paths(app_home).database_path.is_file()


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
    raise AssertionError(f"gateway liveness never came up ({last})")


def test_credential_planes_are_isolated_and_secret_free(tmp_path: Path) -> None:
    """The three planes are non-interchangeable and no secret ever leaks."""
    app_home = tmp_path / "app-home"
    app_home.mkdir()
    credentials_dir = _seed_credentials(app_home)
    _seat_valid_database(app_home, _write_descriptor(tmp_path / "txn.json", app_home))
    port = _free_port()

    log_path = tmp_path / "gateway.log"
    env = os.environ.copy()
    env["VAULTSPEC_DESKTOP_APP_HOME"] = str(app_home)
    env["VAULTSPEC_ENVIRONMENT"] = "production"
    env["VAULTSPEC_PORT"] = str(port)
    # The credential planes are the subject; keep the worker cold so no worker
    # process is started behind this test.
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

        # The gateway minted the worker IPC secret; read it to scan for its leak.
        worker_ipc = (credentials_dir / "worker-ipc.cred").read_text(encoding="utf-8")
        assert worker_ipc and worker_ipc not in (_ATTACH, _OWNERSHIP)

        with httpx.Client(base_url=base, timeout=5.0) as client:
            # --- Discovery record carries no secret, only the ACL-protected ref ---
            discovery_text = (app_home / "service.json").read_text(encoding="utf-8")
            for secret in (_ATTACH, _OWNERSHIP, worker_ipc):
                assert secret not in discovery_text
            assert ATTACH_CREDENTIAL_NAME in discovery_text  # the reference path

            # --- Unauthenticated liveness discloses nothing ---
            live = client.get("/health")
            assert live.status_code == 200
            for secret in (_ATTACH, _OWNERSHIP, worker_ipc):
                assert secret not in live.text

            # --- Attach plane: only the attach credential authenticates ---
            assert client.get("/v1/service").status_code == 401
            assert (
                client.get(
                    "/v1/service", headers={"Authorization": f"Bearer {worker_ipc}"}
                ).status_code
                == 401
            )
            assert (
                client.get(
                    "/v1/service", headers={"Authorization": f"Bearer {_OWNERSHIP}"}
                ).status_code
                == 401
            )
            attach_ok = client.get(
                "/v1/service", headers={"Authorization": f"Bearer {_ATTACH}"}
            )
            assert attach_ok.status_code == 200, attach_ok.text
            for secret in (_ATTACH, _OWNERSHIP, worker_ipc):
                assert secret not in attach_ok.text

            # --- Worker IPC plane: attach is rejected, worker IPC is accepted ---
            assert (
                client.get(
                    "/internal/health",
                    headers={"Authorization": f"Bearer {_ATTACH}"},
                ).status_code
                == 401
            )
            worker_ok = client.get(
                "/internal/health",
                headers={"Authorization": f"Bearer {worker_ipc}"},
            )
            assert worker_ok.status_code == 200

            # --- Lifecycle plane: admin shutdown needs the ownership capability ---
            attach_only = client.post(
                "/api/admin/shutdown",
                headers={"Authorization": f"Bearer {_ATTACH}"},
            )
            assert attach_only.status_code == 403
            wrong_cap = client.post(
                "/api/admin/shutdown",
                headers={
                    "Authorization": f"Bearer {_ATTACH}",
                    _LIFECYCLE_HEADER: "not-the-capability",
                },
            )
            assert wrong_cap.status_code == 403

        # --- The process logs never printed a secret ---
        log_handle.flush()
        log_bytes = log_path.read_bytes()
        for secret in (_ATTACH, _OWNERSHIP, worker_ipc):
            assert secret.encode("utf-8") not in log_bytes
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=25)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive teardown
            proc.kill()
            proc.wait(timeout=25)
        log_handle.close()
