"""mcp group: status, tools, discovery."""

from __future__ import annotations

__all__ = ["mcp_group"]

import anyio
import click

from ..protocols.mcp.server import mcp


def _tool_rows() -> list[tuple[str, str]]:
    """Return MCP tool names and concise descriptions from the live registry."""
    tools = anyio.run(mcp.list_tools)
    rows: list[tuple[str, str]] = []
    for tool in tools:
        description = (tool.description or "").strip().splitlines()[0]
        rows.append((tool.name, description))
    rows.sort(key=lambda row: row[0])
    return rows


@click.group("mcp")
def mcp_group() -> None:
    """MCP server inspection and discovery."""


@mcp_group.command()
def status() -> None:
    """Print MCP server launch instructions."""
    click.echo("The MCP server runs as a standalone process.")
    click.echo("")
    click.echo("  stdio:            python -m vaultspec_a2a.protocols.mcp")
    click.echo(
        "  streamable-http:  python -m vaultspec_a2a.protocols.mcp"
        " --transport streamable-http"
    )
    click.echo("")
    click.echo("Environment variables:")
    click.echo(
        "  VAULTSPEC_GATEWAY_URL       "
        "Gateway API base URL (default: http://localhost:8000)"
    )
    click.echo("  VAULTSPEC_MCP_HOST          Bind host (default: 0.0.0.0)")
    click.echo("  VAULTSPEC_MCP_PORT          Bind port (default: 8100)")
    click.echo("")
    click.echo(f"Tools: {len(_tool_rows())}")


@mcp_group.command("tools")
def tools_cmd() -> None:
    """List available MCP tools."""
    tool_rows = _tool_rows()
    max_name = max(len(name) for name, _ in tool_rows)
    for name, desc in tool_rows:
        click.echo(f"  {name:<{max_name}}  -- {desc}")


@mcp_group.command()
def discovery() -> None:
    """Print MCP server discovery info (static — MCP is now standalone)."""
    import json

    data = {
        "name": "vaultspec-a2a",
        "version": "0.1.0",
        "transport": [
            {"type": "stdio", "command": "python -m vaultspec_a2a.protocols.mcp"},
            {"type": "streamable-http", "url": "http://localhost:8100/mcp"},
        ],
    }
    click.echo(json.dumps(data, indent=2))
