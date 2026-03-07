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
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.pregel._retry import RetryPolicy

from ..providers.acp_exceptions import AcpSessionError
from ..providers.factory import ProviderFactory
from ..utils.enums import Model, Provider
from .exceptions import ConfigError, WorkerExecutionError
from .nodes.mount import create_mount_node
from .nodes.supervisor import create_supervisor_node
from .nodes.worker import WorkerNode, create_worker_node
from .state import TeamState
from .team_config import AgentConfig, TeamConfig, TopologyType, WorkerRef


logger = logging.getLogger(__name__)


__all__ = ["build_initial_vault_index", "compile_team_graph"]

_VAULT_STAGE_PATTERNS: dict[str, str] = {
    "research": ".vault/research/*{tag}*.md",
    "reference": ".vault/reference/*{tag}*.md",
    "adr": ".vault/adr/*{tag}*.md",
    "plan": ".vault/plan/*{tag}*.md",
    "exec": ".vault/exec/*{tag}*/**/*.md",
    "audit": ".vault/audit/*{tag}*.md",
}
_VAULT_INDEX_CAP = 50

# ADR-023: maps AgentConfig.role → pipeline phase for worker_phase_map derivation.
# Roles not in this map are exempt from phase prerequisite gating.
_ROLE_TO_PHASE: dict[str, str] = {
    "researcher": "research",
    "analyst": "adr",
    "planner": "plan",
    "coder": "exec",
    "reviewer": "audit",
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
    AcpSessionError,
)


