"""Event handlers for worker → gateway relay.

Business-logic handlers that persist worker events into the database,
journal permission requests, re-project the run's pause, and release the
relay hub's run state on thread termination.  They live here, not in
``api/internal.py``, so the route keeps to protocol translation and the domain
logic stays out of it.

The :func:`relay_event` orchestrator runs the one handler sequence every
relayed worker event goes through.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import TypeAdapter, ValidationError

from ..graph.enums import ProviderCondition, ServerEventType
from ..ipc.schemas import (
    ExecutionStateProjectionPayload,
)
from ..thread import named_request_id
from ..thread.cancellation_evidence import CancellationEvidence
from ..thread.constants import MAX_PERMISSION_DESCRIPTION_CHARS
from ..thread.enums import TERMINAL_STATUS_VALUES, InterruptType, ThreadStatus
from ..thread.failure_evidence import GraphFailureEvidence
from ..thread.idempotency import permission_request_action_key
from ..thread.snapshots import (
    PERMISSION_REQUEST_EVENT_TYPES,
    classify_permission_pause_reason,
    is_permission_event,
    is_terminal_event,
    wire_event_type,
)
from ..utils.coercion import decode_json_object
from ._event_application import (
    apply_relayed_permission_resolution as _apply_relayed_permission_resolution,
)
from ._event_application import (
    commit_proven_application as _commit_proven_application,
)
from ._event_application import (
    proven_application_receipt as _proven_application_receipt,
)
from ._event_application import (
    validated_application_receipt as _validated_application_receipt,
)
from ._thread_metadata import run_lease_id

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ..database import (
        Checkpointer,
        ControlActionModel,
        ThreadModel,
        ThreadStatusElectionOutcome,
    )
    from ..streaming import RelayHub
    from ..thread import ProjectedInterrupt
    from .drain import DrainGate
    from .terminal_settlement import TerminalEvidence

__all__ = [
    "CheckpointPruneRegistry",
    "RelayServices",
    "_handle_execution_state_event",
    "_handle_permission_event",
    "_handle_progress_event",
    "_handle_terminal_event",
    "relay_event",
]

logger = logging.getLogger(__name__)


# Strong references to in-flight settlement callbacks so a fire-and-forget task is
# not garbage-collected before it completes; each removes itself when done.
_settlement_tasks: set[asyncio.Task[None]] = set()
_OPTION_MAPPINGS = TypeAdapter(list[dict[str, object]])


#: Fans out the terminal frame the relay is holding for this event.
#:
#: Synchronous because the fan-out is: it enqueues an already-projected body on
#: each subscriber's queue and does no I/O. The relay hands it over instead of
#: calling it, so the frame crosses to clients only on the side of the
#: settlement decision where the run really is ending.
type _TerminalPublisher = Callable[[], None]


@dataclass(frozen=True, slots=True, kw_only=True)
class RelayServices:
    """The collaborators a relayed worker event is handled against.

    Each is optional because a process may own none of them: without a session
    factory the durable writes are skipped, without a checkpointer the handlers
    that need checkpoint proof decline, and without a drain gate, prune registry
    or relay hub there is nothing to release.
    """

    relay_hub: RelayHub | None = None
    session_factory: async_sessionmaker[AsyncSession] | None = None
    checkpointer: Checkpointer | None = None
    drain_gate: DrainGate | None = None
    prune_registry: CheckpointPruneRegistry | None = None
    publish_terminal: _TerminalPublisher | None = None


def _session_factory(
    configured: async_sessionmaker[AsyncSession] | None,
) -> async_sessionmaker[AsyncSession] | None:
    """Return the caller's session factory; ``None`` means skip the durable write.

    Deliberately NOT a resolver. Which database an event belongs in is a property
    of the application relaying it, and the app boundary is the only place that
    knows - so it resolves once, in ``api.internal``, and these handlers use what
    they are given.

    Resolving again here defeated that. An app that had DECLARED it owns no
    database arrived as ``None``, this reached for the process database anyway,
    and the write landed in whichever store some unrelated component had opened
    in the same process. The earlier form was worse still: it called
    ``get_session_factory``, which CREATES an engine from ambient settings when
    none was initialized, so a process owning no database acquired a connection
    to a settings-derived path and failed at its first query.
    """
    return configured


async def _keep_settlement_if_won(
    db: AsyncSession, outcome: ThreadStatusElectionOutcome
) -> bool:
    """Commit a worker-evidence settlement whose election won; discard any other."""
    from ..database import ThreadStatusElectionOutcome

    if outcome is not ThreadStatusElectionOutcome.WON:
        await db.rollback()
        return False
    await db.commit()
    return True


@dataclass(frozen=True, slots=True, kw_only=True)
class _ProvenTerminal:
    """One terminal the worker's own evidence asks the control plane to settle.

    *prove* judges the locked run and the journal action the evidence names,
    and returns what to settle them with, or ``None`` when the pair does not
    admit this evidence.
    """

    thread_id: str
    dispatch_id: str
    status: ThreadStatus
    last_sequence: int | None
    prove: Callable[[ThreadModel, ControlActionModel], TerminalEvidence | None]


async def _settle_proven_terminal(
    factory: async_sessionmaker[AsyncSession], terminal: _ProvenTerminal
) -> bool:
    """Lock the run, find the action its evidence names, and settle if proven."""
    from ..database import get_control_action_by_dispatch_id
    from .terminal_settlement import lock_terminal_run, settle_terminal

    async with factory() as db:
        thread = await lock_terminal_run(db, terminal.thread_id)
        action = await get_control_action_by_dispatch_id(
            db, thread_id=terminal.thread_id, dispatch_id=terminal.dispatch_id
        )
        proof = (
            None if thread is None or action is None else terminal.prove(thread, action)
        )
        if thread is None or proof is None:
            await db.rollback()
            return False
        outcome = await settle_terminal(
            db,
            thread,
            terminal.status,
            evidence=proof,
            last_sequence=terminal.last_sequence,
        )
        return await _keep_settlement_if_won(db, outcome)


async def _persist_proven_cancellation(
    factory: async_sessionmaker[AsyncSession],
    *,
    thread_id: str,
    evidence: CancellationEvidence,
    last_sequence: int | None,
) -> bool:
    """Elect and settle one exact current cancellation terminal."""
    from ..database import thread_write_expectation
    from ..thread.enums import ControlActionResultStatus, ControlActionType
    from .terminal_settlement import TerminalEvidence

    def prove(
        thread: ThreadModel, action: ControlActionModel
    ) -> TerminalEvidence | None:
        expectation = thread_write_expectation(thread)
        if (
            action.action_type != ControlActionType.CANCEL.value
            or thread.status
            not in {ThreadStatus.CANCELLING.value, ThreadStatus.RECONCILING.value}
            or not expectation.authority.owned_by(
                ControlActionType.CANCEL, evidence.dispatch_id
            )
        ):
            return None
        return TerminalEvidence(
            expectation=expectation,
            action_id=action.id,
            action_type=ControlActionType.CANCEL,
            action_receipt_id=evidence.dispatch_id,
            result_status=(
                ControlActionResultStatus.CANCELLED_CEASED
                if evidence.outcome == "ceased"
                else ControlActionResultStatus.CANCELLED_NO_ACTIVE_WORK
            ),
        )

    return await _settle_proven_terminal(
        factory,
        _ProvenTerminal(
            thread_id=thread_id,
            dispatch_id=evidence.dispatch_id,
            status=ThreadStatus.CANCELLED,
            last_sequence=last_sequence,
            prove=prove,
        ),
    )


async def _persist_proven_failure(
    factory: async_sessionmaker[AsyncSession],
    *,
    thread_id: str,
    evidence: GraphFailureEvidence,
    failure_reason: str,
    last_sequence: int | None,
) -> bool:
    """Elect and settle one failure for the exact current graph action."""
    from ..database import thread_write_expectation
    from ..thread.enums import NON_ACTIVE_STATUSES
    from .dispatch_receipts import validate_current_graph_receipt
    from .terminal_settlement import TerminalEvidence

    def prove(
        thread: ThreadModel, action: ControlActionModel
    ) -> TerminalEvidence | None:
        if (
            ThreadStatus(thread.status) in NON_ACTIVE_STATUSES
            or validate_current_graph_receipt(thread, action) != evidence.action
        ):
            return None
        return TerminalEvidence(
            expectation=thread_write_expectation(thread),
            action_id=action.id,
            action_type=evidence.action.action_type,
            action_receipt_id=evidence.action.dispatch_id,
            failure_reason=failure_reason,
            provider_condition=evidence.provider_condition,
        )

    return await _settle_proven_terminal(
        factory,
        _ProvenTerminal(
            thread_id=thread_id,
            dispatch_id=evidence.action.dispatch_id,
            status=ThreadStatus.FAILED,
            last_sequence=last_sequence,
            prove=prove,
        ),
    )


def _skip_without_database(what: str, thread_id: str) -> None:
    """Record a durable write skipped because this process has no database.

    Silence here would be the same defect as the ambient engine it replaces: a
    projection that never happened must be readable as an absence, not inferred
    from a missing row much later.
    """
    logger.warning(
        "Skipping %s for %s: this process has no database",
        what,
        thread_id,
        extra={"thread_id": thread_id, "action": "durable_write_skipped_no_database"},
    )


def _option_mappings(value: object) -> list[dict[str, object]]:
    """Keep only bounded, string-keyed permission option objects."""
    try:
        return _OPTION_MAPPINGS.validate_python(value)[:50]
    except ValidationError:
        return []


def _schedule_terminal_settlement(
    thread_id: str,
    terminal_status: ThreadStatus,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Schedule the run's terminal-settlement callback without blocking the relay.

    A no-op outside the armed desktop profile, where there is no dashboard to
    settle with. Otherwise it fires the bounded callback as a background task so a
    slow or unreachable dashboard never stalls worker event relay; the emitter is
    itself bounded and never raises.
    """
    from .config import settings

    if not settings.desktop_profile_armed:
        return
    task = asyncio.create_task(
        _settle_terminal_run(thread_id, terminal_status, session_factory)
    )
    _settlement_tasks.add(task)
    task.add_done_callback(_settlement_tasks.discard)


