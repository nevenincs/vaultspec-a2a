"""Shared Server-Sent-Events frame reader for real-process streaming proofs.

One parser for the encoded progress boundary so no test tier re-derives frame
decoding. Each frame is returned with both its parsed payload and the raw
joined ``data:`` text, so an assertion can bind to the encoded bytes - proving
a forbidden body never crossed the edge - not only to the decoded structure.
Heartbeat frames are always skipped: they are keep-alives, never a frame any
caller wants to assert on.

``timeout`` is required rather than defaulted: how long a caller can afford to
wait for one frame depends on what is on the other end of the stream - an
in-process ASGI app answers in milliseconds, a certification stack booting a
real subprocess tree does not - and a single silent default would be wrong for
at least one of this module's own callers.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

__all__ = ["read_frame"]


async def read_frame(
    lines: AsyncIterator[str], *, wanted: str | None = None, timeout: float
) -> tuple[dict, str]:
    """Read SSE frames until one matches (or any non-heartbeat); return it + raw."""

    async def _scan() -> tuple[dict, str]:
        buffer: list[str] = []
        async for raw in lines:
            line = raw.rstrip("\r")
            if line.startswith("data: "):
                buffer.append(line.removeprefix("data: "))
                continue
            if line == "" and buffer:
                joined = "".join(buffer)
                buffer = []
                payload = json.loads(joined)
                if payload.get("type") == "heartbeat":
                    continue
                if wanted is None or payload.get("type") == wanted:
                    return payload, joined
        raise AssertionError(
            f"stream closed before a {wanted or 'non-heartbeat'} frame"
        )

    return await asyncio.wait_for(_scan(), timeout=timeout)
