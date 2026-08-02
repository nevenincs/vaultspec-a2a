"""Contract verification of the declared harness MCP tool surface.

Real objects only, no mocks: every probe below completes a genuine MCP
``initialize`` + ``tools/list`` handshake against the production launch spec that
a run would actually advertise. The negative cases perturb the DECLARATION (the
side under this project's control), never the server, so a failing contract is
exercised against the same real server the passing one uses.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from ...thread.errors import ConfigError, HarnessToolContractError
from .._acp_mcp import (
    declared_harness_tools,
    is_known_harness_server,
    resolve_harness_mcp_servers,
)
from .._mcp_contract import (
    verify_declared_tool_contract,
    verify_harness_mcp_contract,
)

if TYPE_CHECKING:
    from .._json_contract import JsonObject


def _rag_spec() -> JsonObject:
    return resolve_harness_mcp_servers(["vaultspec-rag"])[0]


def test_declared_tools_are_the_registry_read_surface() -> None:
    assert declared_harness_tools("vaultspec-rag") == (
        "search_vault",
        "search_codebase",
        "get_code_file",
    )


def test_declared_tools_unknown_name_raises_naming_the_known_set() -> None:
    with pytest.raises(ConfigError) as excinfo:
        declared_harness_tools("does-not-exist")
    message = str(excinfo.value)
    assert "does-not-exist" in message
    assert "vaultspec-rag" in message


def test_known_server_predicate_separates_registry_from_bridge() -> None:
    # The authoring bridge rides the same advertised list but carries no static
    # tool declaration, so the verifier must be able to tell them apart.
    assert is_known_harness_server("vaultspec-rag")
    assert not is_known_harness_server("vaultspec-authoring")


@pytest.mark.asyncio
async def test_production_launch_spec_serves_every_declared_tool() -> None:
    """The live contract: the unpinned spec serves exactly what the run declares.

    This is the assertion the removed version pin was a proxy for. It resolves the
    real registry spec, launches it, and confirms the server advertises every
    declared tool - so an incompatible release fails HERE, loudly, instead of
    leaving an agent advertising grounding tools it can never call.
    """
    spec = _rag_spec()
    command = spec["command"]
    raw_args = spec["args"]
    assert isinstance(command, str)
    assert isinstance(raw_args, list)
    args: list[str] = []
    for arg in raw_args:
        assert isinstance(arg, str)
        args.append(arg)
    await verify_declared_tool_contract(
        name="vaultspec-rag",
        command=command,
        args=args,
        declared=declared_harness_tools("vaultspec-rag"),
        env=dict(os.environ),
    )


@pytest.mark.asyncio
async def test_session_shaped_verification_skips_the_authoring_bridge() -> None:
    """Only registry-owned servers are probed; the bridge is left to its own seam.

    Mirrors the real ACP session list, which carries the per-run authoring bridge
    beside the harness servers. The bridge entry names a command that does not
    exist, so were it probed the call would raise - passing proves it is skipped.
    """
    session: list[JsonObject] = [
        {
            "name": "vaultspec-authoring",
            "command": "no-such-authoring-bridge-executable",
            "args": [],
        },
        _rag_spec(),
    ]
    await verify_harness_mcp_contract(session, env=dict(os.environ))


@pytest.mark.asyncio
async def test_missing_declared_tool_is_refused_and_named() -> None:
    """A declared tool the real server does not serve fails loud and is named.

    The server is the real one; the DECLARATION is perturbed, which is the honest
    direction - drift happens when this project keeps declaring a tool a released
    server has renamed or dropped.
    """
    spec = _rag_spec()
    command = spec["command"]
    raw_args = spec["args"]
    assert isinstance(command, str)
    assert isinstance(raw_args, list)
    args: list[str] = []
    for arg in raw_args:
        assert isinstance(arg, str)
        args.append(arg)
    with pytest.raises(HarnessToolContractError) as excinfo:
        await verify_declared_tool_contract(
            name="vaultspec-rag",
            command=command,
            args=args,
            declared=("search_vault", "tool_that_no_release_serves"),
            env=dict(os.environ),
        )
    message = str(excinfo.value)
    # Actionable: names the server, the missing tool, and what was served instead.
    assert "vaultspec-rag" in message
    assert "tool_that_no_release_serves" in message
    assert "search_vault" in message
    # A tool the server DOES serve is never reported missing.
    assert "does not serve its declared tool(s): tool_that_no_release_serves" in message


@pytest.mark.asyncio
async def test_unlaunchable_server_is_refused_rather_than_assumed_good() -> None:
    """An unverifiable contract is an unmet one, not a silent pass."""
    with pytest.raises(HarnessToolContractError) as excinfo:
        await verify_declared_tool_contract(
            name="vaultspec-rag",
            command="no-such-mcp-server-executable",
            args=["--serve"],
            declared=("search_vault",),
            env=dict(os.environ),
            timeout=30.0,
        )
    message = str(excinfo.value)
    assert "no-such-mcp-server-executable" in message
    assert "could not be verified" in message


@pytest.mark.asyncio
async def test_probe_deadline_is_refused_rather_than_hanging_the_run() -> None:
    """A server that never completes the handshake fails on the deadline."""
    spec = _rag_spec()
    command = spec["command"]
    assert isinstance(command, str)
    with pytest.raises(HarnessToolContractError) as excinfo:
        await verify_declared_tool_contract(
            name="vaultspec-rag",
            command=command,
            args=["--from", "vaultspec-rag[mcp]", "vaultspec-search-mcp"],
            declared=("search_vault",),
            env=dict(os.environ),
            timeout=0.01,
        )
    assert "could not be verified" in str(excinfo.value)


@pytest.mark.asyncio
async def test_spec_without_a_command_is_refused() -> None:
    with pytest.raises(HarnessToolContractError) as excinfo:
        await verify_harness_mcp_contract([{"name": "vaultspec-rag", "args": []}])
    assert "no launch command" in str(excinfo.value)