async def _settle_terminal_run(
    thread_id: str,
    terminal_status: ThreadStatus,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Recover the run's lease and deliver its attach-authenticated settlement."""
    from ..desktop.settlement import emit_run_settlement

    lease_id = await _read_run_lease(thread_id, session_factory)
    if lease_id is None:
        # A run created outside the two-stage admission protocol (the one-shot
        # start path) carries no lease, so there is nothing to settle.
        return
    result = await emit_run_settlement(
        run_id=thread_id,
        lease_id=lease_id,
        terminal_status=terminal_status,
    )
    if not result.delivered and not result.skipped:
        logger.warning(
            "Terminal settlement not delivered for run %s: %s",
            thread_id,
            result.reason,
        )


async def _read_run_lease(
    thread_id: str, session_factory: async_sessionmaker[AsyncSession]
) -> str | None:
    """Read a run's non-secret lease identity from its persisted metadata."""
    from ..database import get_thread

    async with session_factory() as db:
        thread = await get_thread(db, thread_id)
    if thread is None:
        return None
    return run_lease_id(decode_json_object(thread.thread_metadata))


async def _confirm_completed_terminal(
    thread_id: str,
    factory: async_sessionmaker[AsyncSession] | None,
    checkpointer: Checkpointer | None,
    last_sequence: int | None,
) -> _TerminalDisposition:
    if factory is None:
        _skip_without_database("the completion reconciliation", thread_id)
        return _TerminalDisposition.REFUSED
    if checkpointer is None:
        logger.warning(
            "Refusing completion for %s: no checkpointer is available",
            thread_id,
            extra={"thread_id": thread_id, "action": "completion_proof_unavailable"},
        )
        return _TerminalDisposition.REFUSED
    from ..domain_config import domain_config
    from .recovery_authority import (
        CONTINUATION_PROMOTED,
        RecoveryRequest,
        RecoveryTrigger,
        reconcile_run_checkpoint,
    )

    async with factory() as db:
        observation = await reconcile_run_checkpoint(
            db,
            checkpointer,
            RecoveryRequest(
                thread_id=thread_id,
                trigger=RecoveryTrigger.WORKER_EVENT,
                checkpoint_timeout_seconds=domain_config.aget_state_timeout_seconds,
                last_sequence=last_sequence,
            ),
        )
    if observation.condition == CONTINUATION_PROMOTED:
        # The turn ended and the run did not. Nothing terminal may follow from
        # this event: no settlement, no history prune, no release of the run's
        # admission slot, and no reset of the numbering the next turn
        # continues from.
        logger.info(
            "Turn boundary on %s: a queued continuation now owns the run",
            thread_id,
            extra={"thread_id": thread_id, "action": "continuation_promoted"},
        )
        return _TerminalDisposition.PROMOTED
    if observation.status is not ThreadStatus.COMPLETED:
        logger.warning(
            "Refusing unproven completion for %s: %s",
            thread_id,
            observation.condition,
            extra={
                "thread_id": thread_id,
                "condition": observation.condition,
                "action": "unproven_completion",
            },
        )
        return _TerminalDisposition.REFUSED
    return _TerminalDisposition.SETTLED


async def _confirm_cancelled_terminal(
    thread_id: str,
    raw_evidence: object,
    factory: async_sessionmaker[AsyncSession] | None,
    last_sequence: int | None,
) -> bool:
    if raw_evidence is None:
        logger.warning(
            "Refusing cancellation without exact cessation evidence for %s",
            thread_id,
            extra={"thread_id": thread_id, "action": "missing_cancellation_evidence"},
        )
        return False
    try:
        evidence = CancellationEvidence.model_validate(raw_evidence)
    except ValidationError:
        logger.warning(
            "Refusing invalid cancellation evidence for thread %s",
            thread_id,
            extra={"thread_id": thread_id, "action": "invalid_cancellation_evidence"},
        )
        return False
    if factory is None:
        _skip_without_database("the cancellation terminal election", thread_id)
        return False
    accepted = await _persist_proven_cancellation(
        factory,
        thread_id=thread_id,
        evidence=evidence,
        last_sequence=last_sequence,
    )
    if not accepted:
        logger.warning(
            "Refusing stale cancellation evidence for thread %s",
            thread_id,
            extra={
                "thread_id": thread_id,
                "dispatch_id": evidence.dispatch_id,
                "action": "stale_cancellation_evidence",
            },
        )
    return accepted


def _parse_failure_terminal(
    thread_id: str, payload: dict[str, object]
) -> tuple[GraphFailureEvidence, str] | None:
    raw_evidence = payload.get("failure_evidence")
    if raw_evidence is None:
        logger.warning(
            "Refusing failure without exact action evidence for %s",
            thread_id,
            extra={"thread_id": thread_id, "action": "missing_failure_evidence"},
        )
        return None
    try:
        evidence = GraphFailureEvidence.model_validate(raw_evidence)
    except ValidationError:
        logger.warning(
            "Refusing invalid failure evidence for thread %s",
            thread_id,
            extra={"thread_id": thread_id, "action": "invalid_failure_evidence"},
        )
        return None
    error_detail = payload.get("error_detail")
    raw_condition = payload.get("provider_condition")
    if not isinstance(error_detail, str) or not error_detail:
        return None
    try:
        condition = ProviderCondition(raw_condition)
    except (TypeError, ValueError):
        return None
    if not evidence.matches(
        thread_id=thread_id,
        error_detail=error_detail,
        provider_condition=condition.value,
    ):
        logger.warning(
            "Refusing mismatched failure evidence for thread %s",
            thread_id,
            extra={"thread_id": thread_id, "action": "mismatched_failure_evidence"},
        )
        return None
    return evidence, error_detail


async def _confirm_failed_terminal(
    thread_id: str,
    payload: dict[str, object],
    factory: async_sessionmaker[AsyncSession] | None,
    last_sequence: int | None,
) -> bool:
    parsed = _parse_failure_terminal(thread_id, payload)
    if parsed is None:
        return False
    evidence, error_detail = parsed
    if factory is None:
        _skip_without_database("the failure terminal election", thread_id)
        return False
    accepted = await _persist_proven_failure(
        factory,
        thread_id=thread_id,
        evidence=evidence,
        failure_reason=error_detail,
        last_sequence=last_sequence,
    )
    if not accepted:
        logger.warning(
            "Refusing stale failure evidence for thread %s",
            thread_id,
            extra={"thread_id": thread_id, "action": "stale_failure_evidence"},
        )
    return accepted


def _validated_terminal_status(
    thread_id: str, payload: dict[str, object]
) -> ThreadStatus | None:
    """Reject evidence attached to a different terminal outcome."""
    payload_status = payload.get("status")
    if not isinstance(payload_status, str) or payload_status not in (
        TERMINAL_STATUS_VALUES
    ):
        return None
    status = ThreadStatus(payload_status)
    if (
        payload.get("cancellation_evidence") is not None
        and status is not ThreadStatus.CANCELLED
    ):
        logger.warning(
            "Refusing cancellation evidence on non-cancelled terminal for %s",
            thread_id,
        )
        return None
    if (
        payload.get("failure_evidence") is not None
        and status is not ThreadStatus.FAILED
    ):
        logger.warning(
            "Refusing failure evidence on non-failed terminal for %s", thread_id
        )
        return None
    return status


class _TerminalDisposition(StrEnum):
    """What a proven terminal event did to the run that emitted it.

    Three outcomes, not two. ``PROMOTED`` is the one the deferred-terminal
    model adds: the evidence was proven and accepted, and the run did not
    settle because a continuation was waiting for it. Collapsing it into a
    refusal would log every honest turn boundary as an unproven completion.
    """

    SETTLED = "settled"
    PROMOTED = "promoted"
    REFUSED = "refused"


async def _accept_terminal_event(
    thread_id: str,
    payload: dict[str, object],
    terminal_status: ThreadStatus,
    context: tuple[
        async_sessionmaker[AsyncSession] | None, int | None, Checkpointer | None
    ],
) -> _TerminalDisposition:
    factory, last_sequence, checkpointer = context
    if terminal_status is ThreadStatus.COMPLETED:
        return await _confirm_completed_terminal(
            thread_id, factory, checkpointer, last_sequence
        )
    if terminal_status is ThreadStatus.CANCELLED:
        return _settled_or_refused(
            await _confirm_cancelled_terminal(
                thread_id, payload.get("cancellation_evidence"), factory, last_sequence
            )
        )
    return _settled_or_refused(
        await _confirm_failed_terminal(thread_id, payload, factory, last_sequence)
    )


def _settled_or_refused(accepted: bool) -> _TerminalDisposition:
    """Classify the two terminals a continuation never defers.

    Cancellation and failure settle from their own durable evidence rather
    than from a proven checkpoint, so neither is the turn boundary a
    continuation waits behind: a cancelled run is leaving, and a failed turn
    has no state for a next turn to continue from.
    """
    return _TerminalDisposition.SETTLED if accepted else _TerminalDisposition.REFUSED


async def _prune_settled_history(
    thread_id: str, checkpointer: Checkpointer | None
) -> None:
    """Drop a settled run's superseded checkpoints; never fails the relay.

    Runs here rather than in the worker because the relay applies a thread's
    events in order: every application receipt the run emitted, each pinned to
    the checkpoint it names, has been checked by the time its terminal lands.
    """
    if checkpointer is None:
        return
    from ..database import prune_settled_checkpoints
    from ..domain_config import domain_config

    try:
        await asyncio.wait_for(
            prune_settled_checkpoints(checkpointer, thread_id),
            timeout=domain_config.aget_state_timeout_seconds,
        )
    except Exception:
        logger.warning(
            "Could not prune the settled checkpoint history of %s",
            thread_id,
            exc_info=True,
            extra={"thread_id": thread_id, "action": "checkpoint_prune_failed"},
        )


class CheckpointPruneRegistry:
    """The settled-history prunes one application started and must wait for.

    Owned by the application whose lifespan closes the checkpointer these
    prunes delete through: that owner is the only one that knows when waiting
    for them is over. Held as process state, a shutting-down application
    waited on another application's deletes against a store it does not close,
    and could not tell which of the pending work was its own.
    """

    __slots__ = ("_tasks",)

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[None]] = set()

    def schedule(self, thread_id: str, checkpointer: Checkpointer | None) -> None:
        """Prune a settled run's history without holding up the relay.

        The relay applies a thread's events in order, so a prune awaited there
        would delay every later event of every run behind one run's delete.
        """
        if checkpointer is None:
            return
        task = asyncio.create_task(_prune_settled_history(thread_id, checkpointer))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def settle(self) -> None:
        """Wait for every prune already started to finish."""
        while self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)


