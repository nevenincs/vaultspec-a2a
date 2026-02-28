"""Tests for the team graph compilation and execution."""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from ..graph import compile_team_graph
from ..team_config import load_agent_config, load_team_config


@pytest_asyncio.fixture
async def checkpointer() -> AsyncGenerator[AsyncSqliteSaver]:
    """Provide an in-memory SQLite checkpointer for tests."""
    async with AsyncSqliteSaver.from_conn_string(":memory:") as saver:
        await saver.setup()
        yield saver


@pytest.mark.asyncio
async def test_compile_star_graph(checkpointer: AsyncSqliteSaver) -> None:
    """Verify that a star topology graph compiles successfully."""
    team = load_team_config("coding-star")
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}
    supervisor_cfg = load_agent_config("supervisor")

    graph = compile_team_graph(
        team_config=team,
        agent_configs=agent_configs,
        checkpointer=checkpointer,
        supervisor_agent_config=supervisor_cfg,
    )
    assert graph is not None


@pytest.mark.asyncio
async def test_compile_pipeline_graph(checkpointer: AsyncSqliteSaver) -> None:
    """Verify that a pipeline topology graph compiles successfully."""
    team = load_team_config("coding-pipeline")
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}

    graph = compile_team_graph(
        team_config=team,
        agent_configs=agent_configs,
        checkpointer=checkpointer,
    )
    assert graph is not None


@pytest.mark.asyncio
async def test_compile_pipeline_loop_graph(checkpointer: AsyncSqliteSaver) -> None:
    """Verify that a pipeline_loop topology graph compiles successfully."""
    team = load_team_config("coding-loop")
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}

    graph = compile_team_graph(
        team_config=team,
        agent_configs=agent_configs,
        checkpointer=checkpointer,
    )
    assert graph is not None


@pytest.mark.asyncio
async def test_compile_solo_coder_graph(checkpointer: AsyncSqliteSaver) -> None:
    """Verify that the solo-coder pipeline preset compiles successfully."""
    team = load_team_config("solo-coder")
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}

    graph = compile_team_graph(
        team_config=team,
        agent_configs=agent_configs,
        checkpointer=checkpointer,
    )
    assert graph is not None


@pytest.mark.live
@pytest.mark.asyncio
async def test_graph_execution_routing(checkpointer: AsyncSqliteSaver) -> None:
    """Verify end-to-end execution, routing, and checkpointer state persistence."""
    team = load_team_config("coding-star")
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}
    supervisor_cfg = load_agent_config("supervisor")

    graph = compile_team_graph(
        team_config=team,
        agent_configs=agent_configs,
        checkpointer=checkpointer,
        supervisor_agent_config=supervisor_cfg,
    )

    initial_state = {
        "messages": [
            HumanMessage(
                content=(
                    "Calculate 25 * 4 and have the coder return the"
                    " expected numerical result. Then immediately FINISH."
                )
            )
        ],
    }

    config: RunnableConfig = {
        "configurable": {"thread_id": "test_routing_thread"},
        "recursion_limit": 5,
    }

    # Execute the graph and collect nodes that finished
    executed_nodes = []
    try:
        async for event in graph.astream_events(initial_state, config, version="v2"):
            if event["event"] == "on_chain_end":
                node_name = event["name"]
                if node_name in ("supervisor", "coder", "planner", "reviewer"):
                    executed_nodes.append(node_name)
    except Exception:  # graph may raise on partial execution
        pass

    # Validate state was checkpointed
    saved_state = await checkpointer.aget(config)
    assert saved_state is not None
    channel_values = saved_state["channel_values"]
    assert "messages" in channel_values

    # Supervisor must run at least once for star topology
    assert "supervisor" in executed_nodes

    messages = channel_values["messages"]
    assert len(messages) > 1

    # Check that AI messages were generated
    ai_messages = [msg for msg in messages if msg.type == "ai"]
    assert len(ai_messages) > 0, f"No AI messages found: {messages}"
