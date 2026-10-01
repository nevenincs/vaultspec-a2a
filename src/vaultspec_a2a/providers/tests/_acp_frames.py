"""Shared ACP stdout frame pieces for live provider subprocess tests.

Both live subprocess tests (the authoring-bridge connection proof and the
migration handshake-surface regression) drive the raw ACP JSON-RPC stream and
need to pull the response frame for a specific request id off the agent's
stdout. This is that one reader, shared rather than duplicated per file, beside
the mode surface every session result has to carry.
"""

from __future__ import annotations

import asyncio
import json

from pydantic import TypeAdapter, ValidationError

from .._json_contract import JsonObject

__all__ = ["SESSION_MODES", "read_acp_frame"]

# What a lane reports about the permission modes it can run in, in the pinned
# adapter's own session-result shape. An unattended session is pinned to a mode
# and verifies it against this list, and a lane that advertises none is refused,
# so a responder that opens a session has to say it - the real one always does.
#
# The ids are the catalog a session reports when it has declined the permission
# bypass capability, which is every session this project opens. A session that
# keeps the capability also reports `bypassPermissions`; no lane here does.
SESSION_MODES: JsonObject = {
    "currentModeId": "default",
    "availableModes": [
        {"id": "default", "name": "Manual"},
        {"id": "acceptEdits", "name": "Accept edits"},
        {"id": "plan", "name": "Plan"},
        {"id": "auto", "name": "Auto"},
    ],
}

_JSON_OBJECT = TypeAdapter[JsonObject](JsonObject)


async def read_acp_frame(
    stdout: asyncio.StreamReader, want_id: int, timeout: float, *, max_frames: int = 60
) -> JsonObject:
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
            frame = _JSON_OBJECT.validate_json(raw.decode("utf-8").strip())
        except (json.JSONDecodeError, ValidationError):
            continue
        if frame.get("id") == want_id:
            return frame
    raise AssertionError(f"no frame with id {want_id}")