def _publish_terminal(thread_id: str, publish: _TerminalPublisher | None) -> None:
    """Release the held terminal frame to this run's viewers.

    A failure here is logged and nothing more. By the time it can happen the
    settlement is already durable, so raising would abandon the release below
    and leave the finished run holding its admission slot - a worse outcome
    than one viewer missing a frame it can still resume for.
    """
    if publish is None:
        return
    try:
        publish()
    except Exception:
        logger.warning(
            "Could not fan out the terminal frame of %s",
            thread_id,
            exc_info=True,
            extra={"thread_id": thread_id, "action": "terminal_frame_not_published"},
        )


async def _handle_terminal_event(
    thread_id: str,
    payload: dict[str, object],
    services: RelayServices | None = None,
) -> None:
    """Settle a proven terminal event, then release drain and relay hub state.

    Also the gate on the client-visible terminal frame. The relay hands the
    frame over as *publish_terminal* rather than fanning it out itself,
    because only the settlement below knows whether this terminal ends the
    RUN or only the TURN: a run with a continuation waiting takes the next
    turn instead of ending, and a terminal shown there is a lie a viewer
    cannot take back. A refused terminal also cannot be shown: a delayed
    first-turn event may arrive after recovery already promoted its successor.
    Only a settled run publishes, before the prune, drain release and
    relay hub purge that would otherwise make the frame undeliverable.
    """
    resolved = services or RelayServices()
    relay_hub = resolved.relay_hub
    checkpointer = resolved.checkpointer
    drain_gate = resolved.drain_gate
    prune_registry = resolved.prune_registry
    if not is_terminal_event(payload):
        return
    # Capture before the durable write and before relay hub state is pruned.
    # The relay has already numbered the terminal frame it is holding, so this
    # mark IS that frame's own number and the cursor recorded below names the
    # last frame the client receives. ``None`` - nothing numbers this run -
    # leaves the settled cursor unwritten.
    last_sequence = (
        relay_hub.issued_sequence(thread_id) if relay_hub is not None else None
    )
    terminal_status = _validated_terminal_status(thread_id, payload)
    if terminal_status is None:
        # An unreadable terminal settled nothing and cannot close a stream.
        return
    factory = _session_factory(resolved.session_factory)
    disposition = await _accept_terminal_event(
        thread_id, payload, terminal_status, (factory, last_sequence, checkpointer)
    )
    if disposition is not _TerminalDisposition.SETTLED:
        # A promoted turn or refused stale event did not end the run. Its
        # frame is never published, so it never enters the replay log and the
        # relay gives its number back to the run.
        return
    _publish_terminal(thread_id, resolved.publish_terminal)
    if factory is None:
        return
    _schedule_terminal_settlement(thread_id, terminal_status, factory)
    if prune_registry is not None:
        # No registry, no prune: a delete nobody waits for outlives the
        # checkpointer it writes through.
        prune_registry.schedule(thread_id, checkpointer)
    if drain_gate is not None:
        await drain_gate.release(thread_id)
    if relay_hub is not None:
        relay_hub.clear_thread_state(thread_id)


