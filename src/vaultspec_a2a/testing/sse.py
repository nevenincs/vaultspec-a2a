"""Test-side readers over the production SSE decoder.

Decoding the wire grammar is :mod:`vaultspec_a2a.streaming.sse_frames`'s job and
is not repeated here. This module only turns a dispatched event into the frame a
test asserts on - its id, its type and its JSON payload, with the raw ``data``
text kept beside the parsed value so an assertion can bind to the encoded bytes
and prove a forbidden body never crossed the edge - and bounds how long a test
waits for the next frame on a live stream.

``timeout`` is required on :func:`read_frame` rather than defaulted: how long a
caller can afford to wait for one frame depends on what is on the other end of
the stream - an in-process ASGI app answers in milliseconds, a certification
stack booting a real subprocess tree does not - and a single silent default
would be wrong for at least one caller.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..graph.enums import ServerEventType
from ..streaming.sse_frames import SseEvent, decode_sse_text, iter_sse_events
from ..thread.snapshots import wire_event_type

if TYPE_CHECKING:
    from collections.abc import AsyncIterable

__all__ = ["SseFrame", "SseReader", "decode_frame", "read_frame"]


@dataclass(frozen=True, slots=True)
class SseFrame:
    """One dispatched event: its id field, its type and its decoded payload."""

    event_id: str | None
    event: str
    raw: str
    data: dict[str, Any]

    @classmethod
    def from_event(cls, event: SseEvent) -> SseFrame:
        """Decode the JSON object an event carries in its ``data`` field."""
        payload = json.loads(event.data)
        if not isinstance(payload, dict):
            raise AssertionError(f"SSE data is not a JSON object: {event.data!r}")
        return cls(
            event_id=event.event_id, event=event.event, raw=event.data, data=payload
        )

    @property
    def sequence(self) -> int | None:
        """The decimal half of the id field, or ``None`` when there is no id."""
        if self.event_id is None:
            return None
        _, _, decimal = self.event_id.rpartition(":")
        return int(decimal) if decimal.isdigit() else None

    @property
    def type(self) -> str:
        """The payload's frame type under either wire key, or the empty string."""
        return wire_event_type(self.data)


class SseReader:
    """Pull dispatched frames, one at a time, from one streaming response."""

    def __init__(self, lines: AsyncIterable[str]) -> None:
        self._events = iter_sse_events(lines)

    async def next_frame(self, *, timeout: float = 10.0) -> SseFrame:
        """Return the next dispatched frame, waiting at most *timeout* for it."""
        try:
            event = await asyncio.wait_for(anext(self._events), timeout=timeout)
        except StopAsyncIteration:
            raise AssertionError("stream closed before another frame") from None
        return SseFrame.from_event(event)

    async def until(self, frame_type: str, *, limit: int = 200) -> list[SseFrame]:
        """Read frames up to and including the first one of *frame_type*."""
        collected: list[SseFrame] = []
        for _ in range(limit):
            frame = await self.next_frame()
            collected.append(frame)
            if frame.type == frame_type:
                return collected
        raise AssertionError(f"no {frame_type!r} frame within {limit} frames")


def decode_frame(raw: bytes) -> SseFrame:
    """Decode one complete encoded frame, as ``encode_sse_frame`` returns it."""
    events = decode_sse_text(raw.decode("utf-8"))
    if len(events) != 1:
        raise AssertionError(
            f"expected one SSE event, decoded {len(events)} from {raw!r}"
        )
    return SseFrame.from_event(events[0])


async def read_frame(
    lines: AsyncIterable[str], *, wanted: str | None = None, timeout: float
) -> tuple[dict[str, object], str]:
    """Read frames until one matches (or any non-heartbeat); return it and its raw.

    Heartbeats are always skipped: they are keep-alives, never a frame a caller
    wants to assert on. The kind is read through the owner of the mirrored
    ``type``/``event_type`` pair, so a producer that wrote only the other key
    does not read as untyped - skipping no keep-alive and matching no wanted
    frame.
    """

    async def _scan() -> tuple[dict[str, object], str]:
        async for event in iter_sse_events(lines):
            frame = SseFrame.from_event(event)
            if frame.type == ServerEventType.HEARTBEAT:
                continue
            if wanted is None or frame.type == wanted:
                return frame.data, frame.raw
        raise AssertionError(
            f"stream closed before a {wanted or 'non-heartbeat'} frame"
        )

    return await asyncio.wait_for(_scan(), timeout=timeout)
