"""Shared ACP stdout frame reader for live provider subprocess tests.

Both live subprocess tests (the authoring-bridge connection proof and the
migration handshake-surface regression) drive the raw ACP JSON-RPC stream and
need to pull the response frame for a specific request id off the agent's
stdout. This is that one reader, shared rather than duplicated per file.
"""

from __future__ import annotations

import asyncio
import json

__all__ = ["read_acp_frame"]


async def read_acp_frame(
    stdout: asyncio.StreamReader, want_id: int, timeout: float, *, max_frames: int = 60
) -> dict:
    """Return the first JSON-RPC frame from *stdout* whose ``id`` is *want_id*.

    Skips interleaved notifications and malformed lines. Raises
    ``AssertionError`` if no matching frame arrives within *max_frames* lines or
    the stream closes first.
    """
    for _ in range(max_frames):
        raw = await asyncio.wait_for(stdout.readline(), timeout=timeout)
        if not raw:
            break
        try:
            frame = json.loads(raw.decode("utf-8").strip())
        except json.JSONDecodeError:
            continue
        if frame.get("id") == want_id:
            return frame
    raise AssertionError(f"no frame with id {want_id}")
