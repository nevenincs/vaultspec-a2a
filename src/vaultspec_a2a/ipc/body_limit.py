"""Bound gateway and worker HTTP bodies before JSON and model parsing."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Final, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable

    from starlette.types import ASGIApp, Message, Receive, Scope, Send

__all__ = ["BoundedHttpBodyMiddleware", "gateway_body_limit", "worker_body_limit"]

_MAX_V1_WRITE_BODY_BYTES: Final = 1024 * 1024

#: The allowance for one write, with the detail its refusal carries.
type _BodyLimit = Callable[[Scope], tuple[int, str]]


class _BodyLimitSettings(Protocol):
    """The configured allowances, handed in by the application factory.

    Read on each request rather than copied at construction, so the allowance an
    app enforces is always the configuration's current one.
    """

    @property
    def internal_max_http_body_bytes(self) -> int: ...

    @property
    def internal_max_event_batch_bytes(self) -> int: ...


def worker_body_limit(settings: _BodyLimitSettings) -> _BodyLimit:
    """Use the configured internal allowance for worker writes."""

    def limit(_scope: Scope) -> tuple[int, str]:
        max_bytes = settings.internal_max_http_body_bytes
        return max_bytes, f"Internal request body exceeds {max_bytes} bytes"

    return limit


def gateway_body_limit(settings: _BodyLimitSettings) -> _BodyLimit:
    """Preserve the versioned allowance and the larger event-batch allowance."""
    internal = worker_body_limit(settings)

    def limit(scope: Scope) -> tuple[int, str]:
        path = str(scope.get("path", ""))
        if path.startswith("/v1/"):
            max_bytes = _MAX_V1_WRITE_BODY_BYTES
            return max_bytes, f"v1 request body exceeds {max_bytes} bytes"
        if path.rstrip("/") == "/internal/events/batch":
            max_bytes = settings.internal_max_event_batch_bytes
            return max_bytes, f"Payload too large (max {max_bytes} bytes)"
        return internal(scope)

    return limit


class BoundedHttpBodyMiddleware:
    """Count received bytes on every HTTP write before handing its body onward."""

    def __init__(self, app: ASGIApp, *, limit: _BodyLimit) -> None:
        self.app = app
        self.limit = limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self._is_bounded_write(scope):
            await self.app(scope, receive, send)
            return

        max_bytes, detail = self.limit(scope)
        declared = self._content_length(scope)
        if declared is not None and declared > max_bytes:
            await self._reject(send, detail)
            return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                await self.app(scope, self._replay(message, receive), send)
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > max_bytes:
                await self._reject(send, detail)
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break

        replay: Message = {
            "type": "http.request",
            "body": bytes(body),
            "more_body": False,
        }
        await self.app(scope, self._replay(replay, receive), send)

    @staticmethod
    def _is_bounded_write(scope: Scope) -> bool:
        return scope["type"] == "http" and scope.get("method") in {
            "POST",
            "PUT",
            "PATCH",
            "DELETE",
        }

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
    def _replay(message: Message, upstream: Receive) -> Receive:
        delivered = False

        async def receive() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return message
            return await upstream()

        return receive

    @staticmethod
    async def _reject(send: Send, detail: str) -> None:
        body = json.dumps({"detail": detail}).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": (
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ),
            }
        )
        await send({"type": "http.response.body", "body": body})
