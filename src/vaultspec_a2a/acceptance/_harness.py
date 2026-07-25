"""Real-process boot and authenticated client for the certification stack.

The single source of the certification stack's lifecycle: allocate a loopback
port pair, seat a valid desktop application home (dashboard-created credentials
plus a database seated by the real ``migrate`` entrypoint), spawn the production
gateway armed with the desktop profile so it owns and spawns its own worker, and
wait for readiness with a death-aware poll that fails fast on a child that dies
before it answers rather than after a silent timeout.

The deterministic provider backend the worker proxies to (VidaiMock) is a
separate real process. Where a certifying environment runs it, pass its base URL
as ``MOCK_API_BASE`` through the keyword environment and the gateway-owned worker
inherits it, so runs complete against a real deterministic provider. The
provider is not required to certify the provider-independent gateway contract -
run creation, status, cancellation routing, streaming, deletion, and
authentication all hold whether a run ultimately completes or fails - so those
scenarios drive this stack without it.

``CertifiedGateway`` is the authenticated handle scenarios drive. Its request
helpers are the one place the public verbs are shaped, so a scenario asserts on
responses instead of re-deriving request bodies - no shadowed request logic
spread across scenario files.
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
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

from ..desktop._platform_acl import harden_credential_file
from ..desktop.credentials import (
    ATTACH_CREDENTIAL_NAME,
    OWNERSHIP_CAPABILITY_NAME,
)
from ..desktop.profile import derive_state_paths
from ..utils import kill_pid_tree_async

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

__all__ = [
    "DEFAULT_REQUIRED_ROLE",
    "DEFAULT_TEAM_PRESET",
    "CertifiedGateway",
    "GatewayBootError",
    "certified_gateway",
]

# The bundled deterministic preset the stack certifies against. It ships only in
# source and Compose environments; the gateway loads it from the checkout, never
# a published wheel, which is why this harness is source-only.
DEFAULT_TEAM_PRESET = "mock-success-single"
DEFAULT_REQUIRED_ROLE = "mock-coder-success"

_MIGRATE_MODULE = "vaultspec_a2a.cli.main"
_LOG_TAIL_BYTES = 4096

# The child gateway is a real interpreter running the production ASGI app under
# uvicorn; nothing here is stubbed. The armed desktop profile is selected by the
# environment the parent passes, so this script carries no test-only wiring.
_GATEWAY_SCRIPT = """
import logging
import sys

logging.basicConfig(level=logging.INFO)
import uvicorn
from vaultspec_a2a.api.app import create_app

port = int(sys.argv[1])
uvicorn.run(create_app(), host="127.0.0.1", port=port, log_level="info")
"""


class GatewayBootError(AssertionError):
    """The gateway process exited before its readiness endpoint answered."""


def _free_port() -> int:
    """Return a currently-free loopback port (bind-then-close; racy by nature).

    The port is a CANDIDATE only: nothing reserves it between this close and the
    child's bind, which is exactly why :func:`_spawn_until_ready` retries a child
    that dies before readiness - the Windows bind race that otherwise burns a
    whole readiness window.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _log_tail(log_path: Path | None) -> str:
    if log_path is None:
        return ""
    try:
        data = log_path.read_bytes()
    except OSError:
        return ""
    tail = data[-_LOG_TAIL_BYTES:].decode("utf-8", errors="replace")
    return f"; log tail:\n{tail}" if tail else ""


def _await_ready(
    base: str,
    proc: subprocess.Popen[bytes],
    *,
    log_path: Path | None,
    timeout: float,
) -> None:
    """Wait until ``GET /health`` answers 200, failing fast on a dead child.

    A process that exits before readiness raises :class:`GatewayBootError`
    immediately (the bind-race signature) carrying its exit code and log tail; a
    process that stays alive but never answers raises a plain
    :class:`AssertionError` at the deadline - a genuine readiness failure that is
    never retried.
    """
    deadline = time.monotonic() + timeout
    last: str | None = None
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise GatewayBootError(
                f"gateway exited before readiness (exit {proc.returncode})"
                f"{_log_tail(log_path)}"
            )
        try:
            with httpx.Client(base_url=base, timeout=2.0) as client:
                if client.get("/health").status_code == 200:
                    return
        except httpx.HTTPError as exc:
            last = repr(exc)
        time.sleep(0.1)
    raise AssertionError(f"gateway never became ready ({last}){_log_tail(log_path)}")


