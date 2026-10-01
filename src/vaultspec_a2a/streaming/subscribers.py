"""Subscriber management for the streaming event bus.

Manages client WebSocket connections, thread subscriptions, broadcast hooks,
and the graph node metadata cache.  Extracted from the monolithic
``aggregator.py`` during the aggregator decomposition.

This module also owns the one place a run's authoritative event sequence is
allocated. Every frame a subscriber receives passes through
:meth:`SubscriberManager.enqueue_payload` or :meth:`SubscriberManager.broadcast`,
so numbering there - and only there - gives a relayed worker payload and an
in-process domain event exactly one number each from one counter. A process
that binds no allocator (the worker's own aggregator, or a gateway serving no
replay) numbers nothing and behaves exactly as it did before.
"""

import asyncio
import logging
from collections import OrderedDict, defaultdict
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, cast

from ..domain_config import domain_config
from ..graph.protocols import NullTelemetryHook, TelemetryHook
from ..thread.errors import EventAggregatorError
from .fanout import deliver_bounded
from .node_metadata import node_metadata_from_graph
from .types import SequencedEvent, StreamableGraph

logger = logging.getLogger(__name__)

#: Forgotten runs whose issued floor is remembered, so a reseed cannot rewind.
#:
#: Bounded for the same reason the writer bounds its rings: a gateway serving
#: runs for weeks would otherwise keep one entry per run it has ever numbered.
#: A floor evicted here belongs to a run that produced nothing while this many
#: others did, by which time its allocations are long flushed and the durable
#: mark answers at least as high.
_REMEMBERED_FLOORS = 1024

__all__ = [
    "AllocationSink",
    "RunSequenceAllocator",
    "RunSequenceSeedSource",
    "SequenceAllocation",
    "SubscriberManager",
]


@dataclass(frozen=True, slots=True)
class SequenceAllocation:
    """One run's authoritative number for one outgoing frame.

    ``allocated_at`` is stamped here rather than where the frame is later
    written, so the durable row records when the frame was PRODUCED. The write
    sits behind the fan-out and may land much later; dating a row by its write
    would misreport the age bound that expires it.
    """

    thread_id: str
    sequence: int
    allocated_at: datetime


class RunSequenceSeedSource(Protocol):
    """The two durable reads a run's numbering is established from."""

    async def high_water_mark(self, thread_id: str) -> int | None:
        """Return the greatest sequence already retained for this run."""
        ...

    async def settled_sequence(self, thread_id: str) -> int | None:
        """Return the cursor captured on this run when it settled."""
        ...


class AllocationSink(Protocol):
    """Where an allocation is recorded, between numbering and fan-out.

    Synchronous on purpose: this runs IN FRONT of the fan-out, so it may only
    do in-memory work. The durable write belongs behind the fan-out and is the
    sink's own business.
    """

    def retains(self, frame: object) -> bool:
        """Whether this sink would keep *frame* if it were numbered.

        Asked BEFORE a number is taken, which is what keeps a run's sequence
        space contiguous: a frame nothing retains leaves a permanent hole, and
        a hole costs a resume every retained frame older than it.
        """
        ...

    def record(self, allocation: SequenceAllocation, frame: object) -> None:
        """Record one numbered frame for later durable writing."""
        ...

    def discard(self, thread_id: str) -> None:
        """Drop everything held for a run whose durable home is gone."""
        ...

    async def aclose(self) -> None:
        """Stop recording and make a last attempt to write what is held."""
        ...