#: The approval gates record the pause they relay as the interrupt kind the run
#: is really parked on; a tool permission classifies its pause from the tool it
#: asks about. Read off the checkpoint, never off the relayed frame: every
#: permission frame crosses the wire as ``permission_request``, so keying this on
#: the frame's own type named a document approval a plan approval and hid it from
#: the lookup the out-of-run verdict subscriber reaches its run through.
_APPROVAL_GATE_INTERRUPT_TYPES: frozenset[str] = frozenset(
    {
        InterruptType.PLAN_APPROVAL_REQUEST.value,
        InterruptType.DOCUMENT_APPROVAL_REQUEST.value,
    }
)


async def _held_request_interrupt(
    thread_id: str,
    payload: dict[str, object],
    checkpointer: Checkpointer | None,
) -> ProjectedInterrupt | None:
    """The checkpoint interrupt a relayed permission request announces.

    The checkpoint is the pause authority for every interrupt kind, so the kind
    a request is journaled under, and whether it is still open at all, are read
    from the interrupt the run is really parked on rather than from the frame
    that announced it. ``None`` means nothing may be journaled: the frame named
    no request, no checkpoint could be read, or the request it names is one the
    run no longer holds - answered in the window between emission and relay, so
    a pending row written for it would be a row nobody can answer.
    """
    request_id = named_request_id(payload)
    if request_id is None:
        return None
    if checkpointer is None:
        logger.warning(
            "Skipping the permission journal for %s: no checkpointer is available",
            thread_id,
            extra={"thread_id": thread_id, "action": "pause_proof_unavailable"},
        )
        return None
    from ..database import read_latest_checkpoint
    from ._permission_response_contract import held_interrupt
    from .pause import project_checkpoint_read

    projection = project_checkpoint_read(
        await read_latest_checkpoint(checkpointer, thread_id), thread_id
    )
    held = held_interrupt(projection, request_id)
    if held is None:
        logger.info(
            "Not journaling permission request %s on %s: its checkpoint holds "
            "no such pause",
            request_id,
            thread_id,
            extra={
                "thread_id": thread_id,
                "request_id": request_id,
                "action": "permission_request_not_held",
            },
        )
    return held


