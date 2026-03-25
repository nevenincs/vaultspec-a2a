"""Snapshot enrichment business logic extracted from api/endpoints.py."""

from __future__ import annotations

import contextlib
import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from ..api.schemas.enums import (
    AgentLifecycleState,
    PermissionOptionKind,
    ToolCallStatus,
    ToolKind,
)
from ..api.schemas.events import PlanEntry
from ..api.schemas.snapshots import (
    ArtifactSnapshot,
    MessageSnapshot,
    ThreadStateSnapshot,
    ToolCallSnapshot,
    _AgentSnapshot,
    _PermissionOptionSnapshot,
    _PermissionSnapshot,
)
from ..database.crud import ThreadStatus
from ..streaming.aggregator import EventAggregator, classify_tool_kind

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig
    from langgraph.types import StateSnapshot

    from ..database.checkpoints import Checkpointer


def enrich_snapshot_from_state(
    snapshot: ThreadStateSnapshot,
    state: StateSnapshot,
    aggregator: EventAggregator | None = None,
) -> ThreadStateSnapshot:
    """Populate snapshot fields from LangGraph checkpointer state.

    Maps LangChain ``BaseMessage`` objects to ``MessageSnapshot`` and
    extracts ``checkpoint_id``, plan, artifacts from the state config.
    Populates agents and pending permissions from the aggregator.
    """
    msgs: list[MessageSnapshot] = []
    for m in state.values.get("messages", []):
        if isinstance(m, HumanMessage):
            role = "user"
        elif isinstance(m, AIMessage):
            role = "assistant"
        elif isinstance(m, ToolMessage):
            role = "tool"
        else:
            role = "system"

        content = m.content if isinstance(m.content, str) else str(m.content)

        # Prefer actual message timestamp from response_metadata or additional_kwargs;
        # fall back to now() only if the provider did not populate a timestamp.
        ts: datetime | None = None
        for meta_src in (
            getattr(m, "response_metadata", None) or {},
            getattr(m, "additional_kwargs", None) or {},
        ):
            raw_ts = meta_src.get("created_at") or meta_src.get("timestamp")
            if isinstance(raw_ts, datetime):
                ts = raw_ts
                break
            if isinstance(raw_ts, str):
                with contextlib.suppress(ValueError):
                    ts = datetime.fromisoformat(raw_ts)
                if ts is not None:
                    break
        if ts is None:
            ts = datetime.now(UTC)

        # Stable fallback: deterministic hash of role+content so repeated
        # snapshot fetches return the same message_id (uuid4 would change each
        # call, breaking client-side deduplication for messages without a
        # persisted LangChain message id).
        stored_id: str | None = getattr(m, "id", None)
        message_id = (
            stored_id or hashlib.sha256(f"{role}:{content}".encode()).hexdigest()[:32]
        )

        msgs.append(
            MessageSnapshot(
                message_id=message_id,
                role=role,
                content=content,
                agent_id=getattr(m, "name", None),
                timestamp=ts,
            )
        )

    checkpoint_id: str | None = None
    if hasattr(state, "config") and state.config:
        checkpoint_id = state.config.get("configurable", {}).get("checkpoint_id")

    # Extract plan entries from checkpoint channel_values
    plan_raw = state.values.get("current_plan", [])
    plan_entries: list[PlanEntry] = []
    for entry in plan_raw:
        if isinstance(entry, dict):
            plan_entries.append(
                PlanEntry(
                    content=entry.get("content", ""),
                    status=entry.get("status", "pending"),
                    priority=entry.get("priority", "medium"),
                )
            )
        elif isinstance(entry, PlanEntry):
            plan_entries.append(entry)

    # Extract artifacts from checkpoint channel_values
    artifacts_raw = state.values.get("artifacts", [])
    artifact_snapshots: list[ArtifactSnapshot] = []
    for art in artifacts_raw:
        if isinstance(art, dict):
            artifact_snapshots.append(
                ArtifactSnapshot(
                    artifact_id=art.get("artifact_id", ""),
                    filename=art.get("filename", ""),
                    content=art.get("content", ""),
                    complete=art.get("complete", True),
                )
            )

    # Populate agents from aggregator node summaries + agent states
    agent_snapshots: list[_AgentSnapshot] = []
    if aggregator is not None:
        node_summaries = aggregator.get_node_summaries()
        agent_states = aggregator.get_agent_states()
        for node in node_summaries:
            agent_id = node.get("agent_id", node.get("node_name", ""))
            agent_snapshots.append(
                _AgentSnapshot(
                    agent_id=agent_id,
                    node_name=node.get("node_name", ""),
                    state=agent_states.get(agent_id, AgentLifecycleState.IDLE),
                    role=node.get("role", ""),
                    display_name=node.get("display_name", ""),
                    description=node.get("description", ""),
                )
            )

    # Populate pending permissions from aggregator
    perm_snapshots: list[_PermissionSnapshot] = []
    if aggregator is not None:
        thread_id = snapshot.thread_id
        for perm in aggregator.get_pending_permissions(thread_id):
            perm_snapshots.append(
                _PermissionSnapshot(
                    request_id=perm.request_id,
                    description=perm.description,
                    tool_call=perm.tool_call,
                    options=[
                        _PermissionOptionSnapshot(
                            option_id=opt.get("option_id", ""),
                            name=opt.get("name", ""),
                            kind=PermissionOptionKind(opt.get("kind", "allow_once")),
                        )
                        for opt in perm.options
                    ],
                )
            )

    # Extract tool calls from AIMessage.tool_calls, cross-reference with
    # ToolMessage to determine completion status.
    answered_tool_ids: set[str] = {
        m.tool_call_id
        for m in state.values.get("messages", [])
        if isinstance(m, ToolMessage) and hasattr(m, "tool_call_id")
    }
    tool_call_snapshots: list[ToolCallSnapshot] = []
    checkpoint_tc_ids: set[str] = set()
    for m in state.values.get("messages", []):
        if isinstance(m, AIMessage) and m.tool_calls:
            for tc in m.tool_calls:
                tc_id = tc.get("id", "")
                tc_name = tc.get("name", "unknown_tool")
                checkpoint_tc_ids.add(tc_id)
                tool_call_snapshots.append(
                    ToolCallSnapshot(
                        tool_call_id=tc_id,
                        title=tc_name,
                        kind=classify_tool_kind(tc_name),
                        status=(
                            ToolCallStatus.COMPLETED
                            if tc_id in answered_tool_ids
                            else ToolCallStatus.PENDING
                        ),
                    )
                )

    # F-38: Merge tool calls from aggregator in-memory state for tool calls
    # not present in the checkpoint.  This covers cases where: (a) the
    # checkpoint is stale / not yet written, (b) the gateway restarted but
    # the worker relayed tool_call events that the aggregator tracked, or
    # (c) the checkpoint's channel_values are not deserialized objects.
    if aggregator is not None:
        thread_id = snapshot.thread_id
        aggregator_tc_states = aggregator.get_tool_call_states(thread_id)
        for tc_id, tc_state in aggregator_tc_states.items():
            if tc_id in checkpoint_tc_ids:
                continue
            try:
                kind = ToolKind(tc_state.get("kind", ToolKind.OTHER.value))
            except ValueError:
                kind = ToolKind.OTHER
            try:
                status = ToolCallStatus(
                    tc_state.get("status", ToolCallStatus.PENDING.value)
                )
            except ValueError:
                status = ToolCallStatus.PENDING
            tool_call_snapshots.append(
                ToolCallSnapshot(
                    tool_call_id=tc_id,
                    title=tc_state.get("title", "unknown_tool"),
                    kind=kind,
                    status=status,
                )
            )

    return snapshot.model_copy(
        update={
            "messages": msgs,
            "checkpoint_id": checkpoint_id,
            "plan": plan_entries,
            "artifacts": artifact_snapshots,
            "agents": agent_snapshots,
            "pending_permissions": perm_snapshots,
            "tool_calls": tool_call_snapshots,
        }
    )


