"""LangGraph orchestration engine for agent teams.

Compiles a ``StateGraph`` from a ``TeamConfig`` and resolved ``AgentConfig``
map.  Four topology types are supported:

- ``star``:          supervisor routes dynamically; workers report back to
                     the supervisor.
- ``pipeline``:      fixed sequential chain; no supervisor required.
- ``pipeline_loop``: sequential chain where the loop_node conditionally
                     routes back into the loop or finishes.
- ``research_adr``:  document phase machine; researchers fan out into a
                     synthesis node, then the research, ADR, and plan phases
                     each run author -> review -> submit -> approval gate.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol, TypedDict, Unpack, cast

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

    from langchain_core.runnables import RunnableConfig
    from langchain_core.runnables.graph import Graph as DrawableGraph
    from langgraph.checkpoint.base import BaseCheckpointSaver
    from langgraph.types import Command, RetryPolicy

    from ..authoring import FeedbackContextReader
    from ..providers.team_selection import FrozenLaneAssignment
    from ..worker.authoring_binding import AuthoringBindingProvider
    from .nodes.phase_gate import DocumentProposalSubmitter
    from .protocols import (
        CostPort,
        ProviderFactoryProtocol,
        RuntimeIdentityPort,
        TaskQueuePort,
    )

from langgraph.graph import END, StateGraph
from langgraph.types import TimeoutPolicy

from ..domain_config import domain_config
from ..thread.clarification import (
    CLARIFICATION_TOPOLOGIES,
    topology_honours_clarification,
)
from ..thread.errors import (
    ConfigError,
)
from ..thread.state import TeamState
from ._compiler_models import (
    resolve_model_for_worker,
    validate_frozen_assignment_inventory,
)
from ._compiler_prompts import (
    composed_worker_prompt,
)
from ._compiler_retry import _NODE_RETRY_POLICY, node_occupancy_ceiling
from .enums import PipelinePhase, Provider
from .nodes.action_completion import GRAPH_COMPLETION_NODE, record_graph_completion
from .nodes.diverge import (
    create_research_dispatch_node,
    researcher_node_name,
)
from .nodes.vault_reader import create_context_mounter
from .nodes.worker import WorkerNode, create_worker_node
from .run_context import RunContext

logger = logging.getLogger(__name__)


__all__ = [
    "STEP_BACKSTOP_GRACE_SECONDS",
    "_ROLE_TO_PHASE",
    "CompiledTeamGraph",
    "_add_node",
    "_agent_node_metadata",
    "_compile_worker_node",
    "_loop_route",
    "_route_from_supervisor",
    "_wire_diverge_stage",
    "compile_team_graph",
    "required_recursion_limit_for_finish_blocks",
]


class _NodeWiring(TypedDict, total=False):
    """Everything that decides how one added node behaves, beside the node.

    The five keywords langgraph's ``add_node`` takes that this project sets.
    Declared once so the protocol below, the boundary helper, and every call
    site name the same set, and so adding a sixth is one edit rather than
    three.
    """

    metadata: dict[str, str] | None
    retry_policy: RetryPolicy | Sequence[RetryPolicy] | None
    error_handler: Callable[..., Any] | None
    destinations: tuple[str, ...] | None
    timeout: TimeoutPolicy | None


class _TypedBuilder(Protocol):
    """The exact ``StateGraph`` surface this module uses, precisely typed.

    Mirrors ``CompiledTeamGraph`` below: langgraph declares ``cache_policy``
    and ``checkpointer`` as bare unparametrized generics in its own source, so
    the member reads as partially unknown whatever a caller passes. Viewing the
    builder through this declared subset is what makes the two calls below
    checked rather than unknown. Every parameter here is narrower than
    langgraph's real signature, never wider, so a call accepted here is
    accepted there.
    """

    def add_node(
        self,
        node: str,
        action: Callable[..., Any],
        **wiring: Unpack[_NodeWiring],
    ) -> object: ...

    def set_node_defaults(
        self,
        *,
        timeout: TimeoutPolicy | None = ...,
    ) -> object: ...

    def compile(
        self,
        checkpointer: BaseCheckpointSaver[str] | bool | None = ...,
        *,
        interrupt_before: list[str] | None = ...,
        name: str | None = ...,
    ) -> object: ...


def _add_node(
    builder: StateGraph[Any, Any, Any, Any],
    name: str,
    node: Callable[..., Any],
    **wiring: Unpack[_NodeWiring],
) -> None:
    """Add a node to ``builder`` behind one fully-typed call boundary.

    langgraph's own ``add_node`` overloads default ``cache_policy`` to a bare
    ``CachePolicy[Unknown]`` in its shipped source (not just a stub gap), so
    the member access itself is permanently partially-typed regardless of the
    arguments passed at a given call site. Every ``add_node`` call in this
    module routes through here instead of the library method directly, so
    that irreducible diagnostic is paid once, at this boundary, rather than at
    each of the two dozen call sites that would otherwise repeat it.

    Every key is forwarded whether or not the caller set it, so an unset
    option reaches langgraph as the explicit ``None`` this boundary has always
    sent rather than as an absent argument the library would default for
    itself.

    ``destinations`` is required in practice for any node that routes by
    returning ``Command``: such a node has no static outgoing edge, so without
    it the compiled graph's own topology reports the node as ending the run and
    every node it actually jumps to as unreachable.
    """
    cast("_TypedBuilder", builder).add_node(
        name,
        node,
        metadata=wiring.get("metadata"),
        retry_policy=wiring.get("retry_policy"),
        error_handler=wiring.get("error_handler"),
        destinations=wiring.get("destinations"),
        timeout=wiring.get("timeout"),
    )


def _set_node_defaults(
    builder: StateGraph[Any, Any, Any, Any],
    *,
    timeout: TimeoutPolicy,
) -> None:
    """Apply graph-wide node defaults behind the same typed call boundary.

    Mirrors ``_add_node``: langgraph declares ``cache_policy`` here as a bare
    ``CachePolicy[Unknown]`` too, so the member read is partially unknown
    whatever this module passes. Going through the protocol is what makes the
    one argument this project actually sets a checked argument.
    """
    cast("_TypedBuilder", builder).set_node_defaults(timeout=timeout)


def _compile_graph(
    builder: StateGraph[Any, Any, Any, Any],
    *,
    checkpointer: BaseCheckpointSaver[str] | None,
    interrupt_before: list[str] | None,
    name: str,
) -> CompiledTeamGraph:
    """Compile ``builder`` behind one fully-typed call boundary.

    Mirrors ``_add_node``: langgraph's ``compile`` overloads carry the same
    unresolved ``BaseCheckpointSaver[Unknown]``-shaped defaults in their own
    source, so this is the single place that diagnostic is paid.

    ``name`` is the team the graph was compiled from. Unnamed, every compiled
    graph reports itself as ``LangGraph``, so a trace, a stream event or a
    subgraph label could not say which team produced it - and a worker process
    holds several compiled graphs at once.
    """
    return cast(
        "CompiledTeamGraph",
        cast("_TypedBuilder", builder).compile(
            checkpointer, interrupt_before=interrupt_before, name=name
        ),
    )


class CompiledTeamGraph(Protocol):
    """The compiler's supported surface for a team graph: invoke, and inspect.

    ``ainvoke`` returns the run's final state rather than ``object``. It is a
    state mapping in fact, and saying so is what lets a caller read a key off the
    result without casting at every site - the previous ``object`` return made
    every such read an error while the value underneath was always a mapping.

    ``nodes`` and ``interrupt_before_nodes`` are introspection rather than
    invocation, and they are declared because compilation is a thing this project
    ASSERTS about: which nodes a topology produced, and where it parks, are the
    compiler's observable output. Both exist on the compiled graph; leaving them
    off the protocol did not hide them, it only stopped the checker seeing what
    the tests legitimately read.
    """

    @property
    def nodes(self) -> Mapping[str, object]: ...

    @property
    def interrupt_before_nodes(self) -> Sequence[str]: ...

    # The team the graph was compiled from, set at compile time. Every runnable
    # carries a name and an unnamed compiled graph takes langgraph's default,
    # so a trace holding several of them could not tell them apart.
    name: str

    # The drawable topology, including the edges a ``Command``-routing node
    # declares. It is how a compiled graph's reachability is asserted: a routing
    # node without declared destinations draws as ending the run.
    def get_graph(self) -> DrawableGraph: ...

    # Not a property: this function SETS it on the compiled graph a few lines
    # below, and the compiler's tests read back what was set. It is the
    # superstep backstop, a grace above the per-node run budget every node
    # carries, so the node's own timeout fires first and names the node.
    step_timeout: float | None

    async def ainvoke(
        self,
        # A PARTIAL state mapping, which is what the graph actually accepts:
        # every TeamState field bar a few is NotRequired, and callers seed a run
        # with the handful of keys it needs. Annotating this ``TeamState`` named
        # the intent but refused the real argument, since a plain dict is not
        # structurally a TypedDict. TeamState remains the shape being described -
        # the state module is where that contract lives.
        input: Mapping[str, Any] | Command[str] | None,
        config: RunnableConfig | None = None,
        # The final state, PLUS langgraph's own control keys - a parked run
        # carries ``__interrupt__`` alongside the state fields. So this is a
        # mapping rather than TeamState: TeamState would be the more useful
        # promise and would be false, since ``__interrupt__`` is not one of its
        # keys and reading it is exactly what a parked-run assertion does.
    ) -> Mapping[str, Any]: ...


#: Seconds the graph-wide superstep bound sits above the longest a node can
#: legitimately occupy its superstep. Both are measured from roughly the same
#: instant, so at equal values the superstep bound would win the race and
#: report an anonymous step timeout instead of the node's own, which names the
#: node and which limit it hit. The bound it sits above is the RETRY budget -
#: every attempt's run budget plus the waits between them - not one attempt's,
#: which is what truncated the retries a node was configured for.
STEP_BACKSTOP_GRACE_SECONDS = 30.0

# Maps AgentConfig.role -> pipeline phase for worker_phase_map derivation.
# Roles not in this map are exempt from phase prerequisite gating.
#
# Plain ``.value`` strings, not the members: this map's values are what the
# supervisor writes into the checkpointed ``pipeline_phase`` channel, and under
# strict msgpack the checkpoint serializer will not rebuild a type it does not
# know - it logs the block and hands back the member's raw value, so a parked
# run would resume holding a plain string where it wrote a member.
# ``PipelinePhase`` is a ``StrEnum``, so every comparison against a member
# still holds.
_ROLE_TO_PHASE: dict[str, str] = {
    "researcher": PipelinePhase.RESEARCH.value,
    "analyst": PipelinePhase.ADR.value,
    "adr-author": PipelinePhase.ADR.value,
    "planner": PipelinePhase.PLAN.value,
    "plan-author": PipelinePhase.PLAN.value,
    "coder": PipelinePhase.EXEC.value,
    "reviewer": PipelinePhase.AUDIT.value,
}


def _agent_node_metadata(
    agent_config: Any, provider: Provider, model_name: str
) -> dict[str, str]:
    """Build node metadata from the exact catalog-frozen model identity."""
    return {
        "display_name": agent_config.display_name,
        "role": agent_config.role,
        "description": agent_config.description.strip(),
        "provider": provider.value,
        "model_name": model_name,
    }


class _CompileWorkerOptions(TypedDict):
    provider_factory: ProviderFactoryProtocol
    frozen_assignment: dict[str, FrozenLaneAssignment] | None
    autonomous: bool
    feature_tag: str | None
    task_queue_port: TaskQueuePort | None
    cost_port: CostPort | None
    runtime_identity_port: RuntimeIdentityPort | None
    authoring_binding_provider: AuthoringBindingProvider | None


def _compile_worker_node(
    worker_ref: Any,
    agent_cfg: Any,
    team_config: Any,
    workspace_root: Path | None,
    **options: Unpack[_CompileWorkerOptions],
) -> tuple[WorkerNode, dict[str, str]]:
    """Resolve one worker's model and build its compiled node plus node metadata.

    Shared by the star, pipeline, and pipeline_loop topologies, which otherwise
    each wrote this exact resolve-compose-build-metadata step out in full - not
    hypothetical duplication: the model-name disclosure fix had to touch all
    three call sites identically, and a miss at any one of them would have meant
    that topology silently failing to disclose which model it ran, in exactly
    the way that fix existed to close.

    The team harness is resolved HERE rather than passed in, for that same
    reason: it is read off the ``team_config`` all three topologies already hand
    over, so there is one resolution site instead of three that must agree. It
    was previously read only by ``_compile_research_adr``, which left a preset
    declaring ``[team.harness] mcp_servers`` on any other topology compiling to
    a worker that never advertised it - a declaration the config layer parsed,
    validated, and then dropped on the floor.

    Deliberately stops short of ``builder.add_node``. pipeline_loop wraps
    exactly one returned node - its own loop node - in ``_wrap_loop_node``
    before adding it, which needs a seam between "node built" and "node added"
    that a helper owning ``add_node`` could only offer back as a callback
    parameter every caller would have to remember to pass correctly. The mount
    node each topology inserts around its worker, and the edge each draws out
    of it, differ enough between topologies (star edges the worker back to the
    supervisor; pipeline and pipeline_loop insert the mount before add_node
    rather than after) that they stay topology-owned rather than folded in here
    - that wiring is each topology's actual subject, not shared duplication.
    """
    model, used_provider, model_name = resolve_model_for_worker(
        worker_ref,
        agent_cfg,
        team_config,
        workspace_root,
        provider_factory=options["provider_factory"],
        frozen_assignment=options["frozen_assignment"],
    )
    # Flat and team-level, exactly as the research_adr path reads it: the harness
    # schema carries no per-role MCP field, so every worker of the team gets the
    # team's declaration. Empty when no harness is declared, which composes to a
    # no-op rather than to some inherited default.
    harness = team_config.effective_harness()
    worker_node = create_worker_node(
        model,
        composed_worker_prompt(agent_cfg, model),
        name=agent_cfg.id,
        autonomous=options["autonomous"],
        workspace_root=workspace_root,
        feature_tag=options["feature_tag"],
        task_queue_port=options["task_queue_port"],
        cost_port=options["cost_port"],
        runtime_identity_port=options["runtime_identity_port"],
        authoring_binding_provider=options["authoring_binding_provider"],
        role=agent_cfg.role,
        # The same role-to-phase reading the supervisor gates on, so the worker
        # the completion gate reroutes a blocked FINISH to is the worker whose
        # return retires the validation errors that blocked it. Reading it here
        # keeps the mapping in the one place that owns it.
        phase=_ROLE_TO_PHASE.get(agent_cfg.role),
        harness_mcp_servers=list(harness.mcp_servers) if harness is not None else [],
        # Every worker these topologies compile sits behind a mount node that
        # refreshes the vault index; the worker expands the documents itself.
        context_mounter=create_context_mounter(
            workspace_root, options["task_queue_port"]
        ),
    )
    metadata = _agent_node_metadata(agent_cfg, used_provider, model_name)
    return worker_node, metadata


class _DivergeStageArgs(TypedDict):
    dispatch_name: str
    synthesis_name: str
    specs: list[dict[str, Any]]
    make_researcher: Callable[[dict[str, Any]], WorkerNode]
    researcher_metadata: dict[str, str]


def _wire_diverge_stage(
    builder: StateGraph[Any, Any, Any, Any], **kwargs: Unpack[_DivergeStageArgs]
) -> str:
    """Wire a Send-based diverge stage into ``builder``.

    Adds the dispatch node, one researcher node per thread spec (named via
    ``researcher_node_name``), and a static edge from each researcher into
    ``synthesis_name`` to form the join. The dispatch node fans out with
    ``Send`` through ``Command.goto`` and carries no static outgoing edges; the
    synthesis node itself is wired by the caller (the topology owns the synthesis
    stage and its inner review loop). Returns the dispatch node name so the
    caller can edge into it.

    ``make_researcher`` maps a thread spec to the branch node, so the topology
    supplies model-backed researchers while the fan-out/join structure stays
    model-agnostic and independently testable. ``researcher_metadata`` is the
    one caller-built exception to that: every branch shares the same researcher
    role, provider, and model, so one precomputed metadata dict is applied to
    each - a per-spec callback would only ever be asked to return the same
    value, which is a flag in disguise, not a real degree of freedom.

    Each researcher carries the same retry policy as every other model-backed
    node. A branch was the lone exception, so a transient provider failure in one
    researcher aborted a whole fan-out that its siblings would have survived. The
    policy retries transient failures ONLY: a deterministic error - a producer
    handing the branch a contract-violating finding - still fails fast, since a
    retry of a deterministic failure only spends a turn to fail identically. That
    class is kept off the production path at the producer instead, where the
    citation channel's locators are normalised into the contract.
    """
    dispatch_name = kwargs["dispatch_name"]
    synthesis_name = kwargs["synthesis_name"]
    specs = kwargs["specs"]
    make_researcher = kwargs["make_researcher"]
    researcher_metadata = kwargs["researcher_metadata"]
    if not specs:
        raise ConfigError(
            f"diverge stage {dispatch_name!r} requires at least one research "
            "thread spec"
        )

    researcher_names: list[str] = []
    for index, spec in enumerate(specs):
        name = researcher_node_name(dispatch_name, index)
        _add_node(
            builder,
            name,
            make_researcher(spec),
            metadata=researcher_metadata,
            retry_policy=_NODE_RETRY_POLICY,
        )
        builder.add_edge(name, synthesis_name)
        researcher_names.append(name)

    _add_node(
        builder,
        dispatch_name,
        create_research_dispatch_node(researcher_names),
        destinations=tuple(researcher_names),
    )
    return dispatch_name


#: Supersteps one blocked FINISH costs a star run: the supervisor turn that the
#: completion gate refuses, the mount node ahead of the worker it reroutes to,
#: and that worker's own turn. Measured against a compiled star graph rather
#: than reasoned about, and pinned by a test that drives one, because it is the
#: conversion factor between two limits a preset and an operator set
#: independently of each other.
_SUPERSTEPS_PER_FINISH_BLOCK = 3


#: The phases the completion gate reroutes a blocked FINISH to. A team with no
#: worker of either never spends the finish-block budget at all: the gate
#: refuses the FINISH outright rather than rerouting it, and the re-ask budget
#: is what bounds that.
_FINISH_BLOCK_REROUTE_PHASES: frozenset[str] = frozenset(
    {PipelinePhase.EXEC.value, PipelinePhase.AUDIT.value}
)


def required_recursion_limit_for_finish_blocks() -> int:
    """The smallest recursion limit that lets the finish-block budget report.

    Every reroute the budget permits, plus the one further supervisor turn on
    which the budget is spent and the typed error raised. A run cut one
    superstep shorter than this ends in ``GraphRecursionError`` with the gate's
    reason never reported.
    """
    return (
        _SUPERSTEPS_PER_FINISH_BLOCK * domain_config.supervisor_finish_block_limit
    ) + 1


def _can_spend_finish_block_budget(
    team_config: Any, agent_configs: dict[str, Any]
) -> bool:
    """Whether this team has a worker a blocked FINISH could be rerouted to."""
    return any(
        _ROLE_TO_PHASE.get(cfg.role) in _FINISH_BLOCK_REROUTE_PHASES
        for cfg in (
            agent_configs.get(worker.agent_id) for worker in team_config.workers
        )
        if cfg is not None
    )


def _validate_finish_block_budget(
    team_config: Any, agent_configs: dict[str, Any]
) -> None:
    """Refuse a star preset whose recursion limit outlaws its own budget.

    The two limits are set independently - the budget by the operator's domain
    configuration, the ceiling by the preset - and a preset that stops the run
    first converts a diagnosable refusal into an anonymous
    ``GraphRecursionError``: the supervisor never reaches the block that would
    have named the gate it could not satisfy. Refusing at compile time is the
    only place the pair is visible before a run depends on it.

    Only a team that can actually spend the budget is held to it. Refusing one
    that cannot would reject a working preset over a limit no run of it ever
    reaches.
    """
    if not _can_spend_finish_block_budget(team_config, agent_configs):
        return
    required = required_recursion_limit_for_finish_blocks()
    declared = int(team_config.graph.recursion_limit)
    if declared >= required:
        return
    raise ConfigError(
        f"Team {getattr(team_config, 'id', '?')!r} declares recursion_limit "
        f"{declared}, which is below the {required} supersteps the supervisor "
        f"finish-block budget of "
        f"{domain_config.supervisor_finish_block_limit} needs to report a "
        f"blocked FINISH: each blocked FINISH costs "
        f"{_SUPERSTEPS_PER_FINISH_BLOCK} supersteps, and one more carries the "
        f"supervisor turn that spends the budget. A run cut shorter ends in "
        f"GraphRecursionError with the gate's reason unreported. Raise "
        f"recursion_limit to at least {required}, or lower the finish-block "
        f"budget."
    )


def _validate_compiled_topology(
    team_config: Any, agent_configs: dict[str, Any]
) -> None:
    from ..team.team_config import TopologyType

    topology = team_config.topology
    if not isinstance(topology.type, TopologyType):
        raise ValueError(
            f"Unknown topology type: {topology.type!r}. "
            f"Expected one of: {[t.value for t in TopologyType]}"
        )
    if getattr(team_config, "clarification", None) is not None and (
        not topology_honours_clarification(topology.type)
    ):
        raise ConfigError(
            f"Team {getattr(team_config, 'id', '?')!r} declares a clarification "
            f"questionnaire on topology {topology.type.value!r}, which compiles no "
            f"clarification stage; the questions would never be asked. Topologies "
            f"that ask: {sorted(CLARIFICATION_TOPOLOGIES)}."
        )
    if topology.type == TopologyType.STAR:
        # Only the star compiles a supervisor, so only the star can spend this
        # budget; every other topology's recursion limit is its own business.
        _validate_finish_block_budget(team_config, agent_configs)


def _route_from_supervisor(state: TeamState) -> str:
    """Route a star-topology supervisor output to its next hop.

    A refused decision - one naming no route, or a route a HARD phase gate
    blocked - returns to the supervisor, whose ``next`` then records only its
    intent. A pending plan approval short-circuits to the ``plan_approval`` node
    before any worker routing. Otherwise the supervisor's own ``next`` decision
    is the route key. ``next`` is read directly (not defaulted): by the time
    this edge runs the supervisor has always set it, so a missing key is a real
    invariant break that should fail loud rather than silently route nowhere.
    Lifted to module scope so its contract is testable without compiling a
    graph.
    """
    if state.get("supervisor_reasks"):
        return "supervisor"
    if state.get("approval_status") == "pending":
        return "plan_approval"
    next_route = state.get("next")
    if next_route is None:
        raise ConfigError(
            "supervisor routing invariant broken: 'next' was not set before "
            "the supervisor->route edge ran"
        )
    return next_route


def _loop_route(*, revision_requested: bool, loop_count: int, max_loops: int) -> str:
    """Decide a pipeline-loop node's next hop: ``"revise"`` or ``"FINISH"``.

    The pure routing decision behind the ``_loop_router`` closure, lifted to
    module scope so it is testable without compiling a graph. The loop goes
    round again only when the loop node's own verdict asks for revision; the
    ``max_loops`` guard forces ``"FINISH"`` once the counter reaches the
    ceiling, whatever the verdict. The early exit used to wait for a literal
    ``"FINISH"`` in ``next``, which no worker writes, so every loop ran to its
    ceiling.
    """
    if loop_count >= max_loops:
        return "FINISH"
    return "revise" if revision_requested else "FINISH"


class _CompileTeamOptional(TypedDict, total=False):
    checkpointer: BaseCheckpointSaver[str] | None
    supervisor_agent_config: Any | None
    workspace_root: Path | None
    autonomous: bool
    step_timeout: float | None
    feature_tag: str | None
    task_queue_port: TaskQueuePort | None
    cost_port: CostPort | None
    runtime_identity_port: RuntimeIdentityPort | None
    proposal_submitter: DocumentProposalSubmitter | None
    feedback_reader: FeedbackContextReader | None
    authoring_binding_provider: AuthoringBindingProvider | None
    model_assignment: dict[str, FrozenLaneAssignment] | None


class _CompileTeamOptions(_CompileTeamOptional):
    provider_factory: ProviderFactoryProtocol


def compile_team_graph(
    team_config: Any,
    agent_configs: dict[str, Any],
    **options: Unpack[_CompileTeamOptions],
) -> CompiledTeamGraph:
    """Compile the LangGraph orchestration engine from a TeamConfig.

    Supports four topology types:

    - ``star``:          Dynamic supervisor routing.
    - ``pipeline``:      Fixed sequential chain (no supervisor).
    - ``pipeline_loop``: Sequential chain with conditional back-edge.
    - ``research_adr``:  Document phase machine (diverge, synthesize, gate,
                         decide, gate, plan, gate); requires
                         ``proposal_submitter``.

    Args:
        team_config:             Validated team preset (loaded from TOML).
        agent_configs:           Mapping of agent_id -> AgentConfig for all
                                 workers referenced in the team.
        checkpointer:            Optional LangGraph checkpointer for state
                                 persistence.
        supervisor_agent_config: Optional AgentConfig for the supervisor node.
                                 Only used for star/pipeline_loop topologies.
        workspace_root:          Optional workspace root for ACP CWD scoping.
        autonomous:              When True, skip permission_callback wiring so
                                 ACP models auto-approve tool calls (headless
                                 MCP-launched runs).
        step_timeout:            Positive timeout from accepted graph authority.
        feature_tag:             Optional feature tag for task-queue scoping.
        task_queue_port:         Optional database-backed task-queue port
                                 injected into worker and mount nodes.
        provider_factory:        Provider factory for model creation.

    Returns:
        The compiled StateGraph runnable.

    Raises:
        ConfigError: If a worker agent_id from team_config is not in agent_configs,
                     if topology configuration is invalid, or if a clarification
                     questionnaire is declared on a topology that mounts no
                     clarification stage.
        ValueError:  If an unknown topology type is encountered.
    """
    from ..team.team_config import TopologyType
    from ._compiler_research import _compile_research_adr
    from ._compiler_topologies import (
        _compile_pipeline,
        _compile_pipeline_loop,
        _compile_star,
    )

    provider_factory = options["provider_factory"]
    workspace_root = options.get("workspace_root")
    autonomous = options.get("autonomous", False)
    step_timeout = options.get("step_timeout")
    feature_tag = options.get("feature_tag")
    task_queue_port = options.get("task_queue_port")
    cost_port = options.get("cost_port")
    runtime_identity_port = options.get("runtime_identity_port")
    proposal_submitter = options.get("proposal_submitter")
    feedback_reader = options.get("feedback_reader")
    authoring_binding_provider = options.get("authoring_binding_provider")
    model_assignment = options.get("model_assignment")

    if step_timeout is None:
        step_timeout = team_config.graph.step_timeout_seconds

    if step_timeout is None or step_timeout <= 0:
        raise ConfigError(
            "compiled execution requires an explicit positive step timeout"
        )

    validate_frozen_assignment_inventory(model_assignment)

    builder: StateGraph[Any, RunContext, Any, Any] = StateGraph(
        cast("Any", TeamState), context_schema=RunContext
    )
    # Every node attempt is capped at the preset's step budget. No idle limit:
    # a provider CLI running a long tool call relays no LangChain callback while
    # it works, so an idle clock would fell agents that are making progress.
    _set_node_defaults(builder, timeout=TimeoutPolicy(run_timeout=step_timeout))
    _add_node(builder, GRAPH_COMPLETION_NODE, record_graph_completion)
    builder.add_edge(GRAPH_COMPLETION_NODE, END)
    topology = team_config.topology

    _validate_compiled_topology(team_config, agent_configs)

    # interrupt_before disabled: approval flows via interrupt() inside the node only.
    interrupt_nodes: list[str] = []

    if topology.type == TopologyType.STAR:
        _compile_star(
            builder,
            team_config,
            agent_configs,
            options.get("supervisor_agent_config"),
            provider_factory=provider_factory,
            workspace_root=workspace_root,
            autonomous=autonomous,
            feature_tag=feature_tag,
            task_queue_port=task_queue_port,
            cost_port=cost_port,
            runtime_identity_port=runtime_identity_port,
            authoring_binding_provider=authoring_binding_provider,
            frozen_assignment=model_assignment,
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
            cost_port=cost_port,
            runtime_identity_port=runtime_identity_port,
            authoring_binding_provider=authoring_binding_provider,
            frozen_assignment=model_assignment,
        )
    elif topology.type == TopologyType.PIPELINE_LOOP:
        _compile_pipeline_loop(
            builder,
            team_config,
            agent_configs,
            options.get("supervisor_agent_config"),
            provider_factory=provider_factory,
            workspace_root=workspace_root,
            autonomous=autonomous,
            feature_tag=feature_tag,
            task_queue_port=task_queue_port,
            cost_port=cost_port,
            runtime_identity_port=runtime_identity_port,
            authoring_binding_provider=authoring_binding_provider,
            frozen_assignment=model_assignment,
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
            feedback_reader=feedback_reader,
            frozen_assignment=model_assignment,
            cost_port=cost_port,
            runtime_identity_port=runtime_identity_port,
        )
    else:
        raise ValueError(
            f"Unknown topology type: {topology.type!r}. "
            "Expected 'star', 'pipeline', 'pipeline_loop', or 'research_adr'."
        )

    graph = _compile_graph(
        builder,
        checkpointer=options.get("checkpointer"),
        interrupt_before=interrupt_nodes,
        name=str(team_config.id),
    )

    graph.step_timeout = (
        node_occupancy_ceiling(step_timeout) + STEP_BACKSTOP_GRACE_SECONDS
    )

    return graph
