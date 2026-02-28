"""LangGraph orchestration engine for agent teams.

Compiles a ``StateGraph`` from a ``TeamConfig`` and resolved ``AgentConfig``
map.  Three topology types are supported (ADR-013 §2.5):

- ``star``:          supervisor routes dynamically; workers report back to
                     the supervisor.
- ``pipeline``:      fixed sequential chain; no supervisor required.
- ``pipeline_loop``: sequential chain where the loop_node conditionally
                     routes back into the loop or finishes.
"""

import functools
import logging

from pathlib import Path
from typing import Any, cast

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph

from ..providers.factory import ProviderFactory
from ..utils.enums import Model, Provider
from .exceptions import ConfigError
from .nodes.supervisor import create_supervisor_node
from .nodes.worker import create_worker_node
from .state import TeamState
from .team_config import AgentConfig, TeamConfig, TopologyType, WorkerRef


logger = logging.getLogger(__name__)


__all__ = ["compile_team_graph"]


def _resolve_model_for_worker(
    worker_ref: WorkerRef,
    agent_config: AgentConfig,
    team_config: TeamConfig,
    workspace_root: Path | None = None,
) -> BaseChatModel:
    """Resolve provider + capability following ADR-013 §2.3 precedence.

    Priority (highest to lowest):
    1. [[team.workers]] model.* override
    2. agent TOML [agent.model].*
    3. [team.defaults].*
    """
    provider: Provider = (
        worker_ref.model.provider
        or agent_config.model.provider
        or team_config.defaults.provider
        or Provider.CLAUDE
    )
    capability: Model | None = (
        worker_ref.model.capability
        or agent_config.model.capability
        or team_config.defaults.capability
    )
    return ProviderFactory.create(
        provider,
        model=capability,
        agent_config=agent_config,
        workspace_root=workspace_root,
    )


def _resolve_supervisor_model(
    team_config: TeamConfig,
    workspace_root: Path | None = None,
) -> BaseChatModel:
    """Resolve the supervisor model from team config."""
    provider: Provider = (
        team_config.supervisor.provider
        or team_config.defaults.provider
        or Provider.CLAUDE
    )
    capability: Model = team_config.supervisor.capability or Model.MAX
    return ProviderFactory.create(
        provider, model=capability, workspace_root=workspace_root
    )


def _build_supervisor_prompt(
    resolved_agents: list[AgentConfig],
    base_prompt: str,
) -> str:
    """Inject the agent roster into the supervisor system prompt.

    Replaces ``{{AGENT_ROSTER}}`` placeholder if present, otherwise appends
    the roster to the base prompt (ADR-013 §2.6).
    """
    roster = "\n".join(
        f"- {cfg.display_name} ({cfg.id}): {cfg.description.strip()}"
        for cfg in resolved_agents
    )
    if "{{AGENT_ROSTER}}" in base_prompt:
        return base_prompt.replace("{{AGENT_ROSTER}}", roster)
    return base_prompt + f"\n\nYour team members and their specializations:\n{roster}"


def compile_team_graph(  # noqa: PLR0913
    team_config: TeamConfig,
    agent_configs: dict[str, AgentConfig],
    checkpointer: AsyncSqliteSaver | None = None,
    supervisor_agent_config: AgentConfig | None = None,
    workspace_root: Path | None = None,
    autonomous: bool = False,
) -> Any:  # noqa: ANN401
    """Compile the LangGraph orchestration engine from a TeamConfig.

    Supports three topology types (ADR-013 §2.5):

    - ``star``:          Dynamic supervisor routing.
    - ``pipeline``:      Fixed sequential chain (no supervisor).
    - ``pipeline_loop``: Sequential chain with conditional back-edge.

    Args:
        team_config:             Validated team preset (loaded from TOML).
        agent_configs:           Mapping of agent_id -> AgentConfig for all
                                 workers referenced in the team.
        checkpointer:            Optional SQLite checkpointer for state
                                 persistence.
        supervisor_agent_config: Optional AgentConfig for the supervisor node.
                                 Only used for star/pipeline_loop topologies.
        workspace_root:          Optional workspace root for ACP CWD scoping
                                 (ADR-014 §2.7).
        autonomous:              When True, skip permission_callback wiring so
                                 ACP models auto-approve tool calls (headless
                                 MCP-launched runs).

    Returns:
        The compiled StateGraph runnable.

    Raises:
        ConfigError: If a worker agent_id from team_config is not in agent_configs,
                     or if topology configuration is invalid.
        ValueError:  If an unknown topology type is encountered.
    """
    builder = StateGraph(cast(Any, TeamState))
    topology = team_config.topology

    # M3: validate topology_type is a known TopologyType enum value before dispatch.
    if not isinstance(topology.type, TopologyType):
        raise ValueError(
            f"Unknown topology type: {topology.type!r}. "
            f"Expected one of: {[t.value for t in TopologyType]}"
        )

    # interrupt_before disabled: approval flows via interrupt() inside the node only
    # (ADR-013 §2.7 superseded by plan 2026-28-02).
    interrupt_nodes: list[str] = []

    if topology.type == TopologyType.STAR:
        _compile_star(
            builder,
            team_config,
            agent_configs,
            supervisor_agent_config,
            workspace_root,
            autonomous=autonomous,
        )
    elif topology.type == TopologyType.PIPELINE:
        _compile_pipeline(
            builder, team_config, agent_configs, workspace_root, autonomous=autonomous
        )
    elif topology.type == TopologyType.PIPELINE_LOOP:
        _compile_pipeline_loop(
            builder,
            team_config,
            agent_configs,
            supervisor_agent_config,
            workspace_root,
            autonomous=autonomous,
        )
    else:
        raise ValueError(
            f"Unknown topology type: {topology.type!r}. "
            "Expected 'star', 'pipeline', or 'pipeline_loop'."
        )

    return builder.compile(
        checkpointer=checkpointer,
        interrupt_before=interrupt_nodes,
    )


