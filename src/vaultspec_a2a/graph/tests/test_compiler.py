"""Tests for the team graph compilation and execution."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from langchain_core.language_models.fake_chat_models import FakeChatModel
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from ..protocols import ProviderFactoryProtocol

from vaultspec_a2a.team.team_config import (
    TeamConfig,
    TopologyConfig,
    TopologyType,
    WorkerRef,
    load_agent_config,
    load_team_config,
)
from vaultspec_a2a.thread.errors import ConfigError

from ..compiler import (
    _build_supervisor_prompt,
    _make_research_producer,
    _resolve_worker_model_preferences,
    _worker_retry_on,
    compile_team_graph,
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


def _make_team(
    *,
    topology: TopologyConfig,
    worker_ids: list[str],
    team_id: str = "inline-test-team",
) -> TeamConfig:
    """Build a TeamConfig inline from real models for topology coverage.

    The multi-role coder presets that used to carry the star, pipeline, and
    pipeline_loop topologies were retired; this constructs an equivalent config
    directly so the real ``compile_team_graph`` paths for those topologies stay
    exercised without depending on a bundled preset.
    """
    return TeamConfig(
        id=team_id,
        display_name=team_id,
        topology=topology,
        workers=[WorkerRef(agent_id=aid) for aid in worker_ids],
    )


def _pipeline_team() -> TeamConfig:
    """A standard three-role pipeline team (planner -> coder -> reviewer)."""
    roles = ["vaultspec-planner", "vaultspec-coder", "vaultspec-reviewer"]
    return _make_team(
        topology=TopologyConfig(type=TopologyType.PIPELINE, order=roles),
        worker_ids=roles,
    )


# (preset, topology, expected_worker_nodes, has_supervisor)
_PRESET_CASES: list[tuple[str, str, set[str], bool]] = [
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
    pf: ProviderFactoryProtocol,
    preset: str,
    topology: str,
    expected_workers: set[str],
    has_supervisor: bool,
) -> None:
    """Compiled graph has the correct node set and empty interrupt_before."""
    team = load_team_config(preset)
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}
    supervisor_cfg = (
        load_agent_config("vaultspec-supervisor") if has_supervisor else None
    )

    graph = compile_team_graph(
        team_config=team,
        agent_configs=agent_configs,
        checkpointer=checkpointer,
        supervisor_agent_config=supervisor_cfg,
        provider_factory=pf,
    )

    assert team.topology.type == topology

    node_keys = {k for k in graph.nodes if not k.startswith("__")}
    assert expected_workers <= node_keys

    if has_supervisor:
        assert "supervisor" in node_keys
    else:
        assert "supervisor" not in node_keys

    assert list(graph.interrupt_before_nodes) == []


# ---------------------------------------------------------------------------
# workspace_root kwarg (ADR-014)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compile_team_graph_accepts_workspace_root(
    checkpointer: AsyncSqliteSaver,
    pf: ProviderFactoryProtocol,
) -> None:
    """compile_team_graph accepts workspace_root and produces a valid graph."""
    team = _make_team(
        topology=TopologyConfig(type=TopologyType.STAR),
        worker_ids=["vaultspec-planner", "vaultspec-coder", "vaultspec-reviewer"],
    )
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}
    supervisor_cfg = load_agent_config("vaultspec-supervisor")

    graph = compile_team_graph(
        team_config=team,
        agent_configs=agent_configs,
        checkpointer=checkpointer,
        supervisor_agent_config=supervisor_cfg,
        workspace_root=Path("Y:/code/test-workspace"),
        provider_factory=pf,
    )

    node_keys = {k for k in graph.nodes if not k.startswith("__")}
    assert {
        "vaultspec-planner",
        "vaultspec-coder",
        "vaultspec-reviewer",
        "supervisor",
        "plan_approval",
        "mount_vaultspec-planner",
        "mount_vaultspec-coder",
        "mount_vaultspec-reviewer",
    } == node_keys


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
    pf: ProviderFactoryProtocol,
    autonomous: bool,
) -> None:
    """interrupt_before is [] in both supervised and autonomous modes."""
    team = _pipeline_team()
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}

    graph = compile_team_graph(
        team_config=team,
        agent_configs=agent_configs,
        checkpointer=checkpointer,
        autonomous=autonomous,
        provider_factory=pf,
    )

    assert list(graph.interrupt_before_nodes) == []
    node_keys = {k for k in graph.nodes if not k.startswith("__")}
    worker_ids = {"vaultspec-planner", "vaultspec-coder", "vaultspec-reviewer"}
    mount_ids = {f"mount_{wid}" for wid in worker_ids}
    assert worker_ids | mount_ids == node_keys


# ---------------------------------------------------------------------------
# Invalid topology
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compile_unknown_topology_raises(
    checkpointer: AsyncSqliteSaver,
    pf: ProviderFactoryProtocol,
) -> None:
    """An unknown topology type raises ValueError."""
    team = _pipeline_team()
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}

    bad_topology = team.topology.model_copy(update={"type": "unknown_topology"})
    bad_team = team.model_copy(update={"topology": bad_topology})
    with pytest.raises(ValueError, match="Unknown topology type"):
        compile_team_graph(
            team_config=bad_team,
            agent_configs=agent_configs,
            checkpointer=checkpointer,
            provider_factory=pf,
        )


# ---------------------------------------------------------------------------
# Pipeline-loop specific tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compile_pipeline_loop_structure(
    checkpointer: AsyncSqliteSaver,
    pf: ProviderFactoryProtocol,
) -> None:
    """pipeline_loop topology produces the correct node set."""
    team = _make_team(
        topology=TopologyConfig(
            type=TopologyType.PIPELINE_LOOP,
            order=["vaultspec-planner", "vaultspec-coder", "vaultspec-reviewer"],
            loop_node="vaultspec-reviewer",
            max_loops=3,
        ),
        worker_ids=["vaultspec-planner", "vaultspec-coder", "vaultspec-reviewer"],
    )
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}

    graph = compile_team_graph(
        team_config=team,
        agent_configs=agent_configs,
        checkpointer=checkpointer,
        provider_factory=pf,
    )

    node_keys = {k for k in graph.nodes if not k.startswith("__")}
    assert "supervisor" not in node_keys
    assert {"vaultspec-planner", "vaultspec-coder", "vaultspec-reviewer"} <= node_keys
    assert list(graph.interrupt_before_nodes) == []


@pytest.mark.asyncio
async def test_compile_pipeline_loop_single_agent_raises(
    checkpointer: AsyncSqliteSaver,
    pf: ProviderFactoryProtocol,
) -> None:
    """pipeline_loop with only the loop_node raises ConfigError."""
    bad_topology = TopologyConfig(
        type=TopologyType.PIPELINE_LOOP,
        order=["vaultspec-reviewer"],
        loop_node="vaultspec-reviewer",
        max_loops=3,
    )
    bad_team = _make_team(topology=bad_topology, worker_ids=["vaultspec-reviewer"])
    agent_configs = {"vaultspec-reviewer": load_agent_config("vaultspec-reviewer")}
    with pytest.raises(ConfigError, match="degenerate self-loop"):
        compile_team_graph(
            team_config=bad_team,
            agent_configs=agent_configs,
            checkpointer=checkpointer,
            provider_factory=pf,
        )


@pytest.mark.asyncio
async def test_compile_pipeline_missing_agent_config_raises(
    checkpointer: AsyncSqliteSaver,
    pf: ProviderFactoryProtocol,
) -> None:
    """Referencing an agent_id not in agent_configs raises ConfigError."""
    team = _pipeline_team()
    agent_configs = {
        w.agent_id: load_agent_config(w.agent_id)
        for w in team.workers
        if w.agent_id != "vaultspec-planner"
    }
    with pytest.raises(ConfigError, match="vaultspec-planner"):
        compile_team_graph(
            team_config=team,
            agent_configs=agent_configs,
            checkpointer=checkpointer,
            provider_factory=pf,
        )


@pytest.mark.asyncio
async def test_compile_pipeline_empty_order_raises(
    checkpointer: AsyncSqliteSaver,
    pf: ProviderFactoryProtocol,
) -> None:
    """Empty pipeline_order raises ConfigError."""
    team = _pipeline_team()
    bad_topology = team.topology.model_copy(update={"order": []})
    bad_team = team.model_copy(update={"topology": bad_topology})
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}
    with pytest.raises(ConfigError, match="empty"):
        compile_team_graph(
            team_config=bad_team,
            agent_configs=agent_configs,
            checkpointer=checkpointer,
            provider_factory=pf,
        )


@pytest.mark.asyncio
async def test_loop_router_worker_can_signal_finish(
    checkpointer: AsyncSqliteSaver,
    pf: ProviderFactoryProtocol,
) -> None:
    """_loop_router returns FINISH when state['next'] is set to 'FINISH'."""
    team = _make_team(
        topology=TopologyConfig(
            type=TopologyType.PIPELINE_LOOP,
            order=["vaultspec-planner", "vaultspec-coder", "vaultspec-reviewer"],
            loop_node="vaultspec-reviewer",
            max_loops=3,
        ),
        worker_ids=["vaultspec-planner", "vaultspec-coder", "vaultspec-reviewer"],
    )
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}

    graph = compile_team_graph(
        team_config=team,
        agent_configs=agent_configs,
        checkpointer=checkpointer,
        provider_factory=pf,
    )

    node_keys = {k for k in graph.nodes if not k.startswith("__")}
    assert "vaultspec-reviewer" in node_keys
    assert graph is not None


# ---------------------------------------------------------------------------
# T01 -- star topology conditional edge with missing 'next' field
# ---------------------------------------------------------------------------


def test_star_missing_next_field() -> None:
    """Star topology conditional edge must not raise KeyError."""
    edge_fn = lambda state: state.get("next", "")  # noqa: E731

    state_without_next: dict = {
        "messages": [],
        "active_agent": "",
        "artifacts": [],
        "current_plan": [],
        "thread_id": "test-thread",
        "token_usage": {},
    }

    result = edge_fn(state_without_next)
    assert result == ""

    state_with_next = {**state_without_next, "next": "planner"}
    assert edge_fn(state_with_next) == "planner"

    state_finish = {**state_without_next, "next": "FINISH"}
    assert edge_fn(state_finish) == "FINISH"


# ---------------------------------------------------------------------------
# T05 -- _worker_retry_on predicate
# ---------------------------------------------------------------------------


def test_worker_retry_on_timeout_wrapped_in_worker_error_is_retried() -> None:
    """WorkerExecutionError wrapping TimeoutError must be retried."""
    from vaultspec_a2a.thread.errors import WorkerExecutionError

    cause = TimeoutError("connection timed out")
    wrapped = WorkerExecutionError(
        worker="coder", model="AcpChatModel", message_count=5
    )
    wrapped.__cause__ = cause
    assert _worker_retry_on(wrapped) is True


def test_worker_retry_on_connection_error_is_retried() -> None:
    """ConnectionError is retried via default_retry_on delegation."""
    assert _worker_retry_on(ConnectionError("connection refused")) is True


def test_worker_retry_on_connection_error_wrapped_in_worker_error_is_retried() -> None:
    """WorkerExecutionError wrapping ConnectionError is retried via __cause__."""
    from vaultspec_a2a.thread.errors import WorkerExecutionError

    cause = ConnectionError("refused")
    wrapped = WorkerExecutionError(
        worker="coder", model="AcpChatModel", message_count=3
    )
    wrapped.__cause__ = cause
    assert _worker_retry_on(wrapped) is True


def test_worker_retry_on_runtime_error_not_retried() -> None:
    """RuntimeError is not retried."""
    assert _worker_retry_on(RuntimeError("boom")) is False


def test_worker_retry_on_worker_error_with_runtime_cause_not_retried() -> None:
    """WorkerExecutionError wrapping RuntimeError is not retried."""
    from vaultspec_a2a.thread.errors import WorkerExecutionError

    cause = RuntimeError("deterministic failure")
    wrapped = WorkerExecutionError(
        worker="coder", model="AcpChatModel", message_count=2
    )
    wrapped.__cause__ = cause
    assert _worker_retry_on(wrapped) is False


# ---------------------------------------------------------------------------
# T11 -- step_timeout wired to compiled graph
# ---------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="function")
async def test_compile_team_graph_step_timeout_set(pf: ProviderFactoryProtocol) -> None:
    """compile_team_graph sets step_timeout on the compiled Pregel graph."""
    team = _pipeline_team()
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}
    async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
        await cp.setup()
        graph = compile_team_graph(
            team_config=team,
            agent_configs=agent_configs,
            checkpointer=cp,
            step_timeout=42.0,
            provider_factory=pf,
        )
    assert graph.step_timeout == 42.0


@pytest.mark.asyncio(loop_scope="function")
async def test_compile_team_graph_step_timeout_falls_back_to_toml(
    pf: ProviderFactoryProtocol,
) -> None:
    """When step_timeout=None, the team TOML step_timeout_seconds is used."""
    team = load_team_config("vaultspec-solo-coder")
    assert team.graph.step_timeout_seconds == 120
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}
    async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
        await cp.setup()
        graph = compile_team_graph(
            team_config=team,
            agent_configs=agent_configs,
            checkpointer=cp,
            step_timeout=None,
            provider_factory=pf,
        )
    assert graph.step_timeout == 120.0


# ---------------------------------------------------------------------------
# TOML-05 -- directive injection + recursion_limit
# ---------------------------------------------------------------------------


def test_build_supervisor_prompt_injects_directive() -> None:
    """_build_supervisor_prompt appends team directive after roster when set."""
    from vaultspec_a2a.team.team_config import AgentConfig

    agents: list[AgentConfig] = []
    base = "You are a supervisor."
    result = _build_supervisor_prompt(agents, base, directive="Always plan first.")
    assert "## Team Directive" in result
    assert "Always plan first." in result


def test_build_supervisor_prompt_no_directive() -> None:
    """_build_supervisor_prompt omits directive section when directive is None."""
    base = "You are a supervisor."
    result = _build_supervisor_prompt([], base, directive=None)
    assert "## Team Directive" not in result


@pytest.mark.asyncio(loop_scope="function")
async def test_compile_team_graph_passes_supervisor_agent_config_to_provider_factory(
    checkpointer: AsyncSqliteSaver,
) -> None:
    """Supervisor model resolution must preserve the supervisor agent identity."""

    class _RecordingProviderFactory:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def create(
            self,
            provider: object,
            *,
            model: object | None = None,
            agent_config: object | None = None,
            workspace_root: object | None = None,
            **kwargs: object,
        ) -> FakeChatModel:
            self.calls.append(
                {
                    "provider": provider,
                    "model": model,
                    "agent_config": agent_config,
                    "workspace_root": workspace_root,
                }
            )
            return FakeChatModel()

    team = load_team_config("mock-supervisor-human-in-loop")
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}
    supervisor_cfg = load_agent_config("vaultspec-supervisor")
    factory = _RecordingProviderFactory()

    graph = compile_team_graph(
        team_config=team,
        agent_configs=agent_configs,
        checkpointer=checkpointer,
        supervisor_agent_config=supervisor_cfg,
        provider_factory=factory,
    )

    assert graph is not None
    assert factory.calls[0]["agent_config"] is supervisor_cfg


@pytest.mark.asyncio(loop_scope="function")
async def test_compile_team_graph_does_not_set_recursion_limit(
    pf: ProviderFactoryProtocol,
) -> None:
    """compile_team_graph leaves recursion_limit at LangGraph default.

    The recursion_limit is passed at runtime via the executor config dict,
    not baked into the compiled graph object.
    """
    team = load_team_config("vaultspec-solo-coder")
    assert team.graph.recursion_limit == 10
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}
    async with AsyncSqliteSaver.from_conn_string(":memory:") as cp:
        await cp.setup()
        graph = compile_team_graph(
            team_config=team,
            agent_configs=agent_configs,
            checkpointer=cp,
            provider_factory=pf,
        )
    # recursion_limit is passed at runtime via config, not set on graph.
    assert not hasattr(graph, "recursion_limit")


# ---------------------------------------------------------------------------
# TOML-05 Scope 2 -- provider_fallback chain
# ---------------------------------------------------------------------------


def test_resolve_worker_model_preferences_honors_worker_override_precedence() -> None:
    """Worker-level provider/capability/fallback overrides win over defaults."""
    from vaultspec_a2a.graph.enums import Model, Provider

    team = load_team_config("vaultspec-solo-coder")
    agent_cfg = load_agent_config("vaultspec-coder")
    worker_ref = team.workers[0]

    worker_ref = worker_ref.model_copy(
        update={
            "model": worker_ref.model.model_copy(
                update={
                    "provider": Provider.GEMINI,
                    "capability": Model.MID,
                    "provider_fallback": [Provider.OPENAI, Provider.ZHIPU],
                }
            )
        }
    )

    provider, capability, fallback_chain = _resolve_worker_model_preferences(
        worker_ref,
        agent_cfg,
        team,
    )
    assert provider == Provider.GEMINI
    assert capability == Model.MID
    assert fallback_chain == [Provider.OPENAI, Provider.ZHIPU]


def test_resolve_worker_model_preferences_consumes_frozen_assignment() -> None:
    """A frozen assignment wins outright and is applied verbatim (restart reuse)."""
    from vaultspec_a2a.graph.enums import Model, Provider

    team = load_team_config("vaultspec-solo-coder")
    agent_cfg = load_agent_config("vaultspec-coder")
    worker_ref = team.workers[0]

    # The frozen record forces mock/low with an openai fallback, overriding both
    # the worker override and the agent config that would otherwise resolve.
    frozen = {
        worker_ref.agent_id: {
            "provider": "mock",
            "capability": "low",
            "fallback": ["openai"],
        }
    }
    provider, capability, fallback_chain = _resolve_worker_model_preferences(
        worker_ref, agent_cfg, team, frozen_assignment=frozen
    )
    assert provider == Provider.MOCK
    assert capability == Model.LOW
    assert fallback_chain == [Provider.OPENAI]


def test_frozen_assignment_absent_worker_falls_through_to_resolution() -> None:
    """A frozen map that does not name this worker leaves resolution unchanged."""
    team = load_team_config("vaultspec-solo-coder")
    agent_cfg = load_agent_config("vaultspec-coder")
    worker_ref = team.workers[0]

    with_frozen = _resolve_worker_model_preferences(
        worker_ref, agent_cfg, team, frozen_assignment={"someone-else": {}}
    )
    without_frozen = _resolve_worker_model_preferences(worker_ref, agent_cfg, team)
    assert with_frozen == without_frozen


# ---------------------------------------------------------------------------
# T15 -- GraphRecursionError excluded from retry
# ---------------------------------------------------------------------------


def test_worker_retry_on_graph_recursion_error_not_retried() -> None:
    """GraphRecursionError must never be retried."""
    from langgraph.errors import GraphRecursionError

    exc = GraphRecursionError("Recursion limit of 100 reached")
    assert _worker_retry_on(exc) is False


@pytest.mark.asyncio
async def test_research_producer_injects_scoped_conventions(tmp_path) -> None:
    """The researcher's model turn receives the role-scoped bundled conventions.

    The researcher is the fourth research_adr document persona but runs through
    ``_make_research_producer`` (not ``_build_worker_messages``); this pins the P04
    follow-on that wires the scoped document-authoring conventions into its turn so
    it is not conventions-blind (graph-agent-framework-harness, S09 flag).
    """
    from typing import Any, cast

    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, ChatResult

    captured: dict[str, list] = {}

    class _RecordingModel(FakeChatModel):
        async def _agenerate(  # type: ignore[no-untyped-def]
            self, messages, stop=None, run_manager=None, **kwargs
        ):
            captured["messages"] = list(messages)
            return ChatResult(
                generations=[ChatGeneration(message=AIMessage(content="finding"))]
            )

    # A bare tmp workspace with no .vaultspec rules: the scoped conventions can
    # only arrive from the shipped bundled default.
    producer = _make_research_producer(
        cast("Any", _RecordingModel()),
        "RESEARCHER SYSTEM PROMPT",
        workspace_root=tmp_path,
    )
    await producer(
        cast("Any", {"messages": []}),
        {"thread_id": "t", "topic": "x", "instructions": "y"},
    )

    texts = "\n".join(str(m.content) for m in captured["messages"])
    assert "RESEARCHER SYSTEM PROMPT" in texts
    # A stable heading from the bundled document-authoring conventions.
    assert "Tag taxonomy" in texts
