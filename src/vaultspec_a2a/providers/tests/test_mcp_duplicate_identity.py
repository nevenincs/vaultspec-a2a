"""A repeated MCP identity must be refused, not silently resolved.

Composition is keyed by name, so a duplicate does not conflict - it overwrites,
and the last spec wins without a word. The harness invariant is that the spawned
agent's MCP surface is exactly the declared set, and a name that can be
redeclared with a different command breaks it: the surviving entry is no longer
the one that was reviewed.

These drive the real declared-surface guard at the session seam and the real
Codex spec emitter, so a refusal is proven at the boundaries that actually emit
configuration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ...thread.errors import ConfigError
from .._acp_authoring import AUTHORING_MCP_SERVER_NAME
from .._acp_mcp import (
    codex_mcp_server_specs,
    reject_duplicate_identities,
    require_declared_surface,
)

if TYPE_CHECKING:
    from .._json_contract import JsonObject

_KNOWN = "vaultspec-rag"


def _spec(command: str) -> JsonObject:
    return {"name": _KNOWN, "command": command, "args": ["serve"]}


def test_a_single_identity_passes_the_declared_surface_guard() -> None:
    """The ordinary case is unaffected by the guard."""
    require_declared_surface([_spec("only")], bridge_name=AUTHORING_MCP_SERVER_NAME)


def test_a_repeated_identity_is_refused_rather_than_overwritten() -> None:
    """Without the guard the second spec silently wins and the first vanishes."""
    with pytest.raises(ConfigError, match="duplicate MCP server identities"):
        require_declared_surface(
            [_spec("first"), _spec("second")],
            bridge_name=AUTHORING_MCP_SERVER_NAME,
        )


def test_the_refusal_names_every_duplicated_identity() -> None:
    """Naming only the first would leave the operator fixing them one run at a time."""
    servers: list[JsonObject] = [
        {"name": "alpha", "command": "a"},
        {"name": "alpha", "command": "a2"},
        {"name": "beta", "command": "b"},
        {"name": "beta", "command": "b2"},
    ]

    with pytest.raises(ConfigError) as raised:
        reject_duplicate_identities(servers)

    message = str(raised.value)
    assert "alpha" in message
    assert "beta" in message


def test_unknown_and_unnamed_specs_do_not_trigger_a_false_refusal() -> None:
    """Only a genuinely repeated name is a duplicate."""
    reject_duplicate_identities(
        [
            {"name": "alpha", "command": "a"},
            {"name": "beta", "command": "b"},
            {"command": "no-name"},
            {"name": "", "command": "blank"},
            {"name": "", "command": "blank-again"},
        ]
    )


def test_the_codex_transport_also_refuses_a_repeated_name() -> None:
    """Both emitters share one registry, so both must share the refusal.

    Guarding only the ACP path left the second transport emitting two blocks
    under one configuration key - either a parse failure or a last-wins
    overwrite, which is the shadowing the specs path already refused.
    """
    with pytest.raises(ConfigError, match="duplicate MCP server names"):
        codex_mcp_server_specs([_KNOWN, _KNOWN])


def test_the_codex_transport_still_resolves_a_single_name() -> None:
    """The guard must not disturb the ordinary path."""
    specs = codex_mcp_server_specs([_KNOWN])

    assert [spec["name"] for spec in specs] == [_KNOWN]


def test_both_transports_refuse_the_same_condition() -> None:
    """One registry, one trust root, one answer to a repeated identity."""
    with pytest.raises(ConfigError):
        require_declared_surface(
            [_spec("a"), _spec("b")], bridge_name=AUTHORING_MCP_SERVER_NAME
        )
    with pytest.raises(ConfigError):
        codex_mcp_server_specs([_KNOWN, _KNOWN])