def _compile_star(  # noqa: PLR0913
    builder: StateGraph,
    team_config: TeamConfig,
    agent_configs: dict[str, AgentConfig],
    supervisor_agent_config: AgentConfig | None,
    workspace_root: Path | None = None,
    autonomous: bool = False,
) -> None:
    """Wire up a star topology: supervisor -> workers -> supervisor -> END.

    ADR-013 §2.5 star spec.
    """
    worker_ids: list[str] = [w.agent_id for w in team_config.workers]
    resolved_agents = [agent_configs[wid] for wid in worker_ids if wid in agent_configs]

    # M2: validate supervisor agent exists in agent_configs when a supervisor
    # AgentConfig is expected (star topology always uses a supervisor).
    # supervisor_agent_config is optional only to allow test/minimal setups;
    # when provided it must be a proper AgentConfig (no further check needed).
    # The supervisor model itself is always resolved from team_config defaults.

    supervisor_model = _resolve_supervisor_model(team_config, workspace_root)

    if supervisor_agent_config is not None:
        supervisor_prompt = _build_supervisor_prompt(
            resolved_agents, supervisor_agent_config.persona.system_prompt
        )
        sv_meta: dict[str, str] = {
            "display_name": supervisor_agent_config.display_name,
            "role": "supervisor",
            "description": supervisor_agent_config.description.strip(),
        }
    else:
        roster = "\n".join(
            f"- {cfg.display_name} ({cfg.id}): {cfg.description.strip()}"
            for cfg in resolved_agents
        )
        supervisor_prompt = (
            "You are a supervisor managing a team of expert assistants.\n"
            f"Your team members and their specializations:\n{roster}\n\n"
            "Review the recent messages, identify what needs to be done, "
            "and decide who should act next to progress the goal. "
            "When the goal is fully achieved, respond with FINISH."
        )
        sv_meta = {
            "display_name": "Supervisor",
            "role": "supervisor",
            "description": "Routes tasks to the appropriate specialist.",
        }

    supervisor_node = create_supervisor_node(
        model=supervisor_model,
        system_prompt=supervisor_prompt,
        workers=worker_ids,
    )
    builder.add_node("supervisor", supervisor_node, metadata=sv_meta)
    builder.add_edge(START, "supervisor")

    compiled_worker_ids: list[str] = []
    for worker_ref in team_config.workers:
        if worker_ref.agent_id not in agent_configs:
            # H6: log a warning instead of raising so partial teams can still run.
            logger.warning(
                "Worker %r is listed in team %r but has no resolved AgentConfig "
                "— skipping this worker node.",
                worker_ref.agent_id,
                team_config.id,
            )
            continue
        agent_cfg = agent_configs[worker_ref.agent_id]
        model = _resolve_model_for_worker(
            worker_ref,
            agent_cfg,
            team_config,
            workspace_root,
        )
        worker_node = create_worker_node(
            model,
            agent_cfg.persona.system_prompt,
            name=agent_cfg.id,
            autonomous=autonomous,
        )
        builder.add_node(
            agent_cfg.id,
            worker_node,
            metadata={
                "display_name": agent_cfg.display_name,
                "role": agent_cfg.role,
                "description": agent_cfg.description.strip(),
            },
        )
        builder.add_edge(agent_cfg.id, "supervisor")
        compiled_worker_ids.append(agent_cfg.id)

    # M3: fail fast if no workers compiled — a supervisor with zero routes
    # produces a trivially useless graph.
    if not compiled_worker_ids:
        raise ValueError(
            f"Star topology for team {team_config.id!r} has zero compiled workers. "
            "All worker AgentConfigs are missing or unresolvable."
        )

    route_map: dict[str, str] = {wid: wid for wid in compiled_worker_ids}
    route_map["FINISH"] = END
    builder.add_conditional_edges(
        "supervisor",
        lambda state: state["next"],
        route_map,  # type: ignore[arg-type]
    )


