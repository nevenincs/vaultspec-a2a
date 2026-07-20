"""Graph lifecycle management -- compilation, caching, and registration.

Extracted from ``executor.py`` to isolate graph compilation,
LRU cache management, and graph-input construction from the dispatch
orchestration logic in ``Executor``.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from langchain_core.messages import HumanMessage, SystemMessage

from ..domain_config import domain_config
from ..graph.compiler import _resolve_model_for_worker, compile_team_graph
from ..graph.enums import Provider
from ..team.team_config import AgentConfig, load_agent_config, load_team_config
from ..telemetry import ws_span
from ..thread.constants import DEFAULT_SUPERVISOR_ID
from ..thread.errors import (
    AgentConfigNotFoundError,
    IsolationRequiredError,
    TeamConfigNotFoundError,
)

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

    from ..authoring import DocumentProposalSubmitter, FeedbackContextReader
    from ..database.checkpoints import Checkpointer
    from ..ipc.schemas import DispatchRequest
    from ..streaming.aggregator import EventAggregator, StreamableGraph
    from .authoring_binding import AuthoringBindingProvider
    from .catalog_store import RunCatalogStore
    from .ipc import WorkerBridge
    from .token_store import RunTokenStore

__all__ = ["GraphCompilationError", "GraphLifecycleManager"]


class GraphCompilationError(RuntimeError):
    """Raised when a team graph fails to compile."""


logger = logging.getLogger(__name__)

# Type alias for the graph cache key.
_CacheKey = tuple[str, str | None, bool]

# Provider families whose per-run isolation IS the CLAUDE_CONFIG_DIR config home
# (Claude and Z.ai share the claude-agent-acp wrapper), mapped to the env
# variable names that carry their lane auth. An armed run on one of these lanes
# with no token resolves to auth_mode "none_detected" and would spawn unisolated.
# Kimi rides its own inline --config isolation and Gemini its own home, so they
# are deliberately absent - a none_detected resolution there is not the
# config-home isolation breach this gate guards. Extend per family as lanes grow.
_CONFIG_HOME_LANE_AUTH_ENV_VARS: dict[Provider, tuple[str, ...]] = {
    Provider.CLAUDE: ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_AUTH_TOKEN"),
    Provider.ZAI: ("ZAI_AUTH_TOKEN",),
}


def assert_armed_lanes_authenticated(
    team_config: Any,
    agent_configs: dict[str, AgentConfig],
    ws_root: Path | None,
    *,
    provider_factory: Any,
) -> None:
    """Refuse an armed preset whose config-home lane has no auth token.

    Resolves each worker's model through the real provider factory (cheap - no
    subprocess spawn) and reads the authoritative ``auth_mode`` the factory stamps
    from the environment. When a worker's lane is a config-home isolation family
    (Claude/Z.ai) and resolves to ``none_detected``, the run could not establish
    the per-run isolated home its declared MCP surface requires, so it is refused
    with an :class:`IsolationRequiredError` - the message names the missing env
    VARIABLE for the lane, never a value. Kimi/Gemini/Codex ride other isolation
    paths and are absent from the lane map, so they never trip this gate.

    ``provider_factory`` is injected (not read off a manager) so the gate is a
    pure, deterministically-testable seam - the same dependency-injection shape as
    :func:`compile_team_graph`.
    """
    missing: dict[str, tuple[str, ...]] = {}
    for worker_ref in team_config.workers:
        agent_config = agent_configs.get(worker_ref.agent_id)
        if agent_config is None:
            continue
        try:
            model = _resolve_model_for_worker(
                worker_ref,
                agent_config,
                team_config,
                ws_root,
                provider_factory=provider_factory,
            )
        except ValueError:
            # Provider exhaustion is a distinct failure surfaced by compile.
            continue
        provider_value = getattr(model, "provider", None)
        if not provider_value:
            continue
        try:
            provider = Provider(provider_value)
        except ValueError:
            continue
        env_vars = _CONFIG_HOME_LANE_AUTH_ENV_VARS.get(provider)
        if env_vars and getattr(model, "auth_mode", None) == "none_detected":
            missing[provider.value] = env_vars
    if missing:
        lanes = "; ".join(
            f"{lane} (set one of: {', '.join(env_vars)})"
            for lane, env_vars in sorted(missing.items())
        )
        raise IsolationRequiredError(
            f"harness-armed preset {team_config.id!r} cannot establish the "
            "config-home isolation its declared MCP surface requires: no provider "
            f"auth token for lane(s): {lanes}. Provide the lane token or select a "
            "preset with no harness/bridge."
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
        from vaultspec_a2a.providers.factory import ProviderFactory

        from ..database.session import get_session_factory
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
        self._graph_cache: OrderedDict[_CacheKey, CompiledStateGraph] = OrderedDict()
        # Maps thread_id -> cache key so resume can find the graph
        # and recompile if evicted.
        self._thread_to_cache_key: dict[str, _CacheKey] = {}

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    @property
    def graph_count(self) -> int:
        """Number of compiled graphs currently held."""
        return len(self._graph_cache)

    @property
    def thread_to_cache_key(self) -> dict[str, _CacheKey]:
        """Read-only access to thread->cache-key mapping."""
        return self._thread_to_cache_key

    @property
    def graph_cache(self) -> OrderedDict[_CacheKey, CompiledStateGraph]:
        """Read-only access to the graph cache (for test injection)."""
        return self._graph_cache

    def clear(self) -> None:
        """Clear all cached graphs and thread mappings."""
        self._graph_cache.clear()
        self._thread_to_cache_key.clear()

    # ------------------------------------------------------------------
    # Graph cache lookup and compilation
    # ------------------------------------------------------------------

    async def get_or_compile_graph(
        self,
        req: DispatchRequest,
    ) -> CompiledStateGraph | None:
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

        new_key: _CacheKey = (team_preset, workspace_root, autonomous)

        # Check if another thread already compiled for this key.
        if new_key in self._graph_cache:
            self._graph_cache.move_to_end(new_key)
            self._thread_to_cache_key[req.thread_id] = new_key
            return self._graph_cache[new_key]

        # Compile fresh.
        async with ws_span("executor.compile_graph", thread_id=req.thread_id) as span:
            span.set_attribute("team_preset", team_preset)
            try:
                graph = self._compile_graph(req)
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
        self._aggregator.register_graph(cast("StreamableGraph", graph))
        # Relay node metadata to the control-surface aggregator so
        # REST /team-status and WS team_status events include role/display_name.
        await self._send_graph_registered(req.thread_id, graph)
        return graph

    async def _send_graph_registered(
        self, thread_id: str, graph: CompiledStateGraph
    ) -> None:
        """Send a ``graph_registered`` event with node metadata via the bridge.

        The control-surface aggregator uses this to populate its
        ``_node_metadata`` cache so that ``emit_team_status`` and the REST
        ``/team-status`` endpoint include role/display_name/description.
        """
        nodes: dict[str, dict[str, str]] = {}
        for node_name, node_spec in getattr(graph, "nodes", {}).items():
            meta = getattr(node_spec, "metadata", None) or {}
            if meta:
                nodes[node_name] = {
                    "role": str(meta.get("role", "")),
                    "display_name": str(meta.get("display_name", "")),
                    "description": str(meta.get("description", "")),
                }
        if nodes:
            await self._bridge.send_event(
                thread_id,
                {"type": "graph_registered", "nodes": nodes},
            )

    # ------------------------------------------------------------------
    # Graph compilation
    # ------------------------------------------------------------------

    def _compile_graph(self, req: DispatchRequest) -> CompiledStateGraph:
        """Load team/agent configs and compile a LangGraph ``StateGraph``.

        Uses the same two-level config discovery order as the monolith:
        workspace override then bundled preset.
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
            proposal_submitter = self._build_proposal_submitter()
            feedback_reader = self._build_feedback_reader()

        # CLI-coder presets that arm the engine authoring bridge get a per-run
        # binding provider, built here behind the same fail-closed contract as the
        # submitter: a run that cannot reach the engine to fetch its catalog never
        # starts vague. Only a coding topology can arm this (the config validator
        # rejects authoring_bridge on document-authoring presets).
        authoring_binding_provider = None
        harness = team_config.effective_harness()
        if harness is not None and harness.authoring_bridge:
            authoring_binding_provider = self._build_authoring_binding_provider()

        # Compile gate (agent-harness-provisioning isolation invariant): an ARMED
        # preset - one declaring the authoring bridge OR harness MCP servers - can
        # only bind its declared MCP surface if the run spawns inside an isolated
        # CLI config home, and that isolation is established from an env-carried
        # provider token. If an armed worker's config-home lane resolves to
        # auth_mode "none_detected" the run would spawn UNISOLATED and inherit
        # ambient + workspace .mcp.json (the S20 leak), so refuse here - the outer
        # compile wrapper turns this into a GraphCompilationError. The predicate
        # matches authoring_bridge presets (e.g. vaultspec-solo-coder, which may
        # declare no harness mcp_servers yet is exactly the leak surface).
        armed = harness is not None and (
            harness.authoring_bridge or bool(harness.mcp_servers)
        )
        if armed:
            assert_armed_lanes_authenticated(
                team_config,
                agent_configs,
                ws_root,
                provider_factory=self._provider_factory,
            )

        return compile_team_graph(
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
            provider_factory=self._provider_factory,
            proposal_submitter=proposal_submitter,
            feedback_reader=feedback_reader,
            authoring_binding_provider=authoring_binding_provider,
            # Compile against the run's frozen effective assignment so a
            # restart reproduces the exact launched models.
            model_assignment=req.model_assignment,
        )

    def _build_proposal_submitter(self) -> DocumentProposalSubmitter:
        """Construct the production authoring submitter for a research_adr run.

        Fails closed at build time: a research_adr run whose engine origin cannot
        be resolved never starts vaguely — the typed error propagates as a
        ``GraphCompilationError`` and a truthful run failure. The per-role tokens
        the submitter reads at call time come from this worker's
        :class:`RunTokenStore`; the engine bearer and the writer document body are
        resolved per run from the store and graph state, so the cached graph is
        reused safely across runs. The phase specs map each document phase to the
        graph writer node whose ``AIMessage.name`` carries the document
        (``synthesis``/``adr_author``, the ``_RA_*`` node names in the compiler)
        and to the role whose actor token authors it. The role key is the worker
        ``agent_id`` (``vaultspec-synthesist``/``vaultspec-adr-author``), matching
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
        # run that succeeds seconds later. Blocking is acceptable here - this
        # path already blocks for the heavy graph compile itself.
        engine = resolve_engine_with_retry()
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
            },
        )

    def _build_authoring_binding_provider(self) -> AuthoringBindingProvider:
        """Construct the per-run authoring-bridge binding provider for a coding run.

        Fails closed at build time exactly like the submitter: a bridged run whose
        engine origin cannot be resolved never starts vaguely - the typed
        ``EngineUnavailableError`` is wrapped into a ``GraphCompilationError`` by
        the compile guard. The provider reads the run's per-role tokens from this
        worker's :class:`RunTokenStore` at binding time and caches the engine
        catalog once per run in the shared :class:`RunCatalogStore`, so every
        worker in the run shares one fetch.
        """
        from ..authoring import EngineUnavailableError, resolve_engine_with_retry
        from .authoring_binding import AuthoringBindingProvider

        engine = resolve_engine_with_retry()
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

        The read-path companion to the submitter (edge ADR D5, feedback-loop D4):
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
