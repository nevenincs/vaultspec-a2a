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
from typing import TYPE_CHECKING, Any, cast

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.base import WRITES_IDX_MAP
from langgraph.checkpoint.serde.types import INTERRUPT

from ..graph.enums import (
    AgentLifecycleState,
    PermissionType,
    Provider,
    StreamFrameKind,
)
from .enums import (
    TERMINAL_STATUS_VALUES,
    DegradedReason,
    InterruptType,
    RepairStatus,
    ReplayStatus,
    ThreadStatus,
    TranscriptAvailability,
)
from .models import PlanEntry

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from .clarification import ClarificationRequest

__all__ = [
    "LOCALLY_RESPONDABLE_PAUSE_CAUSES",
    "PERMISSION_REQUEST_EVENT_TYPES",
    "PLAN_APPROVAL_PAUSE_CAUSES",
    "AgentData",
    "ArtifactData",
    "CheckpointProjection",
    "ExecutionStateProjection",
    "ExecutionTaskData",
    "LiveInterrupt",
    "MessageData",
    "PermissionData",
    "PermissionOptionData",
    "ProjectedInterrupt",
    "ThreadStateData",
    "ToolCallData",
    "build_agent_descriptor",
    "classify_message_role",
    "classify_permission_pause_reason",
    "classify_transcript_availability",
    "coerce_provider",
    "derive_message_id",
    "extract_checkpoint_fields",
    "extract_message_timestamp",
    "finalize_snapshot_replay_status",
    "fold_pending_writes",
    "is_permission_event",
    "is_terminal_event",
    "live_interrupts",
    "named_request_id",
    "normalize_artifacts",
    "normalize_plan_entries",
    "normalize_wire_event_type",
    "project_checkpoint_tuple",
    "record_repair_posture",
    "stamp_message_created_at",
    "tasks_past_their_interrupt",
    "unanswered_interrupt_values",
    "wire_event_type",
]

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
        InterruptType.PLAN_APPROVAL_REQUEST.value,
        InterruptType.DOCUMENT_APPROVAL_REQUEST.value,
    }
)

# The subset of PLAN_APPROVAL_PAUSE_CAUSES this repository's own respond route
# may resolve. Excludes the document approval pause: that pause is decided
# solely by the engine review surface, correlated back into the run by the
# verdict subscriber (the amended a2a-orchestration-edge contract: no second
# approval authority in A2A). Consumed only by control/permission_service.py's
# respond-route gating.
LOCALLY_RESPONDABLE_PAUSE_CAUSES: frozenset[str] = PLAN_APPROVAL_PAUSE_CAUSES - {
    InterruptType.DOCUMENT_APPROVAL_REQUEST.value
}

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
        wire_event_type(payload) == StreamFrameKind.THREAD_TERMINAL
        and payload.get("status", "") in TERMINAL_STATUS_VALUES
    )


#: The relayed event types that open a durable permission pause: a tool
#: permission and the two approval gates. A clarification is the one interrupt
#: type absent, because it parks the run without a permission row.
PERMISSION_REQUEST_EVENT_TYPES: frozenset[str] = frozenset(
    {
        InterruptType.PERMISSION_REQUEST.value,
        InterruptType.PLAN_APPROVAL_REQUEST.value,
        InterruptType.DOCUMENT_APPROVAL_REQUEST.value,
    }
)


def is_permission_event(payload: dict[str, Any]) -> bool:
    """Return True if the payload is a permission request or resolution."""
    event_type = wire_event_type(payload)
    return (
        event_type in PERMISSION_REQUEST_EVENT_TYPES
        or event_type == "permission_resolved"
    )


def classify_permission_pause_reason(tool_call: str | None) -> str:
    """Derive the ``pause_reason_type`` string from a permission tool_call."""
    if tool_call == PermissionType.PLAN_APPROVAL:
        return InterruptType.PLAN_APPROVAL_REQUEST.value
    return str(tool_call or InterruptType.PERMISSION_REQUEST.value)


