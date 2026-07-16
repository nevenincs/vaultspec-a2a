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
