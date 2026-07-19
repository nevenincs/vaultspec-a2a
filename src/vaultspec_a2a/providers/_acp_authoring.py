"""Bind the engine authoring tool catalog into an ACP subprocess session (R4).

The engine owns the agent-tool catalog; the authoring package snapshots it per
run (``vaultspec_a2a.authoring.catalog``). This module turns that snapshot plus
the run's loopback connection into the ``mcpServers`` config the spawned CLI
agent receives in ``session/new``: a single loopback MCP server advertising the
bridged propose/read tools. Tool execution routes back through the engine's
run-scoped execute endpoint under the calling role's actor token; that routing
lives in the served MCP module, not here.

Two invariants hold at construction time (R2 + R4):

- Loopback only. The engine edge is loopback HTTP; a non-loopback server host is
  refused so the CLI can never be pointed at a remote authoring surface.
- No vault-write path. Only the engine catalog's tools are surfaced, and the
  catalog carries no filesystem-write tool by construction; the binding refuses
  any tool whose name looks like a raw write so a drifted catalog fails loudly
  rather than silently handing an agent a direct write.

Token hygiene (R7): the machine bearer and per-actor token are held only to
assemble request headers for the local subprocess and are redacted from
``repr``; the binding is a worker-scoped runtime value, never placed in graph
state or a checkpoint.

Process topology: this module only BUILDS the per-run authoring bridge launch
spec (an HTTP entry with no process, or a ``python -m`` stdio entry). When the
stdio transport is used, the ACP/Codex provider CLI spawns that bridge as its
own child, so the bridge is a descendant of the run-owned provider root and
inherits that root's OS containment. Nothing here spawns a process.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from ..authoring import ACTOR_TOKEN_HEADER, BEARER_HEADER
from ..authoring.catalog import snapshot_to_catalog_payload
from ..protocols.mcp.authoring_stdio import (
    ENV_ACTOR_TOKEN as STDIO_ENV_ACTOR_TOKEN,
)
from ..protocols.mcp.authoring_stdio import (
    ENV_BASE_URL as STDIO_ENV_BASE_URL,
)
from ..protocols.mcp.authoring_stdio import (
    ENV_BEARER as STDIO_ENV_BEARER,
)
from ..protocols.mcp.authoring_stdio import (
    ENV_CATALOG_JSON as STDIO_ENV_CATALOG_JSON,
)
from ..protocols.mcp.authoring_stdio import (
    ENV_DEBUG_MARKER as STDIO_ENV_DEBUG_MARKER,
)
from ..protocols.mcp.authoring_stdio import (
    ENV_RUN_ID as STDIO_ENV_RUN_ID,
)
from ..protocols.mcp.authoring_stdio import (
    ENV_SERVER_NAME as STDIO_ENV_SERVER_NAME,
)
from ..thread.errors import ConfigError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ..authoring import CatalogSnapshot

__all__ = [
    "AUTHORING_MCP_SERVER_NAME",
    "AUTHORING_STDIO_MODULE",
    "LOOPBACK_HOSTS",
    "AuthoringToolBinding",
    "authoring_allowed_tool_names",
    "build_authoring_mcp_servers",
    "build_authoring_stdio_mcp_servers",
    "config_home_authoring_entry",
    "is_write_tool_name",
]

# The advertised MCP server name the CLI keys the bridged tools under.
AUTHORING_MCP_SERVER_NAME = "vaultspec-authoring"

# The stdio bridge entry module, spawned by the CLI as `python -m <module>`. The
# subprocess reconstructs the run's dispatch against the engine and serves the
# bridged tools over stdio. On the pinned stack, session-INJECTED MCP servers do
# not surface (S20 registration-scope matrix: only user-global home-config
# servers surface). The bridge reaches the model through that surfacing channel:
# its stdio spec is admitted into the isolated config home as user-global config
# by ``config_home_authoring_entry`` (S18), so the stdio shape IS load-bearing
# for surfacing there — the args signature is the home's admission key.
AUTHORING_STDIO_MODULE = "vaultspec_a2a.protocols.mcp.authoring_stdio"

# Env var names the spawned stdio bridge reads are imported from the bridge
# module itself (single source of truth: the reader owns the names; STDIO_ENV_*
# above alias them so the config writer and the reader can never diverge).

# Hosts the loopback edge permits; anything else is refused (no remote edge).
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

# Substrings that mark a raw filesystem-write tool. The engine catalog surfaces
# only proposal/read tools, so none of its names match; a match means the
# catalog drifted and a direct write would otherwise be handed to the agent.
_WRITE_TOOL_MARKERS = ("write", "put_file", "save_file", "unlink", "delete_file")


def is_write_tool_name(name: str) -> bool:
    """Return True if ``name`` looks like a raw filesystem-write tool."""
    lowered = name.casefold()
    return any(marker in lowered for marker in _WRITE_TOOL_MARKERS)


def _is_loopback(url: str) -> bool:
    """Return True if ``url`` targets a loopback host over http/https."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.hostname
    return host is not None and host in LOOPBACK_HOSTS


