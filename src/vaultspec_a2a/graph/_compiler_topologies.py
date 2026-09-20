"""Star, pipeline, and loop topology builders."""

from __future__ import annotations

import functools
import logging
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Hashable
    from pathlib import Path

    # Annotation-only: importing langchain_core.language_models at module scope
    # costs seconds (it eagerly probes for transformers), and the compiler only
    # names BaseChatModel in signatures — the instances it wires come from the
    # provider factory, which imports the model stack at construction time.
    from langchain_core.language_models import BaseChatModel
    from langchain_core.runnables import RunnableConfig

    from ..worker.authoring_binding import AuthoringBindingProvider
    from .nodes.worker import WorkerNode
    from .protocols import CostPort, ProviderFactoryProtocol, TaskQueuePort

from langgraph.graph import START, StateGraph
from langgraph.types import Command

from ..thread.errors import (
    ConfigError,
)
from ..thread.state import (
    TeamState,  # noqa: TC001 - LangGraph inspects route annotations
)
from ._compiler_retry import _NODE_RETRY_POLICY
from .compiler import (
    _ROLE_TO_PHASE,
    _add_node,
    _build_supervisor_prompt,
    _compile_worker_node,
    _compose_persona_prompt,
    _lane_web_demonstrated,
    _loop_route,
    _resolve_supervisor_model,
    _route_from_supervisor,
)
from .nodes._config_contract import accepting_runnable_config
from .nodes.action_completion import GRAPH_COMPLETION_NODE
from .nodes.supervisor import create_plan_approval_node, create_supervisor_node
from .nodes.vault_reader import create_mount_node

__all__ = ["_compile_pipeline", "_compile_pipeline_loop", "_compile_star"]

logger = logging.getLogger("vaultspec_a2a.graph.compiler")


def _star_supervisor_presentation(
    supervisor_agent_config: Any | None,
    supervisor_model: BaseChatModel,
    resolved_agents: list[Any],
    team_config: Any,
    sv_assignment: dict[str, str],
) -> tuple[str, dict[str, str]]:
    if supervisor_agent_config is not None:
        # Routed through the same composition as a worker so a supervisor persona
        # marking the spot cannot ship a literal placeholder to a model; the role
        # authors no document, so what it resolves to is always the disclaimer.
        supervisor_prompt = _build_supervisor_prompt(
            resolved_agents,
            _compose_persona_prompt(
                supervisor_agent_config.persona.system_prompt,
                role="supervisor",
                demonstrated=_lane_web_demonstrated(supervisor_model),
            ),
            directive=team_config.persona.directive,
        )
        sv_display_name = (
            team_config.persona.supervisor_display_name
            or supervisor_agent_config.display_name
        )
        sv_meta: dict[str, str] = {
            "display_name": sv_display_name,
            "role": "supervisor",
            "description": supervisor_agent_config.description.strip(),
            **sv_assignment,
        }
    else:
        _fallback_base = (
            "You are a supervisor managing a team of expert assistants.\n"
            "{{AGENT_ROSTER}}\n\n"
            "Review the recent messages, identify what needs to be done, "
            "and decide who should act next to progress the goal. "
            "When the goal is fully achieved, respond with FINISH."
        )
        supervisor_prompt = _build_supervisor_prompt(
            resolved_agents,
            _fallback_base,
            directive=team_config.persona.directive,
        )
        sv_meta = {
            "display_name": "Supervisor",
            "role": "supervisor",
            "description": "Routes tasks to the appropriate specialist.",
            **sv_assignment,
        }
    return supervisor_prompt, sv_meta


def _route_from_plan_approval(state: TeamState) -> str:
    next_route = state.get("next")
    if next_route is None:
        raise ConfigError(
            "plan_approval routing invariant broken: 'next' was not set "
            "before the plan_approval->route edge ran"
        )
    return next_route


def _star_worker_context(
    team_config: Any, agent_configs: dict[str, Any]
) -> tuple[list[str], list[Any], dict[str, str]]:
    worker_ids = [worker.agent_id for worker in team_config.workers]
    resolved_agents = [agent_configs[wid] for wid in worker_ids if wid in agent_configs]
    worker_phase_map = {
        cfg.id: _ROLE_TO_PHASE[cfg.role]
        for cfg in resolved_agents
        if cfg.role in _ROLE_TO_PHASE
    }
    return worker_ids, resolved_agents, worker_phase_map


