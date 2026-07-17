"""The single worker-health probe classifies identically via own and pooled client.

Real loopback HTTP servers, no mocks. Pins the equivalence the dedup exists to
guarantee: an exact 200 is healthy and a 204 is NOT, for both the self-contained
client path (watchdog/boot) and the injected pooled-client path (/api/health), so
the two can never silently disagree on a worker's health.
"""

from __future__ import annotations

import http.server
import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING

import httpx
import pytest

from vaultspec_a2a.control.worker_management import _check_worker_health

if TYPE_CHECKING:
    from collections.abc import Iterator


def _make_handler(status: int) -> type[http.server.BaseHTTPRequestHandler]:
    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(status if self.path == "/health" else 404)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            """Silence the default access log."""

    return _Handler


@contextmanager
def _health_server(status: int) -> Iterator[str]:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(status))
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.asyncio
async def test_worker_health_200_is_healthy_via_both_client_paths() -> None:
    with _health_server(200) as url:
        assert await _check_worker_health(url) is True
        async with httpx.AsyncClient() as pooled:
            assert await _check_worker_health(url, client=pooled) is True


@pytest.mark.asyncio
async def test_worker_health_204_is_unhealthy_identically_via_both_paths() -> None:
    # 204 passed the old /api/health raise_for_status but fails the watchdog's exact
    # 200 - the silent disagreement this unification removes. Both must now say False.
    with _health_server(204) as url:
        own = await _check_worker_health(url)
        async with httpx.AsyncClient() as pooled:
            injected = await _check_worker_health(url, client=pooled)
        assert own is False
        assert injected is False


@pytest.mark.asyncio
async def test_worker_health_false_when_unreachable() -> None:
    # Nothing is listening; both an own and an injected client must degrade to False.
    assert await _check_worker_health("http://127.0.0.1:9") is False
    async with httpx.AsyncClient() as pooled:
        assert await _check_worker_health("http://127.0.0.1:9", client=pooled) is False
