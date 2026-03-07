"""Central Event Aggregator for LangGraph stream broadcasting.

Ingests LangGraph ``astream_events`` callbacks, transforms them into
wire-protocol event models (``vaultspec_a2a.api.schemas.events``), assigns
per-thread monotonic sequence numbers, applies debouncing rules, and
fans out to connected WebSocket clients.

See: ADR-004 (Event Aggregation & State Replay)
     ADR-011 (Frontend-Backend Wire Contract)
     docs/research/2026-02-27-backend-gaps-research.md §1
"""

import asyncio
import json
import logging
import time

from collections import defaultdict
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from langgraph.types import Command

from ..api.schemas.enums import (
    AgentLifecycleState,
    PermissionOptionKind,
    PermissionType,
    ToolCallStatus,
    ToolKind,
)
from ..api.schemas.events import (
    AgentStatusEvent,
    AgentSummary,
    ArtifactUpdateEvent,
    ErrorEvent,
    MessageChunkEvent,
    PermissionOption,
    PermissionRequestEvent,
    PlanEntry,
    PlanUpdateEvent,
    ServerEvent,
    TeamStatusEvent,
    ThoughtChunkEvent,
    ToolCallContent,
    ToolCallContentText,
    ToolCallStartEvent,
    ToolCallUpdateEvent,
)
from ..telemetry.instrumentation import get_meter, get_tracer
from .exceptions import EventAggregatorError


# M6: import GraphInterrupt for isinstance check vs string comparison.
try:
    from langgraph.errors import GraphInterrupt as _GraphInterrupt
except ImportError:
    _GraphInterrupt = None  # type: ignore[assignment,misc]

try:
    from langgraph.errors import GraphRecursionError as _GraphRecursionError
except ImportError:
    _GraphRecursionError = None  # type: ignore[assignment,misc]


logger = logging.getLogger(__name__)


__all__ = ["EventAggregator", "StreamableGraph"]

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

# AGG-03: safety cap for debounce timestamp maps to prevent unbounded growth.
_DEBOUNCE_MAP_MAX_ENTRIES = 1000


def _evict_oldest(d: dict, max_entries: int) -> None:
    """Remove oldest entries (by value = timestamp) until at max_entries."""
    to_remove = len(d) - max_entries
    if to_remove <= 0:
        return
    # Sort by timestamp (value), evict the oldest.
    for key in sorted(d, key=d.__getitem__)[:to_remove]:
        del d[key]


_CHUNK_BUFFER_MAX_BYTES = 4096  # 4KB buffer threshold
_TOOL_ARG_TRUNCATE_LEN = 1000  # Max chars for tool input/output preview

# ---------------------------------------------------------------------------
# Backpressure boundary — research §1.5
# ---------------------------------------------------------------------------
_QUEUE_MAXSIZE = 512

# ---------------------------------------------------------------------------
# aget_state timeout — M3: was hardcoded 10s; now configurable constant
# ---------------------------------------------------------------------------
_AGET_STATE_TIMEOUT = 10.0

# ---------------------------------------------------------------------------
# LangGraph event filtering — research §1.2
# ---------------------------------------------------------------------------
_PASSTHROUGH_EVENTS = frozenset(
    {
        "on_chat_model_stream",
        "on_chat_model_end",
        "on_tool_start",
        "on_tool_end",
        "on_tool_error",
        "on_custom_event",
    }
)

_NODE_BOUNDARY_EVENTS = frozenset(
    {
        "on_chain_start",
        "on_chain_end",
        "on_chain_error",
    }
)


