"""Deterministic tests for the Kimi read-only permission-RPC enforcement (P03.S11).

Real objects, no mocks: the frozen ``_AcpModelConfig`` and the real
``on_request_permission`` handler. The autonomous/normal-callback paths do not
touch the session context, so a lightweight stand-in is passed for it.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from .._acp_rpc_handlers import _kimi_autonomous_option_id, on_request_permission
from .._acp_types import _AcpModelConfig, _AcpSessionContext

_RAG_READS = [
    "mcp__vaultspec-rag__search_vault",
    "mcp__vaultspec-rag__search_codebase",
    "mcp__vaultspec-rag__get_code_file",
]
_OPTIONS = [
    {"optionId": "approve", "kind": "allow_once"},
    {"optionId": "approve_for_session", "kind": "allow_always"},
    {"optionId": "reject", "kind": "reject_once"},
]


def _config(*, acp_family: str, permission_callback=None) -> _AcpModelConfig:
    return _AcpModelConfig(
        agent_config=None,
        permission_callback=permission_callback,
        workspace_root=None,
        cwd=None,
        command=["kimi", "acp"],
        env_vars={},
        session_id=None,
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


def _ctx() -> _AcpSessionContext:
    # The autonomous and normal-callback-return paths never touch the context.
    return cast("_AcpSessionContext", SimpleNamespace())


async def _decide(name: str, config: _AcpModelConfig) -> str:
    params = {"toolCall": {"title": name, "rawInput": {}}, "options": _OPTIONS}
    raw = await on_request_permission(1, params, _ctx(), config)
    resp = cast("dict[str, Any]", raw)
    return resp["result"]["outcome"]["optionId"]


@pytest.mark.parametrize(
    "title",
    [
        "ReadFile: src/x.py",
        "Grep",
        "Glob",
        "ReadMediaFile: img.png",
        "search_vault: acp",
        "search_codebase",
        "get_code_file",
    ],
)
def test_autonomous_kimi_auto_approves_exact_read_tools(title: str) -> None:
    cfg = _config(acp_family="kimi")
    assert _kimi_autonomous_option_id(title, cfg, _OPTIONS) == "approve"


@pytest.mark.parametrize(
    "title",
    [
        "WriteFile: y",
        "StrReplaceFile",
        "bash: rm -rf /",
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
    assert _kimi_autonomous_option_id(title, cfg, _OPTIONS) == "reject"


@pytest.mark.asyncio
async def test_handler_autonomous_kimi_approves_read_rejects_write() -> None:
    cfg = _config(acp_family="kimi")
    assert await _decide("ReadFile: src/a.py", cfg) == "approve"
    assert await _decide("WriteFile: src/a.py", cfg) == "reject"


@pytest.mark.asyncio
async def test_handler_supervised_kimi_uses_callback_not_auto_approve() -> None:
    """A supervised Kimi run (permission_callback present) keeps its prompt: the
    callback decides, the auto-approve set is NOT consulted."""
    calls: list[str] = []

    async def callback(name, args, options):
        calls.append(name)
        return "reject"  # a human would reject this read

    cfg = _config(acp_family="kimi", permission_callback=callback)
    # ReadFile is in the auto-approve set, but the callback rejects it — proving
    # supervised mode does not fall through to the autonomous auto-approve branch.
    option = await _decide("ReadFile: src/a.py", cfg)
    assert option == "reject"
    assert calls == ["ReadFile: src/a.py"]
