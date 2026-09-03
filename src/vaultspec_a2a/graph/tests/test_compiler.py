"""Tests for the team graph compilation and execution."""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast, override

import pytest
import pytest_asyncio
from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import FakeChatModel
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable

    from langgraph.types import RetryPolicy

    from ..protocols import ProviderFactoryProtocol

from ...providers import AcpPromptError, ProviderCondition
from ...providers.codex_chat_model import _turn_failure
from ...providers.conditions import condition_from_acp_error, condition_is_retryable
from ...providers.factory import ProviderFactory
from ...providers.lane_admission import IN_PROCESS_LANES
from ...providers.model_profiles import resolve_role_assignment
from ...team.team_config import (
    TeamConfig,
    TopologyConfig,
    TopologyType,
    WorkerRef,
    discover_team_preset_ids,
    load_agent_config,
    load_team_config,
)
from ...thread.errors import ConfigError, WorkerExecutionError
from ...thread.state import TeamState
from ..compiler import (
    _NODE_RETRY_POLICY,
    _build_supervisor_prompt,
    _loop_route,
    _make_research_producer,
    _parse_catalog_preferences,
    _resolve_model_for_worker,
    _resolve_worker_model_preferences,
    _route_from_supervisor,
    _worker_retry_on,
    compile_team_graph,
)
from .conftest import deterministic_model_assignment


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
    """A standard three-role pipeline team (plan-author -> coder -> doc-reviewer)."""
    roles = ["vaultspec-plan-author", "vaultspec-coder", "vaultspec-doc-reviewer"]
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
        model_assignment=deterministic_model_assignment(team),
    )

    assert team.topology.type == topology

    node_keys = {k for k in graph.nodes if not k.startswith("__")}
    assert expected_workers <= node_keys

    if has_supervisor:
        assert "supervisor" in node_keys
    else:
        assert "supervisor" not in node_keys

    assert list(graph.interrupt_before_nodes) == []


@pytest.mark.parametrize("preset_id", sorted(discover_team_preset_ids()))
def test_bundled_preset_workers_resolve_only_on_an_in_process_lane(
    preset_id: str,
) -> None:
    """A shipped worker resolves WITHOUT a frozen selection only in process.

    Both branches are asserted rather than just the resolving one, because the
    refusal is the part that regressed silently before. An external lane's models
    are named by the catalog that provider serves and frozen per role at run
    start, so resolving one from configuration alone would mean inventing a model
    identifier the provider never advertised. The in-process lanes are exempt
    because no catalog exists to enumerate them.
    """
    team = load_team_config(preset_id)
    factory = ProviderFactory()

    for worker_ref in team.workers:
        agent_config = load_agent_config(worker_ref.agent_id)
        assignment = resolve_role_assignment(worker_ref, agent_config, team, None)

        if assignment.provider in IN_PROCESS_LANES:
            model, _provider, _capability, _frozen_model = _resolve_model_for_worker(
                worker_ref, agent_config, team, provider_factory=factory
            )
            assert isinstance(model, BaseChatModel), (
                f"{preset_id}:{worker_ref.agent_id} resolved "
                f"{type(model).__name__}, not a BaseChatModel"
            )
            continue

        # The compiler now names the cause directly rather than surfacing it as
        # fallback exhaustion: the role declares no provider, and a run picks its
        # provider and model at start from the catalog its lane serves.
        with pytest.raises(ValueError, match="has no provider"):
            _resolve_model_for_worker(
                worker_ref, agent_config, team, provider_factory=factory
            )