class RunSequenceAllocator:
    """One monotonic, restart-stable number per run, allocated in memory.

    The counter is seeded once per run per gateway lifetime, from the run's
    durable high-water mark, then advanced in process. Three outcomes, and the
    difference between them is the whole point:

    * seeded from a retained row - numbering continues where the last gateway
      left off, which is what lets a consumer resume across a restart;
    * seeded from the cursor captured at settle, or from zero for a run with
      neither - the only honest starting points left;
    * UNSEEDABLE, because the store could not be read - the run is left
      unnumbered for this process's lifetime. Restarting its numbering instead
      would hand two different frames the same number, which is exactly the
      hazard that forced the SSE id to be withdrawn once already.

    An unnumbered run still streams. It just carries no id, so no consumer is
    handed a cursor it cannot resume from.
    """

    def __init__(self, seeds: RunSequenceSeedSource) -> None:
        self._seeds = seeds
        self._counters: dict[str, int] = {}
        self._unnumbered: set[str] = set()
        # The highest number this process has already handed a forgotten run.
        # A reseed may never fall below it: the durable reads below see only
        # what has been FLUSHED, and a run forgotten with allocations still in
        # the writer's ring would otherwise restart inside a range it already
        # issued, handing two frames one number.
        self._issued: OrderedDict[str, int] = OrderedDict()
        # Seeding awaits two reads, and a second first touch of the same run
        # arriving in that window used to read the same mark and assign over
        # the counter the first had already advanced.
        self._seed_lock = asyncio.Lock()

    def _established(self, thread_id: str) -> bool:
        """Whether this process has already settled how this run is numbered."""
        return thread_id in self._counters or thread_id in self._unnumbered

    async def seed(self, thread_id: str) -> None:
        """Establish *thread_id*'s counter if this process has not yet done so.

        Idempotent and cheap after the first call: a run already seeded, or
        already known unseedable, costs one dictionary lookup and no database
        round trip, and never takes the lock.
        """
        if self._established(thread_id):
            return
        async with self._seed_lock:
            # Re-asked under the lock, because the answer can have changed
            # while this call waited for it.
            if self._established(thread_id):
                return
            try:
                retained = await self._seeds.high_water_mark(thread_id)
                durable = (
                    retained
                    if retained is not None
                    else (await self._seeds.settled_sequence(thread_id) or 0)
                )
            except Exception:
                self._unnumbered.add(thread_id)
                logger.warning(
                    "Could not establish the event sequence of run %s; its stream "
                    "will carry no resumable id for the life of this process",
                    thread_id,
                    exc_info=True,
                    extra={"thread_id": thread_id, "action": "run_sequence_unseedable"},
                )
                return
            self._counters[thread_id] = max(durable, self._issued.pop(thread_id, 0))

    def allocate(self, thread_id: str) -> int | None:
        """Return *thread_id*'s next number, or ``None`` when it has none.

        ``None`` means the run was never seeded on this gateway, or could not
        be. Both answers are the same to a caller: emit the frame, write no
        durable row, and offer no id.
        """
        current = self._counters.get(thread_id)
        if current is None:
            return None
        advanced = current + 1
        self._counters[thread_id] = advanced
        return advanced

    def is_numbered(self, thread_id: str) -> bool:
        """Whether this gateway's own numbers are what this run's frames carry.

        True for a run whose counter has been forgotten while its floor is
        still remembered. Forgetting bounds memory; it does not retract the
        numbers already stamped on frames still crossing the fan-out, nor the
        rows those frames became. Read as "holds a live counter", it cost a
        settled run's terminal its id: the purge that follows a settlement
        runs in the same step as the release of that terminal, before any
        subscriber has drained it.

        False while a run is known unseedable, even if a floor from before
        survives. Its frames carry the producing worker's own counter, which
        restarts with that process and must never be offered back as a cursor.
        """
        if thread_id in self._unnumbered:
            return False
        return thread_id in self._counters or thread_id in self._issued

    def forget(self, thread_id: str) -> None:
        """Drop *thread_id*'s in-memory numbering state.

        Called when a run's aggregator state is purged, which the terminal
        relay does before the batch holding that terminal has been flushed.
        The counter goes, the floor it reached stays: a later frame for the
        same run reseeds from the durable mark OR that floor, whichever is
        higher, so forgetting costs a read and can never cost a number.
        """
        issued = self._counters.pop(thread_id, None)
        self._unnumbered.discard(thread_id)
        if issued is None:
            return
        self._issued[thread_id] = max(issued, self._issued.get(thread_id, 0))
        self._issued.move_to_end(thread_id)
        while len(self._issued) > _REMEMBERED_FLOORS:
            self._issued.popitem(last=False)


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
        # Node metadata cache: thread_id -> node_name -> safe descriptor fields.
        self._node_metadata: dict[str, dict[str, dict[str, str]]] = {}
        # Events this client lost to backpressure and has not been told about.
        # Held here rather than pushed into the queue because the queue being
        # full is the very condition being reported: a notice enqueued then
        # would evict another event to make room for the news that an event was
        # evicted. The consumer collects it on its way past instead.
        self._dropped: dict[str, int] = defaultdict(int)
        self._telemetry = telemetry
        # Unbound by default. The worker's aggregator and a gateway serving no
        # replay never bind one, and then nothing below numbers anything.
        self._allocator: RunSequenceAllocator | None = None
        self._allocation_sink: AllocationSink | None = None

    # ------------------------------------------------------------------
    # Sequence allocation
    # ------------------------------------------------------------------

    def bind_sequence_allocator(
        self,
        allocator: RunSequenceAllocator | None,
        *,
        sink: AllocationSink | None = None,
    ) -> None:
        """Seat the authority that numbers outgoing frames, and its recorder."""
        self._allocator = allocator
        self._allocation_sink = sink

    @property
    def sequence_allocator(self) -> RunSequenceAllocator | None:
        """The seated numbering authority, or ``None`` where none is bound."""
        return self._allocator

    async def prepare_run(self, thread_id: str) -> None:
        """Establish *thread_id*'s numbering before its frames are enqueued.

        :meth:`enqueue_payload` is synchronous and cannot read a database, so
        the ingest path that owns the await calls this first. A run reaching
        the chokepoint unprepared is not numbered, which costs it its id and
        never costs it a frame.
        """
        if self._allocator is not None:
            await self._allocator.seed(thread_id)

    async def shutdown_allocation_sink(self) -> None:
        """Close the seated recorder, so a shutdown does not strand its ring."""
        sink, self._allocation_sink = self._allocation_sink, None
        if sink is None:
            return
        try:
            await sink.aclose()
        except Exception:
            logger.warning("Replay recorder did not close cleanly", exc_info=True)

    def discard_run_replay(self, thread_id: str) -> None:
        """Drop what the recorder holds for a run whose durable home is gone.

        Deliberately NOT part of :meth:`remove_thread`. A terminal purges a
        run's aggregator state while the batch carrying that terminal is
        still unflushed, so dropping the recorder's hold there would discard
        the very frames a reconnect comes back for. Only a DELETED run has no
        durable home left: the rows its held frames would become reference a
        thread that is gone, so no flush can ever place them.
        """
        if self._allocation_sink is not None:
            self._allocation_sink.discard(thread_id)

    def _retainable(self, frame: object) -> bool:
        """Whether a number spent on *frame* would leave a retained row behind.

        A run's sequence space has to stay contiguous: the replay reader
        serves the longest consecutive tail of what it finds, so one frame
        numbered and never retained costs a resume every older frame in the
        window. Asking the recorder first is what stops that, and a process
        with no recorder retains nothing anyway, so nothing there is at stake.
        """
        sink = self._allocation_sink
        return sink is None or sink.retains(frame)

    def _allocate(self, thread_id: str) -> SequenceAllocation | None:
        """Take this run's next number, or ``None`` where it has none."""
        if self._allocator is None:
            return None
        sequence = self._allocator.allocate(thread_id)
        if sequence is None:
            return None
        return SequenceAllocation(
            thread_id=thread_id, sequence=sequence, allocated_at=datetime.now(UTC)
        )

    def _record(self, allocation: SequenceAllocation, frame: object) -> None:
        """Hand the recorder the frame EXACTLY as subscribers will receive it.

        Called after the number is stamped and before any fan-out, which is
        both halves of the ordering this seam exists to keep. Stamping first
        is what stops the retained row carrying the producer's own number
        while the live frame carries the gateway's - the two would then
        disagree about the identity a resume is taken against. Recording
        first is what keeps the fan-out free of a database round trip; the
        recorder does in-memory work only, and a recorder that fails costs
        the run its replay, never its stream.
        """
        if self._allocation_sink is None:
            return
        try:
            self._allocation_sink.record(allocation, frame)
        except Exception:
            logger.warning(
                "Could not record event %d of run %s for replay",
                allocation.sequence,
                allocation.thread_id,
                exc_info=True,
                extra={
                    "thread_id": allocation.thread_id,
                    "action": "run_event_record_failed",
                },
            )

    # ------------------------------------------------------------------
    # Subscriber management
    # ------------------------------------------------------------------

    def add_subscriber(self, client_id: str) -> asyncio.Queue[SequencedEvent]:
        """Register a new subscriber and return its bounded event queue.

        Refuses once the registry is at its global capacity. Each subscriber owns
        a bounded queue and a delivery path, so the count is a resource an
        authenticated caller can demand without limit unless something says no.

        Enforced here, at the domain seam, rather than only at the route that
        happens to have asked first. The registry is shared: the SSE stream route
        and the event WebSocket both register against it, so a bound checked in
        one route is not a bound - the other path admits subscribers the check
        never sees. The route keeps its own cheap pre-check because refusing
        before a database round trip is worth doing; this is where the limit is
        actually true.

        Re-registering an existing ``client_id`` replaces that client's queue
        rather than growing the registry, so it is never refused - the same
        reasoning as the idempotent re-subscribe in :meth:`subscribe`.
        """
        limit = domain_config.max_stream_connections
        if (
            limit > 0
            and client_id not in self._subscribers
            and len(self._subscribers) >= limit
        ):
            self._telemetry.increment_counter(
                "aggregator.subscribers_refused", 1, **{"client_id": client_id}
            )
            logger.warning(
                "Refused subscriber %s: %d registered meets cap %d",
                client_id,
                len(self._subscribers),
                limit,
                extra={
                    "client_id": client_id,
                    "action": "subscriber_refused",
                    "registered": len(self._subscribers),
                    "limit": limit,
                },
            )
            raise EventAggregatorError(
                f"Gateway holds {len(self._subscribers)} stream subscribers, "
                f"meeting the global limit of {limit}"
            )
        queue: asyncio.Queue[SequencedEvent] = asyncio.Queue(
            maxsize=domain_config.event_queue_maxsize
        )
        self._subscribers[client_id] = queue
        self._subscriptions[client_id] = set()
        self._dropped.pop(client_id, None)
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
        self._dropped.pop(client_id, None)

    def take_dropped_count(self, client_id: str) -> int:
        """Return and clear the events *client_id* lost to backpressure.

        Read by the client's own delivery loop on its way past, so a burst of
        drops becomes one resynchronization notice rather than one per event,
        and a client that is keeping up pays nothing.
        """
        return self._dropped.pop(client_id, 0)

    def subscribe(self, client_id: str, thread_ids: list[str]) -> None:
        """Subscribe a client to one or more thread event streams.

        Refuses the whole request once it would carry the client past its
        subscription cap. Every subscription is matched against every broadcast
        event, so cardinality here is fan-out work an authenticated caller can
        demand of the gateway - the connection limit bounds how many clients
        exist, not how much each one costs. Rejecting outright rather than
        truncating keeps the client's view honest: a partially applied
        subscription would silently drop threads it believes it is watching.
        """
        if client_id not in self._subscribers:
            raise EventAggregatorError(f"Client {client_id} is not registered")
        current = self._subscriptions[client_id]
        limit = domain_config.max_subscriptions_per_client
        # Union first: re-subscribing to threads already held must stay a no-op
        # rather than counting twice against the cap.
        prospective = current | set(thread_ids)
        if limit > 0 and len(prospective) > limit:
            self._telemetry.increment_counter(
                "aggregator.subscriptions_refused", 1, **{"client_id": client_id}
            )
            logger.warning(
                "Refused subscription for %s: %d held + %d requested exceeds cap %d",
                client_id,
                len(current),
                len(thread_ids),
                limit,
                extra={
                    "client_id": client_id,
                    "action": "subscription_refused",
                    "held": len(current),
                    "requested": len(thread_ids),
                    "limit": limit,
                },
            )
            raise EventAggregatorError(
                f"Client {client_id} would hold {len(prospective)} subscriptions, "
                f"exceeding the per-client limit of {limit}"
            )
        self._subscriptions[client_id] = prospective

    def unsubscribe(self, client_id: str, thread_ids: list[str]) -> None:
        """Unsubscribe a client from one or more thread event streams."""
        if client_id in self._subscriptions:
            self._subscriptions[client_id].difference_update(thread_ids)

    def remove_thread(self, thread_id: str) -> None:
        """Remove ``thread_id`` from every active subscriber subscription set."""
        for client_id in list(self._subscriptions):
            self._subscriptions[client_id].discard(thread_id)
        self._node_metadata.pop(thread_id, None)
        if self._allocator is not None:
            self._allocator.forget(thread_id)

    def remove_node_metadata(self, thread_id: str) -> None:
        """Drop the live graph descriptors for one terminal worker thread."""
        self._node_metadata.pop(thread_id, None)

    def add_broadcast_hook(
        self, hook: Callable[[SequencedEvent], Awaitable[None]]
    ) -> None:
        """Register a hook called on every broadcast (worker bridge relay)."""
        self._broadcast_hooks.append(hook)

    def subscriber_count(self) -> int:
        """Return the number of currently registered subscribers.

        Each subscriber owns a bounded queue and a delivery path, so this count
        is the resource the gateway's global stream-connection limit bounds.
        """
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
        """Enqueue a pre-serialized payload for all subscribers of ``thread_id``.

        Numbers the frame first, where a number is available AND the frame is
        one the recorder will keep, and stamps that number over the body's own
        ``sequence``. The worker's counter orders a run's events within one
        worker lifetime and restarts with the process; the number stamped here
        is the run's identity and survives a restart of either process, so the
        relay overwrites rather than forwards.

        A payload that is not a mapping cannot carry the stamp and is not
        retained either, so it takes no number at all rather than leaving a
        hole in the run's sequence space.
        """
        delivered = payload
        if self._retainable(payload) and isinstance(payload, Mapping):
            allocation = self._allocate(thread_id)
            if allocation is not None:
                stamped: dict[str, object] = {
                    **cast("Mapping[str, object]", payload),
                    "sequence": allocation.sequence,
                }
                self._record(allocation, stamped)
                delivered = stamped
        for client_id, queue in list(self._subscribers.items()):
            client_subs = self._subscriptions.get(client_id, set())
            if thread_id not in client_subs:
                continue
            outcome = deliver_bounded(queue, delivered, client_id=client_id)
            if outcome.dropped:
                self._dropped[client_id] += outcome.dropped

    # ------------------------------------------------------------------
    # Graph registration
    # ------------------------------------------------------------------

    def register_graph(self, thread_id: str, graph: StreamableGraph) -> None:
        """Cache node metadata from a compiled LangGraph graph."""
        self._node_metadata[thread_id] = node_metadata_from_graph(graph)
        logger.debug(
            "register_graph: cached metadata for %d nodes on %s",
            len(self._node_metadata[thread_id]),
            thread_id,
        )

    def get_node_summaries(self, thread_id: str) -> list[dict[str, str]]:
        """Return a list of node metadata dicts for the team status endpoint."""
        return [
            {"node_name": name, "agent_id": name, **meta}
            for name, meta in self._node_metadata.get(thread_id, {}).items()
        ]

    def get_node_metadata(self, thread_id: str) -> dict[str, dict[str, str]]:
        """Return the raw node metadata dict (used by emitters)."""
        return self._node_metadata.get(thread_id, {})

    def set_node_metadata(
        self, thread_id: str, metadata: dict[str, dict[str, str]]
    ) -> None:
        """Replace node metadata (used by sync_worker_event)."""
        self._node_metadata[thread_id] = metadata

    # ------------------------------------------------------------------
    # Broadcasting
    # ------------------------------------------------------------------

    async def broadcast(self, sequenced: SequencedEvent) -> None:
        """Fan out a sequenced domain event to all interested subscribers.

        An in-process domain event takes its number from the same counter a
        relayed worker payload does, so two producers on one run cannot both
        claim one number. The delivered wrapper is a new one rather than the
        caller's: the hooks below are the worker's relay, which must keep
        forwarding its own producer-side ordering untouched.

        Uses a drop-oldest strategy: if a subscriber queue is full,
        the oldest buffered event is discarded before inserting the new
        one.  This keeps the aggregator non-blocking while bounding
        per-client memory (research §1.5).
        """
        thread_id = getattr(sequenced.event, "thread_id", None)
        event_type = type(sequenced.event).__name__

        delivered_event = sequenced
        if thread_id is not None:
            await self.prepare_run(thread_id)
            # Same rule as the relay path: a frame the recorder would decline
            # takes no number, so the run's sequence space stays contiguous.
            allocation = (
                self._allocate(thread_id) if self._retainable(sequenced) else None
            )
            if allocation is not None:
                delivered_event = SequencedEvent(
                    event=sequenced.event, sequence=allocation.sequence
                )
                self._record(allocation, delivered_event)

        with self._telemetry.start_span(
            "aggregator.broadcast",
            **{"event.type": str(event_type), "thread_id": thread_id or ""},
        ):
            delivered = 0
            for client_id, queue in list(self._subscribers.items()):
                client_subs = self._subscriptions.get(client_id, set())
                if not (thread_id is None or thread_id in client_subs):
                    continue
                outcome = deliver_bounded(queue, delivered_event, client_id=client_id)
                if outcome.dropped:
                    self._dropped[client_id] += outcome.dropped
                if outcome.delivered:
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
        self._dropped.clear()
