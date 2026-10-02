"""Deterministic tests for the Kimi read-only permission-RPC enforcement.

Real objects, no mocks: the frozen ``AcpModelConfig``, the real
``on_request_permission`` handler, and real directories on disk for the project
a run is bound to and the host paths outside it. The autonomous/normal-callback
paths do not touch the session context, so the module's real idle-child fixture
serves for it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from .._acp_rpc_handlers import _autonomous_option_id, on_request_permission
from .._acp_types import AcpModelConfig, AcpSessionContext, PermissionCallback
from .._json_contract import JsonObject, JsonValue

if TYPE_CHECKING:
    from pathlib import Path

_RAG_READS: list[str] = [
    "mcp__vaultspec-rag__search_vault",
    "mcp__vaultspec-rag__search_codebase",
    "mcp__vaultspec-rag__get_code_file",
]
_OPTIONS: list[JsonObject] = [
    {"optionId": "approve", "kind": "allow_once"},
    {"optionId": "approve_for_session", "kind": "allow_always"},
    {"optionId": "reject", "kind": "reject_once"},
]

# The lane's own read built-ins, in the spelling a kimi permission title carries.
_FLOOR_TOOLS: list[str] = ["ReadFile", "Grep", "Glob"]


def _config(
    *,
    acp_family: str,
    workspace_root: str | None = None,
    permission_callback: PermissionCallback | None = None,
) -> AcpModelConfig:
    return AcpModelConfig(
        agent_config=None,
        permission_callback=permission_callback,
        workspace_root=workspace_root,
        command=["kimi", "acp"],
        env_vars={},
        mcp_servers=[],
        use_exec=False,
        provider="kimi",
        runtime_authority=None,
        acp_backend="kimi_cli",
        command_origin=None,
        command_kind=None,
        command_executable=None,
        command_target=None,
        auth_mode=None,
        allowed_tools=list(_RAG_READS),
        acp_family=acp_family,
    )


async def _decide(
    name: str,
    config: AcpModelConfig,
    ctx: AcpSessionContext,
    raw_input: JsonObject | None = None,
) -> str:
    tool_call: JsonObject = {"title": name, "rawInput": raw_input or {}}
    params: JsonObject = {
        "toolCall": tool_call,
        "options": list[JsonValue](_OPTIONS),
    }
    response = await on_request_permission(1, params, ctx, config)
    result = response.get("result")
    assert isinstance(result, dict)
    outcome = result.get("outcome")
    assert isinstance(outcome, dict)
    option_id = outcome.get("optionId")
    assert isinstance(option_id, str)
    return option_id


@pytest.mark.parametrize(
    "title",
    [
        "search_vault: acp",
        "search_codebase",
        "get_code_file",
    ],
)
def test_autonomous_kimi_auto_approves_its_declared_reads(title: str) -> None:
    cfg = _config(acp_family="kimi")
    assert (
        _autonomous_option_id(title, cfg, _OPTIONS, args={}, locations=[]) == "approve"
    )


@pytest.mark.parametrize(
    "title",
    [
        "WriteFile: y",
        "StrReplaceFile",
        "bash: rm -rf /",
        "ReadMediaFile: img.png",
        "SearchWeb: secrets",
        "FetchURL: http://x",
        "Agent: subtask",
        "EnterPlanMode",
        "SendDMail",
        "TotallyUnknownTool",
    ],
)
def test_autonomous_kimi_rejects_everything_else(title: str) -> None:
    cfg = _config(acp_family="kimi")
    assert (
        _autonomous_option_id(title, cfg, _OPTIONS, args={}, locations=[]) == "reject"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", _FLOOR_TOOLS)
async def test_a_floor_read_inside_the_bound_project_is_approved(
    acp_session_context: AcpSessionContext, tmp_path: Path, tool: str
) -> None:
    """Grounding survives: the lane's read built-ins still read the run's project."""
    cfg = _config(acp_family="kimi", workspace_root=str(tmp_path))

    assert (
        await _decide(
            f"{tool}: src/a.py", cfg, acp_session_context, {"path": "src/a.py"}
        )
        == "approve"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", _FLOOR_TOOLS)
async def test_a_floor_read_of_a_host_path_is_refused(
    acp_session_context: AcpSessionContext, tmp_path: Path, tool: str
) -> None:
    """The name is not the grant: a floor tool pointed off the project is refused.

    This is the whole reach of a bare floor name - a content search over an
    absolute host path is every file the operator can read - and the title
    reduces to exactly the allowlisted name, so nothing but the argument
    distinguishes it from the approved call above.
    """
    bound = tmp_path / "bound-project"
    outside = tmp_path / "other-project"
    bound.mkdir()
    outside.mkdir()
    cfg = _config(acp_family="kimi", workspace_root=str(bound))

    assert (
        await _decide(
            f"{tool}: {outside}",
            cfg,
            acp_session_context,
            {"path": str(outside / "secrets.env")},
        )
        == "reject"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", _FLOOR_TOOLS)
async def test_a_floor_read_that_steps_out_of_the_project_is_refused(
    acp_session_context: AcpSessionContext, tmp_path: Path, tool: str
) -> None:
    """A relative argument is measured where the call runs, so ``..`` is refused."""
    bound = tmp_path / "bound-project"
    bound.mkdir()
    cfg = _config(acp_family="kimi", workspace_root=str(bound))

    assert (
        await _decide(
            f"{tool}: ../other-project",
            cfg,
            acp_session_context,
            {"path": "../other-project/secrets.env"},
        )
        == "reject"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", _FLOOR_TOOLS)
async def test_a_floor_read_naming_no_path_at_all_is_refused(
    acp_session_context: AcpSessionContext, tmp_path: Path, tool: str
) -> None:
    """Saying nothing about where a read lands is not saying it lands inside."""
    cfg = _config(acp_family="kimi", workspace_root=str(tmp_path))

    assert await _decide(f"{tool}: everything", cfg, acp_session_context, {}) == (
        "reject"
    )


@pytest.mark.asyncio
async def test_a_floor_read_is_judged_by_the_adapter_locations_too(
    acp_session_context: AcpSessionContext, tmp_path: Path
) -> None:
    """The files the adapter says the call touches are read beside the raw input.

    The two halves of the payload are filled in differently by different
    backends, so a decision taken from one of them alone is decided by which
    backend served the run.
    """
    bound = tmp_path / "bound-project"
    outside = tmp_path / "other-project"
    bound.mkdir()
    outside.mkdir()
    cfg = _config(acp_family="kimi", workspace_root=str(bound))
    tool_call: JsonObject = {
        "title": "Grep",
        "rawInput": {"pattern": "credential"},
        "locations": [{"path": str(outside / "secrets.env")}],
    }
    params: JsonObject = {
        "toolCall": tool_call,
        "options": list[JsonValue](_OPTIONS),
    }

    response = await on_request_permission(1, params, acp_session_context, cfg)

    assert response["result"] == {
        "outcome": {"optionId": "reject", "outcome": "selected"}
    }


@pytest.mark.asyncio
async def test_handler_autonomous_kimi_approves_read_rejects_write(
    acp_session_context: AcpSessionContext, tmp_path: Path
) -> None:
    cfg = _config(acp_family="kimi", workspace_root=str(tmp_path))
    read_input: JsonObject = {"path": "src/a.py"}
    assert (
        await _decide("ReadFile: src/a.py", cfg, acp_session_context, read_input)
        == "approve"
    )
    assert (
        await _decide("WriteFile: src/a.py", cfg, acp_session_context, read_input)
        == "reject"
    )


@pytest.mark.asyncio
async def test_handler_supervised_kimi_uses_callback_not_auto_approve(
    acp_session_context: AcpSessionContext, tmp_path: Path
) -> None:
    """A supervised Kimi run (permission_callback present) keeps its prompt: the
    callback decides, the auto-approve set is NOT consulted."""
    calls: list[str] = []

    async def callback(name: str, _args: JsonObject, _options: list[JsonObject]) -> str:
        calls.append(name)
        return "reject"  # a human would reject this read

    cfg = _config(
        acp_family="kimi",
        workspace_root=str(tmp_path),
        permission_callback=callback,
    )
    # ReadFile is in the auto-approve set, but the callback rejects it — proving
    # supervised mode does not fall through to the autonomous auto-approve branch.
    option = await _decide(
        "ReadFile: src/a.py", cfg, acp_session_context, {"path": "src/a.py"}
    )
    assert option == "reject"
    assert calls == ["ReadFile: src/a.py"]
