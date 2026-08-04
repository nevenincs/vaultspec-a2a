"""The one-shot half of a JSON-RPC-over-stdio client, declared once.

Reading a single response frame off a subprocess's stdout - bounded frame count,
bounded frame size, charged against an output budget, matched on request id,
skipping anything that will not parse - was written out independently by the ACP
and Codex catalog-discovery lanes. The two implementations differed only in
DIALECT: the name of a constant, and which typed error they raise. The mechanism
was identical, including the order of its guards.

What stays a caller-side argument is exactly that dialect. Each lane raises its
own error type carrying its own vocabulary, because a Codex caller reading an
ACP-shaped protocol error would be told something untrue about which transport
failed. Passing an error factory keeps that difference explicit where a shared
error type would have flattened it.

Deliberately scoped to the ONE-SHOT call shape - a single in-flight request, no
pending-id map, no notification stream. The long-lived multiplexed session used
by the live ACP and Codex chat models is the same primitive at a larger scope,
and folding the two together here would force these callers to carry session
bookkeeping they never use. That consolidation is a separate step with its own
tests; this module is where it would land.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Protocol

from pydantic import TypeAdapter, ValidationError

from ._json_contract import JsonObject

_JSON_OBJECT: TypeAdapter[JsonObject] = TypeAdapter(JsonObject)


class OutputBudgetLike(Protocol):
    """The subset of an output budget this reader charges against."""

    def charge(self, size: int) -> None:
        """Account for *size* bytes read from the child's stream."""
        ...


class ProtocolErrorFactory(Protocol):
    """Builds the caller's own typed protocol error from a message."""

    def __call__(self, message: str) -> Exception:
        """Return the error this lane raises for a protocol fault."""
        ...


async def cancel_task(task: asyncio.Task[None]) -> None:
    """Cancel *task* and absorb the resulting cancellation."""
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


async def read_response(
    stdout: asyncio.StreamReader,
    *,
    request_id: int,
    timeout: float,
    output_budget: OutputBudgetLike,
    max_frames: int,
    max_frame_bytes: int,
    protocol_error: ProtocolErrorFactory,
) -> JsonObject:
    """Read frames until one carries *request_id*, or refuse.

    An unparseable frame is SKIPPED rather than fatal: a child may interleave
    diagnostics with protocol output, and one noisy line must not lose a
    response that arrives after it. An oversized frame is refused outright,
    because a frame that large is evidence the stream is not what this reader
    thinks it is, and charging it to the budget would be too late.
    """
    for _ in range(max_frames):
        raw = await asyncio.wait_for(stdout.readline(), timeout=timeout)
        if not raw:
            break
        if len(raw) > max_frame_bytes:
            raise protocol_error("discovery frame exceeds one MiB")
        output_budget.charge(len(raw))
        try:
            value = _JSON_OBJECT.validate_json(raw)
        except (ValidationError, UnicodeDecodeError):
            continue
        if value.get("id") == request_id:
            return value
    raise protocol_error(f"discovery received no response for request {request_id}")
