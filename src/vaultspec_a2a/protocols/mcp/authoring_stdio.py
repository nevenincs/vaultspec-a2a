"""Per-run stdio MCP bridge for the engine authoring tools.

Spawned by the CLI as ``python -m vaultspec_a2a.protocols.mcp.authoring_stdio``.
The process serves the run's handed proposal/read catalog over stdio. Production
children relay calls to the worker over authenticated loopback HTTP. The worker
owns engine credentials, refresh and private replay state. An explicitly
configured direct transport remains available to standalone callers.

Token hygiene: the role actor token arrives by environment; a standalone direct
caller also hands its machine bearer. These credentials are held only for this
process's lifetime, and are NEVER written to stdout (the
MCP JSON-RPC channel) or stderr. stdout carries only MCP protocol frames; the
only stderr output is a value-free diagnostic when required env is absent.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack
from functools import partial
from pathlib import Path
from typing import Any, Literal, cast

from mcp.server.stdio import stdio_server
from pydantic import Field
from pydantic_settings import SettingsConfigDict

from ...authoring import AuthoringClient
from ...authoring._bridge_refresh import resolve_bridge_engine
from ...authoring._relay_client import AuthoringRelayClient
from ...authoring.catalog import (
    fetch_catalog,
    make_tool_dispatch,
    parse_catalog,
)
from ...control.env_prefix import ENV_PREFIX
from ...control.settings_base import ProjectSettings, env_name
from .tools.authoring_bridge import LOGICAL_CALL_ID_META_KEY, build_authoring_mcp_server

__all__ = [
    "ENV_ACTOR_TOKEN",
    "ENV_BASE_URL",
    "ENV_BEARER",
    "ENV_CALL_ID_SOURCE",
    "ENV_CALL_SCOPE",
    "ENV_CATALOG_JSON",
    "ENV_DEBUG_MARKER",
    "ENV_JOURNAL_PATH",
    "ENV_REFRESH_RECORD",
    "ENV_REFRESH_ROOTS_JSON",
    "ENV_RELAY_URL",
    "ENV_RUN_ID",
    "ENV_SERVER_NAME",
    "AuthoringBridgeSettings",
]


class AuthoringBridgeSettings(ProjectSettings):
    """The bridge's configuration, handed to it by the provider-side builder.

    Read from the process environment only, never a setting from a file: the
    bridge runs in the agent's working directory, and a file there must not be
    able to point the bridge at another engine or hand it another bearer.
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
    call_scope: str = "bridge"
    journal_path: Path | None = None
    call_id_source: Literal["explicit", "codex", "claude"] = "explicit"
    refresh_record: Path | None = None
    refresh_roots_json: str | None = None
    relay_url: str | None = None
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
ENV_CALL_SCOPE = env_name(AuthoringBridgeSettings, "call_scope")
ENV_JOURNAL_PATH = env_name(AuthoringBridgeSettings, "journal_path")
ENV_CALL_ID_SOURCE = env_name(AuthoringBridgeSettings, "call_id_source")
ENV_REFRESH_RECORD = env_name(AuthoringBridgeSettings, "refresh_record")
ENV_REFRESH_ROOTS_JSON = env_name(AuthoringBridgeSettings, "refresh_roots_json")
ENV_RELAY_URL = env_name(AuthoringBridgeSettings, "relay_url")
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

    if not (actor_token and run_id) or not (
        configured.relay_url or (base_url and bearer)
    ):
        # R7: name the failure, never the values.
        print(
            "authoring stdio bridge: missing required engine env vars",
            file=sys.stderr,
        )
        return 2

    handed = configured.catalog_json
    resolver = None
    if configured.refresh_record is not None:
        try:
            roots = json.loads(configured.refresh_roots_json or "null")
        except ValueError:
            print("authoring stdio bridge: invalid refresh authority", file=sys.stderr)
            return 2
        if not isinstance(roots, list) or not roots:
            print("authoring stdio bridge: invalid refresh authority", file=sys.stderr)
            return 2
        root_paths: list[Path] = []
        for root in cast("list[object]", roots):
            if not isinstance(root, str) or not Path(root).is_absolute():
                print(
                    "authoring stdio bridge: invalid refresh authority", file=sys.stderr
                )
                return 2
            root_paths.append(Path(root))
        resolver = partial(
            resolve_bridge_engine,
            configured.refresh_record,
            tuple(root_paths),
        )
    async with AsyncExitStack() as stack:
        # Serve list_tools from the worker's handed snapshot when present (no
        # engine round-trip at spawn); the engine is reached only at execute time
        # via the dispatch. Fall back to fetching when no snapshot was handed.
        if configured.relay_url:
            if not handed:
                print("authoring stdio bridge: missing relay catalog", file=sys.stderr)
                return 2
            snapshot = parse_catalog(json.loads(handed))
            relay = await stack.enter_async_context(
                AuthoringRelayClient(
                    configured.relay_url, actor_token, run_id, configured.call_scope
                )
            )
            dispatch = relay.dispatch
        else:
            assert base_url and bearer
            client = await stack.enter_async_context(
                AuthoringClient(
                    base_url, bearer, actor_token=actor_token, bearer_resolver=resolver
                )
            )
            snapshot = (
                parse_catalog(json.loads(handed))
                if handed
                else await fetch_catalog(client)
            )
            dispatch = make_tool_dispatch(
                client,
                run_id=run_id,
                actor_token=actor_token,
                snapshot=snapshot,
                call_scope=configured.call_scope,
                journal_path=configured.journal_path,
            )
        # Refresh rebuilds the client. Keep its single-consumer contract even
        # when an MCP client issues several requests on the same connection.
        dispatch_lock = asyncio.Lock()

        async def serialized_dispatch(
            name: str, arguments: dict[str, Any], *, tool_call_id: str | None = None
        ) -> dict[str, Any]:
            async with dispatch_lock:
                return await dispatch(name, arguments, tool_call_id=tool_call_id)

        server = build_authoring_mcp_server(
            snapshot,
            serialized_dispatch,
            server_name=server_name,
            logical_call_meta_key=(
                {
                    "explicit": LOGICAL_CALL_ID_META_KEY,
                    "codex": "callId",
                    "claude": "claudecode/toolUseId",
                }[configured.call_id_source]
            ),
        )
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
