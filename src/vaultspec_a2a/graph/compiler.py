"""LangGraph orchestration engine for agent teams.

Compiles a ``StateGraph`` from a ``TeamConfig`` and resolved ``AgentConfig``
map.  Three topology types are supported (ADR-013 S2.5):

- ``star``:          supervisor routes dynamically; workers report back to
                     the supervisor.
- ``pipeline``:      fixed sequential chain; no supervisor required.
- ``pipeline_loop``: sequential chain where the loop_node conditionally
                     routes back into the loop or finishes.
"""

import functools
import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Hashable

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import RetryPolicy

from vaultspec_a2a.thread.errors import (
    ConfigError,
    ProviderSessionError,
    WorkerExecutionError,
)
from vaultspec_a2a.thread.state import TeamState

from .enums import Model, PipelinePhase, Provider
from .nodes.diverge import (
    ResearchFindingProducer,
    create_research_dispatch_node,
    create_researcher_node,
    researcher_node_name,
)
from .nodes.phase_gate import DocumentProposalSubmitter, create_phase_gate_node
from .nodes.supervisor import create_plan_approval_node, create_supervisor_node
from .nodes.vault_reader import build_initial_vault_index, create_mount_node
from .nodes.worker import WorkerNode, create_worker_node
from .protocols import ProviderFactoryProtocol, TaskQueuePort

logger = logging.getLogger(__name__)


# ``build_initial_vault_index`` is defined in ``nodes.vault_reader`` (the mount
# node reuses it to refresh the index each pass) and re-exported here to preserve
# the historical ``graph.compiler.build_initial_vault_index`` import surface.
__all__ = ["build_initial_vault_index", "compile_team_graph"]

# ADR-023: maps AgentConfig.role -> pipeline phase for worker_phase_map derivation.
# Roles not in this map are exempt from phase prerequisite gating.
_ROLE_TO_PHASE: dict[str, str] = {
    "researcher": PipelinePhase.RESEARCH,
    "analyst": PipelinePhase.ADR,
    "planner": PipelinePhase.PLAN,
    "coder": PipelinePhase.EXEC,
    "reviewer": PipelinePhase.AUDIT,
}

# Transient exceptions that warrant a retry at the LangGraph node level.
_TRANSIENT_EXCEPTIONS: tuple[type[BaseException], ...] = (
    TimeoutError,
    ConnectionError,
    ConnectionResetError,
    ConnectionAbortedError,
    ConnectionRefusedError,
)

# Exceptions that must never trigger a retry.
_NO_RETRY_EXCEPTIONS: tuple[type[BaseException], ...] = (
    GraphRecursionError,
    ProviderSessionError,
)


def _worker_retry_on(exc: Exception) -> bool:
    """Predicate passed to ``RetryPolicy`` for every worker node.

    Inspects the direct exception and, for ``WorkerExecutionError`` wrappers,
    the ``__cause__`` to determine whether a retry is appropriate.

    Returns:
        ``True``  -- transient failure, retry is safe.
        ``False`` -- permanent or indeterminate failure, do not retry.
    """
    # Never retry deterministic or quota errors.
    if isinstance(exc, _NO_RETRY_EXCEPTIONS):
        return False

    # WorkerExecutionError wraps the original cause -- inspect it.
    if isinstance(exc, WorkerExecutionError):
        cause = exc.__cause__
        if cause is None:
            return False
        if isinstance(cause, _NO_RETRY_EXCEPTIONS):
            return False
        return isinstance(cause, _TRANSIENT_EXCEPTIONS)

    return isinstance(exc, _TRANSIENT_EXCEPTIONS)


#: RetryPolicy applied to every worker and supervisor node (T05).
_NODE_RETRY_POLICY = RetryPolicy(retry_on=_worker_retry_on)