# ---------------------------------------------------------------------------
# workspace_root kwarg
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compile_team_graph_accepts_workspace_root(
    checkpointer: AsyncSqliteSaver,
    pf: ProviderFactoryProtocol,
) -> None:
    """compile_team_graph accepts workspace_root and produces a valid graph."""
    team = _make_team(
        topology=TopologyConfig(type=TopologyType.STAR),
        worker_ids=[
            "vaultspec-plan-author",
            "vaultspec-coder",
            "vaultspec-doc-reviewer",
        ],
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
        model_assignment=deterministic_model_assignment(team),
    )

    node_keys = {k for k in graph.nodes if not k.startswith("__")}
    assert {
        "vaultspec-plan-author",
        "vaultspec-coder",
        "vaultspec-doc-reviewer",
        "supervisor",
        "plan_approval",
        "mount_vaultspec-plan-author",
        "mount_vaultspec-coder",
        "mount_vaultspec-doc-reviewer",
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
        model_assignment=deterministic_model_assignment(team),
    )

    assert list(graph.interrupt_before_nodes) == []
    node_keys = {k for k in graph.nodes if not k.startswith("__")}
    worker_ids = {
        "vaultspec-plan-author",
        "vaultspec-coder",
        "vaultspec-doc-reviewer",
    }
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
            model_assignment=deterministic_model_assignment(bad_team),
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
            order=[
                "vaultspec-plan-author",
                "vaultspec-coder",
                "vaultspec-doc-reviewer",
            ],
            loop_node="vaultspec-doc-reviewer",
            max_loops=3,
        ),
        worker_ids=[
            "vaultspec-plan-author",
            "vaultspec-coder",
            "vaultspec-doc-reviewer",
        ],
    )
    agent_configs = {w.agent_id: load_agent_config(w.agent_id) for w in team.workers}

    graph = compile_team_graph(
        team_config=team,
        agent_configs=agent_configs,
        checkpointer=checkpointer,
        provider_factory=pf,
        model_assignment=deterministic_model_assignment(team),
    )

    node_keys = {k for k in graph.nodes if not k.startswith("__")}
    assert "supervisor" not in node_keys
    assert {
        "vaultspec-plan-author",
        "vaultspec-coder",
        "vaultspec-doc-reviewer",
    } <= node_keys
    assert list(graph.interrupt_before_nodes) == []


@pytest.mark.asyncio
async def test_compile_pipeline_loop_single_agent_raises(
    checkpointer: AsyncSqliteSaver,
    pf: ProviderFactoryProtocol,
) -> None:
    """pipeline_loop with only the loop_node raises ConfigError."""
    bad_topology = TopologyConfig(
        type=TopologyType.PIPELINE_LOOP,
        order=["vaultspec-doc-reviewer"],
        loop_node="vaultspec-doc-reviewer",
        max_loops=3,
    )
    bad_team = _make_team(topology=bad_topology, worker_ids=["vaultspec-doc-reviewer"])
    agent_configs = {
        "vaultspec-doc-reviewer": load_agent_config("vaultspec-doc-reviewer")
    }
    with pytest.raises(ConfigError, match="degenerate self-loop"):
        compile_team_graph(
            team_config=bad_team,
            agent_configs=agent_configs,
            checkpointer=checkpointer,
            provider_factory=pf,
            model_assignment=deterministic_model_assignment(bad_team),
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
        if w.agent_id != "vaultspec-plan-author"
    }
    with pytest.raises(ConfigError, match="vaultspec-plan-author"):
        compile_team_graph(
            team_config=team,
            agent_configs=agent_configs,
            checkpointer=checkpointer,
            provider_factory=pf,
            model_assignment=deterministic_model_assignment(team),
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
            model_assignment=deterministic_model_assignment(bad_team),
        )


