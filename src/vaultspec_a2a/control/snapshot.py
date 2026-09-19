"""Snapshot enrichment business logic extracted from api/endpoints.py."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from langchain_core.messages import AIMessage, ToolCall, ToolMessage

from ..graph.enums import (
    AgentLifecycleState,
    ToolCallStatus,
    ToolKind,
)
from ..streaming.node_metadata import NODE_METADATA_FIELDS
from ..streaming.types import (
    action_detail_projection,
    classify_tool_kind,
    map_action_item_status,
)
from ..thread.snapshots import (
    AgentData,
    ArtifactData,
    MessageData,
    ThreadStateData,
    ToolCallData,
    build_agent_descriptor,
    classify_message_role,
    derive_message_id,
    extract_message_timestamp,
    normalize_artifacts,
    normalize_plan_entries,
)

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig

    from ..database.checkpoints import Checkpointer
    from ..streaming.aggregator import EventAggregator


def _is_valid_agent_descriptor(name: object, descriptor: object) -> bool:
    """Validate one raw agent-descriptor entry before it is trusted as data."""
    if not (isinstance(name, str) and 0 < len(name) <= 128):
        return False
    if not isinstance(descriptor, dict):
        return False
    fields = cast("dict[str, object]", descriptor)
    if set(fields) != set(NODE_METADATA_FIELDS):
        return False
    return all(
        isinstance(value, str) and len(value) <= 1024 for value in fields.values()
    )


def _checkpoint_messages(values: dict[str, Any]) -> list[MessageData]:
    messages: list[MessageData] = []
    for message in values.get("messages", []):
        role = classify_message_role(message)
        content = (
            message.content
            if isinstance(message.content, str)
            else str(message.content)
        )
        stored_id: str | None = getattr(message, "id", None)
        messages.append(
            MessageData(
                message_id=derive_message_id(role, content, stored_id),
                role=role,
                content=content,
                agent_id=getattr(message, "name", None),
                timestamp=extract_message_timestamp(message),
            )
        )
    return messages


def _checkpoint_agents(
    snapshot: ThreadStateData,
    values: dict[str, Any],
    aggregator: EventAggregator | None,
) -> list[AgentData]:
    raw_descriptors: object = values.get("agent_descriptors")
    node_summaries: list[dict[str, str]] = []
    if isinstance(raw_descriptors, dict):
        descriptors = cast("dict[object, object]", raw_descriptors)
        descriptors_valid = all(
            _is_valid_agent_descriptor(name, descriptor)
            for name, descriptor in descriptors.items()
        )
        if descriptors_valid:
            node_summaries = [
                {
                    "node_name": cast("str", name),
                    "agent_id": cast("str", name),
                    **cast("dict[str, str]", descriptor),
                }
                for name, descriptor in descriptors.items()
            ]
        else:
            snapshot.snapshot_complete = False
            snapshot.degraded_reasons.append("invalid_agent_descriptors")
    elif aggregator is not None:
        node_summaries = aggregator.get_node_summaries(snapshot.thread_id)
    if not node_summaries:
        return []
    agent_states = (
        aggregator.get_agent_states(snapshot.thread_id)
        if aggregator is not None
        else {}
    )
    return [
        build_agent_descriptor(
            node,
            agent_states.get(
                node.get("agent_id", node.get("node_name", "")),
                AgentLifecycleState.IDLE,
            ),
            thread_id=snapshot.thread_id,
        )
        for node in node_summaries
    ]


def _checkpoint_tool_call(
    call: ToolCall, answered_tool_ids: set[str]
) -> ToolCallData | None:
    call_id = call.get("id")
    if not isinstance(call_id, str):
        return None
    name = call.get("name", "unknown_tool")
    detail = call.get("args") or {}
    if "status" in detail:
        content, locations = action_detail_projection(name, detail)
        return ToolCallData(
            tool_call_id=call_id,
            title=name,
            kind=str(classify_tool_kind(name)),
            status=str(map_action_item_status(detail.get("status"))),
            content=content,
            locations=locations,
        )
    return ToolCallData(
        tool_call_id=call_id,
        title=name,
        kind=str(classify_tool_kind(name)),
        status=str(
            ToolCallStatus.COMPLETED
            if call_id in answered_tool_ids
            else ToolCallStatus.PENDING
        ),
    )


def _checkpoint_tool_calls(
    values: dict[str, Any],
) -> tuple[list[ToolCallData], set[str]]:
    answered_tool_ids: set[str] = {
        message.tool_call_id
        for message in values.get("messages", [])
        if isinstance(message, ToolMessage)
    }
    tool_calls: list[ToolCallData] = []
    checkpoint_ids: set[str] = set()
    for message in values.get("messages", []):
        if not isinstance(message, AIMessage) or not message.tool_calls:
            continue
        for call in message.tool_calls:
            projected = _checkpoint_tool_call(call, answered_tool_ids)
            if projected is None:
                continue
            checkpoint_ids.add(projected.tool_call_id)
            tool_calls.append(projected)
    return tool_calls, checkpoint_ids


def _live_tool_calls(
    aggregator: EventAggregator, thread_id: str, checkpoint_ids: set[str]
) -> list[ToolCallData]:
    tool_calls: list[ToolCallData] = []
    for call_id, state in aggregator.get_tool_call_states(thread_id).items():
        if call_id in checkpoint_ids:
            continue
        try:
            kind = str(ToolKind(state.get("kind", ToolKind.OTHER.value)))
        except ValueError:
            kind = str(ToolKind.OTHER)
        try:
            status = str(
                ToolCallStatus(state.get("status", ToolCallStatus.PENDING.value))
            )
        except ValueError:
            status = str(ToolCallStatus.PENDING)
        tool_calls.append(
            ToolCallData(
                tool_call_id=call_id,
                title=state.get("title", "unknown_tool"),
                kind=kind,
                status=status,
            )
        )
    return tool_calls


def enrich_snapshot_from_state(
    snapshot: ThreadStateData,
    state: Any,
    aggregator: EventAggregator | None = None,
    expected_assignment_digest: str | None = None,
) -> ThreadStateData:
    """Populate snapshot fields from LangGraph checkpointer state.

    Maps LangChain ``BaseMessage`` objects to ``MessageData`` and
    extracts ``checkpoint_id``, plan, artifacts from the state config.
    Populates agents and pending permissions from the aggregator.
    """
    msgs = _checkpoint_messages(state.values)

    checkpoint_id: str | None = None
    if hasattr(state, "config") and state.config:
        checkpoint_id = state.config.get("configurable", {}).get("checkpoint_id")

    plan_entries = normalize_plan_entries(state.values.get("current_plan", []))

    artifact_dicts = normalize_artifacts(state.values.get("artifacts", []))
    artifact_data = [ArtifactData(**d) for d in artifact_dicts]

    # Checkpoint-owned descriptors win; the thread-scoped live cache is used
    # only before the first descriptor checkpoint lands.
    agent_data = _checkpoint_agents(snapshot, state.values, aggregator)

    # Extract tool calls from AIMessage.tool_calls. Two shapes reach this
    # loop through the identical field:
    #
    # A genuine LangChain BaseTool/ToolNode call cross-references against a
    # ToolMessage the dispatch produced, since that message is the only
    # place its outcome lives.
    #
    # A provider-internal action (an ACP CLI's own built-in tools; Codex's
    # commandExecution/fileChange/mcpToolCall) never produces a ToolMessage
    # - no ToolNode ever dispatched it - so it fell to the else-PENDING
    # branch below unconditionally, FOREVER, regardless of what it actually
    # did (F17: 15/15 tool calls on a completed run served pending, one of
    # them a policy-rejected command the model narrated as failed). Codex's
    # own model (codex_chat_model._completed_action_chunk) already encodes
    # that item's terminal status/content/locations into its tool_call's
    # args as a deliberate durability move - "parity with a mechanism
    # already proven durable" per that function's own docstring - so args
    # carrying a "status" key is read as that report instead of guessed at
    # via ToolMessage correlation. action_detail_projection/
    # map_action_item_status are the SAME functions streaming.transformer
    # uses for the live stream, so a provider action classifies identically
    # whether read live or reconstructed from a settled run's checkpoint.
    tool_call_data, checkpoint_tc_ids = _checkpoint_tool_calls(state.values)
    if aggregator is not None:
        tool_call_data.extend(
            _live_tool_calls(aggregator, snapshot.thread_id, checkpoint_tc_ids)
        )

    snapshot.messages = msgs
    assignment_digest = state.values.get("model_assignment_digest")
    if expected_assignment_digest is None:
        snapshot.snapshot_complete = False
        snapshot.degraded_reasons.append("incompatible_execution_authority")
    elif assignment_digest == expected_assignment_digest:
        snapshot.model_assignment_digest = expected_assignment_digest
    else:
        snapshot.snapshot_complete = False
        snapshot.degraded_reasons.append(
            "missing_assignment_digest"
            if assignment_digest is None
            else "invalid_assignment_digest"
        )
    snapshot.checkpoint_id = checkpoint_id
    snapshot.plan = plan_entries
    snapshot.artifacts = artifact_data
    snapshot.agents = agent_data
    snapshot.tool_calls = tool_call_data
    return snapshot


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