def _resolve_model_for_worker(
    worker_ref: Any,
    agent_config: Any,
    team_config: Any,
    workspace_root: Path | None = None,
    *,
    provider_factory: ProviderFactoryProtocol,
) -> BaseChatModel:
    """Resolve provider + capability following ADR-013 S2.3 precedence."""
    factory = provider_factory
    primary_provider, capability, fallback_chain = _resolve_worker_model_preferences(
        worker_ref,
        agent_config,
        team_config,
    )
    providers_to_try = [primary_provider, *fallback_chain]
    last_exc: Exception | None = None
    for p in providers_to_try:
        try:
            model = factory.create(
                p,
                model=capability,
                agent_config=agent_config,
                workspace_root=workspace_root,
            )
            logger.info(
                "worker=%r resolved model_type=%s provider=%s capability=%s",
                agent_config.id,
                type(model).__name__,
                p.value,
                capability.value if capability else "default",
            )
            return model
        except ValueError as exc:
            logger.warning(
                "Provider %s unavailable for worker %s: %s",
                p.value,
                agent_config.id,
                exc,
            )
            last_exc = exc
    raise ValueError(
        f"All providers exhausted for worker {agent_config.id!r}: "
        f"tried {[p.value for p in providers_to_try]}"
    ) from last_exc