def test_loop_route_signals_finish_only_on_the_literal_and_the_guard() -> None:
    """The real ``_loop_route`` decision, exercised directly (not compile-only).

    Before this replaced a compile-only assertion, the test only checked that a
    pipeline-loop graph compiled - it never exercised the routing logic its name
    and docstring promised. Import the production decision and assert every arm:
    the literal FINISH ends the loop, the max_loops guard forces FINISH, and any
    other residue (empty, a stale star value, ``None``) routes back to revise.
    """
    # Literal FINISH ends the loop early, while below the guard.
    assert _loop_route(next_value="FINISH", loop_count=0, max_loops=3) == "FINISH"
    # Any non-FINISH residue routes back to the loop, not out of it.
    assert _loop_route(next_value="revise", loop_count=0, max_loops=3) == "revise"
    assert _loop_route(next_value="", loop_count=1, max_loops=3) == "revise"
    assert _loop_route(next_value="vaultspec-coder", loop_count=1, max_loops=3) == (
        "revise"
    )
    assert _loop_route(next_value=None, loop_count=0, max_loops=3) == "revise"
    # The max_loops guard forces FINISH once the counter reaches the ceiling,
    # regardless of the residue in next_value.
    assert _loop_route(next_value="revise", loop_count=3, max_loops=3) == "FINISH"
    assert _loop_route(next_value="", loop_count=4, max_loops=3) == "FINISH"


# ---------------------------------------------------------------------------
# T01 -- star topology conditional edge with missing 'next' field
# ---------------------------------------------------------------------------


def test_route_from_supervisor_honors_approval_then_the_next_decision() -> None:
    """The real star supervisor router, exercised directly (not a shadow lambda).

    This replaced a test that reimplemented the edge as ``state.get("next", "")``
    - a shadow that matched neither the production router (which reads
    ``state["next"]`` directly) nor its flow. Import the real router and assert
    both arms: a pending approval short-circuits to ``plan_approval`` ahead of any
    ``next`` decision, and otherwise the supervisor's ``next`` is the route key.
    """

    def _state(**overrides: object) -> TeamState:
        base: dict[str, object] = {
            "messages": [],
            "active_agent": "",
            "artifacts": [],
            "current_plan": [],
            "thread_id": "test-thread",
            "token_usage": {},
        }
        base.update(overrides)
        return cast("TeamState", base)

    # A pending plan approval short-circuits before next is even consulted.
    assert (
        _route_from_supervisor(_state(approval_status="pending", next="planner"))
        == "plan_approval"
    )

    # With no pending approval, the supervisor's own next decision routes.
    assert _route_from_supervisor(_state(next="planner")) == "planner"
    assert _route_from_supervisor(_state(next="FINISH")) == "FINISH"


# ---------------------------------------------------------------------------
# T05 -- _worker_retry_on predicate
# ---------------------------------------------------------------------------


def test_worker_retry_on_timeout_wrapped_in_worker_error_is_retried() -> None:
    """WorkerExecutionError wrapping TimeoutError must be retried."""
    from ...thread.errors import WorkerExecutionError

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
    from ...thread.errors import WorkerExecutionError

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
    from ...thread.errors import WorkerExecutionError

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
            model_assignment=deterministic_model_assignment(team),
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
            model_assignment=deterministic_model_assignment(team),
        )
    assert graph.step_timeout == 120.0


# ---------------------------------------------------------------------------
# directive injection + recursion_limit
# ---------------------------------------------------------------------------


def test_build_supervisor_prompt_injects_directive() -> None:
    """_build_supervisor_prompt appends team directive after roster when set."""
    from ...team.team_config import AgentConfig

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
        model_assignment=deterministic_model_assignment(team),
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
            model_assignment=deterministic_model_assignment(team),
        )
    # recursion_limit is passed at runtime via config, not set on graph.
    assert not hasattr(graph, "recursion_limit")


# ---------------------------------------------------------------------------
# provider_fallback chain
# ---------------------------------------------------------------------------


def test_resolve_worker_model_preferences_honors_worker_override_precedence() -> None:
    """Worker-level provider/capability/fallback overrides win over defaults."""
    from ...graph.enums import Model, Provider

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

    provider, capability, fallback_chain, model_name = (
        _resolve_worker_model_preferences(
            worker_ref,
            agent_cfg,
            team,
        )
    )
    assert provider == Provider.GEMINI
    assert capability == Model.MID
    assert fallback_chain == [Provider.OPENAI, Provider.ZHIPU]
    # Unfrozen resolution carries no concrete model name; the launch-time mapping
    # picks it. Only a frozen assignment pins one.
    assert model_name is None


