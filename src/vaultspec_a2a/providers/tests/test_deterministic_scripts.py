"""Direct production-provider proofs for the deterministic scripted scenarios.

These tests construct each model through ``ProviderFactory`` and then exercise the
real worker/graph or async-provider boundary. They intentionally do not model ACP
or VidaiMock SSE semantics; tape scenarios remain supplemental coverage.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, cast

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ...database import create_thread, seed_task_queue
from ...database.models import Base
from ...graph.enums import Provider
from ...graph.nodes.worker import create_worker_node
from ...team.team_config import AgentConfig, load_agent_config, load_team_config
from ...thread.state import TeamState
from ...worker.task_queue_port import SqlTaskQueuePort
from ..deterministic_chat_model import DeterministicResearchAdrChatModel
from ..factory import ProviderFactory

if TYPE_CHECKING:
    from pathlib import Path

    from langchain_core.runnables import RunnableConfig


def _scenario_model(
    team_id: str,
) -> tuple[DeterministicResearchAdrChatModel, AgentConfig]:
    """Resolve one bundled scenario through the production factory."""
    team = load_team_config(team_id)
    assert team.defaults.provider is Provider.DETERMINISTIC
    assert len(team.workers) == 1
    agent = load_agent_config(team.workers[0].agent_id)
    model = ProviderFactory().create(Provider.DETERMINISTIC, agent_config=agent)
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
async def test_deterministic_tool_call_advances_real_task_queue(tmp_path: Path) -> None:
    """The factory model's tool call is executed by the real SQLite queue port."""
    model, agent = _scenario_model("deterministic-tool-call")
    database_path = tmp_path / "deterministic-tool-call.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        async with session_factory() as session:
            thread = await create_thread(session, title="deterministic tool call")
            await seed_task_queue(
                session,
                thread_id=thread.id,
                feature_tag="deterministic-scripts",
                entries=[
                    {
                        "task_key": "D-1",
                        "description": "first",
                        "status": "in_progress",
                    },
                    {"task_key": "D-2", "description": "second", "status": "pending"},
                ],
            )
            await session.commit()

        node = create_worker_node(
            model=model,
            system_prompt=agent.persona.system_prompt,
            name=agent.id,
            feature_tag="deterministic-scripts",
            task_queue_port=SqlTaskQueuePort(session_factory),
        )
        state = _state(thread.id)
        state["active_feature"] = "deterministic-scripts"
        state["pipeline_phase"] = "exec"
        state["current_task_id"] = "D-1"

        result = await node(state)

        assert result["current_task_id"] == "D-2"
        assert (
            result["messages"][0].content == "Deterministic task queue update settled."
        )
        assert result["messages"][0].name == agent.id
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_deterministic_permission_pause_resumes_generic_callback() -> None:
    """The factory model pauses and resumes through LangGraph's real callback seam."""
    model, agent = _scenario_model("deterministic-permission-pause")
    node = create_worker_node(
        model=model,
        system_prompt=agent.persona.system_prompt,
        name=agent.id,
    )
    builder = StateGraph(cast("Any", TeamState))
    builder.add_node("coder", node)
    builder.set_entry_point("coder")
    builder.add_edge("coder", END)
    graph = builder.compile(checkpointer=InMemorySaver())
    config: RunnableConfig = {"configurable": {"thread_id": "deterministic-permission"}}

    first = await graph.ainvoke(_state("deterministic-permission"), config=config)

    assert "__interrupt__" in first
    pause = first["__interrupt__"][0].value
    assert pause["type"] == "permission_request"
    assert pause["tool_name"] == "deterministic_permission"
    assert {option["optionId"] for option in pause["options"]} == {
        "allow_once",
        "deny_once",
    }

    resumed = await graph.ainvoke(
        Command(resume={"option_id": "allow_once"}), config=config
    )

    assert resumed["messages"][-1].content == (
        "Deterministic permission approved with allow_once."
    )
    assert resumed["messages"][-1].name == agent.id


# The scripted FAILURE path has no scenario preset on this branch, so no test
# drives it here. `deterministic-failure` is NOT that scenario: it is a GRAPH
# BUDGET failure whose preset says so in as many words ("It is NOT a provider
# failure and produces no provider condition"), and it runs two workers rather
# than the single-worker shape these scripted scenarios assume. The branch this
# merged from used that same name for a provider-failure scenario; keeping its
# test would have asserted a contract this repository deliberately replaced.
# `team/tests/test_failure_scenario_preset.py` covers the budget scenario.


@pytest.mark.asyncio
async def test_deterministic_cancel_window_propagates_async_cancellation() -> None:
    """Cancelling an in-flight factory model generation remains cancellation."""
    model, _agent = _scenario_model("deterministic-cancel-window")
    task = asyncio.create_task(model.ainvoke([HumanMessage(content="wait")]))
    await asyncio.wait_for(model.wait_for_cancel_window(), timeout=1.0)

    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