@dataclass(slots=True)
class ProjectedInterrupt:
    """Normalized persisted interrupt extracted from a checkpoint tuple.

    ``interrupt_id`` is the request id the producer named the question by, the
    same id the stream discloses it under and an answer is addressed to.
    """

    interrupt_id: str
    interrupt_type: str
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LiveInterrupt:
    """One question a run's live state shows it still stopped on.

    Read off a LangGraph state snapshot rather than a checkpoint tuple, so it
    keeps what only the snapshot knows: the task that asked, under its node
    name, and LangGraph's own ``interrupt_id``, which is how an answer is
    addressed while more than one question is pending. ``request_id`` is the id
    the producer named the question by, ``None`` when the payload names none;
    such a question cannot be matched to an answer.
    """

    task_id: str
    task_name: str
    interrupt_id: str | None
    interrupt_type: str | None
    request_id: str | None
    payload: dict[str, Any] | None


@dataclass(slots=True)
# Flat projection matches the durable checkpoint read model.
class CheckpointProjection:  # pylint: disable=too-many-instance-attributes
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
    # The types of the held interrupts that name no request. None is disclosed,
    # because no answer can be addressed to one, but a run stopped on such a
    # question is still stopped, so a reader can tell what kind holds it.
    unnamed_interrupt_types: list[str] = field(default_factory=list)
    # Every observation, once per occurrence; merging onto a snapshot dedupes.
    degraded_reasons: list[DegradedReason] = field(default_factory=list)


@dataclass(slots=True)
# Flat projection matches the execution-state response model.
class ExecutionStateProjection:  # pylint: disable=too-many-instance-attributes
    """Normalized durable execution-state read model."""

    task_count: int
    interrupt_count: int
    next_nodes: list[str] = field(default_factory=list)
    execution_tasks: list[ExecutionTaskData] = field(default_factory=list)
    degraded_reasons: list[DegradedReason] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Layer 1 snapshot dataclasses mirroring api/schemas/snapshots Pydantic
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class MessageData:
    """Layer 1 equivalent of ``MessageSnapshot``."""

    message_id: str
    role: str
    content: str
    # None when the message carries no production time: an older run's
    # history, recorded before messages were stamped.
    timestamp: datetime | None
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
    """Layer 1 equivalent of ``PermissionOptionSnapshot``."""

    option_id: str
    name: str
    kind: str


@dataclass(slots=True)
class PermissionData:
    """Layer 1 equivalent of ``PermissionSnapshot``."""

    request_id: str
    description: str
    options: list[PermissionOptionData] = field(default_factory=list)
    tool_call: str | None = None
    tool_kind: str | None = None


@dataclass(slots=True)
# Flat data mirrors the public agent snapshot schema.
class AgentData:  # pylint: disable=too-many-instance-attributes
    """Canonical agent descriptor.

    Single declaration behind every agent-shaped surface: the REST team-status
    entry, the ``team_status`` broadcast summary, and the thread snapshot all
    project from this type rather than redeclaring the field set. ``state``,
    ``provider``, and ``model`` carry the real enums so an unknown value cannot
    survive as an arbitrary string all the way to the wire.

    ``model_name`` holds the exact provider-issued catalog identifier the run
    executed.
    """

    thread_id: str
    agent_id: str
    node_name: str
    state: AgentLifecycleState
    provider: Provider | None = None
    model_name: str | None = None
    role: str = ""
    display_name: str = ""
    description: str = ""


