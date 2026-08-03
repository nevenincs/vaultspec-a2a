"""Domain snapshot types and pure projection/classification functions.

Layer 1 module — no imports from ``api/`` or ``control/``.  Infrastructure
services in ``control/`` construct these types and delegate classification
to the pure functions defined here.
"""

from __future__ import annotations

import contextlib
import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from ..graph.enums import AgentLifecycleState, Model, PermissionType, Provider
from .enums import RepairStatus, ThreadStatus, TranscriptAvailability
from .models import PlanEntry

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "CHECKPOINT_ERROR_REPAIR_MAP",
    "CLARIFICATION_REQUEST_INTERRUPT_TYPE",
    "LOCALLY_RESPONDABLE_PAUSE_CAUSES",
    "PLAN_APPROVAL_PAUSE_CAUSES",
    "TERMINAL_STATUS_MAP",
    "WIRE_EVENT_TYPE_KEYS",
    "AgentData",
    "ArtifactData",
    "CheckpointProjection",
    "ClarificationQuestionData",
    "ClarificationRequestData",
    "ExecutionStateProjection",
    "ExecutionTaskData",
    "MessageData",
    "PermissionData",
    "PermissionOptionData",
    "ProjectedInterrupt",
    "ThreadStateData",
    "ToolCallData",
    "build_agent_descriptor",
    "clarification_data_from_interrupt",
    "classify_message_role",
    "classify_permission_pause_reason",
    "classify_transcript_availability",
    "coerce_model",
    "coerce_provider",
    "derive_message_id",
    "extract_message_timestamp",
    "finalize_snapshot_replay_status",
    "is_permission_event",
    "is_progress_event",
    "is_terminal_event",
    "normalize_artifacts",
    "normalize_plan_entries",
    "normalize_wire_event_type",
    "project_checkpoint_tuple",
    "wire_event_type",
]

# The interrupt payload's ``type`` discriminator for a mid-run clarification
# question. Named once here so the projection below and any future
# producer/consumer read the same literal.
CLARIFICATION_REQUEST_INTERRUPT_TYPE = "clarification_request"

# Shared constant — previously duplicated in control/projection.py and
# control/event_handlers.py.
# Verdict-style approval-gate pause causes (as opposed to tool permission pauses):
# the FSM and the served projection classify a pause here whenever its
# resolution carries an approval_status rather than a bare tool option. This is
# a CLASSIFICATION set, not an answerability set — the execution plan-approval
# gate and the document phase gates both park with this shape, so both are
# classified here, but that says nothing about who may ANSWER a document pause
# (see LOCALLY_RESPONDABLE_PAUSE_CAUSES below). Consumed by projection.py,
# permission_fsm.py, and thread_service.py.
PLAN_APPROVAL_PAUSE_CAUSES: frozenset[str] = frozenset(
    {
        PermissionType.PLAN_APPROVAL.value,
        "plan_approval_request",
        "document_approval_request",
    }
)

# The subset of PLAN_APPROVAL_PAUSE_CAUSES this repository's own respond route
# may resolve. Excludes "document_approval_request": that pause is decided
# solely by the engine review surface, correlated back into the run by the
# verdict subscriber (the amended a2a-orchestration-edge contract: no second
# approval authority in A2A). Consumed only by control/permission_service.py's
# respond-route gating.
LOCALLY_RESPONDABLE_PAUSE_CAUSES: frozenset[str] = PLAN_APPROVAL_PAUSE_CAUSES - {
    "document_approval_request"
}

# Map aggregator outcome strings to ThreadStatus enum values.
TERMINAL_STATUS_MAP: dict[str, str] = {
    ThreadStatus.COMPLETED: ThreadStatus.COMPLETED,
    ThreadStatus.FAILED: ThreadStatus.FAILED,
    ThreadStatus.CANCELLED: ThreadStatus.CANCELLED,
}

