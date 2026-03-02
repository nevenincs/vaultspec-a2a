"""Worker-to-control-surface IPC bridge (ADR-019).

Uses HTTP POST to push events and heartbeats to the control surface.
Avoids introducing a WebSocket client dependency by using httpx
(already in the project's dependency set).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import anyio
import httpx

__all__ = ["WorkerBridge"]

logger = logging.getLogger(__name__)


class WorkerBridge:
    """Pushes events and heartbeats to the control surface via HTTP.

    The bridge maintains an ``httpx.AsyncClient`` pointed at the control
    surface's ``/internal/`` endpoints.  It tracks which thread IDs are
    actively being processed so the heartbeat payload can report them.

    Parameters
    ----------
    api_url:
        Base URL of the control surface (e.g. ``http://localhost:8000``).
    worker_id:
        Unique identifier for this worker instance (hex string).
    """

    def __init__(self, api_url: str, worker_id: str) -> None:
        self._api_url = api_url.rstrip("/")
        self._worker_id = worker_id
        self._client = httpx.AsyncClient(
            base_url=self._api_url,
            timeout=httpx.Timeout(10.0, connect=5.0),
        )
        self._active_threads: set[str] = set()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Shut down the underlying HTTP client."""
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
    # Event relay
    # ------------------------------------------------------------------

    async def send_event(self, thread_id: str, payload: dict[str, Any]) -> None:
        """Push a single event to the control surface for relay to browser clients.

        Failures are logged at WARNING level but never raised -- the worker
        must not crash because the control surface is temporarily unavailable.
        """
        try:
            resp = await self._client.post(
                "/internal/events",
                json={
                    "type": "event",
                    "thread_id": thread_id,
                    "payload": payload,
                },
            )
            if resp.status_code != 200:
                logger.warning(
                    "Event relay failed (HTTP %d) for thread %s",
                    resp.status_code,
                    thread_id,
                )
        except httpx.HTTPError:
            logger.warning(
                "Failed to send event to control surface for thread %s",
                thread_id,
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
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
        except httpx.HTTPError:
            logger.debug("Heartbeat send failed", exc_info=True)

    async def heartbeat_loop(self, interval: float = 10.0) -> None:
        """Run a periodic heartbeat in a loop (designed for task groups).

        Parameters
        ----------
        interval:
            Seconds between heartbeats.  Defaults to 10 s.
        """
        while True:
            await self.send_heartbeat()
            await anyio.sleep(interval)
