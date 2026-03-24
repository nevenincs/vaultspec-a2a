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
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import Command, StateSnapshot

from ..api.event_adapter import sequenced_to_dict
from ..api.schemas.internal import (
    DispatchRequest,
    ExecutionStateProjectionPayload,
    ExecutionTaskProjectionPayload,
)
from ..control.config import settings
from ..graph.compiler import compile_team_graph
from ..streaming.aggregator import EventAggregator, SequencedEvent, StreamableGraph
from ..team.team_config import AgentConfig, load_agent_config, load_team_config
from ..telemetry import ws_span
from ..thread.errors import AgentConfigNotFoundError, TeamConfigNotFoundError

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

    from ..database.checkpoints import Checkpointer
    from .ipc import WorkerBridge

__all__ = ["ConcurrentCapError", "Executor", "GraphCompilationError"]


class ConcurrentCapError(RuntimeError):
    """Raised when the worker concurrent thread cap is reached (WPA-001)."""


class GraphCompilationError(RuntimeError):
    """Raised when a team graph fails to compile (WRK-K03)."""


logger = logging.getLogger(__name__)

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
        Shared LangGraph checkpointer opened by the worker lifespan.
    bridge:
        ``WorkerBridge`` for forwarding events and heartbeats.
    """

    def __init__(
        self,
        checkpointer: Checkpointer,
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

        async def _relay_event(sequenced: SequencedEvent) -> None:
            thread_id = getattr(sequenced.event, "thread_id", "")
            if thread_id:
                await _bridge_ref.send_event(thread_id, sequenced_to_dict(sequenced))

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

    def _log_extra(self, **fields: Any) -> dict[str, Any]:
        """Build bounded structured log fields for executor-owned events."""
        extra = {
            "worker_id": getattr(self._bridge, "_worker_id", None),
            "active_thread_count": self.active_ingest_count,
        }
        extra.update(fields)
        return {key: value for key, value in extra.items() if value is not None}

    def _dispatch_log_extra(
        self,
        req: DispatchRequest,
        **fields: Any,
    ) -> dict[str, Any]:
        """Build structured log fields for a dispatch-bound executor event."""
        return self._log_extra(
            thread_id=req.thread_id,
            dispatch_id=req.dispatch_id,
            dispatch_action=req.action,
            agent_id=req.agent_id,
            team_preset=req.team_preset,
            autonomous=req.autonomous,
            **fields,
        )

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
        """Release the ingest slot, untrack in the bridge, and prune aggregator.

        WRK-K02: prune stale permissions and inactive-thread sequences after
        each ingest to prevent unbounded memory growth in long-running workers.
        """
        async with self._ingest_lock:
            self._active_ingests.discard(thread_id)
            active_snapshot = set(self._active_ingests)
        self._bridge.untrack_thread(thread_id)
        # Prune sequences for threads that are no longer actively executing.
        self._aggregator.prune_sequences(active_snapshot)
        # Prune permissions older than 5 minutes regardless of thread state.
        self._aggregator.prune_stale_permissions()

    # ------------------------------------------------------------------
    # Dispatch routing
    # ------------------------------------------------------------------

    async def handle_dispatch(self, req: DispatchRequest) -> None:
        """Route a ``DispatchRequest`` to the appropriate handler.

        Wraps all handler logic in a top-level guard so that no unhandled
        exception can escape into the anyio task group started by the worker
        lifespan.  An escaped exception would cancel every task in the group
        (including the heartbeat loop) and terminate the worker process.
        """
        try:
            async with ws_span(
                f"executor.{req.action}",
                thread_id=req.thread_id,
                agent_id=req.agent_id or "supervisor",
            ) as span:
                match req.action:
                    case "ingest":
                        await self._handle_ingest(req)
                    case "resume":
                        await self._handle_resume(req)
                    case "cancel":
                        span.add_event("thread_cancelled")
                        self._aggregator.cancel_thread(req.thread_id)
                        # If no ingest is active, the cooperative cancel
                        # flag has no listener.  Emit the terminal event
                        # directly so the gateway can transition
                        # cancelling → cancelled.
                        async with self._ingest_lock:
                            is_active = req.thread_id in self._active_ingests
                        # TOCTOU: There is a small window between checking is_active and
                        # emitting the terminal event. If an ingest starts between the
                        # check and the emit, a duplicate terminal event may fire.
                        # This is safe because:
                        # 1. The cooperative cancel flag is set BEFORE the check
                        # 2. The DB transition validator rejects duplicate
                        #    terminal transitions
                        if not is_active:
                            await self._emit_terminal_status(req.thread_id, "cancelled")
                    case _:
                        logger.warning(
                            "Unknown dispatch action: %s",
                            req.action,
                            extra=self._dispatch_log_extra(
                                req,
                                action="unknown_dispatch_action",
                            ),
                        )
                        span.set_attribute("error", True)
                        span.set_attribute(
                            "error.message", f"Unknown action: {req.action}"
                        )
        except Exception:
            logger.exception(
                "Unhandled exception in handle_dispatch (action=%s, thread=%s); "
                "worker task group protected — thread may be stuck in RUNNING",
                req.action,
                req.thread_id,
                extra=self._dispatch_log_extra(
                    req,
                    action="dispatch_unhandled_exception",
                ),
            )

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
        while len(self._graph_cache) >= settings.max_cached_graphs:
            self._graph_cache.popitem(last=False)

        self._graph_cache[new_key] = graph
        self._thread_to_cache_key[req.thread_id] = new_key
        self._aggregator.register_graph(cast("StreamableGraph", graph))
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

    # ------------------------------------------------------------------
    # Pre-flight checkpoint inspection (reconciliation window guard)
    # ------------------------------------------------------------------

    async def _pre_flight_checkpoint(self, thread_id: str) -> tuple[str | None, bool]:
        """Inspect the latest checkpoint before running an ingest.

        Resolves the reconciliation window gap: after a worker restart the
        gateway moves non-terminal threads to ``RECONCILING`` and re-dispatches
        them.  If the thread actually completed or errored *before* the crash
        (checkpoint was written but the DB update was lost), LangGraph would
        silently start another generation.  Inspecting the checkpoint first
        lets us detect and short-circuit these cases.

        Also corrects ``is_first_ingest``: after a restart the in-memory cache
        is empty so every dispatch looks like a first ingest, which would pass
        initial-state fields (``active_agent``, ``artifacts``, ``current_plan``)
        and overwrite accumulated checkpoint values.  Using checkpoint truth
        prevents that overwrite.

        Returns:
            ``(outcome, is_first_ingest)`` where *outcome* is one of:

            * ``None``           — proceed normally with ingest
            * ``"completed"``    — graph ran to END before crash; emit and skip
            * ``"failed"``       — unhandled error before crash; emit and skip
            * ``"interrupted"``  — graph paused at ``interrupt()``; skip and
                                   await a resume dispatch

            *is_first_ingest* is ``True`` only when no prior checkpoint row
            exists (``aget_tuple`` returns ``None``).
        """
        # Sentinel channel constants from langgraph.checkpoint.serde.types.
        interrupt_ch = "__interrupt__"
        error_ch = "__error__"

        try:
            checkpoint_tuple = await asyncio.wait_for(
                self._checkpointer.aget_tuple(
                    {"configurable": {"thread_id": thread_id}}
                ),
                timeout=5.0,
            )
        except Exception:
            logger.warning(
                "Could not inspect checkpoint for thread %s before ingest"
                " — falling back to in-memory heuristic",
                thread_id,
                exc_info=True,
                extra=self._log_extra(
                    thread_id=thread_id,
                    action="checkpoint_preflight_fallback",
                    fallback_strategy="in_memory_heuristic",
                ),
            )
            is_first_ingest = thread_id not in self._thread_to_cache_key
            return None, is_first_ingest

        if checkpoint_tuple is None:
            # No prior checkpoint — genuinely new thread.
            return None, True

        pending_writes = checkpoint_tuple.pending_writes or []
        if not pending_writes:
            # Empty pending_writes: graph ran to END cleanly before crash.
            return "completed", False

        channels = {w[1] for w in pending_writes}
        if error_ch in channels:
            # Unhandled task error flushed to checkpoint before crash.
            return "failed", False
        if interrupt_ch in channels:
            # Graph paused at interrupt() — needs a resume, not a new ingest.
            return "interrupted", False

        # Normal pending task writes: thread was mid-execution.
        # LangGraph will restart from the last persisted checkpoint.
        return None, False

    async def _handle_ingest(self, req: DispatchRequest) -> None:
        """Compile graph on first use and execute a new user turn."""
        async with ws_span("executor.ingest", thread_id=req.thread_id) as span:
            # Pre-flight: detect threads that already reached a terminal or
            # interrupted state before a crash.  Also grounds is_first_ingest
            # in checkpoint truth rather than the stale in-memory cache.
            pre_flight_outcome, is_first_ingest = await self._pre_flight_checkpoint(
                req.thread_id
            )
            if pre_flight_outcome == "completed":
                logger.info(
                    "Thread %s checkpoint shows completion before crash"
                    " — emitting completed without re-running",
                    req.thread_id,
                    extra=self._dispatch_log_extra(
                        req,
                        action="checkpoint_preflight_terminal",
                        outcome="completed",
                    ),
                )
                span.set_attribute("pre_flight", "completed")
                await self._emit_terminal_status(req.thread_id, "completed")
                return
            if pre_flight_outcome == "failed":
                logger.warning(
                    "Thread %s checkpoint shows error before crash"
                    " — emitting failed without re-running",
                    req.thread_id,
                    extra=self._dispatch_log_extra(
                        req,
                        action="checkpoint_preflight_terminal",
                        outcome="failed",
                    ),
                )
                span.set_attribute("pre_flight", "failed")
                await self._emit_terminal_status(req.thread_id, "failed")
                return
            if pre_flight_outcome == "interrupted":
                logger.info(
                    "Thread %s checkpoint is paused at interrupt"
                    " — skipping ingest; awaiting resume dispatch",
                    req.thread_id,
                    extra=self._dispatch_log_extra(
                        req,
                        action="checkpoint_preflight_interrupted",
                        outcome="interrupted",
                    ),
                )
                span.set_attribute("pre_flight", "interrupted")
                return

            span.set_attribute("is_first_ingest", is_first_ingest)

            try:
                graph = await self._get_or_compile_graph(req)
            except GraphCompilationError as exc:
                logger.warning(
                    "Graph compilation failed for thread %s: %s",
                    req.thread_id,
                    exc,
                    extra=self._dispatch_log_extra(
                        req,
                        action="compile_graph_failed",
                        error_type=type(exc).__name__,
                    ),
                )
                span.set_attribute("error", True)
                span.set_attribute("error.message", str(exc))
                await self._emit_terminal_status(
                    req.thread_id, "failed", error_detail=str(exc)
                )
                return

            if graph is None:
                logger.warning(
                    "No graph for thread %s -- no team preset provided",
                    req.thread_id,
                    extra=self._dispatch_log_extra(
                        req,
                        action="graph_missing",
                        runtime_mode="ingest",
                    ),
                )
                span.set_attribute("error", True)
                span.set_attribute("error.message", "No team preset")
                await self._emit_terminal_status(req.thread_id, "failed")
                return

            if not await self._mark_ingest_active(req.thread_id):
                logger.warning(
                    "Ingest already active for thread %s -- dropping",
                    req.thread_id,
                    extra=self._dispatch_log_extra(
                        req,
                        action="ingest_rejected_active",
                        runtime_mode="ingest",
                    ),
                )
                span.set_attribute("error", True)
                span.set_attribute("error.message", "Ingest already active")
                return

            self._bridge.track_thread(req.thread_id)

            graph_input = self._build_graph_input(req, is_first_ingest=is_first_ingest)
            config = {
                "configurable": {"thread_id": req.thread_id},
                "recursion_limit": (
                    req.recursion_limit or settings.graph_recursion_limit
                ),
            }

            agent_id = req.agent_id or "vaultspec-supervisor"

            try:
                span.add_event("starting_graph_execution")
                outcome = await self._aggregator.ingest(
                    req.thread_id,
                    agent_id,
                    cast("StreamableGraph", graph),
                    graph_input,
                    config,
                )
                span.set_attribute("outcome", outcome)
            except Exception:
                outcome = "failed"
                logger.exception(
                    "Ingest failed for thread %s",
                    req.thread_id,
                    extra=self._dispatch_log_extra(
                        req,
                        action="ingest_failed",
                        runtime_mode="ingest",
                    ),
                )
                span.record_exception(Exception("Graph execution failed"))
            finally:
                await self._emit_execution_state_projection(
                    req.thread_id,
                    cast("StreamableGraph", graph),
                    config,
                )
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
        async with ws_span("executor.resume", thread_id=req.thread_id) as span:
            # ADR-010: record resume option (cast to str for span attribute)
            val = str(req.option_id) if req.option_id else "none"
            span.set_attribute("option_id", val)
            try:
                graph = await self._get_or_compile_graph(req)
            except GraphCompilationError as exc:
                logger.warning(
                    "Graph recompile failed for thread %s: %s",
                    req.thread_id,
                    exc,
                    extra=self._dispatch_log_extra(
                        req,
                        action="compile_graph_failed",
                        runtime_mode="resume",
                        error_type=type(exc).__name__,
                    ),
                )
                span.set_attribute("error", True)
                span.set_attribute("error.message", str(exc))
                await self._emit_terminal_status(
                    req.thread_id, "failed", error_detail=str(exc)
                )
                return

            if graph is None:
                logger.warning(
                    "No graph for thread %s -- cannot resume",
                    req.thread_id,
                    extra=self._dispatch_log_extra(
                        req,
                        action="graph_missing",
                        runtime_mode="resume",
                    ),
                )
                await self._emit_terminal_status(req.thread_id, "failed")
                return

            if not await self._mark_ingest_active(req.thread_id):
                logger.warning(
                    "Ingest already active for thread %s -- cannot resume",
                    req.thread_id,
                    extra=self._dispatch_log_extra(
                        req,
                        action="resume_rejected_active",
                        runtime_mode="resume",
                    ),
                )
                return

            self._bridge.track_thread(req.thread_id)

            # Resolve recursion_limit: explicit request > team TOML > global default.
            cache_key = self._thread_to_cache_key.get(req.thread_id)
            team_preset = cache_key[0] if cache_key else req.team_preset

            # Resolve workspace_root from cache or request.
            ws_root_path = cache_key[1] if cache_key else req.workspace_root
            ws_root = Path(ws_root_path).resolve() if ws_root_path else None

            team_recursion_limit: int | None = None
            if team_preset:
                try:
                    team_cfg = load_team_config(team_preset, workspace_root=ws_root)
                    team_recursion_limit = team_cfg.graph.recursion_limit
                except Exception:
                    logger.debug(
                        "Could not load team config for recursion_limit fallback",
                        exc_info=True,
                        extra=self._dispatch_log_extra(
                            req,
                            action="team_config_fallback",
                            runtime_mode="resume",
                        ),
                    )
            effective_recursion_limit = (
                req.recursion_limit
                or team_recursion_limit
                or settings.graph_recursion_limit
            )
            config = {
                "configurable": {"thread_id": req.thread_id},
                "recursion_limit": effective_recursion_limit,
            }
            agent_id = req.agent_id or "vaultspec-supervisor"

            try:
                span.add_event("resuming_graph_execution")
                # Command(resume=...) is accepted by astream_events in place of
                # a dict graph_input -- LangGraph handles the type internally.
                outcome = await self._aggregator.ingest(
                    req.thread_id,
                    agent_id,
                    cast("StreamableGraph", graph),
                    Command(resume=req.option_id),
                    config,
                )
                span.set_attribute("outcome", outcome)
            except Exception:
                outcome = "failed"
                logger.exception(
                    "Resume failed for thread %s",
                    req.thread_id,
                    extra=self._dispatch_log_extra(
                        req,
                        action="resume_failed",
                        runtime_mode="resume",
                    ),
                )
                span.record_exception(Exception("Graph resume failed"))
            finally:
                await self._emit_execution_state_projection(
                    req.thread_id,
                    cast("StreamableGraph", graph),
                    config,
                )
                await self._emit_terminal_status(req.thread_id, outcome)
                await self._mark_ingest_done(req.thread_id)

    # ------------------------------------------------------------------
    # Terminal status relay
    # ------------------------------------------------------------------

    async def _emit_terminal_status(
        self,
        thread_id: str,
        outcome: str,
        error_detail: str | None = None,
    ) -> None:
        """Emit a ``thread_terminal`` event to the gateway.

        Emits for ``"completed"``, ``"failed"``, and ``"cancelled"`` outcomes.
        ``"interrupted"`` means the graph is suspended (awaiting permission)
        and the thread should remain ``RUNNING``.

        *error_detail* is forwarded in the event payload when set, allowing
        the gateway to surface compilation/execution error messages to clients
        (WRK-K03).
        """
        if outcome not in ("completed", "failed", "cancelled"):
            return
        payload: dict[str, str] = {
            "event_type": "thread_terminal",
            "thread_id": thread_id,
            "status": outcome,
        }
        if error_detail:
            payload["error_detail"] = error_detail
        await self._bridge.send_event(thread_id, payload)
        # F-17 fix: flush terminal events immediately — do not batch.
        # A lost thread_terminal event leaves the thread stuck in RUNNING
        # forever.  The cost is one extra HTTP POST per thread completion.
        try:
            await self._bridge.flush_events()
        except Exception:
            logger.warning(
                "Failed to flush terminal event for %s", thread_id, exc_info=True
            )

    def _normalize_execution_state(
        self,
        state: StateSnapshot,
    ) -> ExecutionStateProjectionPayload:
        """Normalize LangGraph runtime state into a durable worker payload."""
        next_nodes = [str(node) for node in getattr(state, "next", ())]
        state_interrupts = getattr(state, "interrupts", ()) or ()
        interrupt_types: list[str] = []
        tasks: list[ExecutionTaskProjectionPayload] = []

        for task in getattr(state, "tasks", ()) or ():
            task_interrupts = getattr(task, "interrupts", ()) or ()
            interrupt_ids: list[str] = []
            task_interrupt_types: list[str] = []
            for interrupt in task_interrupts:
                interrupt_id = getattr(interrupt, "id", None)
                if interrupt_id is not None:
                    interrupt_ids.append(str(interrupt_id))
                payload = getattr(interrupt, "value", interrupt)
                if isinstance(payload, dict) and payload.get("type") is not None:
                    interrupt_type = str(payload["type"])
                    task_interrupt_types.append(interrupt_type)
                    if interrupt_type not in interrupt_types:
                        interrupt_types.append(interrupt_type)
            tasks.append(
                ExecutionTaskProjectionPayload(
                    task_id=str(getattr(task, "id", "")),
                    name=str(getattr(task, "name", "")),
                    path=[str(item) for item in getattr(task, "path", ())],
                    has_error=getattr(task, "error", None) is not None,
                    error_type=(
                        type(task.error).__name__
                        if getattr(task, "error", None) is not None
                        else None
                    ),
                    interrupt_ids=interrupt_ids,
                    interrupt_types=task_interrupt_types,
                    has_nested_state=getattr(task, "state", None) is not None,
                    has_result=getattr(task, "result", None) is not None,
                )
            )

        if state_interrupts and not interrupt_types:
            for interrupt in state_interrupts:
                payload = getattr(interrupt, "value", interrupt)
                if isinstance(payload, dict) and payload.get("type") is not None:
                    interrupt_types.append(str(payload["type"]))

        snapshot_created_at = getattr(state, "created_at", None)
        if isinstance(snapshot_created_at, datetime):
            snapshot_created_at_value: str | None = snapshot_created_at.isoformat()
        elif isinstance(snapshot_created_at, str):
            snapshot_created_at_value = snapshot_created_at
        else:
            snapshot_created_at_value = None

        state_config = getattr(state, "config", None) or {}
        parent_config = getattr(state, "parent_config", None) or {}
        return ExecutionStateProjectionPayload(
            checkpoint_id=state_config.get("configurable", {}).get("checkpoint_id"),
            parent_checkpoint_id=parent_config.get("configurable", {}).get(
                "checkpoint_id"
            ),
            snapshot_created_at=snapshot_created_at_value,
            next_nodes=next_nodes,
            interrupt_types=interrupt_types,
            interrupt_count=(
                len(state_interrupts)
                if state_interrupts
                else sum(len(task.interrupt_ids) for task in tasks)
            ),
            task_count=len(tasks),
            tasks=tasks,
        )

    async def _emit_execution_state_projection(
        self,
        thread_id: str,
        graph: StreamableGraph,
        config: dict[str, Any],
    ) -> None:
        """Emit latest runtime execution-state truth over the internal event path."""
        try:
            state = await asyncio.wait_for(graph.aget_state(config), timeout=10.0)
            payload = self._normalize_execution_state(cast("StateSnapshot", state))
        except TimeoutError:
            payload = ExecutionStateProjectionPayload(
                degraded_reasons=["execution_state_projection_timeout"]
            )
        except Exception:
            logger.warning(
                "Failed to inspect execution state for thread %s",
                thread_id,
                exc_info=True,
                extra=self._log_extra(
                    thread_id=thread_id,
                    action="execution_state_projection_failed",
                ),
            )
            payload = ExecutionStateProjectionPayload(
                degraded_reasons=["execution_state_projection_unavailable"]
            )
        await self._bridge.send_event(thread_id, payload.model_dump(mode="json"))

    # ------------------------------------------------------------------
    # Graph input construction
    # ------------------------------------------------------------------

    @staticmethod
    def _build_graph_input(
        req: DispatchRequest, *, is_first_ingest: bool
    ) -> dict[str, Any]:
        """Build the ``graph_input`` dict for a new user turn.

        For the *initial* ingest on a thread, all required ``TeamState``
        fields are supplied so the checkpointer starts with a clean state.
        For follow-up messages, the plan/agent/artifact/token fields are
        omitted so LangGraph preserves checkpoint values (supplying
        ``current_plan=[]`` would trigger the ``_replace_plan`` reducer's
        "clear" sentinel and wipe the supervisor's execution plan).

        SDD blackboard fields (ADR-019 MED-01) are passed through on the
        first ingest only and only when non-empty.

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
        return graph_input

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
                    extra=self._log_extra(
                        agent_id=worker_ref.agent_id,
                        team_preset=req.team_preset,
                        workspace_root=str(ws_root) if ws_root else None,
                        action="agent_config_missing",
                    ),
                )

        supervisor_config: AgentConfig | None = None
        if team_config.topology.type in ("star", "pipeline_loop"):
            try:
                supervisor_config = load_agent_config(
                    "vaultspec-supervisor", workspace_root=ws_root
                )
            except AgentConfigNotFoundError:
                logger.debug(
                    "No supervisor config; using defaults",
                    extra=self._log_extra(
                        agent_id="vaultspec-supervisor",
                        team_preset=req.team_preset,
                        workspace_root=str(ws_root) if ws_root else None,
                        action="supervisor_config_defaulted",
                    ),
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