def test_resolve_worker_model_preferences_consumes_frozen_assignment() -> None:
    """A frozen assignment wins outright and is applied verbatim (restart reuse)."""
    from ...graph.enums import Model, Provider

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
            "model_name": "mock-frozen-1",
        }
    }
    provider, capability, fallback_chain, model_name = (
        _resolve_worker_model_preferences(
            worker_ref, agent_cfg, team, frozen_assignment=frozen
        )
    )
    assert provider == Provider.MOCK
    assert capability == Model.LOW
    assert fallback_chain == [Provider.OPENAI]
    # The whole point of freezing: the concrete model name is reproduced verbatim
    # across a restart rather than re-resolved from a possibly-newer mapping.
    assert model_name == "mock-frozen-1"


def test_frozen_assignment_absent_worker_falls_through_to_resolution() -> None:
    """A frozen map that does not name this worker leaves resolution unchanged.

    Unchanged now means "refuses identically". The preset declares no provider,
    so configuration alone cannot resolve one and the resolver says so; what this
    pins is that a frozen map naming SOMEONE ELSE neither supplies the missing
    lane nor changes the refusal. Comparing the two outcomes is still the point -
    only the outcome being compared moved from a resolved pair to a refusal.
    """
    team = load_team_config("vaultspec-solo-coder")
    agent_cfg = load_agent_config("vaultspec-coder")
    worker_ref = team.workers[0]

    with pytest.raises(ValueError, match="has no provider") as with_frozen:
        _resolve_worker_model_preferences(
            worker_ref, agent_cfg, team, frozen_assignment={"someone-else": {}}
        )
    with pytest.raises(ValueError, match="has no provider") as without_frozen:
        _resolve_worker_model_preferences(worker_ref, agent_cfg, team)
    assert str(with_frozen.value) == str(without_frozen.value)


def test_catalog_preferences_preserve_exact_mode_model_and_controls() -> None:
    from ...graph.enums import Provider

    provider, model_name, execution_mode, controls = _parse_catalog_preferences(
        {
            "schema_version": 1,
            "provider": "codex",
            "execution_mode": "codex-app-server",
            "model_name": "provider-model",
            "controls": [
                {
                    "control_id": "reasoning_effort:entry",
                    "option_id": "opaque-option",
                    "provider_value": "brief",
                }
            ],
        }
    )
    assert provider == Provider.CODEX
    assert model_name == "provider-model"
    assert execution_mode == "codex-app-server"
    assert controls == {"reasoning_effort:entry": "brief"}


# ---------------------------------------------------------------------------
# T15 -- GraphRecursionError excluded from retry
# ---------------------------------------------------------------------------


def test_worker_retry_on_graph_recursion_error_not_retried() -> None:
    """GraphRecursionError must never be retried."""
    from langgraph.errors import GraphRecursionError

    exc = GraphRecursionError("Recursion limit of 100 reached")
    assert _worker_retry_on(exc) is False


# ---------------------------------------------------------------------------
# Provider conditions under the real node retry policy
# ---------------------------------------------------------------------------
#
# These drive a real compiled graph and count the attempts its node body actually
# made. Asserting on the classifier in isolation would prove the predicate and
# nothing else: it would still pass with the policy detached from every node, so
# it cannot tell "retries correctly" from "never retries at all". The counter is
# incremented by the node body itself, which is the only instrument that observes
# the retry rather than the intent to retry.


def _acp_failure(kind: str) -> AcpPromptError:
    """Raise-shaped ACP failure carrying the condition its own mapper resolves.

    The condition is derived from a wire-shaped frame through the lane's real
    mapper rather than named directly, so a mapping change moves these cases with
    it instead of leaving them asserting a member the lane stopped emitting.
    """
    frame: dict[str, object] = {
        "code": -32603,
        "message": f"acp failure: {kind}",
        "data": {"errorKind": kind},
    }
    return AcpPromptError(
        f"acp failure: {kind}",
        code=-32603,
        data=frame["data"],
        condition=condition_from_acp_error(frame),
    )


