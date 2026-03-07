"""Worker-to-control-surface IPC bridge (ADR-031).

Uses HTTP POST to push events and heartbeats to the gateway.
Avoids introducing a WebSocket client dependency by using httpx
(already in the project's dependency set).

Events are batched for up to ``_FLUSH_INTERVAL`` seconds before being
sent as a single HTTP POST to ``/internal/events/batch`` (CRIT-02).
"""

from __future__ import annotations

import asyncio
import logging
import time

from typing import Any

import anyio
import httpx


__all__ = ["WorkerBridge"]

logger = logging.getLogger(__name__)

# CRIT-02: batch flush interval in seconds.
_FLUSH_INTERVAL = 0.05

# IPC-03: retry and buffer limits for event relay.
_MAX_FLUSH_RETRIES = 3
_RETRY_BACKOFF_BASE = 0.1  # seconds; doubles each retry (0.1, 0.2, 0.4)
_MAX_EVENT_BUFFER = 10_000


class WorkerBridge:
    """Pushes events and heartbeats to the gateway via HTTP.

    The bridge maintains an ``httpx.AsyncClient`` pointed at the control
    surface's ``/internal/`` endpoints.  It tracks which thread IDs are
    actively being processed so the heartbeat payload can report them.

    Events are accumulated in a buffer and flushed as a batch every
    ``_FLUSH_INTERVAL`` seconds to reduce HTTP overhead (CRIT-02).

    Parameters
    ----------
    api_url:
        Base URL of the gateway (e.g. ``http://localhost:8000``).
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
        # WPA-002: attach bearer token to all internal IPC requests if provided.
        headers = {}
        if internal_token:
            headers["Authorization"] = f"Bearer {internal_token}"
        self._client = httpx.AsyncClient(
            base_url=self._api_url,
            timeout=httpx.Timeout(10.0, connect=5.0),
            headers=headers,
        )
        self._active_threads: set[str] = set()
        self._start_time = time.monotonic()  # WPA-004: track uptime

        # CRIT-02: event batching state
        self._event_buffer: list[dict[str, Any]] = []
        self._flush_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Flush pending events and shut down the underlying HTTP client."""
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
        await self.flush_events()
        await self._client.aclose()

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
    # Event relay (batched, CRIT-02)
    # ------------------------------------------------------------------

    async def send_event(self, thread_id: str, payload: dict[str, Any]) -> None:
        """Buffer an event for batched relay to the gateway.

        Events are accumulated and flushed as a single HTTP POST after
        ``_FLUSH_INTERVAL`` seconds of inactivity or when ``flush_events``
        is called explicitly.
        """
        # IPC-03: cap buffer to prevent unbounded memory growth.
        if len(self._event_buffer) >= _MAX_EVENT_BUFFER:
            logger.warning(
                "Event buffer full (%d events), dropping oldest event",
                _MAX_EVENT_BUFFER,
            )
            self._event_buffer.pop(0)

        self._event_buffer.append(
            {"thread_id": thread_id, "payload": payload, "ts": time.monotonic()}
        )
        # Schedule a flush if one isn't already pending.
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.create_task(self._deferred_flush())

    async def _deferred_flush(self) -> None:
        """Wait for the flush interval then send accumulated events."""
        await asyncio.sleep(_FLUSH_INTERVAL)
        await self.flush_events()

    async def flush_events(self) -> None:
        """Immediately send all buffered events as a single batch POST.

        IPC-03: retries up to ``_MAX_FLUSH_RETRIES`` times with exponential
        backoff on failure.  Events are re-queued on final failure so they
        are not silently lost (subject to the buffer cap).

        Failures are logged at WARNING level but never raised -- the worker
        must not crash because the gateway is temporarily unavailable.
        """
        if not self._event_buffer:
            return

        batch = self._event_buffer[:]
        self._event_buffer.clear()

        for attempt in range(_MAX_FLUSH_RETRIES):
            try:
                resp = await self._client.post(
                    "/internal/events/batch",
                    json={"events": batch},
                )
                if resp.status_code == 200:
                    return  # success
                logger.warning(
                    "Batch event relay failed (HTTP %d), attempt %d/%d",
                    resp.status_code,
                    attempt + 1,
                    _MAX_FLUSH_RETRIES,
                )
            except httpx.HTTPError:
                logger.warning(
                    "Failed to send %d events (attempt %d/%d)",
                    len(batch),
                    attempt + 1,
                    _MAX_FLUSH_RETRIES,
                    exc_info=True,
                )

            # Exponential backoff before retry.
            if attempt < _MAX_FLUSH_RETRIES - 1:
                await asyncio.sleep(_RETRY_BACKOFF_BASE * (2**attempt))

        # All retries exhausted -- re-queue events (respecting buffer cap).
        space = _MAX_EVENT_BUFFER - len(self._event_buffer)
        if space > 0:
            self._event_buffer[:0] = batch[:space]
        dropped = len(batch) - max(space, 0)
        if dropped > 0:
            logger.warning(
                "Dropped %d events after %d failed flush attempts",
                dropped,
                _MAX_FLUSH_RETRIES,
            )

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    async def send_heartbeat(self) -> None:
        """Send a single heartbeat POST to the gateway."""
        try:
            await self._client.post(
                "/internal/heartbeat",
                json={
                    "type": "heartbeat",
                    "worker_id": self._worker_id,
                    "active_threads": sorted(self._active_threads),
                    "uptime_seconds": round(time.monotonic() - self._start_time),
                },
            )
        except httpx.HTTPError:
            logger.debug("Heartbeat send failed", exc_info=True)

    async def heartbeat_loop(self, interval: float = 30.0) -> None:
        """Run a periodic heartbeat in a loop (designed for task groups).

        Parameters
        ----------
        interval:
            Seconds between heartbeats.  Defaults to 10 s.
        """
        while True:
            await self.send_heartbeat()
            await anyio.sleep(interval)
