"""LangGraph orchestration engine for agent teams.

Compiles a ``StateGraph`` from a ``TeamConfig`` and resolved ``AgentConfig``
map.  Three topology types are supported (ADR-013 §2.5):

- ``star``:          supervisor routes dynamically; workers report back to
                     the supervisor.
- ``pipeline``:      fixed sequential chain; no supervisor required.
- ``pipeline_loop``: sequential chain where the loop_node conditionally
                     routes back into the loop or finishes.
"""

from pathlib import Path
from typing import Any, cast

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph

from ..providers.factory import ProviderFactory
from ..utils.enums import Model, Provider
from .nodes.supervisor import create_supervisor_node
from .nodes.worker import create_worker_node
from .state import TeamState
from .team_config import AgentConfig, TeamConfig, WorkerRef


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


def compile_team_graph(
    team_config: TeamConfig,
    agent_configs: dict[str, AgentConfig],
    checkpointer: AsyncSqliteSaver | None = None,
    supervisor_agent_config: AgentConfig | None = None,
    workspace_root: Path | None = None,
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

    Returns:
        The compiled StateGraph runnable.

    Raises:
        KeyError: If a worker agent_id from team_config is not in agent_configs.
        ValueError: If an unknown topology type is encountered.
    """
    builder = StateGraph(cast(Any, TeamState))
    topology = team_config.topology

    # Collect interrupt_before nodes (ADR-013 §2.7):
    # Any agent with a non-empty require_approval_for list gets its node interrupted.
    interrupt_nodes: list[str] = [
        agent_configs[w.agent_id].id
        for w in team_config.workers
        if w.agent_id in agent_configs
        and agent_configs[w.agent_id].permissions.require_approval_for
    ]

    if topology.type == "star":
        _compile_star(
            builder, team_config, agent_configs, supervisor_agent_config, workspace_root
        )
    elif topology.type == "pipeline":
        _compile_pipeline(builder, team_config, agent_configs, workspace_root)
    elif topology.type == "pipeline_loop":
        _compile_pipeline_loop(
            builder, team_config, agent_configs, supervisor_agent_config, workspace_root
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


def _compile_star(
    builder: StateGraph,
    team_config: TeamConfig,
    agent_configs: dict[str, AgentConfig],
    supervisor_agent_config: AgentConfig | None,
    workspace_root: Path | None = None,
) -> None:
    """Wire up a star topology: supervisor -> workers -> supervisor -> END.

    ADR-013 §2.5 star spec.
    """
    worker_ids: list[str] = [w.agent_id for w in team_config.workers]
    resolved_agents = [agent_configs[wid] for wid in worker_ids if wid in agent_configs]

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
    builder.add_node("supervisor", supervisor_node, metadata=sv_meta)  # type: ignore[arg-type]
    builder.add_edge(START, "supervisor")

    for worker_ref in team_config.workers:
        agent_cfg = agent_configs[worker_ref.agent_id]
        model = _resolve_model_for_worker(
            worker_ref,
            agent_cfg,
            team_config,
            workspace_root,
        )
        worker_node = create_worker_node(
            model, agent_cfg.persona.system_prompt, name=agent_cfg.id
        )
        builder.add_node(
            agent_cfg.id,
            worker_node,  # type: ignore[arg-type]
            metadata={
                "display_name": agent_cfg.display_name,
                "role": agent_cfg.role,
                "description": agent_cfg.description.strip(),
            },
        )
        builder.add_edge(agent_cfg.id, "supervisor")

    route_map: dict[str, str] = {wid: wid for wid in worker_ids}
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
) -> None:
    """Wire up a pipeline topology: START -> node[0] -> node[1] -> ... -> END.

    ADR-013 §2.5 pipeline spec. No supervisor node.
    Uses explicit add_edge calls (not add_sequence) because nodes are added
    with metadata via add_node first.
    """
    order = team_config.topology.order
    node_names: list[str] = []

    for agent_id in order:
        agent_cfg = agent_configs[agent_id]
        worker_ref = next(w for w in team_config.workers if w.agent_id == agent_id)
        model = _resolve_model_for_worker(
            worker_ref,
            agent_cfg,
            team_config,
            workspace_root,
        )
        worker_node = create_worker_node(
            model, agent_cfg.persona.system_prompt, name=agent_cfg.id
        )
        builder.add_node(
            agent_cfg.id,
            worker_node,  # type: ignore[arg-type]
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


def _compile_pipeline_loop(
    builder: StateGraph,
    team_config: TeamConfig,
    agent_configs: dict[str, AgentConfig],
    supervisor_agent_config: AgentConfig | None,
    workspace_root: Path | None = None,
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
        raise ValueError("pipeline_loop topology requires loop_node to be set")

    pre_loop = [aid for aid in order if aid != loop_node_id]

    for agent_id in order:
        agent_cfg = agent_configs[agent_id]
        worker_ref = next(w for w in team_config.workers if w.agent_id == agent_id)
        model = _resolve_model_for_worker(
            worker_ref,
            agent_cfg,
            team_config,
            workspace_root,
        )
        worker_node = create_worker_node(
            model, agent_cfg.persona.system_prompt, name=agent_cfg.id
        )

        if agent_id == loop_node_id:
            # Wrap the loop node so it increments loop_count on every pass.
            # The plain worker_node returns {"messages": [...]}.  We merge in
            # the updated counter so _loop_router sees a monotonically increasing
            # value and can enforce max_loops (ADR-013 §5).
            _inner = worker_node

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
            node_fn,  # type: ignore[arg-type]
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
    max_loops = team_config.topology.max_loops

    def _loop_router(state: TeamState) -> str:
        """Route loop_node output: enforce max_loops guard.

        Defaults to "revise" (continue loop) when the worker does not
        explicitly set ``next``.  Workers signal loop exit by returning
        ``next="FINISH"``; the max_loops guard forces FINISH regardless.
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