def _permission_request_fields(
    payload: dict[str, object], held: ProjectedInterrupt
) -> tuple[str | None, str, str]:
    """Normalize the fields stored with a permission request the run holds."""
    tool_value = payload.get("tool_call")
    tool_call = tool_value if isinstance(tool_value, str) else None
    pause_reason_type = (
        held.interrupt_type
        if held.interrupt_type in _APPROVAL_GATE_INTERRUPT_TYPES
        else classify_permission_pause_reason(tool_call)
    )
    description_value = payload.get("description")
    # Keep the durable row at least as descriptive as the streamed frame.
    description = (
        description_value[:MAX_PERMISSION_DESCRIPTION_CHARS]
        if isinstance(description_value, str)
        else ""
    )
    return (
        tool_call,
        pause_reason_type,
        description,
    )


async def _persist_permission_request(
    db: AsyncSession,
    thread_id: str,
    payload: dict[str, object],
    *,
    held: ProjectedInterrupt,
) -> None:
    """Record a fresh permission or approval request in the durable journal.

    The request row and its creation action are the journal: they hold the
    request's lifecycle and cache its description and offered options for
    disclosure. Whether the run is parked on it is the checkpoint's to say, so
    the pause recorder projects the pause and this writes no run state, and
    *held* - the interrupt that checkpoint holds under this request id - names
    the pause kind the row records.

    A request whose creation action is already reserved has been journaled
    before, so this is either a replayed event or a RE-ASK: a run holding the
    request again after answering it is asking the same question a second time.
    :func:`reopen_reasked_permission_request` tells the two apart from the row's
    settled state, which reads the same whichever of the re-ask's park frame and
    the previous answer's receipt the relay handled first.
    """
    from ..database import (
        get_thread,
        mark_control_action_applied,
        record_permission_request,
        reopen_reasked_permission_request,
        reserve_control_action,
        supersede_permission_requests,
    )
    from ..thread.enums import ControlActionType

    request_id = held.interrupt_id
    tool_call, pause_reason_type, description = _permission_request_fields(
        payload, held
    )
    if await get_thread(db, thread_id) is None:
        return
    reservation = await reserve_control_action(
        db,
        thread_id=thread_id,
        action_type=ControlActionType.PERMISSION_REQUEST_CREATED,
        request_id=request_id,
        idempotency_key=permission_request_action_key(request_id),
        payload={"description": description},
    )
    if not reservation.payload_matches:
        await db.rollback()
        return
    if not reservation.created:
        await reopen_reasked_permission_request(
            db,
            request_id=request_id,
            allowed_options=_option_mappings(payload.get("options")),
        )
        return
    # Nothing dispatches a request-creation action: writing it IS applying it.
    # It is settled through the journal's one settler, which stamps the instant
    # beside the status. Assigning the status alone left every such row applied
    # with no ``applied_at``, so a settled action was indistinguishable from one
    # still owed a delivery - and the recovery reads that tell them apart match
    # on the timestamp, not on the status.
    await mark_control_action_applied(db, reservation.action.id)
    await supersede_permission_requests(
        db,
        thread_id=thread_id,
        except_request_id=request_id,
    )
    await record_permission_request(
        db,
        request_id=request_id,
        thread_id=thread_id,
        pause_reason_type=pause_reason_type,
        description=description,
        allowed_options=_option_mappings(payload.get("options")),
        tool_call=tool_call,
    )


