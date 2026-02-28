"""Tests for the team graph compilation and execution."""

from collections.abc import AsyncGenerator
from pathlib import Path

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


# ---------------------------------------------------------------------------
# Parametrized compilation (C7 rewrite)
# ---------------------------------------------------------------------------

# (preset, topology, expected_worker_nodes, has_supervisor)
_PRESET_CASES: list[tuple[str, str, set[str], bool]] = [
    ("coding-star", "star", {"planner", "coder", "reviewer"}, True),
    ("coding-pipeline", "pipeline", {"planner", "coder", "reviewer"}, False),
    ("coding-loop", "pipeline_loop", {"planner", "coder", "reviewer"}, False),
    ("solo-coder", "pipeline", {"coder"}, False),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("preset", "topology", "expected_workers", "has_supervisor"),
    _PRESET_CASES,
    ids=[c[0] for c in _PRESET_CASES],
)
async def test_compile_graph_structure(
    checkpointer: AsyncSqliteSaver,
    preset: str,
    topology: str,
    expected_workers: set[str],
    has_supervisor: bool,
) -> None:
    """Compiled graph has the correct node set and empty interrupt_before.

    Replaces the previous seven ``assert graph is not None`` tests with
    structural assertions on the compiled graph (C7).
    """
    team = load_team_config(preset)
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}
    supervisor_cfg = load_agent_config("supervisor") if has_supervisor else None

    graph = compile_team_graph(
        team_config=team,
        agent_configs=agent_configs,
        checkpointer=checkpointer,
        supervisor_agent_config=supervisor_cfg,
    )

    assert team.topology.type == topology

    # Verify all expected worker nodes are present
    node_keys = {k for k in graph.nodes if not k.startswith("__")}
    assert expected_workers <= node_keys

    # Supervisor node present only for star topology
    if has_supervisor:
        assert "supervisor" in node_keys
    else:
        assert "supervisor" not in node_keys

    # interrupt_before must always be empty (ADR-013 §2.7)
    assert list(graph.interrupt_before_nodes) == []


# ---------------------------------------------------------------------------
# workspace_root kwarg (ADR-014)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compile_team_graph_accepts_workspace_root(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """compile_team_graph accepts workspace_root and produces a valid graph.

    ADR-014 requires the workspace_root kwarg for ACP CWD scoping.
    """
    team = load_team_config("coding-star")
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}
    supervisor_cfg = load_agent_config("supervisor")

    graph = compile_team_graph(
        team_config=team,
        agent_configs=agent_configs,
        checkpointer=checkpointer,
        supervisor_agent_config=supervisor_cfg,
        workspace_root=Path("Y:/code/test-workspace"),
    )

    node_keys = {k for k in graph.nodes if not k.startswith("__")}
    assert {"planner", "coder", "reviewer", "supervisor"} == node_keys


# ---------------------------------------------------------------------------
# Autonomous vs. supervised mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "autonomous",
    [False, True],
    ids=["supervised", "autonomous"],
)
async def test_compile_interrupt_before_always_empty(
    checkpointer: AsyncSqliteSaver,
    autonomous: bool,
) -> None:
    """interrupt_before is [] in both supervised and autonomous modes.

    ADR-013 §2.7: pre-node interrupts removed. Approval flows
    exclusively via interrupt() inside the node.
    """
    team = load_team_config("coding-pipeline")
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}

    graph = compile_team_graph(
        team_config=team,
        agent_configs=agent_configs,
        checkpointer=checkpointer,
        autonomous=autonomous,
    )

    assert list(graph.interrupt_before_nodes) == []
    # Nodes still present regardless of mode
    node_keys = {k for k in graph.nodes if not k.startswith("__")}
    assert {"planner", "coder", "reviewer"} == node_keys


# ---------------------------------------------------------------------------
# Invalid topology
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compile_unknown_topology_raises(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """An unknown topology type raises ValueError."""
    team = load_team_config("coding-pipeline")
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}

    # Temporarily patch the topology type
    original_type = team.topology.type
    team.topology.type = "unknown_topology"  # type: ignore[assignment]
    try:
        with pytest.raises(ValueError, match="Unknown topology type"):
            compile_team_graph(
                team_config=team,
                agent_configs=agent_configs,
                checkpointer=checkpointer,
            )
    finally:
        team.topology.type = original_type


# ---------------------------------------------------------------------------
# Live execution test (C6 rewrite — no blanket except)
# ---------------------------------------------------------------------------


@pytest.mark.live
@pytest.mark.asyncio
async def test_graph_execution_routing(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """End-to-end: supervisor routes, checkpointer persists state.

    Requires live LLM credentials. Errors propagate instead of
    being silently swallowed (C6 fix).
    """
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
                    "Calculate 25 * 4 and have the coder return"
                    " the expected numerical result."
                    " Then immediately FINISH."
                )
            )
        ],
    }

    config: RunnableConfig = {
        "configurable": {"thread_id": "test_routing_thread"},
        "recursion_limit": 5,
    }

    # Execute — let errors propagate (C6: no blanket except)
    executed_nodes: list[str] = []
    async for event in graph.astream_events(initial_state, config, version="v2"):
        if event["event"] == "on_chain_end":
            node_name = event["name"]
            if node_name in ("supervisor", "coder", "planner", "reviewer"):
                executed_nodes.append(node_name)

    # Validate state was checkpointed
    saved_state = await checkpointer.aget(config)
    assert saved_state is not None
    channel_values = saved_state["channel_values"]
    assert "messages" in channel_values

    # Supervisor must run at least once for star topology
    assert "supervisor" in executed_nodes

    messages = channel_values["messages"]
    assert len(messages) > 1

    # At least one AI message was generated
    ai_messages = [msg for msg in messages if msg.type == "ai"]
    assert len(ai_messages) > 0, f"No AI messages found: {messages}"
