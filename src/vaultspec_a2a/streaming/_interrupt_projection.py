"""Project graph interrupts into permission and input-required events."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeGuard

from langgraph.checkpoint.base import BaseCheckpointSaver

from ..database import read_latest_checkpoint
from ..domain_config import domain_config
from ..graph.acp_options import (
    APPROVAL_OPTIONS,
    option_display_name,
    option_id_of,
    option_kind,
)
from ..graph.enums import AgentLifecycleState, PermissionOptionKind, PermissionType
from ..thread import InterruptType, live_interrupts

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ..database import Checkpointer
    from ..thread import LiveInterrupt
    from .emitters import EventEmitters
    from .types import StreamableGraph

__all__ = ["emit_interrupt_events"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _InterruptEmission:
    """One recognized graph interrupt, ready for its wire projection."""

    thread_id: str
    agent_id: str
    request_id: str
    interrupt_type: InterruptType
    payload: dict[str, Any]


async def emit_interrupt_events(
    thread_id: str,
    graph: StreamableGraph,
    config: dict[str, Any],
    emitters: EventEmitters,
) -> bool:
    """Inspect graph state after streaming and project every open question.

    A fanned-out branch that was answered and ran on keeps its interrupt in
    the snapshot until the superstep commits, so the questions are read
    against the checkpoint's held writes: an answered one is not asked again.
    """
    state = await _read_graph_state(thread_id, graph, config)
    if state is None:
        return False

    interrupts = live_interrupts(state, await _held_writes(thread_id, graph))
    if not interrupts:
        return False

    for emission in _interrupt_emissions(thread_id, interrupts):
        if not emitters.has_pending_permission(emission.request_id):
            await _emit_interrupt(emission, emitters)
    return True


async def _read_graph_state(
    thread_id: str, graph: StreamableGraph, config: dict[str, Any]
) -> object | None:
    """Read the final graph state without letting a failed read change the run."""
    try:
        return await asyncio.wait_for(
            graph.aget_state(config), timeout=domain_config.aget_state_timeout_seconds
        )
    except TimeoutError:
        logger.warning(
            "Timed out inspecting state for interrupt detection on thread %s",
            thread_id,
        )
    except Exception:
        logger.exception(
            "Failed to inspect state for interrupt detection on thread %s",
            thread_id,
        )
    return None


async def _held_writes(thread_id: str, graph: StreamableGraph) -> tuple[object, ...]:
    """The writes the store holds against the run's latest checkpoint.

    The run's own ingest is finishing, so nothing else writes this thread
    between the state read and this one. A store that cannot be read returns
    nothing, which leaves every question the snapshot lists reading as open:
    the snapshot's own reading, and the one that discloses a question rather
    than hiding one.
    """
    checkpointer: object = getattr(graph, "checkpointer", None)
    if not _is_checkpointer(checkpointer):
        return ()
    stored = await read_latest_checkpoint(checkpointer, thread_id)
    if stored.checkpoint_tuple is None:
        return ()
    return tuple(stored.checkpoint_tuple.pending_writes or ())


def _interrupt_emissions(
    thread_id: str, interrupts: Sequence[LiveInterrupt]
) -> list[_InterruptEmission]:
    """Normalize the recognized open questions while retaining the task that asked."""
    emissions: list[_InterruptEmission] = []
    for interrupt in interrupts:
        if interrupt.payload is None or interrupt.interrupt_type not in InterruptType:
            continue
        if interrupt.request_id is None:
            logger.warning(
                "Thread %s parked on a %s interrupt that names no request; it "
                "cannot be answered, so it is not disclosed",
                thread_id,
                interrupt.interrupt_type,
            )
            continue
        emissions.append(
            _InterruptEmission(
                thread_id=thread_id,
                agent_id=interrupt.task_name,
                request_id=interrupt.request_id,
                interrupt_type=InterruptType(interrupt.interrupt_type),
                payload=interrupt.payload,
            )
        )
    return emissions


def _is_payload(value: object) -> TypeGuard[dict[str, Any]]:
    """Narrow an untrusted graph payload to the mapping shape we project."""
    return isinstance(value, dict)


def _is_checkpointer(value: object) -> TypeGuard[Checkpointer]:
    """Narrow a graph's ``checkpointer`` attribute to a real saver.

    The attribute also takes ``False`` (checkpointing off) and ``True`` (a
    subgraph inheriting its parent's), neither of which holds any writes.
    """
    return isinstance(value, BaseCheckpointSaver)


async def _emit_interrupt(
    emission: _InterruptEmission, emitters: EventEmitters
) -> None:
    """Route one recognized interrupt to its explicit projection branch."""
    if emission.interrupt_type is InterruptType.CLARIFICATION_REQUEST:
        await _emit_clarification(emission, emitters)
    elif emission.interrupt_type is InterruptType.PLAN_APPROVAL_REQUEST:
        await _emit_plan_approval(emission, emitters)
    elif emission.interrupt_type is InterruptType.DOCUMENT_APPROVAL_REQUEST:
        await _emit_document_approval(emission, emitters)
    else:
        await _emit_tool_permission(emission, emitters)


async def _emit_clarification(
    emission: _InterruptEmission, emitters: EventEmitters
) -> None:
    """Emit only a nudge: question material belongs to the durable snapshot."""
    await emitters.emit_clarification_pending(
        thread_id=emission.thread_id,
        agent_id=emission.agent_id,
        request_id=emission.request_id,
    )
    await _emit_input_required(
        emission,
        emitters,
        "Awaiting an answer to a clarifying question",
    )


async def _emit_plan_approval(
    emission: _InterruptEmission, emitters: EventEmitters
) -> None:
    """Project a plan approval interrupt into its durable permission frame."""
    feature = _payload_text(emission.payload, "feature", "unknown")
    raw_plan_paths: object = emission.payload.get("plan_paths")
    plan_paths = raw_plan_paths if _is_object_list(raw_plan_paths) else []
    exec_worker = _payload_text(emission.payload, "exec_worker", "unknown")
    plan_summary = (
        f"{len(plan_paths)} plan document(s)" if plan_paths else "no plan documents"
    )
    await _emit_approval_request(
        emission,
        emitters,
        (
            f"Approve plan for feature '{feature}' before routing to {exec_worker} "
            f"({plan_summary})"
        ),
        _approval_options("Plan"),
        f"Awaiting plan approval for feature '{feature}'",
    )


async def _emit_document_approval(
    emission: _InterruptEmission, emitters: EventEmitters
) -> None:
    """Project a document approval interrupt into its durable permission frame."""
    phase = _payload_text(emission.payload, "phase", "document")
    feature = _payload_text(emission.payload, "feature", "unknown")
    await _emit_approval_request(
        emission,
        emitters,
        f"Approve the {phase} document for feature '{feature}' before the run proceeds",
        _approval_options("Document"),
        f"Awaiting {phase} document approval for feature '{feature}'",
    )


async def _emit_approval_request(
    emission: _InterruptEmission,
    emitters: EventEmitters,
    description: str,
    options: list[dict[str, Any]],
    status_detail: str,
) -> None:
    """Emit one approval request and its matching input-required status."""
    await emitters.emit_permission_request(
        thread_id=emission.thread_id,
        agent_id=emission.agent_id,
        request_id=emission.request_id,
        description=description,
        options=options,
        tool_call=PermissionType.PLAN_APPROVAL,
    )
    await _emit_input_required(emission, emitters, status_detail)


def _approval_options(subject: str) -> list[dict[str, Any]]:
    """Return the stable approve/reject pair for a plan or document decision."""
    approve, reject = APPROVAL_OPTIONS
    return [
        {**approve, "name": f"Approve {subject}"},
        {**reject, "name": f"Reject — Revise {subject}"},
    ]


async def _emit_tool_permission(
    emission: _InterruptEmission, emitters: EventEmitters
) -> None:
    """Project a provider tool permission while retaining its declared option kinds."""
    tool_name = _payload_text(emission.payload, "tool_name", "unknown")
    await emitters.emit_permission_request(
        thread_id=emission.thread_id,
        agent_id=emission.agent_id,
        request_id=emission.request_id,
        description=f"Permission required: {tool_name}",
        options=_permission_options(emission.payload.get("options", [])),
        tool_call=tool_name,
    )
    await _emit_input_required(emission, emitters, f"Awaiting approval for {tool_name}")


def _permission_options(raw_options: object) -> list[dict[str, Any]]:
    """Normalize ACP option identities and honor valid declared permission kinds."""
    options: list[dict[str, Any]] = []
    if _is_object_list(raw_options):
        for option in raw_options:
            options.append(_permission_option(option))
    return options or _default_permission_options()


def _is_object_list(value: object) -> TypeGuard[list[object]]:
    """Narrow a provider option collection to an iterable list of raw entries."""
    return isinstance(value, list)


def _permission_option(option: object) -> dict[str, Any]:
    """Project one ACP option, deriving a kind only for an invalid declaration."""
    fields: dict[str, Any] = option if _is_payload(option) else {}
    option_id = option_id_of(option)
    declared_kind = fields.get("kind")
    kind = option_kind(option)
    if declared_kind and kind != declared_kind:
        logger.warning(
            "Permission option %r declared unrecognised kind %r; "
            "derived %s from the option id instead",
            option_id,
            declared_kind,
            kind.value,
        )
    return {
        "option_id": option_id or "allow_once",
        "name": option_display_name(option),
        "kind": kind,
    }


def _default_permission_options() -> list[dict[str, Any]]:
    """Keep an omitted provider option list answerable."""
    return [
        {
            "option_id": "allow_once",
            "name": "Allow",
            "kind": PermissionOptionKind.ALLOW_ONCE,
        },
        {
            "option_id": "deny_once",
            "name": "Deny",
            "kind": PermissionOptionKind.REJECT_ONCE,
        },
    ]


def _payload_text(payload: dict[str, Any], key: str, default: str) -> str:
    """Read a text payload field without forwarding a malformed value to emitters."""
    value: object = payload.get(key)
    return value if isinstance(value, str) and value else default


async def _emit_input_required(
    emission: _InterruptEmission, emitters: EventEmitters, detail: str
) -> None:
    """Record that the task is parked until a human provides an answer."""
    await emitters.emit_agent_status(
        thread_id=emission.thread_id,
        agent_id=emission.agent_id,
        node_name=emission.agent_id,
        state=AgentLifecycleState.INPUT_REQUIRED,
        detail=detail,
    )
