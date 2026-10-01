"""The bounded ring behind the fan-out, and the batch that drains it.

The ordering this module exists to preserve is: allocate, ring, fan out,
flush. A frame reaches its subscribers before its row is durable, and that is
deliberate - the stream's terminal bound is one heartbeat and a database round
trip in front of the fan-out would be paid by every viewer on every frame.
What the ring buys is that the price of writing late is bounded: a resume
taken before a flush reads the ring, and a flush that fails leaves its records
exactly where a resume can still find them.

Two numbers here are tuning, not contract. The ring's capacity and the flush
cadence may move; the ordering above may not.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections import OrderedDict, deque
from collections.abc import Mapping
from typing import TYPE_CHECKING

from ..database.run_event_repository import RunEventRecord

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from ..database.run_event_repository import RunEventStore
    from .subscribers import SequenceAllocation

#: The three bounds below and the default projector are this writer's own
#: tuning, reachable as keyword defaults rather than as a published surface;
#: naming them here would advertise knobs no caller turns.
__all__ = ["FrameProjector", "RunEventWriter"]

logger = logging.getLogger(__name__)

#: How long an allocation may wait for a batch that never comes.
#:
#: The relay path flushes each ingested batch itself, so this cadence only ever
#: covers frames produced outside one - and bounds how long a resume taken
#: right now would have to read the ring instead of the table.
DEFAULT_FLUSH_INTERVAL_SECONDS = 0.05

#: Allocations held per run between flushes, and the window a resume can read
#: before the table has them.
#:
#: Sized against the cadence above rather than against the retention window:
#: at 50 ms, filling this ring needs a sustained ten thousand frames a second
#: on one run, an order of magnitude past anything this service produces.
DEFAULT_RING_CAPACITY = 512

#: Runs whose rings this writer keeps at once.
#:
#: The second bound, and the one that stops a long-lived gateway accumulating
#: one ring per run it has ever served. A run evicted here has not produced a
#: frame while this many others did, so its own frames are long written; a
#: resume for it reads the table, which is where its window lives anyway.
DEFAULT_TRACKED_RUNS = 64

#: Projects whatever crossed the fan-out chokepoint into the frame body to
#: store, or ``None`` for a frame this writer should not retain. Injected
#: because the wire projection of an in-process domain event belongs to the API
#: boundary, and this package sits below it.
type FrameProjector = Callable[[object], Mapping[str, object] | None]


def projected_mappings_only(frame: object) -> Mapping[str, object] | None:
    """Retain a frame that already IS a projected mapping, and nothing else."""
    return frame if isinstance(frame, Mapping) else None


class RunEventWriter:
    """Hold each allocation in a per-run ring and write it behind the fan-out."""

    def __init__(
        self,
        store: RunEventStore,
        *,
        window: int,
        project: FrameProjector = projected_mappings_only,
        ring_capacity: int = DEFAULT_RING_CAPACITY,
        tracked_runs: int = DEFAULT_TRACKED_RUNS,
        flush_interval_seconds: float = DEFAULT_FLUSH_INTERVAL_SECONDS,
    ) -> None:
        self._store = store
        self._window = window
        self._project = project
        self._ring_capacity = ring_capacity
        self._tracked_runs = tracked_runs
        self._flush_interval = flush_interval_seconds
        self._rings: OrderedDict[str, deque[RunEventRecord]] = OrderedDict()
        # The highest sequence per run this writer has seen land in the table.
        # Everything above it in the ring is what the next flush offers, which
        # is why a failed flush needs no separate retry queue: the records are
        # still in the ring and still above this mark.
        self._flushed_through: dict[str, int] = {}
        self._flush_lock = asyncio.Lock()
        self._ticker: asyncio.Task[None] | None = None
        self._closed = False

    # ------------------------------------------------------------------
    # In front of the fan-out: in-memory only
    # ------------------------------------------------------------------

    def record(self, allocation: SequenceAllocation, frame: object) -> None:
        """Hold one numbered frame for the next batch.

        Runs in front of the fan-out, so it does no I/O at all. A frame the
        projector declines is held by nothing and simply has no retained row.
        """
        if self._closed:
            return
        body = self._project(frame)
        if body is None:
            return
        ring = self._ring_for(allocation.thread_id)
        self._warn_on_unflushed_eviction(allocation.thread_id, ring)
        ring.append(
            RunEventRecord(
                thread_id=allocation.thread_id,
                sequence=allocation.sequence,
                event_type=str(body.get("type") or body.get("event_type") or ""),
                payload_json=json.dumps(body, separators=(",", ":")),
                created_at=allocation.allocated_at,
            )
        )
        self._ensure_ticker()

    def pending(self, thread_id: str) -> list[RunEventRecord]:
        """Return the run's ring, newest window first written or not.

        A resume taken between an allocation and its flush reads this after the
        table, and both may name the same sequence while a flush is in flight,
        so the reader unions by sequence rather than concatenating.
        """
        return list(self._rings.get(thread_id, ()))

    # ------------------------------------------------------------------
    # Behind the fan-out: the batch
    # ------------------------------------------------------------------

    async def flush(self) -> int:
        """Write every held allocation the table does not have, as one batch.

        Returns the number of records written. A failure is logged with its
        count and changes nothing else: the records stay in their rings, above
        the flushed mark, so the next flush offers them again and a resume
        taken in between still reads them.
        """
        async with self._flush_lock:
            batch = list(self._unflushed())
            if not batch:
                return 0
            try:
                await self._store.append(batch, window=self._window)
            except Exception:
                logger.warning(
                    "Could not write %d progress frame(s) to the replay log; "
                    "they remain in memory and replay is degraded to the ring",
                    len(batch),
                    exc_info=True,
                    extra={
                        "action": "run_event_flush_failed",
                        "pending": len(batch),
                    },
                )
                return 0
            for record in batch:
                self._flushed_through[record.thread_id] = max(
                    self._flushed_through.get(record.thread_id, 0), record.sequence
                )
            return len(batch)

    async def aclose(self) -> None:
        """Stop the cadence and make one last attempt to write what is held."""
        self._closed = True
        ticker, self._ticker = self._ticker, None
        if ticker is not None:
            ticker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await ticker
        self._closed = False
        try:
            await self.flush()
        finally:
            self._closed = True

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _ring_for(self, thread_id: str) -> deque[RunEventRecord]:
        """Return the run's ring, creating it and evicting the coldest run."""
        ring = self._rings.get(thread_id)
        if ring is not None:
            self._rings.move_to_end(thread_id)
            return ring
        ring = deque(maxlen=self._ring_capacity)
        self._rings[thread_id] = ring
        while len(self._rings) > self._tracked_runs:
            evicted, dropped = self._rings.popitem(last=False)
            mark = self._flushed_through.pop(evicted, 0)
            unwritten = sum(1 for record in dropped if record.sequence > mark)
            if unwritten:
                logger.warning(
                    "Evicting run %s from the replay ring with %d frame(s) "
                    "never written",
                    evicted,
                    unwritten,
                    extra={
                        "thread_id": evicted,
                        "action": "run_event_ring_evicted",
                        "pending": unwritten,
                    },
                )
        return ring

    def _unflushed(self) -> Iterable[RunEventRecord]:
        for thread_id, ring in self._rings.items():
            mark = self._flushed_through.get(thread_id, 0)
            yield from (record for record in ring if record.sequence > mark)

    def _warn_on_unflushed_eviction(
        self, thread_id: str, ring: deque[RunEventRecord]
    ) -> None:
        """Report a frame the ring must drop before it was ever written.

        Only reachable when production outruns the flush cadence for a whole
        ring's worth of frames. The frame is still delivered; what is lost is
        its durable row, which a later resume reports as a gap rather than
        silently skipping.
        """
        if len(ring) < self._ring_capacity:
            return
        oldest = ring[0]
        if oldest.sequence <= self._flushed_through.get(thread_id, 0):
            return
        logger.warning(
            "Replay ring for run %s is full; dropping unwritten event %d",
            thread_id,
            oldest.sequence,
            extra={
                "thread_id": thread_id,
                "action": "run_event_ring_overflow",
                "sequence": oldest.sequence,
            },
        )

    def _ensure_ticker(self) -> None:
        if self._ticker is not None and not self._ticker.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # Recorded outside a loop: the caller owns the flush, and the
            # cadence starts the next time a frame is recorded on one.
            return
        self._ticker = loop.create_task(self._tick())

    async def _tick(self) -> None:
        while not self._closed:
            await asyncio.sleep(self._flush_interval)
            await self.flush()
