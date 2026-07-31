"""Standalone entry point for the Vaultspec MCP server.

Run independently of the gateway via stdio or Streamable HTTP transport::

    # stdio (for IDE integration via subprocess)
    python -m vaultspec_a2a.protocols.mcp

    # Streamable HTTP (for network clients)
    python -m vaultspec_a2a.protocols.mcp --transport streamable-http

Environment variables:
    VAULTSPEC_GATEWAY_URL         Gateway API base URL (default: http://localhost:18000)
    VAULTSPEC_MCP_HOST            Bind host for streamable-http (default: 0.0.0.0)
    VAULTSPEC_MCP_PORT            Bind port for streamable-http (default: 8200)
"""

import argparse
import asyncio

from mcp.server.transport_security import TransportSecuritySettings

from ...control.config import settings
from ...utils import configure_logging, reconfigure_console_utf8
from .server import mcp

__all__ = ["build_transport_security", "main"]


def build_transport_security() -> TransportSecuritySettings:
    """Build the streamable-http DNS-rebinding policy from configuration.

    Separate from :func:`main` so the policy the entrypoint actually ships is
    the same object a test can mount and drive, rather than a second copy that
    could agree with the settings while the entrypoint diverged.
    """
    return TransportSecuritySettings(
        allowed_hosts=settings.mcp_allowed_hosts,
        allowed_origins=settings.mcp_allowed_origins,
    )


def main() -> None:
    """Launch the MCP server with configurable transport."""
    reconfigure_console_utf8()
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
        help=f"Bind host for streamable-http (default: {settings.mcp_host})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"Bind port for streamable-http (default: {settings.mcp_port})",
    )
    args = parser.parse_args()

    if args.transport == "stdio":
        # stdout carries JSON-RPC frames: stderr-only logging, no stdout handler.
        configure_logging("protocol")
        asyncio.run(mcp.run_stdio_async())
    else:
        # Streamable-HTTP is a network server, not a stdout protocol: the service
        # lane (JSON to stderr + rotating file) is correct; stdout is free.
        configure_logging("service", service_name="mcp")
        # Bind address is a per-run transport argument, not server state: the
        # server object no longer carries host/port settings.
        #
        # DNS-rebinding protection is passed explicitly. The SDK's middleware
        # DISABLES the Host/Origin checks when handed no settings, so omitting
        # this argument silently ships an unguarded network listener.
        asyncio.run(
            mcp.run_streamable_http_async(
                host=args.host or settings.mcp_host,
                port=args.port or settings.mcp_port,
                transport_security=build_transport_security(),
            )
        )


if __name__ == "__main__":
    main()
