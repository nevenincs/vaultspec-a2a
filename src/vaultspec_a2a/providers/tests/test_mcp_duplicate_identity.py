"""A repeated MCP identity must be refused, not silently resolved.

Composition is keyed by name, so a duplicate does not conflict - it overwrites,
and the last spec wins without a word. The harness invariant is that the spawned
agent's MCP surface is exactly the declared set, and a name that can be
redeclared with a different command breaks it: the surviving entry is no longer
the one that was reviewed.

These drive the real composition functions and the real config-home writer, so a
refusal is proven at the boundary that actually emits configuration.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from ...thread.errors import ConfigError
from .._acp_config_home import create_isolated_config_home
from .._acp_mcp import config_home_mcp_servers, reject_duplicate_identities

if TYPE_CHECKING:
    from pathlib import Path

_KNOWN = "vaultspec-rag"


def _spec(command: str) -> dict[str, Any]:
    return {"name": _KNOWN, "command": command, "args": ["serve"]}


def test_a_single_identity_composes() -> None:
    """The ordinary case is unaffected by the guard."""
    composed = config_home_mcp_servers([_spec("only")])

    assert composed[_KNOWN]["command"] == "only"


def test_a_repeated_identity_is_refused_rather_than_overwritten() -> None:
    """Without the guard the second spec silently wins and the first vanishes."""
    with pytest.raises(ConfigError, match="duplicate MCP server identities"):
        config_home_mcp_servers([_spec("first"), _spec("second")])


def test_the_refusal_names_every_duplicated_identity() -> None:
    """Naming only the first would leave the operator fixing them one run at a time."""
    servers = [
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


def test_the_written_config_home_carries_the_reviewed_command(
    tmp_path: Path,
) -> None:
    """Proven through the real writer: what lands on disk is the declared entry."""
    home = create_isolated_config_home(
        config_home_mcp_servers([_spec("reviewed-command")]),
        workspace_root=tmp_path,
    )

    written = json.loads((home / ".claude.json").read_text(encoding="utf-8"))

    assert written["mcpServers"][_KNOWN]["command"] == "reviewed-command"


def test_a_duplicate_never_reaches_the_config_home_writer(tmp_path: Path) -> None:
    """The refusal happens before anything is written, so no home is left behind."""
    before = sorted(tmp_path.iterdir())

    with pytest.raises(ConfigError):
        create_isolated_config_home(
            config_home_mcp_servers([_spec("first"), _spec("second")]),
            workspace_root=tmp_path,
        )

    assert sorted(tmp_path.iterdir()) == before