def _compile_pipeline(
    builder: StateGraph,
    team_config: TeamConfig,
    agent_configs: dict[str, AgentConfig],
    workspace_root: Path | None = None,
    autonomous: bool = False,
) -> None:
    """Wire up a pipeline topology: START -> node[0] -> node[1] -> ... -> END.

    ADR-013 §2.5 pipeline spec. No supervisor node.
    Uses explicit add_edge calls (not add_sequence) because nodes are added
    with metadata via add_node first.
    """
    order = team_config.topology.order

    # M5: validate pipeline_order is non-empty before iterating.
    if not order:
        raise ConfigError(
            f"Pipeline topology for team {team_config.id!r} has an empty "
            "pipeline_order. At least one agent must be listed in topology.order."
        )

    # L3: validate no duplicate entries in pipeline_order.
    if len(order) != len(set(order)):
        seen_set: set[str] = set()
        dupes_list = [a for a in order if a in seen_set or seen_set.add(a)]  # type: ignore[func-returns-value]
        raise ConfigError(
            f"Pipeline order for team {team_config.id!r} has duplicate entries: "
            f"{dupes_list}. Each agent may appear at most once."
        )

    node_names: list[str] = []

    for agent_id in order:
        # C2: descriptive error when agent_id is missing from agent_configs.
        if agent_id not in agent_configs:
            raise ConfigError(
                f"Agent '{agent_id}' referenced in pipeline_order but not defined "
                "in agent_configs. Ensure the agent TOML exists and is loaded "
                "before compiling the graph."
            )
        agent_cfg = agent_configs[agent_id]
        # H1: use next() with a sentinel to avoid bare StopIteration
        worker_ref = next(
            (w for w in team_config.workers if w.agent_id == agent_id), None
        )
        if worker_ref is None:
            raise ValueError(
                f"Pipeline node {agent_id!r} has no matching WorkerRef in "
                f"team {team_config.id!r}."
            )
        model = _resolve_model_for_worker(
            worker_ref,
            agent_cfg,
            team_config,
            workspace_root,
        )
        worker_node = create_worker_node(
            model,
            agent_cfg.persona.system_prompt,
            name=agent_cfg.id,
            autonomous=autonomous,
        )
        builder.add_node(
            agent_cfg.id,
            worker_node,
            metadata={
                "display_name": agent_cfg.display_name,
                "role": agent_cfg.role,
                "description": agent_cfg.description.strip(),
            },
        )
        node_names.append(agent_cfg.id)

    builder.add_edge(START, node_names[0])
    for i in range(len(node_names) - 1):
        builder.add_edge(node_names[i], node_names[i + 1])
    builder.add_edge(node_names[-1], END)