def _spawn_until_ready(
    spawn: Callable[[int, int], subprocess.Popen[bytes]],
    *,
    log_path: Path | None,
    attempts: int = 3,
    timeout: float = 60.0,
) -> tuple[subprocess.Popen[bytes], int, int, str]:
    """Boot a gateway on a fresh port pair, retrying only the bind-race death."""
    last_error: GatewayBootError | None = None
    for _ in range(attempts):
        gateway_port = _free_port()
        worker_port = _free_port()
        proc = spawn(gateway_port, worker_port)
        base = f"http://127.0.0.1:{gateway_port}"
        try:
            _await_ready(base, proc, log_path=log_path, timeout=timeout)
        except GatewayBootError as exc:
            last_error = exc
            continue
        return proc, gateway_port, worker_port, base
    raise AssertionError(
        f"gateway did not boot within {attempts} attempts; last: {last_error}"
    )


def _seed_credentials(app_home: Path, *, attach: str, ownership: str) -> None:
    """Write the dashboard-created attach and ownership credential files."""
    state = derive_state_paths(app_home)
    state.credentials_dir.mkdir(parents=True, exist_ok=True)
    for name, secret in (
        (ATTACH_CREDENTIAL_NAME, attach),
        (OWNERSHIP_CAPABILITY_NAME, ownership),
    ):
        path = state.credentials_dir / name
        path.write_text(secret, encoding="utf-8")
        harden_credential_file(path)


def _seat_valid_database(app_home: Path) -> None:
    """Seat a valid desktop database via the real ``migrate`` entrypoint."""
    result = subprocess.run(
        [sys.executable, "-m", _MIGRATE_MODULE, "migrate", "--app-home", str(app_home)],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if result.returncode != 0:
        raise GatewayBootError(
            f"migrate failed (exit {result.returncode}): "
            f"{result.stdout}\n{result.stderr}"
        )
    payload = json.loads(result.stdout.strip())
    if payload.get("status") != "succeeded":
        raise GatewayBootError(f"migrate did not succeed: {payload}")
    if not derive_state_paths(app_home).database_path.is_file():
        raise GatewayBootError("migrate reported success but no database file exists")


@dataclass(slots=True)
class CertifiedGateway:
    """An authenticated handle to one running armed-desktop certification stack.

    The verb helpers shape the exact public-surface requests once so scenarios
    read as assertions on real responses. Every helper presents the real
    attach-control credential; none uses the test-only authentication bypass.
    """

    base_url: str
    attach_token: str
    app_home: Path

    @property
    def auth_header(self) -> dict[str, str]:
        """The real attach-control Authorization header the dashboard presents."""
        return {"Authorization": f"Bearer {self.attach_token}"}

    def client(self, *, timeout: float = 30.0) -> httpx.Client:
        """A synchronous authenticated client bound to the gateway base URL."""
        return httpx.Client(
            base_url=self.base_url, timeout=timeout, headers=self.auth_header
        )

    def async_client(self, *, timeout: float = 30.0) -> httpx.AsyncClient:
        """An async authenticated client, for the streaming certification path."""
        return httpx.AsyncClient(
            base_url=self.base_url, timeout=timeout, headers=self.auth_header
        )

    def stream_path(self, run_id: str) -> str:
        """The versioned public progress-stream path for *run_id*."""
        return f"/v1/runs/{run_id}/stream"

    # -- versioned run-start verb (prepare / start / release) ------------------

    def prepare(
        self, run_id: str, *, team_preset: str = DEFAULT_TEAM_PRESET
    ) -> httpx.Response:
        """Reserve a bounded admission slot for *run_id* (readiness-gated)."""
        with self.client(timeout=90.0) as client:
            return client.post(
                "/v1/runs",
                json={
                    "team_preset": team_preset,
                    "stage": "prepare",
                    "run_id": run_id,
                    "autonomous": True,
                },
            )

    def release(
        self,
        run_id: str,
        reservation_id: str,
        *,
        team_preset: str = DEFAULT_TEAM_PRESET,
    ) -> httpx.Response:
        """Explicitly free an uncommitted prepared reservation."""
        with self.client(timeout=30.0) as client:
            return client.post(
                "/v1/runs",
                json={
                    "team_preset": team_preset,
                    "stage": "release",
                    "reservation_id": reservation_id,
                    "run_id": run_id,
                    "autonomous": True,
                },
            )

    def start(
        self,
        run_id: str,
        *,
        team_preset: str = DEFAULT_TEAM_PRESET,
        role: str = DEFAULT_REQUIRED_ROLE,
        message: str = "certify the assembled product",
    ) -> httpx.Response:
        """Drive the one-shot ``start`` stage: create and dispatch in one call."""
        with self.client(timeout=90.0) as client:
            return client.post(
                "/v1/runs",
                json={
                    "team_preset": team_preset,
                    "stage": "start",
                    "run_id": run_id,
                    "message": message,
                    "autonomous": True,
                    "actor_tokens": {
                        "tokens": {role: "tok-certification"},
                        "engine_bearer": "bearer",
                    },
                },
            )

    # -- versioned run reads and cancel ---------------------------------------

    def status(self, run_id: str) -> httpx.Response:
        """Read the authoritative run-status snapshot for *run_id*."""
        with self.client(timeout=30.0) as client:
            return client.get(f"/v1/runs/{run_id}")

    def active_runs(self) -> httpx.Response:
        """Discover the bounded set of durable non-terminal runs."""
        with self.client(timeout=30.0) as client:
            return client.get("/v1/runs")

    def cancel(
        self, run_id: str, *, idempotency_key: str | None = None
    ) -> httpx.Response:
        """Cancel *run_id* idempotently through the versioned public verb."""
        headers = dict(self.auth_header)
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        with self.client(timeout=30.0) as client:
            return client.post(f"/v1/runs/{run_id}/cancel", headers=headers)

    # -- attach-gated dashboard product surface -------------------------------

    def thread_state(self, run_id: str) -> httpx.Response:
        """Read the dashboard product-surface state for a run."""
        with self.client(timeout=30.0) as client:
            return client.get(f"/api/threads/{run_id}/state")

    def delete_run(self, run_id: str) -> httpx.Response:
        """Delete *run_id* through the durable cross-store deletion saga."""
        with self.client(timeout=60.0) as client:
            return client.delete(f"/api/threads/{run_id}")


def _reap(proc: subprocess.Popen[bytes]) -> None:
    """Reap the whole gateway-owned process tree, best effort."""
    with contextlib.suppress(Exception):
        asyncio.run(kill_pid_tree_async(proc.pid, term_timeout=10.0, kill_timeout=5.0))
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=15)


