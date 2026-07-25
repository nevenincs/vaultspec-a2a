"""Shared Server-Sent-Events reader for the streaming certification scenarios.

One parser for the encoded progress boundary so no scenario re-derives frame
decoding. Each frame is returned with both its parsed payload and the raw joined
``data:`` text, so an assertion can bind to the encoded bytes - proving a
forbidden body never crossed the edge - not only to the decoded structure.
Heartbeat frames are skipped: they are keep-alives, not progress.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


async def read_frame(
    lines: AsyncIterator[str], *, wanted: str | None = None, timeout: float = 30.0
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