def _codex_failure(info: object, *, will_retry: object = None) -> Exception:
    """Raise-shaped Codex failure built by the lane's own turn-error builder.

    Used for the members only this lane's wire can name, and for the retry hint,
    which no other served lane carries.
    """
    return _turn_failure(
        cast("Any", {"message": "codex failure", "codexErrorInfo": info}),
        will_retry=cast("Any", will_retry),
    )


#: One real provider failure per condition member, each built from the wire shape
#: of the lane that actually emits that member.
_FAILURE_BY_CONDITION: dict[ProviderCondition, Callable[[], Exception]] = {
    ProviderCondition.THROTTLED: lambda: _acp_failure("rate_limit"),
    ProviderCondition.PROVIDER_OVERLOADED: lambda: _acp_failure("overloaded"),
    ProviderCondition.UNAUTHENTICATED: lambda: _acp_failure("authentication_failed"),
    ProviderCondition.CREDITS_EXHAUSTED: lambda: _acp_failure("billing_error"),
    ProviderCondition.INVALID_REQUEST: lambda: _acp_failure("invalid_request"),
    ProviderCondition.UNKNOWN: lambda: _acp_failure("server_error"),
    ProviderCondition.NETWORK_UNREACHABLE: lambda: _codex_failure(
        {"httpConnectionFailed": {}}
    ),
    ProviderCondition.USAGE_EXHAUSTED: lambda: _codex_failure("usageLimitExceeded"),
    ProviderCondition.BUDGET_EXHAUSTED: lambda: _codex_failure("sessionBudgetExceeded"),
}

#: What each member is SPECIFIED to do, written out rather than read back from the
#: production set. Reading the set would make this table agree with the code by
#: construction and pass however the code was mutated; spelled out, it fails the
#: moment production and the decision disagree.
#:
#: Retry: the two canonically transient refusals, plus the transport failure whose
#: stdlib equivalents this policy has always retried. Do not retry: the three that
#: need a credential, a payment or a raised ceiling; the request that cannot
#: succeed as sent; the allowance window no bounded backoff outlives; and the
#: floor, where the wire said nothing at all.
_EXPECTED_ATTEMPTS: dict[ProviderCondition, int] = {
    ProviderCondition.THROTTLED: 3,
    ProviderCondition.PROVIDER_OVERLOADED: 3,
    ProviderCondition.NETWORK_UNREACHABLE: 3,
    ProviderCondition.UNAUTHENTICATED: 1,
    ProviderCondition.CREDITS_EXHAUSTED: 1,
    ProviderCondition.BUDGET_EXHAUSTED: 1,
    ProviderCondition.USAGE_EXHAUSTED: 1,
    ProviderCondition.INVALID_REQUEST: 1,
    ProviderCondition.UNKNOWN: 1,
}

#: The production policy with its sleep collapsed and nothing else touched.
#:
#: ``retry_on`` - the classifier under test - and ``max_attempts`` are carried
#: over verbatim from the shipped object; only the timing fields are replaced, so
#: the exhaustive sweep below costs milliseconds instead of sleeping through
#: 0.5s + 1.0s of real backoff nine times over. The shipped intervals are not left
#: unproven: one case below runs the untouched production object and asserts that
#: its real first interval actually elapsed.
_FAST_RETRY_POLICY = _NODE_RETRY_POLICY._replace(
    initial_interval=0.001, max_interval=0.001, jitter=False
)


