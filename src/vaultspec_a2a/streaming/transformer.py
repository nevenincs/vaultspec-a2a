"""LangGraph stream projection — maps public stream frames to domain events.

A run is consumed through the documented stream modes of ``astream``. Each
frame arrives as ``(namespace, mode, payload)`` and this module turns it into
the wire events a client sees:

- ``messages`` carries the model's own token stream, already filtered by the
  ``nostream`` tag at the stream layer;
- ``tasks`` carries one start and one result per graph node, which is the node
  boundary and the node's own state update;
- ``updates`` carries the interrupts a parked run raised;
- ``custom`` carries whatever a node wrote through ``get_stream_writer()``.

A tool's own lifecycle is not a graph stream mode - it is a LangChain callback
- so it is projected by ``RunLifecycleCallbacks`` instead, seated in the run's
config. That handler is the sibling of this module, not a layer under it.

These functions are *logically* stateless — they receive emitter/buffering
references to perform side effects but hold no state of their own.
"""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from ..domain_config import domain_config
from ..graph.enums import AgentLifecycleState
from ..graph.protocols import NullTelemetryHook, TelemetryHook
from ._interrupt_projection import emit_interrupt_events as emit_interrupt_events
from .buffering import BufferingManager
from .emitters import EventEmitters
from .sse_frames import enforce_progress_allowlist
from .translation import (
    ModelStreamProjection,
    emit_additional_reasoning,
    text_field,
    translate_content_blocks,
    translate_tool_call_chunks,
)

logger = logging.getLogger(__name__)

#: The ``updates`` key LangGraph writes a parked run's interrupts under.
INTERRUPT_UPDATE_KEY = "__interrupt__"

#: The stream modes this projection consumes, in the order they are requested.
#: ``checkpoints`` is included because the run's own lifecycle reads it (the
#: dispatch receipt fires from the first durable one); it produces no wire
#: event of its own, so it is handled by the ingest loop rather than here.
STREAM_MODES = ("messages", "updates", "tasks", "custom", "checkpoints")


def project_run_progress(payload: object) -> object:
    """Transform a relayed gateway run event through the positive progress DTO.

    The gateway relays each worker run event onto the public progress edge; this
    is the producer-side projection that drops prompts, document and artifact
    bodies, edit diffs, and raw provider payloads before the event ever reaches a
    subscriber queue, keeping only the identifiers, lifecycle state, tool and
    artifact identity, and bounded text its frame type enumerates in the closed
    progress catalog. A non-mapping payload is returned unchanged. The encode
    boundary re-applies the catalog, so the exclusion still holds if this call
    site is bypassed; both layers call the one shared catalog deliberately, so
    they cannot drift apart.
    """
    if isinstance(payload, Mapping):
        return enforce_progress_allowlist(cast("Mapping[str, object]", payload))
    return payload


@dataclass(frozen=True, slots=True)
class StreamFrame:
    """One frame of a run's graph stream, as ``astream`` yields it."""

    namespace: tuple[str, ...]
    mode: str
    payload: object

    @property
    def is_root(self) -> bool:
        """Whether this frame came from the run's own graph, not a subgraph.

        A subgraph's inner node is a node of that subgraph, not an agent of
        this team, so only a root frame names an agent the client knows.
        """
        return not self.namespace


@dataclass(frozen=True, slots=True)
class EventProjectionServices:
    """The stable emitter, buffer, and telemetry dependencies for one stream."""

    emitters: EventEmitters
    buffering: BufferingManager
    telemetry: TelemetryHook | NullTelemetryHook


def frame_reports_interrupt(frame: StreamFrame) -> bool:
    """Whether this frame says the run parked on an interrupt.

    Read from the stream as it happens rather than from a state snapshot taken
    after it: a snapshot read can time out or fail, and a run whose interrupt
    was only ever visible in a failed read used to settle as though it had
    completed. LangGraph reports a park twice - once as an ``updates`` entry
    under its own key, and once on the parked task's result - and either is
    enough, so both are honoured.
    """
    payload = frame.payload
    if frame.mode == "updates" and isinstance(payload, dict):
        return INTERRUPT_UPDATE_KEY in cast("dict[str, object]", payload)
    if frame.mode == "tasks" and isinstance(payload, dict):
        return bool(cast("dict[str, object]", payload).get("interrupts"))
    return False


