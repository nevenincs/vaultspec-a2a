"""Graph execution engine -- manages LangGraph run lifecycle (ADR-031).

Owns the graph registry (compiled ``CompiledStateGraph`` instances),
``EventAggregator``, and checkpointer.  Dispatches events to the
gateway via ``WorkerBridge``.

The executor is the worker-process analogue of the monolith's
``GraphRegistry`` + endpoint ingest logic, restructured for the
separated-process architecture.
"""

from __future__ import annotations

import asyncio
import logging

from collections import OrderedDict
from pathlib import Path
from typing import Any, cast

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from ..api.schemas.internal import DispatchRequest
from ..core import (
    AgentConfig,
    AgentConfigNotFoundError,
    EventAggregator,
    StreamableGraph,
    TeamConfigNotFoundError,
    compile_team_graph,
    load_agent_config,
    load_team_config,
    settings,
)
from .ipc import WorkerBridge


__all__ = ["ConcurrentCapError", "Executor"]


class ConcurrentCapError(RuntimeError):
    """Raised when the worker concurrent thread cap is reached (WPA-001)."""


logger = logging.getLogger(__name__)

# Match the recursion limit used by the control-surface endpoints.
_GRAPH_RECURSION_LIMIT = 100

# WPA-001: Default cap; overridden by settings.max_concurrent_threads.
_DEFAULT_MAX_CONCURRENT_THREADS = 5

# Maximum number of compiled graphs kept in the LRU cache.
# Threads sharing the same (team_preset, workspace_root, autonomous) key
# reuse a single CompiledStateGraph — thread isolation comes from
# thread_id in the checkpointer config, not from the graph object.
_MAX_CACHED_GRAPHS = 32

# Type alias for the graph cache key.
_CacheKey = tuple[str, str | None, bool]


