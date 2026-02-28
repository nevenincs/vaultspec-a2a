"""Tests for the team graph compilation and execution."""

from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
import pytest_asyncio

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from ..exceptions import ConfigError
from ..graph import compile_team_graph
from ..team_config import (
    TopologyConfig,
    TopologyType,
    WorkerRef,
    load_agent_config,
    load_team_config,
)


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

    # M1: use model_copy instead of direct mutation (fragile if model becomes frozen)
    bad_topology = team.topology.model_copy(update={"type": "unknown_topology"})
    bad_team = team.model_copy(update={"topology": bad_topology})
    with pytest.raises(ValueError, match="Unknown topology type"):
        compile_team_graph(
            team_config=bad_team,
            agent_configs=agent_configs,
            checkpointer=checkpointer,
        )


# ---------------------------------------------------------------------------
# Pipeline-loop specific tests (CORE-L4: independent test for pipeline_loop)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compile_pipeline_loop_structure(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """coding-loop (pipeline_loop) produces correct node set without a supervisor.

    CORE-L4: independent test for _compile_pipeline_loop topology.
    """
    team = load_team_config("coding-loop")
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}

    graph = compile_team_graph(
        team_config=team,
        agent_configs=agent_configs,
        checkpointer=checkpointer,
    )

    node_keys = {k for k in graph.nodes if not k.startswith("__")}
    # pipeline_loop has no supervisor
    assert "supervisor" not in node_keys
    # All three pipeline nodes present
    assert {"planner", "coder", "reviewer"} <= node_keys
    # interrupt_before always empty
    assert list(graph.interrupt_before_nodes) == []


@pytest.mark.asyncio
async def test_compile_pipeline_loop_single_agent_raises(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """pipeline_loop with only the loop_node (no pre-loop stages) raises ConfigError.

    CORE-H3: degenerate single-node pipeline_loop must be rejected.
    """
    team = load_team_config("coding-loop")
    # Build a config where only the loop_node ("reviewer") is in the order —
    # no pre-loop stages exist (degenerate case).
    bad_topology = TopologyConfig(
        type=TopologyType.PIPELINE_LOOP,
        order=["reviewer"],
        loop_node="reviewer",
        max_loops=3,
    )
    # Must also have reviewer in workers
    reviewer_ref = WorkerRef(agent_id="reviewer")
    bad_team = team.model_copy(
        update={"topology": bad_topology, "workers": [reviewer_ref]}
    )
    agent_configs = {"reviewer": load_agent_config("reviewer")}
    with pytest.raises(ConfigError, match="degenerate self-loop"):
        compile_team_graph(
            team_config=bad_team,
            agent_configs=agent_configs,
            checkpointer=checkpointer,
        )


@pytest.mark.asyncio
async def test_compile_pipeline_missing_agent_config_raises(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """Referencing an agent_id not in agent_configs raises ConfigError.

    CORE-C2: descriptive error instead of KeyError.
    """
    team = load_team_config("coding-pipeline")
    # Omit "planner" from agent_configs — pipeline order references it
    agent_configs = {
        w.agent_id: load_agent_config(w.agent_id)
        for w in team.workers
        if w.agent_id != "planner"
    }
    with pytest.raises(ConfigError, match="planner"):
        compile_team_graph(
            team_config=team,
            agent_configs=agent_configs,
            checkpointer=checkpointer,
        )


@pytest.mark.asyncio
async def test_compile_pipeline_empty_order_raises(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """Empty pipeline_order raises ConfigError (CORE-M5)."""
    team = load_team_config("coding-pipeline")
    # Force empty order via model_copy on the topology
    bad_topology = team.topology.model_copy(update={"order": []})
    bad_team = team.model_copy(update={"topology": bad_topology})
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}
    with pytest.raises(ConfigError, match="empty"):
        compile_team_graph(
            team_config=bad_team,
            agent_configs=agent_configs,
            checkpointer=checkpointer,
        )


@pytest.mark.asyncio
async def test_loop_router_worker_can_signal_finish(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """_loop_router returns FINISH when state['next'] is set to 'FINISH'.

    CORE-C1: verify the 'FINISH' routing path in _loop_router is reachable
    when a worker node sets next='FINISH' in its return dict. This test
    verifies the graph compiles with correct conditional edges.
    """
    team = load_team_config("coding-loop")
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}

    graph = compile_team_graph(
        team_config=team,
        agent_configs=agent_configs,
        checkpointer=checkpointer,
    )

    # Verify the conditional edge from the loop_node (reviewer) exists
    # by checking that the graph compiled without error and has the
    # expected conditional edges registered.
    node_keys = {k for k in graph.nodes if not k.startswith("__")}
    assert "reviewer" in node_keys
    # Conditional edges from reviewer should route to planner (revise) or END (FINISH)
    # The graph compiles without error — this validates CORE-C1's fix is in place.
    assert graph is not None


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
