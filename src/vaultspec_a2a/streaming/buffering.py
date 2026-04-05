"""Chunk buffering and debounce management for streaming events.

Manages token chunk batching (50ms / 4KB flush), tool call update debounce,
and plan update debounce.  Extracted from the monolithic ``aggregator.py``
during Phase 6 decomposition (ADR D-01).
"""

import asyncio
import logging
from collections import defaultdict
from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import Any

from ..domain_config import domain_config
from ..graph.events import MessageChunk
from ..graph.protocols import NullTelemetryHook, TelemetryHook
from .subscribers import SubscriberManager
from .types import SequencedEvent, evict_oldest

logger = logging.getLogger(__name__)


class BufferingManager:
    """Chunk batching + debounce state for the streaming event bus."""

    def __init__(
        self,
        subscribers: SubscriberManager,
        telemetry: TelemetryHook | NullTelemetryHook,
        next_sequence: Any,  # callable: (thread_id: str) -> int
    ) -> None:
        self._subscribers = subscribers
        self._telemetry = telemetry
        self._next_sequence = next_sequence

        # Per-thread token chunk buffers for batching (research §1.3).
        self._chunk_buffers: dict[str, list[str]] = defaultdict(list)
        self._chunk_buffer_meta: dict[str, dict[str, str]] = {}
        self._chunk_flush_tasks: dict[str, asyncio.Task[None]] = {}

        # Debounce state: (thread_id, tool_call_id) -> last_emit_time
        self._tool_update_last_emit: dict[tuple[str, str], float] = {}
        # Debounce state: thread_id -> last_emit_time for plan updates
        self._plan_update_last_emit: dict[str, float] = {}

        # Pending debounced events
        self._tool_update_pending: dict[tuple[str, str], SequencedEvent] = {}
        self._plan_update_pending: dict[str, SequencedEvent] = {}

        # Debounce flush tasks
        self._debounce_tasks: set[asyncio.Task[None]] = set()

        # Lock for debounce pending maps
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Debounced broadcasting
    # ------------------------------------------------------------------

    async def broadcast_debounced_tool_update(
        self,
        key: tuple[str, str],
    ) -> None:
        """Flush a pending debounced tool call update after the interval."""
        await asyncio.sleep(domain_config.tool_call_debounce_seconds)
        async with self._lock:
            event = self._tool_update_pending.pop(key, None)
        if event is not None:
            await self._subscribers.broadcast(event)

    async def broadcast_debounced_plan_update(
        self,
        thread_id: str,
    ) -> None:
        """Flush a pending debounced plan update after the interval."""
        await asyncio.sleep(domain_config.plan_update_debounce_seconds)
        async with self._lock:
            event = self._plan_update_pending.pop(thread_id, None)
        if event is not None:
            await self._subscribers.broadcast(event)

    def schedule_debounce(
        self,
        coro: Coroutine[Any, Any, None],
    ) -> None:
        """Schedule a debounce flush task and track it for cleanup."""
        task = asyncio.create_task(coro)
        self._debounce_tasks.add(task)
        task.add_done_callback(self._debounce_tasks.discard)

    # ------------------------------------------------------------------
    # Tool update debounce helpers (used by emitters)
    # ------------------------------------------------------------------

    def get_tool_update_last_emit(self, key: tuple[str, str]) -> float:
        """Return the last emit timestamp for a tool update debounce key."""
        return self._tool_update_last_emit.get(key, 0.0)

    def set_tool_update_last_emit(self, key: tuple[str, str], ts: float) -> None:
        """Set the last emit timestamp for a tool update debounce key."""
        self._tool_update_last_emit[key] = ts
        max_entries = domain_config.debounce_map_max_entries
        if len(self._tool_update_last_emit) > max_entries:
            evict_oldest(self._tool_update_last_emit, max_entries)

    def get_plan_update_last_emit(self, thread_id: str) -> float:
        """Return the last emit timestamp for a plan update debounce key."""
        return self._plan_update_last_emit.get(thread_id, 0.0)

    def set_plan_update_last_emit(self, thread_id: str, ts: float) -> None:
        """Set the last emit timestamp for a plan update debounce key."""
        self._plan_update_last_emit[thread_id] = ts

    async def store_pending_tool_update(
        self, key: tuple[str, str], sequenced: SequencedEvent
    ) -> bool:
        """Store a pending tool update; return True if it was NOT already pending."""
        async with self._lock:
            already_pending = key in self._tool_update_pending
            self._tool_update_pending[key] = sequenced
        return not already_pending

    async def store_pending_plan_update(
        self, thread_id: str, sequenced: SequencedEvent
    ) -> None:
        """Store a pending plan update."""
        async with self._lock:
            self._plan_update_pending[thread_id] = sequenced

    # ------------------------------------------------------------------
    # Token chunk batching (research §1.3)
    # ------------------------------------------------------------------

    async def flush_chunk_buffer(self, thread_id: str) -> None:
        """Flush accumulated token chunks as a single MessageChunk."""
        chunks = self._chunk_buffers.pop(thread_id, [])
        meta = self._chunk_buffer_meta.pop(thread_id, None)
        self._chunk_flush_tasks.pop(thread_id, None)
        if chunks and meta:
            with self._telemetry.start_span(
                "aggregator.flush_chunks",
                thread_id=thread_id,
                chunk_count=len(chunks),
            ):
                combined = "".join(chunks)
                seq = self._next_sequence(thread_id)
                event = MessageChunk(
                    thread_id=thread_id,
                    agent_id=meta.get("agent_id", ""),
                    timestamp=datetime.now(UTC).timestamp(),
                    content=combined,
                    message_id=meta.get("message_id", ""),
                )
                await self._subscribers.broadcast(
                    SequencedEvent(event=event, sequence=seq)
                )

    async def _scheduled_chunk_flush(self, thread_id: str) -> None:
        """Timer-based flush: waits 50ms then flushes."""
        await asyncio.sleep(domain_config.chunk_flush_interval_seconds)
        await self.flush_chunk_buffer(thread_id)

    async def buffer_message_chunk(
        self,
        thread_id: str,
        agent_id: str,
        content: str,
        message_id: str,
    ) -> None:
        """Buffer a token chunk and flush on 50ms timeout or 4KB threshold."""
        existing_meta = self._chunk_buffer_meta.get(thread_id)
        if existing_meta and existing_meta["message_id"] != message_id:
            existing_task = self._chunk_flush_tasks.pop(thread_id, None)
            if existing_task is not None:
                existing_task.cancel()
            await self.flush_chunk_buffer(thread_id)

        self._chunk_buffers[thread_id].append(content)
        self._chunk_buffer_meta[thread_id] = {
            "agent_id": agent_id,
            "message_id": message_id,
        }
        self._telemetry.increment_counter(
            "aggregator.chunks_batched", 1, thread_id=thread_id
        )

        buffer_size = sum(len(c) for c in self._chunk_buffers[thread_id])

        if buffer_size >= domain_config.chunk_buffer_max_bytes:
            existing_task = self._chunk_flush_tasks.pop(thread_id, None)
            if existing_task is not None:
                existing_task.cancel()
            await self.flush_chunk_buffer(thread_id)
        elif thread_id not in self._chunk_flush_tasks:
            task = asyncio.create_task(self._scheduled_chunk_flush(thread_id))
            self._chunk_flush_tasks[thread_id] = task
            self._debounce_tasks.add(task)
            task.add_done_callback(self._debounce_tasks.discard)

    # ------------------------------------------------------------------
    # Cleanup helpers (used by ingest finalisation)
    # ------------------------------------------------------------------

    def prune_tool_debounce(self, thread_id: str) -> None:
        """Remove debounce timestamps for a completed thread."""
        stale_tool_keys = [k for k in self._tool_update_last_emit if k[0] == thread_id]
        for k in stale_tool_keys:
            del self._tool_update_last_emit[k]
        self._plan_update_last_emit.pop(thread_id, None)

    def clear_thread_state(self, thread_id: str) -> None:
        """Purge all buffered and debounced state scoped to ``thread_id``."""
        task = self._chunk_flush_tasks.pop(thread_id, None)
        if task is not None:
            task.cancel()
            self._debounce_tasks.discard(task)
        self._chunk_buffers.pop(thread_id, None)
        self._chunk_buffer_meta.pop(thread_id, None)
        self.prune_tool_debounce(thread_id)
        stale_tool_pending = [k for k in self._tool_update_pending if k[0] == thread_id]
        for key in stale_tool_pending:
            self._tool_update_pending.pop(key, None)
        self._plan_update_pending.pop(thread_id, None)

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    async def shutdown(self) -> None:
        """Cancel all debounce and chunk flush tasks and clear state."""
        for task in list(self._debounce_tasks):
            task.cancel()
        if self._debounce_tasks:
            await asyncio.gather(*self._debounce_tasks, return_exceptions=True)
        self._debounce_tasks.clear()

        chunk_flush_tasks = list(self._chunk_flush_tasks.values())
        for task in chunk_flush_tasks:
            task.cancel()
        if chunk_flush_tasks:
            await asyncio.gather(*chunk_flush_tasks, return_exceptions=True)
        self._chunk_flush_tasks.clear()

        self._chunk_buffers.clear()
        self._chunk_buffer_meta.clear()
        self._tool_update_last_emit.clear()
        self._plan_update_last_emit.clear()
        self._tool_call_states_ref = None
