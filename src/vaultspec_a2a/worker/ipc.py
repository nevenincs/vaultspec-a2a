"""Worker-to-control-surface IPC bridge (ADR-031).

Uses HTTP POST to push events and heartbeats to the gateway.
Avoids introducing a WebSocket client dependency by using httpx
(already in the project's dependency set).

Events are batched for up to ``ipc_flush_interval_seconds`` seconds before being
sent as a single HTTP POST to ``/internal/events/batch`` (CRIT-02).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import anyio
import httpx
from fastapi.encoders import jsonable_encoder

from ..core.config import settings

__all__ = ["WorkerBridge"]

logger = logging.getLogger(__name__)


class WorkerBridge:
    """Pushes events and heartbeats to the gateway via HTTP.

    The bridge maintains an ``httpx.AsyncClient`` pointed at the control
    surface's ``/internal/`` endpoints.  It tracks which thread IDs are
    actively being processed so the heartbeat payload can report them.

    Events are accumulated in a buffer and flushed as a batch every
    ``ipc_flush_interval_seconds`` seconds to reduce HTTP overhead (CRIT-02).

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

        # Phase 4: consecutive heartbeat failure tracking for escalating logs.
        self._consecutive_hb_failures: int = 0

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
        ``ipc_flush_interval_seconds`` seconds of inactivity or when ``flush_events``
        is called explicitly.
        """
        # IPC-03: cap buffer to prevent unbounded memory growth.
        if len(self._event_buffer) >= settings.ipc_max_event_buffer:
            logger.warning(
                "Event buffer full (%d events), dropping oldest event",
                settings.ipc_max_event_buffer,
                extra={
                    "worker_id": self._worker_id,
                    "thread_id": thread_id,
                    "action": "buffer_drop_oldest",
                    "event_buffer_size": len(self._event_buffer),
                    "event_buffer_limit": settings.ipc_max_event_buffer,
                },
            )
            self._event_buffer.pop(0)

        self._event_buffer.append(
            {
                "thread_id": thread_id,
                "payload": jsonable_encoder(payload),
                "ts": time.monotonic(),
            }
        )
        # Schedule a flush if one isn't already pending.
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.create_task(self._deferred_flush())

    async def _deferred_flush(self) -> None:
        """Wait for the flush interval then send accumulated events."""
        await asyncio.sleep(settings.ipc_flush_interval_seconds)
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

        for attempt in range(settings.ipc_max_flush_retries):
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

            # Exponential backoff before retry.
            if attempt < settings.ipc_max_flush_retries - 1:
                await asyncio.sleep(
                    settings.ipc_retry_backoff_base_seconds * (2**attempt)
                )

        # All retries exhausted — events could not reach the gateway.
        # Phase 4: escalate to ERROR so operators notice IPC breakdown.
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
        space = settings.ipc_max_event_buffer - len(self._event_buffer)
        if space > 0:
            self._event_buffer[:0] = batch[:space]
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
                    "event_buffer_size": len(self._event_buffer),
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
                    "type": "heartbeat",
                    "worker_id": self._worker_id,
                    "active_threads": sorted(self._active_threads),
                    "uptime_seconds": round(time.monotonic() - self._start_time),
                },
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

        Phase 4: tracks consecutive failures and escalates log severity.
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
