"""The single worker-health probe classifies identically via own and pooled client.

Real loopback HTTP servers and real sockets, no mocks. Pins the equivalence the
dedup exists to guarantee: an exact 200 is healthy and a 204 is NOT, for both the
self-contained client path (watchdog/boot) and the injected pooled-client path
(/health), so the two can never silently disagree on a worker's health. It also
pins the one verdict that is not about the status code at all - a connect that
never completes leaves health UNKNOWN rather than absent - against a real
unanswering port.
"""

from __future__ import annotations

import http.server
import socket
from contextlib import contextmanager
from typing import TYPE_CHECKING

import httpx
import pytest

from ...control._worker_health import WorkerHealthProbe, probe_worker_health
from ...testing import JsonReplyHandler, serve_handler

if TYPE_CHECKING:
    from collections.abc import Generator

_LOOPBACK = "127.0.0.1"
# One probe budget, short enough to keep the saturation test quick and long
# enough that a loopback connect which CAN complete does.
_PROBE_TIMEOUT_SECONDS = 0.5
# The accept queue is filled one connect at a time until a connect stops
# completing. The bound only stops a host whose queue never fills from looping
# forever; saturation is normally observed within a handful of attempts.
_MAX_PENDING_CONNECTS = 256


def _make_handler(status: int) -> type[http.server.BaseHTTPRequestHandler]:
    class _Handler(JsonReplyHandler, http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(status if self.path == "/health" else 404)
            payload = b"[]" if status == 200 and self.path == "/health" else b""
            if payload:
                self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if payload:
                self.wfile.write(payload)

    return _Handler


@contextmanager
def _health_server(status: int) -> Generator[str]:
    with serve_handler(_make_handler(status)) as port:
        yield f"http://{_LOOPBACK}:{port}"


@contextmanager
def _unanswering_listener() -> Generator[str]:
    """A real listener whose accept queue is full, so a connect gets no answer.

    Nothing here ever calls ``accept``, so every completed handshake stays queued
    and a further connect has nowhere to land: it hangs instead of being refused.
    That is what a live worker does to its owner's probe under host saturation,
    and it is the distinction the verdict under test rests on - "nothing is
    listening" versus "it did not answer in time" are different facts about the
    same port, and only the OS can actually produce the second one.

    Fills until a connect is observed not to complete, so the body runs against
    real saturation rather than a guessed backlog depth.
    """
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind((_LOOPBACK, 0))
    listener.listen(1)
    port = int(listener.getsockname()[1])
    pending: list[socket.socket] = []
    try:
        for _ in range(_MAX_PENDING_CONNECTS):
            filler = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            filler.settimeout(_PROBE_TIMEOUT_SECONDS)
            try:
                filler.connect((_LOOPBACK, port))
            except OSError:
                # The connect did not complete: the queue is full.
                filler.close()
                break
            pending.append(filler)
        yield f"http://{_LOOPBACK}:{port}"
    finally:
        for filler in pending:
            filler.close()
        listener.close()


@pytest.mark.asyncio
async def test_worker_health_200_is_healthy_via_both_client_paths() -> None:
    with _health_server(200) as url:
        own = await probe_worker_health(url, internal_token=None)
        async with httpx.AsyncClient() as pooled:
            injected = await probe_worker_health(
                url, client=pooled, internal_token=None
            )
    # ``[]`` is valid JSON but not a health-object payload. The public contract
    # keeps the exact-200 liveness verdict while withholding unusable evidence.
    assert own == WorkerHealthProbe(healthy=True, body=None)
    assert injected == WorkerHealthProbe(healthy=True, body=None)


@pytest.mark.asyncio
async def test_worker_health_204_is_unhealthy_identically_via_both_paths() -> None:
    # 204 passed the old readiness raise_for_status but fails the watchdog's exact
    # 200 - the silent disagreement this unification removes. Both must now say False.
    with _health_server(204) as url:
        own = await probe_worker_health(url, internal_token=None)
        async with httpx.AsyncClient() as pooled:
            injected = await probe_worker_health(
                url, client=pooled, internal_token=None
            )
        assert own == WorkerHealthProbe(healthy=False, body=None)
        assert injected == WorkerHealthProbe(healthy=False, body=None)


@pytest.mark.asyncio
async def test_worker_health_false_when_unreachable() -> None:
    # Nothing is listening. The public one-shot path is the dead-port contract,
    # and a refused connection is decisive: NOT indeterminate.
    assert await probe_worker_health(
        f"http://{_LOOPBACK}:9", internal_token=None
    ) == WorkerHealthProbe(healthy=False, body=None)


@pytest.mark.asyncio
async def test_worker_health_connect_timeout_is_indeterminate() -> None:
    """A saturated live worker is not demoted merely because connect ran late.

    Driven by a port that really does accept nothing further, so the refusal and
    the timeout are produced by the same transport the gateway uses in
    production - the two are a single ``except`` clause apart in the probe, and
    a stand-in transport raising the exception the test wants to see proves only
    that the classifier reads its own argument.
    """
    with _unanswering_listener() as url:
        probe = await probe_worker_health(
            url, timeout=_PROBE_TIMEOUT_SECONDS, internal_token=None
        )

    assert probe == WorkerHealthProbe(
        healthy=False,
        body=None,
        indeterminate=True,
    )
