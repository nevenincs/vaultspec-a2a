"""Per-run stdio MCP bridge for the engine authoring tools.

Spawned by the CLI as ``python -m vaultspec_a2a.protocols.mcp.authoring_stdio``.
The process reconstructs the run's engine dispatch from its environment and
serves the bridged propose/read tools over stdio. Neither session-injected
transport surfaces to the model on the current stack — the registration-scope
matrix found only user-global home-config servers surface, over both stdio and
the loopback HTTP bridge (``build_authoring_mcp_servers``) — so stdio here is the
bridge's spawned-subprocess transport, not a surfacing lever. The engine edge is
unchanged: this process still speaks to the engine over loopback HTTP via
:class:`AuthoringClient` under the calling role's actor token, so it is an
orchestration-internal transport swap, not an engine-contract change.

Token hygiene: the machine bearer and actor token arrive by environment,
are held only for this process's lifetime, and are NEVER written to stdout (the
MCP JSON-RPC channel) or stderr. stdout carries only MCP protocol frames; the
only stderr output is a value-free diagnostic when required env is absent.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp.server.stdio import stdio_server
from pydantic import Field
from pydantic_settings import SettingsConfigDict

from ...authoring import AuthoringClient
from ...authoring.catalog import (
    fetch_catalog,
    make_tool_dispatch,
    parse_catalog,
)
from ...control.settings_base import ENV_PREFIX, ProjectSettings, env_name
from .tools.authoring_bridge import build_authoring_mcp_server

__all__ = [
    "ENV_ACTOR_TOKEN",
    "ENV_BASE_URL",
    "ENV_BEARER",
    "ENV_CATALOG_JSON",
    "ENV_DEBUG_MARKER",
    "ENV_RUN_ID",
    "ENV_SERVER_NAME",
    "AuthoringBridgeSettings",
]


class AuthoringBridgeSettings(ProjectSettings):
    """The bridge's configuration, handed to it by the provider-side builder.

    Read from the process environment only, never from a dotenv: the bridge runs
    in the agent's working directory, and a file there must not be able to point
    the bridge at another engine or hand it another bearer.
    """

    model_config = SettingsConfigDict(
        env_file=None,
        env_prefix=f"{ENV_PREFIX}AUTHORING_",
        extra="ignore",
        env_ignore_empty=True,
    )

    base_url: str | None = None
    bearer: str | None = Field(default=None, repr=False)
    actor_token: str | None = Field(default=None, repr=False)
    run_id: str | None = None
    server_name: str | None = None
    # The worker's already-fetched catalog snapshot (JSON), so the bridge serves
    # list_tools without its own engine round-trip at spawn and both sides serve
    # the SAME snapshot. Carries only tool schemas, no secret. Absent: fetch.
    catalog_json: str | None = None
    # Debug-only: a writable path the bridge appends a value-free startup line
    # to, so an orchestrator can confirm the CLI actually spawned it. Never
    # carries tokens; off unless set.
    debug_marker: Path | None = None


# The names the provider-side config builder writes, derived from the schema
# above so the reader and the writer cannot disagree.
ENV_BASE_URL = env_name(AuthoringBridgeSettings, "base_url")
ENV_BEARER = env_name(AuthoringBridgeSettings, "bearer")
ENV_ACTOR_TOKEN = env_name(AuthoringBridgeSettings, "actor_token")
ENV_RUN_ID = env_name(AuthoringBridgeSettings, "run_id")
ENV_SERVER_NAME = env_name(AuthoringBridgeSettings, "server_name")
ENV_CATALOG_JSON = env_name(AuthoringBridgeSettings, "catalog_json")
ENV_DEBUG_MARKER = env_name(AuthoringBridgeSettings, "debug_marker")

_DEFAULT_SERVER_NAME = "vaultspec-authoring"


def _write_startup_marker(stage: str, path: Path | None) -> None:
    if path is None:
        return
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{stage} pid={os.getpid()}\n")
    except OSError:
        pass


async def _amain() -> int:
    configured = AuthoringBridgeSettings()
    _write_startup_marker("spawned", configured.debug_marker)
    base_url = configured.base_url
    bearer = configured.bearer
    actor_token = configured.actor_token
    run_id = configured.run_id
    server_name = configured.server_name or _DEFAULT_SERVER_NAME

    if not (base_url and bearer and actor_token and run_id):
        # R7: name the failure, never the values.
        print(
            "authoring stdio bridge: missing required engine env vars",
            file=sys.stderr,
        )
        return 2

    handed = configured.catalog_json
    async with AuthoringClient(base_url, bearer, actor_token=actor_token) as client:
        # Serve list_tools from the worker's handed snapshot when present (no
        # engine round-trip at spawn); the engine is reached only at execute time
        # via the dispatch. Fall back to fetching when no snapshot was handed.
        if handed:
            snapshot = parse_catalog(json.loads(handed))
        else:
            snapshot = await fetch_catalog(client)
        dispatch = make_tool_dispatch(
            client, run_id=run_id, actor_token=actor_token, snapshot=snapshot
        )
        server = build_authoring_mcp_server(snapshot, dispatch, server_name=server_name)
        _write_startup_marker(
            f"serving tools={len(snapshot.tools)}", configured.debug_marker
        )
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
    return 0


def main() -> None:
    """Console entry: run the stdio bridge until the client closes the pipe."""
    # Protocol lane: stdout is JSON-RPC frames, so logging is stderr-only and
    # configure_logging asserts no stdout handler exists. The UTF-8 guard keeps
    # diagnostics safe on legacy Windows consoles without touching the frame bytes.
    from ...utils import configure_logging, reconfigure_console_utf8

    reconfigure_console_utf8()
    configure_logging("protocol")
    raise SystemExit(asyncio.run(_amain()))


if __name__ == "__main__":
    main()
