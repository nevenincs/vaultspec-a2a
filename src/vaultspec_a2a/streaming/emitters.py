"""Event emission for the worker's event producer.

:class:`BroadcastChannel` is where every event the worker produces leaves it,
numbered for its run and handed to the relay hooks. :class:`EventEmitters`
builds each domain event, records what it changes in the run's live state
through the shared mutation layer, and broadcasts it.
"""

import json
import logging
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, NotRequired, TypedDict, Unpack

from ..domain_config import domain_config
from ..graph.acp_options import option_id_of, option_kind
from ..graph.enums import (
    AgentLifecycleState,
    ToolCallStatus,
    ToolKind,
)
from ..graph.events import (
    AgentStatus,
    ArtifactUpdate,
    ClarificationPending,
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
from ._run_state import RunLiveState
from .buffering import BufferingManager
from .node_metadata import node_metadata_fields
from .types import SequencedEvent, classify_tool_kind

logger = logging.getLogger(__name__)

__all__ = ["BroadcastChannel", "EventEmitters"]


class BroadcastChannel:
    """Where every event the worker produces leaves it, numbered for its run.

    The number is a worker-local ordering aid. It orders a run's events within
    one worker lifetime and restarts with the process, so it is not the run's
    event identity: the gateway stamps its own over the body's sequence field
    where the relayed frame enters subscriber queues. Nothing downstream
    resumes, deduplicates or persists against it.

    The hooks are the worker's relay to the gateway. A hook that fails costs
    that event its relay, never the run that produced it.
    """

    def __init__(self, telemetry: TelemetryHook | NullTelemetryHook) -> None:
        self._telemetry = telemetry
        self._sequences: dict[str, int] = defaultdict(int)
        self._hooks: list[Callable[[SequencedEvent], Awaitable[None]]] = []

    def next_sequence(self, thread_id: str) -> int:
        """Advance and return *thread_id*'s worker-local ordering number."""
        self._sequences[thread_id] += 1
        return self._sequences[thread_id]

    def forget(self, thread_id: str) -> None:
        """Drop *thread_id*'s counter, so a later run on the id starts at one."""
        self._sequences.pop(thread_id, None)

    def prune(self, active_thread_ids: set[str]) -> None:
        """Drop the counter of every run outside *active_thread_ids*."""
        for thread_id in [t for t in self._sequences if t not in active_thread_ids]:
            del self._sequences[thread_id]

    def add_hook(self, hook: Callable[[SequencedEvent], Awaitable[None]]) -> None:
        """Register a hook every broadcast event is handed to."""
        self._hooks.append(hook)

    async def broadcast(self, sequenced: SequencedEvent) -> None:
        """Hand one numbered event to every hook, in registration order."""
        thread_id = sequenced.event.thread_id
        event_type = type(sequenced.event).__name__
        with self._telemetry.start_span(
            "aggregator.broadcast",
            **{"event.type": event_type, "thread_id": thread_id or ""},
        ):
            self._telemetry.increment_counter(
                "aggregator.events_emitted", 1, **{"event.type": event_type}
            )
            for hook in self._hooks:
                try:
                    await hook(sequenced)
                except Exception:
                    logger.warning("Broadcast hook failed", exc_info=True)

    def clear(self) -> None:
        """Drop every run's counter."""
        self._sequences.clear()


class _ToolCallStartRequired(TypedDict):
    thread_id: str
    agent_id: str
    tool_call_id: str
    title: str


class _ToolCallStartKwargs(_ToolCallStartRequired, total=False):
    kind: NotRequired[ToolKind]
    input_args: NotRequired[dict[str, Any] | None]


class _ToolCallUpdateRequired(TypedDict):
    thread_id: str
    agent_id: str
    tool_call_id: str


class _ToolCallUpdateKwargs(_ToolCallUpdateRequired, total=False):
    status: NotRequired[ToolCallStatus | None]
    title: NotRequired[str | None]
    content: NotRequired[list[dict[str, str | None]] | None]
    locations: NotRequired[list[dict[str, str | int | None]] | None]


class _PermissionRequestRequired(TypedDict):
    thread_id: str
    agent_id: str
    request_id: str
    description: str
    options: list[dict[str, str]]


class _PermissionRequestKwargs(_PermissionRequestRequired, total=False):
    tool_call: NotRequired[str | None]
    tool_kind: NotRequired[ToolKind | None]


class _ArtifactUpdateRequired(TypedDict):
    thread_id: str
    artifact_id: str
    filename: str
    content: str


class _ArtifactUpdateKwargs(_ArtifactUpdateRequired, total=False):
    append: NotRequired[bool]
    last_chunk: NotRequired[bool]


class EventEmitters:
    """Build each domain event, record what it changes, and broadcast it.

    The run's agent, tool-call and node state is recorded through the shared
    :class:`RunLiveState` mutations, the same ones the gateway's mirror applies
    to the relayed payloads. Pending permissions are tracked here and nowhere
    else: the interrupt projection reads them before projecting a parked
    request again, and the gateway serves the durable row instead.
    """

    def __init__(
        self,
        channel: BroadcastChannel,
        buffering: BufferingManager,
        state: RunLiveState,
    ) -> None:
        self._channel = channel
        self._buffering = buffering
        self._state = state
        self._pending_permissions: dict[str, tuple[PermissionRequest, float]] = {}

    def get_tool_call_states(self, thread_id: str) -> dict[str, dict[str, str]]:
        """Return the state of each tool call recorded for *thread_id*."""
        return self._state.get_tool_call_states(thread_id)

    # ------------------------------------------------------------------
    # Permission management
    # ------------------------------------------------------------------

    def _replace_thread_pending_permission(
        self,
        *,
        thread_id: str,
        request_id: str,
        event: PermissionRequest,
    ) -> None:
        stale_request_ids = [
            rid
            for rid, (pending, _created_at) in self._pending_permissions.items()
            if pending.thread_id == thread_id and rid != request_id
        ]
        for stale_request_id in stale_request_ids:
            self._pending_permissions.pop(stale_request_id, None)
        self._pending_permissions[request_id] = (event, time.monotonic())

    def expire_thread_permissions(self, thread_id: str) -> int:
        """Drop every pending permission belonging to ``thread_id``.

        Age-independent: a terminal thread can never answer its requests,
        so they are dropped regardless of how recently they were recorded.
        """
        expired = [
            request_id
            for request_id, (evt, _ts) in self._pending_permissions.items()
            if evt.thread_id == thread_id
        ]
        for request_id in expired:
            del self._pending_permissions[request_id]
        return len(expired)

    def prune_stale_permissions(
        self, max_age_seconds: float | None = None, *, held_thread_ids: set[str]
    ) -> int:
        """Drop aged requests of runs this worker no longer holds.

        The age bound alone is the wrong rule. A parked run waits for a HUMAN,
        which routinely takes longer than any bound worth setting, and dropping
        its record lets the next projection of the same unanswered request emit a
        duplicate frame for it. So age only decides WHEN a droppable record goes;
        *held_thread_ids* decides WHICH are droppable, and a run the worker is
        still executing or still holding parked is never one of them. What is
        left for the bound to clean up is the record of a run whose end this
        worker never saw - the gateway restarted, the run was abandoned - which
        no terminal release will ever reach.

        *max_age_seconds* defaults to the configured bound.
        """
        if max_age_seconds is None:
            max_age_seconds = domain_config.pending_permission_max_age_seconds
        cutoff = time.monotonic() - max_age_seconds
        stale = [
            rid
            for rid, (evt, created_at) in self._pending_permissions.items()
            if created_at < cutoff and evt.thread_id not in held_thread_ids
        ]
        for rid in stale:
            del self._pending_permissions[rid]
        if stale:
            logger.info("Pruned %d stale permission request(s)", len(stale))
        return len(stale)

    def has_pending_permission(self, request_id: str) -> bool:
        """Report whether ``request_id`` already has a tracked pending permission."""
        return request_id in self._pending_permissions

    # ------------------------------------------------------------------
    # Event emission (public API)
    # ------------------------------------------------------------------

    async def emit_agent_status(
        self,
        thread_id: str,
        agent_id: str,
        node_name: str,
        state: AgentLifecycleState,
        detail: str | None = None,
    ) -> None:
        """Emit an agent lifecycle state transition event."""
        self._state.record_agent_state(thread_id, agent_id, state)
        seq = self._channel.next_sequence(thread_id)
        event = AgentStatus(
            thread_id=thread_id,
            agent_id=agent_id,
            timestamp=datetime.now(UTC).timestamp(),
            node_name=node_name,
            state=state,
            detail=detail,
        )
        await self._channel.broadcast(SequencedEvent(event=event, sequence=seq))
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
        seq = self._channel.next_sequence(thread_id)
        event = MessageChunk(
            thread_id=thread_id,
            agent_id=agent_id,
            timestamp=datetime.now(UTC).timestamp(),
            content=content,
            message_id=message_id,
            finish_reason=finish_reason,
        )
        await self._channel.broadcast(SequencedEvent(event=event, sequence=seq))

    async def emit_thought_chunk(
        self,
        thread_id: str,
        agent_id: str,
        content: str,
        message_id: str,
    ) -> None:
        """Emit a streaming thought/reasoning token event."""
        seq = self._channel.next_sequence(thread_id)
        event = ThoughtChunk(
            thread_id=thread_id,
            agent_id=agent_id,
            timestamp=datetime.now(UTC).timestamp(),
            content=content,
            message_id=message_id,
        )
        await self._channel.broadcast(SequencedEvent(event=event, sequence=seq))

    async def emit_tool_call_start(
        self,
        **kwargs: Unpack[_ToolCallStartKwargs],
    ) -> None:
        """Emit a tool invocation start event."""
        thread_id = kwargs["thread_id"]
        agent_id = kwargs["agent_id"]
        tool_call_id = kwargs["tool_call_id"]
        title = kwargs["title"]
        kind = kwargs.get("kind", ToolKind.OTHER)
        input_args = kwargs.get("input_args")
        content: list[dict[str, str | None]] = []
        if input_args:
            try:
                args_str = json.dumps(input_args, default=str, ensure_ascii=False)
            except (TypeError, ValueError):
                args_str = str(input_args)
            if len(args_str) > domain_config.tool_arg_truncate_len:
                args_str = args_str[: domain_config.tool_arg_truncate_len] + "..."
            content.append({"content_type": "text", "text": args_str})
        self._state.start_tool_call(
            (thread_id, tool_call_id), title=title, kind=kind, agent_id=agent_id
        )
        seq = self._channel.next_sequence(thread_id)
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
        await self._channel.broadcast(SequencedEvent(event=event, sequence=seq))

    async def emit_tool_call_update(
        self,
        **kwargs: Unpack[_ToolCallUpdateKwargs],
    ) -> None:
        """Emit a tool call update event (debounced).

        ``locations`` was previously accepted by the ``ToolCallUpdate`` domain
        event but had no parameter here to reach it, so a call site that
        DOES observe what a tool call touched (a Codex file-change item, an
        ACP-declared edit location) had no way to report it -- every update
        served empty ``locations`` regardless of what the provider disclosed.
        """
        thread_id = kwargs["thread_id"]
        agent_id = kwargs["agent_id"]
        tool_call_id = kwargs["tool_call_id"]
        status = kwargs.get("status")
        title = kwargs.get("title")
        content = kwargs.get("content")
        locations = kwargs.get("locations")
        now = time.monotonic()
        key = (thread_id, tool_call_id)

        self._state.update_tool_call(key, agent_id=agent_id, status=status, title=title)

        seq = self._channel.next_sequence(thread_id)
        event = ToolCallUpdate(
            thread_id=thread_id,
            agent_id=agent_id,
            timestamp=datetime.now(UTC).timestamp(),
            tool_call_id=tool_call_id,
            status=status,
            title=title,
            content=content,
            locations=locations,
        )
        sequenced = SequencedEvent(event=event, sequence=seq)

        last_emit = self._buffering.get_tool_update_last_emit(key)
        if now - last_emit >= domain_config.tool_call_debounce_seconds:
            self._buffering.set_tool_update_last_emit(key, now)
            await self._channel.broadcast(sequenced)
        else:
            is_new = await self._buffering.store_pending_tool_update(key, sequenced)
            if is_new:
                self._buffering.schedule_debounce(
                    self._buffering.broadcast_debounced_tool_update(key)
                )

    async def emit_permission_request(
        self,
        **kwargs: Unpack[_PermissionRequestKwargs],
    ) -> None:
        """Emit a permission request event (LangGraph interrupt)."""
        thread_id = kwargs["thread_id"]
        agent_id = kwargs["agent_id"]
        request_id = kwargs["request_id"]
        description = kwargs["description"]
        options = kwargs["options"]
        tool_call = kwargs.get("tool_call")
        tool_kind = kwargs.get("tool_kind")
        # An option carrying no id is dropped, never renamed. A minted id names
        # a choice no producer offered and no answer can be matched back to, so
        # a frame carrying one offered the operator a button that decides
        # nothing - and the durable row cached that invention as the request's
        # own offer.
        parsed_options: list[dict[str, str]] = [
            {
                "option_id": option_id,
                "name": opt.get("name", ""),
                "kind": str(option_kind(opt)),
            }
            for opt in options
            if (option_id := option_id_of(opt))
        ]

        resolved_kind = tool_kind
        if resolved_kind is None and tool_call:
            resolved_kind = classify_tool_kind(tool_call)

        seq = self._channel.next_sequence(thread_id)
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
        self._replace_thread_pending_permission(
            thread_id=thread_id,
            request_id=request_id,
            event=event,
        )
        await self._channel.broadcast(SequencedEvent(event=event, sequence=seq))

    async def emit_clarification_pending(
        self,
        thread_id: str,
        agent_id: str,
        request_id: str,
    ) -> None:
        """Emit the nudge that a run has parked on a questionnaire.

        Deliberately NOT registered in ``_pending_permissions``. That registry
        holds permission requests only - it is what the interrupt inspection
        checks before projecting a parked request again - and a clarification is
        not a permission: it has no options to choose and is answered through its
        own verb.

        The signature takes no question material because there is none to take.
        """
        seq = self._channel.next_sequence(thread_id)
        event = ClarificationPending(
            thread_id=thread_id,
            agent_id=agent_id,
            timestamp=datetime.now(UTC).timestamp(),
            request_id=request_id,
        )
        await self._channel.broadcast(SequencedEvent(event=event, sequence=seq))

    async def emit_artifact_update(
        self,
        **kwargs: Unpack[_ArtifactUpdateKwargs],
    ) -> None:
        """Emit an artifact update event."""
        thread_id = kwargs["thread_id"]
        artifact_id = kwargs["artifact_id"]
        filename = kwargs["filename"]
        content = kwargs["content"]
        append = kwargs.get("append", False)
        last_chunk = kwargs.get("last_chunk", True)
        seq = self._channel.next_sequence(thread_id)
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
        await self._channel.broadcast(SequencedEvent(event=event, sequence=seq))

    async def emit_plan_update(
        self,
        thread_id: str,
        entries: list[dict[str, str]],
    ) -> None:
        """Emit a plan update event (debounced)."""
        seq = self._channel.next_sequence(thread_id)
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
            await self._channel.broadcast(sequenced)
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
        seq = self._channel.next_sequence(thread_id)
        event = ErrorOccurred(
            thread_id=thread_id,
            agent_id=agent_id or "",
            timestamp=datetime.now(UTC).timestamp(),
            code=code,
            message=message,
            recoverable=recoverable,
        )
        await self._channel.broadcast(SequencedEvent(event=event, sequence=seq))

    async def _emit_team_status_from_agent_states(
        self,
        thread_id: str,
    ) -> None:
        """Build the run's agents list from its live state and emit ``team_status``."""
        agents: list[dict[str, Any]] = [
            {"agent_id": agent_id, "node_name": agent_id, "state": lifecycle.value}
            for agent_id, lifecycle in self._state.get_agent_states(thread_id).items()
        ]
        await self.emit_team_status(thread_id, agents)

    async def emit_team_status(
        self,
        thread_id: str,
        agents: list[dict[str, Any]],
        active_thread_ids: list[str] | None = None,
    ) -> None:
        """Emit a team status event (on transitions only)."""
        node_metadata = self._state.get_node_metadata(thread_id)
        agent_summaries: list[dict[str, str]] = []
        for agent_data in agents:
            data = dict(agent_data)
            node_name = data.get("node_name", "")
            node_meta = node_metadata.get(node_name, {})
            # Defaulted, not assigned: a caller-supplied value for any of these
            # wins over the cached node metadata.
            for field, value in node_metadata_fields(node_meta).items():
                data.setdefault(field, value)
            if hasattr(data.get("state"), "value"):
                data["state"] = data["state"].value
            agent_summaries.append(
                {k: str(v) if v is not None else "" for k, v in data.items()}
            )

        seq = self._channel.next_sequence(thread_id)
        event = TeamStatus(
            thread_id=thread_id,
            agent_id="",
            timestamp=datetime.now(UTC).timestamp(),
            agents=agent_summaries,
            active_thread_ids=active_thread_ids or [],
        )
        await self._channel.broadcast(SequencedEvent(event=event, sequence=seq))