def _worker_retry_on(exc: Exception) -> bool:
    """Predicate passed to ``RetryPolicy`` for every worker node.

    Inspects the direct exception and, for ``WorkerExecutionError`` wrappers,
    the ``__cause__`` to determine whether a retry is appropriate.

    Returns:
        ``True``  — transient failure, retry is safe.
        ``False`` — permanent or indeterminate failure, do not retry.
    """
    # Never retry deterministic or quota errors.
    if isinstance(exc, _NO_RETRY_EXCEPTIONS):
        return False

    # WorkerExecutionError wraps the original cause — inspect it.
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
    providers_to_try = [primary_provider, *fallback_chain]
    last_exc: Exception | None = None
    for p in providers_to_try:
        try:
            model = ProviderFactory.create(
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


def build_initial_vault_index(
    workspace_root: Path | None,
    feature_tag: str,
) -> dict[str, list[str]]:
    """Scan .vault/ for files matching feature_tag.

    Returns empty dict when workspace_root is None.
    """
    if workspace_root is None:
        return {}
    index: dict[str, list[str]] = {}
    for stage, pattern in _VAULT_STAGE_PATTERNS.items():
        resolved = pattern.replace("{tag}", feature_tag)
        matches = sorted(workspace_root.glob(resolved))[:_VAULT_INDEX_CAP]
        if matches:
            index[stage] = [str(m.relative_to(workspace_root)) for m in matches]
    return index


def _build_supervisor_prompt(
    resolved_agents: list[AgentConfig],
    base_prompt: str,
    directive: str | None = None,
    feature_context: str | None = None,
) -> str:
    """Inject the agent roster (and optional team directive) into the supervisor prompt.

    Replaces ``{{AGENT_ROSTER}}`` placeholder if present, otherwise appends
    the roster to the base prompt (ADR-013 §2.6).  If a team-level directive
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
    team_config: TeamConfig,
    agent_configs: dict[str, AgentConfig],
    checkpointer: AsyncSqliteSaver | None = None,
    supervisor_agent_config: AgentConfig | None = None,
    workspace_root: Path | None = None,
    autonomous: bool = False,
    step_timeout: float | None = None,
    feature_tag: str | None = None,
) -> CompiledStateGraph:
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
        step_timeout:            Per-step timeout in seconds.  When None the
                                 team TOML ``step_timeout_seconds`` value is
                                 used as fallback (TOML-05).
        feature_tag:             Optional feature tag for task-queue scoping
                                 (ADR-021).

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
            feature_tag=feature_tag,
        )
    elif topology.type == TopologyType.PIPELINE:
        _compile_pipeline(
            builder,
            team_config,
            agent_configs,
            workspace_root,
            autonomous=autonomous,
            feature_tag=feature_tag,
        )
    elif topology.type == TopologyType.PIPELINE_LOOP:
        _compile_pipeline_loop(
            builder,
            team_config,
            agent_configs,
            supervisor_agent_config,
            workspace_root,
            autonomous=autonomous,
            feature_tag=feature_tag,
        )
    else:
        raise ValueError(
            f"Unknown topology type: {topology.type!r}. "
            "Expected 'star', 'pipeline', or 'pipeline_loop'."
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
        graph.step_timeout = effective_timeout

    # recursion_limit: sourced from team TOML (default 25).
    graph.recursion_limit = team_config.graph.recursion_limit

    return graph


def _compile_star(
    builder: StateGraph,
    team_config: TeamConfig,
    agent_configs: dict[str, AgentConfig],
    supervisor_agent_config: AgentConfig | None,
    workspace_root: Path | None = None,
    autonomous: bool = False,
    feature_tag: str | None = None,
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
            resolved_agents,
            supervisor_agent_config.persona.system_prompt,
            directive=team_config.persona.directive,
        )
        # TOML-05: prefer team-level supervisor_display_name when set
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
        )
        worker_node = create_worker_node(
            model,
            agent_cfg.persona.system_prompt,
            name=agent_cfg.id,
            autonomous=autonomous,
            workspace_root=workspace_root,
            feature_tag=feature_tag,
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
        mount_fn = create_mount_node(workspace_root)
        builder.add_node(f"mount_{agent_cfg.id}", mount_fn)
        builder.add_edge(f"mount_{agent_cfg.id}", agent_cfg.id)
        compiled_worker_ids.append(agent_cfg.id)

    # M3: fail fast if no workers compiled — a supervisor with zero routes
    # produces a trivially useless graph.
    if not compiled_worker_ids:
        raise ValueError(
            f"Star topology for team {team_config.id!r} has zero compiled workers. "
            "All worker AgentConfigs are missing or unresolvable."
        )

    # ADR-020: supervisor routes to mount_{wid} which then edges to wid.
    route_map: dict[str, str] = {wid: f"mount_{wid}" for wid in compiled_worker_ids}
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
    feature_tag: str | None = None,
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
        )
        worker_node = create_worker_node(
            model,
            agent_cfg.persona.system_prompt,
            name=agent_cfg.id,
            autonomous=autonomous,
            workspace_root=workspace_root,
            feature_tag=feature_tag,
        )
        # ADR-020: insert mount node between pipeline stages.
        mount_fn = create_mount_node(workspace_root)
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
    team_config: TeamConfig,
    agent_configs: dict[str, AgentConfig],
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
            "A single-agent pipeline_loop is a degenerate self-loop — use "
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
    value and can enforce ``max_loops`` (ADR-013 §5).
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
    team_config: TeamConfig,
    agent_configs: dict[str, AgentConfig],
    supervisor_agent_config: AgentConfig | None,
    workspace_root: Path | None = None,
    autonomous: bool = False,
    feature_tag: str | None = None,
) -> None:
    """Wire up a pipeline_loop topology.

    ADR-013 §2.5 pipeline_loop spec:
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
        )
        worker_node = create_worker_node(
            model,
            agent_cfg.persona.system_prompt,
            name=agent_cfg.id,
            autonomous=autonomous,
            workspace_root=workspace_root,
            feature_tag=feature_tag,
        )
        if agent_id == loop_node_id:
            worker_node = _wrap_loop_node(worker_node)

        # ADR-020: insert mount node before each worker.
        mount_id = f"mount_{agent_cfg.id}"
        mount_fn = create_mount_node(workspace_root)
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
        """Route loop_node output: enforce max_loops guard."""
        loop_count = state.get("loop_count", 0)
        if loop_count >= max_loops:
            return "FINISH"
        return state.get("next", "revise")

    builder.add_conditional_edges(
        loop_node_id,
        _loop_router,
        {"revise": loop_target_mount, "FINISH": END},
    )