@dataclass(frozen=True)
class AuthoringToolBinding:
    """A worker-scoped binding of the run's authoring tools to a loopback server.

    The binding is transport-independent: the same run context is servable over
    the HTTP bridge (``server_url``, when the orchestrator stands up a loopback
    MCP server) or the stdio bridge (``engine_base_url`` + ``run_id``, when the
    CLI spawns our per-run stdio bridge subprocess). At least one transport's
    fields must be present; both may coexist. Both transports are supported;
    when both are present the stdio bridge is chosen. Session INJECTION does not
    surface either transport on the pinned stack (S20 registration-scope matrix:
    only user-global home-config servers surface); the stdio bridge instead
    reaches the model by being admitted into the isolated config home as
    user-global config (``config_home_authoring_entry``, S18), so the transport
    choice is load-bearing — only the stdio shape rides the home channel.

    Parameters
    ----------
    snapshot:
        The per-run catalog snapshot whose tools are surfaced to the agent.
    bearer_token:
        The machine bearer minted at engine boot, forwarded so the bridge can
        reach the engine. Redacted from ``repr``.
    actor_token:
        The calling role's per-actor token, forwarded so execution routes under
        that principal. Redacted from ``repr``.
    server_url:
        Loopback URL of the HTTP MCP server serving the bridged tools. Set for
        the HTTP transport; must be a loopback host.
    engine_base_url:
        Loopback origin of the engine (e.g. ``http://127.0.0.1:8767``). Set for
        the stdio transport so the spawned bridge can reach the engine.
    run_id:
        The engine run id the stdio bridge routes execution under.
    """

    snapshot: CatalogSnapshot
    bearer_token: str
    actor_token: str
    server_url: str | None = None
    engine_base_url: str | None = None
    run_id: str | None = None

    def __post_init__(self) -> None:
        if self.server_url is not None and not _is_loopback(self.server_url):
            raise ValueError(
                f"authoring MCP server_url {self.server_url!r} is not a loopback "
                f"http(s) host; the engine edge is loopback-only (R4)"
            )
        if self.engine_base_url is not None and not _is_loopback(self.engine_base_url):
            raise ValueError(
                f"authoring engine_base_url {self.engine_base_url!r} is not a "
                f"loopback http(s) host; the engine edge is loopback-only (R4)"
            )
        has_http = self.server_url is not None
        has_stdio = self.engine_base_url is not None and self.run_id is not None
        if not (has_http or has_stdio):
            raise ValueError(
                "authoring binding requires an HTTP transport (server_url) or a "
                "stdio transport (engine_base_url + run_id); neither was supplied"
            )
        if not self.bearer_token:
            raise ValueError("authoring binding requires a machine bearer token")
        if not self.actor_token:
            raise ValueError("authoring binding requires a per-actor token")
        offenders = [
            name for name in self.snapshot.tool_names() if is_write_tool_name(name)
        ]
        if offenders:
            raise ValueError(
                f"authoring catalog surfaced filesystem-write tools {offenders!r}; "
                f"agents get no vault-write path (R2)"
            )

    @property
    def tool_names(self) -> tuple[str, ...]:
        """The tool names surfaced to the agent, in catalog order."""
        return self.snapshot.tool_names()

    def __repr__(self) -> str:
        """Redacted representation — never leaks tokens."""
        return (
            f"AuthoringToolBinding(server_url={self.server_url!r}, "
            f"engine_base_url={self.engine_base_url!r}, run_id={self.run_id!r}, "
            f"tools={self.tool_names!r}, bearer_token=<redacted>, "
            f"actor_token=<redacted>)"
        )


