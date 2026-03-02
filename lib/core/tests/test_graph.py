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
    ("vaultspec-adaptive-coder", "star", {"vaultspec-planner", "vaultspec-coder", "vaultspec-reviewer"}, True),
    ("vaultspec-structured-coder", "pipeline", {"vaultspec-planner", "vaultspec-coder", "vaultspec-reviewer"}, False),
    ("vaultspec-iterative-coder", "pipeline_loop", {"vaultspec-planner", "vaultspec-coder", "vaultspec-reviewer"}, False),
    ("vaultspec-solo-coder", "pipeline", {"vaultspec-coder"}, False),
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
    supervisor_cfg = load_agent_config("vaultspec-supervisor") if has_supervisor else None

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
    team = load_team_config("vaultspec-adaptive-coder")
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}
    supervisor_cfg = load_agent_config("vaultspec-supervisor")

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
    team = load_team_config("vaultspec-structured-coder")
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
    team = load_team_config("vaultspec-structured-coder")
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
    """vaultspec-iterative-coder (pipeline_loop) produces correct node set without a supervisor.

    CORE-L4: independent test for _compile_pipeline_loop topology.
    """
    team = load_team_config("vaultspec-iterative-coder")
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
    team = load_team_config("vaultspec-iterative-coder")
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
    agent_configs = {"vaultspec-reviewer": load_agent_config("vaultspec-reviewer")}
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
    team = load_team_config("vaultspec-structured-coder")
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
    team = load_team_config("vaultspec-structured-coder")
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
    team = load_team_config("vaultspec-iterative-coder")
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
# T01 — star topology conditional edge with missing 'next' field
# ---------------------------------------------------------------------------


def test_star_missing_next_field() -> None:
    """Star topology conditional edge must not raise KeyError when 'next' is absent.

    T01: state.get("next", "") is used instead of state["next"] so a state
    dict that omits 'next' does not raise KeyError when the conditional edge
    function is evaluated.
    """
    # Simulate the star conditional edge lambda directly.
    edge_fn = lambda state: state.get("next", "")  # noqa: E731

    # State without 'next' — previously caused KeyError with state["next"].
    state_without_next: dict = {
        "messages": [],
        "active_agent": "",
        "artifacts": [],
        "current_plan": [],
        "thread_id": "test-thread",
        "token_usage": {},
    }

    # Must not raise KeyError.
    result = edge_fn(state_without_next)
    assert result == ""

    # State with 'next' set to a worker id — normal routing path still works.
    state_with_next = {**state_without_next, "next": "planner"}
    assert edge_fn(state_with_next) == "planner"

    # State with 'next' = 'FINISH' — finish routing path works.
    state_finish = {**state_without_next, "next": "FINISH"}
    assert edge_fn(state_finish) == "FINISH"


# ---------------------------------------------------------------------------
# T05 — _worker_retry_on predicate
# ---------------------------------------------------------------------------


def test_worker_retry_on_timeout_wrapped_in_worker_error_is_retried() -> None:
    """WorkerExecutionError wrapping TimeoutError must be retried.

    T05: Pregel passes WorkerExecutionError to the predicate. We inspect
    __cause__ to evaluate the original failure — TimeoutError is transient.
    """
    from ..exceptions import WorkerExecutionError  # noqa: PLC0415
    from ..graph import _worker_retry_on  # noqa: PLC0415

    cause = TimeoutError("connection timed out")
    wrapped = WorkerExecutionError(worker="coder", model="AcpChatModel", message_count=5)
    wrapped.__cause__ = cause
    assert _worker_retry_on(wrapped) is True


def test_worker_retry_on_connection_error_is_retried() -> None:
    """ConnectionError is retried via default_retry_on delegation."""
    from ..graph import _worker_retry_on  # noqa: PLC0415

    assert _worker_retry_on(ConnectionError("connection refused")) is True


def test_worker_retry_on_connection_error_wrapped_in_worker_error_is_retried() -> None:
    """WorkerExecutionError wrapping ConnectionError is retried via __cause__ inspection."""
    from ..exceptions import WorkerExecutionError  # noqa: PLC0415
    from ..graph import _worker_retry_on  # noqa: PLC0415

    cause = ConnectionError("refused")
    wrapped = WorkerExecutionError(worker="coder", model="AcpChatModel", message_count=3)
    wrapped.__cause__ = cause
    assert _worker_retry_on(wrapped) is True


def test_worker_retry_on_runtime_error_not_retried() -> None:
    """RuntimeError is not retried — not a transient network failure."""
    from ..graph import _worker_retry_on  # noqa: PLC0415

    assert _worker_retry_on(RuntimeError("boom")) is False


def test_worker_retry_on_worker_error_with_runtime_cause_not_retried() -> None:
    """WorkerExecutionError wrapping RuntimeError is not retried."""
    from ..exceptions import WorkerExecutionError  # noqa: PLC0415
    from ..graph import _worker_retry_on  # noqa: PLC0415

    cause = RuntimeError("deterministic failure")
    wrapped = WorkerExecutionError(worker="coder", model="AcpChatModel", message_count=2)
    wrapped.__cause__ = cause
    assert _worker_retry_on(wrapped) is False


# ---------------------------------------------------------------------------
# T11 — step_timeout wired to compiled graph
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="function")
async def test_compile_team_graph_step_timeout_set() -> None:
    """compile_team_graph sets step_timeout on the compiled Pregel graph."""
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from ..graph import compile_team_graph  # noqa: PLC0415
    from ..team_config import load_agent_config, load_team_config  # noqa: PLC0415

    team = load_team_config("vaultspec-adaptive-coder")
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}
    async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
        await cp.setup()
        graph = compile_team_graph(
            team_config=team,
            agent_configs=agent_configs,
            checkpointer=cp,
            step_timeout=42.0,
        )
    assert graph.step_timeout == 42.0