def durable_loop_checkpoint_id(frame: StreamFrame) -> str | None:
    """The id of a committed root checkpoint of the run's own loop, if this is one.

    ``input`` checkpoints record what the run was handed and carry none of the
    work, so only a ``loop`` one proves a superstep of this dispatch is on
    disk. A subgraph's checkpoint is not this run's, so only root frames count.
    """
    payload = frame.payload
    if (
        frame.mode != "checkpoints"
        or not frame.is_root
        or not isinstance(payload, dict)
    ):
        return None
    snapshot = cast("dict[str, object]", payload)
    metadata = snapshot.get("metadata")
    if not isinstance(metadata, dict):
        return None
    if cast("dict[str, object]", metadata).get("source") != "loop":
        return None
    config = snapshot.get("config")
    if not isinstance(config, dict):
        return None
    configurable = cast("dict[str, object]", config).get("configurable")
    if not isinstance(configurable, dict):
        return None
    checkpoint_id = cast("dict[str, object]", configurable).get("checkpoint_id")
    return checkpoint_id if isinstance(checkpoint_id, str) else None


async def process_stream_frame(
    frame: StreamFrame,
    thread_id: str,
    agent_id: str,
    services: EventProjectionServices,
) -> None:
    """Transform one public LangGraph stream frame into wire events."""
    if frame.mode == "messages":
        await _project_messages(frame, thread_id, agent_id, services)
        return
    if frame.mode == "tasks":
        await _project_task(frame, thread_id, agent_id, services)
        return
    if frame.mode == "custom":
        await _project_custom(frame, thread_id, agent_id, services.emitters)
        return
    if frame.mode in ("updates", "checkpoints"):
        # `updates` duplicates what the task result already carried, and is
        # consumed for its interrupt key by the run's own classification;
        # `checkpoints` drives the dispatch receipt. Neither is wire output.
        return
    services.telemetry.increment_counter(
        "aggregator.events_filtered", 1, **{"event.kind": frame.mode}
    )
    logger.debug("Unhandled LangGraph stream mode: %s", frame.mode)


# ---------------------------------------------------------------------------
# messages — the model's own token stream
# ---------------------------------------------------------------------------


async def _project_messages(
    frame: StreamFrame,
    thread_id: str,
    agent_id: str,
    services: EventProjectionServices,
) -> None:
    """Project one ``(chunk, metadata)`` pair of the model token stream.

    The ``nostream`` tag is honoured by the stream layer itself, so the
    supervisor's routing decision never reaches here to be filtered out by
    hand, and nothing this projection does can let it through.
    """
    pair = frame.payload
    if not isinstance(pair, tuple) or len(cast("tuple[object, ...]", pair)) != 2:
        return
    chunk, raw_metadata = cast("tuple[object, object]", pair)
    metadata = cast(
        "dict[str, object]", raw_metadata if isinstance(raw_metadata, dict) else {}
    )
    node = metadata.get("langgraph_node")
    projection = ModelStreamProjection(
        thread_id=thread_id,
        agent_id=node if isinstance(node, str) and node else agent_id,
        message_id=_message_id(chunk, thread_id),
        emitters=services.emitters,
        buffering=services.buffering,
    )
    await translate_tool_call_chunks(
        chunk, projection.thread_id, projection.agent_id, projection.emitters
    )
    content: object = getattr(chunk, "content", "")
    if isinstance(content, list):
        await translate_content_blocks(cast("list[object]", content), projection)
    elif isinstance(content, str) and content:
        await projection.buffering.buffer_message_chunk(
            thread_id=projection.thread_id,
            agent_id=projection.agent_id,
            content=content,
            message_id=projection.message_id,
        )
    await emit_additional_reasoning(chunk, projection)


def _message_id(chunk: object, thread_id: str) -> str:
    """The identity a client joins one model turn's chunks under.

    The message's own id is used, not the run id that produced it, because the
    same id is what lands in checkpointed state and what the settled run's REST
    snapshot reports for the same message. Keying the live stream on anything
    else gives a reloading client two ids for one message.
    """
    message_id = getattr(chunk, "id", None)
    return message_id if isinstance(message_id, str) and message_id else thread_id


# ---------------------------------------------------------------------------
# tasks — the node boundary and the node's own update
# ---------------------------------------------------------------------------


