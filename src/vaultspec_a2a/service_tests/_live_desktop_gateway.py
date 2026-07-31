"""Real-process desktop gateway harness for cross-repository certification."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import subprocess
import sys
import time
from typing import TYPE_CHECKING, Final

from ..desktop._platform_acl import harden_credential_file
from ..desktop.credentials import (
    ATTACH_CREDENTIAL_NAME,
    OWNERSHIP_CAPABILITY_NAME,
)
from ..desktop.profile import derive_state_paths
from ..desktop_tests._boot import spawn_until_ready
from ..utils import kill_pid_tree_async

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


def _seat_valid_database(app_home: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            _MODULE,
            "migrate",
            "--app-home",
            str(app_home),
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, f"migrate failed: {result.stdout}\n{result.stderr}"
    assert json.loads(result.stdout.strip())["status"] == "succeeded"
    assert derive_state_paths(app_home).database_path.is_file()


@contextlib.contextmanager
def armed_gateway(tmp_path: Path, **extra_env: str) -> Iterator[tuple[str, str]]:
    """Boot a migrated production desktop gateway and its real lazy worker."""
    app_home = tmp_path / "app-home"
    app_home.mkdir()
    _seed_credentials(app_home)
    _seat_valid_database(app_home)

    log_path = tmp_path / "gateway.log"
    log_handle = log_path.open("wb")

    def _spawn(gateway_port: int, worker_port: int) -> subprocess.Popen[bytes]:
        environment = {
            **os.environ,
            "VAULTSPEC_DESKTOP_APP_HOME": str(app_home),
            "VAULTSPEC_ENVIRONMENT": "production",
            "VAULTSPEC_PORT": str(gateway_port),
            "VAULTSPEC_WORKER_PORT": str(worker_port),
            "VAULTSPEC_AUTO_SPAWN_WORKER": "true",
            **extra_env,
        }
        return subprocess.Popen(
            [sys.executable, "-c", _GATEWAY, str(gateway_port)],
            env=environment,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=os.name != "nt",
        )

    process, _gateway_port, _worker_port, base = spawn_until_ready(
        _spawn, log_path=log_path
    )
    try:
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