def _compile_star(
    builder: StateGraph[Any, None, Any, Any],
    team_config: Any,
    agent_configs: dict[str, Any],
    supervisor_agent_config: Any | None,
    *,
    provider_factory: ProviderFactoryProtocol,
    workspace_root: Path | None = None,
    autonomous: bool = False,
    feature_tag: str | None = None,
    task_queue_port: TaskQueuePort | None = None,
    cost_port: CostPort | None = None,
    authoring_binding_provider: AuthoringBindingProvider | None = None,
    frozen_assignment: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Wire up a star topology: supervisor -> workers -> supervisor -> END."""
    worker_ids, resolved_agents, worker_phase_map = _star_worker_context(
        team_config, agent_configs
    )

    supervisor_model, sv_provider, sv_model_name = _resolve_supervisor_model(
        workspace_root,
        provider_factory=provider_factory,
        supervisor_agent_config=supervisor_agent_config,
        frozen_assignment=frozen_assignment,
    )
    sv_assignment = {"provider": sv_provider.value, "model_name": sv_model_name}

    supervisor_prompt, sv_meta = _star_supervisor_presentation(
        supervisor_agent_config,
        supervisor_model,
        resolved_agents,
        team_config,
        sv_assignment,
    )

    supervisor_node = create_supervisor_node(
        model=supervisor_model,
        system_prompt=supervisor_prompt,
        workers=worker_ids,
        worker_phase_map=worker_phase_map or None,
        autonomous=autonomous,
        workspace_root=workspace_root,
    )
    _add_node(
        builder,
        "supervisor",
        supervisor_node,
        metadata=sv_meta,
        retry_policy=_NODE_RETRY_POLICY,
    )
    builder.add_edge(START, "supervisor")

    compiled_worker_ids: list[str] = []
    for worker_ref in team_config.workers:
        if worker_ref.agent_id not in agent_configs:
            raise ConfigError(
                f"Worker {worker_ref.agent_id!r} is listed in team "
                f"{team_config.id!r} but has no resolved AgentConfig. "
                f"Ensure the agent TOML exists and is loaded."
            )
        agent_cfg = agent_configs[worker_ref.agent_id]
        worker_node, node_metadata = _compile_worker_node(
            worker_ref,
            agent_cfg,
            team_config,
            workspace_root,
            provider_factory=provider_factory,
            frozen_assignment=frozen_assignment,
            autonomous=autonomous,
            feature_tag=feature_tag,
            task_queue_port=task_queue_port,
            cost_port=cost_port,
            authoring_binding_provider=authoring_binding_provider,
        )
        _add_node(
            builder,
            agent_cfg.id,
            worker_node,
            metadata=node_metadata,
            retry_policy=_NODE_RETRY_POLICY,
        )
        builder.add_edge(agent_cfg.id, "supervisor")
        # Insert mount node between supervisor routing and worker invocation.
        mount_fn = create_mount_node(workspace_root, task_queue_port)
        _add_node(builder, f"mount_{agent_cfg.id}", mount_fn)
        builder.add_edge(f"mount_{agent_cfg.id}", agent_cfg.id)
        compiled_worker_ids.append(agent_cfg.id)

    # M3: fail fast if no workers compiled -- a supervisor with zero routes
    # produces a trivially useless graph.
    if not compiled_worker_ids:
        raise ValueError(
            f"Star topology for team {team_config.id!r} has zero compiled workers. "
            "All worker AgentConfigs are missing or unresolvable."
        )

    # The dedicated approval node owns the plan-approval
    # interrupt; the supervisor only marks approval_status="pending". The node
    # is replay-safe because nothing before its interrupt() has side effects.
    approval_node = create_plan_approval_node(
        compiled_worker_ids, worker_phase_map or None
    )
    _add_node(
        builder,
        "plan_approval",
        approval_node,
        metadata={
            "display_name": "Plan Approval",
            "role": "gate",
            "description": "Pauses for human plan approval before execution.",
        },
    )

    # Supervisor routes to mount_{wid} which then edges to wid.
    route_map: dict[str, str] = {wid: f"mount_{wid}" for wid in compiled_worker_ids}
    route_map["FINISH"] = GRAPH_COMPLETION_NODE

    supervisor_route_map = {**route_map, "plan_approval": "plan_approval"}
    builder.add_conditional_edges(
        "supervisor",
        _route_from_supervisor,
        cast("dict[Hashable, str]", supervisor_route_map),
    )

    # Approved -> exec worker's mount; rejected -> revision worker's mount.
    builder.add_conditional_edges(
        "plan_approval",
        _route_from_plan_approval,
        cast("dict[Hashable, str]", route_map),
    )


def _validated_pipeline_order(team_config: Any) -> list[str]:
    order = team_config.topology.order

    # M5: validate pipeline_order is non-empty before iterating.
    if not order:
        raise ConfigError(
            f"Pipeline topology for team {team_config.id!r} has an empty "
            "pipeline_order. At least one agent must be listed in topology.order."
        )

    if len(order) != len(set(order)):
        seen_set: set[str] = set()
        dupes_list: list[str] = []
        for a in order:
            if a in seen_set:
                dupes_list.append(a)
            else:
                seen_set.add(a)
        raise ConfigError(
            f"Pipeline order for team {team_config.id!r} has duplicate entries: "
            f"{dupes_list}. Each agent may appear at most once."
        )
    return order


def _compile_pipeline(
    builder: StateGraph[Any, None, Any, Any],
    team_config: Any,
    agent_configs: dict[str, Any],
    *,
    provider_factory: ProviderFactoryProtocol,
    workspace_root: Path | None = None,
    autonomous: bool = False,
    feature_tag: str | None = None,
    task_queue_port: TaskQueuePort | None = None,
    cost_port: CostPort | None = None,
    authoring_binding_provider: AuthoringBindingProvider | None = None,
    frozen_assignment: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Wire up a pipeline topology: START -> node[0] -> node[1] -> ... -> END.

    No supervisor node.
    """
    order = _validated_pipeline_order(team_config)

    node_names: list[str] = []
    mount_names: list[str] = []

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
        worker_node, node_metadata = _compile_worker_node(
            worker_ref,
            agent_cfg,
            team_config,
            workspace_root,
            provider_factory=provider_factory,
            frozen_assignment=frozen_assignment,
            autonomous=autonomous,
            feature_tag=feature_tag,
            task_queue_port=task_queue_port,
            cost_port=cost_port,
            authoring_binding_provider=authoring_binding_provider,
        )
        # Insert mount node between pipeline stages.
        mount_fn = create_mount_node(workspace_root, task_queue_port)
        mount_id = f"mount_{agent_cfg.id}"
        _add_node(builder, mount_id, mount_fn)
        _add_node(
            builder,
            agent_cfg.id,
            worker_node,
            metadata=node_metadata,
            retry_policy=_NODE_RETRY_POLICY,
        )
        builder.add_edge(mount_id, agent_cfg.id)
        node_names.append(agent_cfg.id)
        mount_names.append(mount_id)

    # Wire: START -> mount_0 -> node_0 -> mount_1 -> node_1 -> ... -> END
    builder.add_edge(START, mount_names[0])
    for i in range(len(node_names) - 1):
        builder.add_edge(node_names[i], mount_names[i + 1])
    builder.add_edge(node_names[-1], GRAPH_COMPLETION_NODE)


def _duplicate_order_entries(order: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for agent_id in order:
        if agent_id in seen:
            duplicates.append(agent_id)
        else:
            seen.add(agent_id)
    return duplicates


def _validate_pipeline_loop_config(
    team_config: Any,
    agent_configs: dict[str, Any],
) -> tuple[str, list[str]]:
    """Validate pipeline_loop topology configuration.

    Returns ``(loop_node_id, pre_loop)`` on success.

    Raises:
        ConfigError: On any validation failure.
    """
    order = team_config.topology.order
    loop_node_id = team_config.topology.loop_node
    if loop_node_id is None:
        raise ConfigError("pipeline_loop topology requires loop_node to be set")

    if len(order) != len(set(order)):
        dupes = _duplicate_order_entries(order)
        raise ConfigError(
            f"pipeline_loop order for team {team_config.id!r} has duplicate "
            f"entries: {dupes}. Each agent may appear at most once."
        )

    pre_loop = [aid for aid in order if aid != loop_node_id]
    if not pre_loop:
        raise ConfigError(
            f"Pipeline_loop for team {team_config.id!r} requires at least one "
            f"pre-loop stage in addition to the loop_node {loop_node_id!r}. "
            "A single-agent pipeline_loop is a degenerate self-loop -- use "
            "topology.type='pipeline' for single-agent sequential runs."
        )

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

    return loop_node_id, pre_loop


def _wrap_loop_node(worker_node: WorkerNode) -> WorkerNode:
    """Wrap a worker node to increment ``loop_count`` on every pass.

    The plain worker returns ``{"messages": [...]}``.  This wrapper merges in
    the updated counter so ``_loop_router`` sees a monotonically increasing
    value and can enforce ``max_loops``.
    """

    @functools.wraps(worker_node)
    async def _loop_node_with_counter(
        state: TeamState,
        config: RunnableConfig | None = None,
        _inner: WorkerNode = worker_node,
    ) -> dict[str, Any] | Command[Any]:
        result = await _inner(state, config=config)
        if isinstance(result, Command):
            # Routing nodes never wrap the loop counter: only plain state
            # updates need it incremented before ``_loop_router`` reads it.
            return result
        result["loop_count"] = state.get("loop_count", 0) + 1
        return result

    return accepting_runnable_config(_loop_node_with_counter)


def _compile_pipeline_loop(
    builder: StateGraph[Any, None, Any, Any],
    team_config: Any,
    agent_configs: dict[str, Any],
    _supervisor_agent_config: Any | None,
    *,
    provider_factory: ProviderFactoryProtocol,
    workspace_root: Path | None = None,
    autonomous: bool = False,
    feature_tag: str | None = None,
    task_queue_port: TaskQueuePort | None = None,
    cost_port: CostPort | None = None,
    authoring_binding_provider: AuthoringBindingProvider | None = None,
    frozen_assignment: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Wire up a pipeline_loop topology.

    - pre_loop nodes run sequentially, wired via explicit add_edge calls.
    - loop_node gets a conditional edge: revise -> last pre-loop node | FINISH -> END.
    - max_loops guard uses TeamState.loop_count.
    """
    loop_node_id, pre_loop = _validate_pipeline_loop_config(team_config, agent_configs)
    order = team_config.topology.order
    mount_map: dict[str, str] = {}

    for agent_id in order:
        if agent_id not in agent_configs:
            raise ConfigError(
                f"Agent '{agent_id}' referenced in pipeline_loop order but not "
                "defined in agent_configs. Ensure the agent TOML exists and is "
                "loaded before compiling the graph."
            )
        agent_cfg = agent_configs[agent_id]
        worker_ref = next(
            (w for w in team_config.workers if w.agent_id == agent_id), None
        )
        if worker_ref is None:
            raise ConfigError(
                f"Pipeline-loop node {agent_id!r} has no matching WorkerRef in "
                f"team {team_config.id!r}."
            )
        worker_node, node_metadata = _compile_worker_node(
            worker_ref,
            agent_cfg,
            team_config,
            workspace_root,
            provider_factory=provider_factory,
            frozen_assignment=frozen_assignment,
            autonomous=autonomous,
            feature_tag=feature_tag,
            task_queue_port=task_queue_port,
            cost_port=cost_port,
            authoring_binding_provider=authoring_binding_provider,
        )
        if agent_id == loop_node_id:
            worker_node = _wrap_loop_node(worker_node)

        # Insert mount node before each worker.
        mount_id = f"mount_{agent_cfg.id}"
        mount_fn = create_mount_node(workspace_root, task_queue_port)
        _add_node(builder, mount_id, mount_fn)
        _add_node(
            builder,
            agent_cfg.id,
            worker_node,
            metadata=node_metadata,
            retry_policy=_NODE_RETRY_POLICY,
        )
        builder.add_edge(mount_id, agent_cfg.id)
        mount_map[agent_id] = mount_id

    # Wire: START -> mount_0 -> node_0 -> mount_1 -> node_1 -> ... -> loop_node
    all_sequential: list[str] = [*pre_loop, loop_node_id]
    first_mount = mount_map[all_sequential[0]]
    builder.add_edge(START, first_mount)
    for i in range(len(all_sequential) - 1):
        next_mount = mount_map[all_sequential[i + 1]]
        builder.add_edge(all_sequential[i], next_mount)

    # Loop-back target is the mount node before the loop target worker.
    loop_target_worker: str = pre_loop[-1] if pre_loop else all_sequential[0]
    loop_target_mount: str = mount_map[loop_target_worker]
    max_loops = team_config.topology.max_loops

    def _loop_router(state: TeamState) -> str:
        return _loop_route(
            next_value=state.get("next"),
            loop_count=state.get("loop_count", 0),
            max_loops=max_loops,
        )

    builder.add_conditional_edges(
        loop_node_id,
        _loop_router,
        {"revise": loop_target_mount, "FINISH": GRAPH_COMPLETION_NODE},
    )


# ---------------------------------------------------------------------------
# research_adr topology
# ---------------------------------------------------------------------------
