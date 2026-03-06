"""Worker-to-control-surface IPC bridge (ADR-031).

Uses HTTP POST to push events and heartbeats to the control surface.
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


class WorkerBridge:
    """Pushes events and heartbeats to the control surface via HTTP.

    The bridge maintains an ``httpx.AsyncClient`` pointed at the control
    surface's ``/internal/`` endpoints.  It tracks which thread IDs are
    actively being processed so the heartbeat payload can report them.

    Events are accumulated in a buffer and flushed as a batch every
    ``_FLUSH_INTERVAL`` seconds to reduce HTTP overhead (CRIT-02).

    Parameters
    ----------
    api_url:
        Base URL of the control surface (e.g. ``http://localhost:8000``).
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
        """Buffer an event for batched relay to the control surface.

        Events are accumulated and flushed as a single HTTP POST after
        ``_FLUSH_INTERVAL`` seconds of inactivity or when ``flush_events``
        is called explicitly.
        """
        self._event_buffer.append(
            {"thread_id": thread_id, "payload": payload}
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

        Failures are logged at WARNING level but never raised -- the worker
        must not crash because the control surface is temporarily unavailable.
        """
        if not self._event_buffer:
            return

        batch = self._event_buffer[:]
        self._event_buffer.clear()

        try:
            resp = await self._client.post(
                "/internal/events/batch",
                json={"events": batch},
            )
            if resp.status_code != 200:
                logger.warning(
                    "Batch event relay failed (HTTP %d), %d events dropped",
                    resp.status_code,
                    len(batch),
                )
        except httpx.HTTPError:
            logger.warning(
                "Failed to send %d events to control surface",
                len(batch),
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    async def send_heartbeat(self) -> None:
        """Send a single heartbeat POST to the control surface."""
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
