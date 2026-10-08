"""Bound gateway and worker HTTP bodies before JSON and model parsing."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable

    from starlette.types import ASGIApp, Message, Receive, Scope, Send

__all__ = [
    "BoundedHttpBodyMiddleware",
    "dispatch_envelope_budget",
    "gateway_body_limit",
    "worker_body_limit",
]

_MAX_V1_WRITE_BODY_BYTES: Final = 1024 * 1024

#: What a request whose declared length cannot be read is told.
#:
#: Deliberately not a size refusal. The request is not too large - it is
#: unreadable, and the two are different facts for a client: one says "send
#: less", the other says "send a well-formed request".
_UNREADABLE_LENGTH_DETAIL: Final = (
    "Content-Length must be a single non-negative decimal integer"
)

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


def dispatch_envelope_budget(settings: _BodyLimitSettings) -> int:
    """The bytes one gateway-to-worker dispatch envelope may occupy.

    The sender's budget IS the receiver's allowance, named here beside it rather
    than restated anywhere else. A dispatch is built from state the gateway
    accepted earlier - a seed transcript, a frozen graph, a context preamble -
    and the sum of those is not bounded by any one of their own caps, so an
    envelope can legitimately exceed what the worker's own body limit admits.
    Measuring it against this number before delivery is what turns that into a
    refusal the caller is told about, instead of a 413 discovered at the far end
    of work the gateway has already accepted.
    """
    return settings.internal_max_http_body_bytes


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


@dataclass(frozen=True, slots=True)
class _DeclaredLength:
    """What a request's ``Content-Length`` header or headers say, if anything.

    ``readable`` is the distinction this type exists for. A request that
    declares nothing and a request whose declaration cannot be read were both
    reported as ``None`` and both treated as "no declaration", so a value that
    is not a length at all was silently discarded and the request admitted on
    its streamed bytes alone. The two must part company: the first is normal
    and the second is a request this middleware cannot reason about.
    """

    value: int | None
    readable: bool = True


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
        if not declared.readable:
            # Refused before a byte is received. A declaration this layer
            # cannot read is one it cannot enforce against, and admitting the
            # request anyway left the bound resting on the stream counter
            # alone - which is the path a caller controls.
            await self._reject(send, _UNREADABLE_LENGTH_DETAIL, status=400)
            return
        if declared.value is not None and declared.value > max_bytes:
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
    def _content_length(scope: Scope) -> _DeclaredLength:
        """Read the declared body length, or report that it cannot be read.

        ``isdigit`` rather than ``int``, because ``int`` accepts more than the
        HTTP grammar does: a sign, surrounding whitespace, and Python's own
        digit separators all parse, so ``1_2`` read as twelve and ``-1`` read
        as a negative length that no comparison against a cap could refuse.

        Every header is read rather than the first, because two that disagree
        are two different claims about one body and neither can be trusted.
        Repeats that agree are one value and are admitted.
        """
        declared: int | None = None
        for name, value in scope.get("headers", ()):
            if name.lower() != b"content-length":
                continue
            if not value.isdigit():
                return _DeclaredLength(None, readable=False)
            length = int(value)
            if declared is not None and length != declared:
                return _DeclaredLength(None, readable=False)
            declared = length
        return _DeclaredLength(declared)

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
    async def _reject(send: Send, detail: str, *, status: int = 413) -> None:
        body = json.dumps({"detail": detail}).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": (
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ),
            }
        )
        await send({"type": "http.response.body", "body": body})