def authoring_allowed_tool_names(binding: AuthoringToolBinding) -> list[str]:
    """Return the exact CLI tool names to auto-permit for the run.

    Claude Code names an MCP tool ``mcp__<server-name>__<tool-name>``. This
    returns exactly the run's bridged tool names under the authoring server —
    never a wildcard — so a headless run can invoke the propose/read tools while
    every other tool (built-ins, other MCP servers) stays gated.
    """
    return [f"mcp__{AUTHORING_MCP_SERVER_NAME}__{name}" for name in binding.tool_names]


def build_authoring_mcp_servers(
    binding: AuthoringToolBinding,
) -> list[dict[str, Any]]:
    """Build the ACP ``mcpServers`` list surfacing the bridged authoring tools.

    Returns a single HTTP MCP server entry (the shape the claude-agent-acp CLI
    consumes in ``session/new``: ``{name, type, url, headers}``) pointing at the
    run's loopback authoring MCP server, carrying the machine bearer and the
    per-actor token as headers so the served module can reach and route to the
    engine under the calling role.
    """
    if binding.server_url is None:
        raise ValueError(
            "HTTP authoring bridge requires server_url on the binding; this "
            "binding carries only the stdio transport"
        )
    return [
        {
            "name": AUTHORING_MCP_SERVER_NAME,
            "type": "http",
            "url": binding.server_url,
            "headers": [
                {"name": BEARER_HEADER, "value": f"Bearer {binding.bearer_token}"},
                {"name": ACTOR_TOKEN_HEADER, "value": binding.actor_token},
            ],
        }
    ]


def build_authoring_stdio_mcp_servers(
    binding: AuthoringToolBinding,
    *,
    python_executable: str | None = None,
) -> list[dict[str, Any]]:
    """Build the ACP ``mcpServers`` list that spawns the per-run stdio bridge.

    Returns a single stdio MCP server entry (the shape claude-agent-acp consumes
    in ``session/new`` for a server without a ``type``: ``{name, command, args,
    env}``) that runs ``python -m <AUTHORING_STDIO_MODULE>``. The engine origin,
    run id, and tokens travel to the subprocess by env — never argv — so a
    process listing never exposes them (R7); the subprocess reconstructs the
    run's dispatch and serves the bridged tools over stdio. Session INJECTION of
    this spec does not surface it (S20: only user-global home-config servers
    surface); the same spec is instead admitted into the isolated config home by
    ``config_home_authoring_entry`` (S18), where its ``env`` becomes
    ``${VAULTSPEC_AUTHORING_*}`` placeholders and the real values ride the CLI
    spawn env — so surfacing rides the home channel, not the injected session.

    ``python_executable`` defaults to the current interpreter (``sys.executable``),
    which in a deployed run is the venv python carrying the installed package.
    """
    if binding.engine_base_url is None or binding.run_id is None:
        raise ValueError(
            "stdio authoring bridge requires engine_base_url + run_id on the "
            "binding; this binding carries only the HTTP transport"
        )
    command = python_executable or sys.executable
    env = [
        {"name": STDIO_ENV_BASE_URL, "value": binding.engine_base_url},
        {"name": STDIO_ENV_BEARER, "value": binding.bearer_token},
        {"name": STDIO_ENV_ACTOR_TOKEN, "value": binding.actor_token},
        {"name": STDIO_ENV_RUN_ID, "value": binding.run_id},
        {"name": STDIO_ENV_SERVER_NAME, "value": AUTHORING_MCP_SERVER_NAME},
        # Hand the run's already-fetched catalog snapshot so the bridge serves
        # list_tools immediately without an engine round-trip at spawn, and both
        # sides serve the same snapshot (closes the re-fetch drift window). Carries
        # only tool schemas, no secret.
        {
            "name": STDIO_ENV_CATALOG_JSON,
            "value": json.dumps(snapshot_to_catalog_payload(binding.snapshot)),
        },
    ]
    # Forward the debug startup marker to the subprocess when enabled (the MCP
    # SDK filters arbitrary parent env, so it must ride the explicit env list).
    # Off unless the orchestrator sets it; carries no token (R7).
    debug_marker = os.environ.get(STDIO_ENV_DEBUG_MARKER)
    if debug_marker:
        env.append({"name": STDIO_ENV_DEBUG_MARKER, "value": debug_marker})
    return [
        {
            "name": AUTHORING_MCP_SERVER_NAME,
            "command": command,
            "args": ["-m", AUTHORING_STDIO_MODULE],
            "env": env,
        }
    ]