def _compile_pipeline_loop(  # noqa: PLR0913
    builder: StateGraph,
    team_config: TeamConfig,
    agent_configs: dict[str, AgentConfig],
    supervisor_agent_config: AgentConfig | None,
    workspace_root: Path | None = None,
    autonomous: bool = False,
) -> None:
    """Wire up a pipeline_loop topology.

    ADR-013 §2.5 pipeline_loop spec:
    - pre_loop nodes run sequentially, wired via explicit add_edge calls.
    - loop_node gets a conditional edge: revise -> last pre-loop node | FINISH -> END.
    - max_loops guard uses TeamState.loop_count.
    """
    order = team_config.topology.order
    loop_node_id = team_config.topology.loop_node
    if loop_node_id is None:
        raise ConfigError("pipeline_loop topology requires loop_node to be set")

    # L3: check for duplicate entries in pipeline_order before processing.
    if len(order) != len(set(order)):
        seen: set[str] = set()
        dupes = [a for a in order if a in seen or seen.add(a)]  # type: ignore[func-returns-value]
        raise ConfigError(
            f"pipeline_loop order for team {team_config.id!r} has duplicate "
            f"entries: {dupes}. Each agent may appear at most once."
        )

    # H3: validate that pipeline_loop has at least 2 agents to avoid a
    # degenerate single-node self-loop that consumes max_loops iterations
    # without meaningful work.
    pre_loop = [aid for aid in order if aid != loop_node_id]
    if not pre_loop:
        raise ConfigError(
            f"Pipeline_loop for team {team_config.id!r} requires at least one "
            f"pre-loop stage in addition to the loop_node {loop_node_id!r}. "
            "A single-agent pipeline_loop is a degenerate self-loop — use "
            "topology.type='pipeline' for single-agent sequential runs."
        )

    # H7: validate loop_node is in the agent_configs before we try to compile it.
    worker_names = {w.agent_id for w in team_config.workers}
    if loop_node_id not in worker_names:
        raise ConfigError(
            f"pipeline_loop loop_node {loop_node_id!r} is not a known worker "
            f"in team {team_config.id!r}. Known workers: {sorted(worker_names)}"
        )
    if loop_node_id not in agent_configs:
        raise ConfigError(
            f"pipeline_loop loop_node {loop_node_id!r} has no resolved AgentConfig. "
            "Ensure the agent TOML exists and is loaded before compiling the graph."
        )

    for agent_id in order:
        # C2: descriptive error when agent_id is missing from agent_configs.
        if agent_id not in agent_configs:
            raise ConfigError(
                f"Agent '{agent_id}' referenced in pipeline_loop order but not "
                "defined in agent_configs. Ensure the agent TOML exists and is "
                "loaded before compiling the graph."
            )
        agent_cfg = agent_configs[agent_id]
        # H1: use next() with a sentinel to avoid bare StopIteration
        worker_ref = next(
            (w for w in team_config.workers if w.agent_id == agent_id), None
        )
        if worker_ref is None:
            raise ConfigError(
                f"Pipeline-loop node {agent_id!r} has no matching WorkerRef in "
                f"team {team_config.id!r}."
            )
        model = _resolve_model_for_worker(
            worker_ref,
            agent_cfg,
            team_config,
            workspace_root,
        )
        # M8: snapshot the needed config at closure creation time to avoid
        # capturing the mutable agent_configs dict by reference.
        agent_system_prompt = agent_cfg.persona.system_prompt
        agent_node_name = agent_cfg.id
        worker_node = create_worker_node(
            model,
            agent_system_prompt,
            name=agent_node_name,
            autonomous=autonomous,
        )

        if agent_id == loop_node_id:
            # Wrap the loop node so it increments loop_count on every pass.
            # The plain worker_node returns {"messages": [...]}.  We merge in
            # the updated counter so _loop_router sees a monotonically increasing
            # value and can enforce max_loops (ADR-013 §5).
            # H1: use functools.wraps to preserve the original __name__ so that
            # LangGraph node identification remains correct.
            _inner = worker_node

            @functools.wraps(_inner)
            async def _loop_node_with_counter(
                state: TeamState,
                _inner: Any = _inner,  # noqa: ANN401
            ) -> dict[str, Any]:
                result = await _inner(state)
                result["loop_count"] = state.get("loop_count", 0) + 1
                return result

            node_fn = _loop_node_with_counter
        else:
            node_fn = worker_node

        builder.add_node(
            agent_cfg.id,
            node_fn,
            metadata={
                "display_name": agent_cfg.display_name,
                "role": agent_cfg.role,
                "description": agent_cfg.description.strip(),
            },
        )

    all_sequential: list[str] = [*pre_loop, loop_node_id]
    builder.add_edge(START, all_sequential[0])
    # Wire consecutive edges manually (add_sequence requires unregistered nodes)
    for i in range(len(all_sequential) - 1):
        builder.add_edge(all_sequential[i], all_sequential[i + 1])

    loop_target: str = pre_loop[-1] if pre_loop else all_sequential[0]
    # L2: max_loops default is 3 (set in TopologyConfig), range 1–100.
    # Enforced in TopologyConfig via Field(ge=1, le=100).
    max_loops = team_config.topology.max_loops

    def _loop_router(state: TeamState) -> str:
        """Route loop_node output: enforce max_loops guard.

        Returns ``"FINISH"`` when ``loop_count >= max_loops`` (hard cap).
        When below the cap, returns the value of ``state["next"]`` if set
        by the worker node, or ``"revise"`` as the default (continue the loop).
        Workers can signal early exit by setting ``next="FINISH"`` in their
        return dict — the router routes to END in that case.

        L1: max_loops default (3) is documented in TopologyConfig.
        """
        loop_count = state.get("loop_count", 0)
        if loop_count >= max_loops:
            return "FINISH"
        return state.get("next", "revise")

    builder.add_conditional_edges(
        loop_node_id,
        _loop_router,
        {"revise": loop_target, "FINISH": END},
    )
