"""Spawn-path provenance: a live worker on the port must be judged by which
gateway it targets, not by liveness alone.

Real loopback HTTP servers, no mocks. Pins the fix for the adoption defect where
a resident gateway blindly adopted any healthy worker squatting the worker port -
including a stale orphan still heartbeating a dead dev-band gateway - and never
re-pointed or reaped it. ``/health`` now reports the worker's heartbeat target so
the spawn path can tell a same-gateway worker (adopt) from a foreign orphan
(evict + respawn).
"""

from __future__ import annotations

import http.server
import json
import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING

import pytest

from vaultspec_a2a.control.config import settings
from vaultspec_a2a.control.worker_management import (
    LazyWorkerSpawner,
    _evict_stale_worker,
    _fetch_worker_health,
    _same_gateway,
    _worker_ready_and_ours,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


@contextmanager
def _internal_token(value: str | None) -> Iterator[None]:
    """Set ``settings.internal_token`` for the evictor's token-presenting path.

    Mirrors the sanctioned ``_SettingsOverride`` seam used across the worker
    suite - a real attribute swap on the live settings object, restored on exit,
    not a mock.
    """
    original = settings.internal_token
    settings.internal_token = value
    try:
        yield
    finally:
        settings.internal_token = original


def _make_handler(
    body: dict[str, object] | None,
    shutdown_flag: dict[str, bool],
    expected_token: str | None,
) -> type[http.server.BaseHTTPRequestHandler]:
    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path != "/health" or body is None:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            payload = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self) -> None:
            if self.path != "/admin/shutdown":
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if expected_token is not None:
                got = self.headers.get("Authorization")
                if got != f"Bearer {expected_token}":
                    self.send_response(401)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
            shutdown_flag["called"] = True
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            """Silence the default access log."""

    return _Handler


@contextmanager
def _worker_like(
    body: dict[str, object] | None,
    *,
    expected_token: str | None = None,
) -> Iterator[tuple[str, int, dict[str, bool]]]:
    shutdown_flag: dict[str, bool] = {"called": False}
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), _make_handler(body, shutdown_flag, expected_token)
    )
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}", port, shutdown_flag
    finally:
        server.shutdown()
        server.server_close()


def test_same_gateway_matches_normalized_and_treats_missing_as_match() -> None:
    ours = "http://127.0.0.1:8000"
    assert _same_gateway("http://127.0.0.1:8000/", ours) is True
    assert _same_gateway("http://127.0.0.1:8000", ours) is True
    # A worker whose /health predates the gateway_url field must not be evicted.
    assert _same_gateway(None, ours) is True
    assert _same_gateway("", ours) is True
    # A foreign / dead-gateway target is the orphan signature.
    assert _same_gateway("http://127.0.0.1:50553", ours) is False


@pytest.mark.asyncio
async def test_fetch_worker_health_returns_body_with_gateway_target() -> None:
    body: dict[str, object] = {
        "status": "ok",
        "service": "worker",
        "gateway_url": "http://127.0.0.1:8000",
    }
    with _worker_like(body) as (url, _port, _flag):
        got = await _fetch_worker_health(url)
    assert got is not None
    assert got["gateway_url"] == "http://127.0.0.1:8000"


@pytest.mark.asyncio
async def test_fetch_worker_health_none_when_unreachable() -> None:
    assert await _fetch_worker_health("http://127.0.0.1:9") is None


@pytest.mark.asyncio
async def test_evict_stale_worker_posts_shutdown_and_waits_for_port_free() -> None:
    body: dict[str, object] = {
        "status": "ok",
        "service": "worker",
        "gateway_url": "http://127.0.0.1:1",
    }
    with _worker_like(body) as (url, port, flag):
        # Server is still listening, so eviction cannot confirm the port freed.
        freed = await _evict_stale_worker(url, port, timeout=1.0)
        assert flag["called"] is True
        assert freed is False
    # Once the server is torn down the port is free; a fresh call confirms release.
    assert await _evict_stale_worker(url, port, timeout=1.0) is True


