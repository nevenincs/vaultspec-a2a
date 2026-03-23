"""End-to-end live integration tests for multi-agent LangGraph orchestration."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from langchain_core.runnables import RunnableConfig
    from langgraph.graph.state import CompiledStateGraph

from vaultspec_a2a.team.team_config import (
    AgentConfig,
    AgentModelConfig,
    TeamConfig,
    TeamDefaultsConfig,
    load_agent_config,
    load_team_config,
)
from vaultspec_a2a.utils.enums import Model, Provider

from ..compiler import compile_team_graph


@pytest_asyncio.fixture
async def checkpointer() -> AsyncGenerator[AsyncSqliteSaver]:
    """In-memory SQLite checkpointer, isolated per test."""
    async with AsyncSqliteSaver.from_conn_string(":memory:") as saver:
        await saver.setup()
        yield saver


def _team_and_agents_with_provider(
    team_id: str, provider: Provider
) -> tuple[TeamConfig, dict[str, AgentConfig]]:
    """Load a preset and override provider at both team and agent-config level."""
    team = load_team_config(team_id)
    team = team.model_copy(
        update={"defaults": TeamDefaultsConfig(provider=provider, capability=Model.LOW)}
    )
    override = AgentModelConfig(provider=provider, capability=Model.LOW)
    agent_configs = {
        w.agent_id: load_agent_config(w.agent_id).model_copy(update={"model": override})
        for w in team.workers
    }
    return team, agent_configs


async def _run_and_collect_nodes(
    graph: CompiledStateGraph,
    initial_state: dict,
    config: RunnableConfig,
    agent_ids: set[str],
) -> set[str]:
    """Stream graph events and return the set of agent node names that executed."""
    executed: set[str] = set()
    async for event in graph.astream_events(initial_state, config, version="v2"):
        if event["event"] == "on_chain_end" and event["name"] in agent_ids:
            executed.add(event["name"])
    return executed


@pytest.mark.live
@pytest.mark.asyncio
async def test_solo_coder_openai(checkpointer: AsyncSqliteSaver) -> None:
    """Single-agent graph completes a code task via OpenAI."""
    team, agent_configs = _team_and_agents_with_provider(
        "vaultspec-solo-coder", Provider.OPENAI
    )
    graph = compile_team_graph(
        team_config=team,
        agent_configs=agent_configs,
        checkpointer=checkpointer,
        autonomous=True,
    )

    thread_id = "e2e-solo-openai"
    config: RunnableConfig = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": 10,
    }
    state = {
        "messages": [
            HumanMessage(
                content=(
                    "Write a Python function that checks if a number is prime."
                    " Keep it short."
                )
            )
        ]
    }

    executed = await _run_and_collect_nodes(graph, state, config, {"vaultspec-coder"})
    assert "vaultspec-coder" in executed

    saved = await checkpointer.aget(config)
    assert saved is not None
    messages = saved["channel_values"]["messages"]
    ai_msgs = [m for m in messages if isinstance(m, AIMessage)]
    assert len(ai_msgs) >= 1


@pytest.mark.live
@pytest.mark.asyncio
async def test_pipeline_team_openai_collaboration(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """Three-agent pipeline with OpenAI."""
    team, agent_configs = _team_and_agents_with_provider(
        "vaultspec-structured-coder", Provider.OPENAI
    )
    graph = compile_team_graph(
        team_config=team,
        agent_configs=agent_configs,
        checkpointer=checkpointer,
        autonomous=True,
    )

    thread_id = "e2e-pipeline-openai"
    config: RunnableConfig = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": 20,
    }
    state = {
        "messages": [
            HumanMessage(
                content=(
                    "Write a Python function that reverses a string"
                    " without using slicing. Keep each response concise."
                )
            )
        ]
    }

    executed = await _run_and_collect_nodes(graph, state, config, set(agent_configs))
    assert executed == {"vaultspec-planner", "vaultspec-coder", "vaultspec-reviewer"}

    saved = await checkpointer.aget(config)
    assert saved is not None
    messages = saved["channel_values"]["messages"]
    ai_msgs = [m for m in messages if isinstance(m, AIMessage)]
    assert len(ai_msgs) >= 3


@pytest.mark.live
@pytest.mark.asyncio
async def test_checkpoint_resume_openai(checkpointer: AsyncSqliteSaver) -> None:
    """Checkpoint survives and the thread can be resumed."""
    team, agent_configs = _team_and_agents_with_provider(
        "vaultspec-solo-coder", Provider.OPENAI
    )
    graph = compile_team_graph(
        team_config=team,
        agent_configs=agent_configs,
        checkpointer=checkpointer,
        autonomous=True,
    )

    thread_id = "e2e-resume-openai"
    config: RunnableConfig = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": 10,
    }

    state1 = {
        "messages": [
            HumanMessage(
                content="Write a Python function called `add(a, b)` that returns a + b."
            )
        ]
    }
    await _run_and_collect_nodes(graph, state1, config, {"vaultspec-coder"})
    snap1 = await checkpointer.aget(config)
    assert snap1 is not None
    count_after_t1 = len(snap1["channel_values"]["messages"])

    state2 = {
        "messages": [
            HumanMessage(content="Now add type hints and a docstring to that function.")
        ]
    }
    await _run_and_collect_nodes(graph, state2, config, {"vaultspec-coder"})
    snap2 = await checkpointer.aget(config)
    assert snap2 is not None
    messages_t2 = snap2["channel_values"]["messages"]

    assert len(messages_t2) > count_after_t1


@pytest.mark.live
@pytest.mark.asyncio
async def test_star_topology_supervisor_routing_openai(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """Star topology: supervisor routes to at least one worker via OpenAI."""
    team, agent_configs = _team_and_agents_with_provider(
        "vaultspec-adaptive-coder", Provider.OPENAI
    )
    supervisor_cfg = load_agent_config("vaultspec-supervisor").model_copy(
        update={
            "model": AgentModelConfig(provider=Provider.OPENAI, capability=Model.LOW)
        }
    )

    graph = compile_team_graph(
        team_config=team,
        agent_configs=agent_configs,
        checkpointer=checkpointer,
        supervisor_agent_config=supervisor_cfg,
        autonomous=True,
    )

    thread_id = "e2e-star-openai"
    config: RunnableConfig = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": 15,
    }
    state = {
        "messages": [
            HumanMessage(
                content=(
                    "Write a Python function that computes factorial. "
                    "Have the coder implement it and then FINISH immediately."
                )
            )
        ]
    }

    all_node_ids = set(agent_configs) | {"supervisor"}
    executed = await _run_and_collect_nodes(graph, state, config, all_node_ids)

    assert "supervisor" in executed
    workers_ran = executed - {"supervisor"}
    assert len(workers_ran) >= 1


@pytest.mark.live
@pytest.mark.asyncio
async def test_solo_coder_gemini(checkpointer: AsyncSqliteSaver) -> None:
    """Single-agent graph completes a task via Gemini ACP subprocess."""
    team, agent_configs = _team_and_agents_with_provider(
        "vaultspec-solo-coder", Provider.GEMINI
    )
    graph = compile_team_graph(
        team_config=team,
        agent_configs=agent_configs,
        checkpointer=checkpointer,
        autonomous=True,
    )

    thread_id = "e2e-solo-gemini"
    config: RunnableConfig = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": 10,
    }
    state = {
        "messages": [
            HumanMessage(
                content=(
                    "Write a Python function that checks if a string is a palindrome."
                    " Keep it short."
                )
            )
        ]
    }

    executed = await _run_and_collect_nodes(graph, state, config, {"vaultspec-coder"})
    assert "vaultspec-coder" in executed

    saved = await checkpointer.aget(config)
    assert saved is not None


@pytest.mark.live
@pytest.mark.asyncio
async def test_pipeline_team_gemini_collaboration(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """Three-agent pipeline with Gemini ACP."""
    team, agent_configs = _team_and_agents_with_provider(
        "vaultspec-structured-coder", Provider.GEMINI
    )
    graph = compile_team_graph(
        team_config=team,
        agent_configs=agent_configs,
        checkpointer=checkpointer,
        autonomous=True,
    )

    thread_id = "e2e-pipeline-gemini"
    config: RunnableConfig = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": 20,
    }
    state = {
        "messages": [
            HumanMessage(
                content=(
                    "Plan, implement, and review a Python function that counts vowels "
                    "in a string. Keep each response concise."
                )
            )
        ]
    }

    executed = await _run_and_collect_nodes(graph, state, config, set(agent_configs))
    assert executed == {"vaultspec-planner", "vaultspec-coder", "vaultspec-reviewer"}
