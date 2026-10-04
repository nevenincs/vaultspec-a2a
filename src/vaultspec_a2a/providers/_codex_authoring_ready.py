"""Check the authoring surface on Codex's actual thread before model work."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from ._codex_protocol import _CodexProtocolError

if TYPE_CHECKING:
    from ._codex_app_server_client import _CodexAppServerClient
    from ._json_contract import JsonObject


async def verify_authoring_ready(
    client: _CodexAppServerClient,
    thread_id: str,
    spec: JsonObject | None,
    *,
    timeout: float,
) -> None:
    if spec is None:
        return
    name, expected = spec.get("name"), spec.get("tools")
    if not isinstance(name, str) or not isinstance(expected, list):
        raise _CodexProtocolError("invalid Codex authoring surface declaration")
    if any(not isinstance(tool, str) for tool in expected):
        raise _CodexProtocolError("invalid Codex authoring tool declaration")
    # Thread-scoped discovery uses the provider's own connection, rather than a
    # separate MCP probe that could succeed while the actual child failed.
    async with asyncio.timeout(timeout):
        while True:
            cursor = None
            seen: set[str] = set()
            server = None
            while True:
                response = await client.request(
                    "mcpServerStatus/list", {"threadId": thread_id, "cursor": cursor}
                )
                data = response.get("data")
                if not isinstance(data, list):
                    raise _CodexProtocolError("Codex omitted MCP server inventory")
                for item in data:
                    if isinstance(item, dict) and item.get("name") == name:
                        if server is not None:
                            raise _CodexProtocolError(
                                "Codex repeated the authoring server"
                            )
                        server = item
                cursor = response.get("nextCursor")
                if cursor is None:
                    break
                if not isinstance(cursor, str) or not cursor or cursor in seen:
                    raise _CodexProtocolError("Codex returned an invalid MCP cursor")
                seen.add(cursor)
            if server is None:
                raise _CodexProtocolError("Codex did not load the authoring server")
            status = server.get("runtimeStatus")
            if status in ("notStarted", "starting"):
                await asyncio.sleep(0.05)
                continue
            if status not in (None, "connected") or server.get("toolsError"):
                raise _CodexProtocolError("Codex authoring server failed startup")
            tools = server.get("tools")
            if not isinstance(tools, dict):
                raise _CodexProtocolError("Codex omitted the authoring tool inventory")
            actual = {
                item.get("name")
                for item in tools.values()
                if isinstance(item, dict) and isinstance(item.get("name"), str)
            }
            if not set(expected).issubset(actual):
                raise _CodexProtocolError(
                    "Codex authoring tool inventory is incomplete"
                )
            return
