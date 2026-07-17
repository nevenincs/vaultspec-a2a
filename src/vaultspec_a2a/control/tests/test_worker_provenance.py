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

from vaultspec_a2a.control.worker_management import (
    _evict_stale_worker,
    _fetch_worker_health,
    _same_gateway,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


def _make_handler(
    body: dict[str, object] | None,
    shutdown_flag: dict[str, bool],
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
            if self.path == "/admin/shutdown":
                shutdown_flag["called"] = True
                self.send_response(202)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            """Silence the default access log."""

    return _Handler


@contextmanager
def _worker_like(
    body: dict[str, object] | None,
) -> Iterator[tuple[str, int, dict[str, bool]]]:
    shutdown_flag: dict[str, bool] = {"called": False}
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), _make_handler(body, shutdown_flag)
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
