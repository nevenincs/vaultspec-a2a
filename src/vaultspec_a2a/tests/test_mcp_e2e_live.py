"""Live Postgres verification for MCP stdio end-to-end tool execution."""

import re
import sys

import pytest
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from .conftest import _stop_process
from .test_permission_durability_live import (
    _prepare_workspace,
    _select_certifying_provider,
    _start_manual_stack,
)

pytestmark = pytest.mark.live

_THREAD_ID_RE = re.compile(r"Thread started:\s+([0-9a-fA-F]{32}|[0-9a-fA-F-]{36})")


def _tool_text(result) -> str:
    texts: list[str] = []
    for block in result.content:
        text = getattr(block, "text", None)
        if text:
            texts.append(text)
    return "\n".join(texts)


def _extract_thread_id(tool_text: str) -> str:
    match = _THREAD_ID_RE.search(tool_text)
    if match is None:
        raise AssertionError(
            f"Could not extract thread ID from MCP output: {tool_text!r}"
        )
    return match.group(1)


@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.timeout(480)
async def test_mcp_stdio_tools_hit_live_gateway_and_create_real_thread(
    postgres_sqlalchemy_url,
    postgres_checkpoint_url,
    tmp_path,
):
    provider = _select_certifying_provider()
    feature_tag = "mcp-e2e-live"
    workspace_root = _prepare_workspace(tmp_path, feature_tag, provider)
    gateway = None
    worker = None

    try:
        gateway, worker, gateway_url, env = await _start_manual_stack(
            postgres_sqlalchemy_url=postgres_sqlalchemy_url,
            postgres_checkpoint_url=postgres_checkpoint_url,
        )

        server_params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "vaultspec_a2a.protocols.mcp"],
            env={
                **env,
                "VAULTSPEC_MCP_API_BASE_URL": gateway_url,
            },
            cwd=tmp_path,
        )
        errlog_path = tmp_path / "mcp-stderr.log"

        with errlog_path.open("w", encoding="utf-8") as errlog:
            async with (
                stdio_client(server_params, errlog=errlog) as streams,
                ClientSession(*streams) as session,
            ):
                await session.initialize()

                tools = await session.list_tools()
                tool_names = {tool.name for tool in tools.tools}
                assert "start_thread" in tool_names
                assert "get_team_status" in tool_names
                assert "list_team_presets" in tool_names

                presets_result = await session.call_tool("list_team_presets")
                presets_text = _tool_text(presets_result)
                assert presets_result.isError is False
                assert "vaultspec-adaptive-coder" in presets_text

                team_status_before = await session.call_tool("get_team_status")
                team_status_before_text = _tool_text(team_status_before)
                assert team_status_before.isError is False
                assert "Team Status" in team_status_before_text

                start_result = await session.call_tool(
                    "start_thread",
                    {
                        "initial_message": (
                            "Implement a backend improvement and report progress."
                        ),
                        "team_preset": "vaultspec-adaptive-coder",
                        "autonomous": True,
                        "workspace_root": str(workspace_root),
                    },
                )
                start_text = _tool_text(start_result)
                assert start_result.isError is False
                thread_id = _extract_thread_id(start_text)
                assert f"{gateway_url}/api/threads/{thread_id}/state" in start_text

                thread_status = await session.call_tool(
                    "get_thread_status",
                    {"thread_id": thread_id},
                )
                thread_status_text = _tool_text(thread_status)
                assert thread_status.isError is False
                assert thread_id in thread_status_text
                assert any(
                    state in thread_status_text
                    for state in (
                        "submitted",
                        "running",
                        "input_required",
                        "completed",
                        "failed",
                        "cancelled",
                    )
                )

                threads_result = await session.call_tool("list_threads", {"limit": 20})
                threads_text = _tool_text(threads_result)
                assert threads_result.isError is False
                assert thread_id in threads_text
    finally:
        if gateway is not None:
            await _stop_process(gateway)
        if worker is not None:
            await _stop_process(worker)
