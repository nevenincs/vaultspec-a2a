"""Worker-to-control-surface IPC bridge.

Uses HTTP POST to push events and heartbeats to the gateway.
Avoids introducing a WebSocket client dependency by using httpx
(already in the project's dependency set).

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
from ..graph.enums import ServerEventType
from ..telemetry import inject_trace_context

__all__ = ["WorkerBridge"]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _BatchState:
    events: list[dict[str, Any]] = field(default_factory=list)
    flush_task: asyncio.Task[None] | None = None


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
        headers: dict[str, str] = {}
        if internal_token:
            headers["Authorization"] = f"Bearer {internal_token}"
        self._client = httpx.AsyncClient(
            base_url=self._api_url,
            timeout=httpx.Timeout(10.0, connect=5.0),
            headers=headers,
        )
        self._active_threads: set[str] = set()
        self._start_time = time.monotonic()  # track uptime

        # Event batching state
        self._batch = _BatchState()

        # Consecutive heartbeat failure tracking for escalating logs.
        self._consecutive_hb_failures: int = 0

    @property
    def _event_buffer(self) -> list[dict[str, Any]]:
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
        owner has moved to forced process-tree cleanup.
        """
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
                deadline - 0.1,
            )
        delivered = pending_joined and await self.flush_events(deadline=flush_deadline)
        remaining = self._remaining(deadline)
        if remaining is None:
            await self._client.aclose()
        elif remaining > 0:
            try:
                async with asyncio.timeout(remaining):
                    await self._client.aclose()
            except TimeoutError:
                logger.error(
                    "Worker bridge client close exceeded the shared shutdown deadline",
                    extra={
                        "worker_id": self._worker_id,
                        "action": "bridge_close_timeout",
                    },
                )
                delivered = False
        else:
            delivered = False
        return delivered

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

    @staticmethod
    def _trace_headers() -> dict[str, str] | None:
        """Inject the current trace context into outbound IPC requests."""
        headers: dict[str, str] = {}
        inject_trace_context(headers)
        return headers or None

    async def send_event(self, thread_id: str, payload: dict[str, Any]) -> None:
        """Buffer an event for batched relay to the gateway.

        Events are accumulated and flushed as a single HTTP POST after
        ``ipc_flush_interval_seconds`` seconds of inactivity or when ``flush_events``
        is called explicitly.
        """
        # Cap buffer to prevent unbounded memory growth.
        if len(self._batch.events) >= settings.ipc_max_event_buffer:
            logger.warning(
                "Event buffer full (%d events), dropping oldest event",
                settings.ipc_max_event_buffer,
                extra={
                    "worker_id": self._worker_id,
                    "thread_id": thread_id,
                    "action": "buffer_drop_oldest",
                    "event_buffer_size": len(self._batch.events),
                    "event_buffer_limit": settings.ipc_max_event_buffer,
                },
            )
            self._batch.events.pop(0)

        self._batch.events.append(
            {
                "thread_id": thread_id,
                "payload": jsonable_encoder(payload),
                "ts": time.monotonic(),
            }
        )
        # Schedule a flush if one isn't already pending.
        if self._batch.flush_task is None or self._batch.flush_task.done():
            self._batch.flush_task = asyncio.create_task(self._deferred_flush())

    async def _deferred_flush(self) -> None:
        """Wait for the flush interval then send accumulated events."""
        await asyncio.sleep(settings.ipc_flush_interval_seconds)
        await self.flush_events()

    async def _post_event_batch(
        self,
        batch: list[dict[str, Any]],
        *,
        attempt: int,
        request_timeout: httpx.Timeout | float | None,
    ) -> bool:
        try:
            resp = await self._client.post(
                "/internal/events/batch",
                json={"events": batch},
                headers=self._trace_headers(),
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
        self, batch: list[dict[str, Any]], *, attempt: int, remaining: float | None
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
        self, batch: list[dict[str, Any]], *, attempt: int, deadline: float | None
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
        """Immediately send all buffered events as a single batch POST.

        Retries up to ``_MAX_FLUSH_RETRIES`` times with exponential
        backoff on failure.  Events are re-queued on final failure so they
        are not silently lost (subject to the buffer cap).

        Failures are logged at WARNING level but never raised -- the worker
        must not crash because the gateway is temporarily unavailable.
        """
        if not self._batch.events:
            return True

        batch = self._batch.events[:]
        self._batch.events.clear()

        for attempt in range(settings.ipc_max_flush_retries):
            remaining = self._remaining(deadline)
            if remaining is not None and remaining <= 0:
                break
            if await self._send_batch_once(batch, attempt=attempt, remaining=remaining):
                return True

            # Exponential backoff before retry.
            if attempt < settings.ipc_max_flush_retries - 1 and not (
                await self._wait_for_flush_retry(
                    batch, attempt=attempt, deadline=deadline
                )
            ):
                break

        self._requeue_failed_batch(batch)
        return False

    def _requeue_failed_batch(self, batch: list[dict[str, Any]]) -> None:
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

        # Re-queue events (respecting buffer cap).
        space = settings.ipc_max_event_buffer - len(self._batch.events)
        if space > 0:
            self._batch.events[:0] = batch[:space]
        dropped = len(batch) - max(space, 0)
        if dropped > 0:
            logger.error(
                "Dropped %d events after %d failed flush attempts",
                dropped,
                settings.ipc_max_flush_retries,
                extra={
                    "worker_id": self._worker_id,
                    "action": "flush_events_drop",
                    "dropped_events": dropped,
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
                headers=self._trace_headers(),
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
