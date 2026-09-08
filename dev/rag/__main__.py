"""The ``python -m dev.rag`` entry point.

Usage::

    python -m dev.rag tool-contract

Verifies that the ACP launch spec actually serves the MCP tools the harness
declares. This runs against the real provider resolution rather than a
description of it, so a spec that has drifted from the servers it names fails
here rather than at launch.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

#: The harness MCP servers whose served tool surface is verified.
HARNESS_SERVERS = ("vaultspec-rag",)


def _tool_contract() -> int:
    """Verify the harness MCP contract against the resolved launch spec.

    Returns:
        0 when the served tools satisfy the declared contract, otherwise 1.
    """
    from vaultspec_a2a.providers._acp_mcp import resolve_harness_mcp_servers
    from vaultspec_a2a.providers._mcp_contract import verify_harness_mcp_contract

    servers = resolve_harness_mcp_servers(list(HARNESS_SERVERS))
    try:
        asyncio.run(verify_harness_mcp_contract(servers, env=dict(os.environ)))
    except Exception as exc:
        print(f"harness MCP tool contract failed: {exc}", file=sys.stderr, flush=True)
        return 1
    print(
        f"harness MCP tool contract satisfied for {', '.join(HARNESS_SERVERS)}",
        flush=True,
    )
    return 0


CHECKS = {"tool-contract": _tool_contract}


def main(argv: list[str] | None = None) -> int:
    """Dispatch one RAG wiring check and return its exit code.

    Args:
        argv: The argument vector, or ``None`` to read :data:`sys.argv`.

    Returns:
        The exit code of the selected check.
    """
    parser = argparse.ArgumentParser(
        prog="python -m dev.rag",
        description="Check this repository's RAG provider wiring.",
    )
    parser.add_argument("check", nargs="?", default="tool-contract", choices=[*CHECKS])
    args = parser.parse_args(argv)
    return CHECKS[args.check]()


if __name__ == "__main__":
    raise SystemExit(main())