class Executor:
    """Compiles and runs LangGraph graphs, dispatching events via IPC bridge.

    The executor maintains:

    * An LRU ``OrderedDict`` mapping ``(team_preset, workspace_root, autonomous)``
      to compiled ``CompiledStateGraph``.  Threads with identical config share
      one graph (thread isolation comes from the checkpointer's ``thread_id``).
    * A ``dict[str, _CacheKey]`` mapping thread_id to its cache key.
    * An ``EventAggregator`` that drives the ``astream_events`` consumer loop.
    * A set of ``_active_ingests`` guarded by an ``asyncio.Lock`` to prevent
      concurrent graph execution on the same thread (which would race on
      checkpointer state).

    Parameters
    ----------
    checkpointer:
        ``AsyncSqliteSaver`` shared with the gateway (WAL mode).
    bridge:
        ``WorkerBridge`` for forwarding events and heartbeats.
    """

    def __init__(
        self,
        checkpointer: AsyncSqliteSaver,
        bridge: WorkerBridge,
    ) -> None:
        self._checkpointer = checkpointer
        self._bridge = bridge
        self._graph_cache: OrderedDict[_CacheKey, CompiledStateGraph] = OrderedDict()
        # Maps thread_id -> cache key so _handle_resume can find the graph
        # and recompile if evicted.
        self._thread_to_cache_key: dict[str, _CacheKey] = {}
        self._aggregator = EventAggregator()

        # Wire bridge relay: every broadcast event is forwarded to the control
        # surface via HTTP (ADR-031).  Closure captures bridge reference.
        _bridge_ref = bridge

        async def _relay_event(event: Any) -> None:
            thread_id = getattr(event, "thread_id", "")
            if thread_id:
                await _bridge_ref.send_event(thread_id, event.model_dump())

        self._aggregator.add_broadcast_hook(_relay_event)

        self._active_ingests: set[str] = set()
        self._ingest_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    @property
    def aggregator(self) -> EventAggregator:
        """Return the event aggregator (for subscriber wiring, if needed)."""
        return self._aggregator

    @property
    def graph_count(self) -> int:
        """Number of compiled graphs currently held."""
        return len(self._graph_cache)

    @property
    def active_ingest_count(self) -> int:
        """Number of concurrently active graph ingests."""
        return len(self._active_ingests)

    def at_capacity(self) -> bool:
        """Return True if the concurrent thread cap has been reached."""
        cap = settings.max_concurrent_threads
        return len(self._active_ingests) >= cap

    # ------------------------------------------------------------------
    # Ingest gating (same pattern as the monolith's GraphRegistry)
    # ------------------------------------------------------------------

    async def _mark_ingest_active(self, thread_id: str) -> bool:
        """Attempt to acquire the ingest slot for *thread_id*.

        Returns ``True`` on success.  Returns ``False`` if another ingest
        is already running for the same thread.
        """
        async with self._ingest_lock:
            if thread_id in self._active_ingests:
                return False
            self._active_ingests.add(thread_id)
            return True

    async def _mark_ingest_done(self, thread_id: str) -> None:
        """Release the ingest slot and untrack the thread in the bridge."""
        async with self._ingest_lock:
            self._active_ingests.discard(thread_id)
        self._bridge.untrack_thread(thread_id)

    # ------------------------------------------------------------------
    # Dispatch routing
    # ------------------------------------------------------------------

    async def handle_dispatch(self, req: DispatchRequest) -> None:
        """Route a ``DispatchRequest`` to the appropriate handler.

        Supported actions:

        * ``ingest``  -- compile graph (if needed) and run a new user turn.
        * ``resume``  -- resume a suspended graph from a LangGraph interrupt.
        * ``cancel``  -- signal cancellation for a running ingest.
        """
        match req.action:
            case "ingest":
                await self._handle_ingest(req)
            case "resume":
                await self._handle_resume(req)
            case "cancel":
                self._aggregator.cancel_thread(req.thread_id)
            case _:
                logger.warning("Unknown dispatch action: %s", req.action)

    # ------------------------------------------------------------------
    # Ingest handler
    # ------------------------------------------------------------------

    async def _get_or_compile_graph(
        self, req: DispatchRequest
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

        # Resolve preset — from request or previously stored mapping.
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
        try:
            graph = self._compile_graph(req)
        except Exception:
            logger.exception(
                "Failed to compile graph for thread %s (preset=%s)",
                req.thread_id,
                team_preset,
            )
            return None

        # Evict LRU if at capacity.
        while len(self._graph_cache) >= _MAX_CACHED_GRAPHS:
            self._graph_cache.popitem(last=False)

        self._graph_cache[new_key] = graph
        self._thread_to_cache_key[req.thread_id] = new_key
        self._aggregator.register_graph(cast(StreamableGraph, graph))
        # BE-12: relay node metadata to the control-surface aggregator so
        # REST /team-status and WS team_status events include role/display_name.
        await self._send_graph_registered(req.thread_id, graph)
        return graph

    async def _send_graph_registered(
        self, thread_id: str, graph: CompiledStateGraph
    ) -> None:
        """Send a ``graph_registered`` event with node metadata via the bridge.

        The control-surface aggregator uses this to populate its
        ``_node_metadata`` cache so that ``emit_team_status`` and the REST
        ``/team-status`` endpoint include role/display_name/description (BE-12).
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

    async def _handle_ingest(self, req: DispatchRequest) -> None:
        """Compile graph on first use and execute a new user turn."""
        is_first_ingest = req.thread_id not in self._thread_to_cache_key

        graph = await self._get_or_compile_graph(req)
        if graph is None:
            logger.warning("No graph for thread %s -- cannot ingest", req.thread_id)
            return

        if not await self._mark_ingest_active(req.thread_id):
            logger.warning(
                "Ingest already active for thread %s -- dropping", req.thread_id
            )
            return

        self._bridge.track_thread(req.thread_id)

        # Build graph input
        messages: list[SystemMessage | HumanMessage] = []
        if req.context_preamble:
            messages.append(SystemMessage(content=req.context_preamble))
        if req.content:
            messages.append(HumanMessage(content=req.content))

        # For initial thread creation, supply all required TeamState fields so
        # the checkpointer has a clean starting state.  For follow-up messages,
        # omit current_plan, active_agent, artifacts and token_usage so
        # LangGraph preserves the checkpoint values — supplying current_plan=[]
        # would trigger the _replace_plan reducer's "clear" sentinel and wipe
        # the supervisor's execution plan.
        graph_input: dict[str, Any] = {"messages": messages, "thread_id": req.thread_id}
        if is_first_ingest:
            graph_input.update(
                {
                    "active_agent": "",
                    "artifacts": [],
                    "current_plan": [],
                    "token_usage": {},
                }
            )
            # ADR-019 SDD blackboard fields (MED-01): pass through to TeamState
            # so vault context reaches the graph on initial thread creation.
            if req.active_feature:
                graph_input["active_feature"] = req.active_feature
            if req.pipeline_phase:
                graph_input["pipeline_phase"] = req.pipeline_phase
            if req.vault_index:
                graph_input["vault_index"] = req.vault_index
            if req.validation_errors:
                graph_input["validation_errors"] = req.validation_errors
        config = {
            "configurable": {"thread_id": req.thread_id},
            "recursion_limit": req.recursion_limit or _GRAPH_RECURSION_LIMIT,
        }

        agent_id = req.agent_id or "vaultspec-supervisor"

        try:
            outcome = await self._aggregator.ingest(
                req.thread_id,
                agent_id,
                cast(StreamableGraph, graph),
                graph_input,
                config,
            )
        except Exception:
            outcome = "failed"
            logger.exception("Ingest failed for thread %s", req.thread_id)
        finally:
            await self._emit_terminal_status(req.thread_id, outcome)
            await self._mark_ingest_done(req.thread_id)

    # ------------------------------------------------------------------
    # Resume handler (permission response)
    # ------------------------------------------------------------------

    async def _handle_resume(self, req: DispatchRequest) -> None:
        """Resume a graph from a LangGraph interrupt.

        Uses ``Command(resume=option_id)`` as graph input, which causes the
        ``interrupt()`` call in the worker node to return the chosen option.
        """
        graph = await self._get_or_compile_graph(req)
        if graph is None:
            logger.warning("No graph for thread %s -- cannot resume", req.thread_id)
            return

        if not await self._mark_ingest_active(req.thread_id):
            logger.warning(
                "Ingest already active for thread %s -- cannot resume", req.thread_id
            )
            return

        self._bridge.track_thread(req.thread_id)

        # Resolve recursion_limit: explicit request > team TOML > global default.
        cache_key = self._thread_to_cache_key.get(req.thread_id)
        team_preset = cache_key[0] if cache_key else req.team_preset
        ws_root = (
            Path(cache_key[1]).resolve()
            if cache_key and cache_key[1]
            else (Path(req.workspace_root).resolve() if req.workspace_root else None)
        )
        team_recursion_limit: int | None = None
        if team_preset:
            try:
                team_cfg = load_team_config(team_preset, workspace_root=ws_root)
                team_recursion_limit = team_cfg.graph.recursion_limit
            except Exception:
                logger.debug("Could not load team config for recursion_limit fallback")
        effective_recursion_limit = (
            req.recursion_limit or team_recursion_limit or _GRAPH_RECURSION_LIMIT
        )
        config = {
            "configurable": {"thread_id": req.thread_id},
            "recursion_limit": effective_recursion_limit,
        }
        agent_id = req.agent_id or "vaultspec-supervisor"

        try:
            # Command(resume=...) is accepted by astream_events in place of
            # a dict graph_input -- LangGraph handles the type internally.
            outcome = await self._aggregator.ingest(
                req.thread_id,
                agent_id,
                cast(StreamableGraph, graph),
                Command(resume=req.option_id),
                config,
            )
        except Exception:
            outcome = "failed"
            logger.exception("Resume failed for thread %s", req.thread_id)
        finally:
            await self._emit_terminal_status(req.thread_id, outcome)
            await self._mark_ingest_done(req.thread_id)

    # ------------------------------------------------------------------
    # Terminal status relay
    # ------------------------------------------------------------------

    async def _emit_terminal_status(self, thread_id: str, outcome: str) -> None:
        """Emit a ``thread_terminal`` event to the gateway.

        Emits for ``"completed"``, ``"failed"``, and ``"cancelled"`` outcomes.
        ``"interrupted"`` means the graph is suspended (awaiting permission)
        and the thread should remain ``RUNNING``.
        """
        if outcome not in ("completed", "failed", "cancelled"):
            return
        await self._bridge.send_event(
            thread_id,
            {
                "event_type": "thread_terminal",
                "thread_id": thread_id,
                "status": outcome,
            },
        )

    # ------------------------------------------------------------------
    # Graph compilation
    # ------------------------------------------------------------------

    def _compile_graph(self, req: DispatchRequest) -> CompiledStateGraph:
        """Load team/agent configs and compile a LangGraph ``StateGraph``.

        Uses the same two-level config discovery order as the monolith:
        workspace override then bundled preset (ADR-012 section 2.8).
        """
        ws_root = Path(req.workspace_root).resolve() if req.workspace_root else None

        try:
            team_config = load_team_config(
                cast(str, req.team_preset), workspace_root=ws_root
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
                logger.warning("Agent config not found for %s", worker_ref.agent_id)

        supervisor_config: AgentConfig | None = None
        if team_config.topology.type in ("star", "pipeline_loop"):
            try:
                supervisor_config = load_agent_config(
                    "supervisor", workspace_root=ws_root
                )
            except AgentConfigNotFoundError:
                logger.debug("No supervisor config; using defaults")

        return compile_team_graph(
            team_config=team_config,
            agent_configs=agent_configs,
            checkpointer=self._checkpointer,
            supervisor_agent_config=supervisor_config,
            workspace_root=ws_root,
            autonomous=req.autonomous,
            # Let compile_team_graph use team_config.graph.step_timeout_seconds
            step_timeout=None,
            # MED-05: thread feature_tag so vault indexing works in worker
            feature_tag=req.active_feature,
        )

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def shutdown(self) -> None:
        """Release held resources (aggregator debounce tasks, etc.)."""
        await self._aggregator.shutdown()
        self._graph_cache.clear()
        self._thread_to_cache_key.clear()
