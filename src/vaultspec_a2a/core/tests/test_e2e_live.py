"""End-to-end live integration tests for multi-agent LangGraph orchestration.

These tests exercise the core value proposition: multiple LLM agents collaborating
through LangGraph to complete a task, with inter-agent state accumulation and
checkpoint persistence across turns.

Provider coverage
-----------------
- OpenAI (ChatOpenAI, no ACP subprocess) -- most reliable for CI
- Gemini (AcpChatModel, subprocess JSON-RPC) -- proves ACP protocol path

Key design note
---------------
Agent TOMLs carry hardcoded provider settings (planner=claude, coder=claude,
reviewer=zhipu) that take precedence over team-level defaults in the model
resolution chain.  All tests override at *both* the team defaults level AND
the agent-config level via ``_team_and_agents_with_provider()``.

Requirements
------------
- OpenAI tests:  VAULTSPEC_OPENAI_API_KEY env var
- Gemini tests:  active Gemini CLI session (~/.gemini/oauth_creds.json)

Run all live tests::

    pytest lib/core/tests/test_e2e_live.py -m live -v

Run only OpenAI::

    pytest lib/core/tests/test_e2e_live.py -m live -k openai -v

Run only Gemini::

    pytest lib/core/tests/test_e2e_live.py -m live -k gemini -v
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from ...utils.enums import Model, Provider
from ..graph import compile_team_graph
from ..team_config import (
    AgentModelConfig,
    TeamDefaultsConfig,
    load_agent_config,
    load_team_config,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def checkpointer() -> AsyncGenerator[AsyncSqliteSaver]:
    """In-memory SQLite checkpointer, isolated per test."""
    async with AsyncSqliteSaver.from_conn_string(":memory:") as saver:
        await saver.setup()
        yield saver


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _team_and_agents_with_provider(
    team_id: str, provider: Provider
) -> tuple[object, dict[str, object]]:
    """Load a preset and override provider at both team and agent-config level.

    Agent TOMLs carry their own provider settings (planner=claude, coder=claude,
    reviewer=zhipu) which take precedence over team defaults in the model
    resolution chain.  We override at the agent-config level so tests exercise
    the intended provider end-to-end.
    """
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
    graph: object,
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


# ---------------------------------------------------------------------------
# OpenAI -- solo agent
# ---------------------------------------------------------------------------


@pytest.mark.live
@pytest.mark.asyncio
async def test_solo_coder_openai(checkpointer: AsyncSqliteSaver) -> None:
    """Single-agent graph (vaultspec-solo-coder) completes a code task via OpenAI.

    Proves:
    - Graph compiles and executes with OpenAI provider
    - Checkpoint is written after execution
    - At least one AI message is produced
    """
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
                content="Write a Python function that checks if a number is prime. Keep it short."
            )
        ]
    }

    executed = await _run_and_collect_nodes(graph, state, config, {"vaultspec-coder"})
    assert "vaultspec-coder" in executed

    saved = await checkpointer.aget(config)
    assert saved is not None
    messages = saved["channel_values"]["messages"]
    ai_msgs = [m for m in messages if isinstance(m, AIMessage)]
    assert len(ai_msgs) >= 1, f"Expected at least 1 AI message, got: {messages}"


# ---------------------------------------------------------------------------
# OpenAI -- multi-agent pipeline (core value proposition)
# ---------------------------------------------------------------------------


@pytest.mark.live
@pytest.mark.asyncio
async def test_pipeline_team_openai_collaboration(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """Three-agent pipeline (planner -> coder -> reviewer) with OpenAI.

    This is the primary end-to-end test of the core value proposition:
    multiple LLM agents collaborate through LangGraph, with each agent's
    output accumulated into the shared state and visible to subsequent agents.

    Proves:
    - All three agents in the pipeline execute
    - Messages accumulate: reviewer sees planner's plan and coder's code
    - Checkpoint persists the full conversation after all agents complete
    - Each agent contributes at least one AI message
    """
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
                    "Write a Python function that reverses a string without using slicing. "
                    "Keep each response concise."
                )
            )
        ]
    }

    executed = await _run_and_collect_nodes(graph, state, config, set(agent_configs))

    assert executed == {"vaultspec-planner", "vaultspec-coder", "vaultspec-reviewer"}, (
        f"Expected all pipeline agents to execute, got: {executed}"
    )

    saved = await checkpointer.aget(config)
    assert saved is not None
    messages = saved["channel_values"]["messages"]
    ai_msgs = [m for m in messages if isinstance(m, AIMessage)]

    assert len(ai_msgs) >= 3, (
        f"Expected >= 3 AI messages (one per agent), got {len(ai_msgs)}: {messages}"
    )


# ---------------------------------------------------------------------------
# OpenAI -- checkpoint resume (multi-turn conversation)
# ---------------------------------------------------------------------------


@pytest.mark.live
@pytest.mark.asyncio
async def test_checkpoint_resume_openai(checkpointer: AsyncSqliteSaver) -> None:
    """Checkpoint survives and the thread can be resumed with a follow-up message.

    Proves:
    - LangGraph checkpointer persists state across invocations
    - A second human message in the same thread_id resumes from the checkpoint
    - The second turn accumulates messages on top of turn 1 (history preserved)
    """
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

    # Turn 1
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

    # Turn 2: follow-up in the same thread (resumes from checkpoint)
    state2 = {
        "messages": [
            HumanMessage(content="Now add type hints and a docstring to that function.")
        ]
    }
    await _run_and_collect_nodes(graph, state2, config, {"vaultspec-coder"})
    snap2 = await checkpointer.aget(config)
    assert snap2 is not None
    messages_t2 = snap2["channel_values"]["messages"]

    assert len(messages_t2) > count_after_t1, (
        f"Expected messages to grow after resume: "
        f"turn1={count_after_t1}, turn2={len(messages_t2)}"
    )
    assert any(m.content == state1["messages"][0].content for m in messages_t2), (
        "Turn-1 human message must be preserved in the resumed checkpoint"
    )


# ---------------------------------------------------------------------------
# OpenAI -- star topology (supervisor routing)
# ---------------------------------------------------------------------------


@pytest.mark.live
@pytest.mark.asyncio
async def test_star_topology_supervisor_routing_openai(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """Star topology: supervisor dynamically routes to at least one worker via OpenAI.

    Proves:
    - Supervisor executes and determines routing
    - At least one worker node is dispatched
    - Checkpoint captures the full routed conversation
    """
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

    assert "supervisor" in executed, "Supervisor must execute in star topology"
    workers_ran = executed - {"supervisor"}
    assert len(workers_ran) >= 1, (
        f"Supervisor must route to at least one worker; executed: {executed}"
    )

    saved = await checkpointer.aget(config)
    assert saved is not None
    messages = saved["channel_values"]["messages"]
    ai_msgs = [m for m in messages if isinstance(m, AIMessage)]
    assert len(ai_msgs) >= 1


# ---------------------------------------------------------------------------
# Gemini -- solo agent (proves ACP subprocess protocol)
# ---------------------------------------------------------------------------


@pytest.mark.live
@pytest.mark.asyncio
async def test_solo_coder_gemini(checkpointer: AsyncSqliteSaver) -> None:
    """Single-agent graph completes a task via Gemini ACP subprocess.

    Proves the ACP JSON-RPC stdio protocol works end-to-end:
    spawn -> initialize -> session/new -> session/prompt -> stream chunks -> checkpoint.
    """
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
                content="Write a Python function that checks if a string is a palindrome. Keep it short."
            )
        ]
    }

    executed = await _run_and_collect_nodes(graph, state, config, {"vaultspec-coder"})
    assert "vaultspec-coder" in executed

    saved = await checkpointer.aget(config)
    assert saved is not None
    messages = saved["channel_values"]["messages"]
    ai_msgs = [m for m in messages if isinstance(m, AIMessage)]
    assert len(ai_msgs) >= 1, f"Expected at least 1 AI message, got: {messages}"


# ---------------------------------------------------------------------------
# Gemini -- multi-agent pipeline (proves ACP + LangGraph inter-agent comms)
# ---------------------------------------------------------------------------


@pytest.mark.live
@pytest.mark.asyncio
async def test_pipeline_team_gemini_collaboration(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """Three-agent pipeline (planner -> coder -> reviewer) with Gemini ACP.

    Proves the ACP subprocess protocol works for multi-agent orchestration:
    each agent in the pipeline gets a new ACP session, receives accumulated
    messages from prior agents, and contributes its own AI output to the
    shared state before passing to the next agent.
    """
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

    assert executed == {"vaultspec-planner", "vaultspec-coder", "vaultspec-reviewer"}, (
        f"Expected all pipeline agents to execute, got: {executed}"
    )

    saved = await checkpointer.aget(config)
    assert saved is not None
    messages = saved["channel_values"]["messages"]
    ai_msgs = [m for m in messages if isinstance(m, AIMessage)]
    assert len(ai_msgs) >= 3, (
        f"Expected >= 3 AI messages (one per agent), got {len(ai_msgs)}: {messages}"
    )
