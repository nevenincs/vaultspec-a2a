"""Event emission and state tracking for the streaming event bus.

Manages per-thread sequence counters, pending permissions, agent lifecycle
states, tool call state cache, and all ``emit_*`` methods.  Extracted from
the monolithic ``aggregator.py`` during Phase 6 decomposition (ADR D-01).
"""

import json
import logging
import time
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from ..control.config import domain_config
from ..graph.enums import (
    AgentLifecycleState,
    PermissionOptionKind,
    ToolCallStatus,
    ToolKind,
)
from ..graph.events import (
    AgentStatus,
    ArtifactUpdate,
    DomainEvent,
    ErrorOccurred,
    MessageChunk,
    PermissionRequest,
    PlanUpdate,
    TeamStatus,
    ThoughtChunk,
    ToolCallStart,
    ToolCallUpdate,
)
from ..graph.protocols import NullTelemetryHook, TelemetryHook
from .buffering import BufferingManager
from .subscribers import SubscriberManager
from .types import SequencedEvent, classify_tool_kind, map_acp_option_kind

logger = logging.getLogger(__name__)


class EventEmitters:
    """Event emission + state tracking.

    Manages sequences, permissions, agent states, and tool calls.
    """

    def __init__(
        self,
        subscribers: SubscriberManager,
        buffering: BufferingManager,
        telemetry: TelemetryHook | NullTelemetryHook,
    ) -> None:
        self._subscribers = subscribers
        self._buffering = buffering
        self._telemetry = telemetry

        # Per-thread monotonic sequence counters (start at 0, first event = 1)
        self._sequences: dict[str, int] = defaultdict(int)

        # MCP-R5: track pending permission requests per thread.
        self._pending_permissions: dict[str, tuple[PermissionRequest, float]] = {}

        # P8-02: track agent lifecycle states for team status endpoint.
        self._agent_states: dict[str, AgentLifecycleState] = {}

        # F-38: track tool call state for REST snapshot enrichment.
        self._tool_call_states: dict[tuple[str, str], dict[str, str]] = {}

    # ------------------------------------------------------------------
    # Sequence management
    # ------------------------------------------------------------------

    def next_sequence(self, thread_id: str) -> int:
        """Atomically increment and return the next sequence for a thread."""
        self._sequences[thread_id] += 1
        return self._sequences[thread_id]

    def get_sequence(self, thread_id: str) -> int:
        """Return the current sequence counter for a thread (0 if unseen)."""
        return self._sequences.get(thread_id, 0)

    def advance_sequence(self, thread_id: str) -> int:
        """Increment and return the next sequence number for *thread_id*."""
        return self.next_sequence(thread_id)

    def sequence_count(self) -> int:
        """Return the number of threads that have received at least one event."""
        return len(self._sequences)

    def prune_sequences(self, active_thread_ids: set[str]) -> int:
        """Remove sequence counters for threads not in *active_thread_ids*."""
        stale = [tid for tid in self._sequences if tid not in active_thread_ids]
        for tid in stale:
            del self._sequences[tid]
        stale_tc_keys = [
            k for k in self._tool_call_states if k[0] not in active_thread_ids
        ]
        for k in stale_tc_keys:
            del self._tool_call_states[k]
        return len(stale)

    # ------------------------------------------------------------------
    # Tool call state management (F-38)
    # ------------------------------------------------------------------

    def _prune_completed_tool_calls(self, thread_id: str, cap: int = 50) -> None:
        """Remove oldest completed tool call entries when they exceed cap."""
        completed_keys = [
            k
            for k, v in self._tool_call_states.items()
            if k[0] == thread_id
            and v.get("status") in (ToolCallStatus.COMPLETED, ToolCallStatus.FAILED)
        ]
        if len(completed_keys) > cap:
            for key in completed_keys[:-cap]:
                self._tool_call_states.pop(key, None)

    def get_tool_call_states(self, thread_id: str) -> dict[str, dict[str, str]]:
        """Return tool call state dicts for *thread_id* (F-38)."""
        return {
            tc_id: dict(state)
            for (tid, tc_id), state in self._tool_call_states.items()
            if tid == thread_id
        }

    # ------------------------------------------------------------------
    # Permission management (MCP-R5)
    # ------------------------------------------------------------------

    def resolve_permission(self, request_id: str) -> None:
        """Remove a permission request from the pending set."""
        self._pending_permissions.pop(request_id, None)

    def prune_stale_permissions(self, max_age_seconds: float = 300.0) -> int:
        """Remove permission requests older than *max_age_seconds*."""
        cutoff = time.monotonic() - max_age_seconds
        stale = [
            rid
            for rid, (_evt, created_at) in self._pending_permissions.items()
            if created_at < cutoff
        ]
        for rid in stale:
            del self._pending_permissions[rid]
        if stale:
            logger.info("Pruned %d stale permission request(s)", len(stale))
        return len(stale)

    def get_pending_permissions(
        self,
        thread_id: str | None = None,
    ) -> list[PermissionRequest]:
        """Return pending permissions, optionally filtered by thread."""
        if thread_id is None:
            return [evt for evt, _ts in self._pending_permissions.values()]
        return [
            evt
            for evt, _ts in self._pending_permissions.values()
            if evt.thread_id == thread_id
        ]

    # ------------------------------------------------------------------
    # Agent state management (P8-02)
    # ------------------------------------------------------------------

    def get_agent_states(self) -> dict[str, AgentLifecycleState]:
        """Return a snapshot of current agent lifecycle states."""
        return dict(self._agent_states)

    # ------------------------------------------------------------------
    # Event emission (public API)
    # ------------------------------------------------------------------

    async def emit(self, event: DomainEvent) -> None:
        """Emit a pre-built domain event directly."""
        thread_id = getattr(event, "thread_id", None)
        seq = self.next_sequence(thread_id) if thread_id is not None else 0
        await self._subscribers.broadcast(SequencedEvent(event=event, sequence=seq))

    async def emit_agent_status(
        self,
        thread_id: str,
        agent_id: str,
        node_name: str,
        state: AgentLifecycleState,
        detail: str | None = None,
    ) -> None:
        """Emit an agent lifecycle state transition event."""
        self._agent_states[agent_id] = state
        seq = self.next_sequence(thread_id)
        event = AgentStatus(
            thread_id=thread_id,
            agent_id=agent_id,
            timestamp=datetime.now(UTC).timestamp(),
            node_name=node_name,
            state=state,
            detail=detail,
        )
        await self._subscribers.broadcast(SequencedEvent(event=event, sequence=seq))
        await self._emit_team_status_from_agent_states(thread_id)

    async def emit_message_chunk(
        self,
        thread_id: str,
        agent_id: str,
        content: str,
        message_id: str,
        finish_reason: str | None = None,
    ) -> None:
        """Emit a streaming message token event."""
        seq = self.next_sequence(thread_id)
        event = MessageChunk(
            thread_id=thread_id,
            agent_id=agent_id,
            timestamp=datetime.now(UTC).timestamp(),
            content=content,
            message_id=message_id,
            finish_reason=finish_reason,
        )
        await self._subscribers.broadcast(SequencedEvent(event=event, sequence=seq))

    async def emit_thought_chunk(
        self,
        thread_id: str,
        agent_id: str,
        content: str,
        message_id: str,
    ) -> None:
        """Emit a streaming thought/reasoning token event."""
        seq = self.next_sequence(thread_id)
        event = ThoughtChunk(
            thread_id=thread_id,
            agent_id=agent_id,
            timestamp=datetime.now(UTC).timestamp(),
            content=content,
            message_id=message_id,
        )
        await self._subscribers.broadcast(SequencedEvent(event=event, sequence=seq))

    async def emit_tool_call_start(
        self,
        thread_id: str,
        agent_id: str,
        tool_call_id: str,
        title: str,
        kind: ToolKind = ToolKind.OTHER,
        input_args: dict[str, Any] | None = None,
    ) -> None:
        """Emit a tool invocation start event."""
        content: list[dict[str, str | None]] = []
        if input_args:
            try:
                args_str = json.dumps(input_args, default=str, ensure_ascii=False)
            except (TypeError, ValueError):
                args_str = str(input_args)
            if len(args_str) > domain_config.tool_arg_truncate_len:
                args_str = args_str[: domain_config.tool_arg_truncate_len] + "..."
            content.append({"content_type": "text", "text": args_str})
        self._tool_call_states[(thread_id, tool_call_id)] = {
            "title": title,
            "kind": kind.value,
            "status": ToolCallStatus.PENDING.value,
            "agent_id": agent_id,
        }
        seq = self.next_sequence(thread_id)
        event = ToolCallStart(
            thread_id=thread_id,
            agent_id=agent_id,
            timestamp=datetime.now(UTC).timestamp(),
            tool_call_id=tool_call_id,
            title=title,
            kind=kind,
            status=ToolCallStatus.PENDING,
            content=content,
        )
        await self._subscribers.broadcast(SequencedEvent(event=event, sequence=seq))

    async def emit_tool_call_update(
        self,
        thread_id: str,
        agent_id: str,
        tool_call_id: str,
        status: ToolCallStatus | None = None,
        title: str | None = None,
        content: list[dict[str, str | None]] | None = None,
    ) -> None:
        """Emit a tool call update event (debounced per ADR-011 §5)."""
        now = time.monotonic()
        key = (thread_id, tool_call_id)

        existing = self._tool_call_states.get(key)
        if existing is not None:
            if status is not None:
                existing["status"] = status.value
            if title is not None:
                existing["title"] = title
        elif status is not None or title is not None:
            self._tool_call_states[key] = {
                "title": title or "unknown_tool",
                "kind": ToolKind.OTHER.value,
                "status": (status or ToolCallStatus.PENDING).value,
                "agent_id": agent_id,
            }

        if status in (ToolCallStatus.COMPLETED, ToolCallStatus.FAILED):
            self._prune_completed_tool_calls(thread_id)

        seq = self.next_sequence(thread_id)
        event = ToolCallUpdate(
            thread_id=thread_id,
            agent_id=agent_id,
            timestamp=datetime.now(UTC).timestamp(),
            tool_call_id=tool_call_id,
            status=status,
            title=title,
            content=content,
        )
        sequenced = SequencedEvent(event=event, sequence=seq)

        last_emit = self._buffering.get_tool_update_last_emit(key)
        if now - last_emit >= domain_config.tool_call_debounce_seconds:
            self._buffering.set_tool_update_last_emit(key, now)
            await self._subscribers.broadcast(sequenced)
        else:
            is_new = await self._buffering.store_pending_tool_update(key, sequenced)
            if is_new:
                self._buffering.schedule_debounce(
                    self._buffering.broadcast_debounced_tool_update(key)
                )

    async def emit_permission_request(
        self,
        thread_id: str,
        agent_id: str,
        request_id: str,
        description: str,
        options: list[dict[str, str]],
        tool_call: str | None = None,
        tool_kind: ToolKind | None = None,
    ) -> None:
        """Emit a permission request event (LangGraph interrupt)."""
        parsed_options: list[dict[str, str]] = [
            {
                "option_id": opt.get("option_id", str(uuid4())),
                "name": opt.get("name", ""),
                "kind": str(
                    PermissionOptionKind(
                        opt.get("kind", PermissionOptionKind.ALLOW_ONCE)
                    )
                ),
            }
            for opt in options
        ]

        resolved_kind = tool_kind
        if resolved_kind is None and tool_call:
            resolved_kind = classify_tool_kind(tool_call)

        seq = self.next_sequence(thread_id)
        event = PermissionRequest(
            thread_id=thread_id,
            agent_id=agent_id,
            timestamp=datetime.now(UTC).timestamp(),
            request_id=request_id,
            description=description,
            options=parsed_options,
            tool_call=tool_call,
            tool_kind=resolved_kind,
        )
        self._pending_permissions[request_id] = (event, time.monotonic())
        await self._subscribers.broadcast(SequencedEvent(event=event, sequence=seq))

    async def emit_artifact_update(
        self,
        thread_id: str,
        artifact_id: str,
        filename: str,
        content: str,
        append: bool = False,
        last_chunk: bool = True,
    ) -> None:
        """Emit an artifact update event (BE-29)."""
        seq = self.next_sequence(thread_id)
        event = ArtifactUpdate(
            thread_id=thread_id,
            agent_id="",
            timestamp=datetime.now(UTC).timestamp(),
            artifact_id=artifact_id,
            filename=filename,
            content=content,
            append=append,
            last_chunk=last_chunk,
        )
        await self._subscribers.broadcast(SequencedEvent(event=event, sequence=seq))

    async def emit_plan_update(
        self,
        thread_id: str,
        entries: list[dict[str, str]],
    ) -> None:
        """Emit a plan update event (debounced, BE-28)."""
        seq = self.next_sequence(thread_id)
        event = PlanUpdate(
            thread_id=thread_id,
            agent_id="",
            timestamp=datetime.now(UTC).timestamp(),
            entries=entries,
        )
        sequenced = SequencedEvent(event=event, sequence=seq)
        now = time.monotonic()
        last = self._buffering.get_plan_update_last_emit(thread_id)
        if now - last >= domain_config.plan_update_debounce_seconds:
            self._buffering.set_plan_update_last_emit(thread_id, now)
            await self._subscribers.broadcast(sequenced)
        else:
            await self._buffering.store_pending_plan_update(thread_id, sequenced)
            self._buffering.schedule_debounce(
                self._buffering.broadcast_debounced_plan_update(thread_id)
            )

    async def emit_error(
        self,
        thread_id: str,
        code: str,
        message: str,
        recoverable: bool = True,
        agent_id: str | None = None,
    ) -> None:
        """Emit a server-side error notification."""
        seq = self.next_sequence(thread_id)
        event = ErrorOccurred(
            thread_id=thread_id,
            agent_id=agent_id or "",
            timestamp=datetime.now(UTC).timestamp(),
            code=code,
            message=message,
            recoverable=recoverable,
        )
        await self._subscribers.broadcast(SequencedEvent(event=event, sequence=seq))

    async def _emit_team_status_from_agent_states(
        self,
        thread_id: str,
    ) -> None:
        """Build agents list from ``_agent_states`` and emit ``team_status``."""
        agents: list[dict[str, Any]] = []
        for agent_id, lifecycle in self._agent_states.items():
            agents.append(
                {
                    "agent_id": agent_id,
                    "node_name": agent_id,
                    "state": lifecycle.value,
                }
            )
        await self.emit_team_status(thread_id, agents)

    async def emit_team_status(
        self,
        thread_id: str,
        agents: list[dict[str, Any]],
        active_thread_ids: list[str] | None = None,
    ) -> None:
        """Emit a team status event (on transitions only, per ADR-011 §5)."""
        node_metadata = self._subscribers.get_node_metadata()
        agent_summaries: list[dict[str, str]] = []
        for agent_data in agents:
            data = dict(agent_data)
            node_name = data.get("node_name", "")
            node_meta = node_metadata.get(node_name, {})
            data.setdefault("role", node_meta.get("role", ""))
            data.setdefault("display_name", node_meta.get("display_name", ""))
            data.setdefault("description", node_meta.get("description", ""))
            if hasattr(data.get("state"), "value"):
                data["state"] = data["state"].value
            agent_summaries.append(
                {k: str(v) if v is not None else "" for k, v in data.items()}
            )

        seq = self.next_sequence(thread_id)
        event = TeamStatus(
            thread_id=thread_id,
            agent_id="",
            timestamp=datetime.now(UTC).timestamp(),
            agents=agent_summaries,
            active_thread_ids=active_thread_ids or [],
        )
        await self._subscribers.broadcast(SequencedEvent(event=event, sequence=seq))

    # ------------------------------------------------------------------
    # Worker event sync (P8-01)
    # ------------------------------------------------------------------

    def sync_worker_event(
        self,
        thread_id: str,
        payload: dict[str, Any],
    ) -> None:
        """Sync a relayed worker event into aggregator state."""
        event_type = payload.get("type", "")

        if event_type == "agent_status":
            agent_id = payload.get("agent_id", "")
            raw_state = payload.get("state", "")
            if agent_id and raw_state:
                try:
                    lifecycle = AgentLifecycleState(raw_state)
                except ValueError:
                    logger.warning(
                        "Unknown agent state %r in relayed event",
                        raw_state,
                    )
                    return
                self._agent_states[agent_id] = lifecycle
            self.next_sequence(thread_id)

        elif event_type == "permission_request":
            request_id = payload.get("request_id", "")
            if request_id:
                description = payload.get("description", "")
                options = payload.get("options", [])
                tool_call = payload.get("tool_call")
                perm_options: list[dict[str, str]] = []
                for opt in options:
                    perm_options.append(
                        {
                            "option_id": opt.get("option_id", ""),
                            "name": opt.get("name", ""),
                            "kind": str(map_acp_option_kind(opt.get("option_id", ""))),
                        }
                    )
                self._pending_permissions[request_id] = (
                    PermissionRequest(
                        thread_id=thread_id,
                        agent_id=payload.get("agent_id", ""),
                        timestamp=datetime.now(UTC).timestamp(),
                        request_id=request_id,
                        description=description,
                        options=perm_options,
                        tool_call=str(tool_call) if tool_call is not None else None,
                    ),
                    time.monotonic(),
                )
                self.next_sequence(thread_id)

        elif event_type == "permission_resolved":
            request_id = payload.get("request_id", "")
            if request_id:
                self._pending_permissions.pop(request_id, None)
            self.next_sequence(thread_id)

        elif event_type == "graph_registered":
            nodes = payload.get("nodes", {})
            if isinstance(nodes, dict):
                self._subscribers.set_node_metadata(
                    {
                        name: {
                            "role": str(meta.get("role", "")),
                            "display_name": str(meta.get("display_name", "")),
                            "description": str(meta.get("description", "")),
                        }
                        for name, meta in nodes.items()
                        if isinstance(meta, dict)
                    }
                )
                logger.debug(
                    "sync_worker_event: cached metadata for %d nodes",
                    len(nodes),
                )

        elif event_type == "plan_update":
            self.next_sequence(thread_id)

        elif event_type == "artifact_update":
            artifact_id = payload.get("artifact_id", "")
            filename = payload.get("filename", "")
            if artifact_id and filename:
                self.next_sequence(thread_id)

        elif event_type == "tool_call_start":
            tc_id = payload.get("tool_call_id", "")
            tc_title = payload.get("title", "unknown_tool")
            tc_kind = payload.get("kind", ToolKind.OTHER.value)
            agent_id = payload.get("agent_id", "")
            if tc_id:
                self._tool_call_states[(thread_id, tc_id)] = {
                    "title": tc_title,
                    "kind": tc_kind,
                    "status": ToolCallStatus.PENDING.value,
                    "agent_id": agent_id,
                }
            self.next_sequence(thread_id)

        elif event_type == "tool_call_update":
            tc_id = payload.get("tool_call_id", "")
            if tc_id:
                key = (thread_id, tc_id)
                existing = self._tool_call_states.get(key)
                if existing is not None:
                    if payload.get("status"):
                        existing["status"] = payload["status"]
                    if payload.get("title"):
                        existing["title"] = payload["title"]
                else:
                    self._tool_call_states[key] = {
                        "title": payload.get("title", "unknown_tool"),
                        "kind": payload.get("kind", ToolKind.OTHER.value),
                        "status": payload.get("status", ToolCallStatus.PENDING.value),
                        "agent_id": payload.get("agent_id", ""),
                    }
                updated_status = payload.get("status", "")
                if updated_status in (
                    ToolCallStatus.COMPLETED.value,
                    ToolCallStatus.FAILED.value,
                ):
                    self._prune_completed_tool_calls(thread_id)
            self.next_sequence(thread_id)

        elif thread_id and event_type:
            self.next_sequence(thread_id)

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Clear all emitter state."""
        self._sequences.clear()
        self._tool_call_states.clear()
