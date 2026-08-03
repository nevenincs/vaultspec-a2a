"""Graph lifecycle management -- compilation, caching, and registration.

Extracted from ``executor.py`` to isolate graph compilation,
LRU cache management, and graph-input construction from the dispatch
orchestration logic in ``Executor``.
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast, override

from langchain_core.messages import HumanMessage, SystemMessage

from ..domain_config import domain_config
from ..graph.compiler import _resolve_model_for_worker, compile_team_graph
from ..streaming import StreamableGraph, node_metadata_from_graph
from ..team.team_config import AgentConfig, load_agent_config, load_team_config
from ..telemetry import ws_span
from ..thread.constants import DEFAULT_SUPERVISOR_ID
from ..thread.errors import (
    AgentConfigNotFoundError,
    ConfigError,
    TeamConfigNotFoundError,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from langchain_core.runnables import RunnableConfig
    from langgraph.types import Command

    from ..authoring import DocumentProposalSubmitter, FeedbackContextReader
    from ..database.checkpoints import Checkpointer
    from ..ipc.schemas import DispatchRequest
    from ..streaming.aggregator import EventAggregator
    from .authoring_binding import AuthoringBindingProvider
    from .catalog_store import RunCatalogStore
    from .ipc import WorkerBridge
    from .token_store import RunTokenStore

__all__ = [
    "GraphCacheKey",
    "GraphCompilationError",
    "GraphLifecycleManager",
    "GraphStateSnapshot",
    "RegisteredCompiledGraph",
]


class GraphCompilationError(RuntimeError):
    """Raised when a team graph fails to compile."""


logger = logging.getLogger(__name__)

# Public type for the graph cache key.  The explicit registration seam lets
# real-behavior tests install a pre-compiled graph without reaching mutable
# cache dictionaries.
type GraphCacheKey = tuple[str, str | None, bool]


class GraphStateSnapshot(Protocol):
    """State projection required by the worker's graph registration seam."""

    @property
    def values(self) -> Mapping[str, object]: ...

    @property
    def next(self) -> tuple[str, ...]: ...


class RegisteredCompiledGraph(StreamableGraph, Protocol):
    """Executable and state-observable graph eligible for worker registration."""

    @override
    async def aget_state(
        self, config: Mapping[str, object] | RunnableConfig
    ) -> GraphStateSnapshot: ...

    async def ainvoke(
        self,
        graph_input: Mapping[str, object] | Command[str],
        config: RunnableConfig,
    ) -> object: ...