class StreamableGraph(Protocol):
    """Structural protocol for a compiled LangGraph graph with astream_events."""

    def astream_events(
        self,
        graph_input: dict[str, Any] | Command | None,
        config: dict[str, Any],
        *,
        version: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield raw LangGraph event dicts."""
        ...

    async def aget_state(self, config: dict[str, Any]) -> object:
        """Return the current checkpointer state snapshot."""
        ...


def _map_acp_option_kind(option_id: str) -> PermissionOptionKind:
    """Map an ACP option ID string to a ``PermissionOptionKind`` enum value.

    Heuristic matching: looks for ``always`` + ``deny``/``reject`` keywords to
    classify the option kind.  Defaults to ``ALLOW_ONCE`` for unrecognised ids.

    Args:
        option_id: The raw ACP option ID string (e.g. ``"allow_always"``).

    Returns:
        The matching ``PermissionOptionKind`` member.
    """
    oid = option_id.lower()
    if "always" in oid and ("deny" in oid or "reject" in oid):
        return PermissionOptionKind.REJECT_ALWAYS
    if "always" in oid:
        return PermissionOptionKind.ALLOW_ALWAYS
    if "deny" in oid or "reject" in oid:
        return PermissionOptionKind.REJECT_ONCE
    return PermissionOptionKind.ALLOW_ONCE


# ---------------------------------------------------------------------------
# Tool name → ToolKind classification (BE-04, BE-30)
# ---------------------------------------------------------------------------
_TOOL_KIND_MAP: dict[str, ToolKind] = {
    # Read / inspect
    "read": ToolKind.READ,
    "read_file": ToolKind.READ,
    "cat": ToolKind.READ,
    "view": ToolKind.READ,
    "head": ToolKind.READ,
    "tail": ToolKind.READ,
    # Edit / write
    "edit": ToolKind.EDIT,
    "edit_file": ToolKind.EDIT,
    "write": ToolKind.EDIT,
    "write_file": ToolKind.EDIT,
    "create": ToolKind.EDIT,
    "insert": ToolKind.EDIT,
    "replace": ToolKind.EDIT,
    "patch": ToolKind.EDIT,
    "save": ToolKind.EDIT,
    # Delete
    "delete": ToolKind.DELETE,
    "remove": ToolKind.DELETE,
    "rm": ToolKind.DELETE,
    # Move / rename
    "move": ToolKind.MOVE,
    "rename": ToolKind.MOVE,
    "mv": ToolKind.MOVE,
    # Search
    "search": ToolKind.SEARCH,
    "grep": ToolKind.SEARCH,
    "find": ToolKind.SEARCH,
    "glob": ToolKind.SEARCH,
    "rg": ToolKind.SEARCH,
    "ripgrep": ToolKind.SEARCH,
    # Execute / shell
    "execute": ToolKind.EXECUTE,
    "bash": ToolKind.EXECUTE,
    "shell": ToolKind.EXECUTE,
    "run": ToolKind.EXECUTE,
    "terminal": ToolKind.EXECUTE,
    "exec": ToolKind.EXECUTE,
    # Think
    "think": ToolKind.THINK,
    # Fetch / network
    "fetch": ToolKind.FETCH,
    "curl": ToolKind.FETCH,
    "http": ToolKind.FETCH,
    "download": ToolKind.FETCH,
    "web": ToolKind.FETCH,
    # Mode switching
    "switch_mode": ToolKind.SWITCH_MODE,
}

# Substring fallbacks for tool names that don't match exactly
_TOOL_KIND_SUBSTRING_RULES: list[tuple[str, ToolKind]] = [
    ("read", ToolKind.READ),
    ("edit", ToolKind.EDIT),
    ("write", ToolKind.EDIT),
    ("delete", ToolKind.DELETE),
    ("remove", ToolKind.DELETE),
    ("move", ToolKind.MOVE),
    ("rename", ToolKind.MOVE),
    ("search", ToolKind.SEARCH),
    ("grep", ToolKind.SEARCH),
    ("glob", ToolKind.SEARCH),
    ("exec", ToolKind.EXECUTE),
    ("bash", ToolKind.EXECUTE),
    ("shell", ToolKind.EXECUTE),
    ("terminal", ToolKind.EXECUTE),
    ("think", ToolKind.THINK),
    ("fetch", ToolKind.FETCH),
    ("curl", ToolKind.FETCH),
]


def _classify_tool_kind(tool_name: str) -> ToolKind:
    """Classify a tool name into a ``ToolKind`` category.

    Two-pass: exact match on lowered name, then substring scan.
    Defaults to ``ToolKind.OTHER``.
    """
    lower = tool_name.lower()
    # Exact match
    kind = _TOOL_KIND_MAP.get(lower)
    if kind is not None:
        return kind
    # Substring fallback
    for keyword, kind in _TOOL_KIND_SUBSTRING_RULES:
        if keyword in lower:
            return kind
    return ToolKind.OTHER


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

        # Broadcast hooks: called on every event (used by worker bridge relay).
        self._broadcast_hooks: list[Callable[[ServerEvent], Awaitable[None]]] = []

        # Per-thread ingest queues for backpressure (research §1.3)
        self._ingest_queues: dict[str, asyncio.Queue[dict[str, Any] | None]] = {}
        # Per-thread fan-out tasks
        self._fanout_tasks: dict[str, asyncio.Task[None]] = {}

        # Per-thread token chunk buffers for batching (research §1.3).
        # M1: key is thread_id only; two agents in the same thread with the same
        # message_id would collide. The message_id-change detection in
        # _buffer_message_chunk handles sequential agents; for true concurrent
        # agents within one thread the run_id (= message_id) differs per LLM run,
        # so the flush-on-change guard prevents cross-agent contamination.
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

        # Node metadata cache: node_name -> {role, display_name, description}
        # Populated by register_graph() after compile_team_graph() (ADR-012 §6).
        self._node_metadata: dict[str, dict[str, str]] = {}

        # Per-thread cancellation events for ingest loops (Fix 15 / M4).
        self._cancel_events: dict[str, asyncio.Event] = {}

        # Debounce flush tasks
        self._debounce_tasks: set[asyncio.Task[None]] = set()

        # MCP-R5: track pending permission requests per thread.
        # Maps request_id -> (PermissionRequestEvent, created_at_monotonic).
        # Cleared when a permission response is received.
        self._pending_permissions: dict[str, tuple[PermissionRequestEvent, float]] = {}

        # P8-02: track agent lifecycle states for team status endpoint.
        # Maps agent_id -> AgentLifecycleState. Updated by emit_agent_status()
        # and sync_worker_event().
        self._agent_states: dict[str, AgentLifecycleState] = {}

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

    # ------------------------------------------------------------------
    # Graph registration (ADR-012 §6)
    # ------------------------------------------------------------------

    def register_graph(self, graph: StreamableGraph) -> None:
        """Cache node metadata from a compiled LangGraph graph.

        Call this after ``compile_team_graph()`` so that subsequent
        ``emit_team_status`` calls can enrich ``AgentSummary`` with
        ``role``, ``display_name``, and ``description`` sourced from node
        metadata set at compile time (ADR-012 §6).

        Args:
            graph: A compiled LangGraph graph.  Accessed structurally via
                   ``graph.nodes`` — no direct langgraph import required.
        """
        self._node_metadata = {}
        for node_name, node_spec in getattr(graph, "nodes", {}).items():
            meta = getattr(node_spec, "metadata", None) or {}
            if meta:
                self._node_metadata[node_name] = {
                    "role": str(meta.get("role", "")),
                    "display_name": str(meta.get("display_name", "")),
                    "description": str(meta.get("description", "")),
                }
        logger.debug(
            "register_graph: cached metadata for %d nodes", len(self._node_metadata)
        )

    def get_node_summaries(self) -> list[dict[str, str]]:
        """Return a list of node metadata dicts for the team status endpoint.

        Each dict contains ``node_name``, ``role``, ``display_name``, and
        ``description`` as populated by ``register_graph()``.
        """
        return [
            {"node_name": name, "agent_id": name, **meta}
            for name, meta in self._node_metadata.items()
        ]

    # ------------------------------------------------------------------
    # Subscriber count helpers
    # ------------------------------------------------------------------

    def subscriber_count(self) -> int:
        """Return the number of currently registered subscribers."""
        return len(self._subscribers)

    def subscription_count(self) -> int:
        """Return the number of clients with active subscriptions."""
        return len(self._subscriptions)

    def sequence_count(self) -> int:
        """Return the number of threads that have received at least one event."""
        return len(self._sequences)

    def prune_sequences(self, active_thread_ids: set[str]) -> int:
        """Remove sequence counters for threads not in *active_thread_ids*.

        M2: ``_sequences`` grows without bound as threads are created.  Call
        this periodically (e.g. after thread completion) to reclaim memory for
        threads that are no longer active.

        Args:
            active_thread_ids: Set of thread IDs that should be retained.

        Returns:
            The number of sequence entries removed.
        """
        stale = [tid for tid in self._sequences if tid not in active_thread_ids]
        for tid in stale:
            del self._sequences[tid]
        return len(stale)

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

    def get_subscriber_queue(self, client_id: str) -> asyncio.Queue[ServerEvent] | None:
        """Return the event queue for a subscriber, or None if not registered."""
        return self._subscribers.get(client_id)

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

    def add_broadcast_hook(
        self, hook: Callable[[ServerEvent], Awaitable[None]]
    ) -> None:
        """Register a hook called on every broadcast (worker bridge relay)."""
        self._broadcast_hooks.append(hook)

    def get_active_thread_ids(self) -> list[str]:
        """Return all thread IDs that have at least one subscriber.

        Takes a snapshot of subscription values before iterating to avoid
        RuntimeError if a subscriber is added/removed concurrently (H1 fix).
        """
        all_threads: set[str] = set()
        for threads in list(self._subscriptions.values()):
            all_threads.update(threads)
        return sorted(all_threads)

    # ------------------------------------------------------------------
    # Thread cancellation (Fix 15 / M4)
    # ------------------------------------------------------------------

    def cancel_thread(self, thread_id: str) -> None:
        """Signal cancellation for a running ingest on *thread_id*.

        The ``ingest`` method checks the cancellation event between each
        ``astream_events`` iteration and exits early when set.
        """
        event = self._cancel_events.get(thread_id)
        if event is not None:
            event.set()
            logger.info("Cancellation requested for thread %s", thread_id)
        else:
            logger.debug(
                "No active cancel event for thread %s (may not be ingesting)",
                thread_id,
            )

    def _get_cancel_event(self, thread_id: str) -> asyncio.Event:
        """Return (or create) the cancellation event for *thread_id*."""
        if thread_id not in self._cancel_events:
            self._cancel_events[thread_id] = asyncio.Event()
        return self._cancel_events[thread_id]

    def _clear_cancel_event(self, thread_id: str) -> None:
        """Remove the cancellation event for *thread_id*."""
        self._cancel_events.pop(thread_id, None)

    # ------------------------------------------------------------------
    # Broadcasting
    # ------------------------------------------------------------------

    async def _broadcast(self, event: ServerEvent) -> None:
        """Fan out a server event to all interested subscribers.

        Uses a drop-oldest strategy: if a subscriber queue is full,
        the oldest buffered event is discarded before inserting the new
        one.  This keeps the aggregator non-blocking while bounding
        per-client memory (research §1.5).  A slow client loses tail
        events rather than stalling the whole broadcast path.
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
                    if queue.full():
                        try:
                            queue.get_nowait()
                            logger.warning(
                                "Dropped oldest event for slow client %s "
                                "(queue full, maxsize=%d)",
                                client_id,
                                queue.maxsize,
                            )
                        except asyncio.QueueEmpty:
                            pass
                    # H2: guard put_nowait against QueueFull in case the queue
                    # is still full after the drop-oldest attempt (race condition
                    # or concurrent producers).  Log and skip rather than crash.
                    try:
                        queue.put_nowait(event)
                    except asyncio.QueueFull:
                        logger.warning(
                            "Event dropped for client %s — queue still full after "
                            "drop-oldest (concurrent producer race)",
                            client_id,
                        )
                        continue
                    delivered += 1
            _events_emitted_counter.add(1, {"event.type": str(event_type)})
            for hook in self._broadcast_hooks:
                try:
                    await hook(event)
                except Exception:
                    logger.warning("Broadcast hook failed", exc_info=True)

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
        # Detect message_id change: a new LLM run started before the previous
        # buffer was flushed (possible in multi-node topologies where node A ends
        # and node B begins streaming before the 50ms timer fires).
        # Flush the stale buffer immediately so its chunks carry the correct
        # agent_id / message_id rather than being mixed with the new run.
        existing_meta = self._chunk_buffer_meta.get(thread_id)
        if existing_meta and existing_meta["message_id"] != message_id:
            existing_task = self._chunk_flush_tasks.pop(thread_id, None)
            if existing_task is not None:
                existing_task.cancel()
            await self._flush_chunk_buffer(thread_id)

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
        Uses model_copy() rather than object.__setattr__() to respect Pydantic
        model immutability (H3 fix).
        """
        thread_id = getattr(event, "thread_id", None)
        if thread_id is not None and hasattr(event, "sequence"):
            event = event.model_copy(
                update={
                    "sequence": self._next_sequence(thread_id),
                    "timestamp": datetime.now(UTC),
                }
            )
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
        self._agent_states[agent_id] = state
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
        # BE-03: push team_status on every agent transition so browsers
        # see the full agent table update in real time.
        await self._emit_team_status_from_agent_states(thread_id)

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
        input_args: dict[str, Any] | None = None,
    ) -> None:
        """Emit a tool invocation start event."""
        content: list[ToolCallContent] = []
        if input_args:
            # Summarise input args as a text content block (truncate large values)
            try:
                args_str = json.dumps(input_args, default=str, ensure_ascii=False)
            except (TypeError, ValueError):
                args_str = str(input_args)
            if len(args_str) > _TOOL_ARG_TRUNCATE_LEN:
                args_str = args_str[:_TOOL_ARG_TRUNCATE_LEN] + "..."
            content.append(ToolCallContentText(text=args_str))
        event = ToolCallStartEvent(
            thread_id=thread_id,
            agent_id=agent_id,
            tool_call_id=tool_call_id,
            title=title,
            kind=kind,
            status=ToolCallStatus.PENDING,
            content=content,
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
        content: list[ToolCallContent] | None = None,
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
            content=content,
            timestamp=datetime.now(UTC),
            sequence=self._next_sequence(thread_id),
        )

        last_emit = self._tool_update_last_emit.get(key, 0.0)
        if now - last_emit >= _TOOL_CALL_UPDATE_DEBOUNCE:
            # Enough time has passed, emit immediately
            self._tool_update_last_emit[key] = now
            # AGG-03: cap map size to prevent unbounded growth across threads.
            if len(self._tool_update_last_emit) > _DEBOUNCE_MAP_MAX_ENTRIES:
                _evict_oldest(self._tool_update_last_emit, _DEBOUNCE_MAP_MAX_ENTRIES)
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
        tool_kind: ToolKind | None = None,
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

        # Derive tool_kind from tool_call name if not explicitly provided
        resolved_kind = tool_kind
        if resolved_kind is None and tool_call:
            resolved_kind = _classify_tool_kind(tool_call)

        event = PermissionRequestEvent(
            thread_id=thread_id,
            agent_id=agent_id,
            request_id=request_id,
            description=description,
            options=parsed_options,
            tool_call=tool_call,
            tool_kind=resolved_kind,
            timestamp=datetime.now(UTC),
            sequence=self._next_sequence(thread_id),
        )
        # MCP-R5: track pending permission for REST query
        self._pending_permissions[request_id] = (event, time.monotonic())
        await self._broadcast(event)

    def resolve_permission(self, request_id: str) -> None:
        """Remove a permission request from the pending set (MCP-R5).

        Called by the permission response endpoint after the user responds.
        """
        self._pending_permissions.pop(request_id, None)

    def prune_stale_permissions(self, max_age_seconds: float = 300.0) -> int:
        """Remove permission requests older than *max_age_seconds*.

        Returns the number of stale permissions removed.
        """
        cutoff = time.monotonic() - max_age_seconds
        stale = [
            rid
            for rid, (_evt, created_at) in self._pending_permissions.items()
            if created_at < cutoff
        ]
        for rid in stale:
            del self._pending_permissions[rid]
        if stale:
            logger.info("Pruned %d stale permission request(s)", len(stale))
        return len(stale)

    def get_pending_permissions(
        self,
        thread_id: str | None = None,
    ) -> list[PermissionRequestEvent]:
        """Return pending permissions, optionally filtered by thread."""
        if thread_id is None:
            return [evt for evt, _ts in self._pending_permissions.values()]
        return [
            evt
            for evt, _ts in self._pending_permissions.values()
            if evt.thread_id == thread_id
        ]

    def get_agent_states(self) -> dict[str, AgentLifecycleState]:
        """Return a snapshot of current agent lifecycle states (P8-02)."""
        return dict(self._agent_states)

    def sync_worker_event(
        self,
        thread_id: str,
        payload: dict[str, Any],
    ) -> None:
        """Sync a relayed worker event into aggregator state (P8-01).

        Called by internal.py after broadcasting the raw event to WS
        clients.  Updates agent states and pending permissions so the
        REST endpoints reflect the real worker state.
        """
        event_type = payload.get("type", "")

        if event_type == "agent_status":
            agent_id = payload.get("agent_id", "")
            raw_state = payload.get("state", "")
            if agent_id and raw_state:
                try:
                    lifecycle = AgentLifecycleState(raw_state)
                except ValueError:
                    logger.warning(
                        "Unknown agent state %r in relayed event",
                        raw_state,
                    )
                    return
                self._agent_states[agent_id] = lifecycle
            self._next_sequence(thread_id)

        elif event_type == "permission_request":
            request_id = payload.get("request_id", "")
            if request_id:
                description = payload.get("description", "")
                options = payload.get("options", [])
                perm_options = []
                for opt in options:
                    perm_options.append(
                        PermissionOption(
                            option_id=opt.get("option_id", ""),
                            name=opt.get("name", ""),
                            kind=_map_acp_option_kind(opt.get("option_id", "")),
                        )
                    )
                self._pending_permissions[request_id] = (
                    PermissionRequestEvent(
                        thread_id=thread_id,
                        agent_id=payload.get("agent_id", ""),
                        request_id=request_id,
                        description=description,
                        options=perm_options,
                        timestamp=datetime.now(UTC),
                        sequence=self._next_sequence(thread_id),
                    ),
                    time.monotonic(),
                )

        elif event_type == "permission_resolved":
            request_id = payload.get("request_id", "")
            if request_id:
                self._pending_permissions.pop(request_id, None)
            self._next_sequence(thread_id)

        elif event_type == "graph_registered":
            # BE-12: sync node metadata from worker after graph compilation.
            # Payload: {"type": "graph_registered",
            #   "nodes": {"name": {role, display_name, ...}, ...}}
            nodes = payload.get("nodes", {})
            if isinstance(nodes, dict):
                self._node_metadata = {
                    name: {
                        "role": str(meta.get("role", "")),
                        "display_name": str(meta.get("display_name", "")),
                        "description": str(meta.get("description", "")),
                    }
                    for name, meta in nodes.items()
                    if isinstance(meta, dict)
                }
                logger.debug(
                    "sync_worker_event: cached metadata for %d nodes",
                    len(self._node_metadata),
                )

        elif event_type == "plan_update":
            # BE-28: plan updates relayed from worker.  The WS relay in
            # internal.py already broadcasts the raw event to connected
            # clients, so sync_worker_event only needs to bump the sequence
            # counter for ordering consistency.
            self._next_sequence(thread_id)

        elif event_type == "artifact_update":
            # BE-29: relay artifact updates from worker to API aggregator.
            artifact_id = payload.get("artifact_id", "")
            filename = payload.get("filename", "")
            if artifact_id and filename:
                self._next_sequence(thread_id)

        # API CRIT-01 / HIGH-07: advance sequence for ALL event types that
        # carry a thread_id so last_sequence is reliable for reconnection
        # gap detection.  The handlers above already call _next_sequence
        # for their specific types; this catch-all covers message_chunk,
        # tool_call_start, tool_call_update, artifact_update, error, etc.
        elif thread_id and event_type:
            self._next_sequence(thread_id)

    async def emit_artifact_update(
        self,
        thread_id: str,
        artifact_id: str,
        filename: str,
        content: str,
        append: bool = False,
        last_chunk: bool = True,
    ) -> None:
        """Emit an artifact update event (BE-29)."""
        event = ArtifactUpdateEvent(
            thread_id=thread_id,
            artifact_id=artifact_id,
            filename=filename,
            content=content,
            append=append,
            last_chunk=last_chunk,
            timestamp=datetime.now(UTC),
            sequence=self._next_sequence(thread_id),
        )
        await self._broadcast(event)

    async def emit_plan_update(
        self,
        thread_id: str,
        entries: list[PlanEntry],
    ) -> None:
        """Emit a plan update event (debounced, BE-28).

        Uses the existing ``_plan_update_pending`` / ``_plan_update_last_emit``
        debounce infrastructure to coalesce rapid plan changes.
        """
        event = PlanUpdateEvent(
            thread_id=thread_id,
            entries=entries,
            timestamp=datetime.now(UTC),
            sequence=self._next_sequence(thread_id),
        )
        now = time.monotonic()
        last = self._plan_update_last_emit.get(thread_id, 0.0)
        if now - last >= _PLAN_UPDATE_DEBOUNCE:
            self._plan_update_last_emit[thread_id] = now
            await self._broadcast(event)
        else:
            async with self._lock:
                self._plan_update_pending[thread_id] = event
            self._schedule_debounce(self._broadcast_debounced_plan_update(thread_id))

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

    async def _emit_team_status_from_agent_states(
        self,
        thread_id: str,
    ) -> None:
        """Build agents list from ``_agent_states`` and emit ``team_status``.

        Called automatically after every ``emit_agent_status()`` so browsers
        receive the full agent table on each transition (BE-03).
        """
        agents: list[dict[str, Any]] = []
        for agent_id, lifecycle in self._agent_states.items():
            agents.append(
                {
                    "agent_id": agent_id,
                    "node_name": agent_id,
                    "state": lifecycle.value,
                }
            )
        await self.emit_team_status(thread_id, agents)

    async def emit_team_status(
        self,
        thread_id: str,
        agents: list[dict[str, Any]],
        active_thread_ids: list[str] | None = None,
    ) -> None:
        """Emit a team status event (on transitions only, per ADR-011 §5).

        role/display_name/description are sourced from the node metadata cache
        populated by ``register_graph()`` (ADR-012 §6).  Values already present
        in each agent dict take precedence; the cache fills any gaps.
        """
        agent_summaries: list[AgentSummary] = []
        for agent_data in agents:
            data = dict(agent_data)
            node_name = data.get("node_name", "")
            node_meta = self._node_metadata.get(node_name, {})
            data.setdefault("role", node_meta.get("role", ""))
            data.setdefault("display_name", node_meta.get("display_name", ""))
            data.setdefault("description", node_meta.get("description", ""))
            agent_summaries.append(AgentSummary(**data))

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

    async def process_langgraph_event(  # noqa: PLR0911, PLR0915
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

        # Attribute events to the graph node that fired them (e.g. "coder",
        # "reviewer") rather than the outer invocation context ("supervisor").
        # In all LangGraph topologies, the node name IS the agent_id for worker
        # nodes; the supervisor node itself is named "supervisor" so the fallback
        # is accurate for top-level events that lack node metadata.
        effective_agent_id = node or agent_id

        # --- Passthrough events (no node filter needed for LLM/tool) ---
        if event_kind == "on_chat_model_stream":
            chunk = event_data.get("data", {}).get("chunk")
            if chunk is not None:
                content = getattr(chunk, "content", "")
                # BE-26: content may be a list of structured blocks (Anthropic format).
                # Extract text blocks for message content and
                # reasoning blocks for thoughts.
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict):
                            if block.get("type") == "reasoning":
                                reasoning_text = block.get("content", "") or block.get(
                                    "text", ""
                                )
                                if reasoning_text:
                                    await self.emit_thought_chunk(
                                        thread_id=thread_id,
                                        agent_id=effective_agent_id,
                                        content=reasoning_text,
                                        message_id=run_id,
                                    )
                            elif block.get("type") in ("text", "text_delta"):
                                text = block.get("text", "") or block.get("content", "")
                                if text:
                                    await self._buffer_message_chunk(
                                        thread_id=thread_id,
                                        agent_id=effective_agent_id,
                                        content=text,
                                        message_id=run_id,
                                    )
                elif isinstance(content, str) and content:
                    await self._buffer_message_chunk(
                        thread_id=thread_id,
                        agent_id=effective_agent_id,
                        content=content,
                        message_id=run_id,
                    )
                # BE-26: extract reasoning from additional_kwargs
                # (OpenAI/DeepSeek format).
                # Only check when content is NOT a list — Anthropic-style structured
                # blocks already emit reasoning above, so this avoids duplicates.
                if not isinstance(content, list):
                    additional_kwargs = getattr(chunk, "additional_kwargs", {}) or {}
                    reasoning = (
                        additional_kwargs.get("reasoning")
                        or additional_kwargs.get("reasoning_content")
                        or ""
                    )
                    if reasoning:
                        await self.emit_thought_chunk(
                            thread_id=thread_id,
                            agent_id=effective_agent_id,
                            content=reasoning,
                            message_id=run_id,
                        )
            return

        # BE-27: flush chunk buffer and emit finish_reason when LLM call ends.
        if event_kind == "on_chat_model_end":
            await self._flush_chunk_buffer(thread_id)
            output = event_data.get("data", {}).get("output")
            finish_reason: str | None = None
            if output is not None:
                resp_meta = getattr(output, "response_metadata", None) or {}
                finish_reason = resp_meta.get("finish_reason") or resp_meta.get(
                    "stop_reason"
                )
            if finish_reason:
                await self.emit_message_chunk(
                    thread_id=thread_id,
                    agent_id=effective_agent_id,
                    content="",
                    message_id=run_id,
                    finish_reason=finish_reason,
                )
            return

        if event_kind == "on_tool_start":
            if node:  # Only emit for graph-level tool calls
                tool_name = event_data.get("name", "unknown_tool")
                tool_input = event_data.get("data", {}).get("input")
                input_args = tool_input if isinstance(tool_input, dict) else None
                await self.emit_tool_call_start(
                    thread_id=thread_id,
                    agent_id=effective_agent_id,
                    tool_call_id=run_id,
                    title=tool_name,
                    kind=_classify_tool_kind(tool_name),
                    input_args=input_args,
                )
            return

        if event_kind == "on_tool_end":
            if node:  # Only emit for graph-level tool calls
                # BE-30: extract tool output for content enrichment
                tool_name = event_data.get("name", "")
                output = event_data.get("data", {}).get("output")
                output_content: list[ToolCallContent] | None = None
                if output is not None:
                    output_str = ""
                    if hasattr(output, "content"):
                        output_str = str(output.content)
                    elif isinstance(output, str):
                        output_str = output
                    else:
                        output_str = str(output)
                    if output_str:
                        if len(output_str) > _TOOL_ARG_TRUNCATE_LEN:
                            output_str = output_str[:_TOOL_ARG_TRUNCATE_LEN] + "..."
                        output_content = [ToolCallContentText(text=output_str)]
                await self.emit_tool_call_update(
                    thread_id=thread_id,
                    agent_id=effective_agent_id,
                    tool_call_id=run_id,
                    status=ToolCallStatus.COMPLETED,
                    content=output_content,
                )
                # BE-29: inspect tool output for file artifacts.
                _file_tool_keywords = {
                    "write",
                    "edit",
                    "create",
                    "save",
                    "move",
                    "rename",
                    "delete",
                }
                if any(kw in tool_name.lower() for kw in _file_tool_keywords):
                    # Extract file path from tool output or input
                    output_str = ""
                    file_path = ""
                    if hasattr(output, "content"):
                        output_str = str(output.content)
                    elif isinstance(output, str):
                        output_str = output
                    # Try to extract file_path from tool input
                    tool_input = event_data.get("data", {}).get("input", {})
                    if isinstance(tool_input, dict):
                        file_path = (
                            tool_input.get("file_path", "")
                            or tool_input.get("path", "")
                            or tool_input.get("filename", "")
                        )
                    if file_path:
                        filename = (
                            file_path.rsplit("/", 1)[-1]
                            if "/" in file_path
                            else file_path
                        )
                        await self.emit_artifact_update(
                            thread_id=thread_id,
                            artifact_id=f"{run_id}:{file_path}",
                            filename=filename,
                            content=output_str[:500]
                            if output_str
                            else f"[{tool_name}] {file_path}",
                        )
            return

        if event_kind == "on_tool_error":
            if node:  # Only emit for graph-level tool calls
                error_data = event_data.get("data", {})
                error_msg = str(error_data.get("error", "Tool call failed"))
                logger.warning(
                    "Tool error in thread %s node %s: %s",
                    thread_id,
                    node,
                    error_msg,
                )
                error_content: list[ToolCallContent] | None = (
                    [ToolCallContentText(text=error_msg)] if error_msg else None
                )
                await self.emit_tool_call_update(
                    thread_id=thread_id,
                    agent_id=effective_agent_id,
                    tool_call_id=run_id,
                    status=ToolCallStatus.FAILED,
                    content=error_content,
                )
            return

        if event_kind == "on_custom_event":
            # Custom events via StreamWriter map to thought chunks
            data = event_data.get("data", {})
            content = data if isinstance(data, str) else str(data.get("content", ""))
            if content:
                await self.emit_thought_chunk(
                    thread_id=thread_id,
                    agent_id=effective_agent_id,
                    content=content,
                    message_id=run_id,
                )
            return

        # --- Node boundary events (require langgraph_node metadata) ---
        if event_kind in _NODE_BOUNDARY_EVENTS and node:
            if event_kind == "on_chain_start":
                await self.emit_agent_status(
                    thread_id=thread_id,
                    agent_id=effective_agent_id,
                    node_name=node,
                    state=AgentLifecycleState.WORKING,
                )
            elif event_kind == "on_chain_end":
                await self.emit_agent_status(
                    thread_id=thread_id,
                    agent_id=effective_agent_id,
                    node_name=node,
                    state=AgentLifecycleState.IDLE,
                )
                # BE-28: detect current_plan in node output and emit PlanUpdateEvent.
                output = event_data.get("data", {}).get("output")
                if isinstance(output, dict):
                    raw_plan = output.get("current_plan")
                    if raw_plan and isinstance(raw_plan, list):
                        entries = [
                            PlanEntry(
                                content=str(entry.get("content", "")),
                                status=entry.get("status", "pending"),
                                priority=entry.get("priority", "medium"),
                            )
                            for entry in raw_plan
                            if isinstance(entry, dict) and entry.get("content")
                        ]
                        if entries:
                            await self.emit_plan_update(thread_id, entries)
                    # BE-29: detect artifacts in node output.
                    raw_artifacts = output.get("artifacts")
                    if raw_artifacts and isinstance(raw_artifacts, list):
                        for artifact in raw_artifacts:
                            if isinstance(artifact, dict) and artifact.get("id"):
                                await self.emit_artifact_update(
                                    thread_id=thread_id,
                                    artifact_id=str(artifact["id"]),
                                    filename=str(
                                        artifact.get(
                                            "filename", artifact.get("path", "")
                                        )
                                    ),
                                    content=str(artifact.get("content", "")),
                                )
            elif event_kind == "on_chain_error":
                error_data = event_data.get("data", {})
                error_msg = str(error_data.get("error", "Node execution failed"))
                logger.warning(
                    "Chain error in thread %s node %s: %s",
                    thread_id,
                    node,
                    error_msg,
                )
                await self.emit_agent_status(
                    thread_id=thread_id,
                    agent_id=effective_agent_id,
                    node_name=node,
                    state=AgentLifecycleState.FAILED,
                    detail=error_msg[:200],
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
    # Interrupt detection (plan 2026-28-02)
    # ------------------------------------------------------------------

    async def _emit_interrupt_events(
        self,
        thread_id: str,
        agent_id: str,
        graph: StreamableGraph,
        config: dict[str, Any],
    ) -> None:
        """Inspect graph state after astream_events ends; emit PermissionRequestEvents.

        Called from the ``ingest()`` ``finally`` block after every graph run.
        On normal completion ``state.tasks`` is empty and this method returns
        immediately — it is a pure no-op.  When LangGraph suspends via
        ``interrupt()`` (tool-level approval request), tasks will contain
        pending interrupts that must be surfaced to the frontend.

        Args:
            thread_id: LangGraph thread_id for event routing.
            agent_id:  Fallback agent identifier (overridden by task name).
            graph:     Compiled LangGraph graph; must expose ``aget_state``.
            config:    LangGraph config dict with ``configurable.thread_id``.
        """
        # M3: aget_state timeout is configurable via _AGET_STATE_TIMEOUT
        try:
            state = await asyncio.wait_for(
                graph.aget_state(config), timeout=_AGET_STATE_TIMEOUT
            )
        except TimeoutError:
            logger.warning(
                "Timed out inspecting state for interrupt detection on thread %s",
                thread_id,
            )
            return
        except Exception:
            # H3: log as error (not silent swallow) but do NOT re-raise because
            # this method is called from the ``ingest()`` finally block — a raise
            # here would mask the original graph exception.
            logger.exception(
                "Failed to inspect state for interrupt detection on thread %s",
                thread_id,
            )
            return

        tasks = getattr(state, "tasks", None)
        if not state or not tasks or not any(t.interrupts for t in tasks):
            return  # Normal completion — no pending interrupts

        for task in tasks:
            if not task.interrupts:
                continue

            for interrupt_obj in task.interrupts:
                payload = getattr(interrupt_obj, "value", interrupt_obj)
                if not isinstance(payload, dict):
                    continue
                interrupt_type = payload.get("type")
                if interrupt_type not in (
                    "permission_request",
                    "plan_approval_request",
                ):
                    continue

                request_id = f"{thread_id}:{uuid4().hex}"

                if interrupt_type == "plan_approval_request":
                    feature: str = payload.get("feature") or "unknown"
                    plan_paths: list[str] = payload.get("plan_paths") or []
                    exec_worker: str = payload.get("exec_worker") or "unknown"
                    plan_summary = (
                        f"{len(plan_paths)} plan document(s)"
                        if plan_paths
                        else "no plan documents"
                    )
                    description = (
                        f"Approve plan for feature '{feature}' before "
                        f"routing to {exec_worker} ({plan_summary})"
                    )
                    options: list[dict[str, Any]] = [
                        {
                            "option_id": "approve",
                            "name": "Approve Plan",
                            "kind": PermissionOptionKind.ALLOW_ONCE,
                        },
                        {
                            "option_id": "reject",
                            "name": "Reject — Revise Plan",
                            "kind": PermissionOptionKind.REJECT_ONCE,
                        },
                    ]
                    await self.emit_permission_request(
                        thread_id=thread_id,
                        agent_id=task.name,
                        request_id=request_id,
                        description=description,
                        options=options,
                        tool_call=PermissionType.PLAN_APPROVAL,
                    )
                    await self.emit_agent_status(
                        thread_id=thread_id,
                        agent_id=task.name,
                        node_name=task.name,
                        state=AgentLifecycleState.INPUT_REQUIRED,
                        detail=f"Awaiting plan approval for feature '{feature}'",
                    )
                else:
                    # permission_request — existing ACP tool approval path
                    tool_name: str = payload.get("tool_name", "unknown")
                    acp_options: list[dict[str, Any]] = payload.get("options", [])

                    options = [
                        {
                            "option_id": opt.get(
                                "optionId", opt.get("option_id", "allow_once")
                            ),
                            "name": opt.get(
                                "label", opt.get("name", opt.get("optionId", "Allow"))
                            ),
                            "kind": _map_acp_option_kind(
                                opt.get("optionId", opt.get("option_id", ""))
                            ),
                        }
                        for opt in acp_options
                    ]
                    if not options:
                        options = [
                            {
                                "option_id": "allow_once",
                                "name": "Allow",
                                "kind": PermissionOptionKind.ALLOW_ONCE,
                            },
                            {
                                "option_id": "deny_once",
                                "name": "Deny",
                                "kind": PermissionOptionKind.REJECT_ONCE,
                            },
                        ]

                    await self.emit_permission_request(
                        thread_id=thread_id,
                        agent_id=task.name,
                        request_id=request_id,
                        description=f"Permission required: {tool_name}",
                        options=options,
                        tool_call=tool_name,
                    )
                    await self.emit_agent_status(
                        thread_id=thread_id,
                        agent_id=task.name,
                        node_name=task.name,
                        state=AgentLifecycleState.INPUT_REQUIRED,
                        detail=f"Awaiting approval for {tool_name}",
                    )

    # ------------------------------------------------------------------
    # LangGraph graph ingest (research §1.3)
    # ------------------------------------------------------------------

    async def ingest(
        self,
        thread_id: str,
        agent_id: str,
        graph: StreamableGraph,
        graph_input: dict[str, Any] | Command | None,
        config: dict[str, Any],
    ) -> str:
        """Start consuming ``astream_events`` from a compiled graph.

        Returns one of ``"completed"``, ``"interrupted"``, or ``"failed"``
        so callers (e.g. the worker executor) can translate the outcome
        into a thread-level status update.

        Creates a bounded ingest queue (``maxsize=512``) for backpressure
        and processes events through ``process_langgraph_event``.

        Args:
            thread_id: LangGraph thread_id for event routing.
            agent_id: Agent identifier for event attribution.
            graph: Compiled LangGraph ``StateGraph``.
            graph_input: Input to the graph invocation, or ``None`` to
                resume from the last checkpoint.
            config: LangGraph config dict (must include ``configurable.thread_id``).
        """
        start = time.monotonic()
        cancel_event = self._get_cancel_event(thread_id)
        # H4: track whether an interrupt occurred so _emit_interrupt_events is
        # only called when needed (avoids aget_state I/O on normal completion).
        _is_interrupt = False
        _outcome = "completed"
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
                    if cancel_event.is_set():
                        logger.info("Ingest cancelled for thread %s", thread_id)
                        _outcome = "cancelled"
                        span.set_attribute("cancelled", True)
                        await self.emit_agent_status(
                            thread_id=thread_id,
                            agent_id=agent_id,
                            node_name="supervisor",
                            state=AgentLifecycleState.CANCELLED,
                            detail="Terminated by user",
                        )
                        break
                    await self.process_langgraph_event(
                        event_data=raw_event,
                        thread_id=thread_id,
                        agent_id=agent_id,
                    )
            except BaseException as exc:
                # M6: use isinstance for GraphInterrupt detection instead of
                # string class name comparison (robust across LangGraph versions).
                # C1 fix: GraphInterrupt (BaseException subclass) signals a
                # legitimate graph suspension for human-in-the-loop approval.
                # Do NOT emit a spurious INGEST_ERROR — let the finally block
                # call _emit_interrupt_events to surface the permission request.
                _is_interrupt = (
                    _GraphInterrupt is not None and isinstance(exc, _GraphInterrupt)
                ) or exc.__class__.__name__ == "GraphInterrupt"
                _is_recursion_limit = (
                    _GraphRecursionError is not None
                    and isinstance(exc, _GraphRecursionError)
                ) or exc.__class__.__name__ == "GraphRecursionError"
                _is_step_timeout = isinstance(exc, TimeoutError)
                if _is_interrupt:
                    _outcome = "interrupted"
                    logger.info(
                        "Graph interrupted for thread %s (awaiting approval)",
                        thread_id,
                    )
                    span.set_attribute("interrupted", True)
                elif _is_recursion_limit:
                    _outcome = "failed"
                    logger.warning(
                        "Graph recursion limit reached for thread %s", thread_id
                    )
                    span.set_attribute("error.type", "recursion_limit")
                    await self.emit_error(
                        thread_id=thread_id,
                        agent_id=agent_id,
                        code="RECURSION_LIMIT_EXCEEDED",
                        message=(
                            "Graph recursion limit reached — check recursion_limit"
                            " configuration"
                        ),
                        recoverable=False,
                    )
                elif _is_step_timeout:
                    _outcome = "failed"
                    logger.warning("Graph step_timeout fired for thread %s", thread_id)
                    span.set_attribute("error.type", "step_timeout")
                    await self.emit_error(
                        thread_id=thread_id,
                        agent_id=agent_id,
                        code="STEP_TIMEOUT",
                        message=(
                            "A graph node exceeded the step timeout — "
                            "the operation may be retried"
                        ),
                        recoverable=True,
                    )
                else:
                    _outcome = "failed"
                    logger.exception(
                        "Error during graph ingest for thread %s", thread_id
                    )
                    span.set_attribute("error", True)
                    await self.emit_error(
                        thread_id=thread_id,
                        agent_id=agent_id,
                        code="INGEST_ERROR",
                        message="Graph event stream failed unexpectedly",
                        recoverable=False,
                    )
            finally:
                # Clean up cancel event and flush remaining chunks
                self._clear_cancel_event(thread_id)
                await self._flush_chunk_buffer(thread_id)
                # AGG-03: prune per-thread debounce timestamp maps so they
                # don't grow unbounded across many completed ingests.
                stale_tool_keys = [
                    k for k in self._tool_update_last_emit if k[0] == thread_id
                ]
                for k in stale_tool_keys:
                    del self._tool_update_last_emit[k]
                self._plan_update_last_emit.pop(thread_id, None)
                # H4: only call _emit_interrupt_events when an actual interrupt
                # occurred — skips the aget_state I/O on normal completion.
                if _is_interrupt:
                    await self._emit_interrupt_events(
                        thread_id, agent_id, graph, config
                    )
                _ingest_duration_histogram.record(
                    time.monotonic() - start,
                    {"thread_id": thread_id},
                )
        return _outcome

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

        # Cancel chunk flush tasks and await them to ensure clean shutdown (M7).
        chunk_flush_tasks = list(self._chunk_flush_tasks.values())
        for task in chunk_flush_tasks:
            task.cancel()
        if chunk_flush_tasks:
            await asyncio.gather(*chunk_flush_tasks, return_exceptions=True)
        self._chunk_flush_tasks.clear()

        self._subscribers.clear()
        self._subscriptions.clear()
        self._sequences.clear()
        self._chunk_buffers.clear()
        self._chunk_buffer_meta.clear()
        self._cancel_events.clear()
        self._tool_update_last_emit.clear()
        self._plan_update_last_emit.clear()