def _counting_failure_graph(
    make_failure: Callable[[], Exception],
    *,
    policy: RetryPolicy,
    attempts: list[int],
) -> Any:
    """Compile a real one-node graph whose node fails the way a worker fails.

    The node wraps its provider failure in ``WorkerExecutionError`` and chains it,
    which is the shape the worker node produces in production and therefore the
    shape the classifier has to unwrap. Every entered attempt appends to
    *attempts* before raising, so the list length is the count of real executions.
    """
    from ...thread.errors import WorkerExecutionError

    async def failing_node(state: Any) -> dict[str, Any]:
        attempts.append(len(attempts) + 1)
        cause = make_failure()
        raise WorkerExecutionError(
            worker="coder", model="acp:test", message_count=1, cause=cause
        ) from cause

    builder: StateGraph = StateGraph(cast("Any", TeamState))
    builder.add_node("coder", failing_node, retry_policy=policy)
    builder.add_edge(START, "coder")
    builder.add_edge("coder", END)
    return builder.compile()


async def _attempts_for(
    make_failure: Callable[[], Exception], *, policy: RetryPolicy
) -> list[int]:
    """Run a real graph to exhaustion and return the attempts its node made."""
    from ...thread.errors import WorkerExecutionError

    attempts: list[int] = []
    graph = _counting_failure_graph(make_failure, policy=policy, attempts=attempts)
    with pytest.raises(WorkerExecutionError):
        await graph.ainvoke({"messages": []})
    return attempts


@pytest.mark.asyncio(loop_scope="function")
@pytest.mark.parametrize("condition", sorted(_EXPECTED_ATTEMPTS, key=str))
async def test_a_condition_retries_exactly_as_the_taxonomy_says_it_should(
    condition: ProviderCondition,
) -> None:
    """Every member's real attempt count matches what the taxonomy specifies.

    Both halves are load-bearing. Without the retrying members this cannot show
    the policy fires at all; without the refusing ones it cannot distinguish a
    classifier from a policy that retries everything, which would spend a user's
    quota on failures no retry can fix.
    """
    failure = _FAILURE_BY_CONDITION[condition]
    # The failure really does carry the member this case is about, so a mapping
    # change cannot leave the sweep silently exercising one condition nine times.
    assert getattr(failure(), "condition", None) is condition

    attempts = await _attempts_for(failure, policy=_FAST_RETRY_POLICY)
    assert len(attempts) == _EXPECTED_ATTEMPTS[condition]


@pytest.mark.asyncio(loop_scope="function")
async def test_a_throttled_failure_retries_under_the_shipped_backoff() -> None:
    """The untouched production policy retries, and its real interval elapses.

    The sweep above collapses the sleep to keep nine cases cheap, which leaves the
    shipped intervals unexercised. This case runs the object the compiler actually
    attaches, so the wait a throttled provider gets is the configured one rather
    than a value only this test ever sees.
    """
    started = time.monotonic()
    attempts = await _attempts_for(
        _FAILURE_BY_CONDITION[ProviderCondition.THROTTLED],
        policy=_NODE_RETRY_POLICY,
    )
    elapsed = time.monotonic() - started

    assert len(attempts) == _NODE_RETRY_POLICY.max_attempts
    # Two sleeps separate three attempts; the first alone is at least the
    # configured initial interval, so anything shorter means no real backoff ran.
    assert elapsed >= _NODE_RETRY_POLICY.initial_interval


@pytest.mark.asyncio(loop_scope="function")
async def test_a_stated_lane_retry_hint_overrides_the_inferred_verdict() -> None:
    """A verdict the lane sent wins over the one this classifier would derive.

    Driven in both directions on purpose: a hint that only agreed with the
    inference would be indistinguishable from not being read at all.
    """
    # The lane says it would have tried again, on a condition inference refuses.
    retried = await _attempts_for(
        lambda: _codex_failure("unauthorized", will_retry=True),
        policy=_FAST_RETRY_POLICY,
    )
    assert len(retried) == _FAST_RETRY_POLICY.max_attempts

    # The lane says it is done, on a condition inference would have retried.
    abandoned = await _attempts_for(
        lambda: _codex_failure("serverOverloaded", will_retry=False),
        policy=_FAST_RETRY_POLICY,
    )
    assert len(abandoned) == 1


