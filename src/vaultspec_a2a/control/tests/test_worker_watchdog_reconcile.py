"""Watchdog reconciliation against an externally-managed worker (task #8).

Real HTTP /health servers and real breaker/state/spawner objects - no mocks. The
regression these guard: the watchdog must not thrash (force the breaker open, spin
restart cycles, spawn competitors) against a worker that is HTTP-healthy and/or not
owned by this gateway, and the health projection must tell the truth about it. A
pre-fix run of ``test_external_healthy_worker...`` showed worker_restart_count
climbing every tick and the breaker flapping open; post-fix it stays 0 and closed.
"""

from __future__ import annotations

import http.server
import socket
import subprocess
import sys
import threading
from contextlib import contextmanager
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from vaultspec_a2a.control.circuit_breaker import WorkerCircuitBreaker
from vaultspec_a2a.control.config import settings
from vaultspec_a2a.control.health import assemble_health_status
from vaultspec_a2a.control.worker_management import (
    LazyWorkerSpawner,
    WorkerState,
    WorkerWatchdog,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


class _HealthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        code = 200 if self.path == "/health" else 404
        body = b"{}"
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        """Silence the default stderr access log."""


@contextmanager
def _health_server() -> Iterator[int]:
    """A real loopback HTTP server answering GET /health 200, yielding its port."""
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _HealthHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield port
    finally:
        server.shutdown()
        server.server_close()


def _free_port() -> int:
    """An unbound loopback port (nothing listening — an unreachable worker)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _stale_app_state(**singletons: object) -> SimpleNamespace:
    # A frozen heartbeat far past the timeout - the reseat-strands-worker signal.
    return SimpleNamespace(
        worker_last_heartbeat_ts=0.0,
        **singletons,
    )


def _watchdog(spawner: LazyWorkerSpawner, app_state: SimpleNamespace) -> WorkerWatchdog:
    cb = app_state.circuit_breaker
    ws = app_state.worker_state
    return WorkerWatchdog(spawner, cb, ws, app_state)


def test_needs_recovery_treats_http_healthy_as_alive() -> None:
    needs = WorkerWatchdog._needs_recovery
    assert needs(crashed=True, stale=False, http_ready=True) is True  # process died
    assert needs(crashed=False, stale=True, http_ready=True) is False  # stale but up
    assert needs(crashed=False, stale=True, http_ready=False) is True  # stale + down
    assert needs(crashed=False, stale=False, http_ready=True) is False  # healthy


def test_owns_worker_requires_a_process_and_auto_spawn() -> None:
    def wd(spawner: LazyWorkerSpawner) -> WorkerWatchdog:
        return WorkerWatchdog(
            spawner, WorkerCircuitBreaker(3, 30.0), WorkerState(), SimpleNamespace()
        )

    # A real (already-exited) process handle stands in for an owned worker process.
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    try:
        external = LazyWorkerSpawner("http://127.0.0.1:1", 1, auto_spawn=False)
        external.replace_process(proc)  # has a handle but is not auto-spawn
        owned = LazyWorkerSpawner("http://127.0.0.1:1", 1, auto_spawn=True)
        owned.replace_process(proc)
        adopted = LazyWorkerSpawner("http://127.0.0.1:1", 1, auto_spawn=True)
        adopted.replace_process(None)  # auto-spawn but no owned process

        assert wd(external)._owns_worker() is False
        assert wd(owned)._owns_worker() is True
        assert wd(adopted)._owns_worker() is False
    finally:
        if proc.poll() is None:
            proc.kill()


def test_restart_cooldown_gate() -> None:
    wd = WorkerWatchdog(
        LazyWorkerSpawner("http://127.0.0.1:1", 1, auto_spawn=True),
        WorkerCircuitBreaker(3, 30.0),
        WorkerState(),
        SimpleNamespace(),
    )
    # No prior cycle → allowed.
    assert wd._restart_cooldown_elapsed(now=1000.0) is True
    wd._last_restart_cycle_ts = 1000.0
    # Within the cooldown window → blocked.
    assert wd._restart_cooldown_elapsed(now=1000.0 + 5.0) is False
    # Past the cooldown window → allowed again.
    past = 1000.0 + settings.watchdog_restart_cooldown_seconds + 1.0
    assert wd._restart_cooldown_elapsed(now=past) is True


@pytest.mark.asyncio
async def test_external_healthy_worker_stale_heartbeat_is_not_restarted() -> None:
    with _health_server() as port:
        spawner = LazyWorkerSpawner(f"http://127.0.0.1:{port}", port, auto_spawn=False)
        spawner.replace_process(None)  # adopted external worker: spawned, no process
        app_state = _stale_app_state(
            circuit_breaker=WorkerCircuitBreaker(3, 30.0),
            worker_spawner=spawner,
            worker_state=WorkerState(),
        )
        watchdog = _watchdog(spawner, app_state)

        for _ in range(5):
            await watchdog._tick()

        ws = app_state.worker_state
        # No thrash: a HTTP-healthy worker is never restarted, breaker never forced.
        assert ws.worker_restart_count == 0
        assert app_state.circuit_breaker.state == "closed"
        assert ws.worker_status == "up"
        # Health tells the truth: closed breaker, zero restarts, alive.
        health = assemble_health_status(app_state=app_state)
        assert health["circuit_breaker"] == "closed"
        assert health["worker_restart_count"] == 0
        assert health["worker_status"] == "up"


@pytest.mark.asyncio
async def test_unowned_down_worker_is_reported_not_restarted() -> None:
    # No listener → worker unreachable; auto_spawn False → external (not ours).
    port = _free_port()
    spawner = LazyWorkerSpawner(f"http://127.0.0.1:{port}", port, auto_spawn=False)
    spawner.replace_process(None)
    app_state = _stale_app_state(
        circuit_breaker=WorkerCircuitBreaker(3, 30.0),
        worker_spawner=spawner,
        worker_state=WorkerState(),
    )
    watchdog = _watchdog(spawner, app_state)

    for _ in range(5):
        await watchdog._tick()

    ws = app_state.worker_state
    # An unreachable worker we do NOT own is reported down, never restarted, and the
    # breaker is never force-opened (that would 503 dispatches for a worker whose
    # lifecycle we do not control). This pins the VAULTSPEC_AUTO_SPAWN_WORKER=false
    # gate onto the watchdog's respawn path, not just startup.
    assert ws.worker_restart_count == 0
    assert app_state.circuit_breaker.state == "closed"
    assert ws.worker_status == "down"
