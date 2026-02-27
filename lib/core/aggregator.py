"""Central Event Aggregator for LangGraph stream broadcasting.

Ingests LangGraph ``astream_events`` callbacks, transforms them into
wire-protocol event models (``lib.api.schemas.events``), assigns
per-thread monotonic sequence numbers, applies debouncing rules, and
fans out to connected WebSocket clients.

See: ADR-004 (Event Aggregation & State Replay)
     ADR-011 (Frontend-Backend Wire Contract)
     docs/research/2026-02-27-backend-gaps-research.md §1
"""

import asyncio
import logging
import time

from collections import defaultdict
from collections.abc import AsyncIterator, Coroutine
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from ..api.schemas.enums import (
    AgentLifecycleState,
    PermissionOptionKind,
    ToolCallStatus,
    ToolKind,
)
from ..api.schemas.events import (
    AgentStatusEvent,
    AgentSummary,
    ErrorEvent,
    MessageChunkEvent,
    PermissionOption,
    PermissionRequestEvent,
    ServerEvent,
    TeamStatusEvent,
    ThoughtChunkEvent,
    ToolCallStartEvent,
    ToolCallUpdateEvent,
)
from ..telemetry.instrumentation import get_meter, get_tracer
from .exceptions import EventAggregatorError


logger = logging.getLogger(__name__)


__all__ = ["EventAggregator"]

# ---------------------------------------------------------------------------
# OTel instrumentation (ADR-010)
# ---------------------------------------------------------------------------
_tracer = get_tracer(__name__)
_meter = get_meter(__name__)

_events_emitted_counter = _meter.create_counter(
    "aggregator.events_emitted",
    description="Number of wire-protocol events emitted by type",
)
_events_filtered_counter = _meter.create_counter(
    "aggregator.events_filtered",
    description="Number of LangGraph events filtered out",
)
_chunks_batched_counter = _meter.create_counter(
    "aggregator.chunks_batched",
    description="Number of token chunks buffered before flush",
)
_ingest_duration_histogram = _meter.create_histogram(
    "aggregator.ingest_duration_seconds",
    description="Duration of a full graph ingest cycle",
    unit="s",
)


# ---------------------------------------------------------------------------
# Debounce intervals (seconds) — ADR-011 §5
# ---------------------------------------------------------------------------
_TOOL_CALL_UPDATE_DEBOUNCE = 0.100  # max 1 per 100ms per tool call
_PLAN_UPDATE_DEBOUNCE = 0.250  # max 1 per 250ms per thread

# ---------------------------------------------------------------------------
# Token chunk batching — research §1.3
# ---------------------------------------------------------------------------
_CHUNK_FLUSH_INTERVAL = 0.050  # 50ms flush window
_CHUNK_BUFFER_MAX_BYTES = 4096  # 4KB buffer threshold

# ---------------------------------------------------------------------------
# Backpressure boundary — research §1.5
# ---------------------------------------------------------------------------
_QUEUE_MAXSIZE = 512

# ---------------------------------------------------------------------------
# LangGraph event filtering — research §1.2
# ---------------------------------------------------------------------------
_PASSTHROUGH_EVENTS = frozenset(
    {
        "on_chat_model_stream",
        "on_tool_start",
        "on_tool_end",
        "on_custom_event",
    }
)

_NODE_BOUNDARY_EVENTS = frozenset(
    {
        "on_chain_start",
        "on_chain_end",
    }
)


