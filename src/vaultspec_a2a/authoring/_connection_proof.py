"""Authenticate the TCP stream before HTTPX writes authoring credentials."""

from __future__ import annotations

import hashlib
import hmac
import secrets

import anyio
import h11
import httpcore
import httpx

from ._engine_trust import CHALLENGE_HEADER, PROOF_HEADER, TrustedEngineRecord
from ._errors import AuthoringError


class EngineConnectionError(AuthoringError):
    """The connected listener has not proved possession of the engine key."""


async def _prove_stream(
    stream: httpcore.AsyncNetworkStream,
    *,
    port: int,
    bearer: str,
    proof_path: str,
    proof_domain: str | None,
) -> None:
    challenge = secrets.token_hex(32)
    protocol = h11.Connection(h11.CLIENT, max_incomplete_event_size=16_384)
    request = h11.Request(
        method=b"GET",
        target=proof_path.encode("ascii"),
        headers=[
            (b"host", f"127.0.0.1:{port}".encode("ascii")),
            (CHALLENGE_HEADER.encode("ascii"), challenge.encode("ascii")),
        ],
    )
    await stream.write(protocol.send(request) or b"", timeout=5.0)
    await stream.write(protocol.send(h11.EndOfMessage()) or b"", timeout=5.0)
    total = 0
    response: h11.Response | None = None
    while True:
        event = protocol.next_event()
        if event is h11.NEED_DATA:
            chunk = await stream.read(16_384, timeout=5.0)
            total += len(chunk)
            if not chunk or total > 65_536:
                raise EngineConnectionError("engine connection proof is incomplete")
            protocol.receive_data(chunk)
        elif isinstance(event, h11.Response):
            response = event
        elif isinstance(event, h11.EndOfMessage):
            break
        elif not isinstance(event, (h11.Data, h11.InformationalResponse)):
            raise EngineConnectionError("engine connection proof is malformed")
    if (
        response is None
        or response.status_code != 200
        or protocol.their_state is not h11.DONE
        or protocol.trailing_data[0]
    ):
        raise EngineConnectionError(
            "engine connection cannot carry authenticated requests"
        )
    headers = httpx.Headers(response.headers)
    try:
        pid = int(headers.get("x-vaultspec-engine-pid", ""))
        started = int(headers.get("x-vaultspec-engine-started-ms", ""))
        if pid <= 0 or started <= 0:
            raise ValueError("invalid lifecycle")
        identity = TrustedEngineRecord(port, pid, started, bearer)
        message = (
            identity.proof_message(challenge)
            if proof_domain is None
            else (
                f"{proof_domain}:1\n{port}\n{pid}\n{started}\n{proof_path}\n{challenge}"
            ).encode("ascii")
        )
        expected = hmac.new(bearer.encode("utf-8"), message, hashlib.sha256).hexdigest()
    except (ValueError, UnicodeError) as exc:
        raise EngineConnectionError("engine connection identity is invalid") from exc
    proof = headers.get(PROOF_HEADER, "")
    if not proof.isascii() or not hmac.compare_digest(proof, expected):
        raise EngineConnectionError("engine connection proof was rejected")


def authenticated_client(
    base_url: str,
    bearer: str,
    timeout: float,
    *,
    proof_path: str = "/health",
    proof_domain: str | None = None,
) -> httpx.AsyncClient:
    """Gate every new connection, including reconnects; reused streams stay proven.

    HTTPcore is pinned to the documented trace contract: connect completion runs
    before request headers. The proof consumes one bounded HTTP/1.1 response on
    that exact stream. No authoring header reaches an unproven replacement port.
    """
    origin = httpx.URL(base_url)
    if origin.scheme != "http" or origin.host != "127.0.0.1" or origin.port is None:
        raise EngineConnectionError(
            "authoring requires an explicit loopback engine port"
        )
    if (
        not proof_path.startswith("/")
        or not proof_path.isascii()
        or any(ord(character) < 33 or ord(character) > 126 for character in proof_path)
    ):
        raise EngineConnectionError("authoring connection proof path is invalid")

    async def trace(event: str, info: dict[str, object]) -> None:
        if event != "connection.connect_tcp.complete":
            return
        stream = info["return_value"]
        if not isinstance(stream, httpcore.AsyncNetworkStream):
            raise EngineConnectionError("engine connection stream is unavailable")
        try:
            with anyio.fail_after(5.0):
                await _prove_stream(
                    stream,
                    port=origin.port or 0,
                    bearer=bearer,
                    proof_path=proof_path,
                    proof_domain=proof_domain,
                )
        except (h11.RemoteProtocolError, h11.LocalProtocolError) as exc:
            with anyio.CancelScope(shield=True):
                await stream.aclose()
            raise EngineConnectionError("engine connection proof is malformed") from exc
        except BaseException:
            with anyio.CancelScope(shield=True):
                await stream.aclose()
            raise

    async def attach(request: httpx.Request) -> None:
        if (request.url.scheme, request.url.host, request.url.port) != (
            origin.scheme,
            origin.host,
            origin.port,
        ):
            raise EngineConnectionError(
                "authoring cannot change the authenticated origin"
            )
        request.extensions["trace"] = trace

    return httpx.AsyncClient(
        base_url=base_url,
        timeout=httpx.Timeout(timeout, connect=5.0),
        trust_env=False,
        follow_redirects=False,
        event_hooks={"request": [attach]},
    )