def assert_armed_authoring_attachable(
    team_config: Any,
    agent_configs: dict[str, AgentConfig],
    ws_root: Path | None,
    *,
    harness: Any,
    provider_factory: Any,
    frozen_assignment: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Refuse an authoring-bridge-armed preset a worker cannot mount the bridge onto.

    ``providers._acp_authoring.attach_authoring_tools`` dispatches the run's
    authoring binding onto the resolved model's own surface (``with_mcp_servers``
    for the ACP lane, ``with_authoring_mcp_server`` for Codex) and, since the
    codex-authoring-bridge-attachment fix, raises loud when a model exposes
    neither — but that raise fires per-turn, inside the worker node, only once
    the run has already started and begun burning its step timeout waiting on an
    agent that will never see its tools. This gate asks the identical question
    at COMPILE time, for every worker in an ``authoring_bridge``-armed preset,
    so a provider with no attachment surface at all is refused with a served
    compile-time reason before the run ever starts — never a live-run timeout.

    A no-op when *harness* does not arm the authoring bridge (a per-worker
    resolution scoped to authoring_bridge specifically: the
    harness-mcp_servers-only case is
    already proven to reach every known provider's own delivery mechanism -
    ``with_mcp_servers`` or ``with_harness_mcp_servers`` - via
    ``compose_harness_mcp_servers``, so it is out of scope here).
    """
    if harness is None or not harness.authoring_bridge:
        return
    unsupported: list[str] = []
    for worker_ref in team_config.workers:
        agent_config = agent_configs.get(worker_ref.agent_id)
        if agent_config is None:
            continue
        try:
            model, _resolved_provider, _capability = _resolve_model_for_worker(
                worker_ref,
                agent_config,
                team_config,
                ws_root,
                provider_factory=provider_factory,
                frozen_assignment=frozen_assignment,
            )
        except ValueError:
            # Provider exhaustion is a distinct failure surfaced by compile.
            continue
        has_attach_surface = (
            getattr(model, "with_mcp_servers", None) is not None
            or getattr(model, "with_authoring_mcp_server", None) is not None
        )
        if not has_attach_surface:
            unsupported.append(f"{worker_ref.agent_id!r} ({type(model).__name__})")
    if unsupported:
        raise ConfigError(
            f"harness-armed preset {team_config.id!r} declares "
            "[team.harness] authoring_bridge = true, but the following worker(s) "
            f"resolved to a provider with no authoring attachment surface: "
            f"{'; '.join(unsupported)}. The declared authoring tools cannot "
            "mount onto this provider; refusing before the run starts rather "
            "than spawning an agent whose tools silently never attach."
        )


class GraphLifecycleManager:
    """Manages graph compilation, LRU caching, and input construction.

    Parameters
    ----------
    checkpointer:
        Shared LangGraph checkpointer for graph compilation.
    bridge:
        ``WorkerBridge`` for forwarding graph_registered events.
    aggregator:
        ``EventAggregator`` for registering compiled graphs.
    """

    def __init__(
        self,
        checkpointer: Checkpointer,
        bridge: WorkerBridge,
        aggregator: EventAggregator,
        token_store: RunTokenStore,
        catalog_store: RunCatalogStore,
    ) -> None:
        from ..database.session import get_session_factory
        from ..providers.factory import ProviderFactory
        from .cost_port import SqlCostPort
        from .task_queue_port import SqlTaskQueuePort

        self._checkpointer = checkpointer
        self._bridge = bridge
        self._aggregator = aggregator
        # The worker lifecycle is the single site that constructs the
        # production authoring submitter, fed the run's per-role tokens from here.
        self._token_store = token_store
        # Per-run engine catalog cache, shared with the authoring-bridge provider
        # so the run fetches its catalog once regardless of worker count.
        self._catalog_store = catalog_store
        self._provider_factory = ProviderFactory()
        # The worker reaches the app database (task_queue_entries) via
        # the shared session factory; migrations are owned by the gateway.
        self._task_queue_port = SqlTaskQueuePort(get_session_factory())
        # Token accounting reaches the same app database (cost_tracking) over
        # the same shared session factory.
        self._cost_port = SqlCostPort(get_session_factory())
        self._graph_cache: OrderedDict[GraphCacheKey, RegisteredCompiledGraph] = (
            OrderedDict()
        )
        # Maps thread_id -> cache key so resume can find the graph
        # and recompile if evicted.
        self._thread_to_cache_key: dict[str, GraphCacheKey] = {}

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    @property
    def graph_count(self) -> int:
        """Number of compiled graphs currently held."""
        return len(self._graph_cache)

    def has_thread(self, thread_id: str) -> bool:
        """Return whether this worker has a cache-key record for *thread_id*."""
        return thread_id in self._thread_to_cache_key

    def cache_key_for_thread(self, thread_id: str) -> GraphCacheKey | None:
        """Return the cache key known for *thread_id*, if the worker has one."""
        return self._thread_to_cache_key.get(thread_id)

    def clear(self) -> None:
        """Clear all cached graphs and thread mappings."""
        self._graph_cache.clear()
        self._thread_to_cache_key.clear()

    def register_compiled_graph(
        self,
        thread_id: str,
        cache_key: GraphCacheKey,
        graph: RegisteredCompiledGraph,
    ) -> None:
        """Atomically install a compiled graph for a known thread.

        This is the only public graph-injection seam.  It maintains the same
        cache and thread mapping invariant as normal compilation, then makes
        the graph available to event aggregation before dispatch can resume it.
        """
        while (
            cache_key not in self._graph_cache
            and len(self._graph_cache) >= domain_config.max_cached_graphs
        ):
            self._graph_cache.popitem(last=False)
        self._graph_cache[cache_key] = graph
        self._graph_cache.move_to_end(cache_key)
        self._thread_to_cache_key[thread_id] = cache_key
        self._aggregator.register_graph(graph)

    # ------------------------------------------------------------------
    # Graph cache lookup and compilation
    # ------------------------------------------------------------------

    async def get_or_compile_graph(
        self,
        req: DispatchRequest,
    ) -> RegisteredCompiledGraph | None:
        """Return a compiled graph for *req*, using the LRU cache.

        If the thread already maps to a cached graph, return it (LRU touch).
        If the preset is known but no graph is cached (eviction or first use),
        compile a new one, cache it, and register with the aggregator.
        Returns ``None`` if no preset is available.
        """
        # Check if thread already has a cached graph.
        cache_key = self._thread_to_cache_key.get(req.thread_id)
        if cache_key and cache_key in self._graph_cache:
            self._graph_cache.move_to_end(cache_key)
            return self._graph_cache[cache_key]

        # Resolve preset -- from request or previously stored mapping.
        team_preset = req.team_preset
        workspace_root = req.workspace_root
        autonomous = req.autonomous
        if not team_preset and cache_key:
            team_preset = cache_key[0]
            workspace_root = cache_key[1]
            autonomous = cache_key[2]
        if not team_preset:
            return None

        new_key: GraphCacheKey = (team_preset, workspace_root, autonomous)

        # Check if another thread already compiled for this key.
        if new_key in self._graph_cache:
            self._graph_cache.move_to_end(new_key)
            self._thread_to_cache_key[req.thread_id] = new_key
            return self._graph_cache[new_key]

        # Compile fresh.
        async with ws_span("executor.compile_graph", thread_id=req.thread_id) as span:
            span.set_attribute("team_preset", team_preset)
            try:
                graph = await self._compile_graph(req)
                span.add_event("graph_compiled")
            except Exception as exc:
                logger.exception(
                    "Failed to compile graph for thread %s (preset=%s)",
                    req.thread_id,
                    team_preset,
                )
                span.record_exception(exc)
                span.set_attribute("error", True)
                raise GraphCompilationError(str(exc)) from exc

        # Evict LRU if at capacity.
        while len(self._graph_cache) >= domain_config.max_cached_graphs:
            self._graph_cache.popitem(last=False)

        self._graph_cache[new_key] = graph
        self._thread_to_cache_key[req.thread_id] = new_key
        self._aggregator.register_graph(graph)
        # Relay node metadata to the control-surface aggregator so
        # REST /team-status and WS team_status events include role/display_name.
        await self._send_graph_registered(req.thread_id, graph)
        return graph

    async def _send_graph_registered(
        self, thread_id: str, graph: RegisteredCompiledGraph
    ) -> None:
        """Send a ``graph_registered`` event with node metadata via the bridge.

        The control-surface aggregator uses this to populate its
        ``_node_metadata`` cache so that ``emit_team_status`` and the REST
        ``/team-status`` endpoint include role/display_name/description.
        """
        nodes = node_metadata_from_graph(graph)
        if nodes:
            await self._bridge.send_event(
                thread_id,
                {"type": "graph_registered", "nodes": nodes},
            )

    # ------------------------------------------------------------------
    # Graph compilation
    # ------------------------------------------------------------------

    async def _compile_graph(self, req: DispatchRequest) -> RegisteredCompiledGraph:
        """Load team/agent configs and compile a LangGraph ``StateGraph``.

        Uses the same two-level config discovery order as the monolith:
        workspace override then bundled preset. ``async`` only because it may
        await ``_build_proposal_submitter``/``_build_authoring_binding_provider``
        below, which offload the engine-discovery retry loop off this event
        loop; everything else here is synchronous config/compile work.
        """
        ws_root = Path(req.workspace_root).resolve() if req.workspace_root else None

        try:
            team_config = load_team_config(
                cast("str", req.team_preset), workspace_root=ws_root
            )
        except TeamConfigNotFoundError as exc:
            raise ValueError(f"Team preset not found: {req.team_preset!r}") from exc

        agent_configs: dict[str, AgentConfig] = {}
        for worker_ref in team_config.workers:
            try:
                agent_configs[worker_ref.agent_id] = load_agent_config(
                    worker_ref.agent_id, workspace_root=ws_root
                )
            except AgentConfigNotFoundError:
                logger.warning(
                    "Agent config not found for %s",
                    worker_ref.agent_id,
                    extra={
                        "agent_id": worker_ref.agent_id,
                        "team_preset": req.team_preset,
                        "workspace_root": str(ws_root) if ws_root else None,
                        "action": "agent_config_missing",
                    },
                )

        supervisor_config: AgentConfig | None = None
        if team_config.topology.type in ("star", "pipeline_loop"):
            try:
                supervisor_config = load_agent_config(
                    DEFAULT_SUPERVISOR_ID, workspace_root=ws_root
                )
            except AgentConfigNotFoundError:
                logger.debug(
                    "No supervisor config; using defaults",
                    extra={
                        "agent_id": DEFAULT_SUPERVISOR_ID,
                        "team_preset": req.team_preset,
                        "workspace_root": str(ws_root) if ws_root else None,
                        "action": "supervisor_config_defaulted",
                    },
                )

        # Document-phase topologies author through the engine; build the
        # production submitter here, the single construction site, and fail closed
        # at build time when the run cannot author (so it never starts vague). The
        # feedback reader is the read-path companion (best-effort, not fail-closed):
        # it grounds the document writers on a revision run's reviewer batch.
        proposal_submitter = None
        feedback_reader = None
        if team_config.topology.type == "research_adr":
            proposal_submitter = await self._build_proposal_submitter()
            feedback_reader = self._build_feedback_reader()

        # CLI-coder presets that arm the engine authoring bridge get a per-run
        # binding provider, built here behind the same fail-closed contract as the
        # submitter: a run that cannot reach the engine to fetch its catalog never
        # starts vague. Only a coding topology can arm this (the config validator
        # rejects authoring_bridge on document-authoring presets).
        authoring_binding_provider = None
        harness = team_config.effective_harness()
        if harness is not None and harness.authoring_bridge:
            authoring_binding_provider = await self._build_authoring_binding_provider()

        # Compile gate: an ARMED preset - one declaring the authoring bridge OR
        # harness MCP servers - must have an attachment surface on every worker.
        # No credential gate runs here: providers authenticate themselves from
        # the ambient environment they inherit, and an unauthenticated lane
        # reports its own failure at run time. The declared-surface invariant
        # (agent-harness-provisioning; the S20 leak) is enforced at spawn by the
        # run-workspace MCP projection and confinement settings, not by refusing
        # the run for a missing credential.
        armed = harness is not None and (
            harness.authoring_bridge or bool(harness.mcp_servers)
        )
        if armed:
            assert_armed_authoring_attachable(
                team_config,
                agent_configs,
                ws_root,
                harness=harness,
                provider_factory=self._provider_factory,
                frozen_assignment=req.model_assignment,
            )

        return cast(
            "RegisteredCompiledGraph",
            compile_team_graph(
                team_config=team_config,
                agent_configs=agent_configs,
                checkpointer=self._checkpointer,
                supervisor_agent_config=supervisor_config,
                workspace_root=ws_root,
                autonomous=req.autonomous,
                # Let compile_team_graph use team_config.graph.step_timeout_seconds
                step_timeout=None,
                # Thread feature_tag so vault indexing works in worker
                feature_tag=req.active_feature,
                task_queue_port=self._task_queue_port,
                cost_port=self._cost_port,
                provider_factory=self._provider_factory,
                proposal_submitter=proposal_submitter,
                feedback_reader=feedback_reader,
                authoring_binding_provider=authoring_binding_provider,
                # Compile against the run's frozen effective assignment so a
                # restart reproduces the exact launched models.
                model_assignment=req.model_assignment,
            ),
        )

    async def _build_proposal_submitter(self) -> DocumentProposalSubmitter:
        """Construct the production authoring submitter for a research_adr run.

        Fails closed at build time: a research_adr run whose engine origin cannot
        be resolved never starts vaguely — the typed error propagates as a
        ``GraphCompilationError`` and a truthful run failure. The per-role tokens
        the submitter reads at call time come from this worker's
        :class:`RunTokenStore`; the engine bearer and the writer document body are
        resolved per run from the store and graph state, so the cached graph is
        reused safely across runs. The phase specs map each document phase to the
        graph writer node whose ``AIMessage.name`` carries the document
        (``synthesis``/``adr_author``/``plan_author``, the ``_RA_*`` node names in
        the compiler) and to the role whose actor token authors it. The role key is
        the worker ``agent_id`` (``vaultspec-synthesist``/``vaultspec-adr-author``/
        ``vaultspec-plan-author``), matching
        the actor-token bundle keying the run-start eligibility policy
        enforces — not the short persona role.
        """
        from ..authoring import (
            DocumentProposalSubmitter,
            EngineUnavailableError,
            PhaseAuthoringSpec,
            resolve_engine_with_retry,
        )

        # Bounded poll, not a one-shot probe: the engine has measured multi-
        # second stall windows (scope-watcher rebuilds) during which a single
        # 3s /health probe misses a healthy engine and would truthfully fail a
        # run that succeeds seconds later. Offloaded via to_thread rather than
        # made async in place: resolve_engine_with_retry is a plain blocking
        # function (time.sleep + a sync httpx probe, by its own design, reused
        # by non-async callers too) and this is the one call site that runs on
        # a live event loop — a worker's own step_timeout and the S37 ingest
        # stall watchdog exist precisely because a blocking call here used to
        # freeze the whole worker (heartbeats included) for the full retry
        # window on every first compile of a preset+workspace cache key.
        engine = await asyncio.to_thread(resolve_engine_with_retry)
        if engine is None:
            raise EngineUnavailableError(
                "research_adr run requires a reachable authoring engine to submit "
                "document proposals; none was discoverable at run start "
                "(retried across the engine's stall window)"
            )
        return DocumentProposalSubmitter(
            engine_base_url=engine.base_url,
            token_store=self._token_store,
            phases={
                "research": PhaseAuthoringSpec(
                    document_role="vaultspec-synthesist",
                    writer_message_name="synthesis",
                    doc_type="research",
                    completion_sentinel="RESEARCH READY",
                ),
                "adr": PhaseAuthoringSpec(
                    document_role="vaultspec-adr-author",
                    writer_message_name="adr_author",
                    doc_type="adr",
                    completion_sentinel="ADR READY",
                ),
                "plan": PhaseAuthoringSpec(
                    document_role="vaultspec-plan-author",
                    writer_message_name="plan_author",
                    doc_type="plan",
                    completion_sentinel="PLAN READY",
                ),
            },
        )

    async def _build_authoring_binding_provider(self) -> AuthoringBindingProvider:
        """Construct the per-run authoring-bridge binding provider for a coding run.

        Fails closed at build time exactly like the submitter: a bridged run whose
        engine origin cannot be resolved never starts vaguely - the typed
        ``EngineUnavailableError`` is wrapped into a ``GraphCompilationError`` by
        the compile guard. The provider reads the run's per-role tokens from this
        worker's :class:`RunTokenStore` at binding time and caches the engine
        catalog once per run in the shared :class:`RunCatalogStore`, so every
        worker in the run shares one fetch. Offloaded via ``to_thread`` for the
        same reason as ``_build_proposal_submitter``: ``resolve_engine_with_retry``
        blocks with ``time.sleep``, and this runs on a live worker event loop.
        """
        from ..authoring import EngineUnavailableError, resolve_engine_with_retry
        from .authoring_binding import AuthoringBindingProvider

        engine = await asyncio.to_thread(resolve_engine_with_retry)
        if engine is None:
            raise EngineUnavailableError(
                "authoring_bridge run requires a reachable engine to fetch the "
                "agent-tool catalog and route tool execution; none was discoverable "
                "at run start (retried across the engine's stall window)"
            )
        return AuthoringBindingProvider(
            engine_base_url=engine.base_url,
            token_store=self._token_store,
            catalog_store=self._catalog_store,
        )

    def _build_feedback_reader(self) -> FeedbackContextReader | None:
        """Construct the feedback-batch reader for a research_adr run, or None.

        The read-path companion to the submitter:
        on a revision run it retrieves the reviewer's batch by id to ground the
        document writers. Unlike the submitter it is NOT fail-closed - a run
        without a reachable engine simply grounds nothing (best-effort), because a
        run can proceed without feedback grounding even though it cannot AUTHOR
        without the engine. The batch read is capability-by-id, so it presents the
        synthesist role's actor token (a document-authoring role always provisioned
        for a research_adr run); the id, not the role, is the capability.
        """
        from ..authoring import FeedbackContextReader, resolve_engine

        engine = resolve_engine()
        if engine is None:
            return None
        return FeedbackContextReader(
            engine_base_url=engine.base_url,
            token_store=self._token_store,
            read_role="vaultspec-synthesist",
        )

    # ------------------------------------------------------------------
    # Graph input construction
    # ------------------------------------------------------------------

    @staticmethod
    def build_graph_input(
        req: DispatchRequest, *, is_first_ingest: bool
    ) -> dict[str, Any]:
        """Build the ``graph_input`` dict for a new user turn.

        For the *initial* ingest on a thread, all required ``TeamState``
        fields are supplied so the checkpointer starts with a clean state.
        For follow-up messages, the plan/agent/artifact/token fields are
        omitted so LangGraph preserves checkpoint values (supplying
        ``current_plan=[]`` would trigger the ``_replace_plan`` reducer's
        "clear" sentinel and wipe the supervisor's execution plan).

        SDD blackboard fields are always materialized on the first ingest. This
        is the fresh-checkpoint half of the desktop compatibility contract: an
        ordinary restart validates those keys and never runs a migration.

        Args:
            req: The incoming ``DispatchRequest``.
            is_first_ingest: ``True`` when the thread has no prior
                checkpoint (i.e., the thread_id was not in
                ``_thread_to_cache_key`` before this call).

        Returns:
            A ``dict`` suitable for passing directly to
            ``EventAggregator.ingest()`` as *graph_input*.
        """
        messages: list[SystemMessage | HumanMessage] = []
        if req.context_preamble:
            messages.append(SystemMessage(content=req.context_preamble))
        if req.content:
            messages.append(HumanMessage(content=req.content))

        graph_input: dict[str, Any] = {
            "messages": messages,
            "thread_id": req.thread_id,
        }
        if is_first_ingest:
            graph_input.update(
                {
                    "active_agent": "",
                    "artifacts": [],
                    "current_plan": [],
                    "token_usage": {},
                    "active_feature": req.active_feature,
                    "feedback_batch_id": req.feedback_batch_id,
                    "pipeline_phase": req.pipeline_phase,
                    "vault_index": req.vault_index or {},
                    "validation_errors": req.validation_errors or [],
                }
            )
        return graph_input
