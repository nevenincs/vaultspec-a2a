"""Domain snapshot types and pure projection/classification functions.

Layer 1 module — no imports from ``api/`` or ``control/``.  Infrastructure
services in ``control/`` construct these types and delegate classification
to the pure functions defined here.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from ..graph.enums import PermissionType
from .enums import RepairStatus, ThreadStatus
from .models import PlanEntry

__all__ = [
    "CHECKPOINT_ERROR_REPAIR_MAP",
    "PLAN_APPROVAL_PAUSE_CAUSES",
    "TERMINAL_STATUS_MAP",
    "AgentData",
    "ArtifactData",
    "CheckpointProjection",
    "ExecutionStateProjection",
    "ExecutionTaskData",
    "MessageData",
    "PermissionData",
    "PermissionOptionData",
    "ProjectedInterrupt",
    "ThreadStateData",
    "ToolCallData",
    "classify_message_role",
    "classify_permission_pause_reason",
    "derive_message_id",
    "extract_message_timestamp",
    "finalize_snapshot_replay_status",
    "is_permission_event",
    "is_progress_event",
    "is_terminal_event",
    "normalize_artifacts",
    "normalize_plan_entries",
    "project_checkpoint_tuple",
]

# Shared constant — previously duplicated in control/projection.py and
# control/event_handlers.py.
PLAN_APPROVAL_PAUSE_CAUSES: frozenset[str] = frozenset(
    {
        PermissionType.PLAN_APPROVAL.value,
        "plan_approval_request",
    }
)

# DB-CRIT-01: map aggregator outcome strings to ThreadStatus enum values.
TERMINAL_STATUS_MAP: dict[str, str] = {
    ThreadStatus.COMPLETED: ThreadStatus.COMPLETED,
    ThreadStatus.FAILED: ThreadStatus.FAILED,
    ThreadStatus.CANCELLED: ThreadStatus.CANCELLED,
}

# Checkpoint error → repair status mapping.  Used by snapshot replay
# logic to decide which RepairStatus to assign when a checkpoint probe
# fails or returns degraded data.
CHECKPOINT_ERROR_REPAIR_MAP: dict[str, RepairStatus] = {
    "checkpoint_unavailable": RepairStatus.CHECKPOINT_UNAVAILABLE,
    "checkpoint_missing": RepairStatus.CHECKPOINT_UNAVAILABLE,
    "checkpoint_corrupt": RepairStatus.OPERATOR_INTERVENTION_REQUIRED,
    "checkpoint_timeout": RepairStatus.NEEDS_RECONCILIATION,
}

_PROGRESS_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "agent_status",
        "message_chunk",
        "tool_call_start",
        "tool_call_update",
        "plan_update",
        "artifact_update",
    }
)


# ---------------------------------------------------------------------------
# Event classification predicates (extracted from control/event_handlers.py)
# ---------------------------------------------------------------------------


def is_terminal_event(payload: dict[str, Any]) -> bool:
    """Return True if the payload represents a thread-terminal event."""
    return (
        payload.get("event_type") == "thread_terminal"
        and payload.get("status", "") in TERMINAL_STATUS_MAP
    )


def is_permission_event(payload: dict[str, Any]) -> bool:
    """Return True if the payload is a permission request or resolution."""
    return payload.get("type", "") in {"permission_request", "permission_resolved"}


def is_progress_event(payload: dict[str, Any]) -> bool:
    """Return True if the payload represents post-resume worker progress."""
    return payload.get("type", "") in _PROGRESS_EVENT_TYPES


def classify_permission_pause_reason(tool_call: str | None) -> str:
    """Derive the ``pause_reason_type`` string from a permission tool_call."""
    if tool_call == "plan_approval":
        return "plan_approval_request"
    return str(tool_call or "permission_request")


@dataclass(slots=True)
class ProjectedInterrupt:
    """Normalized persisted interrupt extracted from a checkpoint tuple."""

    interrupt_id: str
    interrupt_type: str
    payload: dict[str, Any]


@dataclass(slots=True)
class CheckpointProjection:
    """Gateway-side normalized checkpoint projection."""

    channel_values: dict[str, Any]
    config: dict[str, Any]
    checkpoint_id: str | None
    checkpoint_created_at: datetime | None
    checkpoint_parent_id: str | None = None
    checkpoint_source: str | None = None
    checkpoint_step: int | None = None
    checkpoint_updated_channels: list[str] = field(default_factory=list)
    pending_write_channels: list[str] = field(default_factory=list)
    pending_write_count: int = 0
    history_depth: int | None = None
    pause_cause: str | None = None
    pending_interrupts: list[ProjectedInterrupt] = field(default_factory=list)
    degraded_reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ExecutionStateProjection:
    """Normalized durable execution-state read model."""

    checkpoint_id: str | None
    parent_checkpoint_id: str | None
    recovery_epoch: int
    task_count: int
    interrupt_count: int
    next_nodes: list[str] = field(default_factory=list)
    interrupt_types: list[str] = field(default_factory=list)
    execution_tasks: list[ExecutionTaskData] = field(default_factory=list)
    degraded_reasons: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# D-12: Layer 1 snapshot dataclasses mirroring api/schemas/snapshots Pydantic
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class MessageData:
    """Layer 1 equivalent of ``MessageSnapshot``."""

    message_id: str
    role: str
    content: str
    timestamp: datetime
    agent_id: str | None = None


@dataclass(slots=True)
class ToolCallData:
    """Layer 1 equivalent of ``ToolCallSnapshot``."""

    tool_call_id: str
    title: str
    kind: str
    status: str
    locations: list[Any] = field(default_factory=list)
    content: list[Any] = field(default_factory=list)


@dataclass(slots=True)
class ArtifactData:
    """Layer 1 equivalent of ``ArtifactSnapshot``."""

    artifact_id: str
    filename: str
    content: str
    complete: bool


@dataclass(slots=True)
class PermissionOptionData:
    """Layer 1 equivalent of ``_PermissionOptionSnapshot``."""

    option_id: str
    name: str
    kind: str


@dataclass(slots=True)
class PermissionData:
    """Layer 1 equivalent of ``_PermissionSnapshot``."""

    request_id: str
    description: str
    options: list[PermissionOptionData] = field(default_factory=list)
    tool_call: str | None = None


@dataclass(slots=True)
class AgentData:
    """Layer 1 equivalent of ``_AgentSnapshot``."""

    agent_id: str
    node_name: str
    state: str
    provider: str | None = None
    model: str | None = None
    role: str = ""
    display_name: str = ""
    description: str = ""


@dataclass(slots=True)
class ExecutionTaskData:
    """Layer 1 equivalent of ``ExecutionTaskSnapshot``."""

    task_id: str
    name: str
    path: list[str] = field(default_factory=list)
    has_error: bool = False
    error_type: str | None = None
    interrupt_ids: list[str] = field(default_factory=list)
    interrupt_types: list[str] = field(default_factory=list)
    has_nested_state: bool = False
    has_result: bool = False


@dataclass(slots=True)
class ThreadStateData:
    """Layer 1 equivalent of ``ThreadStateSnapshot``."""

    thread_id: str
    status: str
    last_sequence: int
    messages: list[MessageData] = field(default_factory=list)
    tool_calls: list[ToolCallData] = field(default_factory=list)
    pending_permissions: list[PermissionData] = field(default_factory=list)
    artifacts: list[ArtifactData] = field(default_factory=list)
    plan: list[PlanEntry] = field(default_factory=list)
    agents: list[AgentData] = field(default_factory=list)
    checkpoint_id: str | None = None
    checkpoint_created_at: datetime | None = None
    checkpoint_parent_id: str | None = None
    checkpoint_source: str | None = None
    checkpoint_step: int | None = None
    checkpoint_updated_channels: list[str] = field(default_factory=list)
    pending_write_channels: list[str] = field(default_factory=list)
    pending_write_count: int = 0
    history_depth: int | None = None
    next_nodes: list[str] = field(default_factory=list)
    task_count: int = 0
    pending_interrupt_count: int = 0
    execution_tasks: list[ExecutionTaskData] = field(default_factory=list)
    snapshot_complete: bool = True
    degraded_reasons: list[str] = field(default_factory=list)
    replay_status: str = "unknown"
    repair_status: str | None = None
    execution_readiness: str | None = None
    pause_cause: str | None = None
    approval_status: str | None = None
    approval_request_id: str | None = None


# ---------------------------------------------------------------------------
# Pure projection helpers
# ---------------------------------------------------------------------------


def _parse_checkpoint_created_at(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _load_json_list(raw: str | None, *, field_name: str) -> list[Any]:
    if raw is None:
        return []
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = f"Could not decode {field_name}"
        raise ValueError(msg) from exc
    if not isinstance(decoded, list):
        msg = f"{field_name} must decode to a list"
        raise ValueError(msg)
    return decoded


def project_checkpoint_tuple(
    checkpoint_tuple: Any,
    *,
    thread_id: str,
    history_depth: int | None = None,
) -> CheckpointProjection:
    """Project repair-relevant checkpoint data beyond raw channel values."""
    checkpoint = checkpoint_tuple.checkpoint
    metadata = (
        checkpoint_tuple.metadata if isinstance(checkpoint_tuple.metadata, dict) else {}
    )
    parent_config = (
        checkpoint_tuple.parent_config
        if isinstance(checkpoint_tuple.parent_config, dict)
        else {}
    )
    configurable_parent = parent_config.get("configurable", {})
    checkpoint_id = checkpoint.get("id") or checkpoint_tuple.config.get(
        "configurable", {}
    ).get("checkpoint_id")
    projection = CheckpointProjection(
        channel_values=checkpoint.get("channel_values", {}),
        config={"configurable": {"thread_id": thread_id}},
        checkpoint_id=str(checkpoint_id) if checkpoint_id is not None else None,
        checkpoint_created_at=_parse_checkpoint_created_at(checkpoint.get("ts")),
        checkpoint_parent_id=(
            str(configurable_parent.get("checkpoint_id"))
            if configurable_parent.get("checkpoint_id") is not None
            else None
        ),
        checkpoint_source=(
            str(metadata.get("source")) if metadata.get("source") is not None else None
        ),
        checkpoint_step=(
            int(metadata["step"]) if isinstance(metadata.get("step"), int) else None
        ),
        checkpoint_updated_channels=[
            str(channel)
            for channel in checkpoint.get("updated_channels") or []
            if isinstance(channel, str)
        ],
        history_depth=history_depth,
    )
    if projection.checkpoint_id is not None:
        projection.config["configurable"]["checkpoint_id"] = projection.checkpoint_id

    for index, pending_write in enumerate(checkpoint_tuple.pending_writes or []):
        _task_id, channel, value = pending_write
        projection.pending_write_count += 1
        if (
            isinstance(channel, str)
            and channel not in projection.pending_write_channels
        ):
            projection.pending_write_channels.append(channel)
        if channel != "__interrupt__":
            continue
        raw_interrupts = value if isinstance(value, list | tuple) else [value]
        for raw_interrupt in raw_interrupts:
            payload = getattr(raw_interrupt, "value", raw_interrupt)
            if not isinstance(payload, dict):
                if "interrupt_payload_unreadable" not in projection.degraded_reasons:
                    projection.degraded_reasons.append("interrupt_payload_unreadable")
                continue
            interrupt_type = payload.get("type")
            if not isinstance(interrupt_type, str):
                if "interrupt_payload_untyped" not in projection.degraded_reasons:
                    projection.degraded_reasons.append("interrupt_payload_untyped")
                continue
            interrupt_id = str(
                payload.get("request_id")
                or getattr(raw_interrupt, "id", None)
                or f"{projection.checkpoint_id or thread_id}:interrupt:{index}"
            )
            projection.pending_interrupts.append(
                ProjectedInterrupt(
                    interrupt_id=interrupt_id,
                    interrupt_type=interrupt_type,
                    payload=payload,
                )
            )

    if projection.pending_interrupts:
        projection.pause_cause = projection.pending_interrupts[0].interrupt_type

    if projection.history_depth is None:
        projection.degraded_reasons.append("checkpoint_history_unknown")

    return projection


# ---------------------------------------------------------------------------
# Snapshot enrichment pure helpers (extracted from control/snapshot.py)
# ---------------------------------------------------------------------------


def classify_message_role(msg: Any) -> str:
    """Classify a LangChain message into a role string."""
    if isinstance(msg, HumanMessage):
        return "user"
    if isinstance(msg, AIMessage):
        return "assistant"
    if isinstance(msg, ToolMessage):
        return "tool"
    return "system"


def extract_message_timestamp(msg: Any) -> datetime:
    """Extract message timestamp from response metadata; falls back to now()."""
    ts: datetime | None = None
    for meta_src in (
        getattr(msg, "response_metadata", None) or {},
        getattr(msg, "additional_kwargs", None) or {},
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
    return ts


def derive_message_id(role: str, content: str, stored_id: str | None) -> str:
    """Return the stored id or a deterministic hash fallback for deduplication."""
    if stored_id:
        return stored_id
    return hashlib.sha256(f"{role}:{content}".encode()).hexdigest()[:32]


def normalize_plan_entries(plan_raw: list[Any]) -> list[PlanEntry]:
    """Coerce raw plan dicts/objects into ``PlanEntry`` dataclass instances."""
    entries: list[PlanEntry] = []
    for entry in plan_raw:
        if isinstance(entry, dict):
            entries.append(
                PlanEntry(
                    content=entry.get("content", ""),
                    status=entry.get("status", "pending"),
                    priority=entry.get("priority", "medium"),
                )
            )
        elif isinstance(entry, PlanEntry):
            entries.append(entry)
    return entries


def normalize_artifacts(artifacts_raw: list[Any]) -> list[dict[str, Any]]:
    """Coerce raw artifact dicts into normalized dicts with required keys."""
    normalized: list[dict[str, Any]] = []
    for art in artifacts_raw:
        if isinstance(art, dict):
            normalized.append(
                {
                    "artifact_id": art.get("artifact_id", ""),
                    "filename": art.get("filename", ""),
                    "content": art.get("content", ""),
                    "complete": art.get("complete", True),
                }
            )
    return normalized


def finalize_snapshot_replay_status(
    snapshot: Any,
    *,
    checkpoint_loaded: bool,
    checkpoint_present: bool,
    checkpoint_error: bool,
    thread_status: str,
) -> Any:
    """Apply the reconnect snapshot replay/degradation contract.

    Works with any snapshot object that has ``replay_status``,
    ``snapshot_complete``, and ``degraded_reasons`` attributes.
    """
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
        repair = CHECKPOINT_ERROR_REPAIR_MAP["checkpoint_missing"]
        with contextlib.suppress(AttributeError):
            snapshot.repair_status = repair.value
        with contextlib.suppress(AttributeError):
            snapshot.execution_readiness = repair.value
        snapshot.replay_status = "gap_detected"
    return snapshot
