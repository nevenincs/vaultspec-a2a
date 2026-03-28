"""Snapshot enrichment business logic extracted from api/endpoints.py."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, ToolMessage

from ..graph.enums import (
    AgentLifecycleState,
    PermissionOptionKind,
    ToolCallStatus,
    ToolKind,
)
from ..streaming.aggregator import EventAggregator, classify_tool_kind
from ..thread.snapshots import (
    AgentData,
    ArtifactData,
    MessageData,
    PermissionData,
    PermissionOptionData,
    ThreadStateData,
    ToolCallData,
    classify_message_role,
    derive_message_id,
    extract_message_timestamp,
    normalize_artifacts,
    normalize_plan_entries,
)

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig

    from ..database.checkpoints import Checkpointer


def enrich_snapshot_from_state(
    snapshot: ThreadStateData,
    state: Any,
    aggregator: EventAggregator | None = None,
) -> ThreadStateData:
    """Populate snapshot fields from LangGraph checkpointer state.

    Maps LangChain ``BaseMessage`` objects to ``MessageData`` and
    extracts ``checkpoint_id``, plan, artifacts from the state config.
    Populates agents and pending permissions from the aggregator.
    """
    msgs: list[MessageData] = []
    for m in state.values.get("messages", []):
        role = classify_message_role(m)
        content = m.content if isinstance(m.content, str) else str(m.content)
        ts = extract_message_timestamp(m)
        stored_id: str | None = getattr(m, "id", None)
        message_id = derive_message_id(role, content, stored_id)
        msgs.append(
            MessageData(
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

    plan_entries = normalize_plan_entries(state.values.get("current_plan", []))

    artifact_dicts = normalize_artifacts(state.values.get("artifacts", []))
    artifact_data = [ArtifactData(**d) for d in artifact_dicts]

    # Populate agents from aggregator node summaries + agent states
    agent_data: list[AgentData] = []
    if aggregator is not None:
        node_summaries = aggregator.get_node_summaries()
        agent_states = aggregator.get_agent_states()
        for node in node_summaries:
            agent_id = node.get("agent_id", node.get("node_name", ""))
            agent_data.append(
                AgentData(
                    agent_id=agent_id,
                    node_name=node.get("node_name", ""),
                    state=str(agent_states.get(agent_id, AgentLifecycleState.IDLE)),
                    role=node.get("role", ""),
                    display_name=node.get("display_name", ""),
                    description=node.get("description", ""),
                )
            )

    # Populate pending permissions from aggregator
    perm_data: list[PermissionData] = []
    if aggregator is not None:
        thread_id = snapshot.thread_id
        for perm in aggregator.get_pending_permissions(thread_id):
            perm_data.append(
                PermissionData(
                    request_id=perm.request_id,
                    description=perm.description,
                    tool_call=perm.tool_call,
                    options=[
                        PermissionOptionData(
                            option_id=opt.get("option_id", ""),
                            name=opt.get("name", ""),
                            kind=str(
                                PermissionOptionKind(opt.get("kind", "allow_once"))
                            ),
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
    tool_call_data: list[ToolCallData] = []
    checkpoint_tc_ids: set[str] = set()
    for m in state.values.get("messages", []):
        if isinstance(m, AIMessage) and m.tool_calls:
            for tc in m.tool_calls:
                tc_id = tc.get("id", "")
                tc_name = tc.get("name", "unknown_tool")
                checkpoint_tc_ids.add(tc_id)
                tool_call_data.append(
                    ToolCallData(
                        tool_call_id=tc_id,
                        title=tc_name,
                        kind=str(classify_tool_kind(tc_name)),
                        status=str(
                            ToolCallStatus.COMPLETED
                            if tc_id in answered_tool_ids
                            else ToolCallStatus.PENDING
                        ),
                    )
                )

    # F-38: Merge tool calls from aggregator in-memory state for tool calls
    # not present in the checkpoint.
    if aggregator is not None:
        thread_id = snapshot.thread_id
        aggregator_tc_states = aggregator.get_tool_call_states(thread_id)
        for tc_id, tc_state in aggregator_tc_states.items():
            if tc_id in checkpoint_tc_ids:
                continue
            try:
                kind = str(ToolKind(tc_state.get("kind", ToolKind.OTHER.value)))
            except ValueError:
                kind = str(ToolKind.OTHER)
            try:
                status = str(
                    ToolCallStatus(tc_state.get("status", ToolCallStatus.PENDING.value))
                )
            except ValueError:
                status = str(ToolCallStatus.PENDING)
            tool_call_data.append(
                ToolCallData(
                    tool_call_id=tc_id,
                    title=tc_state.get("title", "unknown_tool"),
                    kind=kind,
                    status=status,
                )
            )

    snapshot.messages = msgs
    snapshot.checkpoint_id = checkpoint_id
    snapshot.plan = plan_entries
    snapshot.artifacts = artifact_data
    snapshot.agents = agent_data
    snapshot.pending_permissions = perm_data
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