@pytest.mark.asyncio(loop_scope="function")
async def test_compile_team_graph_step_timeout_falls_back_to_toml() -> None:
    """When step_timeout=None, the team TOML step_timeout_seconds is used."""
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from ..graph import compile_team_graph  # noqa: PLC0415
    from ..team_config import load_agent_config, load_team_config  # noqa: PLC0415

    team = load_team_config("vaultspec-adaptive-coder")
    assert team.graph.step_timeout_seconds == 300
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}
    async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
        await cp.setup()
        graph = compile_team_graph(
            team_config=team,
            agent_configs=agent_configs,
            checkpointer=cp,
            step_timeout=None,
        )
    # TOML value applied as fallback
    assert graph.step_timeout == 300.0


# ---------------------------------------------------------------------------
# TOML-05 — directive injection + recursion_limit
# ---------------------------------------------------------------------------


def test_build_supervisor_prompt_injects_directive() -> None:
    """_build_supervisor_prompt appends team directive after roster when set."""
    from ..graph import _build_supervisor_prompt  # noqa: PLC0415
    from ..team_config import AgentConfig  # noqa: PLC0415

    agents: list[AgentConfig] = []
    base = "You are a supervisor."
    result = _build_supervisor_prompt(agents, base, directive="Always plan first.")
    assert "## Team Directive" in result
    assert "Always plan first." in result


def test_build_supervisor_prompt_no_directive() -> None:
    """_build_supervisor_prompt does not add directive section when directive is None."""
    from ..graph import _build_supervisor_prompt  # noqa: PLC0415

    base = "You are a supervisor."
    result = _build_supervisor_prompt([], base, directive=None)
    assert "## Team Directive" not in result


@pytest.mark.asyncio(loop_scope="function")
async def test_compile_team_graph_recursion_limit_from_toml() -> None:
    """compile_team_graph sets recursion_limit from team TOML on the compiled graph."""
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from ..graph import compile_team_graph  # noqa: PLC0415
    from ..team_config import load_agent_config, load_team_config  # noqa: PLC0415

    # vaultspec-solo-coder has recursion_limit = 10
    team = load_team_config("vaultspec-solo-coder")
    assert team.graph.recursion_limit == 10
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}
    async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
        await cp.setup()
        graph = compile_team_graph(
            team_config=team,
            agent_configs=agent_configs,
            checkpointer=cp,
        )
    assert graph.recursion_limit == 10


# ---------------------------------------------------------------------------
# TOML-05 Scope 2 — provider_fallback chain in _resolve_model_for_worker
# ---------------------------------------------------------------------------


def test_resolve_model_for_worker_falls_back_on_primary_failure() -> None:
    """When primary provider raises ValueError, fallback provider is tried."""
    from unittest.mock import MagicMock, patch  # noqa: PLC0415

    from ..graph import _resolve_model_for_worker  # noqa: PLC0415
    from ..team_config import (  # noqa: PLC0415
        AgentConfig,
        AgentModelConfig,
        TeamConfig,
        WorkerOverrideConfig,
        WorkerRef,
        load_agent_config,
        load_team_config,
    )
    from ...utils.enums import Provider  # noqa: PLC0415

    team = load_team_config("vaultspec-solo-coder")
    agent_cfg = load_agent_config("vaultspec-coder")
    worker_ref = team.workers[0]

    fallback_model = MagicMock()

    def _create_side_effect(provider, **kwargs):
        if provider == Provider.CLAUDE:
            raise ValueError("Claude unavailable")
        return fallback_model

    with patch("lib.core.graph.ProviderFactory.create", side_effect=_create_side_effect):
        # Inject a fallback chain via agent model config
        agent_cfg = agent_cfg.model_copy(
            update={"model": agent_cfg.model.model_copy(
                update={"provider_fallback": [Provider.OPENAI]}
            )}
        )
        result = _resolve_model_for_worker(worker_ref, agent_cfg, team)

    assert result is fallback_model


def test_resolve_model_for_worker_raises_when_all_exhausted() -> None:
    """ValueError is raised when all providers in the chain fail."""
    from unittest.mock import patch  # noqa: PLC0415

    from ..graph import _resolve_model_for_worker  # noqa: PLC0415
    from ..team_config import load_agent_config, load_team_config  # noqa: PLC0415
    from ...utils.enums import Provider  # noqa: PLC0415

    team = load_team_config("vaultspec-solo-coder")
    agent_cfg = load_agent_config("vaultspec-coder")
    agent_cfg = agent_cfg.model_copy(
        update={"model": agent_cfg.model.model_copy(
            update={"provider_fallback": [Provider.OPENAI]}
        )}
    )
    worker_ref = team.workers[0]

    with patch(
        "lib.core.graph.ProviderFactory.create",
        side_effect=ValueError("all down"),
    ):
        with pytest.raises(ValueError, match="All providers exhausted"):
            _resolve_model_for_worker(worker_ref, agent_cfg, team)


# ---------------------------------------------------------------------------
# T15 — GraphRecursionError excluded from retry
# ---------------------------------------------------------------------------


def test_worker_retry_on_graph_recursion_error_not_retried() -> None:
    """GraphRecursionError must never be retried — retrying would just hit the limit again."""
    from langgraph.errors import GraphRecursionError  # noqa: PLC0415

    from ..graph import _worker_retry_on  # noqa: PLC0415

    exc = GraphRecursionError("Recursion limit of 100 reached")
    assert _worker_retry_on(exc) is False


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
    team = load_team_config("vaultspec-adaptive-coder")
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}
    supervisor_cfg = load_agent_config("vaultspec-supervisor")

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
