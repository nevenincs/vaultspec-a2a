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
    from types import TracebackType

from ._envelope import (
    AuthoringResponse,
    CommandEnvelope,
    Denial,
    decode_success_envelope,
    extract_denial,
)
from ._errors import AuthoringError, raise_for_typed_error

__all__ = ["ACTOR_TOKEN_HEADER", "BEARER_HEADER", "AuthoringClient"]

BEARER_HEADER = "Authorization"
ACTOR_TOKEN_HEADER = "x-authoring-actor-token"

# The authoring subtree is nested under /authoring in the engine router.
_AUTHORING_PREFIX = "/authoring"


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