def _resolve_worker_model_preferences(
    worker_ref: Any,
    agent_config: Any,
    team_config: Any,
) -> tuple[Provider, Model | None, list[Provider]]:
    """Resolve provider + capability following ADR-013 S2.3 precedence.

    Priority (highest to lowest):
    1. [[team.workers]] model.* override
    2. agent TOML [agent.model].*
    3. [team.defaults].*

    If the primary provider fails, the provider_fallback chain is tried in
    order (TOML-05 Scope 2).  provider_fallback is resolved with the same
    priority as the primary provider.
    """
    primary_provider: Provider = (
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
    fallback_chain: list[Provider] = (
        worker_ref.model.provider_fallback
        or agent_config.model.provider_fallback
        or team_config.defaults.provider_fallback
        or []
    )
    return primary_provider, capability, fallback_chain


def _resolve_supervisor_model(
    team_config: Any,
    workspace_root: Path | None = None,
    *,
    provider_factory: ProviderFactoryProtocol,
    supervisor_agent_config: Any | None = None,
) -> BaseChatModel:
    """Resolve the supervisor model from team config."""
    factory = provider_factory
    provider: Provider = (
        team_config.supervisor.provider
        or team_config.defaults.provider
        or Provider.CLAUDE
    )
    capability: Model = team_config.supervisor.capability or Model.MAX
    return factory.create(
        provider,
        model=capability,
        agent_config=supervisor_agent_config,
        workspace_root=workspace_root,
    )


def _wire_diverge_stage(
    builder: StateGraph,
    *,
    dispatch_name: str,
    synthesis_name: str,
    specs: list[dict[str, Any]],
    make_researcher: Callable[[dict[str, Any]], WorkerNode],
) -> str:
    """Wire a Send-based diverge stage into ``builder`` (S04).

    Adds the dispatch node, one researcher node per thread spec (named via
    ``researcher_node_name``), and a static edge from each researcher into
    ``synthesis_name`` to form the join. The dispatch node fans out with
    ``Send`` through ``Command.goto`` and carries no static outgoing edges; the
    synthesis node itself is wired by the caller (the topology owns the synthesis
    stage and its inner review loop). Returns the dispatch node name so the
    caller can edge into it.

    ``make_researcher`` maps a thread spec to the branch node, so the topology
    supplies model-backed researchers while the fan-out/join structure stays
    model-agnostic and independently testable.
    """
    if not specs:
        raise ConfigError(
            f"diverge stage {dispatch_name!r} requires at least one research "
            "thread spec"
        )

    researcher_names: list[str] = []
    for index, spec in enumerate(specs):
        name = researcher_node_name(dispatch_name, index)
        builder.add_node(name, make_researcher(spec))
        builder.add_edge(name, synthesis_name)
        researcher_names.append(name)

    builder.add_node(dispatch_name, create_research_dispatch_node(researcher_names))
    return dispatch_name


def _build_supervisor_prompt(
    resolved_agents: list[Any],
    base_prompt: str,
    directive: str | None = None,
    feature_context: str | None = None,
) -> str:
    """Inject the agent roster (and optional team directive) into the supervisor prompt.

    Replaces ``{{AGENT_ROSTER}}`` placeholder if present, otherwise appends
    the roster to the base prompt (ADR-013 S2.6).  If a team-level directive
    is supplied (from ``[team.persona] directive`` in the preset TOML), it is
    appended after the roster section (TOML-05).
    """
    roster = "\n".join(
        f"- {cfg.display_name} ({cfg.id}): {cfg.description.strip()}"
        for cfg in resolved_agents
    )
    if "{{AGENT_ROSTER}}" in base_prompt:
        result = base_prompt.replace("{{AGENT_ROSTER}}", roster)
    else:
        result = (
            base_prompt + f"\n\nYour team members and their specializations:\n{roster}"
        )
    if directive:
        result = result + f"\n\n## Team Directive\n\n{directive.strip()}"
    if feature_context:
        if "{{FEATURE_CONTEXT}}" in result:
            result = result.replace("{{FEATURE_CONTEXT}}", feature_context)
        else:
            result = result + f"\n\n## Feature Context\n\n{feature_context}"
    return result


def compile_team_graph(
    team_config: Any,
    agent_configs: dict[str, Any],
    *,
    provider_factory: ProviderFactoryProtocol,
    checkpointer: BaseCheckpointSaver | None = None,
    supervisor_agent_config: Any | None = None,
    workspace_root: Path | None = None,
    autonomous: bool = False,
    step_timeout: float | None = None,
    feature_tag: str | None = None,
    task_queue_port: TaskQueuePort | None = None,
    proposal_submitter: DocumentProposalSubmitter | None = None,
) -> CompiledStateGraph:
    """Compile the LangGraph orchestration engine from a TeamConfig.

    Supports four topology types (ADR-013 S2.5, adr-authoring-orchestration):

    - ``star``:          Dynamic supervisor routing.
    - ``pipeline``:      Fixed sequential chain (no supervisor).
    - ``pipeline_loop``: Sequential chain with conditional back-edge.
    - ``research_adr``:  Document phase machine (diverge, synthesize, gate,
                         decide, gate); requires ``proposal_submitter``.

    Args:
        team_config:             Validated team preset (loaded from TOML).
        agent_configs:           Mapping of agent_id -> AgentConfig for all
                                 workers referenced in the team.
        checkpointer:            Optional LangGraph checkpointer for state
                                 persistence.
        supervisor_agent_config: Optional AgentConfig for the supervisor node.
                                 Only used for star/pipeline_loop topologies.
        workspace_root:          Optional workspace root for ACP CWD scoping
                                 (ADR-014 S2.7).
        autonomous:              When True, skip permission_callback wiring so
                                 ACP models auto-approve tool calls (headless
                                 MCP-launched runs).
        step_timeout:            Per-step timeout in seconds.  When None the
                                 team TOML ``step_timeout_seconds`` value is
                                 used as fallback (TOML-05).
        feature_tag:             Optional feature tag for task-queue scoping
                                 (ADR R5).
        task_queue_port:         Optional database-backed task-queue port
                                 injected into worker and mount nodes (ADR R5).
        provider_factory:        Provider factory for model creation.

    Returns:
        The compiled StateGraph runnable.

    Raises:
        ConfigError: If a worker agent_id from team_config is not in agent_configs,
                     or if topology configuration is invalid.
        ValueError:  If an unknown topology type is encountered.
    """
    from vaultspec_a2a.team.team_config import TopologyType

    builder = StateGraph(cast("Any", TeamState))
    topology = team_config.topology

    # M3: validate topology_type is a known TopologyType enum value before dispatch.
    if not isinstance(topology.type, TopologyType):
        raise ValueError(
            f"Unknown topology type: {topology.type!r}. "
            f"Expected one of: {[t.value for t in TopologyType]}"
        )

    # interrupt_before disabled: approval flows via interrupt() inside the node only
    # (ADR-013 S2.7 superseded by plan 2026-28-02).
    interrupt_nodes: list[str] = []

    if topology.type == TopologyType.STAR:
        _compile_star(
            builder,
            team_config,
            agent_configs,
            supervisor_agent_config,
            provider_factory=provider_factory,
            workspace_root=workspace_root,
            autonomous=autonomous,
            feature_tag=feature_tag,
            task_queue_port=task_queue_port,
        )
    elif topology.type == TopologyType.PIPELINE:
        _compile_pipeline(
            builder,
            team_config,
            agent_configs,
            provider_factory=provider_factory,
            workspace_root=workspace_root,
            autonomous=autonomous,
            feature_tag=feature_tag,
            task_queue_port=task_queue_port,
        )
    elif topology.type == TopologyType.PIPELINE_LOOP:
        _compile_pipeline_loop(
            builder,
            team_config,
            agent_configs,
            supervisor_agent_config,
            provider_factory=provider_factory,
            workspace_root=workspace_root,
            autonomous=autonomous,
            feature_tag=feature_tag,
            task_queue_port=task_queue_port,
        )
    elif topology.type == TopologyType.RESEARCH_ADR:
        _compile_research_adr(
            builder,
            team_config,
            agent_configs,
            provider_factory=provider_factory,
            workspace_root=workspace_root,
            autonomous=autonomous,
            proposal_submitter=proposal_submitter,
        )
    else:
        raise ValueError(
            f"Unknown topology type: {topology.type!r}. "
            "Expected 'star', 'pipeline', 'pipeline_loop', or 'research_adr'."
        )

    graph = builder.compile(
        checkpointer=checkpointer,
        interrupt_before=interrupt_nodes,
    )

    # TOML-05: apply per-preset graph settings.
    # step_timeout: explicit caller param wins; fall back to team TOML value.
    effective_timeout = (
        step_timeout
        if step_timeout is not None
        else (
            float(team_config.graph.step_timeout_seconds)
            if team_config.graph.step_timeout_seconds is not None
            else None
        )
    )
    if effective_timeout is not None:
        # step_timeout is an internal Pregel attribute, not in public docs.
        # Pin to LangGraph >=0.2.60 if relying on this.
        graph.step_timeout = effective_timeout

    return graph


def _compile_star(
    builder: StateGraph,
    team_config: Any,
    agent_configs: dict[str, Any],
    supervisor_agent_config: Any | None,
    *,
    provider_factory: ProviderFactoryProtocol,
    workspace_root: Path | None = None,
    autonomous: bool = False,
    feature_tag: str | None = None,
    task_queue_port: TaskQueuePort | None = None,
) -> None:
    """Wire up a star topology: supervisor -> workers -> supervisor -> END.

    ADR-013 S2.5 star spec.
    """
    worker_ids: list[str] = [w.agent_id for w in team_config.workers]
    resolved_agents = [agent_configs[wid] for wid in worker_ids if wid in agent_configs]

    supervisor_model = _resolve_supervisor_model(
        team_config,
        workspace_root,
        provider_factory=provider_factory,
        supervisor_agent_config=supervisor_agent_config,
    )

    if supervisor_agent_config is not None:
        supervisor_prompt = _build_supervisor_prompt(
            resolved_agents,
            supervisor_agent_config.persona.system_prompt,
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
        }

    # ADR-023: derive worker_phase_map from agent roles for phase prerequisite gates.
    worker_phase_map: dict[str, str] = {
        cfg.id: _ROLE_TO_PHASE[cfg.role]
        for cfg in resolved_agents
        if cfg.role in _ROLE_TO_PHASE
    }

    supervisor_node = create_supervisor_node(
        model=supervisor_model,
        system_prompt=supervisor_prompt,
        workers=worker_ids,
        worker_phase_map=worker_phase_map or None,
        autonomous=autonomous,
        workspace_root=workspace_root,
    )
    builder.add_node(
        "supervisor", supervisor_node, metadata=sv_meta, retry_policy=_NODE_RETRY_POLICY
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
        model = _resolve_model_for_worker(
            worker_ref,
            agent_cfg,
            team_config,
            workspace_root,
            provider_factory=provider_factory,
        )
        worker_node = create_worker_node(
            model,
            agent_cfg.persona.system_prompt,
            name=agent_cfg.id,
            autonomous=autonomous,
            workspace_root=workspace_root,
            feature_tag=feature_tag,
            task_queue_port=task_queue_port,
        )
        builder.add_node(
            agent_cfg.id,
            worker_node,
            metadata={
                "display_name": agent_cfg.display_name,
                "role": agent_cfg.role,
                "description": agent_cfg.description.strip(),
            },
            retry_policy=_NODE_RETRY_POLICY,
        )
        builder.add_edge(agent_cfg.id, "supervisor")
        # ADR-020: insert mount node between supervisor routing and worker invocation.
        mount_fn = create_mount_node(workspace_root, task_queue_port)
        builder.add_node(f"mount_{agent_cfg.id}", mount_fn)
        builder.add_edge(f"mount_{agent_cfg.id}", agent_cfg.id)
        compiled_worker_ids.append(agent_cfg.id)

    # M3: fail fast if no workers compiled -- a supervisor with zero routes
    # produces a trivially useless graph.
    if not compiled_worker_ids:
        raise ValueError(
            f"Star topology for team {team_config.id!r} has zero compiled workers. "
            "All worker AgentConfigs are missing or unresolvable."
        )

    # ADR-024 (revised): the dedicated approval node owns the plan-approval
    # interrupt; the supervisor only marks approval_status="pending". The node
    # is replay-safe because nothing before its interrupt() has side effects.
    approval_node = create_plan_approval_node(
        compiled_worker_ids, worker_phase_map or None
    )
    builder.add_node(
        "plan_approval",
        approval_node,
        metadata={
            "display_name": "Plan Approval",
            "role": "gate",
            "description": "Pauses for human plan approval before execution.",
        },
    )

    # ADR-020: supervisor routes to mount_{wid} which then edges to wid.
    route_map: dict[str, str] = {wid: f"mount_{wid}" for wid in compiled_worker_ids}
    route_map["FINISH"] = END

    def _route_from_supervisor(state: TeamState) -> str:
        if state.get("approval_status") == "pending":
            return "plan_approval"
        return state["next"]

    supervisor_route_map = {**route_map, "plan_approval": "plan_approval"}
    builder.add_conditional_edges(
        "supervisor",
        _route_from_supervisor,
        cast("dict[Hashable, str]", supervisor_route_map),
    )
    # Approved -> exec worker's mount; rejected -> revision worker's mount.
    builder.add_conditional_edges(
        "plan_approval",
        lambda state: state["next"],
        cast("dict[Hashable, str]", route_map),
    )


def _compile_pipeline(
    builder: StateGraph,
    team_config: Any,
    agent_configs: dict[str, Any],
    *,
    provider_factory: ProviderFactoryProtocol,
    workspace_root: Path | None = None,
    autonomous: bool = False,
    feature_tag: str | None = None,
    task_queue_port: TaskQueuePort | None = None,
) -> None:
    """Wire up a pipeline topology: START -> node[0] -> node[1] -> ... -> END.

    ADR-013 S2.5 pipeline spec. No supervisor node.
    """
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
        model = _resolve_model_for_worker(
            worker_ref,
            agent_cfg,
            team_config,
            workspace_root,
            provider_factory=provider_factory,
        )
        worker_node = create_worker_node(
            model,
            agent_cfg.persona.system_prompt,
            name=agent_cfg.id,
            autonomous=autonomous,
            workspace_root=workspace_root,
            feature_tag=feature_tag,
            task_queue_port=task_queue_port,
        )
        # ADR-020: insert mount node between pipeline stages.
        mount_fn = create_mount_node(workspace_root, task_queue_port)
        mount_id = f"mount_{agent_cfg.id}"
        builder.add_node(mount_id, mount_fn)
        builder.add_node(
            agent_cfg.id,
            worker_node,
            metadata={
                "display_name": agent_cfg.display_name,
                "role": agent_cfg.role,
                "description": agent_cfg.description.strip(),
            },
            retry_policy=_NODE_RETRY_POLICY,
        )
        builder.add_edge(mount_id, agent_cfg.id)
        node_names.append(agent_cfg.id)
        mount_names.append(mount_id)

    # Wire: START -> mount_0 -> node_0 -> mount_1 -> node_1 -> ... -> END
    builder.add_edge(START, mount_names[0])
    for i in range(len(node_names) - 1):
        builder.add_edge(node_names[i], mount_names[i + 1])
    builder.add_edge(node_names[-1], END)


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
        seen: set[str] = set()
        dupes: list[str] = []
        for a in order:
            if a in seen:
                dupes.append(a)
            else:
                seen.add(a)
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
    value and can enforce ``max_loops`` (ADR-013 S5).
    """

    @functools.wraps(worker_node)
    async def _loop_node_with_counter(
        state: TeamState,
        _inner: WorkerNode = worker_node,
    ) -> dict[str, Any]:
        result = await _inner(state)
        result["loop_count"] = state.get("loop_count", 0) + 1
        return result

    return _loop_node_with_counter


def _compile_pipeline_loop(
    builder: StateGraph,
    team_config: Any,
    agent_configs: dict[str, Any],
    _supervisor_agent_config: Any | None,
    *,
    provider_factory: ProviderFactoryProtocol,
    workspace_root: Path | None = None,
    autonomous: bool = False,
    feature_tag: str | None = None,
    task_queue_port: TaskQueuePort | None = None,
) -> None:
    """Wire up a pipeline_loop topology.

    ADR-013 S2.5 pipeline_loop spec:
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
        model = _resolve_model_for_worker(
            worker_ref,
            agent_cfg,
            team_config,
            workspace_root,
            provider_factory=provider_factory,
        )
        worker_node = create_worker_node(
            model,
            agent_cfg.persona.system_prompt,
            name=agent_cfg.id,
            autonomous=autonomous,
            workspace_root=workspace_root,
            feature_tag=feature_tag,
            task_queue_port=task_queue_port,
        )
        if agent_id == loop_node_id:
            worker_node = _wrap_loop_node(worker_node)

        # ADR-020: insert mount node before each worker.
        mount_id = f"mount_{agent_cfg.id}"
        mount_fn = create_mount_node(workspace_root, task_queue_port)
        builder.add_node(mount_id, mount_fn)
        builder.add_node(
            agent_cfg.id,
            worker_node,
            metadata={
                "display_name": agent_cfg.display_name,
                "role": agent_cfg.role,
                "description": agent_cfg.description.strip(),
            },
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
        """Route loop_node output: enforce max_loops guard.

        Only the literal "FINISH" ends the loop early; any other residue in
        ``state["next"]`` (stale star-route values, empty strings from graph
        input defaults) must not escape the {revise, FINISH} route map.
        """
        loop_count = state.get("loop_count", 0)
        if loop_count >= max_loops:
            return "FINISH"
        return "FINISH" if state.get("next") == "FINISH" else "revise"

    builder.add_conditional_edges(
        loop_node_id,
        _loop_router,
        {"revise": loop_target_mount, "FINISH": END},
    )


# ---------------------------------------------------------------------------
# research_adr topology (adr-authoring-orchestration)
# ---------------------------------------------------------------------------

# Structural node names for the document phase machine. Fixed rather than
# agent-id-derived so the phase gates and inner review loops can reference their
# targets deterministically.
_RA_DISPATCH = "research_dispatch"
_RA_SYNTHESIS = "synthesis"
_RA_RESEARCH_REVIEW = "research_review"
_RA_RESEARCH_GATE = "research_gate"
_RA_ADR_AUTHOR = "adr_author"
_RA_ADR_REVIEW = "adr_review"
_RA_ADR_GATE = "adr_gate"

_RA_REQUIRED_ROLES = ("researcher", "synthesist", "adr-author", "doc-reviewer")


def _resolve_research_adr_models(
    team_config: Any,
    agent_configs: dict[str, Any],
    workspace_root: Path | None,
    *,
    provider_factory: ProviderFactoryProtocol,
) -> dict[str, BaseChatModel]:
    """Resolve one model per required research_adr role.

    Raises ConfigError when a required role has no resolved AgentConfig among the
    team's workers.
    """
    cfg_by_role: dict[str, Any] = {}
    ref_by_role: dict[str, Any] = {}
    for worker_ref in team_config.workers:
        cfg = agent_configs.get(worker_ref.agent_id)
        if cfg is None:
            continue
        cfg_by_role.setdefault(cfg.role, cfg)
        ref_by_role.setdefault(cfg.role, worker_ref)

    missing = [role for role in _RA_REQUIRED_ROLES if role not in cfg_by_role]
    if missing:
        raise ConfigError(
            f"research_adr topology for team {team_config.id!r} is missing a "
            f"worker for role(s) {missing}; required roles are "
            f"{list(_RA_REQUIRED_ROLES)}."
        )

    models: dict[str, BaseChatModel] = {}
    for role in _RA_REQUIRED_ROLES:
        models[role] = _resolve_model_for_worker(
            ref_by_role[role],
            cfg_by_role[role],
            team_config,
            workspace_root,
            provider_factory=provider_factory,
        )
    return models


def _make_research_producer(
    model: BaseChatModel,
    system_prompt: str,
) -> ResearchFindingProducer:
    """Bridge a researcher model into a ResearchFindingProducer.

    Runs one model turn scoped to the branch's thread spec and packages the
    response as a finding keyed by the thread id. Locators are left to the
    researcher's prose in this structural wiring; richer locator extraction is a
    later refinement.
    """

    async def producer(state: TeamState, spec: dict[str, Any]) -> dict[str, Any]:
        from langchain_core.messages import SystemMessage

        assignment = SystemMessage(
            content=(
                f"Research thread {spec.get('thread_id', '')!r}.\n"
                f"Topic: {spec.get('topic', '')}\n"
                f"{spec.get('instructions', '')}"
            )
        )
        messages = [
            SystemMessage(content=system_prompt),
            assignment,
            *state.get("messages", []),
        ]
        response = await model.ainvoke(messages)
        return {
            "claim": str(response.content),
            "locators": [],
            "source_thread": spec.get("thread_id", ""),
        }

    return producer


#: Standalone verdict sentinels the vaultspec-doc-reviewer persona emits.
_DOC_REVIEW_REVISION_SENTINEL = "REVISION REQUIRED"


def _doc_review_router(*, writer_target: str, gate_target: str) -> Any:
    """Return the inner-quality-loop router for a document phase.

    Reads the doc-reviewer's last message for the persona's standalone verdict
    sentinel: a whole line equal to ``REVISION REQUIRED`` routes back to the phase
    writer to revise; anything else (the ``PASS`` verdict) advances to the phase
    gate. The match is an anchored whole-line check, not a substring, so reviewer
    prose such as "no revision required" does not false-positive back to the
    writer. Absent an explicit revision verdict the loop advances, so the human
    gate remains the backstop rather than an inner loop that never exits.
    """

    def router(state: TeamState) -> str:
        messages = state.get("messages") or []
        last_content = str(getattr(messages[-1], "content", "")) if messages else ""
        lines = {line.strip().upper() for line in last_content.splitlines()}
        if _DOC_REVIEW_REVISION_SENTINEL in lines:
            return writer_target
        return gate_target

    return router


def _compile_research_adr(
    builder: StateGraph,
    team_config: Any,
    agent_configs: dict[str, Any],
    *,
    provider_factory: ProviderFactoryProtocol,
    workspace_root: Path | None = None,
    autonomous: bool = False,
    proposal_submitter: DocumentProposalSubmitter | None,
) -> None:
    """Wire the research_adr document phase machine.

    Structural sequencing (gates enforced by graph shape, not LLM convention):

        START -> diverge (N researchers) -> synthesis -> research_review
              -> [PASS] research_gate -> [approved] adr_author
                                      -> [revise]   synthesis
              -> [REVISION] synthesis
        adr_author -> adr_review
              -> [PASS] adr_gate -> [approved] END
                                 -> [revise]   adr_author
              -> [REVISION] adr_author

    The diverge stage (S04) fans out to one researcher branch per configured
    thread spec; each document phase is guarded by the generalized phase gate
    (S05) whose propose-and-submit runs through the injected
    ``proposal_submitter``. The inner doc-review loop enforces the prose quality
    bar before each human gate.
    """
    if proposal_submitter is None:
        raise ConfigError(
            "research_adr topology requires a proposal_submitter for its phase "
            "gates; the control layer injects the concrete authoring client."
        )

    models = _resolve_research_adr_models(
        team_config,
        agent_configs,
        workspace_root,
        provider_factory=provider_factory,
    )

    specs: list[dict[str, Any]] = [
        spec.model_dump() for spec in team_config.topology.research_threads
    ] or [{"thread_id": "primary", "topic": "", "instructions": ""}]

    researcher_producer = _make_research_producer(
        models["researcher"],
        _agent_system_prompt(team_config, agent_configs, "researcher"),
    )

    _wire_diverge_stage(
        builder,
        dispatch_name=_RA_DISPATCH,
        synthesis_name=_RA_SYNTHESIS,
        specs=specs,
        make_researcher=lambda spec: create_researcher_node(spec, researcher_producer),
    )

    builder.add_node(
        _RA_SYNTHESIS,
        create_worker_node(
            models["synthesist"],
            _agent_system_prompt(team_config, agent_configs, "synthesist"),
            name=_RA_SYNTHESIS,
            autonomous=autonomous,
            workspace_root=workspace_root,
        ),
        retry_policy=_NODE_RETRY_POLICY,
    )
    builder.add_node(
        _RA_RESEARCH_REVIEW,
        create_worker_node(
            models["doc-reviewer"],
            _agent_system_prompt(team_config, agent_configs, "doc-reviewer"),
            name=_RA_RESEARCH_REVIEW,
            autonomous=autonomous,
            workspace_root=workspace_root,
        ),
        retry_policy=_NODE_RETRY_POLICY,
    )
    builder.add_node(
        _RA_ADR_AUTHOR,
        create_worker_node(
            models["adr-author"],
            _agent_system_prompt(team_config, agent_configs, "adr-author"),
            name=_RA_ADR_AUTHOR,
            autonomous=autonomous,
            workspace_root=workspace_root,
        ),
        retry_policy=_NODE_RETRY_POLICY,
    )
    builder.add_node(
        _RA_ADR_REVIEW,
        create_worker_node(
            models["doc-reviewer"],
            _agent_system_prompt(team_config, agent_configs, "doc-reviewer"),
            name=_RA_ADR_REVIEW,
            autonomous=autonomous,
            workspace_root=workspace_root,
        ),
        retry_policy=_NODE_RETRY_POLICY,
    )
    builder.add_node(
        _RA_RESEARCH_GATE,
        create_phase_gate_node(
            PipelinePhase.RESEARCH,
            proposal_submitter,
            approved_target=_RA_ADR_AUTHOR,
            revision_target=_RA_SYNTHESIS,
        ),
    )
    builder.add_node(
        _RA_ADR_GATE,
        create_phase_gate_node(
            PipelinePhase.ADR,
            proposal_submitter,
            approved_target=END,
            revision_target=_RA_ADR_AUTHOR,
        ),
    )

    builder.add_edge(START, _RA_DISPATCH)
    builder.add_edge(_RA_SYNTHESIS, _RA_RESEARCH_REVIEW)
    builder.add_conditional_edges(
        _RA_RESEARCH_REVIEW,
        _doc_review_router(writer_target=_RA_SYNTHESIS, gate_target=_RA_RESEARCH_GATE),
        cast(
            "dict[Hashable, str]",
            {_RA_SYNTHESIS: _RA_SYNTHESIS, _RA_RESEARCH_GATE: _RA_RESEARCH_GATE},
        ),
    )
    builder.add_edge(_RA_ADR_AUTHOR, _RA_ADR_REVIEW)
    builder.add_conditional_edges(
        _RA_ADR_REVIEW,
        _doc_review_router(writer_target=_RA_ADR_AUTHOR, gate_target=_RA_ADR_GATE),
        cast(
            "dict[Hashable, str]",
            {_RA_ADR_AUTHOR: _RA_ADR_AUTHOR, _RA_ADR_GATE: _RA_ADR_GATE},
        ),
    )


def _agent_system_prompt(
    team_config: Any,
    agent_configs: dict[str, Any],
    role: str,
) -> str:
    """Return the system prompt for the first worker with ``role``."""
    for worker_ref in team_config.workers:
        cfg = agent_configs.get(worker_ref.agent_id)
        if cfg is not None and cfg.role == role:
            return str(cfg.persona.system_prompt)
    raise ConfigError(
        f"research_adr topology for team {team_config.id!r} has no worker with "
        f"role {role!r}."
    )
