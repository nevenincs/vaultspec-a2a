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
from ..graph.compiler import compile_team_graph, resolve_model_for_worker
from ..ipc.schemas import canonical_project_root
from ..providers.team_selection import model_assignment_digest
from ..providers.warmup import warm_model_imports
from ..streaming import StreamableGraph, node_metadata_from_graph
from ..team.team_config import (
    AgentConfig,
    TopologyType,
)
from ..telemetry import ws_span
from ..thread.errors import (
    ConfigError,
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
    "RegisteredCompiledGraph",
    "graph_cache_key",
]


class GraphCompilationError(RuntimeError):
    """Raised when a team graph fails to compile."""


logger = logging.getLogger(__name__)

# Public type for the graph cache key.  The explicit registration seam lets
# real-behavior tests install a pre-compiled graph without reaching mutable
# cache dictionaries.
type GraphCacheKey = tuple[str, str | None, bool, str, str]


def graph_cache_key(
    team_preset: str,
    workspace_root: str | None,
    autonomous: bool,
    assignment_digest: str,
    graph_definition_digest: str,
) -> GraphCacheKey:
    """Form the cache key for a compiled team graph.

    The single site that builds a key, so the workspace element is always the
    run's canonical project spelling and the final element binds the complete
    catalog-frozen compiler assignment. Keys are compared as plain tuples, so two
    spellings of one directory used to occupy two entries: a run's first
    dispatch keyed on a locally re-resolved path while every later dispatch
    keyed on the spelling stored at admission, and the first follow-up on a
    thread whose entry had been evicted recompiled the identical graph under a
    second key. Minting here collapses them to one entry - and holds even for a
    key handed in through the registration seam, which does not cross the
    dispatch wire and so is not minted by it.
    """
    return (
        team_preset,
        canonical_project_root(workspace_root) if workspace_root else None,
        autonomous,
        assignment_digest,
        graph_definition_digest,
    )


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

    A no-op when *harness* does not arm the authoring bridge. The scope is
    authoring_bridge specifically because the mcp_servers-only case fails
    SOFTLY: ``compose_harness_mcp_servers`` returns a model with no delivery
    mechanism unchanged rather than raising, so there is no per-turn error for a
    compile-time gate to pull forward. That is a weaker guarantee than a gate,
    and it is deliberately not restated as one here - this docstring previously
    claimed the mcp_servers path was "already proven to reach every known
    provider", which was untrue on three of the four topologies at the time it
    was written, because only the research_adr compiler read the declaration at
    all. The forwarding now happens in every worker-compiling topology; what
    remains unguarded here is a lane whose model exposes neither delivery
    surface, and that stays a silent no-op by design rather than by omission.
    """
    if harness is None or not harness.authoring_bridge:
        return
    unsupported: list[str] = []
    for worker_ref in team_config.workers:
        agent_config = agent_configs.get(worker_ref.agent_id)
        if agent_config is None:
            continue
        try:
            model, _resolved_provider, _frozen_model = resolve_model_for_worker(
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
        checkpoint_read_timeout_seconds: float | None = None,
    ) -> None:
        from ..database import get_session_factory
        from ..providers.factory import ProviderFactory
        from .cost_port import SqlCostPort
        from .task_queue_port import SqlTaskQueuePort

        self._checkpointer = checkpointer
        self._checkpoint_read_timeout_seconds = (
            checkpoint_read_timeout_seconds
            if checkpoint_read_timeout_seconds is not None
            else domain_config.aget_state_timeout_seconds
        )
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
        # Assignment identity outlives LRU entries. Per-thread locks make the
        # first binding atomic across duplicate/concurrent dispatch delivery.
        self._thread_compilation_digests: dict[str, tuple[str, str]] = {}
        self._thread_compile_locks: dict[str, asyncio.Lock] = {}
        self._thread_compile_lock_users: dict[str, int] = {}
        # Threads bind their durable assignment before joining this second,
        # exact-key flight. This prevents equivalent first dispatches for
        # different threads from compiling the same provider graph in parallel.
        self._cache_key_compile_locks: dict[GraphCacheKey, asyncio.Lock] = {}
        self._cache_key_compile_lock_users: dict[GraphCacheKey, int] = {}

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

    @property
    def thread_binding_count(self) -> int:
        """Number of non-terminal thread identities retained by this worker."""
        return len(self._thread_compilation_digests)

    @property
    def compile_flight_count(self) -> int:
        """Number of exact cache keys with compilation callers in flight."""
        return len(self._cache_key_compile_locks)

    @property
    def thread_compile_lock_count(self) -> int:
        """Number of thread-scoped first-dispatch callers in flight."""
        return len(self._thread_compile_locks)

    def release_thread(self, thread_id: str) -> None:
        """Release terminal thread identity without evicting a shared graph."""
        self._thread_to_cache_key.pop(thread_id, None)
        self._thread_compilation_digests.pop(thread_id, None)

    def clear(self) -> None:
        """Clear all cached graphs and thread mappings."""
        self._graph_cache.clear()
        self._thread_to_cache_key.clear()
        self._thread_compilation_digests.clear()
        self._thread_compile_locks.clear()
        self._thread_compile_lock_users.clear()
        self._cache_key_compile_locks.clear()
        self._cache_key_compile_lock_users.clear()

    def evict_cached_graphs(self) -> None:
        """Evict compiled graphs while retaining immutable thread bindings."""
        self._graph_cache.clear()

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
        That invariant includes the project spelling: an injected key is minted
        here so a graph installed through this seam shares the entry a dispatch
        for the same workspace would find, rather than shadowing it.
        """
        cache_key = graph_cache_key(*cache_key)
        bound = self._thread_compilation_digests.get(thread_id)
        if bound is not None and bound != (cache_key[3], cache_key[4]):
            raise GraphCompilationError(
                "dispatch compilation authority does not match the bound run"
            )
        self._thread_compilation_digests[thread_id] = (cache_key[3], cache_key[4])
        while (
            cache_key not in self._graph_cache
            and len(self._graph_cache) >= domain_config.max_cached_graphs
        ):
            self._graph_cache.popitem(last=False)
        self._graph_cache[cache_key] = graph
        self._graph_cache.move_to_end(cache_key)
        self._thread_to_cache_key[thread_id] = cache_key
        self._aggregator.register_graph(thread_id, graph)

    # ------------------------------------------------------------------
    # Graph cache lookup and compilation
    # ------------------------------------------------------------------

    async def get_or_compile_graph(
        self,
        req: DispatchRequest,
        *,
        checkpoint_deadline: float | None = None,
    ) -> RegisteredCompiledGraph | None:
        """Return a compiled graph for *req*, using the LRU cache.

        If the thread already maps to a cached graph, return it (LRU touch).
        If the preset is known but no graph is cached (eviction or first use),
        compile a new one, cache it, and register with the aggregator.
        Missing accepted graph authority is a compilation refusal.
        """
        lock = self._thread_compile_locks.setdefault(req.thread_id, asyncio.Lock())
        self._thread_compile_lock_users[req.thread_id] = (
            self._thread_compile_lock_users.get(req.thread_id, 0) + 1
        )
        try:
            async with lock:
                return await self._get_or_compile_graph_locked(
                    req, checkpoint_deadline=checkpoint_deadline
                )
        finally:
            users = self._thread_compile_lock_users[req.thread_id] - 1
            if users == 0:
                self._thread_compile_lock_users.pop(req.thread_id, None)
                self._thread_compile_locks.pop(req.thread_id, None)
            else:
                self._thread_compile_lock_users[req.thread_id] = users

    async def _resume_checkpoint_missing(
        self,
        req: DispatchRequest,
        bound: tuple[str, str] | None,
        checkpoint_digest: tuple[str, str] | None,
        checkpoint_deadline: float | None,
    ) -> bool:
        if req.action != "resume" or checkpoint_digest is not None:
            return False
        if bound is None:
            return True
        return not await self._checkpoint_present(
            req.thread_id, checkpoint_deadline=checkpoint_deadline
        )

    async def _bind_compilation_authority(
        self,
        req: DispatchRequest,
        compilation_digests: tuple[str, str],
        checkpoint_deadline: float | None,
    ) -> bool:
        """Verify durable and bound compilation identities before cache lookup."""
        bound = self._thread_compilation_digests.get(req.thread_id)
        checkpoint_digest = (
            await self._checkpoint_compilation_digests(
                req.thread_id, checkpoint_deadline=checkpoint_deadline
            )
            if bound is None
            else None
        )
        if await self._resume_checkpoint_missing(
            req, bound, checkpoint_digest, checkpoint_deadline
        ):
            return False
        if bound is None:
            if (
                checkpoint_digest is not None
                and checkpoint_digest != compilation_digests
            ):
                raise GraphCompilationError(
                    "dispatch compilation authority does not match the durable run"
                )
            self._thread_compilation_digests[req.thread_id] = compilation_digests
        elif bound != compilation_digests:
            raise GraphCompilationError(
                "dispatch compilation authority does not match the bound run"
            )
        elif checkpoint_digest is not None and checkpoint_digest != compilation_digests:
            raise GraphCompilationError(
                "dispatch compilation authority does not match the durable run"
            )
        return True

    async def _get_or_compile_graph_locked(
        self,
        req: DispatchRequest,
        *,
        checkpoint_deadline: float | None,
    ) -> RegisteredCompiledGraph | None:
        """Resolve one graph while holding the thread's first-dispatch lock."""
        if not req.model_assignment:
            raise GraphCompilationError(
                "graph execution requires an exact current model assignment"
            )
        try:
            definition = req.require_graph_definition()
        except ValueError as exc:
            raise GraphCompilationError(str(exc)) from exc
        definition_digest = definition.digest()
        assignment_digest = model_assignment_digest(req.model_assignment)
        compilation_digests = (assignment_digest, definition_digest)
        if not await self._bind_compilation_authority(
            req, compilation_digests, checkpoint_deadline
        ):
            return None

        # Check if thread already has a cached graph. A thread's accepted
        # assignment is immutable; changing it under the same identity is a
        # structural dispatch error, never a reason to reuse or replace a graph.
        cache_key = self._thread_to_cache_key.get(req.thread_id)
        if cache_key and cache_key in self._graph_cache:
            if (cache_key[3], cache_key[4]) != compilation_digests:
                raise GraphCompilationError(
                    "dispatch compilation authority does not match the compiled run"
                )
            self._graph_cache.move_to_end(cache_key)
            return self._graph_cache[cache_key]

        team_preset = definition.team_id
        workspace_root = req.workspace_root
        autonomous = req.autonomous
        new_key = graph_cache_key(
            team_preset,
            workspace_root,
            autonomous,
            assignment_digest,
            definition_digest,
        )

        graph = await self._get_or_compile_cache_key(req, new_key, team_preset)
        self._thread_to_cache_key[req.thread_id] = new_key
        self._aggregator.register_graph(req.thread_id, graph)
        # Relay node metadata to the control-surface aggregator so
        # REST /team-status and WS team_status events include role/display_name.
        await self._send_graph_registered(req.thread_id, graph)
        return graph

    async def _get_or_compile_cache_key(
        self,
        req: DispatchRequest,
        cache_key: GraphCacheKey,
        team_preset: str,
    ) -> RegisteredCompiledGraph:
        """Compile one exact graph key once across all concurrent threads."""
        lock = self._cache_key_compile_locks.setdefault(cache_key, asyncio.Lock())
        self._cache_key_compile_lock_users[cache_key] = (
            self._cache_key_compile_lock_users.get(cache_key, 0) + 1
        )
        try:
            async with lock:
                cached = self._graph_cache.get(cache_key)
                if cached is not None:
                    self._graph_cache.move_to_end(cache_key)
                    return cached

                async with ws_span(
                    "executor.compile_graph", thread_id=req.thread_id
                ) as span:
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

                while len(self._graph_cache) >= domain_config.max_cached_graphs:
                    self._graph_cache.popitem(last=False)
                self._graph_cache[cache_key] = graph
                return graph
        finally:
            users = self._cache_key_compile_lock_users[cache_key] - 1
            if users == 0:
                self._cache_key_compile_lock_users.pop(cache_key, None)
                self._cache_key_compile_locks.pop(cache_key, None)
            else:
                self._cache_key_compile_lock_users[cache_key] = users

    async def _checkpoint_present(
        self, thread_id: str, *, checkpoint_deadline: float | None
    ) -> bool:
        """Check that a bound resume has a durable checkpoint to resume."""
        timeout = self._checkpoint_read_timeout_seconds
        if checkpoint_deadline is not None:
            timeout = min(
                timeout, checkpoint_deadline - asyncio.get_running_loop().time()
            )
        if timeout <= 0:
            raise GraphCompilationError("durable checkpoint read timed out")
        try:
            checkpoint_tuple = await asyncio.wait_for(
                self._checkpointer.aget_tuple(
                    {"configurable": {"thread_id": thread_id}}
                ),
                timeout=timeout,
            )
        except TimeoutError as exc:
            raise GraphCompilationError("durable checkpoint read timed out") from exc
        return checkpoint_tuple is not None

    async def _checkpoint_compilation_digests(
        self, thread_id: str, *, checkpoint_deadline: float | None
    ) -> tuple[str, str] | None:
        """Read and validate the current assignment binding from checkpoint state."""
        timeout = self._checkpoint_read_timeout_seconds
        if checkpoint_deadline is not None:
            timeout = min(
                timeout, checkpoint_deadline - asyncio.get_running_loop().time()
            )
        if timeout <= 0:
            raise GraphCompilationError("durable checkpoint read timed out")
        try:
            checkpoint_tuple = await asyncio.wait_for(
                self._checkpointer.aget_tuple(
                    {"configurable": {"thread_id": thread_id}}
                ),
                timeout=timeout,
            )
        except TimeoutError as exc:
            raise GraphCompilationError("durable checkpoint read timed out") from exc
        if checkpoint_tuple is None:
            return None
        checkpoint = getattr(checkpoint_tuple, "checkpoint", None)
        if not isinstance(checkpoint, dict):
            raise GraphCompilationError("durable checkpoint state is incompatible")
        checkpoint_obj = cast("dict[str, object]", checkpoint)
        values = checkpoint_obj.get("channel_values")
        if not isinstance(values, dict):
            raise GraphCompilationError("durable checkpoint state is incompatible")
        values_obj = cast("dict[str, object]", values)
        digests: list[str] = []
        for field in ("model_assignment_digest", "graph_definition_digest"):
            digest = values_obj.get(field)
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)
            ):
                raise GraphCompilationError(
                    "durable compilation authority is incompatible"
                )
            digests.append(digest)
        return digests[0], digests[1]

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
        """Compile the accepted program without rereading team or agent files.

        Provider imports and authoring-service discovery are offloaded before
        synchronous compilation. Neither operation supplies compiler authority.
        """
        # No re-resolution here: the project was minted when the dispatch was
        # validated, and re-deriving it is what let compilation disagree with
        # the cache key it was compiled under.
        ws_root = Path(req.workspace_root) if req.workspace_root else None

        definition = req.require_graph_definition()
        team_config, agent_configs, supervisor_config = definition.compiler_inputs()

        # Everything below reaches ``ProviderFactory.create``, which loads the
        # LangChain and ACP model stack on first use - seconds of pure import
        # work with no await in it, on this event loop. Paying it on a thread
        # first is what keeps the worker answering /health and a second dispatch
        # while a run boots; once warm the call is a dict lookup, so a later
        # compile pays nothing for it.
        await asyncio.to_thread(warm_model_imports)

        # Document-phase topologies author through the engine; build the
        # production submitter here, the single construction site, and fail closed
        # at build time when the run cannot author (so it never starts vague). The
        # feedback reader is the read-path companion (best-effort, not fail-closed):
        # it grounds the document writers on a revision run's reviewer batch.
        #
        # KEYED ON TOPOLOGY ON PURPOSE, and it must stay that way. The question
        # here is a MECHANISM one - "does this preset submit over the direct
        # worker-to-engine HTTP path?" - and only ``research_adr`` does. The solo
        # doc-editor lane also authors documents, but submits through the model's
        # bridged tool instead, so it correctly gets no submitter here.
        #
        # The served ``authoring_capability`` field asks a DIFFERENT question -
        # "does this preset author documents?" - and is keyed on declared ROLES,
        # so it answers ``document_authoring`` for that same doc-editor lane. The
        # two therefore DISAGREE for the doc-editor, and both are right.
        #
        # If you arrived here debugging a run that authored nothing, that
        # disagreement is not the bug and making these two agree is not the fix:
        # this gate is why the bridged lane submits by a different route, and
        # aligning it would either strand the served field on a wrong answer again
        # or hand a submitter to a lane that does not use one. They agreed once,
        # when one topology key answered both questions - and answered this one's
        # neighbour wrongly.
        proposal_submitter = None
        feedback_reader = None
        if team_config.topology.type == TopologyType.RESEARCH_ADR:
            proposal_submitter = await self._build_proposal_submitter(ws_root)
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
        # reports its own failure at run time. The declared-surface invariant is
        # enforced at spawn by the run-workspace MCP projection and confinement
        # settings, not by refusing the run for a missing credential.
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
                step_timeout=definition.step_timeout_seconds,
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

    async def _build_proposal_submitter(
        self, workspace_root: Path | None
    ) -> DocumentProposalSubmitter:
        """Construct the production authoring submitter for a research_adr run.

        The submitter is bound to *workspace_root* - the run's minted active
        project - so the authoring session it opens is authorised against the
        project that authored the proposals rather than whichever workspace the
        engine happens to hold active when a command lands. A graph is cached
        per project, so a submitter built alongside one stays bound to it.

        Fails closed at build time: a research_adr run whose engine origin cannot
        be resolved, or which names no project to author into, never starts
        vaguely — the typed error propagates as a ``GraphCompilationError`` and a
        truthful run failure. The per-role tokens
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

        if workspace_root is None:
            raise ConfigError(
                "a document-authoring run must name the project it authors into; "
                "this dispatch carried no active project, so the authoring "
                "session would open against whatever workspace the engine holds "
                "active at command time"
            )

        # Bounded poll, not a one-shot probe: the engine has measured multi-
        # second stall windows (scope-watcher rebuilds) during which a single
        # 3s /health probe misses a healthy engine and would truthfully fail a
        # run that succeeds seconds later. Offloaded via to_thread rather than
        # made async in place: resolve_engine_with_retry is a plain blocking
        # function (time.sleep + a sync httpx probe, by its own design, reused
        # by non-async callers too) and this is the one call site that runs on
        # a live event loop — a worker's own step_timeout and the ingest
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
            workspace_root=workspace_root,
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

        The run's active project is written on EVERY turn, not only the first.
        ``TeamState`` has always declared the key as threaded in from here, and
        nothing wrote it, so the two nodes that read it fell through to their
        compile-time closure every time and the declaration was a dead one. It
        carries no reducer, so an unconditional write is last-write-wins over an
        identity that cannot change within a thread - the graph is cached per
        project - which also repairs a checkpoint written before this key was
        ever populated. The value is the project the dispatch was minted with:
        an ingest that names none is refused at the wire, and this is only ever
        called for an ingest.

        This is a truthful state contract, NOT an authority. Compilation's
        explicit workspace argument remains the binding for every scoped
        behaviour; consumers must keep preferring it and reading state only as
        the fallback it already is.

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
            "workspace_root": req.workspace_root,
            "model_assignment_digest": model_assignment_digest(req.model_assignment),
            "graph_definition_digest": req.require_graph_definition().digest(),
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
