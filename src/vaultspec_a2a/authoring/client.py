"""Loopback httpx client for the dashboard engine authoring plane (ADR R3).

The single seam through which this repo speaks to the engine. Every authoring
call carries two layers of auth in distinct headers: the machine bearer
(``Authorization: Bearer <token>``, the outer gate) and, for authoring
commands, the per-actor principal (``x-authoring-actor-token``). Mutating
commands are wrapped in a :class:`CommandEnvelope` with the idempotency key as
a body field; the bare actor-token bootstrap route is the sole exception.

Token hygiene (ADR R7): tokens are never logged and never rendered in
``repr`` — no bearer, actor token, or request payload is emitted to a log.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from types import TracebackType

from ._envelope import (
    AuthoringResponse,
    CommandEnvelope,
    Denial,
    decode_success_envelope,
    extract_denial,
)
from ._errors import AuthoringError, raise_for_typed_error
from .lifecycle import SseFrame, parse_sse_frame

__all__ = ["ACTOR_TOKEN_HEADER", "BEARER_HEADER", "AuthoringClient"]

BEARER_HEADER = "Authorization"
ACTOR_TOKEN_HEADER = "x-authoring-actor-token"

# The authoring subtree is nested under /authoring in the engine router.
_AUTHORING_PREFIX = "/authoring"


async def _iter_sse_frames(response: httpx.Response) -> AsyncIterator[SseFrame]:
    """Reassemble SSE line events from a stream and decode each into a frame.

    Follows the SSE framing rules: an ``event:`` field names the type
    (defaulting to ``message``), ``data:`` fields accumulate (joined by newline),
    a blank line dispatches the buffered event, and a line starting with ``:`` is
    a keep-alive comment. Undecodable or unrecognised frames are dropped by
    :func:`parse_sse_frame` returning ``None``.
    """
    event_type = "message"
    data_lines: list[str] = []
    async for raw in response.aiter_lines():
        line = raw.rstrip("\r")
        if line == "":
            if data_lines:
                frame = parse_sse_frame(event_type, "\n".join(data_lines))
                if frame is not None:
                    yield frame
            event_type = "message"
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if field == "event":
            event_type = value
        elif field == "data":
            data_lines.append(value)
    if data_lines:
        frame = parse_sse_frame(event_type, "\n".join(data_lines))
        if frame is not None:
            yield frame


class AuthoringClient:
    """Async loopback client for the engine's ``/authoring/v1`` plane.

    Parameters
    ----------
    base_url:
        Engine origin, e.g. ``http://127.0.0.1:8767`` (read from the discovery
        file; never hardcoded by callers in production).
    bearer_token:
        The machine bearer minted at engine boot and published in the
        discovery file. Sent on every request as the outer gate.
    actor_token:
        Optional default per-actor principal token. Individual calls may
        override it; the bootstrap ``mint_actor_token`` call needs none.
    client:
        Optional pre-built ``httpx.AsyncClient`` (tests inject a transport).
    timeout:
        Per-request timeout in seconds when constructing the default client.
    """

    def __init__(
        self,
        base_url: str,
        bearer_token: str,
        *,
        actor_token: str | None = None,
        client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._bearer_token = bearer_token
        self._actor_token = actor_token
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(timeout, connect=5.0),
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def aclose(self) -> None:
        """Close the underlying HTTP client if this instance owns it."""
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> AuthoringClient:
        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    def __repr__(self) -> str:
        """Redacted representation — never leaks tokens (ADR R7)."""
        actor = "set" if self._actor_token else "none"
        return f"AuthoringClient(base_url={self._base_url!r}, actor_token=<{actor}>)"

    # ------------------------------------------------------------------
    # Header assembly
    # ------------------------------------------------------------------

    def _headers(self, *, actor_token: str | None, with_actor: bool) -> dict[str, str]:
        headers = {BEARER_HEADER: f"Bearer {self._bearer_token}"}
        if with_actor:
            token = actor_token or self._actor_token
            if token is None:
                raise AuthoringError(
                    "an actor token is required for this authoring command; "
                    "mint one via mint_actor_token first"
                )
            headers[ACTOR_TOKEN_HEADER] = token
        return headers

    # ------------------------------------------------------------------
    # Low-level transport
    # ------------------------------------------------------------------

    async def post_command(
        self,
        path: str,
        command: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str,
        actor_token: str | None = None,
    ) -> AuthoringResponse | Denial:
        """POST a mutating command wrapped in a :class:`CommandEnvelope`.

        Returns an :class:`AuthoringResponse` on success or a :class:`Denial`
        when the engine returns an in-domain business denial (a 200 value).
        Raises :class:`AuthoringTransportError` for typed transport/identity
        failures.
        """
        envelope = CommandEnvelope(
            command=command, idempotency_key=idempotency_key, payload=payload
        )
        response = await self._client.post(
            self._url(path),
            json=envelope.to_body(),
            headers=self._headers(actor_token=actor_token, with_actor=True),
        )
        return self._decode(response)

    async def post_bare(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        with_actor: bool = False,
        actor_token: str | None = None,
    ) -> AuthoringResponse | Denial:
        """POST a non-enveloped body (the actor-token bootstrap seam).

        Bearer-gated only by default; ``with_actor`` adds the per-actor header
        for the rare non-envelope routes that still require a principal.
        """
        response = await self._client.post(
            self._url(path),
            json=payload,
            headers=self._headers(actor_token=actor_token, with_actor=with_actor),
        )
        return self._decode(response)

    async def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        with_actor: bool = False,
        actor_token: str | None = None,
    ) -> AuthoringResponse:
        """GET a read route and decode its success envelope."""
        response = await self._client.get(
            self._url(path),
            params=params,
            headers=self._headers(actor_token=actor_token, with_actor=with_actor),
        )
        decoded = self._decode(response)
        if isinstance(decoded, Denial):
            # Reads never denominate as business denials; treat as a protocol
            # violation rather than silently returning a non-response.
            raise AuthoringError(
                f"unexpected denial value on read {path!r}: {decoded.denial_kind}"
            )
        return decoded

    # ------------------------------------------------------------------
    # Lifecycle stream and recovery
    # ------------------------------------------------------------------

    async def stream_lifecycle(self, *, last_seq: int = 0) -> AsyncIterator[SseFrame]:
        """Open ``GET /v1/events`` from ``last_seq`` and yield decoded frames.

        The engine serves a bounded replay page from the durable outbox and
        closes the stream, so this iterator terminates naturally at end of page;
        the caller re-opens from the advanced cursor to continue. Only the
        machine bearer is required (no per-actor token). Cancelling the consuming
        task closes the underlying stream via the async context manager.

        Raises :class:`AuthoringError` when the transport rejects the request
        (e.g. a missing/invalid machine bearer yields a 401 from the outer gate),
        which is distinct from an in-band ``error`` frame carrying an
        ``error_kind``.
        """
        async with self._client.stream(
            "GET",
            self._url("/v1/events"),
            params={"last_seq": last_seq},
            headers=self._headers(actor_token=None, with_actor=False),
        ) as response:
            if response.status_code != httpx.codes.OK:
                await response.aread()
                raise AuthoringError(
                    "engine refused the lifecycle stream "
                    f"(status {response.status_code})"
                )
            async for frame in _iter_sse_frames(response):
                yield frame

    async def recovery_snapshot(
        self,
        *,
        last_seq: int = 0,
        session_id: str | None = None,
        run_id: str | None = None,
    ) -> AuthoringResponse:
        """Read the ``GET /v1/recovery`` snapshot (the SSE gap fallback)."""
        params: dict[str, Any] = {"last_seq": last_seq}
        if session_id is not None:
            params["session_id"] = session_id
        if run_id is not None:
            params["run_id"] = run_id
        return await self.get("/v1/recovery", params=params)

    # ------------------------------------------------------------------
    # Decoding
    # ------------------------------------------------------------------

    def _decode(self, response: httpx.Response) -> AuthoringResponse | Denial:
        try:
            body = response.json()
        except ValueError as exc:
            raise AuthoringError(
                f"engine returned a non-JSON body (status {response.status_code})"
            ) from exc
        if not isinstance(body, dict):
            raise AuthoringError("engine returned a non-object JSON body")
        raise_for_typed_error(response.status_code, body)
        denial = extract_denial(body)
        if denial is not None:
            return denial
        return decode_success_envelope(body)

    def _url(self, path: str) -> str:
        """Resolve an authoring path under the ``/authoring`` nest point."""
        suffix = path if path.startswith("/") else f"/{path}"
        if suffix.startswith(_AUTHORING_PREFIX):
            return suffix
        return f"{_AUTHORING_PREFIX}{suffix}"
