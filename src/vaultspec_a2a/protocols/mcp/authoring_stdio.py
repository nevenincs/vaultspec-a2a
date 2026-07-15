"""Per-run stdio MCP bridge for the engine authoring tools (ADR R4 amendment).

Spawned by the CLI as ``python -m vaultspec_a2a.protocols.mcp.authoring_stdio``.
The process reconstructs the run's engine dispatch from its environment and
serves the bridged propose/read tools over stdio — the transport the pinned CLI
surfaces reliably, where the loopback HTTP MCP bridge
(``build_authoring_mcp_servers``) connects but is not surfaced to the model. The
engine edge is unchanged: this process still speaks to the engine over loopback
HTTP via :class:`AuthoringClient` under the calling role's actor token, so it is
an orchestration-internal transport swap, not an engine-contract change.

Token hygiene (ADR R7): the machine bearer and actor token arrive by environment,
are held only for this process's lifetime, and are NEVER written to stdout (the
MCP JSON-RPC channel) or stderr. stdout carries only MCP protocol frames; the
only stderr output is a value-free diagnostic when required env is absent.
"""

from __future__ import annotations

import asyncio
import os
import sys

from mcp.server.stdio import stdio_server

from ...authoring import AuthoringClient
from ...authoring.catalog import fetch_catalog, make_tool_dispatch
from .tools.authoring_bridge import build_authoring_mcp_server

__all__ = [
    "ENV_ACTOR_TOKEN",
    "ENV_BASE_URL",
    "ENV_BEARER",
    "ENV_RUN_ID",
    "ENV_SERVER_NAME",
    "main",
]

# Env var names this bridge reads. The provider-side config builder writes the
# same names (single source of truth: it imports these).
ENV_BASE_URL = "VAULTSPEC_AUTHORING_BASE_URL"
ENV_BEARER = "VAULTSPEC_AUTHORING_BEARER"
ENV_ACTOR_TOKEN = "VAULTSPEC_AUTHORING_ACTOR_TOKEN"
ENV_RUN_ID = "VAULTSPEC_AUTHORING_RUN_ID"
ENV_SERVER_NAME = "VAULTSPEC_AUTHORING_SERVER_NAME"
# Debug-only: if set to a writable path, the bridge appends a value-free startup
# line so an orchestrator can confirm the CLI actually spawned it. Never carries
# tokens (R7); off unless explicitly enabled.
ENV_DEBUG_MARKER = "VAULTSPEC_AUTHORING_DEBUG_MARKER"

_DEFAULT_SERVER_NAME = "vaultspec-authoring"


def _write_startup_marker(stage: str) -> None:
    path = os.environ.get(ENV_DEBUG_MARKER)
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{stage} pid={os.getpid()}\n")
    except OSError:
        pass


async def _amain() -> int:
    _write_startup_marker("spawned")
    base_url = os.environ.get(ENV_BASE_URL)
    bearer = os.environ.get(ENV_BEARER)
    actor_token = os.environ.get(ENV_ACTOR_TOKEN)
    run_id = os.environ.get(ENV_RUN_ID)
    server_name = os.environ.get(ENV_SERVER_NAME) or _DEFAULT_SERVER_NAME

    if not (base_url and bearer and actor_token and run_id):
        # R7: name the failure, never the values.
        print(
            "authoring stdio bridge: missing required engine env vars",
            file=sys.stderr,
        )
        return 2

    async with AuthoringClient(base_url, bearer, actor_token=actor_token) as client:
        snapshot = await fetch_catalog(client)
        dispatch = make_tool_dispatch(
            client, run_id=run_id, actor_token=actor_token, snapshot=snapshot
        )
        server = build_authoring_mcp_server(snapshot, dispatch, server_name=server_name)
        _write_startup_marker(f"serving tools={len(snapshot.tools)}")
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
    return 0


def main() -> None:
    """Console entry: run the stdio bridge until the client closes the pipe."""
    raise SystemExit(asyncio.run(_amain()))


if __name__ == "__main__":
    main()