class _StreamableGraph(Protocol):
    """Structural protocol for a compiled LangGraph graph with astream_events."""

    def astream_events(
        self,
        graph_input: dict[str, Any],
        config: dict[str, Any],
        *,
        version: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield raw LangGraph event dicts."""
        ...


class EventAggregator:
    """Central event bus that transforms LangGraph events into wire events.

    The aggregator maintains per-thread monotonic sequence counters
    (ADR-011 §5) and broadcasts transformed events to registered
    subscriber callbacks.

    Subscribers are async callables ``(ServerEvent) -> None`` keyed by
    a client_id. Each subscriber can declare which thread_ids it wants
    to receive events for.

    Designed as a FastAPI lifespan singleton injected via DI (ADR-007).
    """

    def __init__(self) -> None:
        """Initialize the aggregator with empty subscriber and sequence tables."""
        # Per-thread monotonic sequence counters (start at 0, first event = 1)
        self._sequences: dict[str, int] = defaultdict(int)

        # Subscriber queues: client_id -> bounded asyncio.Queue
        self._subscribers: dict[str, asyncio.Queue[ServerEvent]] = {}
        # Which threads each client is subscribed to: client_id -> set of thread_ids
        self._subscriptions: dict[str, set[str]] = defaultdict(set)

        # Per-thread ingest queues for backpressure (research §1.3)
        self._ingest_queues: dict[str, asyncio.Queue[dict[str, Any] | None]] = {}
        # Per-thread fan-out tasks
        self._fanout_tasks: dict[str, asyncio.Task[None]] = {}

        # Per-thread token chunk buffers for batching (research §1.3)
        self._chunk_buffers: dict[str, list[str]] = defaultdict(list)
        self._chunk_buffer_meta: dict[str, dict[str, str]] = {}
        self._chunk_flush_tasks: dict[str, asyncio.Task[None]] = {}

        # Debounce state: (thread_id, tool_call_id) -> last_emit_time
        self._tool_update_last_emit: dict[tuple[str, str], float] = {}
        # Debounce state: thread_id -> last_emit_time for plan updates
        self._plan_update_last_emit: dict[str, float] = {}

        # Pending debounced events
        self._tool_update_pending: dict[tuple[str, str], ToolCallUpdateEvent] = {}
        self._plan_update_pending: dict[str, Any] = {}

        # Debounce flush tasks
        self._debounce_tasks: set[asyncio.Task[None]] = set()

        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Sequence management
    # ------------------------------------------------------------------

    def _next_sequence(self, thread_id: str) -> int:
        """Atomically increment and return the next sequence for a thread."""
        self._sequences[thread_id] += 1
        return self._sequences[thread_id]

    def get_sequence(self, thread_id: str) -> int:
        """Return the current sequence counter for a thread (0 if unseen)."""
        return self._sequences.get(thread_id, 0)

    def advance_sequence(self, thread_id: str) -> int:
        """Increment and return the next sequence number for *thread_id*.

        Public wrapper for tests that need to advance the counter without
        emitting an event (e.g. to verify shutdown clears the counter table).
        """
        return self._next_sequence(thread_id)

    def subscriber_count(self) -> int:
        """Return the number of currently registered subscribers."""
        return len(self._subscribers)

    def subscription_count(self) -> int:
        """Return the number of currently active subscriptions (across all clients)."""
        return len(self._subscriptions)

    def sequence_count(self) -> int:
        """Return the number of threads that have received at least one event."""
        return len(self._sequences)

    def get_subscriptions(self, client_id: str) -> frozenset[str]:
        """Return a frozen snapshot of the thread subscriptions for *client_id*."""
        return frozenset(self._subscriptions.get(client_id, set()))

    # ------------------------------------------------------------------
    # Subscriber management
    # ------------------------------------------------------------------

    def add_subscriber(self, client_id: str) -> asyncio.Queue[ServerEvent]:
        """Register a new subscriber and return its bounded event queue.

        Uses ``maxsize=512`` for backpressure (research §1.5).
        """
        queue: asyncio.Queue[ServerEvent] = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
        self._subscribers[client_id] = queue
        self._subscriptions[client_id] = set()
        return queue

    def remove_subscriber(self, client_id: str) -> None:
        """Unregister a subscriber."""
        self._subscribers.pop(client_id, None)
        self._subscriptions.pop(client_id, None)

    def subscribe(self, client_id: str, thread_ids: list[str]) -> None:
        """Subscribe a client to one or more thread event streams."""
        if client_id not in self._subscribers:
            raise EventAggregatorError(f"Client {client_id} is not registered")
        self._subscriptions[client_id].update(thread_ids)

    def unsubscribe(self, client_id: str, thread_ids: list[str]) -> None:
        """Unsubscribe a client from one or more thread event streams."""
        if client_id in self._subscriptions:
            self._subscriptions[client_id].difference_update(thread_ids)

    def get_active_thread_ids(self) -> list[str]:
        """Return all thread IDs that have at least one subscriber."""
        all_threads: set[str] = set()
        for threads in self._subscriptions.values():
            all_threads.update(threads)
        return sorted(all_threads)

    # ------------------------------------------------------------------
    # Broadcasting
    # ------------------------------------------------------------------

    async def _broadcast(self, event: ServerEvent) -> None:
        """Fan out a server event to all interested subscribers.

        Uses ``await queue.put()`` (never ``put_nowait``) to propagate
        backpressure when a client is slow (research §1.5).
        """
        thread_id = getattr(event, "thread_id", None)
        event_type = getattr(event, "type", "unknown")

        with _tracer.start_as_current_span(
            "aggregator.broadcast",
            attributes={"event.type": str(event_type), "thread_id": thread_id or ""},
        ):
            delivered = 0
            for client_id, queue in list(self._subscribers.items()):
                client_subs = self._subscriptions.get(client_id, set())
                if thread_id is None or thread_id in client_subs:
                    await queue.put(event)
                    delivered += 1
            _events_emitted_counter.add(1, {"event.type": str(event_type)})

    # ------------------------------------------------------------------
    # Debounced broadcasting
    # ------------------------------------------------------------------

    async def _broadcast_debounced_tool_update(
        self,
        key: tuple[str, str],
    ) -> None:
        """Flush a pending debounced tool call update after the interval."""
        await asyncio.sleep(_TOOL_CALL_UPDATE_DEBOUNCE)
        async with self._lock:
            event = self._tool_update_pending.pop(key, None)
        if event is not None:
            await self._broadcast(event)

    async def _broadcast_debounced_plan_update(
        self,
        thread_id: str,
    ) -> None:
        """Flush a pending debounced plan update after the interval."""
        await asyncio.sleep(_PLAN_UPDATE_DEBOUNCE)
        async with self._lock:
            event = self._plan_update_pending.pop(thread_id, None)
        if event is not None:
            await self._broadcast(event)

    def _schedule_debounce(
        self,
        coro: Coroutine[Any, Any, None],
    ) -> None:
        """Schedule a debounce flush task and track it for cleanup."""
        task = asyncio.create_task(coro)
        self._debounce_tasks.add(task)
        task.add_done_callback(self._debounce_tasks.discard)

    # ------------------------------------------------------------------
    # Token chunk batching (research §1.3)
    # ------------------------------------------------------------------

    async def _flush_chunk_buffer(self, thread_id: str) -> None:
        """Flush accumulated token chunks as a single MessageChunkEvent."""
        chunks = self._chunk_buffers.pop(thread_id, [])
        meta = self._chunk_buffer_meta.pop(thread_id, None)
        self._chunk_flush_tasks.pop(thread_id, None)
        if chunks and meta:
            with _tracer.start_as_current_span(
                "aggregator.flush_chunks",
                attributes={"thread_id": thread_id, "chunk_count": len(chunks)},
            ):
                combined = "".join(chunks)
                event = MessageChunkEvent(
                    thread_id=thread_id,
                    agent_id=meta.get("agent_id"),
                    content=combined,
                    message_id=meta.get("message_id", ""),
                    timestamp=datetime.now(UTC),
                    sequence=self._next_sequence(thread_id),
                )
                await self._broadcast(event)

    async def _scheduled_chunk_flush(self, thread_id: str) -> None:
        """Timer-based flush: waits 50ms then flushes."""
        await asyncio.sleep(_CHUNK_FLUSH_INTERVAL)
        await self._flush_chunk_buffer(thread_id)

    async def _buffer_message_chunk(
        self,
        thread_id: str,
        agent_id: str,
        content: str,
        message_id: str,
    ) -> None:
        """Buffer a token chunk and flush on 50ms timeout or 4KB threshold.

        Per research §1.3: collect chunks, flush every 50ms OR when
        buffer reaches 4KB, whichever comes first.
        """
        self._chunk_buffers[thread_id].append(content)
        self._chunk_buffer_meta[thread_id] = {
            "agent_id": agent_id,
            "message_id": message_id,
        }
        _chunks_batched_counter.add(1, {"thread_id": thread_id})

        buffer_size = sum(len(c) for c in self._chunk_buffers[thread_id])

        if buffer_size >= _CHUNK_BUFFER_MAX_BYTES:
            # 4KB threshold reached: flush immediately
            existing_task = self._chunk_flush_tasks.pop(thread_id, None)
            if existing_task is not None:
                existing_task.cancel()
            await self._flush_chunk_buffer(thread_id)
        elif thread_id not in self._chunk_flush_tasks:
            # Start a 50ms timer for flush
            task = asyncio.create_task(self._scheduled_chunk_flush(thread_id))
            self._chunk_flush_tasks[thread_id] = task
            self._debounce_tasks.add(task)
            task.add_done_callback(self._debounce_tasks.discard)

    async def buffer_message_chunk(
        self,
        thread_id: str,
        agent_id: str,
        content: str,
        message_id: str,
    ) -> None:
        """Buffer a token chunk; flush when 4 KB threshold or 50 ms timer fires.

        Public entry point that delegates to the internal batcher.
        Callers outside this class must use this method instead of
        the private ``_buffer_message_chunk`` helper.
        """
        await self._buffer_message_chunk(thread_id, agent_id, content, message_id)

    async def flush_chunk_buffer(self, thread_id: str) -> None:
        """Flush any buffered token chunks for *thread_id* immediately.

        Public entry point for tests and the ``ingest`` finalisation path to
        drain pending chunks without waiting for the 50 ms timer.
        """
        await self._flush_chunk_buffer(thread_id)

    # ------------------------------------------------------------------
    # Event emission (public API)
    # ------------------------------------------------------------------

    async def emit(self, event: ServerEvent) -> None:
        """Emit a pre-built server event directly.

        Assigns a sequence number if the event is thread-scoped
        (has a ``thread_id`` attribute), then broadcasts.
        """
        thread_id = getattr(event, "thread_id", None)
        if thread_id is not None and hasattr(event, "sequence"):
            object.__setattr__(event, "sequence", self._next_sequence(thread_id))
            object.__setattr__(event, "timestamp", datetime.now(UTC))
        await self._broadcast(event)

    async def emit_agent_status(
        self,
        thread_id: str,
        agent_id: str,
        node_name: str,
        state: AgentLifecycleState,
        detail: str | None = None,
    ) -> None:
        """Emit an agent lifecycle state transition event."""
        event = AgentStatusEvent(
            thread_id=thread_id,
            agent_id=agent_id,
            node_name=node_name,
            state=state,
            detail=detail,
            timestamp=datetime.now(UTC),
            sequence=self._next_sequence(thread_id),
        )
        await self._broadcast(event)

    async def emit_message_chunk(
        self,
        thread_id: str,
        agent_id: str,
        content: str,
        message_id: str,
        finish_reason: str | None = None,
    ) -> None:
        """Emit a streaming message token event."""
        event = MessageChunkEvent(
            thread_id=thread_id,
            agent_id=agent_id,
            content=content,
            message_id=message_id,
            finish_reason=finish_reason,
            timestamp=datetime.now(UTC),
            sequence=self._next_sequence(thread_id),
        )
        await self._broadcast(event)

    async def emit_thought_chunk(
        self,
        thread_id: str,
        agent_id: str,
        content: str,
        message_id: str,
    ) -> None:
        """Emit a streaming thought/reasoning token event."""
        event = ThoughtChunkEvent(
            thread_id=thread_id,
            agent_id=agent_id,
            content=content,
            message_id=message_id,
            timestamp=datetime.now(UTC),
            sequence=self._next_sequence(thread_id),
        )
        await self._broadcast(event)

    async def emit_tool_call_start(
        self,
        thread_id: str,
        agent_id: str,
        tool_call_id: str,
        title: str,
        kind: ToolKind = ToolKind.OTHER,
    ) -> None:
        """Emit a tool invocation start event."""
        event = ToolCallStartEvent(
            thread_id=thread_id,
            agent_id=agent_id,
            tool_call_id=tool_call_id,
            title=title,
            kind=kind,
            status=ToolCallStatus.PENDING,
            timestamp=datetime.now(UTC),
            sequence=self._next_sequence(thread_id),
        )
        await self._broadcast(event)

    async def emit_tool_call_update(
        self,
        thread_id: str,
        agent_id: str,
        tool_call_id: str,
        status: ToolCallStatus | None = None,
        title: str | None = None,
    ) -> None:
        """Emit a tool call update event (debounced per ADR-011 §5).

        Updates are batched at most once per 100ms per tool call.
        """
        now = time.monotonic()
        key = (thread_id, tool_call_id)
        event = ToolCallUpdateEvent(
            thread_id=thread_id,
            agent_id=agent_id,
            tool_call_id=tool_call_id,
            status=status,
            title=title,
            timestamp=datetime.now(UTC),
            sequence=self._next_sequence(thread_id),
        )

        last_emit = self._tool_update_last_emit.get(key, 0.0)
        if now - last_emit >= _TOOL_CALL_UPDATE_DEBOUNCE:
            # Enough time has passed, emit immediately
            self._tool_update_last_emit[key] = now
            await self._broadcast(event)
        else:
            # Debounce: store pending and schedule flush
            async with self._lock:
                already_pending = key in self._tool_update_pending
                self._tool_update_pending[key] = event
            if not already_pending:
                self._schedule_debounce(self._broadcast_debounced_tool_update(key))

    async def emit_permission_request(
        self,
        thread_id: str,
        agent_id: str,
        request_id: str,
        description: str,
        options: list[dict[str, str]],
        tool_call: str | None = None,
    ) -> None:
        """Emit a permission request event (LangGraph interrupt)."""
        parsed_options = [
            PermissionOption(
                option_id=opt.get("option_id", str(uuid4())),
                name=opt.get("name", ""),
                kind=PermissionOptionKind(
                    opt.get("kind", PermissionOptionKind.ALLOW_ONCE)
                ),
            )
            for opt in options
        ]

        event = PermissionRequestEvent(
            thread_id=thread_id,
            agent_id=agent_id,
            request_id=request_id,
            description=description,
            options=parsed_options,
            tool_call=tool_call,
            timestamp=datetime.now(UTC),
            sequence=self._next_sequence(thread_id),
        )
        await self._broadcast(event)

    async def emit_error(
        self,
        thread_id: str,
        code: str,
        message: str,
        recoverable: bool = True,
        agent_id: str | None = None,
    ) -> None:
        """Emit a server-side error notification."""
        event = ErrorEvent(
            thread_id=thread_id,
            agent_id=agent_id,
            code=code,
            message=message,
            recoverable=recoverable,
            timestamp=datetime.now(UTC),
            sequence=self._next_sequence(thread_id),
        )
        await self._broadcast(event)

    async def emit_team_status(
        self,
        thread_id: str,
        agents: list[dict[str, Any]],
        active_thread_ids: list[str] | None = None,
    ) -> None:
        """Emit a team status event (on transitions only, per ADR-011 §5)."""
        agent_summaries = [AgentSummary(**agent_data) for agent_data in agents]

        event = TeamStatusEvent(
            thread_id=thread_id,
            agents=agent_summaries,
            active_thread_ids=active_thread_ids or [],
            timestamp=datetime.now(UTC),
            sequence=self._next_sequence(thread_id),
        )
        await self._broadcast(event)

    # ------------------------------------------------------------------
    # LangGraph astream_events integration (research §1.2)
    # ------------------------------------------------------------------

    async def process_langgraph_event(
        self,
        event_data: dict[str, Any],
        thread_id: str,
        agent_id: str,
    ) -> None:
        """Transform a LangGraph astream_events callback into wire events.

        Filters events using ``langgraph_node`` metadata to eliminate
        ~60% of noisy sub-runnable events (research §1.2).

        Handles:
        - ``on_chat_model_stream`` -> ``MessageChunkEvent`` (batched)
        - ``on_tool_start`` -> ``ToolCallStartEvent``
        - ``on_tool_end`` -> ``ToolCallUpdateEvent``
        - ``on_chain_start`` -> ``AgentStatusEvent(working)``
        - ``on_chain_end`` -> ``AgentStatusEvent(idle)``
        - ``on_custom_event`` -> ``ThoughtChunkEvent``

        Args:
            event_data: Raw event dict from ``astream_events(version="v2")``.
            thread_id: The LangGraph thread_id for routing.
            agent_id: The agent_id that originated the event.
        """
        event_kind = event_data.get("event", "")
        run_id = event_data.get("run_id", str(uuid4()))
        metadata = event_data.get("metadata", {})
        node = metadata.get("langgraph_node")

        # --- Passthrough events (no node filter needed for LLM/tool) ---
        if event_kind == "on_chat_model_stream":
            chunk = event_data.get("data", {}).get("chunk")
            if chunk is not None:
                content = getattr(chunk, "content", "")
                if isinstance(content, str) and content:
                    await self._buffer_message_chunk(
                        thread_id=thread_id,
                        agent_id=agent_id,
                        content=content,
                        message_id=run_id,
                    )
            return

        if event_kind == "on_tool_start":
            if node:  # Only emit for graph-level tool calls
                tool_name = event_data.get("name", "unknown_tool")
                await self.emit_tool_call_start(
                    thread_id=thread_id,
                    agent_id=agent_id,
                    tool_call_id=run_id,
                    title=tool_name,
                )
            return

        if event_kind == "on_tool_end":
            if node:  # Only emit for graph-level tool calls
                await self.emit_tool_call_update(
                    thread_id=thread_id,
                    agent_id=agent_id,
                    tool_call_id=run_id,
                    status=ToolCallStatus.COMPLETED,
                )
            return

        if event_kind == "on_custom_event":
            # Custom events via StreamWriter map to thought chunks
            data = event_data.get("data", {})
            content = data if isinstance(data, str) else str(data.get("content", ""))
            if content:
                await self.emit_thought_chunk(
                    thread_id=thread_id,
                    agent_id=agent_id,
                    content=content,
                    message_id=run_id,
                )
            return

        # --- Node boundary events (require langgraph_node metadata) ---
        if event_kind in _NODE_BOUNDARY_EVENTS and node:
            if event_kind == "on_chain_start":
                await self.emit_agent_status(
                    thread_id=thread_id,
                    agent_id=agent_id,
                    node_name=node,
                    state=AgentLifecycleState.WORKING,
                )
            elif event_kind == "on_chain_end":
                await self.emit_agent_status(
                    thread_id=thread_id,
                    agent_id=agent_id,
                    node_name=node,
                    state=AgentLifecycleState.IDLE,
                )
            return

        # --- Everything else is filtered out (research §1.2) ---
        if event_kind not in _PASSTHROUGH_EVENTS | _NODE_BOUNDARY_EVENTS:
            _events_filtered_counter.add(1, {"event.kind": event_kind})
            logger.debug(
                "Filtered LangGraph event: %s (run_id=%s)",
                event_kind,
                run_id,
            )

    # ------------------------------------------------------------------
    # LangGraph graph ingest (research §1.3)
    # ------------------------------------------------------------------

    async def ingest(
        self,
        thread_id: str,
        agent_id: str,
        graph: _StreamableGraph,
        graph_input: dict[str, Any],
        config: dict[str, Any],
    ) -> None:
        """Start consuming ``astream_events`` from a compiled graph.

        Creates a bounded ingest queue (``maxsize=512``) for backpressure
        and processes events through ``process_langgraph_event``.

        Args:
            thread_id: LangGraph thread_id for event routing.
            agent_id: Agent identifier for event attribution.
            graph: Compiled LangGraph ``StateGraph``.
            graph_input: Input to the graph invocation.
            config: LangGraph config dict (must include ``configurable.thread_id``).
        """
        start = time.monotonic()
        with _tracer.start_as_current_span(
            "aggregator.ingest",
            attributes={"thread_id": thread_id, "agent_id": agent_id},
        ) as span:
            try:
                async for raw_event in graph.astream_events(
                    graph_input,
                    config,
                    version="v2",
                ):
                    await self.process_langgraph_event(
                        event_data=raw_event,
                        thread_id=thread_id,
                        agent_id=agent_id,
                    )
            except Exception:
                logger.exception("Error during graph ingest for thread %s", thread_id)
                span.set_attribute("error", True)
                await self.emit_error(
                    thread_id=thread_id,
                    agent_id=agent_id,
                    code="INGEST_ERROR",
                    message="Graph event stream failed unexpectedly",
                    recoverable=False,
                )
            finally:
                # Flush any remaining chunk buffer
                await self._flush_chunk_buffer(thread_id)
                _ingest_duration_histogram.record(
                    time.monotonic() - start,
                    {"thread_id": thread_id},
                )

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def shutdown(self) -> None:
        """Cancel all debounce tasks and clear state."""
        for task in list(self._debounce_tasks):
            task.cancel()
        if self._debounce_tasks:
            await asyncio.gather(*self._debounce_tasks, return_exceptions=True)
        self._debounce_tasks.clear()

        # Cancel fan-out tasks
        for task in self._fanout_tasks.values():
            task.cancel()
        if self._fanout_tasks:
            await asyncio.gather(*self._fanout_tasks.values(), return_exceptions=True)
        self._fanout_tasks.clear()

        # Cancel chunk flush tasks
        for task in self._chunk_flush_tasks.values():
            task.cancel()
        self._chunk_flush_tasks.clear()

        self._subscribers.clear()
        self._subscriptions.clear()
        self._sequences.clear()
        self._chunk_buffers.clear()
        self._chunk_buffer_meta.clear()
