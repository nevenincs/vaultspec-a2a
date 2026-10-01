"""Read SSE frames off a live response body, field by field.

Shared by the resumption suites, which assert on the ``id`` field as well as
the payload - so the frames cannot be matched with a substring search over the
raw bytes the way a body-only assertion can. Parsing follows the stream
grammar: fields are the text before the first colon, one optional space after
the colon is stripped, ``data`` lines accumulate, and a blank line dispatches.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

__all__ = ["SseFrame", "SseReader"]


@dataclass(frozen=True, slots=True)
class SseFrame:
    """One dispatched event: its id field, its type, and its decoded payload."""

    event_id: str | None
    event: str | None
    data: dict[str, Any]

    @property
    def sequence(self) -> int | None:
        """The decimal half of the id field, or ``None`` when there is no id."""
        if self.event_id is None:
            return None
        _, _, decimal = self.event_id.rpartition(":")
        return int(decimal) if decimal.isdigit() else None

    @property
    def type(self) -> str:
        """The payload's frame type, or the empty string when it names none."""
        value = self.data.get("type")
        return value if isinstance(value, str) else ""


@dataclass(slots=True)
class SseReader:
    """Pull dispatched frames from one streaming response body."""

    body: AsyncIterator[bytes]
    buffer: bytes = b""
    received: list[SseFrame] = field(default_factory=list)

    async def next_frame(self, *, timeout: float = 10.0) -> SseFrame:
        """Return the next dispatched frame, reading more bytes if needed."""
        while b"\n\n" not in self.buffer:
            chunk = await asyncio.wait_for(anext(self.body), timeout=timeout)
            self.buffer += chunk
        block, _, self.buffer = self.buffer.partition(b"\n\n")
        frame = _parse(block.decode("utf-8"))
        self.received.append(frame)
        return frame

    async def until(self, frame_type: str, *, limit: int = 200) -> list[SseFrame]:
        """Read frames up to and including the first one of *frame_type*."""
        collected: list[SseFrame] = []
        for _ in range(limit):
            frame = await self.next_frame()
            collected.append(frame)
            if frame.type == frame_type:
                return collected
        raise AssertionError(f"no {frame_type!r} frame within {limit} frames")


def _parse(block: str) -> SseFrame:
    event_id: str | None = None
    event: str | None = None
    data_lines: list[str] = []
    for line in block.splitlines():
        if not line or line.startswith(":"):
            continue
        name, _, value = line.partition(":")
        value = value.removeprefix(" ")
        if name == "id":
            event_id = value
        elif name == "event":
            event = value
        elif name == "data":
            data_lines.append(value)
    payload: dict[str, Any] = json.loads("\n".join(data_lines)) if data_lines else {}
    return SseFrame(event_id=event_id, event=event, data=payload)