#: Node-name shapes that legitimately carry no retry policy.
#:
#: Every one of them is pure control flow: a mount step, a human gate, a proposal
#: submit, a fan-out dispatch. None invokes a model, so none can suffer a provider
#: fault, and retrying one would repeat a routing decision rather than a request.
#:
#: The assertion below is written against this list INVERTED - every node that
#: carries no policy must be named here - rather than against a list of the nodes
#: that should carry one. The polarity is the point: a list of expected carriers
#: is a second table that silently stops covering a node someone adds later,
#: which is precisely how eight of the eleven attachment sites came to be
#: unasserted. Inverted, a newly added model-backed node fails this test until
#: someone decides which side of the line it is on.
_POLICY_FREE_NODE_NAMES: frozenset[str] = frozenset(
    {
        "plan_approval",
        "research_dispatch",
        "clarification_request",
        "clarification_gate",
        "research_submit",
        "research_gate",
        "adr_submit",
        "adr_gate",
        "plan_submit",
        "plan_gate",
    }
)


def _policy_free_by_shape(name: str) -> bool:
    """Whether *name* is a structural node rather than a model-backed one."""
    return name.startswith("mount_") or name in _POLICY_FREE_NODE_NAMES


async def _submitter(state: Any, phase: str) -> str:
    """A proposal submitter, required to compile the document phase machine."""
    return f"proposal-{phase}"


def _retry_policy_partition(graph: Any) -> tuple[set[str], set[str]]:
    """Split a compiled graph's nodes into policy-carrying and not."""
    carrying: set[str] = set()
    bare: set[str] = set()
    for name, node in graph.nodes.items():
        if name.startswith("__"):
            continue
        if _NODE_RETRY_POLICY in (getattr(node, "retry_policy", None) or ()):
            carrying.add(name)
        else:
            bare.add(name)
    return carrying, bare


@pytest.mark.asyncio(loop_scope="function")
async def test_every_model_backed_node_carries_the_production_retry_policy(
    pf: ProviderFactoryProtocol,
) -> None:
    """The policy proven above is the one compilation attaches to every real node.

    Without this the behavioural cases would describe a policy object that
    production might never reach a node with, which is the exact gap that let a
    configured retry sit inert for the whole life of the provider adapters.

    All four topologies are compiled, because the attachment is repeated per
    topology and a per-topology omission is invisible from any other one. An
    earlier form of this test looked only at the nodes named in ``agent_configs``,
    which covered three attachment sites out of eleven and would have passed with
    the supervisor and the entire document phase machine silently detached.
    """
    star = _make_team(
        topology=TopologyConfig(type=TopologyType.STAR),
        worker_ids=["vaultspec-plan-author", "vaultspec-coder"],
    )
    loop = _make_team(
        topology=TopologyConfig(
            type=TopologyType.PIPELINE_LOOP,
            order=["vaultspec-plan-author", "vaultspec-coder"],
            loop_node="vaultspec-coder",
        ),
        worker_ids=["vaultspec-plan-author", "vaultspec-coder"],
    )
    research_adr = load_team_config("vaultspec-adr-research-mock")

    cases: list[tuple[str, Any, dict[str, Any]]] = [
        ("pipeline", _pipeline_team(), {}),
        (
            "star",
            star,
            {"supervisor_agent_config": load_agent_config("vaultspec-supervisor")},
        ),
        ("pipeline_loop", loop, {}),
        ("research_adr", research_adr, {"proposal_submitter": _submitter}),
    ]

    for label, team, extra in cases:
        agent_configs = {
            w.agent_id: load_agent_config(w.agent_id) for w in team.workers
        }
        graph = compile_team_graph(
            team_config=team,
            agent_configs=agent_configs,
            provider_factory=pf,
            **extra,
            model_assignment=deterministic_model_assignment(team),
        )

        carrying, bare = _retry_policy_partition(graph)

        # Something model-backed compiled, so an empty graph cannot pass by
        # having nothing to check.
        assert carrying, f"{label} compiled no node carrying the retry policy"
        unexplained = {name for name in bare if not _policy_free_by_shape(name)}
        assert not unexplained, (
            f"{label} compiled {sorted(unexplained)} with no retry policy; either "
            "the attachment was missed or these are structural nodes that need "
            "declaring as policy-free"
        )


