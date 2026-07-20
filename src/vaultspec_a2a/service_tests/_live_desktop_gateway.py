"""Real-process desktop gateway harness for cross-repository certification."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

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
    from collections.abc import Iterator
    from pathlib import Path

ATTACH_CREDENTIAL: Final = "attach-credential-cross-repo-1234567890abcdef"
_OWNERSHIP: Final = "ownership-capability-cross-repo-fedcba0987654321"
_DIGEST: Final = "a" * 64
_MODULE: Final = "vaultspec_a2a.cli.main"

_GATEWAY: Final = """
import logging
import sys

logging.basicConfig(level=logging.INFO)
import uvicorn
from vaultspec_a2a.api.app import create_app

port = int(sys.argv[1])
uvicorn.run(create_app(), host="127.0.0.1", port=port, log_level="info")
"""


def _seed_credentials(app_home: Path) -> None:
    state = derive_state_paths(app_home)
    state.credentials_dir.mkdir(parents=True, exist_ok=True)
    for name, secret in (
        (ATTACH_CREDENTIAL_NAME, ATTACH_CREDENTIAL),
        (OWNERSHIP_CAPABILITY_NAME, _OWNERSHIP),
    ):
        path = state.credentials_dir / name
        path.write_text(secret, encoding="utf-8")
        harden_credential_file(path)


def _write_descriptor(descriptor_path: Path, app_home: Path) -> Path:
    state = derive_state_paths(app_home)
    packaged = package_migration_range()
    descriptor_path.write_text(
        json.dumps(
            {
                "descriptor_version": "1",
                "transaction_id": "cross-repo-gateway-txn-1",
                "app_home": str(app_home),
                "database_path": str(state.database_path),
                "checkpoint_path": str(state.checkpoint_path),
                "generation": {
                    "manifest_digest": _DIGEST,
                    "component_version": "4.0.0",
                },
                "migration_range": {"base": packaged.base, "head": packaged.head},
                "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    return descriptor_path


def _seat_valid_database(app_home: Path, descriptor: Path) -> None:
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
    assert json.loads(result.stdout.strip())["status"] == "succeeded"
    assert derive_state_paths(app_home).database_path.is_file()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _await_health(base: str, *, timeout: float = 40.0) -> None:
    deadline = time.monotonic() + timeout
    last = "not started"
    while time.monotonic() < deadline:
        try:
            with httpx.Client(base_url=base, timeout=2.0) as client:
                if client.get("/health").status_code == 200:
                    return
        except httpx.HTTPError as exc:
            last = repr(exc)
        time.sleep(0.1)
    raise AssertionError(f"gateway readiness never came up ({last})")


@contextmanager
def armed_gateway(tmp_path: Path, **extra_env: str) -> Iterator[tuple[str, str]]:
    """Boot a migrated production desktop gateway and its real lazy worker."""
    app_home = tmp_path / "app-home"
    app_home.mkdir()
    _seed_credentials(app_home)
    _seat_valid_database(app_home, _write_descriptor(tmp_path / "txn.json", app_home))

    gateway_port = _free_port()
    worker_port = _free_port()
    environment = {
        **os.environ,
        "VAULTSPEC_DESKTOP_APP_HOME": str(app_home),
        "VAULTSPEC_ENVIRONMENT": "production",
        "VAULTSPEC_PORT": str(gateway_port),
        "VAULTSPEC_WORKER_PORT": str(worker_port),
        "VAULTSPEC_AUTO_SPAWN_WORKER": "true",
        **extra_env,
    }
    base = f"http://127.0.0.1:{gateway_port}"
    log_handle = (tmp_path / "gateway.log").open("wb")
    process = subprocess.Popen(
        [sys.executable, "-c", _GATEWAY, str(gateway_port)],
        env=environment,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=os.name != "nt",
    )
    try:
        _await_health(base)
        yield base, f"Bearer {ATTACH_CREDENTIAL}"
    finally:
        if os.name == "nt":
            with contextlib.suppress(Exception):
                asyncio.run(
                    kill_pid_tree_async(
                        process.pid, term_timeout=10.0, kill_timeout=5.0
                    )
                )
        else:
            for sig in (signal.SIGTERM, signal.SIGKILL):
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, sig)
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    process.poll()
                    try:
                        os.killpg(process.pid, 0)
                    except ProcessLookupError:
                        break
                    time.sleep(0.05)
                else:
                    continue
                break
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=15)
        log_handle.close()
