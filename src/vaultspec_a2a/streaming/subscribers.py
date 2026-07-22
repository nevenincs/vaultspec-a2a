"""Subscriber management for the streaming event bus.

Manages client WebSocket connections, thread subscriptions, broadcast hooks,
and the graph node metadata cache.  Extracted from the monolithic
``aggregator.py`` during the aggregator decomposition.
"""

import asyncio
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable

from vaultspec_a2a.thread.errors import EventAggregatorError

from ..domain_config import domain_config
from ..graph.protocols import NullTelemetryHook, TelemetryHook
from .fanout import deliver_bounded
from .types import SequencedEvent, StreamableGraph

logger = logging.getLogger(__name__)


class SubscriberManager:
    """Client connection state.

    Manages queues, subscriptions, broadcast hooks, and node metadata.
    """

    def __init__(self, telemetry: TelemetryHook | NullTelemetryHook) -> None:
        # Subscriber queues: client_id -> bounded asyncio.Queue
        self._subscribers: dict[str, asyncio.Queue[SequencedEvent]] = {}
        # Which threads each client is subscribed to: client_id -> set of thread_ids
        self._subscriptions: dict[str, set[str]] = defaultdict(set)
        # Broadcast hooks: called on every event (used by worker bridge relay).
        self._broadcast_hooks: list[Callable[[SequencedEvent], Awaitable[None]]] = []
        # Node metadata cache: node_name -> {role, display_name, description}
        self._node_metadata: dict[str, dict[str, str]] = {}
        # Lock for subscriber mutation
        self._lock = asyncio.Lock()
        self._telemetry = telemetry

    # ------------------------------------------------------------------
    # Subscriber management
    # ------------------------------------------------------------------

    def add_subscriber(self, client_id: str) -> asyncio.Queue[SequencedEvent]:
        """Register a new subscriber and return its bounded event queue."""
        queue: asyncio.Queue[SequencedEvent] = asyncio.Queue(
            maxsize=domain_config.event_queue_maxsize
        )
        self._subscribers[client_id] = queue
        self._subscriptions[client_id] = set()
        return queue

    def get_subscriber_queue(
        self, client_id: str
    ) -> asyncio.Queue[SequencedEvent] | None:
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

    def remove_thread(self, thread_id: str) -> None:
        """Remove ``thread_id`` from every active subscriber subscription set."""
        for client_id in list(self._subscriptions):
            self._subscriptions[client_id].discard(thread_id)

    def add_broadcast_hook(
        self, hook: Callable[[SequencedEvent], Awaitable[None]]
    ) -> None:
        """Register a hook called on every broadcast (worker bridge relay)."""
        self._broadcast_hooks.append(hook)

    def subscriber_count(self) -> int:
        """Return the number of currently registered subscribers."""
        return len(self._subscribers)

    def subscription_count(self) -> int:
        """Return the number of clients with active subscriptions."""
        return len(self._subscriptions)

    def get_subscriptions(self, client_id: str) -> frozenset[str]:
        """Return a frozen snapshot of the thread subscriptions for *client_id*."""
        return frozenset(self._subscriptions.get(client_id, set()))

    def get_active_thread_ids(self) -> list[str]:
        """Return all thread IDs that have at least one subscriber.

        Takes a snapshot of subscription values before iterating to avoid
        RuntimeError if a subscriber is added/removed concurrently (H1 fix).
        """
        all_threads: set[str] = set()
        for threads in list(self._subscriptions.values()):
            all_threads.update(threads)
        return sorted(all_threads)

    def enqueue_payload(self, thread_id: str, payload: object) -> None:
        """Enqueue a pre-serialized payload for all subscribers of ``thread_id``."""
        for client_id, queue in list(self._subscribers.items()):
            client_subs = self._subscriptions.get(client_id, set())
            if thread_id not in client_subs:
                continue
            deliver_bounded(queue, payload, client_id=client_id)

    # ------------------------------------------------------------------
    # Graph registration
    # ------------------------------------------------------------------

    def register_graph(self, graph: StreamableGraph) -> None:
        """Cache node metadata from a compiled LangGraph graph."""
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
        """Return a list of node metadata dicts for the team status endpoint."""
        return [
            {"node_name": name, "agent_id": name, **meta}
            for name, meta in self._node_metadata.items()
        ]

    def get_node_metadata(self) -> dict[str, dict[str, str]]:
        """Return the raw node metadata dict (used by emitters)."""
        return self._node_metadata

    def set_node_metadata(self, metadata: dict[str, dict[str, str]]) -> None:
        """Replace node metadata (used by sync_worker_event)."""
        self._node_metadata = metadata

    # ------------------------------------------------------------------
    # Broadcasting
    # ------------------------------------------------------------------

    async def broadcast(self, sequenced: SequencedEvent) -> None:
        """Fan out a sequenced domain event to all interested subscribers.

        Uses a drop-oldest strategy: if a subscriber queue is full,
        the oldest buffered event is discarded before inserting the new
        one.  This keeps the aggregator non-blocking while bounding
        per-client memory (research §1.5).
        """
        thread_id = getattr(sequenced.event, "thread_id", None)
        event_type = type(sequenced.event).__name__

        with self._telemetry.start_span(
            "aggregator.broadcast",
            **{"event.type": str(event_type), "thread_id": thread_id or ""},
        ):
            delivered = 0
            for client_id, queue in list(self._subscribers.items()):
                client_subs = self._subscriptions.get(client_id, set())
                subscribed = thread_id is None or thread_id in client_subs
                if subscribed and deliver_bounded(
                    queue, sequenced, client_id=client_id
                ):
                    delivered += 1
            self._telemetry.increment_counter(
                "aggregator.events_emitted", 1, **{"event.type": str(event_type)}
            )
            for hook in self._broadcast_hooks:
                try:
                    await hook(sequenced)
                except Exception:
                    logger.warning("Broadcast hook failed", exc_info=True)

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Clear all subscriber state."""
        self._subscribers.clear()
        self._subscriptions.clear()