@contextmanager
def certified_gateway(
    workdir: Path,
    *,
    attach_token: str = "attach-certification-1234567890abcdef",
    ownership_capability: str = "ownership-certification-fedcba0987654321",
    settlement_url: str | None = None,
    log_name: str = "gateway.log",
    **extra_env: str,
) -> Iterator[CertifiedGateway]:
    """Boot one armed-desktop certification stack over *workdir* and reap it.

    Seats the dashboard credentials and a real migrated database under a fresh
    application home, spawns the production gateway with worker auto-spawn so the
    gateway owns its worker, waits for readiness, and yields an authenticated
    :class:`CertifiedGateway`. A certifying environment that runs the
    deterministic provider passes ``MOCK_API_BASE`` through *extra_env* so the
    gateway-owned worker reaches it. The gateway-owned process tree is reaped in
    a ``finally`` regardless of scenario outcome, so no worker or gateway leaks.
    """
    app_home = workdir / "app-home"
    app_home.mkdir(parents=True, exist_ok=True)
    _seed_credentials(app_home, attach=attach_token, ownership=ownership_capability)
    _seat_valid_database(app_home)

    log_path = workdir / log_name
    log_handle = log_path.open("wb")

    def _spawn(gateway_port: int, worker_port: int) -> subprocess.Popen[bytes]:
        env = os.environ.copy()
        env["VAULTSPEC_DESKTOP_APP_HOME"] = str(app_home)
        env["VAULTSPEC_ENVIRONMENT"] = "production"
        env["VAULTSPEC_PORT"] = str(gateway_port)
        env["VAULTSPEC_WORKER_PORT"] = str(worker_port)
        env["VAULTSPEC_AUTO_SPAWN_WORKER"] = "true"
        if settlement_url is not None:
            env["VAULTSPEC_DESKTOP_SETTLEMENT_URL"] = settlement_url
        env.update(extra_env)
        return subprocess.Popen(
            [sys.executable, "-c", _GATEWAY_SCRIPT, str(gateway_port)],
            env=env,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=os.name != "nt",
        )

    proc, _gateway_port, _worker_port, base = _spawn_until_ready(
        _spawn, log_path=log_path
    )
    try:
        yield CertifiedGateway(
            base_url=base, attach_token=attach_token, app_home=app_home
        )
    finally:
        _reap(proc)
        log_handle.close()