class MinimalState:
    """Minimal adapter for `enrich_snapshot_from_state()` reuse."""

    def __init__(
        self,
        values: dict[str, Any],
        cfg: dict[str, Any] | None = None,
    ) -> None:
        self.values = values
        self.config = cfg


async def load_checkpoint_history_depth(
    checkpointer: Checkpointer,
    config: RunnableConfig,
    *,
    limit: int = 2,
) -> int | None:
    """Return recent checkpoint history depth when the saver supports listing."""
    count = 0
    async for _item in checkpointer.alist(config, limit=limit):
        count += 1
    return count


def finalize_snapshot_replay_status(
    snapshot: ThreadStateSnapshot,
    *,
    checkpoint_loaded: bool,
    checkpoint_present: bool,
    checkpoint_error: bool,
    thread_status: str,
) -> ThreadStateSnapshot:
    """Apply the reconnect snapshot replay/degradation contract."""
    if checkpoint_loaded:
        snapshot.replay_status = "durable"
    elif checkpoint_error:
        snapshot.snapshot_complete = False
        snapshot.replay_status = "unknown"
    elif checkpoint_present:
        snapshot.snapshot_complete = False
        snapshot.replay_status = "best_effort"
    elif thread_status == ThreadStatus.SUBMITTED.value:
        snapshot.snapshot_complete = True
        snapshot.replay_status = "unknown"
    else:
        snapshot.snapshot_complete = False
        if "checkpoint_missing" not in snapshot.degraded_reasons:
            snapshot.degraded_reasons.append("checkpoint_missing")
        snapshot.replay_status = "gap_detected"
    return snapshot