def config_home_authoring_entry(
    mcp_servers: Sequence[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Admit the run's authoring bridge into the isolated config home (S18).

    The isolated home surfaces user-global ``mcpServers`` to the model, and the
    per-run authoring bridge must ride that channel too — not only the read-only
    harness registry (``config_home_mcp_servers``). This selects the bridge spec
    out of the session's advertised ``mcp_servers`` and returns, atomically:

    - the home entry keyed by :data:`AUTHORING_MCP_SERVER_NAME` in the CLI
      user-global config shape (``{"type": "stdio", "command", "args", "env"}``)
      whose ``env`` values are ALL ``${VAULTSPEC_AUTHORING_*}`` placeholder
      strings — never the real tokens — and
    - the ``name -> real value`` map to hoist into the CLI spawn environment.

    Token hygiene (R7) rides the CLI's user-scope env-variable expansion: the
    pinned binary expands ``${VAR}`` in a user-scope stdio ``env`` value from the
    CLI process environment at parse time, so the home's ``.claude.json`` carries
    only placeholders while the real bearer/actor/run values live in the spawn
    env in memory. The two are emitted from the SAME env list here so a
    placeholder and its value can never diverge; callers MUST NOT split this.

    Admission is guarded by shape: only a spec named
    :data:`AUTHORING_MCP_SERVER_NAME` whose ``args`` are exactly
    ``["-m", AUTHORING_STDIO_MODULE]`` is admitted — i.e. provably produced by
    :func:`build_authoring_stdio_mcp_servers` off a validated
    :class:`AuthoringToolBinding`. Anything else under that name (an HTTP entry,
    a foreign module, a missing env) raises :class:`ConfigError` rather than
    surfacing an unvetted server. Returns ``({}, {})`` when no bridge spec is
    present, so a non-bridged run is unaffected.
    """
    home: dict[str, dict[str, Any]] = {}
    spawn_env: dict[str, str] = {}
    for spec in mcp_servers:
        if spec.get("name") != AUTHORING_MCP_SERVER_NAME:
            continue
        if spec.get("args") != ["-m", AUTHORING_STDIO_MODULE]:
            raise ConfigError(
                f"refusing to admit server {AUTHORING_MCP_SERVER_NAME!r} into the "
                f"isolated config home: its shape is not the per-run stdio "
                f"authoring bridge (args must be ['-m', {AUTHORING_STDIO_MODULE!r}] "
                f"as built by build_authoring_stdio_mcp_servers)"
            )
        if not spec.get("command"):
            raise ConfigError(
                f"authoring bridge spec {AUTHORING_MCP_SERVER_NAME!r} is missing a "
                f"command; cannot admit it into the isolated config home"
            )
        env_list = spec.get("env")
        if not env_list:
            raise ConfigError(
                f"authoring bridge spec {AUTHORING_MCP_SERVER_NAME!r} carries no env; "
                f"the bridge cannot reach the engine without its VAULTSPEC_AUTHORING_* "
                f"variables"
            )
        home_env: dict[str, str] = {}
        for item in env_list:
            var = item["name"]
            home_env[var] = f"${{{var}}}"
            spawn_env[var] = item["value"]
        # Pin the emitted command to THIS worker's interpreter rather than
        # passing the spec's value through: the bridge is `python -m <module>` in
        # the worker's own venv, and sys.executable is the trusted interpreter that
        # carries the installed package. The spec's command is validated present
        # above (shape integrity) but never trusted as the launched binary.
        home[AUTHORING_MCP_SERVER_NAME] = {
            "type": "stdio",
            "command": sys.executable,
            "args": ["-m", AUTHORING_STDIO_MODULE],
            "env": home_env,
        }
    return home, spawn_env
