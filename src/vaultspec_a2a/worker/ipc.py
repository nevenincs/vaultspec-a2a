"""Worker-to-control-surface IPC bridge.

Uses HTTP POST, through httpx, to push events and heartbeats to the gateway.

Events are batched for up to ``ipc_flush_interval_seconds`` seconds before being
sent as a single HTTP POST to ``/internal/events/batch``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import anyio
import httpx
from fastapi.encoders import jsonable_encoder

from ..control.config import settings
from ..domain_config import domain_config
from ..graph.enums import ServerEventType
from ..ipc.schemas import WorkerEventBatch, WorkerEventEnvelope
from ..streaming.fanout import is_protected_payload, pop_oldest_droppable
from ..telemetry import trace_headers
from ..thread.snapshots import wire_event_type
from ..utils import bearer_header

__all__ = ["WorkerBridge", "event_client_timeout"]

logger = logging.getLogger(__name__)

# Closing an HTTP client is independent cleanup from event delivery.  Keep a
# small allowance for that cleanup even when the shared delivery deadline has
# already elapsed, while still preventing an unbounded transport teardown.
_CLIENT_CLOSE_ALLOWANCE_SECONDS = 0.1

_CONNECT_TIMEOUT_SECONDS = 5.0

# What the gateway needs on top of its bounded checkpoint read to answer a post
# carrying a terminal: the durable write that precedes the read, and the
# loopback round trip around both.
_TERMINAL_CONFIRMATION_ALLOWANCE_SECONDS = 5.0

# The JSON envelope every batch body is wrapped in, measured once so a batch's
# size can be accumulated event by event instead of re-serialized per candidate.
_BATCH_ENVELOPE_BYTES = len(b'{"events":[]}')

_BATCH_CONTENT_TYPE = "application/json"


@dataclass(slots=True)
class _BatchState:
    """The buffered events and everything that governs draining them.

    The lock and the closing flag belong with the buffer they guard. One flush
    at a time: the deferred cadence flush and the immediate flush a terminal
    event forces used to be able to run together, each taking a slice of the
    same buffer, so the gateway received two overlapping posts whose ordering
    nothing established and a failure in one re-queued events the other had
    already sent. ``closing`` is set once shutdown begins, so a failed final
    flush cannot schedule a redrive onto a client about to close under it.
    """

    events: list[WorkerEventEnvelope] = field(default_factory=list)
    flush_task: asyncio.Task[None] | None = None
    flush_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    closing: bool = False


def event_client_timeout() -> httpx.Timeout:
    """Return the request budget the worker's event client gives the gateway.

    The gateway confirms the terminal an event post carries before it answers:
    a durable write, then a checkpoint read the operator's own
    ``aget_state`` budget bounds. A client that gave up at that same bound
    would abandon a confirmation still in progress and re-post a terminal the
    gateway is in the middle of accepting, so the budget is read off that
    bound rather than restated as a second number beside it.
    """
    return httpx.Timeout(
        domain_config.aget_state_timeout_seconds
        + _TERMINAL_CONFIRMATION_ALLOWANCE_SECONDS,
        connect=_CONNECT_TIMEOUT_SECONDS,
    )


def _entry_event_type(entry: WorkerEventEnvelope) -> str:
    """Return the wire event type of one buffered entry, or an empty string."""
    return wire_event_type(entry.payload)


def _is_protected_entry(entry: WorkerEventEnvelope) -> bool:
    """Report whether an entry states an outcome that nothing later restates."""
    return is_protected_payload(entry.payload)


def _encoded_batch(batch: list[WorkerEventEnvelope]) -> bytes:
    """Serialize one batch into exactly the bytes that will be posted.

    The body is built here rather than handed to the HTTP client as an object,
    so the size the splitter measured and the ``Content-Length`` the gateway
    checks are the same number. Measuring one serialization and sending another
    is how a batch sized to fit still arrives over the limit.
    """
    return WorkerEventBatch(events=batch).model_dump_json().encode("utf-8")


def _split_into_deliverable_batches(
    events: list[WorkerEventEnvelope], *, limit: int
) -> tuple[list[list[WorkerEventEnvelope]], list[WorkerEventEnvelope]]:
    """Split *events* into batches under *limit* bytes, separating the impossible.

    Returns the deliverable batches in order, then the individual events that
    exceed the limit on their own. The whole buffer used to be posted as one
    body, so a backlog built during a gateway outage was refused for being too
    large and re-queued unchanged - a refusal the worker then repeated forever.
    An event too large alone is the one case retrying cannot fix, so it is
    separated rather than made to block everything behind it.
    """
    batches: list[list[WorkerEventEnvelope]] = []
    oversized: list[WorkerEventEnvelope] = []
    current: list[WorkerEventEnvelope] = []
    size = _BATCH_ENVELOPE_BYTES
    for event in events:
        # One comma per event after the first.
        encoded = len(_encoded_batch([event])) - _BATCH_ENVELOPE_BYTES + 1
        if encoded + _BATCH_ENVELOPE_BYTES > limit:
            oversized.append(event)
            continue
        if current and size + encoded > limit:
            batches.append(current)
            current = []
            size = _BATCH_ENVELOPE_BYTES
        current.append(event)
        size += encoded
    if current:
        batches.append(current)
    return batches, oversized


class WorkerBridge:
    """Pushes events and heartbeats to the gateway via HTTP.

    The bridge maintains an ``httpx.AsyncClient`` pointed at the control
    surface's ``/internal/`` endpoints.  It tracks which thread IDs are
    actively being processed so the heartbeat payload can report them.

    Events are accumulated in a buffer and flushed as a batch every
    ``ipc_flush_interval_seconds`` seconds to reduce HTTP overhead.

    Parameters
    ----------
    api_url:
        Base URL of the gateway (e.g. ``http://localhost:18000``).
    worker_id:
        Unique identifier for this worker instance (hex string).
    """

    def __init__(
        self,
        api_url: str,
        worker_id: str,
        internal_token: str | None = None,
    ) -> None:
        self._api_url = api_url.rstrip("/")
        self._worker_id = worker_id
        # Attach bearer token to all internal IPC requests if provided.
        self._client = httpx.AsyncClient(
            base_url=self._api_url,
            timeout=event_client_timeout(),
            headers=bearer_header(internal_token) if internal_token else {},
        )
        self._active_threads: set[str] = set()
        self._start_time = time.monotonic()  # track uptime

        # Event batching state
        self._batch = _BatchState()

        # Consecutive heartbeat failure tracking for escalating logs.
        self._consecutive_hb_failures: int = 0

    @property
    def _event_buffer(self) -> list[WorkerEventEnvelope]:
        return self._batch.events

    @property
    def _flush_task(self) -> asyncio.Task[None] | None:
        return self._batch.flush_task

    @_flush_task.setter
    def _flush_task(self, task: asyncio.Task[None] | None) -> None:
        self._batch.flush_task = task

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self, *, deadline: float | None = None) -> bool:
        """Flush and close within *deadline*, returning whether every event relayed.

        The deadline is an absolute event-loop timestamp shared with the worker's
        other shutdown phases.  An unreachable gateway therefore cannot spend a
        fresh client timeout on every retry or keep the worker alive after its
        owner has moved to forced process-tree cleanup.  Client transport close
        retains a small independent allowance when delivery has consumed the
        shared deadline.
        """
        self._batch.closing = True
        pending = self._batch.flush_task
        pending_joined = True
        if pending is not None and not pending.done():
            pending.cancel()
            remaining = self._remaining(deadline)
            if remaining is None:
                await asyncio.gather(pending, return_exceptions=True)
            elif remaining > 0:
                done, _ = await asyncio.wait({pending}, timeout=remaining)
                pending_joined = pending in done
            else:
                pending_joined = False
        self._batch.flush_task = None

        flush_deadline = deadline
        if deadline is not None:
            flush_deadline = max(
                asyncio.get_running_loop().time(),
                deadline - _CLIENT_CLOSE_ALLOWANCE_SECONDS,
            )
        delivered = pending_joined and await self.flush_events(deadline=flush_deadline)
        remaining = self._remaining(deadline)
        close_budget = _CLIENT_CLOSE_ALLOWANCE_SECONDS
        if remaining is not None:
            close_budget = max(remaining, close_budget)
        try:
            async with asyncio.timeout(close_budget):
                await self._client.aclose()
        except TimeoutError:
            logger.error(
                "Worker bridge client close exceeded its bounded allowance",
                extra={
                    "worker_id": self._worker_id,
                    "action": "bridge_close_timeout",
                },
            )
            delivered = False
        return delivered

    @staticmethod
    def _redrive_delay_seconds() -> float:
        """Return the wait before retrying a batch that exhausted its attempts."""
        return settings.ipc_retry_backoff_base_seconds * (
            2**settings.ipc_max_flush_retries
        )

    @staticmethod
    def _remaining(deadline: float | None) -> float | None:
        if deadline is None:
            return None
        return max(deadline - asyncio.get_running_loop().time(), 0.0)

    async def probe_health(self) -> httpx.Response:
        """Issue a startup reachability probe against the gateway's health route."""
        return await self._client.get("/health")

    # ------------------------------------------------------------------
    # Thread tracking
    # ------------------------------------------------------------------

    def track_thread(self, thread_id: str) -> None:
        """Mark *thread_id* as actively executing on this worker."""
        self._active_threads.add(thread_id)

    def untrack_thread(self, thread_id: str) -> None:
        """Remove *thread_id* from the active set."""
        self._active_threads.discard(thread_id)

    @property
    def active_threads(self) -> frozenset[str]:
        """Snapshot of currently tracked thread IDs."""
        return frozenset(self._active_threads)

    # ------------------------------------------------------------------
    # Event relay (batched)
    # ------------------------------------------------------------------

    async def send_event(self, thread_id: str, payload: dict[str, Any]) -> None:
        """Buffer an event for batched relay to the gateway.

        Events are accumulated and flushed as a single HTTP POST after
        ``ipc_flush_interval_seconds`` seconds of inactivity or when ``flush_events``
        is called explicitly.
        """
        # Cap buffer to prevent unbounded memory growth.
        if len(self._batch.events) >= settings.ipc_max_event_buffer:
            self._evict_one_buffered_event(thread_id)

        self._batch.events.append(
            WorkerEventEnvelope(
                thread_id=thread_id,
                payload=jsonable_encoder(payload),
                ts=time.monotonic(),
            )
        )
        self._schedule_flush(settings.ipc_flush_interval_seconds)

    def _evict_one_buffered_event(self, thread_id: str) -> None:
        """Free one buffer slot, taking the oldest event that is not an outcome.

        Drop-oldest used to take the head whatever it was, so a run's terminal
        could be evicted by the very flood of progress that preceded it - and a
        lost terminal leaves the gateway watching a run that never ends. The bound
        still holds absolutely: when every buffered event is an outcome the oldest
        one yields, because an unbounded buffer is the failure this cap exists to
        prevent.
        """
        events = self._batch.events
        dropped = pop_oldest_droppable(events, _is_protected_entry)
        logger.warning(
            "Event buffer full (%d events), dropping oldest droppable event",
            settings.ipc_max_event_buffer,
            extra={
                "worker_id": self._worker_id,
                "thread_id": thread_id,
                "action": "buffer_drop_oldest",
                "dropped_event_type": _entry_event_type(dropped),
                "dropped_outcome_event": _is_protected_entry(dropped),
                "event_buffer_size": len(events),
                "event_buffer_limit": settings.ipc_max_event_buffer,
            },
        )

    def _schedule_flush(self, delay: float) -> None:
        """Ensure exactly one pending flush, due in at most *delay* seconds.

        The flush task asking for a flush is finishing, not pending: a batch it
        failed to deliver is re-queued from inside it, and treating it as the
        pending flush would leave that backlog waiting for an event a finished
        run never sends.
        """
        if self._batch.closing:
            return
        pending = self._batch.flush_task
        if pending is None or pending.done() or pending is asyncio.current_task():
            self._batch.flush_task = asyncio.create_task(self._deferred_flush(delay))

    async def _deferred_flush(self, delay: float | None = None) -> None:
        """Wait for the flush interval then send accumulated events."""
        await asyncio.sleep(
            settings.ipc_flush_interval_seconds if delay is None else delay
        )
        await self.flush_events()

    async def _post_event_batch(
        self,
        batch: list[WorkerEventEnvelope],
        *,
        attempt: int,
        request_timeout: httpx.Timeout | float | None,
    ) -> bool:
        headers = trace_headers()
        headers["content-type"] = _BATCH_CONTENT_TYPE
        try:
            resp = await self._client.post(
                "/internal/events/batch",
                content=_encoded_batch(batch),
                headers=headers,
                timeout=request_timeout,
            )
            if resp.status_code == 200:
                return True
            logger.warning(
                "Batch event relay failed (HTTP %d), attempt %d/%d",
                resp.status_code,
                attempt + 1,
                settings.ipc_max_flush_retries,
                extra={
                    "worker_id": self._worker_id,
                    "action": "flush_events",
                    "batch_size": len(batch),
                    "flush_attempt": attempt + 1,
                    "flush_attempt_limit": settings.ipc_max_flush_retries,
                    "http_status_code": resp.status_code,
                },
            )
        except httpx.HTTPError:
            logger.warning(
                "Failed to send %d events (attempt %d/%d)",
                len(batch),
                attempt + 1,
                settings.ipc_max_flush_retries,
                extra={
                    "worker_id": self._worker_id,
                    "action": "flush_events",
                    "batch_size": len(batch),
                    "flush_attempt": attempt + 1,
                    "flush_attempt_limit": settings.ipc_max_flush_retries,
                },
                exc_info=True,
            )
        return False

    async def _send_batch_once(
        self,
        batch: list[WorkerEventEnvelope],
        *,
        attempt: int,
        remaining: float | None,
    ) -> bool:
        request_timeout: httpx.Timeout | float | None = (
            self._client.timeout if remaining is None else remaining
        )
        try:
            return await self._post_event_batch(
                batch, attempt=attempt, request_timeout=request_timeout
            )
        except asyncio.CancelledError:
            self._batch.events[0:0] = batch
            raise

    async def _wait_for_flush_retry(
        self,
        batch: list[WorkerEventEnvelope],
        *,
        attempt: int,
        deadline: float | None,
    ) -> bool:
        delay = settings.ipc_retry_backoff_base_seconds * (2**attempt)
        remaining = self._remaining(deadline)
        if remaining is not None:
            delay = min(delay, remaining)
        if delay <= 0:
            return False
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            self._batch.events[0:0] = batch
            raise
        return True

    async def flush_events(self, *, deadline: float | None = None) -> bool:
        """Send every buffered event, in batches the gateway will accept.

        Serialized: one flush runs at a time, so the cadence flush and the
        immediate flush a terminal forces queue behind each other instead of
        splitting one buffer between two overlapping posts.

        Each batch is retried up to ``ipc_max_flush_retries`` times with
        exponential backoff. Anything still undelivered is re-queued so it is not
        silently lost (subject to the buffer cap) and a redrive is scheduled, so a
        backlog drains on its own rather than waiting for a later event that a
        finished run will never produce.

        Failures are logged but never raised -- the worker must not crash because
        the gateway is temporarily unavailable.
        """
        async with self._batch.flush_lock:
            return await self._flush_locked(deadline=deadline)

    async def _flush_locked(self, *, deadline: float | None) -> bool:
        if not self._batch.events:
            return True

        pending = self._batch.events[:]
        self._batch.events.clear()
        batches, oversized = _split_into_deliverable_batches(
            pending, limit=settings.internal_max_event_batch_bytes
        )
        self._report_undeliverable_events(oversized)

        delivered = True
        for index, batch in enumerate(batches):
            if await self._deliver_batch(batch, deadline=deadline):
                continue
            # Everything after a batch that could not land stays buffered behind
            # it, so the gateway never receives a later event before an earlier one.
            undelivered = [event for rest in batches[index:] for event in rest]
            self._requeue_failed_batch(undelivered)
            delivered = False
            break
        return delivered and not oversized

    async def _deliver_batch(
        self, batch: list[WorkerEventEnvelope], *, deadline: float | None
    ) -> bool:
        """Post one size-bounded batch, retrying with backoff inside the deadline."""
        for attempt in range(settings.ipc_max_flush_retries):
            remaining = self._remaining(deadline)
            if remaining is not None and remaining <= 0:
                return False
            if await self._send_batch_once(batch, attempt=attempt, remaining=remaining):
                return True

            # Exponential backoff before retry.
            if attempt < settings.ipc_max_flush_retries - 1 and not (
                await self._wait_for_flush_retry(
                    batch, attempt=attempt, deadline=deadline
                )
            ):
                return False
        return False

    def _report_undeliverable_events(
        self, oversized: list[WorkerEventEnvelope]
    ) -> None:
        """Record events no batch can carry, rather than retrying them forever.

        An event larger than the whole batch limit cannot be delivered by any
        number of attempts, and keeping it buffered blocks every event behind it.
        Dropping it is a loss, so it is reported as one - with the event type and
        the run, which is what a reader needs to know what is missing.
        """
        for event in oversized:
            logger.error(
                "Event exceeds the gateway's batch limit and cannot be relayed",
                extra={
                    "worker_id": self._worker_id,
                    "thread_id": event.thread_id,
                    "action": "flush_events_undeliverable",
                    "dropped_event_type": _entry_event_type(event),
                    "dropped_outcome_event": _is_protected_entry(event),
                    "event_bytes": len(_encoded_batch([event])),
                    "batch_limit_bytes": settings.internal_max_event_batch_bytes,
                },
            )

    def _requeue_failed_batch(self, batch: list[WorkerEventEnvelope]) -> None:
        """Report exhausted delivery and preserve the buffered events that fit."""
        logger.error(
            "Event flush to gateway FAILED after %d attempts"
            " (gateway_url=%s, batch_size=%d) — permission and status"
            " events may be lost",
            settings.ipc_max_flush_retries,
            self._api_url,
            len(batch),
            extra={
                "worker_id": self._worker_id,
                "action": "flush_events_exhausted",
                "gateway_url": self._api_url,
                "batch_size": len(batch),
                "flush_attempt_limit": settings.ipc_max_flush_retries,
            },
        )

        # The failed batch goes back ahead of what arrived while it was in
        # flight, and the cap is then restored by the same eviction a full
        # buffer uses. Keeping the batch's head instead, as a plain slice does,
        # gave up its tail first - which is where a run's terminal sits.
        self._batch.events[:0] = batch
        overflow = len(self._batch.events) - settings.ipc_max_event_buffer
        dropped = [
            pop_oldest_droppable(self._batch.events, _is_protected_entry)
            for _ in range(max(overflow, 0))
        ]
        if self._batch.events:
            # A re-queued backlog used to sit until the next event arrived, which
            # for a run that has just ended is never. The redrive is delayed by a
            # full retry ladder rather than the flush cadence, so an unreachable
            # gateway is retried steadily instead of in a tight loop.
            self._schedule_flush(self._redrive_delay_seconds())
        if dropped:
            logger.error(
                "Dropped %d events after %d failed flush attempts",
                len(dropped),
                settings.ipc_max_flush_retries,
                extra={
                    "worker_id": self._worker_id,
                    "action": "flush_events_drop",
                    "dropped_events": len(dropped),
                    "dropped_outcome_events": sum(
                        _is_protected_entry(entry) for entry in dropped
                    ),
                    "flush_attempt_limit": settings.ipc_max_flush_retries,
                    "event_buffer_size": len(self._batch.events),
                },
            )

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    async def send_heartbeat(self) -> bool:
        """Send a single heartbeat POST to the gateway.

        Returns
        -------
        bool
            ``True`` if the heartbeat was accepted, ``False`` on any error.
        """
        try:
            resp = await self._client.post(
                "/internal/heartbeat",
                json={
                    "type": ServerEventType.HEARTBEAT,
                    "worker_id": self._worker_id,
                    "active_threads": sorted(self._active_threads),
                    "uptime_seconds": round(time.monotonic() - self._start_time),
                },
                headers=trace_headers(),
            )
            if resp.status_code == 200:
                return True
            # Non-200 is still a failure — gateway may be misconfigured.
            logger.warning(
                "Heartbeat returned HTTP %d (gateway_url=%s)",
                resp.status_code,
                self._api_url,
                extra={
                    "worker_id": self._worker_id,
                    "action": "send_heartbeat",
                    "http_status_code": resp.status_code,
                    "gateway_url": self._api_url,
                },
            )
            return False
        except httpx.HTTPError:
            logger.debug(
                "Heartbeat send failed (gateway_url=%s)",
                self._api_url,
                extra={
                    "worker_id": self._worker_id,
                    "action": "send_heartbeat",
                    "active_thread_count": len(self._active_threads),
                    "gateway_url": self._api_url,
                },
                exc_info=True,
            )
            return False

    async def heartbeat_loop(self, interval: float = 30.0) -> None:
        """Run a periodic heartbeat in a loop (designed for task groups).

        Tracks consecutive failures and escalates log severity.
        First failure → WARNING, every 5th consecutive failure → ERROR.
        On recovery after failures → INFO with recovery notice.

        Parameters
        ----------
        interval:
            Seconds between heartbeats.  Defaults to 30 s.
        """
        while True:
            success = await self.send_heartbeat()

            if success:
                if self._consecutive_hb_failures > 0:
                    logger.info(
                        "Heartbeat recovered after %d consecutive"
                        " failures (gateway_url=%s)",
                        self._consecutive_hb_failures,
                        self._api_url,
                        extra={
                            "worker_id": self._worker_id,
                            "action": "heartbeat_recovered",
                            "consecutive_failures": self._consecutive_hb_failures,
                            "gateway_url": self._api_url,
                        },
                    )
                self._consecutive_hb_failures = 0
            else:
                self._consecutive_hb_failures += 1
                n = self._consecutive_hb_failures

                if n == 1:
                    logger.warning(
                        "Gateway heartbeat failed"
                        " (gateway_url=%s) — will escalate"
                        " if failures persist",
                        self._api_url,
                        extra={
                            "worker_id": self._worker_id,
                            "action": "heartbeat_failure",
                            "consecutive_failures": n,
                            "gateway_url": self._api_url,
                        },
                    )
                elif n % 5 == 0:
                    logger.error(
                        "Gateway UNREACHABLE — %d consecutive"
                        " heartbeat failures"
                        " (gateway_url=%s). Permission events"
                        " and status updates are NOT being"
                        " delivered.",
                        n,
                        self._api_url,
                        extra={
                            "worker_id": self._worker_id,
                            "action": "heartbeat_failure_critical",
                            "consecutive_failures": n,
                            "gateway_url": self._api_url,
                        },
                    )

            await anyio.sleep(interval)
