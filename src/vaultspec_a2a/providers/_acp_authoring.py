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
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from ..authoring import ACTOR_TOKEN_HEADER, BEARER_HEADER

if TYPE_CHECKING:
    from ..authoring import CatalogSnapshot

__all__ = [
    "AUTHORING_MCP_SERVER_NAME",
    "LOOPBACK_HOSTS",
    "AuthoringToolBinding",
    "build_authoring_mcp_servers",
    "is_write_tool_name",
]

# The advertised MCP server name the CLI keys the bridged tools under.
AUTHORING_MCP_SERVER_NAME = "vaultspec-authoring"

# Hosts the loopback edge permits; anything else is refused (R4, no remote edge).
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

    Parameters
    ----------
    snapshot:
        The per-run catalog snapshot whose tools are surfaced to the agent.
    server_url:
        Loopback URL of the MCP server that serves the bridged tools (the run's
        authoring MCP endpoint). Must be a loopback host.
    bearer_token:
        The machine bearer minted at engine boot, forwarded so the served MCP
        module can reach the engine. Redacted from ``repr`` (R7).
    actor_token:
        The calling role's per-actor token, forwarded so execution routes under
        that principal. Redacted from ``repr`` (R7).
    """

    snapshot: CatalogSnapshot
    server_url: str
    bearer_token: str
    actor_token: str

    def __post_init__(self) -> None:
        if not _is_loopback(self.server_url):
            raise ValueError(
                f"authoring MCP server_url {self.server_url!r} is not a loopback "
                f"http(s) host; the engine edge is loopback-only (R4)"
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
        """Redacted representation — never leaks tokens (R7)."""
        return (
            f"AuthoringToolBinding(server_url={self.server_url!r}, "
            f"tools={self.tool_names!r}, bearer_token=<redacted>, "
            f"actor_token=<redacted>)"
        )


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
