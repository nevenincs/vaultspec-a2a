"""Graph execution tests using Provider.MOCK against a live VidaiMock instance.

Requires ``requires_vidaimock`` marker: VidaiMock must be running at
``MOCK_API_BASE`` (default ``http://localhost:8100``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

from vaultspec_a2a.team.team_config import load_agent_config, load_team_config

from ..compiler import compile_team_graph

pytestmark = pytest.mark.requires_vidaimock


@pytest_asyncio.fixture
async def checkpointer() -> AsyncGenerator[AsyncSqliteSaver]:
    """In-memory SQLite checkpointer -- isolated per test."""
    async with AsyncSqliteSaver.from_conn_string(":memory:") as saver:
        await saver.setup()
        yield saver


def _make_config(thread_id: str) -> RunnableConfig:
    return RunnableConfig(configurable={"thread_id": thread_id})


def _ai_messages(states: list[dict]) -> list[AIMessage]:
    """Collect all AIMessages from a list of streamed state snapshots."""
    seen: set[int] = set()
    result: list[AIMessage] = []
    for state in states:
        for msg in state.get("messages", []):
            if isinstance(msg, AIMessage) and id(msg) not in seen:
                seen.add(id(msg))
                result.append(msg)
    return result


@pytest.mark.asyncio
async def test_mock_single_agent_pipeline_runs_to_completion(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """mock-success-single executes two LLM turns and finishes."""
    team = load_team_config("mock-success-single")
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}

    graph = compile_team_graph(
        team_config=team,
        agent_configs=agent_configs,
        checkpointer=checkpointer,
        autonomous=True,
    )

    inputs = {"messages": [HumanMessage(content="Execute the mock protocol.")]}
    config = _make_config("test-mock-single")

    states: list[dict] = []
    async for state in graph.astream(inputs, config, stream_mode="values"):
        states.append(state)

    assert states, "astream yielded no states"

    ai_msgs = _ai_messages(states)
    assert len(ai_msgs) >= 2

    first = ai_msgs[0]
    assert first.tool_calls
    tool_names = [tc["name"] for tc in first.tool_calls]
    assert "run_command" in tool_names

    last = ai_msgs[-1]
    assert not last.tool_calls
    last_text = last.content if isinstance(last.content, str) else str(last.content)
    assert last_text.strip()

    saved = await checkpointer.aget(config)
    assert saved is not None
    assert "messages" in saved["channel_values"]


@pytest.mark.asyncio
async def test_mock_tool_failure_pipeline_surfaces_failure_summary(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """mock-failure-tool executes a failing command then reports it."""
    team = load_team_config("mock-failure-tool")
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}

    graph = compile_team_graph(
        team_config=team,
        agent_configs=agent_configs,
        checkpointer=checkpointer,
        autonomous=True,
    )

    inputs = {"messages": [HumanMessage(content="Execute the mock failure protocol.")]}
    config = _make_config("test-mock-failure")

    states: list[dict] = []
    async for state in graph.astream(inputs, config, stream_mode="values"):
        states.append(state)

    assert states

    ai_msgs = _ai_messages(states)
    assert len(ai_msgs) >= 2

    first = ai_msgs[0]
    assert first.tool_calls

    last = ai_msgs[-1]
    assert not last.tool_calls


@pytest.mark.asyncio
async def test_mock_human_in_loop_pauses_on_permission_request(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """mock-human-in-loop tape pauses on permission request."""
    from langgraph.errors import GraphInterrupt

    team = load_team_config("mock-human-in-loop")
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}

    graph = compile_team_graph(
        team_config=team,
        agent_configs=agent_configs,
        checkpointer=checkpointer,
        autonomous=True,
    )

    inputs = {"messages": [HumanMessage(content="Execute the mock human protocol.")]}
    config = _make_config("test-mock-human")

    states: list[dict] = []
    try:
        async for state in graph.astream(inputs, config, stream_mode="values"):
            states.append(state)
    except GraphInterrupt:
        pass

    assert states

    ai_msgs = _ai_messages(states)
    assert ai_msgs

    permission_calls = [
        tc
        for msg in ai_msgs
        for tc in (msg.tool_calls or [])
        if tc.get("name") == "session_request_permission"
    ]
    assert permission_calls
