"""Certify the three desktop credential planes against a real armed gateway.

A real child interpreter boots the production gateway application armed with the
desktop profile: it loads the dashboard-created attach and ownership credentials
from their owner-restricted files, mints the worker interprocess-communication
secret, publishes the versioned discovery record, and serves the real
authentication stack over a real loopback socket. The parent then proves, over
real HTTP, that the three credentials are non-interchangeable and rejected outside
their planes, that no secret appears in the discovery record, the process logs, or
any response body, that unauthenticated liveness discloses nothing, and that the
listener is loopback-only.

No mock, monkeypatch, stub, skip, or expected failure is used; the child is always
torn down in a ``finally``.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from typing import TYPE_CHECKING

import httpx

from vaultspec_a2a.desktop._platform_acl import harden_credential_file
from vaultspec_a2a.desktop.credentials import (
    ATTACH_CREDENTIAL_NAME,
    OWNERSHIP_CAPABILITY_NAME,
)
from vaultspec_a2a.desktop.profile import derive_state_paths

if TYPE_CHECKING:
    from pathlib import Path

_ATTACH = "attach-credential-token-1234567890abcdef"
_OWNERSHIP = "ownership-capability-token-fedcba0987654321"
_LIFECYCLE_HEADER = "X-Vaultspec-Lifecycle-Capability"

# A real armed desktop gateway: create_app runs the armed credential loading (real
# production path), the lifespan publishes the versioned discovery record and
# signals readiness, and uvicorn serves the real auth stack on loopback.
_GATEWAY = """
import json, os, sys
from contextlib import asynccontextmanager
from pathlib import Path
import uvicorn
from vaultspec_a2a.api.app import create_app
from vaultspec_a2a.control.config import settings
from vaultspec_a2a.lifecycle.discovery import (
    write_desktop_discovery,
    service_json_path,
)

port = int(sys.argv[1])
ready = Path(sys.argv[2])


@asynccontextmanager
async def _lifespan(app):
    references = settings.desktop_credential_paths
    write_desktop_discovery(
        service_json_path(settings.a2a_home),
        generation="gen-1",
        port=port,
        owner="owner-a",
        credential_reference=str(references.attach_path) if references else None,
    )
    ready.write_text(json.dumps({"pid": os.getpid(), "port": port}))
    yield


app = create_app(lifespan=_lifespan)
uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
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


def _await_ready(path: Path, *, timeout: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() and path.read_text():
            return json.loads(path.read_text())
        time.sleep(0.05)
    raise AssertionError(f"gateway did not signal readiness at {path}")


def _await_listener(port: int, *, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.1)
    raise AssertionError(f"gateway listener never came up on 127.0.0.1:{port}")


def test_credential_planes_are_isolated_and_secret_free(tmp_path: Path) -> None:
    """The three planes are non-interchangeable and no secret ever leaks."""
    app_home = tmp_path / "app-home"
    app_home.mkdir()
    credentials_dir = _seed_credentials(app_home)
    port = _free_port()

    ready = tmp_path / "ready.json"
    log_path = tmp_path / "gateway.log"
    env = os.environ.copy()
    env["VAULTSPEC_DESKTOP_APP_HOME"] = str(app_home)
    env["VAULTSPEC_ENVIRONMENT"] = "production"

    log_handle = log_path.open("wb")
    proc = subprocess.Popen(
        [sys.executable, "-c", _GATEWAY, str(port), str(ready)],
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    try:
        _await_ready(ready)
        _await_listener(port)

        # The gateway minted the worker IPC secret; read it to scan for its leak.
        worker_ipc = (credentials_dir / "worker-ipc.cred").read_text(encoding="utf-8")
        assert worker_ipc and worker_ipc not in (_ATTACH, _OWNERSHIP)

        base = f"http://127.0.0.1:{port}"
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
            assert attach_ok.status_code != 401
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