async def _handle_permission_event(
    thread_id: str,
    payload: dict[str, object],
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    checkpointer: Checkpointer | None = None,
) -> None:
    """Persist worker permission events into the durable journal.

    Validates the payload as a permission event, then dispatches to the request
    persistence stage or the resolution stage under one committed transaction.
    A request is journaled only against the interrupt its run's checkpoint
    holds, so the checkpoint read happens before the write transaction opens
    rather than while it holds the store's write lock.
    """
    if not is_permission_event(payload):
        return
    from ..database import begin_write_transaction

    factory = _session_factory(session_factory)
    if factory is None:
        _skip_without_database("the durable permission journal", thread_id)
        return
    if wire_event_type(payload) not in PERMISSION_REQUEST_EVENT_TYPES:
        async with factory() as db:
            await begin_write_transaction(db)
            await _apply_relayed_permission_resolution(db, thread_id, payload)
            await db.commit()
        return
    held = await _held_request_interrupt(thread_id, payload, checkpointer)
    if held is None:
        return
    async with factory() as db:
        await begin_write_transaction(db)
        await _persist_permission_request(db, thread_id, payload, held=held)
        await db.commit()


def _is_resume_receipt(payload: dict[str, object]) -> bool:
    """Whether a relayed event is the application receipt of a resume."""
    return (
        wire_event_type(payload) == "dispatch_applied"
        and payload.get("action") == "resume"
    )