@pytest.mark.asyncio
async def test_research_producer_injects_scoped_conventions(tmp_path: Any) -> None:
    """The researcher's model turn receives the role-scoped bundled conventions.

    The researcher is the fourth research_adr document persona but runs through
    ``_make_research_producer`` (not ``_build_worker_messages``); this pins the
    behavior that wires the scoped document-authoring conventions into its turn so
    it is not conventions-blind.
    """
    from typing import cast

    from langchain_core.messages import AIMessage, BaseMessage
    from langchain_core.outputs import ChatGeneration, ChatResult

    captured: dict[str, list[BaseMessage]] = {}

    class _RecordingModel(FakeChatModel):
        @override
        async def _agenerate(
            self,
            messages: Any,
            stop: Any = None,
            run_manager: Any = None,
            **kwargs: Any,
        ) -> ChatResult:
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
    assert "Emission mechanics" in texts


# ---------------------------------------------------------------------------
# A turn that already streamed is never retried
# ---------------------------------------------------------------------------


class TestARetryNeverDuplicatesRelayedOutput:
    """A turn that already reached the client must not be run again.

    The node re-invokes the model on retry, so every token the lane already
    produced is relayed a second time and the user watches the same text arrive
    twice with nothing to explain it. The pair below is what distinguishes this
    guard from simply switching retry off: the SAME condition must still retry
    when nothing was relayed.
    """

    def _refusal(self, *, relayed: bool) -> tuple[WorkerExecutionError, AcpPromptError]:
        """A retryable provider refusal, wrapped as the worker node wraps it.

        The condition is resolved by the PRODUCTION mapper from the wire shape
        the adapter actually emits, then carried on the exception exactly as the
        lane carries it at its raise site - so the retryable-ness under test is
        the real one rather than a value this test chose.
        """
        wire = {
            "code": -32603,
            "message": "provider is over capacity",
            "data": {"errorKind": "overloaded"},
        }
        cause = AcpPromptError(
            "provider is over capacity",
            code=-32603,
            data={"errorKind": "overloaded"},
            condition=condition_from_acp_error(wire),
        )
        wrapped = WorkerExecutionError(
            worker="researcher",
            model="claude/sonnet",
            message_count=3,
            cause=cause,
            relayed_output=relayed,
        )
        wrapped.__cause__ = cause
        return wrapped, cause

    def test_a_refusal_after_output_is_not_retried(self) -> None:
        """Streamed output outranks a retryable condition."""
        failure, cause = self._refusal(relayed=True)
        # The condition itself is retryable - that is the point. Retry is
        # refused because of what the attempt already sent, not what refused it.
        assert cause.condition == ProviderCondition.PROVIDER_OVERLOADED
        assert condition_is_retryable(ProviderCondition.PROVIDER_OVERLOADED) is True
        assert _worker_retry_on(failure) is False

    def test_the_same_refusal_is_retried_when_nothing_was_relayed(self) -> None:
        """Without the companion, the guard is indistinguishable from off."""
        failure, _cause = self._refusal(relayed=False)
        assert _worker_retry_on(failure) is True

    def test_streamed_output_outranks_a_lane_hint_that_says_retry(self) -> None:
        """A vendor cannot consent to duplicated output on the user's behalf.

        The hint is the provider's verdict on ITS failure; the duplication is
        harm we would cause. So this is the one axis that outranks a stated
        hint, and the ordering is asserted rather than left to reading order.
        """
        cause = _turn_failure(
            {"message": "stream died", "codexErrorInfo": "responseStreamDisconnected"},
            will_retry=True,
        )
        wrapped = WorkerExecutionError(
            worker="researcher",
            model="codex/gpt",
            message_count=3,
            cause=cause,
            relayed_output=True,
        )
        wrapped.__cause__ = cause
        assert _worker_retry_on(wrapped) is False
