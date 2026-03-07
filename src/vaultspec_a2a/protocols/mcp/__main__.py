"""Standalone entry point for the Vaultspec MCP server.

Run independently of the gateway via stdio or Streamable HTTP transport::

    # stdio (for IDE integration via subprocess)
    python -m vaultspec_a2a.protocols.mcp

    # Streamable HTTP (for network clients)
    python -m vaultspec_a2a.protocols.mcp --transport streamable-http

Environment variables:
    VAULTSPEC_MCP_API_BASE_URL  Gateway API base URL (default: http://localhost:8000)
    VAULTSPEC_MCP_HOST          Bind host for streamable-http (default: 0.0.0.0)
    VAULTSPEC_MCP_PORT          Bind port for streamable-http (default: 8100)
"""

import argparse
import asyncio

from .server import _mcp_settings, mcp


def main() -> None:
    """Launch the MCP server with configurable transport."""
    parser = argparse.ArgumentParser(description="Vaultspec MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="Transport mode (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default=None,
        help=f"Bind host for streamable-http (default: {_mcp_settings.mcp_host})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"Bind port for streamable-http (default: {_mcp_settings.mcp_port})",
    )
    args = parser.parse_args()

    if args.transport == "stdio":
        asyncio.run(mcp.run_stdio_async())
    else:
        host = args.host or _mcp_settings.mcp_host
        port = args.port or _mcp_settings.mcp_port
        asyncio.run(mcp.run_streamable_http_async(host=host, port=port))


if __name__ == "__main__":
    main()