async def _answered_request_id(
    db: AsyncSession, thread_id: str, payload: dict[str, object]
) -> str | None:
    """The request the resume a receipt proves applied was an answer to.

    The accepted action the receipt names is the answer that landed, and the
    request it answered is the only one this receipt says anything about.
    ``None`` for a resume that answered no permission request.
    """
    from ..database import get_control_action_by_dispatch_id
    from ..thread.enums import ControlActionType

    dispatch_id = payload.get("dispatch_id")
    if not isinstance(dispatch_id, str) or not dispatch_id:
        return None
    action = await get_control_action_by_dispatch_id(
        db, thread_id=thread_id, dispatch_id=dispatch_id
    )
    if (
        action is None
        or action.action_type != ControlActionType.PERMISSION_RESPONSE_SUBMITTED.value
    ):
        return None
    return action.request_id


async def _handle_reasked_permission_event(
    thread_id: str,
    payload: dict[str, object],
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    checkpointer: Checkpointer | None = None,
) -> None:
    """Reopen a permission request its run is holding again after answering it.

    The second prompt for the permission journal, beside the re-ask's own park
    frame. The worker emits that frame from inside the graph run while the
    application receipt waits for the checkpoint that proves the resume landed,
    so one relay batch can carry them in either order and the frame that arrives
    before the answer settles finds the row still being settled. This runs AFTER
    the settlement its own receipt proved, which is the moment the journal can
    tell a re-ask from an answer still in flight.

    Both prompts reopen through the one repository verb, whose precondition -
    the row has settled - is the single rule. Neither trusts the frame for
    whether the run is parked: the checkpoint says that, as it does for every
    interrupt kind.
    """
    if not _is_resume_receipt(payload):
        return
    factory = _session_factory(session_factory)
    if factory is None or checkpointer is None:
        return
    from ..database import (
        begin_write_transaction,
        read_latest_checkpoint,
        reopen_reasked_permission_request,
    )
    from ._permission_response_contract import held_interrupt
    from .pause import project_checkpoint_read

    async with factory() as db:
        request_id = await _answered_request_id(db, thread_id, payload)
        await db.rollback()
        if request_id is None:
            return
        projection = project_checkpoint_read(
            await read_latest_checkpoint(checkpointer, thread_id), thread_id
        )
        held = held_interrupt(projection, request_id)
        if held is None:
            return
        await begin_write_transaction(db)
        await reopen_reasked_permission_request(
            db,
            request_id=request_id,
            allowed_options=_option_mappings(held.payload.get("options")),
        )
        await db.commit()


