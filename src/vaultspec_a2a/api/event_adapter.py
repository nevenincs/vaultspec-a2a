"""Translate domain events to wire-protocol events at the API boundary.

This module is the single point where domain events (``graph.events``)
are converted into Pydantic wire-protocol models (``api.schemas.events``)
for WebSocket serialisation.  The aggregator emits ``SequencedEvent``
wrappers; this adapter unpacks them.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from ..streaming.aggregator import SequencedEvent
from .schemas.enums import (
    AgentLifecycleState,
    PermissionOptionKind,
    PlanEntryPriority,
    PlanEntryStatus,
)
from .schemas.events import (
    AgentStatusEvent,
    AgentSummary,
    ArtifactUpdateEvent,
    ErrorEvent,
    MessageChunkEvent,
    PermissionOption,
    PermissionRequestEvent,
    PlanEntry,
    PlanUpdateEvent,
    ServerEvent,
    TeamStatusEvent,
    ThoughtChunkEvent,
    ToolCallContent,
    ToolCallContentDiff,
    ToolCallContentTerminal,
    ToolCallContentText,
    ToolCallLocation,
    ToolCallStartEvent,
    ToolCallUpdateEvent,
)

__all__ = ["domain_to_wire", "sequenced_to_wire"]


def _ts(epoch: float) -> datetime:
    """Convert a Unix epoch timestamp to a timezone-aware datetime."""
    return datetime.fromtimestamp(epoch, tz=UTC)


def _content_to_wire(c: dict[str, str | None]) -> ToolCallContent | None:
    """Convert a domain content dict to the appropriate wire ToolCallContent variant.

    Returns ``None`` for unrecognised ``content_type`` values so callers can
    filter silently — the aggregator currently only emits ``text``, but the ACP
    protocol also defines ``diff`` and ``terminal`` content blocks.
    """
    ct = c.get("content_type")
    if ct == "text":
        return ToolCallContentText(text=c.get("text") or "")
    if ct == "diff":
        return ToolCallContentDiff(
            path=str(c.get("path") or ""),
            old_text=c.get("old_text"),
            new_text=str(c.get("new_text") or ""),
        )
    if ct == "terminal":
        return ToolCallContentTerminal(terminal_id=str(c.get("terminal_id") or ""))
    return None


def _loc_to_wire(loc: dict[str, str | int | None]) -> ToolCallLocation:
    """Convert a domain location dict to a wire ToolCallLocation."""
    raw_line = loc.get("line")
    return ToolCallLocation(
        path=str(loc.get("path") or ""),
        line=raw_line if isinstance(raw_line, int) else None,
    )


def domain_to_wire(event: DomainEvent, sequence: int) -> ServerEvent:
    """Map a domain event + sequence number to a wire-protocol event."""
    ts = _ts(event.timestamp)

    match event:
        case MessageChunk():
            return MessageChunkEvent(
                thread_id=event.thread_id,
                agent_id=event.agent_id,
                sequence=sequence,
                timestamp=ts,
                content=event.content,
                message_id=event.message_id,
                finish_reason=event.finish_reason,
            )

        case ThoughtChunk():
            return ThoughtChunkEvent(
                thread_id=event.thread_id,
                agent_id=event.agent_id,
                sequence=sequence,
                timestamp=ts,
                content=event.content,
                message_id=event.message_id,
            )

        case ToolCallStart():
            content: list[ToolCallContent] = [
                w for c in event.content if (w := _content_to_wire(c)) is not None
            ]
            locations = [_loc_to_wire(loc) for loc in event.locations]
            return ToolCallStartEvent(
                thread_id=event.thread_id,
                agent_id=event.agent_id,
                sequence=sequence,
                timestamp=ts,
                tool_call_id=event.tool_call_id,
                title=event.title,
                kind=event.kind,
                status=event.status,
                content=content,
                locations=locations,
            )

        case ToolCallUpdate():
            upd_content: list[ToolCallContent] | None = None
            if event.content is not None:
                upd_content = [
                    w for c in event.content if (w := _content_to_wire(c)) is not None
                ]
            upd_locations = None
            if event.locations is not None:
                upd_locations = [_loc_to_wire(loc) for loc in event.locations]
            return ToolCallUpdateEvent(
                thread_id=event.thread_id,
                agent_id=event.agent_id,
                sequence=sequence,
                timestamp=ts,
                tool_call_id=event.tool_call_id,
                title=event.title,
                kind=event.kind,
                status=event.status,
                content=upd_content,
                locations=upd_locations,
            )

        case PermissionRequest():
            options = [
                PermissionOption(
                    option_id=opt.get("option_id", ""),
                    name=opt.get("name", ""),
                    kind=PermissionOptionKind(
                        opt.get("kind", PermissionOptionKind.ALLOW_ONCE)
                    ),
                )
                for opt in event.options
            ]
            return PermissionRequestEvent(
                thread_id=event.thread_id,
                agent_id=event.agent_id,
                sequence=sequence,
                timestamp=ts,
                request_id=event.request_id,
                description=event.description,
                options=options,
                tool_call=event.tool_call,
                tool_kind=event.tool_kind,
            )

        case PlanUpdate():
            entries = [
                PlanEntry(
                    content=e.get("content", ""),
                    status=PlanEntryStatus(e.get("status", "pending")),
                    priority=PlanEntryPriority(e.get("priority", "medium")),
                )
                for e in event.entries
            ]
            return PlanUpdateEvent(
                thread_id=event.thread_id,
                sequence=sequence,
                timestamp=ts,
                entries=entries,
            )

        case ArtifactUpdate():
            return ArtifactUpdateEvent(
                thread_id=event.thread_id,
                sequence=sequence,
                timestamp=ts,
                artifact_id=event.artifact_id,
                filename=event.filename,
                content=event.content,
                append=event.append,
                last_chunk=event.last_chunk,
            )

        case AgentStatus():
            return AgentStatusEvent(
                thread_id=event.thread_id,
                agent_id=event.agent_id,
                sequence=sequence,
                timestamp=ts,
                state=event.state,
                node_name=event.node_name,
                detail=event.detail,
            )

        case TeamStatus():
            agents = [
                AgentSummary(
                    agent_id=a.get("agent_id", ""),
                    node_name=a.get("node_name", ""),
                    state=AgentLifecycleState(a.get("state", "idle")),
                    role=a.get("role", ""),
                    display_name=a.get("display_name", ""),
                    description=a.get("description", ""),
                )
                for a in event.agents
            ]
            return TeamStatusEvent(
                thread_id=event.thread_id,
                sequence=sequence,
                timestamp=ts,
                agents=agents,
                active_thread_ids=event.active_thread_ids,
            )

        case ErrorOccurred():
            return ErrorEvent(
                thread_id=event.thread_id,
                agent_id=event.agent_id or None,
                sequence=sequence,
                timestamp=ts,
                code=event.code,
                message=event.message,
                recoverable=event.recoverable,
            )

        case _:
            msg = f"Unmapped domain event type: {type(event).__name__}"
            raise TypeError(msg)


def sequenced_to_wire(sequenced: SequencedEvent) -> ServerEvent:
    """Convenience wrapper: unpack a ``SequencedEvent`` and convert."""
    return domain_to_wire(sequenced.event, sequenced.sequence)


def sequenced_to_dict(sequenced: SequencedEvent) -> dict:
    """Serialise a ``SequencedEvent`` to a plain dict (for bridge relay)."""
    d = asdict(sequenced.event)
    d["sequence"] = sequenced.sequence
    return d