@pytest.mark.asyncio
async def test_evict_presents_internal_token_and_is_accepted() -> None:
    """The evictor must present the internal bearer so an authenticated worker
    accepts the shutdown (the eviction path is now behind auth)."""
    body: dict[str, object] = {"status": "ok", "gateway_url": "http://127.0.0.1:1"}
    with (
        _internal_token("evict-secret"),
        _worker_like(body, expected_token="evict-secret") as (url, port, flag),
    ):
        await _evict_stale_worker(url, port, timeout=1.0)
        assert flag["called"] is True


@pytest.mark.asyncio
async def test_tokenless_shutdown_is_rejected_by_authenticated_worker() -> None:
    """A worker that requires the bearer must reject an evictor with no token,
    leaving the process alive (no shutdown recorded)."""
    body: dict[str, object] = {"status": "ok", "gateway_url": "http://127.0.0.1:1"}
    with (
        _internal_token(None),
        _worker_like(body, expected_token="evict-secret") as (url, port, flag),
    ):
        await _evict_stale_worker(url, port, timeout=1.0)
        assert flag["called"] is False


@pytest.mark.asyncio
async def test_worker_ready_and_ours_accepts_a_same_gateway_worker() -> None:
    """A healthy worker declaring THIS gateway is ready and ours."""
    body: dict[str, object] = {
        "status": "ok",
        "service": "worker",
        "gateway_url": settings.gateway_url,
    }
    with _worker_like(body) as (url, _port, _flag):
        assert await _worker_ready_and_ours(url) is True


@pytest.mark.asyncio
async def test_worker_ready_and_ours_rejects_a_foreign_gateway_worker() -> None:
    """The adoption guard: a healthy worker heartbeating a DIFFERENT gateway is not
    ours, even though it answers /health on the port. This is the readiness signal
    every adoption path now routes through, so a foreign orphan cannot be adopted.
    """
    foreign = "http://127.0.0.1:59999"
    assert foreign.rstrip("/") != settings.gateway_url.rstrip("/")
    body: dict[str, object] = {
        "status": "ok",
        "service": "worker",
        "gateway_url": foreign,
    }
    with _worker_like(body) as (url, _port, _flag):
        assert await _worker_ready_and_ours(url) is False


@pytest.mark.asyncio
async def test_worker_ready_and_ours_accepts_a_legacy_worker_without_a_target() -> None:
    """A worker whose /health predates the gateway_url field is treated as ours, so
    the provenance gate never disowns a correctly-wired legacy worker."""
    body: dict[str, object] = {"status": "ok", "service": "worker"}
    with _worker_like(body) as (url, _port, _flag):
        assert await _worker_ready_and_ours(url) is True


@pytest.mark.asyncio
async def test_worker_ready_and_ours_false_when_no_worker_answers() -> None:
    assert await _worker_ready_and_ours("http://127.0.0.1:9") is False


@pytest.mark.asyncio
async def test_ensure_worker_does_not_adopt_a_foreign_worker() -> None:
    """A non-auto-spawn gateway must not mark itself paired to a foreign worker.

    Before the fix ensure_worker's fallback was a bare /health check, so a healthy
    orphan targeting another gateway squatting the port was adopted and this gateway
    dispatched to a worker emitting events elsewhere. The provenance-aware fallback
    leaves the gateway unpaired instead.
    """
    body: dict[str, object] = {
        "status": "ok",
        "service": "worker",
        "gateway_url": "http://127.0.0.1:59999",
    }
    with _worker_like(body) as (url, port, _flag):
        spawner = LazyWorkerSpawner(worker_url=url, worker_port=port, auto_spawn=False)
        await spawner.ensure_worker()
        assert spawner.spawned is False


@pytest.mark.asyncio
async def test_ensure_worker_attaches_to_a_same_gateway_worker() -> None:
    """The positive: a non-auto-spawn gateway attaches to a worker that targets it."""
    body: dict[str, object] = {
        "status": "ok",
        "service": "worker",
        "gateway_url": settings.gateway_url,
    }
    with _worker_like(body) as (url, port, _flag):
        spawner = LazyWorkerSpawner(worker_url=url, worker_port=port, auto_spawn=False)
        await spawner.ensure_worker()
        assert spawner.spawned is True
