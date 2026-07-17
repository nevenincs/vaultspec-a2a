"""Protocol-layer proof that declared harness MCP servers reach session/new.

No mocks: a real ``AcpChatModel`` drives the real ACP protocol simulator, which
records the ``session/new`` params it receives. The assertion is protocol-layer
only - that the declared server is advertised in the session the spawned CLI is
handed. Model-VISIBLE surfacing of session-injected MCP servers is upstream-gated
in the pinned Claude CLI, so it is deliberately NOT asserted here.

Both delivery paths are exercised, because the researcher's model does NOT route
through ``create_worker_node`` - it is composed in the ``_make_research_producer``
branch - so the researcher is asserted specifically, not just a generic worker.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from langchain_core.messages import HumanMessage

from ....graph.compiler import _make_research_producer
from ...nodes.worker import create_worker_node

if TYPE_CHECKING:
    from vaultspec_a2a.thread.state import TeamState

SIMULATOR_PATH = Path(__file__).parent.parent / "acp_simulator.py"
PYTHON_EXE = sys.executable


def _recording_model(record_file: Path, tmp_path: Path):
    from vaultspec_a2a.providers.acp_chat_model import AcpChatModel

    return AcpChatModel(
        command=[
            PYTHON_EXE,
            str(SIMULATOR_PATH),
            "--response",
            "done",
            "--record-session-new",
            str(record_file),
        ],
        env_vars={},
        workspace_root=str(tmp_path),
    )


def _state() -> TeamState:
    return {
        "active_agent": "synthesist",
        "artifacts": [],
        "current_plan": [],
        "messages": [HumanMessage(content="do the work")],
        "next": "",
        "thread_id": "harness-mcp-thread",
        "token_usage": {},
    }


def _server_names(record_file: Path) -> list[str]:
    params = json.loads(record_file.read_text(encoding="utf-8"))
    return [s["name"] for s in params["mcpServers"]]


def _allowed_tools(record_file: Path) -> list[str]:
    params = json.loads(record_file.read_text(encoding="utf-8"))
    return (
        params.get("_meta", {})
        .get("claudeCode", {})
        .get("options", {})
        .get("allowedTools", [])
    )


@pytest.mark.asyncio
async def test_worker_node_advertises_declared_harness_server(tmp_path: Path) -> None:
    """A document worker turn advertises its declared harness MCP server."""
    record_file = tmp_path / "worker_session_new.json"
    node = create_worker_node(
        model=_recording_model(record_file, tmp_path),
        system_prompt="You are the synthesist.",
        name="synthesis",
        role="synthesist",
        harness_mcp_servers=["vaultspec-rag"],
    )

    result = await node(_state())
    assert result["messages"][0].content == "done"
    assert "vaultspec-rag" in _server_names(record_file)


@pytest.mark.asyncio
async def test_researcher_producer_advertises_declared_harness_server(
    tmp_path: Path,
) -> None:
    """The researcher path advertises the harness server too.

    The researcher's model is composed in ``_make_research_producer``, not
    ``create_worker_node``; a worker-only wiring would starve exactly the role
    the rag server exists for. This asserts the researcher branch specifically.
    """
    record_file = tmp_path / "researcher_session_new.json"
    producer = _make_research_producer(
        _recording_model(record_file, tmp_path),
        "You are the researcher.",
        harness_mcp_servers=["vaultspec-rag"],
    )

    finding = await producer(
        _state(), {"thread_id": "t1", "topic": "streams", "instructions": ""}
    )
    assert finding["source_thread"] == "t1"
    assert "vaultspec-rag" in _server_names(record_file)


@pytest.mark.asyncio
async def test_autonomous_worker_auto_permits_composed_rag_read_tools(
    tmp_path: Path,
) -> None:
    """A headless worker turn joins the composed rag read tools to allowedTools.

    Closes the attach(combined) gap end to end: with the harness server declared
    and the run headless, the session the CLI is handed auto-permits exactly the
    three read tool names, so a surfaced rag tool is not blocked by a prompt.
    """
    record_file = tmp_path / "autonomous_session_new.json"
    node = create_worker_node(
        model=_recording_model(record_file, tmp_path),
        system_prompt="You are the synthesist.",
        name="synthesis",
        role="synthesist",
        harness_mcp_servers=["vaultspec-rag"],
        autonomous=True,
    )

    await node(_state())
    allowed = _allowed_tools(record_file)
    assert "mcp__vaultspec-rag__search_vault" in allowed
    assert "mcp__vaultspec-rag__search_codebase" in allowed
    assert "mcp__vaultspec-rag__get_code_file" in allowed
    # The read-only boundary holds at the allowlist too: no write verb.
    assert not any("reindex" in t for t in allowed)


@pytest.mark.asyncio
async def test_supervised_worker_does_not_auto_permit_harness_tools(
    tmp_path: Path,
) -> None:
    """A supervised (non-headless) worker turn keeps the permission prompt.

    Auto-permission is headless-only: without ``autonomous`` the composed server
    is still advertised, but its tools are NOT joined to allowedTools, so the
    human permission gate stays in force.
    """
    record_file = tmp_path / "supervised_session_new.json"
    node = create_worker_node(
        model=_recording_model(record_file, tmp_path),
        system_prompt="You are the synthesist.",
        name="synthesis",
        role="synthesist",
        harness_mcp_servers=["vaultspec-rag"],
        autonomous=False,
    )

    await node(_state())
    assert "vaultspec-rag" in _server_names(record_file)
    assert not any("vaultspec-rag" in t for t in _allowed_tools(record_file))


@pytest.mark.asyncio
async def test_autonomous_researcher_producer_auto_permits_rag_read_tools(
    tmp_path: Path,
) -> None:
    """The researcher producer path auto-permits the composed rag read tools too.

    Wiring parity with the worker: the researcher is the primary target of the
    grounding feature, so its headless composition must join the same three read
    tool names to allowedTools - otherwise a surfaced rag tool would stall on a
    permission prompt exactly where the feature is meant to work.
    """
    record_file = tmp_path / "researcher_autonomous_session_new.json"
    producer = _make_research_producer(
        _recording_model(record_file, tmp_path),
        "You are the researcher.",
        harness_mcp_servers=["vaultspec-rag"],
        autonomous=True,
    )

    await producer(_state(), {"thread_id": "t1", "topic": "x", "instructions": ""})
    allowed = _allowed_tools(record_file)
    assert "mcp__vaultspec-rag__search_vault" in allowed
    assert "mcp__vaultspec-rag__search_codebase" in allowed
    assert "mcp__vaultspec-rag__get_code_file" in allowed
    assert not any("reindex" in t for t in allowed)


@pytest.mark.asyncio
async def test_supervised_researcher_producer_does_not_auto_permit(
    tmp_path: Path,
) -> None:
    """Without autonomous, the researcher producer keeps the permission prompt."""
    record_file = tmp_path / "researcher_supervised_session_new.json"
    producer = _make_research_producer(
        _recording_model(record_file, tmp_path),
        "You are the researcher.",
        harness_mcp_servers=["vaultspec-rag"],
        autonomous=False,
    )

    await producer(_state(), {"thread_id": "t1", "topic": "x", "instructions": ""})
    assert "vaultspec-rag" in _server_names(record_file)
    assert not any("vaultspec-rag" in t for t in _allowed_tools(record_file))


@pytest.mark.asyncio
async def test_no_harness_declaration_advertises_no_extra_server(
    tmp_path: Path,
) -> None:
    """Without a harness declaration the session carries no injected server."""
    record_file = tmp_path / "bare_session_new.json"
    node = create_worker_node(
        model=_recording_model(record_file, tmp_path),
        system_prompt="You are the synthesist.",
        name="synthesis",
        role="synthesist",
        harness_mcp_servers=None,
    )

    await node(_state())
    assert _server_names(record_file) == []
