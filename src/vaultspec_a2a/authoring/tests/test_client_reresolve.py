"""Real-objects proof of the machine-bearer re-resolution seam.

An engine that restarts mid-run republishes its ``service.json`` with a fresh
machine bearer; the long-lived worker's :class:`AuthoringClient` is then holding
a stale token and the very next authoring call trips the outer bearer gate with
a bare 401. These tests stand up a genuine loopback HTTP server (real sockets,
real ``httpx`` requests - no mocks, no monkeypatch) that behaves like that outer
gate, rotate its accepted bearer together with the discovery file, and assert
the client re-resolves from ``service.json`` and retries exactly once.

Three behaviours are pinned: recovery after a rotation (the engine-restart
simulation), no retry on an inner per-actor 401 (only the outer machine gate is
transient), and a loud failure when the engine is genuinely gone so a stale
bearer never silently degrades into an infinite quiet retry.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING

import pytest

from .. import AuthoringClient
from .._envelope import AuthoringResponse
from .._errors import AuthoringError, AuthoringTransportError
from ..discovery import SERVICE_JSON_ENV, resolve_engine

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

_BOOT_BEARER = "boot-bearer-token"
_ROTATED_BEARER = "rotated-bearer-token"


@dataclass
class _EngineState:
    """Mutable server-side state shared with the request handler."""

    current_bearer: str
    reject_actor: bool = False
    requests: list[dict[str, str | None]] = field(default_factory=list)


def _make_handler(state: _EngineState) -> type[BaseHTTPRequestHandler]:
    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return  # silence the stdlib access log

        def _reply(self, status: int, body: dict[str, object]) -> None:
            payload = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:
            if self.path == "/health":
                self._reply(200, {"status": "ok"})
                return
            self._reply(404, {"error": "not found"})

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length:
                self.rfile.read(length)
            bearer = self.headers.get("Authorization", "").removeprefix("Bearer ")
            state.requests.append({"path": self.path, "bearer": bearer})
            if bearer != state.current_bearer:
                # Outer machine bearer gate: bare Unauthorized, no error_kind.
                self._reply(401, {"error": "Unauthorized"})
                return
            if state.reject_actor:
                # Inner per-actor gate: 401 WITH an actor-token error_kind.
                self._reply(
                    401,
                    {
                        "error": "actor token unknown",
                        "error_kind": "authoring_actor_token_unknown",
                    },
                )
                return
            self._reply(200, {"data": {"ok": True}})

    return _Handler


@dataclass
class _LiveEngine:
    base_url: str
    port: int
    state: _EngineState
    _server: ThreadingHTTPServer

    def rotate_bearer(self, new_bearer: str, service_json: Path) -> None:
        """Simulate an engine restart: swap the accepted bearer and rewrite disk."""
        self.state.current_bearer = new_bearer
        _write_service_json(service_json, self.port, new_bearer)

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()


def _write_service_json(path: Path, port: int, bearer: str) -> None:
    path.write_text(
        json.dumps(
            {
                "port": port,
                "service_token": bearer,
                "last_heartbeat": int(time.time() * 1000),
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture
def live_engine() -> Iterator[_LiveEngine]:
    state = _EngineState(current_bearer=_BOOT_BEARER)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(state))
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    engine = _LiveEngine(
        base_url=f"http://127.0.0.1:{port}",
        port=port,
        state=state,
        _server=server,
    )
    try:
        yield engine
    finally:
        engine.stop()
        thread.join(timeout=5.0)


@pytest.fixture
def service_json(live_engine: _LiveEngine, tmp_path: Path) -> Iterator[Path]:
    """A real discovery file for ``resolve_engine`` pinned via the env override.

    The env var is the first (and here only) discovery candidate, so the real
    ``resolve_engine`` reads this file and confirms liveness against the live
    loopback engine - the production path, not a stand-in. The override env var
    is the discovery module's own public contract (:data:`SERVICE_JSON_ENV`); it
    is saved and restored around the test rather than monkeypatched.
    """
    path = tmp_path / "service.json"
    _write_service_json(path, live_engine.port, _BOOT_BEARER)
    previous = os.environ.get(SERVICE_JSON_ENV)
    os.environ[SERVICE_JSON_ENV] = str(path)
    try:
        yield path
    finally:
        if previous is None:
            os.environ.pop(SERVICE_JSON_ENV, None)
        else:
            os.environ[SERVICE_JSON_ENV] = previous


@pytest.mark.asyncio
async def test_recovers_after_engine_bearer_rotation(
    live_engine: _LiveEngine, service_json: Path
) -> None:
    """A mid-run bearer rotation is recovered by one re-resolve-and-retry."""
    async with AuthoringClient(
        live_engine.base_url,
        _BOOT_BEARER,
        bearer_resolver=resolve_engine,
    ) as client:
        first = await client.post_bare("/v1/sessions", {"scope": "repo"})
        assert isinstance(first, AuthoringResponse)
        assert first.data == {"ok": True}
        assert len(live_engine.state.requests) == 1

        # Engine restarts: it now accepts only the rotated bearer and republishes
        # the discovery file. The client is still holding the boot bearer.
        live_engine.rotate_bearer(_ROTATED_BEARER, service_json)

        second = await client.post_bare("/v1/sessions", {"scope": "repo"})
        assert isinstance(second, AuthoringResponse)
        assert second.data == {"ok": True}

    # Second call = one stale-bearer 401 then one retry with the re-resolved
    # bearer: exactly two extra requests, the last carrying the rotated token.
    assert len(live_engine.state.requests) == 3
    assert live_engine.state.requests[1]["bearer"] == _BOOT_BEARER
    assert live_engine.state.requests[2]["bearer"] == _ROTATED_BEARER


@pytest.mark.asyncio
async def test_inner_actor_token_401_is_not_retried(
    live_engine: _LiveEngine, service_json: Path
) -> None:
    """An inner per-actor 401 is not retried; only the outer gate is transient."""
    live_engine.state.reject_actor = True
    async with AuthoringClient(
        live_engine.base_url,
        _BOOT_BEARER,
        bearer_resolver=resolve_engine,
    ) as client:
        with pytest.raises(AuthoringTransportError) as exc:
            await client.post_command(
                "/v1/sessions",
                "create_session",
                {"scope": "repo"},
                idempotency_key="k1",
                actor_token="some-actor-token",
            )
    assert exc.value.is_actor_token_rejection
    assert not exc.value.is_machine_bearer_rejection
    # No re-resolve, no retry: a single request reached the engine.
    assert len(live_engine.state.requests) == 1


@pytest.mark.asyncio
async def test_fails_loud_when_engine_is_unreachable(
    live_engine: _LiveEngine,
) -> None:
    """A stale bearer with no reachable engine fails loud, never a quiet retry loop."""

    # The resolver returning None is exactly ``resolve_engine``'s real contract
    # output when the engine is down / its service.json is unreadable; here we
    # exercise the client's fail-loud branch deterministically without depending
    # on host-global discovery files.
    def _unreachable() -> None:
        return None

    resolver: Callable[[], None] = _unreachable
    # Rotate the accepted bearer so the client's boot bearer trips the outer gate.
    live_engine.state.current_bearer = _ROTATED_BEARER
    async with AuthoringClient(
        live_engine.base_url,
        _BOOT_BEARER,
        bearer_resolver=resolver,
    ) as client:
        with pytest.raises(AuthoringError) as exc:
            await client.post_bare("/v1/sessions", {"scope": "repo"})
    assert not isinstance(exc.value, AuthoringTransportError)
    assert "re-resolving the machine bearer" in str(exc.value)
