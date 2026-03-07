"""mcp group: status, tools, discovery."""

from __future__ import annotations


__all__ = ["mcp_group"]

import click


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
        "  VAULTSPEC_MCP_API_BASE_URL  "
        "Gateway API base URL (default: http://localhost:8000)"
    )
    click.echo("  VAULTSPEC_MCP_HOST          Bind host (default: 0.0.0.0)")
    click.echo("  VAULTSPEC_MCP_PORT          Bind port (default: 8100)")
    click.echo("")
    click.echo(f"Tools: {len(_TOOLS)}")


_TOOLS: list[tuple[str, str]] = [
    ("start_thread", "Start a new agent team workflow (non-blocking)"),
    ("list_threads", "List existing orchestration threads"),
    ("get_thread_status", "Query the status of a specific thread"),
    ("send_message", "Send a follow-up message into an existing thread"),
    ("respond_to_permission", "Respond to a pending permission request"),
    ("get_team_status", "Get agent lifecycle states and active threads"),
    ("get_pending_permissions", "List outstanding permission requests"),
    ("list_team_presets", "List available team presets with details"),
    ("delete_thread", "Permanently delete a thread and its data"),
    ("archive_thread", "Archive a completed/failed/cancelled thread"),
    ("cancel_thread", "Cancel a running thread"),
]


@mcp_group.command("tools")
def tools_cmd() -> None:
    """List available MCP tools."""
    max_name = max(len(name) for name, _ in _TOOLS)
    for name, desc in _TOOLS:
        click.echo(f"  {name:<{max_name}}  -- {desc}")


@mcp_group.command()
def discovery() -> None:
    """Print MCP server discovery info (static — MCP is now standalone)."""
    import json  # noqa: PLC0415

    data = {
        "name": "vaultspec-a2a",
        "version": "0.1.0",
        "transport": [
            {"type": "stdio", "command": "python -m vaultspec_a2a.protocols.mcp"},
            {"type": "streamable-http", "url": "http://localhost:8100/mcp"},
        ],
    }
    click.echo(json.dumps(data, indent=2))