async def _project_task(
    frame: StreamFrame,
    thread_id: str,
    agent_id: str,
    services: EventProjectionServices,
) -> None:
    """Project one node's start or result into its status and state events.

    Only a root frame is an agent of this team. A subgraph's inner node runs
    under a non-empty namespace and is that subgraph's business; reporting it
    here put a node no client had ever been told about on the team roster.
    """
    payload = frame.payload
    if not frame.is_root or not isinstance(payload, dict):
        return
    task = cast("dict[str, object]", payload)
    name = task.get("name")
    node = name if isinstance(name, str) and name else agent_id
    del agent_id
    emitters = services.emitters
    if "result" not in task and "error" not in task:
        await emitters.emit_agent_status(
            thread_id=thread_id,
            agent_id=node,
            node_name=node,
            state=AgentLifecycleState.WORKING,
        )
        return
    error = task.get("error")
    if error is not None:
        error_msg = str(error)
        logger.warning(
            "Node error in thread %s node %s: %s", thread_id, node, error_msg
        )
        await emitters.emit_agent_status(
            thread_id=thread_id,
            agent_id=node,
            node_name=node,
            state=AgentLifecycleState.FAILED,
            detail=error_msg[:200],
        )
        return
    await emitters.emit_agent_status(
        thread_id=thread_id,
        agent_id=node,
        node_name=node,
        state=AgentLifecycleState.IDLE,
    )
    await _emit_node_result(task.get("result"), thread_id, emitters)


async def _emit_node_result(
    result: object, thread_id: str, emitters: EventEmitters
) -> None:
    """Project a node's own state update into plan and artifact events.

    The node's update is read, not the whole graph state: a nested runnable
    inside a node used to be mistaken for the node itself, so a helper chain
    that happened to return a plan-shaped value published a plan the node
    never wrote.
    """
    if not isinstance(result, dict):
        return
    update = cast("dict[str, object]", result)
    await _emit_plan(update.get("current_plan"), thread_id, emitters)
    await _emit_artifacts(update.get("artifacts"), thread_id, emitters)


async def _emit_plan(raw_plan: object, thread_id: str, emitters: EventEmitters) -> None:
    if not isinstance(raw_plan, list) or not raw_plan:
        return
    entries: list[dict[str, str]] = [
        {
            "content": text_field(entry_map, "content"),
            "status": text_field(entry_map, "status") or "pending",
            "priority": text_field(entry_map, "priority") or "medium",
        }
        for entry in cast("list[object]", raw_plan)
        if isinstance(entry, dict)
        for entry_map in (cast("dict[str, object]", entry),)
        if entry_map.get("content")
    ]
    if entries:
        await emitters.emit_plan_update(thread_id, entries)


async def _emit_artifacts(
    raw_artifacts: object, thread_id: str, emitters: EventEmitters
) -> None:
    if not isinstance(raw_artifacts, list) or not raw_artifacts:
        return
    for artifact in cast("list[object]", raw_artifacts):
        if not isinstance(artifact, dict):
            continue
        artifact_map = cast("dict[str, object]", artifact)
        if artifact_map.get("id"):
            await emitters.emit_artifact_update(
                thread_id=thread_id,
                artifact_id=str(artifact_map["id"]),
                filename=str(
                    artifact_map.get("filename", artifact_map.get("path", ""))
                ),
                content=str(artifact_map.get("content", "")),
            )


# ---------------------------------------------------------------------------
# custom — whatever a node wrote through get_stream_writer()
# ---------------------------------------------------------------------------


async def _project_custom(
    frame: StreamFrame,
    thread_id: str,
    agent_id: str,
    emitters: EventEmitters,
) -> None:
    """Relay a node's own stream write as a thought.

    LangGraph strips the writing node from a custom write's namespace, so the
    write is attributed to the run's agent rather than guessed at. Any payload
    shape a node cares to write is accepted: the reason this path existed
    without a producer is that only one shape was ever contemplated.
    """
    content = _custom_text(frame.payload)
    if not content:
        return
    await emitters.emit_thought_chunk(
        thread_id=thread_id,
        agent_id=agent_id,
        content=content,
        message_id=thread_id,
    )


def _custom_text(payload: object) -> str:
    """Render an arbitrary stream write as bounded display text."""
    if isinstance(payload, str):
        text = payload
    elif isinstance(payload, Mapping):
        mapping = cast("Mapping[str, object]", payload)
        raw = mapping.get("content", mapping)
        text = raw if isinstance(raw, str) else str(raw)
    elif payload is None:
        return ""
    elif isinstance(payload, Sequence | bytes):
        text = str(payload)
    else:
        text = str(payload)
    if not text:
        return ""
    max_len = domain_config.tool_arg_truncate_len
    return text[:max_len] + "..." if len(text) > max_len else text
