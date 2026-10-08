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

import contextlib
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler
from typing import TYPE_CHECKING, override

import pytest

from ...testing import JsonReplyHandler, serve_handler, settings_override
from .. import AuthoringClient
from .._connection_proof import EngineConnectionError
from .._envelope import AuthoringResponse
from .._errors import AuthoringError, AuthoringTransportError
from ..discovery import resolve_engine
from ._engine_peer import (
    engine_health_listener,
    reply_health_proof,
    write_engine_record,
)
from .test_engine_discovery_security import attacker_listener

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

_BOOT_BEARER = "boot-bearer-token-0123456789abcdef0123456789abcdef"
_ROTATED_BEARER = "rotated-bearer-token-0123456789abcdef0123456789abcdef"


@dataclass
class _EngineState:
    """Mutable server-side state shared with the request handler."""

    current_bearer: str
    reject_actor: bool = False
    close_after_response: bool = False
    requests: list[dict[str, str | None]] = field(default_factory=list)


def _make_handler(state: _EngineState) -> type[JsonReplyHandler]:
    # BaseHTTPRequestHandler is listed again, redundantly - see
    # testing/http.py's docstring for why.
    class _Handler(JsonReplyHandler, BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        @override
        def end_headers(self) -> None:
            if state.close_after_response and self.path != "/health":
                self.send_header("Connection", "close")
                self.close_connection = True
            super().end_headers()

        def do_GET(self) -> None:
            if self.path == "/health":
                reply_health_proof(self, state.current_bearer)
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
    _listener: contextlib.ExitStack

    def rotate_bearer(self, new_bearer: str, service_json: Path) -> None:
        """Simulate an engine restart: swap the accepted bearer and rewrite disk."""
        self.state.current_bearer = new_bearer
        _write_service_json(service_json, self.port, new_bearer)

    def stop(self) -> None:
        """Take the engine's listener down; idempotent, so teardown may repeat it."""
        self._listener.close()


def _write_service_json(path: Path, port: int, bearer: str) -> None:
    write_engine_record(path, port, bearer)


@pytest.fixture
def live_engine() -> Iterator[_LiveEngine]:
    state = _EngineState(current_bearer=_BOOT_BEARER)
    with contextlib.ExitStack() as listener:
        port = listener.enter_context(serve_handler(_make_handler(state)))
        yield _LiveEngine(
            base_url=f"http://127.0.0.1:{port}",
            port=port,
            state=state,
            _listener=listener,
        )


@pytest.fixture
def service_json(live_engine: _LiveEngine, secure_engine_dir: Path) -> Iterator[Path]:
    """A real discovery file for ``resolve_engine`` pinned through settings.

    The configured record is discovery's only candidate, so the real
    ``resolve_engine`` reads this file and confirms liveness against the live
    loopback engine - the production path, not a stand-in.
    """
    path = secure_engine_dir / "service.json"
    _write_service_json(path, live_engine.port, _BOOT_BEARER)
    with settings_override(engine_service_json=path):
        yield path


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
async def test_retry_does_not_disclose_actor_to_an_unproven_listener(
    live_engine: _LiveEngine, service_json: Path
) -> None:
    """A forged replacement record cannot redirect the retry's retained actor token."""
    live_engine.state.current_bearer = _ROTATED_BEARER
    with attacker_listener() as (port, requests):
        write_engine_record(service_json, port, _ROTATED_BEARER)
        async with AuthoringClient(
            live_engine.base_url,
            _BOOT_BEARER,
            actor_token="per-run-actor-token",
            bearer_resolver=resolve_engine,
        ) as client:
            with pytest.raises(AuthoringError, match="re-resolving"):
                await client.post_command(
                    "/v1/sessions", "create_session", {}, idempotency_key="retry"
                )
        assert len(requests) == 1
        assert "Authorization" not in requests[0]
        assert "x-authoring-actor-token" not in requests[0]
        assert "per-run-actor-token" not in str(requests)
    assert len(live_engine.state.requests) == 0


@pytest.mark.asyncio
async def test_port_takeover_after_discovery_cannot_receive_credentials(
    secure_engine_dir: Path,
) -> None:
    """Discovery and authoring use different sockets; the latter must prove itself."""
    record = secure_engine_dir / "service.json"
    with engine_health_listener() as port:
        write_engine_record(record, port)
        with settings_override(engine_service_json=record):
            endpoint = resolve_engine()
        assert endpoint is not None
    with attacker_listener(port=port) as (_, requests):
        async with AuthoringClient(
            endpoint.base_url, endpoint.bearer_token, actor_token="genuine-run-actor"
        ) as client:
            with pytest.raises(EngineConnectionError, match="proof was rejected"):
                await client.post_command(
                    "/v1/sessions", "create_session", {}, idempotency_key="takeover"
                )
        assert len(requests) == 1
        assert "Authorization" not in requests[0]
        assert "x-authoring-actor-token" not in requests[0]
        assert "genuine-run-actor" not in str(requests)
        assert endpoint.bearer_token not in str(requests)


@pytest.mark.asyncio
async def test_reconnect_after_authenticated_command_rejects_port_takeover(
    live_engine: _LiveEngine,
) -> None:
    """A proven pooled connection does not license a new connection to its port."""
    live_engine.state.close_after_response = True
    async with AuthoringClient(
        live_engine.base_url, _BOOT_BEARER, actor_token="genuine-run-actor"
    ) as client:
        first = await client.post_bare("/v1/sessions", {"scope": "repo"})
        assert isinstance(first, AuthoringResponse)
        live_engine.stop()
        with attacker_listener(port=live_engine.port) as (_, requests):
            with pytest.raises(EngineConnectionError, match="proof was rejected"):
                await client.post_command(
                    "/v1/sessions", "create_session", {}, idempotency_key="reconnect"
                )
            assert len(requests) == 1
            assert "Authorization" not in requests[0]
            assert "x-authoring-actor-token" not in requests[0]


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
