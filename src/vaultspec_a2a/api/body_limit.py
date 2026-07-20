"""Bound request-body memory before :mod:`vaultspec_a2a.api.routes.gateway`.

The application installs this middleware ahead of authenticated ``/v1`` write
routes so a declared or streamed oversized body is rejected before JSON and
Pydantic parsing allocate the gateway request model. Non-``/v1`` traffic and
read-only verbs pass through unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

__all__ = ["BoundedV1WriteBodyMiddleware"]

_MAX_V1_WRITE_BODY_BYTES: Final = 1024 * 1024
_JSON_413: Final = b'{"detail":"v1 request body exceeds 1048576 bytes"}'


class BoundedV1WriteBodyMiddleware:
    """Reject oversized ``/v1`` writes before JSON parsing allocates their body."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self._is_bounded_write(scope):
            await self.app(scope, receive, send)
            return

        declared = self._content_length(scope)
        if declared is not None and declared > _MAX_V1_WRITE_BODY_BYTES:
            await self._reject(send)
            return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                await self.app(scope, self._replay(message), send)
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > _MAX_V1_WRITE_BODY_BYTES:
                await self._reject(send)
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break

        replay: Message = {
            "type": "http.request",
            "body": bytes(body),
            "more_body": False,
        }
        await self.app(scope, self._replay(replay), send)

    @staticmethod
    def _is_bounded_write(scope: Scope) -> bool:
        return (
            scope["type"] == "http"
            and scope.get("method") in {"POST", "PUT", "PATCH"}
            and str(scope.get("path", "")).startswith("/v1/")
        )

    @staticmethod
    def _content_length(scope: Scope) -> int | None:
        for name, value in scope.get("headers", ()):
            if name.lower() == b"content-length":
                try:
                    return int(value)
                except ValueError:
                    return None
        return None

    @staticmethod
    def _replay(message: Message) -> Receive:
        delivered = False

        async def receive() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return message
            return {"type": "http.disconnect"}

        return receive

    @staticmethod
    async def _reject(send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": (
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(_JSON_413)).encode("ascii")),
                ),
            }
        )
        await send({"type": "http.response.body", "body": _JSON_413})