@dataclass(slots=True)
# Flat data mirrors the public task snapshot schema.
class ExecutionTaskData:  # pylint: disable=too-many-instance-attributes
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
# Flat data mirrors the public thread snapshot schema.
class ThreadStateData:  # pylint: disable=too-many-instance-attributes
    """Layer 1 equivalent of ``ThreadStateSnapshot``."""

    thread_id: str
    status: str
    last_sequence: int
    messages: list[MessageData] = field(default_factory=list)
    tool_calls: list[ToolCallData] = field(default_factory=list)
    pending_permissions: list[PermissionData] = field(default_factory=list)
    # The questionnaire the run is parked on, read once from the checkpoint
    # projection as the producer's own model, so every surface serving this
    # snapshot discloses the same bounded request run-status does.
    pending_clarification: ClarificationRequest | None = None
    artifacts: list[ArtifactData] = field(default_factory=list)
    plan: list[PlanEntry] = field(default_factory=list)
    agents: list[AgentData] = field(default_factory=list)
    model_assignment_digest: str | None = None
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
    degraded_reasons: list[DegradedReason] = field(default_factory=list)
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
    # connected client already saw.
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
    # How many follow-up turns this run is holding behind the one it is
    # running. Counted from the durable journal, never from a stream: a client
    # that reloaded without one has no other way to learn that a turn it sent
    # is still waiting, and the quiet boundary between two turns looks exactly
    # like a run that has gone idle. Bounded by the configured per-run depth.
    queued_messages: int = 0


# ---------------------------------------------------------------------------
# Pure projection helpers
# ---------------------------------------------------------------------------


def record_repair_posture(snapshot: ThreadStateData, posture: str | None) -> None:
    """Set *snapshot*'s repair posture together with the readiness it implies.

    Readiness is never judged on its own: a run is as fit to resume as its
    repair posture says, so every write of the posture writes the served
    readiness with it and the two cannot disagree.
    """
    snapshot.repair_status = posture
    snapshot.execution_readiness = posture


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