async def _handle_progress_event(
    thread_id: str,
    payload: dict[str, object],
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    checkpointer: Checkpointer | None = None,
) -> None:
    """Settle one exact control action from a private worker receipt."""
    application = _validated_application_receipt(thread_id, payload)
    if application is None:
        return
    factory = _session_factory(session_factory)
    if factory is None:
        _skip_without_database("the control-action settlement", thread_id)
        return
    if checkpointer is None:
        logger.warning(
            "Skipping application receipt for %s: no checkpointer is available",
            thread_id,
            extra={"thread_id": thread_id, "action": "checkpoint_proof_unavailable"},
        )
        return
    async with factory() as db:
        stored_receipt = await _proven_application_receipt(
            db, thread_id, application, checkpointer
        )
        if stored_receipt is None:
            return
        await _commit_proven_application(db, thread_id, application, stored_receipt)


async def _handle_execution_state_event(
    thread_id: str,
    payload: dict[str, object],
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> None:
    """Persist worker-owned execution-state projection events."""
    if payload.get("type") != "execution_state_projection":
        return

    from ..database import begin_write_transaction, record_thread_execution_state

    projection = ExecutionStateProjectionPayload.model_validate(payload)
    factory = _session_factory(session_factory)
    if factory is None:
        _skip_without_database("the execution-state projection", thread_id)
        return
    async with factory() as db:
        await begin_write_transaction(db)
        await record_thread_execution_state(
            db,
            thread_id=thread_id,
            checkpoint_id=projection.checkpoint_id,
            parent_checkpoint_id=projection.parent_checkpoint_id,
            task_count=projection.task_count,
            interrupt_count=projection.interrupt_count,
            next_nodes=list(projection.next_nodes),
            tasks=[asdict(task) for task in projection.tasks],
            degraded_reasons=list(projection.degraded_reasons),
        )
        await db.commit()


def _prompts_pause_read(payload: dict[str, object]) -> bool:
    """Whether a relayed event says the run's pause may have moved.

    A clarification nudge or a permission request says the run may have
    parked; a permission resolution or a resume's application receipt says it
    may have left the pause. None of them is trusted for the answer: each only
    prompts the checkpoint read that decides.
    """
    event_type = wire_event_type(payload)
    if event_type == ServerEventType.CLARIFICATION_PENDING or is_permission_event(
        payload
    ):
        return True
    return event_type == "dispatch_applied" and payload.get("action") == "resume"


async def _handle_pause_event(
    thread_id: str,
    payload: dict[str, object],
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    checkpointer: Checkpointer | None = None,
) -> None:
    """Re-project the run's pause when a relayed event says it may have moved."""
    if not _prompts_pause_read(payload):
        return
    factory = _session_factory(session_factory)
    if factory is None:
        _skip_without_database("the pause projection", thread_id)
        return
    if checkpointer is None:
        logger.warning(
            "Skipping the pause projection for %s: no checkpointer is available",
            thread_id,
            extra={"thread_id": thread_id, "action": "pause_proof_unavailable"},
        )
        return
    from .pause import reconcile_run_pause

    async with factory() as db:
        await reconcile_run_pause(db, thread_id=thread_id, checkpointer=checkpointer)


async def relay_event(
    thread_id: str,
    payload: dict[str, object],
    services: RelayServices | None = None,
) -> None:
    """Run every event handler in sequence for one relayed worker event.

    Callers are responsible for routing execution-state projections before this
    general relay, fanning the frame out through the relay hub, and mirroring
    non-projection events into the hub's live run state.

    This function handles the DB-side event processing:
    permission journal, progress inference, the re-ask reopen, execution state
    persistence, the pause projection, and terminal status updates with relay
    hub GC.

    A terminal frame is the one exception to the caller owning the fan-out.
    Whether it may be shown at all is this plane's answer, so the caller hands
    it over as the services' *publish_terminal* and :func:`_handle_terminal_event`
    releases it; see that function for why.
    """
    resolved = services or RelayServices()
    await _handle_permission_event(
        thread_id,
        payload,
        session_factory=resolved.session_factory,
        checkpointer=resolved.checkpointer,
    )
    await _handle_progress_event(
        thread_id,
        payload,
        session_factory=resolved.session_factory,
        checkpointer=resolved.checkpointer,
    )
    # After the settlement above, never before it: a request its run is holding
    # again reads as re-asked only once the answer before it has settled.
    await _handle_reasked_permission_event(
        thread_id,
        payload,
        session_factory=resolved.session_factory,
        checkpointer=resolved.checkpointer,
    )
    await _handle_pause_event(
        thread_id,
        payload,
        session_factory=resolved.session_factory,
        checkpointer=resolved.checkpointer,
    )
    # Terminal status update + relay hub GC + drain-gate release.
    await _handle_terminal_event(thread_id, payload, resolved)
