"""Direct production-provider proofs for the deterministic scripted scenarios.

These tests construct each model through ``ProviderFactory``, with the lane held
through its plugin, and then exercise the real worker/graph or async-provider
boundary. They intentionally do not model ACP transport semantics.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, cast

import pytest
from langchain_core.messages import AIMessageChunk, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END
from langgraph.types import Command

from ....graph.enums import Provider
from ....graph.nodes.phase_gate import REVIEW_REVISION_SENTINEL
from ....graph.nodes.worker import create_worker_node
from ....providers.factory import ProviderFactory
from ....team.team_config import AgentConfig, load_agent_config, load_team_config
from ... import (
    add_test_node,
    ainvoke_test_graph,
    compile_test_graph,
    new_state_graph,
)
from .. import DeterministicResearchAdrChatModel

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from langchain_core.runnables import RunnableConfig

    from ....thread.state import TeamState


def _scenario_model(
    team_id: str,
) -> tuple[DeterministicResearchAdrChatModel, AgentConfig]:
    """Resolve one bundled scenario through the production factory."""
    team = load_team_config(team_id)
    assert len(team.workers) == 1
    agent = load_agent_config(team.workers[0].agent_id)
    model = ProviderFactory().create(
        Provider.DETERMINISTIC, model="deterministic", agent_config=agent
    )
    assert isinstance(model, DeterministicResearchAdrChatModel)
    return model, agent


def _state(thread_id: str) -> TeamState:
    """Return the minimum real graph state for a single pipeline worker turn."""
    return {
        "active_agent": "coder",
        "artifacts": [],
        "current_plan": [],
        "messages": [HumanMessage(content="Run the deterministic scenario.")],
        "next": "",
        "thread_id": thread_id,
        "token_usage": {},
    }


@pytest.mark.asyncio
async def test_deterministic_permission_pause_resumes_generic_callback() -> None:
    """The factory model pauses and resumes through LangGraph's real callback seam."""
    model, agent = _scenario_model("deterministic-permission-pause")
    node = create_worker_node(
        model=model,
        system_prompt=agent.persona.system_prompt,
        name=agent.id,
    )
    builder = new_state_graph()
    add_test_node(builder, "coder", node)
    builder.set_entry_point("coder")
    builder.add_edge("coder", END)
    graph = compile_test_graph(builder, checkpointer=InMemorySaver())
    config: RunnableConfig = {"configurable": {"thread_id": "deterministic-permission"}}

    first = await ainvoke_test_graph(
        graph, cast("dict[str, Any]", _state("deterministic-permission")), config
    )

    assert "__interrupt__" in first
    pause = first["__interrupt__"][0].value
    assert pause["type"] == "permission_request"
    assert pause["tool_name"] == "deterministic_permission"
    assert {option["optionId"] for option in pause["options"]} == {
        "allow_once",
        "deny_once",
    }

    # Named and recorded as a dispatched permission response is: an answer
    # that names no request belongs to no call and is refused.
    resumed = await ainvoke_test_graph(
        graph,
        Command(
            resume={"option_id": "allow_once", "request_id": pause["request_id"]},
            update={"permission_answers": {pause["request_id"]: "allow_once"}},
        ),
        config,
    )

    assert resumed["messages"][-1].content == (
        "Deterministic permission approved with allow_once."
    )
    assert resumed["messages"][-1].name == agent.id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "agent_id", ("deterministic-coder-success", "deterministic-passing-reviewer")
)
async def test_deterministic_completion_answers_without_asking_for_revision(
    agent_id: str,
) -> None:
    """A completing turn answers, and its answer never sends a review loop back."""
    model = ProviderFactory().create(
        Provider.DETERMINISTIC,
        model="deterministic",
        agent_config=load_agent_config(agent_id),
    )

    reply = await model.ainvoke([HumanMessage(content="finish")])

    assert str(reply.content).strip()
    assert REVIEW_REVISION_SENTINEL not in str(reply.content)


@pytest.mark.asyncio
async def test_deterministic_cancel_window_propagates_non_streaming_cancellation() -> (
    None
):
    """Cancelling an in-flight non-streaming generation remains cancellation."""
    model, _agent = _scenario_model("deterministic-cancel-window")
    task = asyncio.create_task(model.ainvoke([HumanMessage(content="wait")]))
    await asyncio.wait_for(model.wait_for_cancel_window(), timeout=1.0)

    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_deterministic_cancel_window_propagates_streaming_cancellation() -> None:
    """The factory model's streaming turn stays in flight until cancellation."""
    model, _agent = _scenario_model("deterministic-cancel-window")
    stream = model.astream([HumanMessage(content="wait")])

    async def _first_chunk() -> AIMessageChunk:
        # `anext` is an Awaitable, not a Coroutine, and create_task takes the
        # latter. Wrapping is the honest bridge between the two.
        return await anext(stream)

    task = asyncio.create_task(_first_chunk())
    await asyncio.wait_for(model.wait_for_cancel_window(), timeout=1.0)

    assert not task.done()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_deterministic_relay_burst_crosses_replay_window() -> None:
    """The factory scenario emits real chunks beyond the engine relay ring cap."""
    model, _agent = _scenario_model("deterministic-relay-burst")

    stream = model.astream([HumanMessage(content="burst")])
    content_chunks: list[AIMessageChunk] = []
    async for chunk in stream:
        if str(chunk.content):
            content_chunks.append(chunk)
        if len(content_chunks) == 1100:
            break
    # `astream` is typed as an AsyncIterator but is an async generator at
    # runtime, and this loop breaks early, so the generator is closed explicitly
    # rather than left for the collector.
    await cast("AsyncGenerator[AIMessageChunk]", stream).aclose()

    assert len(content_chunks) == 1100
    assert all(len(str(chunk.content)) == 4096 for chunk in content_chunks)