def build_agent_descriptor(
    summary: Mapping[str, str],
    state: AgentLifecycleState,
    *,
    thread_id: str,
) -> AgentData:
    """Project one aggregator node summary onto the canonical descriptor.

    The single seam shared by every agent-listing surface, so a field carried on
    :class:`AgentData` reaches the REST route, the thread snapshot, and the
    broadcast together instead of being wired one caller at a time.
    """
    return AgentData(
        thread_id=thread_id,
        agent_id=summary.get("agent_id") or summary.get("node_name", ""),
        node_name=summary.get("node_name", ""),
        state=state,
        provider=coerce_provider(summary.get("provider")),
        model_name=summary.get("model_name") or None,
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


def _object_dict(value: object) -> dict[str, object]:
    return cast("dict[str, object]", value) if isinstance(value, dict) else {}


def extract_checkpoint_fields(
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
    checkpoint = _object_dict(checkpoint_tuple.checkpoint)
    metadata = _object_dict(checkpoint_tuple.metadata)
    parent_config = _object_dict(checkpoint_tuple.parent_config)
    configurable_parent = _object_dict(parent_config.get("configurable", {}))
    config = _object_dict(checkpoint_tuple.config)
    config_configurable = _object_dict(config.get("configurable", {}))
    checkpoint_id: object = checkpoint.get("id") or config_configurable.get(
        "checkpoint_id"
    )
    channel_values = cast(
        "dict[str, Any]", _object_dict(checkpoint.get("channel_values", {}))
    )
    # The parent the checkpoint records, which is not the same as a parent that
    # still exists: a settled run's superseded history is pruned and this
    # reference outlives it. Carried through as recorded, and the served field
    # says so rather than this projection guessing at what is still stored.
    parent_checkpoint_id_raw = configurable_parent.get("checkpoint_id")
    checkpoint_source_raw = metadata.get("source")
    checkpoint_step_raw = metadata.get("step")
    projection = CheckpointProjection(
        channel_values=channel_values,
        config={"configurable": {"thread_id": thread_id}},
        checkpoint_id=str(checkpoint_id) if checkpoint_id is not None else None,
        checkpoint_created_at=_parse_checkpoint_created_at(checkpoint.get("ts")),
        checkpoint_parent_id=(
            str(parent_checkpoint_id_raw)
            if parent_checkpoint_id_raw is not None
            else None
        ),
        checkpoint_source=(
            str(checkpoint_source_raw) if checkpoint_source_raw is not None else None
        ),
        checkpoint_step=(
            checkpoint_step_raw if isinstance(checkpoint_step_raw, int) else None
        ),
        checkpoint_updated_channels=[
            str(channel)
            for channel in cast(
                "list[object]", checkpoint.get("updated_channels") or []
            )
            if isinstance(channel, str)
        ],
        history_depth=history_depth,
    )
    if projection.checkpoint_id is not None:
        projection.config["configurable"]["checkpoint_id"] = projection.checkpoint_id
    return projection


#: The channels a saver holds in a fixed slot per task rather than appending:
#: what the loop records ABOUT a task - the interrupt it raised, the resume
#: values it consumed, its error, its schedule. Every other write in a task's
#: set is output the task itself produced, down to the marker meaning "ended
#: with nothing to say".
_TASK_BOOKKEEPING_CHANNELS = frozenset(WRITES_IDX_MAP)


def _held_write_entries(pending_writes: Iterable[Any]) -> list[Sequence[object]]:
    """Return the held writes shaped as ``(task_id, channel, value)``.

    Durable storage is untrusted, so a write of any other shape is skipped
    rather than unpacked.
    """
    entries: list[Sequence[object]] = []
    for write in pending_writes or ():
        entry: Sequence[object] = (
            cast("Sequence[object]", write) if isinstance(write, tuple | list) else ()
        )
        if len(entry) == 3:
            entries.append(entry)
    return entries


def tasks_past_their_interrupt(pending_writes: Iterable[Any]) -> frozenset[str]:
    """Return the tasks whose held interrupt is a leftover, not a live question.

    A task's interrupt write is never cleared when the answer lets that task
    run on. With work fanned out, the superstep another branch is still parked
    in has not committed, so the answered branch's interrupt stays in the
    checkpoint beside the output its node produced afterwards. Every reader of
    the held interrupts then sees a question that has been answered, and
    re-asks it - or admits its answer a second time.

    A task that produced output is the one that got past its question. A task
    holding only bookkeeping has not: it is stopped at an interrupt, or it
    consumed an answer and asked again, or it failed before finishing, and all
    three are still waiting. A malformed write says nothing either way and is
    skipped, leaving its task reading as waiting - the direction that keeps
    disclosing a question rather than hiding one.
    """
    finished: set[str] = set()
    for entry in _held_write_entries(pending_writes):
        task_id, channel = entry[0], entry[1]
        if (
            isinstance(task_id, str)
            and isinstance(channel, str)
            and channel not in _TASK_BOOKKEEPING_CHANNELS
        ):
            finished.add(task_id)
    return frozenset(finished)


def unanswered_interrupt_values(pending_writes: Iterable[Any]) -> list[object]:
    """Return the held interrupt writes of the tasks still asking their question.

    The one reading of a checkpoint's held writes as questions: an interrupt
    write whose task has since run past it (:func:`tasks_past_their_interrupt`)
    is a leftover, not a pause. Each value is the write as held - one interrupt
    or a sequence of them. A malformed write is skipped.
    """
    entries = _held_write_entries(pending_writes)
    answered = tasks_past_their_interrupt(entries)
    return [
        entry[2]
        for entry in entries
        if entry[1] == INTERRUPT and entry[0] not in answered
    ]


def named_request_id(value: object) -> str | None:
    """Return the non-empty ``request_id`` *value* names, or ``None``.

    An interrupt payload names the request it asks under this key, and a resume
    value names the request it answers under the same one. One reader keeps the
    question and its answer from disagreeing about what counts as naming a
    request; there is no fallback identity, because a question its producer did
    not name cannot be matched to any answer.
    """
    if not isinstance(value, dict):
        return None
    named = cast("dict[str, object]", value).get("request_id")
    return named if isinstance(named, str) and named else None


def _interrupt_payload(raw_interrupt: object) -> dict[str, Any] | None:
    """Return the mapping payload a LangGraph interrupt carries, if it has one."""
    payload: object = getattr(raw_interrupt, "value", raw_interrupt)
    return cast("dict[str, Any]", payload) if isinstance(payload, dict) else None


def live_interrupts(
    state: object, held_writes: Iterable[Any]
) -> tuple[LiveInterrupt, ...]:
    """Return the questions a run's live state is still stopped on, task by task.

    *state* is a LangGraph state snapshot. Its tasks list every interrupt write
    the checkpoint holds against them, including one a fanned-out branch has
    already answered and run past: the superstep that would clear it cannot
    commit while another branch is parked. *held_writes*, the writes the store
    holds against the snapshot's checkpoint, are the only thing that tells the
    two apart, so a task they show finished contributes nothing. Without them
    every listed interrupt reads as open, which is the snapshot's own reading.
    """
    answered = tasks_past_their_interrupt(held_writes)
    found: list[LiveInterrupt] = []
    for task in getattr(state, "tasks", None) or ():
        task_id = str(getattr(task, "id", ""))
        if task_id in answered:
            continue
        task_name = str(getattr(task, "name", ""))
        for raw_interrupt in getattr(task, "interrupts", None) or ():
            payload = _interrupt_payload(raw_interrupt)
            raw_id: object = getattr(raw_interrupt, "id", None)
            raw_type: object = payload.get("type") if payload is not None else None
            found.append(
                LiveInterrupt(
                    task_id=task_id,
                    task_name=task_name,
                    interrupt_id=raw_id if isinstance(raw_id, str) and raw_id else None,
                    interrupt_type=raw_type if isinstance(raw_type, str) else None,
                    request_id=named_request_id(payload),
                    payload=payload,
                )
            )
    return tuple(found)


def _project_pending_interrupt(
    projection: CheckpointProjection, raw_interrupt: object
) -> None:
    payload = _interrupt_payload(raw_interrupt)
    if payload is None:
        projection.degraded_reasons.append(DegradedReason.INTERRUPT_PAYLOAD_UNREADABLE)
        return
    interrupt_type = payload.get("type")
    if not isinstance(interrupt_type, str):
        projection.degraded_reasons.append(DegradedReason.INTERRUPT_PAYLOAD_UNTYPED)
        return
    request_id = named_request_id(payload)
    if request_id is None:
        # Every producer names its question; one that does not cannot be
        # answered, so it is not disclosed as a pause anyone could resolve.
        projection.degraded_reasons.append(DegradedReason.INTERRUPT_PAYLOAD_UNREADABLE)
        projection.unnamed_interrupt_types.append(interrupt_type)
        return
    projection.pending_interrupts.append(
        ProjectedInterrupt(
            interrupt_id=request_id,
            interrupt_type=interrupt_type,
            payload=payload,
        )
    )


def _record_pending_channel(projection: CheckpointProjection, channel: object) -> None:
    """Record one held write's channel, once, on the projection."""
    if isinstance(channel, str) and channel not in projection.pending_write_channels:
        projection.pending_write_channels.append(channel)


def _project_write_interrupts(projection: CheckpointProjection, value: object) -> None:
    """Project every interrupt one held interrupt write carries.

    A single write holds either one interrupt or a sequence of them, so the
    value is normalized to a sequence before any of it is projected.
    """
    raw_interrupts: list[object] = (
        list(cast("list[object] | tuple[object, ...]", value))
        if isinstance(value, list | tuple)
        else [value]
    )
    for raw_interrupt in raw_interrupts:
        _project_pending_interrupt(projection, raw_interrupt)


def fold_pending_writes(
    projection: CheckpointProjection, checkpoint_tuple: Any
) -> None:
    """Fold the checkpoint's pending writes onto a base projection in place.

    This is the response-shaping stage: it counts pending writes, records their
    channels, decodes interrupt payloads into projected interrupts, and marks the
    degraded reasons a malformed interrupt surfaces. It mutates *projection*
    rather than returning a new one, because the base fields it builds on are
    already correct and only the pending-work view is being added.
    """
    pending_writes: list[tuple[object, object, object]] = (
        checkpoint_tuple.pending_writes or []
    )
    # Every held write is counted and its channel recorded: those describe the
    # checkpoint. Only the questions are narrowed, to the tasks still asking.
    for _task_id, channel, _value in pending_writes:
        projection.pending_write_count += 1
        _record_pending_channel(projection, channel)
    for value in unanswered_interrupt_values(pending_writes):
        _project_write_interrupts(projection, value)

    if projection.pending_interrupts:
        projection.pause_cause = projection.pending_interrupts[0].interrupt_type

    if projection.history_depth is None:
        projection.degraded_reasons.append(DegradedReason.CHECKPOINT_HISTORY_UNKNOWN)


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
    projection = extract_checkpoint_fields(
        checkpoint_tuple, thread_id=thread_id, history_depth=history_depth
    )
    fold_pending_writes(projection, checkpoint_tuple)
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


#: The metadata key a produced message records its production time under.
MESSAGE_CREATED_AT_KEY = "created_at"


def stamp_message_created_at(msg: Any, *, at: datetime | None = None) -> Any:
    """Record when *msg* was produced, unless it already says.

    Kept in ``response_metadata``, which the message carries through the
    checkpoint but no provider integration sends back to a model.
    """
    metadata: object = getattr(msg, "response_metadata", None)
    if isinstance(metadata, dict) and MESSAGE_CREATED_AT_KEY not in metadata:
        cast("dict[str, object]", metadata)[MESSAGE_CREATED_AT_KEY] = (
            at or datetime.now(UTC)
        ).isoformat()
    return msg


def extract_message_timestamp(msg: Any) -> datetime | None:
    """Return when *msg* was produced, or ``None`` when it does not say.

    The time a projection happens to read the message is not when it was
    produced, so an unstamped message reports no time rather than that one.
    """
    ts: datetime | None = None
    response_metadata_raw: object = getattr(msg, "response_metadata", None) or {}
    additional_kwargs_raw: object = getattr(msg, "additional_kwargs", None) or {}
    for meta_src_raw in (response_metadata_raw, additional_kwargs_raw):
        meta_src = (
            cast("dict[str, object]", meta_src_raw)
            if isinstance(meta_src_raw, dict)
            else {}
        )
        raw_ts: object = meta_src.get(MESSAGE_CREATED_AT_KEY) or meta_src.get(
            "timestamp"
        )
        if isinstance(raw_ts, datetime):
            ts = raw_ts
            break
        if isinstance(raw_ts, str):
            with contextlib.suppress(ValueError):
                ts = datetime.fromisoformat(raw_ts)
            if ts is not None:
                break
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
            entry_map = cast("dict[str, object]", entry)
            content = entry_map.get("content", "")
            status = entry_map.get("status", "pending")
            priority = entry_map.get("priority", "medium")
            entries.append(
                PlanEntry(
                    content=content if isinstance(content, str) else str(content),
                    status=status if isinstance(status, str) else str(status),
                    priority=priority if isinstance(priority, str) else str(priority),
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
            art_map = cast("dict[str, object]", art)
            normalized.append(
                {
                    "artifact_id": art_map.get("artifact_id", ""),
                    "filename": art_map.get("filename", ""),
                    "content": art_map.get("content", ""),
                    "complete": art_map.get("complete", True),
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
        snapshot.replay_status = ReplayStatus.DURABLE.value
    elif checkpoint_error:
        snapshot.snapshot_complete = False
        snapshot.replay_status = ReplayStatus.UNKNOWN.value
    elif checkpoint_present:
        snapshot.snapshot_complete = False
        snapshot.replay_status = ReplayStatus.BEST_EFFORT.value
    elif thread_status == ThreadStatus.SUBMITTED.value:
        snapshot.snapshot_complete = True
        snapshot.replay_status = ReplayStatus.UNKNOWN.value
    else:
        snapshot.snapshot_complete = False
        if DegradedReason.CHECKPOINT_MISSING not in snapshot.degraded_reasons:
            snapshot.degraded_reasons.append(DegradedReason.CHECKPOINT_MISSING)
        # The probe succeeded and found nothing, so the history a replay would
        # rebuild from is provably absent: a replay gap, not the unknown that an
        # unavailable checkpoint reports.
        with contextlib.suppress(AttributeError):
            record_repair_posture(snapshot, RepairStatus.REPLAY_GAP.value)
        snapshot.replay_status = ReplayStatus.GAP_DETECTED.value
    return snapshot
