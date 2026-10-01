"""A harness tool the registry withholds is served but never callable.

The core server's restricted launch serves two open-world tools that send vault
text to a hosted API whenever the host has a key for it, and the launch has no
flag to drop them. The registry declares them withheld: the contract check
expects the server to serve them and nothing more, and every lane refuses a call
to one before an allowlist or a human is consulted.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from ...thread.errors import ConfigError, HarnessToolContractError
from .._codex_permission import (
    DECLINE_ACTION,
    MCP_TOOL_CALL_APPROVAL_KIND,
    CodexPermissionRung,
)
from .._harness_mcp_registry import (
    _declare_registry,
    _launch_spec,
    _registry_entry,
    declared_harness_tools,
    harness_tool_is_withheld,
    withheld_harness_tools,
)
from .._mcp_contract import verify_declared_tool_contract
from .test_project_confinement import _config, _decide

if TYPE_CHECKING:
    from .._acp_types import AcpSessionContext, PermissionCallback
    from .._json_contract import JsonObject, JsonValue

_CORE = "vaultspec-core"
_REPO_ROOT = Path(__file__).resolve().parents[4]


def _entry(**overrides: JsonValue) -> JsonObject:
    entry: JsonObject = {
        "name": "candidate",
        "command": "uvx",
        "args": ["--from", "candidate", "candidate-mcp"],
        "tools": ["read"],
        "read_only": True,
        "network_egress": False,
        "root_pin": "CANDIDATE_ROOT",
        "per_call_project": False,
        "exact_surface": True,
    }
    entry.update(overrides)
    return entry


def test_withheld_tools_are_a_list_of_names() -> None:
    with pytest.raises(ConfigError, match="withheld_tools"):
        _declare_registry({"candidate": _entry(withheld_tools="search")})


def test_a_tool_is_either_permitted_or_withheld() -> None:
    with pytest.raises(ConfigError, match="both permits and withholds"):
        _declare_registry({"candidate": _entry(withheld_tools=["read"])})


def test_the_core_server_withholds_its_hosted_search_tools() -> None:
    assert withheld_harness_tools(_CORE) == ("search", "crossref")
    assert not {"search", "crossref"} & set(declared_harness_tools(_CORE))
    assert harness_tool_is_withheld("mcp__vaultspec-core__search")
    assert harness_tool_is_withheld("mcp__vaultspec-core__crossref")
    assert not harness_tool_is_withheld("mcp__vaultspec-core__find")
    assert not harness_tool_is_withheld("mcp__vaultspec-rag__search_vault")
    # A lane whose titles drop the server prefix still cannot reach one.
    assert harness_tool_is_withheld("search")


def _core_launch() -> tuple[str, list[str]]:
    spec = _launch_spec(_CORE, _registry_entry(_CORE))
    command = spec["command"]
    raw_args = spec["args"]
    assert isinstance(command, str)
    assert isinstance(raw_args, list)
    return command, [str(arg) for arg in raw_args]


def _core_env() -> dict[str, str]:
    # The server refuses to start on a target it cannot find, and a run always
    # pins one, so the probe does too.
    return {**os.environ, "VAULTSPEC_TARGET_DIR": str(_REPO_ROOT)}


@pytest.mark.asyncio
async def test_the_real_core_launch_serves_the_withheld_tools_and_nothing_else() -> (
    None
):
    command, args = _core_launch()

    await verify_declared_tool_contract(
        name=_CORE,
        command=command,
        args=args,
        declared=declared_harness_tools(_CORE),
        exact_surface=True,
        withheld=withheld_harness_tools(_CORE),
        env=_core_env(),
    )


@pytest.mark.asyncio
async def test_a_served_tool_the_registry_does_not_withhold_is_still_refused() -> None:
    command, args = _core_launch()

    with pytest.raises(HarnessToolContractError) as excinfo:
        await verify_declared_tool_contract(
            name=_CORE,
            command=command,
            args=args,
            declared=declared_harness_tools(_CORE),
            exact_surface=True,
            withheld=("search",),
            env=_core_env(),
        )

    assert "crossref" in str(excinfo.value)


@pytest.mark.asyncio
async def test_a_supervised_acp_run_never_asks_a_human_about_a_withheld_tool(
    tmp_path: Path, acp_session_context: AcpSessionContext
) -> None:
    asked: list[str] = []

    async def human(tool: str, args: JsonObject, options: list[JsonObject]) -> str:
        del args, options
        asked.append(tool)
        return "allow"

    callback: PermissionCallback = human
    config = _config(workspace_root=str(tmp_path), permission_callback=callback)

    decision = await _decide(
        "mcp__vaultspec-core__search", {"query": "x"}, config, acp_session_context
    )

    assert decision == "reject"
    assert asked == []


@pytest.mark.asyncio
async def test_codex_declines_a_withheld_tool_even_when_allowlisted() -> None:
    asked: list[str] = []

    async def human(tool: str, args: JsonObject, options: list[JsonObject]) -> str:
        del args, options
        asked.append(tool)
        return "accept"

    rung = CodexPermissionRung(
        allowed_tools=frozenset({(_CORE, "search")}),
        permission_callback=human,
    )
    rung.observe(
        "item/started",
        {
            "threadId": "t",
            "turnId": "u",
            "item": {
                "type": "mcpToolCall",
                "server": _CORE,
                "tool": "search",
                "arguments": {"query": "x"},
            },
        },
    )

    decision = await rung.decide(
        {
            "threadId": "t",
            "turnId": "u",
            "serverName": _CORE,
            "_meta": {"codex_approval_kind": MCP_TOOL_CALL_APPROVAL_KIND},
        }
    )

    assert decision == DECLINE_ACTION
    assert asked == []
