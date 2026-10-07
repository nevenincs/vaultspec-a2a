"""The gateway's relay: subscriber queues, frame numbering and the live-state mirror.

Every frame a viewer receives is a relayed worker payload, and every one enters
through :meth:`RelayHub.relay_payload`. That is the one place a run's
authoritative event sequence is allocated: numbering there - and only there -
gives each relayed frame exactly one number from one counter. A hub that binds
no allocator (a gateway serving no replay) numbers nothing, and its frames
carry the worker's own ordering untouched.
"""

import asyncio
import logging
from collections import OrderedDict, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, cast

from ..domain_config import domain_config
from ..graph.protocols import NullTelemetryHook, TelemetryHook
from ..thread.errors import StreamSubscriptionError
from ._run_state import RunLiveStateMirror
from .fanout import deliver_bounded
from .transformer import project_run_progress

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
    "RelayHub",
    "RunSequenceAllocator",
    "RunSequenceSeedSource",
    "SequenceAllocation",
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

    def issued_high_water(self, thread_id: str) -> int | None:
        """Return the highest number issued to *thread_id*, or ``None`` if unnumbered.

        The one reading of a run's numbering that is recorded as, and served
        as, the run's cursor. A live counter answers with its current value; a
        run forgotten while its floor is remembered answers with that floor,
        because forgetting bounds memory and retracts nothing already stamped.

        ``None`` is the answer for a run this process does not number: never
        seeded here, or unseedable. A caller must read it as "no value", never
        as zero - a counter this process did not keep says nothing about the
        frames another gateway lifetime numbered.
        """
        if thread_id in self._unnumbered:
            return None
        live = self._counters.get(thread_id)
        return live if live is not None else self._issued.get(thread_id)

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
        return self.issued_high_water(thread_id) is not None

    def forget(self, thread_id: str) -> None:
        """Drop *thread_id*'s in-memory numbering state.

        Called when a run's relay state is purged, which the terminal
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


class RelayHub:
    """The gateway's relay: subscriber queues, frame numbering, and the live mirror.

    A relayed worker payload is projected onto the positive progress catalog,
    numbered where a number is available, and fanned out to the run's
    subscribers; the same payload moves the mirror that run-status and team
    status read the run's live agents, tool calls and nodes from. The hub
    produces no event of its own.
    """

    def __init__(self, telemetry: TelemetryHook | None = None) -> None:
        # Subscriber queues: client_id -> bounded asyncio.Queue of relayed payloads.
        self._subscribers: dict[str, asyncio.Queue[object]] = {}
        # Which threads each client is subscribed to: client_id -> set of thread_ids
        self._subscriptions: dict[str, set[str]] = defaultdict(set)
        # Events this client lost to backpressure and has not been told about.
        # Held here rather than pushed into the queue because the queue being
        # full is the very condition being reported: a notice enqueued then
        # would evict another event to make room for the news that an event was
        # evicted. The consumer collects it on its way past instead.
        self._dropped: dict[str, int] = defaultdict(int)
        self._telemetry: TelemetryHook | NullTelemetryHook = (
            telemetry or NullTelemetryHook()
        )
        # Unbound by default. A gateway serving no replay never binds one, and
        # then nothing below numbers anything.
        self._allocator: RunSequenceAllocator | None = None
        self._allocation_sink: AllocationSink | None = None
        self._mirror = RunLiveStateMirror()

    @property
    def mirror(self) -> RunLiveStateMirror:
        """The live agent, tool-call and node state the relayed events rebuilt."""
        return self._mirror

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

    def issued_sequence(self, thread_id: str) -> int | None:
        """Return the highest frame number issued to *thread_id*, or ``None``.

        ``None`` covers a gateway serving no replay and a run left unnumbered,
        so a caller recording the answer records nothing for either.
        """
        allocator = self._allocator
        return None if allocator is None else allocator.issued_high_water(thread_id)

    async def prepare_run(self, thread_id: str) -> None:
        """Establish *thread_id*'s numbering before its frames are relayed.

        :meth:`relay_payload` is synchronous and cannot read a database, so
        the ingest path that owns the await calls this first. A run reaching
        the chokepoint unprepared is not numbered, which costs it its id and
        never costs it a frame.
        """
        if self._allocator is not None:
            await self._allocator.seed(thread_id)

    def discard_run_replay(self, thread_id: str) -> None:
        """Drop what the recorder holds for a run whose durable home is gone.

        Called by the delete path only, and deliberately NOT part of
        :meth:`clear_thread_state`. A terminal purges a run's relay state while
        the batch carrying that terminal is still unflushed, so dropping the
        recorder's hold there would discard the very frames a reconnect comes
        back for. Only a DELETED run has no durable home left: the rows its
        held frames would become reference a thread that is gone, so no flush
        can ever place them.
        """
        if self._allocation_sink is not None:
            self._allocation_sink.discard(thread_id)

    def _retainable(self, frame: object) -> bool:
        """Whether a number spent on *frame* would leave a retained row behind.

        A run's sequence space has to stay contiguous: the replay reader
        serves the longest consecutive tail of what it finds, so one frame
        numbered and never retained costs a resume every older frame in the
        window. Asking the recorder first is what stops that, and a hub with
        no recorder retains nothing anyway, so nothing there is at stake.
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

    def add_subscriber(self, client_id: str) -> asyncio.Queue[object]:
        """Register a new subscriber and return its bounded event queue.

        Refuses once the registry is at its global capacity. Each subscriber owns
        a bounded queue and a delivery path, so the count is a resource an
        authenticated caller can demand without limit unless something says no.

        Enforced here, at the domain seam, rather than only at the route that
        happens to have asked first. The route keeps its own cheap pre-check
        because refusing before a database round trip is worth doing; this is
        where the limit is actually true.

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
            raise StreamSubscriptionError(
                f"Gateway holds {len(self._subscribers)} stream subscribers, "
                f"meeting the global limit of {limit}"
            )
        queue: asyncio.Queue[object] = asyncio.Queue(
            maxsize=domain_config.event_queue_maxsize
        )
        self._subscribers[client_id] = queue
        self._subscriptions[client_id] = set()
        self._dropped.pop(client_id, None)
        return queue

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
        subscription cap. Every subscription is matched against every relayed
        frame, so cardinality here is fan-out work an authenticated caller can
        demand of the gateway - the connection limit bounds how many clients
        exist, not how much each one costs. Rejecting outright rather than
        truncating keeps the client's view honest: a partially applied
        subscription would silently drop threads it believes it is watching.
        """
        if client_id not in self._subscribers:
            raise StreamSubscriptionError(f"Client {client_id} is not registered")
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
            raise StreamSubscriptionError(
                f"Client {client_id} would hold {len(prospective)} subscriptions, "
                f"exceeding the per-client limit of {limit}"
            )
        self._subscriptions[client_id] = prospective

    def subscriber_count(self) -> int:
        """Return the number of currently registered subscribers.

        Each subscriber owns a bounded queue and a delivery path, so this count
        is the resource the gateway's global stream-connection limit bounds.
        """
        return len(self._subscribers)

    def get_active_thread_ids(self) -> list[str]:
        """Return all thread IDs that have at least one subscriber.

        Takes a snapshot of subscription values before iterating, so a
        subscriber added or removed concurrently cannot fail the read.
        """
        all_threads: set[str] = set()
        for threads in list(self._subscriptions.values()):
            all_threads.update(threads)
        return sorted(all_threads)

    # ------------------------------------------------------------------
    # Relay
    # ------------------------------------------------------------------

    def relay_payload(self, thread_id: str, payload: object) -> None:
        """Fan out one relayed worker payload to every subscriber of ``thread_id``.

        Worker run events enter the public progress edge here. Each is
        projected through the positive progress DTO before it reaches a
        subscriber queue, so prompts, document and artifact bodies, edit diffs,
        and raw provider payloads are dropped at the relay seam - a first
        enforcement the encode boundary independently repeats.

        The projected frame is then numbered, where a number is available AND
        the frame is one the recorder will keep, and that number is stamped
        over the body's own ``sequence``. The worker's counter orders a run's
        events within one worker lifetime and restarts with the process; the
        number stamped here is the run's identity and survives a restart of
        either process, so the relay overwrites rather than forwards. A payload
        that is not a mapping cannot carry the stamp and is not retained
        either, so it takes no number at all rather than leaving a hole in the
        run's sequence space.

        Call :meth:`prepare_run` for the run first: this path is synchronous and
        cannot establish a number it has never read.
        """
        projected = project_run_progress(payload)
        delivered: object = projected
        if self._retainable(projected) and isinstance(projected, Mapping):
            allocation = self._allocate(thread_id)
            if allocation is not None:
                stamped: dict[str, object] = {
                    **cast("Mapping[str, object]", projected),
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

    def sync_worker_event(self, thread_id: str, payload: Mapping[str, Any]) -> None:
        """Mirror one relayed worker event into the run's live state."""
        self._mirror.sync_worker_event(thread_id, payload)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def clear_thread_state(self, thread_id: str) -> None:
        """Purge every in-memory trace of ``thread_id`` this hub holds.

        The run leaves every subscription set, its mirrored state goes, and the
        allocator forgets its live counter while keeping the floor it reached.
        """
        for client_id in list(self._subscriptions):
            self._subscriptions[client_id].discard(thread_id)
        self._mirror.clear_thread_state(thread_id)
        if self._allocator is not None:
            self._allocator.forget(thread_id)

    async def shutdown(self) -> None:
        """Close the replay recorder, then drop every subscriber and mirrored run.

        The recorder is closed first, so a shutdown does not strand its ring.
        """
        sink, self._allocation_sink = self._allocation_sink, None
        if sink is not None:
            try:
                await sink.aclose()
            except Exception:
                logger.warning("Replay recorder did not close cleanly", exc_info=True)
        self._subscribers.clear()
        self._subscriptions.clear()
        self._dropped.clear()
        self._mirror.clear()
