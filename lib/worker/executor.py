"""Graph execution engine -- manages LangGraph run lifecycle (ADR-019).

Owns the graph registry (compiled ``CompiledStateGraph`` instances),
``EventAggregator``, and checkpointer.  Dispatches events to the
control surface via ``WorkerBridge``.

The executor is the worker-process analogue of the monolith's
``GraphRegistry`` + endpoint ingest logic, restructured for the
separated-process architecture.
"""

from __future__ import annotations

import asyncio
import logging

from pathlib import Path
from typing import Any, cast

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from ..api.schemas.internal import DispatchRequest
from ..core.aggregator import EventAggregator, StreamableGraph
from ..core.graph import compile_team_graph
from ..core.team_config import (
    AgentConfig,
    AgentConfigNotFoundError,
    TeamConfigNotFoundError,
    load_agent_config,
    load_team_config,
)
from .ipc import WorkerBridge


__all__ = ["Executor"]

logger = logging.getLogger(__name__)

# Match the recursion limit used by the control-surface endpoints.
_GRAPH_RECURSION_LIMIT = 100


class Executor:
    """Compiles and runs LangGraph graphs, dispatching events via IPC bridge.

    The executor maintains:

    * A ``dict[str, CompiledStateGraph]`` mapping thread_id to compiled graph.
    * An ``EventAggregator`` that drives the ``astream_events`` consumer loop.
    * A set of ``_active_ingests`` guarded by an ``asyncio.Lock`` to prevent
      concurrent graph execution on the same thread (which would race on
      checkpointer state).

    Parameters
    ----------
    checkpointer:
        ``AsyncSqliteSaver`` shared with the control surface (WAL mode).
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
        self._graphs: dict[str, CompiledStateGraph] = {}
        # Stores (team_preset, workspace_root) for each compiled thread so that
        # _handle_resume can recompile the graph if it was lost (e.g. eviction).
        self._graph_presets: dict[str, tuple[str, str | None]] = {}
        self._aggregator = EventAggregator()

        # Wire bridge relay: every broadcast event is forwarded to the control
        # surface via HTTP (ADR-019).  Closure captures bridge reference.
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
        return len(self._graphs)

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

    async def _handle_ingest(self, req: DispatchRequest) -> None:
        """Compile graph on first use and execute a new user turn."""
        # Compile on first encounter for this thread
        is_first_ingest = req.thread_id not in self._graphs
        if is_first_ingest and req.team_preset:
            try:
                graph = self._compile_graph(req)
                self._graphs[req.thread_id] = graph
                self._aggregator.register_graph(cast(StreamableGraph, graph))
                # Cache preset so _handle_resume can recompile after eviction.
                self._graph_presets[req.thread_id] = (
                    req.team_preset,
                    req.workspace_root,
                )
            except Exception:
                logger.exception(
                    "Failed to compile graph for thread %s (preset=%s)",
                    req.thread_id,
                    req.team_preset,
                )
                return

        graph = self._graphs.get(req.thread_id)
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
        config = {
            "configurable": {"thread_id": req.thread_id},
            "recursion_limit": req.recursion_limit or _GRAPH_RECURSION_LIMIT,
        }

        agent_id = req.agent_id or "vaultspec-supervisor"

        try:
            await self._aggregator.ingest(
                req.thread_id,
                agent_id,
                cast(StreamableGraph, graph),
                graph_input,
                config,
            )
        except Exception:
            logger.exception("Ingest failed for thread %s", req.thread_id)
        finally:
            await self._mark_ingest_done(req.thread_id)

    # ------------------------------------------------------------------
    # Resume handler (permission response)
    # ------------------------------------------------------------------

    async def _handle_resume(self, req: DispatchRequest) -> None:
        """Resume a graph from a LangGraph interrupt.

        Uses ``Command(resume=option_id)`` as graph input, which causes the
        ``interrupt()`` call in the worker node to return the chosen option.
        """
        graph = self._graphs.get(req.thread_id)
        if graph is None:
            # Attempt lazy recompilation using cached preset (handles graph
            # eviction within the same process) or req.team_preset supplied
            # by the API (handles cold-restart recovery when caller provides it).
            preset_info = self._graph_presets.get(req.thread_id)
            team_preset = (
                preset_info[0] if preset_info else req.team_preset
            )
            workspace_root = (
                preset_info[1] if preset_info else req.workspace_root
            )
            if team_preset:
                recompile_req = req.model_copy(
                    update={"team_preset": team_preset, "workspace_root": workspace_root}
                )
                try:
                    graph = self._compile_graph(recompile_req)
                    self._graphs[req.thread_id] = graph
                    self._aggregator.register_graph(cast(StreamableGraph, graph))
                    self._graph_presets[req.thread_id] = (team_preset, workspace_root)
                    logger.info(
                        "Lazily recompiled graph for thread %s (preset=%s)",
                        req.thread_id,
                        team_preset,
                    )
                except Exception:
                    logger.exception(
                        "Failed to recompile graph for thread %s (preset=%s)",
                        req.thread_id,
                        team_preset,
                    )
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
        preset_info = self._graph_presets.get(req.thread_id)
        team_preset = preset_info[0] if preset_info else req.team_preset
        ws_root = (
            Path(preset_info[1]).resolve()
            if preset_info and preset_info[1]
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
            req.recursion_limit
            or team_recursion_limit
            or _GRAPH_RECURSION_LIMIT
        )
        config = {
            "configurable": {"thread_id": req.thread_id},
            "recursion_limit": effective_recursion_limit,
        }
        agent_id = req.agent_id or "vaultspec-supervisor"

        try:
            # Command(resume=...) is accepted by astream_events in place of
            # a dict graph_input -- LangGraph handles the type internally.
            await self._aggregator.ingest(
                req.thread_id,
                agent_id,
                cast(StreamableGraph, graph),
                Command(resume=req.option_id),
                config,
            )
        except Exception:
            logger.exception("Resume failed for thread %s", req.thread_id)
        finally:
            await self._mark_ingest_done(req.thread_id)

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
            step_timeout=None,  # let compile_team_graph use team_config.graph.step_timeout_seconds
        )

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def shutdown(self) -> None:
        """Release held resources (aggregator debounce tasks, etc.)."""
        await self._aggregator.shutdown()
        self._graphs.clear()
        self._graph_presets.clear()