# Checkpoint error → repair status mapping.  Used by snapshot replay
# logic to decide which RepairStatus to assign when a checkpoint probe
# fails or returns degraded data.
#
# ``checkpoint_missing`` and ``checkpoint_unavailable`` are distinct conditions
# and classify differently. Unavailable means the probe itself failed - the
# checkpoint's contents are unknown, so the run may still be intact. Missing
# means the probe succeeded and found nothing: the history a replay would rebuild
# from is provably absent, which is a replay gap, not an unknown. Collapsing the
# two onto CHECKPOINT_UNAVAILABLE reported a known gap as an unknown probe and
# left REPLAY_GAP with no producer at all.
CHECKPOINT_ERROR_REPAIR_MAP: dict[str, RepairStatus] = {
    "checkpoint_unavailable": RepairStatus.CHECKPOINT_UNAVAILABLE,
    "checkpoint_missing": RepairStatus.REPLAY_GAP,
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
# Wire event-type key pair
# ---------------------------------------------------------------------------

# A relayed event names its type under two keys. ``type`` is the original
# discriminator every wire consumer reads; ``event_type`` is the mirror the
# worker IPC and terminal paths grew alongside it. Both are kept because both
# have live readers, so the pair is stated once here rather than re-derived at
# each producer - three near-copies of the mirroring rule previously disagreed,
# and one of them could not repair a ``type``-only payload at all.
#
# This module is the canonical home because it is the only layer every party can
# reach: ``api/``, ``streaming/``, and ``ipc/`` all import ``thread/``, while
# ``thread/`` (a Layer 1 module) imports none of them. Siting the rule in
# ``streaming/`` instead would invert that edge and make the import cycle
# ``thread`` -> ``streaming`` -> ``streaming.subscribers`` -> ``thread.errors``.
WIRE_EVENT_TYPE_KEYS: tuple[str, str] = ("type", "event_type")


def wire_event_type(payload: Mapping[str, Any]) -> str:
    """Return the event type a relayed payload names, under either key.

    The single read side of the mirrored pair. A consumer that reads one key
    directly classifies a payload written under only the other key as untyped;
    reading through here cannot, whatever path produced the payload.
    """
    for key in WIRE_EVENT_TYPE_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def normalize_wire_event_type(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return *payload* with both wire event-type keys naming its event type.

    The single write side of the mirrored pair, and the seam every producer
    crosses. Mirroring is bidirectional: a payload carrying either key alone
    leaves with both. A payload naming no type at all is returned unchanged
    rather than stamped with an empty one.
    """
    normalized = dict(payload)
    event_type = wire_event_type(normalized)
    if not event_type:
        return normalized
    for key in WIRE_EVENT_TYPE_KEYS:
        normalized[key] = event_type
    return normalized


# ---------------------------------------------------------------------------
# Event classification predicates (extracted from control/event_handlers.py)
# ---------------------------------------------------------------------------


def is_terminal_event(payload: dict[str, Any]) -> bool:
    """Return True if the payload represents a thread-terminal event."""
    return (
        wire_event_type(payload) == "thread_terminal"
        and payload.get("status", "") in TERMINAL_STATUS_MAP
    )


def is_permission_event(payload: dict[str, Any]) -> bool:
    """Return True if the payload is a permission request or resolution."""
    return wire_event_type(payload) in {
        "permission_request",
        "plan_approval_request",
        "document_approval_request",
        "permission_resolved",
    }


def is_progress_event(payload: dict[str, Any]) -> bool:
    """Return True if the payload represents post-resume worker progress."""
    return wire_event_type(payload) in _PROGRESS_EVENT_TYPES


def classify_permission_pause_reason(tool_call: str | None) -> str:
    """Derive the ``pause_reason_type`` string from a permission tool_call."""
    if tool_call == "plan_approval":
        return "plan_approval_request"
    return str(tool_call or "permission_request")


def clarification_data_from_interrupt(
    interrupt: ProjectedInterrupt,
) -> ClarificationRequestData | None:
    """Project a checkpoint-sourced clarification interrupt to its wire shape.

    Returns ``None`` for any interrupt whose type is not
    :data:`CLARIFICATION_REQUEST_INTERRUPT_TYPE`, or whose ``questions`` list
    contains no readable entry — this is checkpoint-truth disclosure: the
    pending clarification survives a reload from
    ``run-status`` alone because it is read from ``ProjectedInterrupt``
    (:func:`project_checkpoint_tuple`), never from in-memory state.

    Malformed questions are dropped rather than failing the projection —
    consistent with the node's own bound-by-truncation discipline — so a
    drifted producer degrades the disclosed set instead of hiding the whole
    request.
    """
    if interrupt.interrupt_type != CLARIFICATION_REQUEST_INTERRUPT_TYPE:
        return None
    payload = interrupt.payload
    if type(payload) is not dict:
        return None
    raw_questions = payload.get("questions", [])
    if not isinstance(raw_questions, list):
        return None
    questions: list[ClarificationQuestionData] = []
    for raw in raw_questions:
        if not isinstance(raw, dict):
            continue
        qid = raw.get("id")
        prompt = raw.get("prompt")
        if (
            not isinstance(qid, str)
            or not qid
            or not isinstance(prompt, str)
            or not prompt
        ):
            continue
        kind = raw.get("kind")
        kind = kind if kind in ("choice", "text") else "text"
        options = raw.get("options", [])
        questions.append(
            ClarificationQuestionData(
                id=qid,
                prompt=prompt,
                kind=kind,
                required=bool(raw.get("required", False)),
                options=[o for o in options if isinstance(o, str)]
                if isinstance(options, list)
                else [],
            )
        )
    if not questions:
        return None
    return ClarificationRequestData(
        request_id=interrupt.interrupt_id,
        questions=questions,
    )


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
# Layer 1 snapshot dataclasses mirroring api/schemas/snapshots Pydantic
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
    tool_kind: str | None = None


@dataclass(slots=True)
class ClarificationQuestionData:
    """Layer 1 equivalent of ``_ClarificationQuestionSnapshot``.

    One bounded question within a pending clarification request.
    """

    id: str
    prompt: str
    kind: str
    required: bool = False
    options: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ClarificationRequestData:
    """Layer 1 equivalent of ``_ClarificationRequestSnapshot``.

    A pending mid-run clarification request. ``request_id`` is the same
    checkpoint-derived interrupt id every other interrupt
    projection uses (:class:`ProjectedInterrupt`), so the respond route's
    ``{run_id}/clarifications/{request_id}/respond`` path segment is exactly
    the id disclosed here.
    """

    request_id: str
    questions: list[ClarificationQuestionData] = field(default_factory=list)


@dataclass(slots=True)
class AgentData:
    """Canonical agent descriptor.

    Single declaration behind every agent-shaped surface: the REST team-status
    entry, the ``team_status`` broadcast summary, and the thread snapshot all
    project from this type rather than redeclaring the field set. ``state``,
    ``provider``, and ``model`` carry the real enums so an unknown value cannot
    survive as an arbitrary string all the way to the wire.
    """

    agent_id: str
    node_name: str
    state: AgentLifecycleState
    provider: Provider | None = None
    model: Model | None = None
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
    pending_clarification: ClarificationRequestData | None = None
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
    # The capped, single-line reason this run last failed, or None (never
    # failed, or the durable record predates the failure_reason column).
    # Sourced straight from the durable threads.failure_reason column — never
    # from a live SSE frame — so a reloaded panel recovers the same reason a
    # connected client already saw (S37 / failure-reason persistence).
    failure_reason: str | None = None
    # The machine-readable counterpart to the reason above: which closed
    # condition the failure resolved to, so a client branches on a value instead
    # of parsing prose that changes whenever a vendor rewords a message. Read
    # from the same durable row and on the same terms - None for a run that
    # never failed, or whose record predates the column.
    provider_condition: str | None = None
    # Why an operation did not take on a run that is STILL ALIVE - an
    # undelivered follow-up or resume - as distinct from why a run FAILED. Its
    # writers decline to set the two fields above precisely because the run
    # survives, so this is the only channel their account has, and a client that
    # rendered it as a failure would report a death that did not happen.
    repair_reason: str | None = None


# ---------------------------------------------------------------------------
# Pure projection helpers
# ---------------------------------------------------------------------------


def coerce_provider(value: object) -> Provider | None:
    """Coerce a node-metadata value to a :class:`Provider`, else ``None``.

    Node metadata is a flat string map, so an agent whose provider was never
    resolved arrives as an empty string or not at all.  Both that case and an
    unrecognised value read as "unknown" rather than reaching the wire as a
    fabricated enum member.
    """
    if isinstance(value, Provider):
        return value
    try:
        return Provider(value)
    except ValueError:
        return None


def coerce_model(value: object) -> Model | None:
    """Coerce a node-metadata value to a :class:`Model` capability, else ``None``."""
    if isinstance(value, Model):
        return value
    try:
        return Model(value)
    except ValueError:
        return None


def build_agent_descriptor(
    summary: Mapping[str, str],
    state: AgentLifecycleState,
) -> AgentData:
    """Project one aggregator node summary onto the canonical descriptor.

    The single seam shared by every agent-listing surface, so a field carried on
    :class:`AgentData` reaches the REST route, the thread snapshot, and the
    broadcast together instead of being wired one caller at a time.
    """
    return AgentData(
        agent_id=summary.get("agent_id") or summary.get("node_name", ""),
        node_name=summary.get("node_name", ""),
        state=state,
        provider=coerce_provider(summary.get("provider")),
        model=coerce_model(summary.get("model")),
        role=summary.get("role", ""),
        display_name=summary.get("display_name", ""),
        description=summary.get("description", ""),
    )


def _parse_checkpoint_created_at(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _extract_checkpoint_fields(
    checkpoint_tuple: Any,
    *,
    thread_id: str,
    history_depth: int | None,
) -> CheckpointProjection:
    """Extract the immutable per-checkpoint fields into a base projection.

    Reads only the checkpoint, its metadata, and its parent config - the values
    that describe the checkpoint itself, not the pending work layered on it. The
    pending-write fold is a separate stage so the two concerns read apart.
    """
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
    return projection


def _fold_pending_writes(
    projection: CheckpointProjection,
    checkpoint_tuple: Any,
    *,
    thread_id: str,
) -> None:
    """Fold the checkpoint's pending writes onto a base projection in place.

    This is the response-shaping stage: it counts pending writes, records their
    channels, decodes interrupt payloads into projected interrupts, and marks the
    degraded reasons a malformed interrupt surfaces. It mutates *projection*
    rather than returning a new one, because the base fields it builds on are
    already correct and only the pending-work view is being added.
    """
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


def project_checkpoint_tuple(
    checkpoint_tuple: Any,
    *,
    thread_id: str,
    history_depth: int | None = None,
) -> CheckpointProjection:
    """Project repair-relevant checkpoint data beyond raw channel values.

    Two stages: extract the immutable per-checkpoint fields, then fold the
    pending-write and interrupt view onto them. The split keeps the checkpoint's
    own description separate from the pending work layered on it, so each reads
    and tests apart.
    """
    projection = _extract_checkpoint_fields(
        checkpoint_tuple, thread_id=thread_id, history_depth=history_depth
    )
    _fold_pending_writes(projection, checkpoint_tuple, thread_id=thread_id)
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


# The only statuses a run can hold before its first checkpoint exists: it is
# marked running on dispatch, and can be cancelled during that same window. An
# absent checkpoint in any OTHER status means the record was lost, not unwritten.
_PRE_TRANSCRIPT_STATUSES: frozenset[str] = frozenset(
    {
        ThreadStatus.SUBMITTED.value,
        ThreadStatus.RUNNING.value,
        ThreadStatus.CANCELLING.value,
    }
)


def classify_transcript_availability(
    *,
    checkpoint_loaded: bool,
    checkpoint_present: bool,
    checkpoint_error: bool,
    thread_status: str,
) -> TranscriptAvailability:
    """Classify whether a run's conversation is readable from its checkpoint.

    Takes the SAME four facts as :func:`finalize_snapshot_replay_status` and
    sits beside it deliberately: both answer from one checkpoint read, and
    splitting them across modules would let the replay verdict and the
    transcript verdict drift out of agreement on the same run.

    Distinct from the replay verdict rather than derived from it. Replay status
    answers "can this run resume", which folds the not-yet-dispatched case and
    an unreadable checkpoint store together under ``unknown``. Those are
    opposite answers to "is the transcript lost": one is a run that has said
    nothing yet, the other is a record we cannot read.

    Absence is excused ONLY in the states a run can legitimately reach before
    its first checkpoint write, and that window is real: a run is marked running
    the moment it dispatches, well before the worker writes anything, and it can
    be cancelled inside that window. Calling ordinary startup a loss would fire
    the signal on healthy traffic and teach every reader to ignore it.

    Every other state is held to owe a transcript, including the states that are
    still "active". A run parked on an interrupt was checkpointed to park, and a
    run in a recovery state advanced far enough for recovery to be needed, so an
    absent checkpoint there is a loss and not a run that has yet to speak -
    excusing those would soft-pedal exactly the cases most likely to BE the
    loss.
    """
    if checkpoint_loaded:
        return TranscriptAvailability.AVAILABLE
    if checkpoint_error or checkpoint_present:
        # ``checkpoint_present`` without ``checkpoint_loaded`` means the tuple
        # was read but its projection raised: the record exists and this reader
        # could not render it, which is unreadable, not missing.
        return TranscriptAvailability.UNREADABLE
    if thread_status in _PRE_TRANSCRIPT_STATUSES:
        return TranscriptAvailability.NOT_YET_RECORDED
    return TranscriptAvailability.MISSING


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
