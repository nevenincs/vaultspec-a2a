"""Event handlers for worker → gateway relay.

Business-logic handlers that persist worker events into the database,
manage permission state machines, and perform aggregator GC on thread
termination.  Extracted from ``api/internal.py`` to decouple protocol
translation from domain logic.

The :func:`relay_event` orchestrator consolidates the duplicated 4-handler
call sequence that previously appeared in 3 call sites.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import TypeAdapter, ValidationError

from ..ipc.schemas import (
    DispatchApplicationReceiptPayload,
    ExecutionStateProjectionPayload,
)
from ..providers import ProviderCondition
from ..thread.cancellation_evidence import CancellationEvidence
from ..thread.constants import MAX_PERMISSION_DESCRIPTION_CHARS
from ..thread.enums import ThreadStatus
from ..thread.failure_evidence import GraphFailureEvidence, failure_detail_fingerprint
from ..thread.permission_fsm import (
    compute_permission_request_effects,
    compute_permission_resolution_effects,
)
from ..thread.snapshots import (
    TERMINAL_STATUS_MAP,
    classify_permission_pause_reason,
    is_permission_event,
    is_terminal_event,
)
from ..thread.terminal_effects import compute_terminal_effects
from ..utils.coercion import coerce_object_mapping

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ..database.checkpoints import Checkpointer
    from ..streaming.aggregator import EventAggregator
    from .drain import DrainGate

__all__ = [
    "_handle_execution_state_event",
    "_handle_permission_event",
    "_handle_progress_event",
    "_handle_terminal_event",
    "relay_event",
]

logger = logging.getLogger(__name__)

_TERMINAL_STATUS_MAP = TERMINAL_STATUS_MAP


def _time_now_utc() -> datetime:
    """Return the current UTC timestamp for durable terminal effects."""
    from datetime import UTC

    return datetime.now(UTC)


# The metadata key binding a run to its non-secret admission lease identity,
# written by the gateway at commit; restated inline here to read it back, matching
# the metadata convention the frozen model profile uses.
_RUN_LEASE_METADATA_KEY = "run_lease"

# Strong references to in-flight settlement callbacks so a fire-and-forget task is
# not garbage-collected before it completes; each removes itself when done.
_settlement_tasks: set[asyncio.Task[None]] = set()
_JSON_OBJECT = TypeAdapter(dict[str, object])
_OPTION_MAPPINGS = TypeAdapter(list[dict[str, object]])


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


async def _persist_proven_cancellation(
    factory: async_sessionmaker[AsyncSession],
    *,
    thread_id: str,
    evidence: CancellationEvidence,
    last_sequence: int | None,
) -> bool:
    """Elect and settle one exact current cancellation terminal."""
    from ..database import (
        ThreadStatusElectionOutcome,
        elect_thread_status,
        expire_pending_permission_requests,
        get_control_action_by_dispatch_id,
        get_thread,
        mark_control_action_applied,
        set_thread_approval_state,
        set_thread_repair_state,
        successor_thread_write_authority,
        thread_write_expectation,
    )
    from ..thread.enums import ControlActionResultStatus, ControlActionType

    async with factory() as db:
        thread = await get_thread(db, thread_id)
        action = await get_control_action_by_dispatch_id(
            db, thread_id=thread_id, dispatch_id=evidence.dispatch_id
        )
        if (
            thread is None
            or action is None
            or action.action_type != ControlActionType.CANCEL.value
            or thread.status != ThreadStatus.CANCELLING.value
            or thread.writer_action_type != ControlActionType.CANCEL.value
            or thread.writer_action_receipt_id != evidence.dispatch_id
        ):
            await db.rollback()
            return False
        expectation = thread_write_expectation(thread)
        election = await elect_thread_status(
            db,
            thread_id,
            expectation=expectation,
            status=ThreadStatus.CANCELLED,
            successor=successor_thread_write_authority(
                expectation,
                action_type=ControlActionType.CANCEL,
                action_receipt_id=evidence.dispatch_id,
            ),
        )
        if election.outcome is not ThreadStatusElectionOutcome.WON:
            await db.rollback()
            return False
        if last_sequence is not None:
            thread.last_sequence = last_sequence
        await expire_pending_permission_requests(db, thread_id=thread_id)
        await set_thread_approval_state(
            db,
            thread_id,
            approval_status=None,
            approval_request_id=None,
            approval_reason=None,
            approval_response_action_id=None,
        )
        await mark_control_action_applied(
            db,
            action.id,
            applied_at=_time_now_utc(),
            result_status=(
                ControlActionResultStatus.CANCELLED_CEASED
                if evidence.outcome == "ceased"
                else ControlActionResultStatus.CANCELLED_NO_ACTIVE_WORK
            ),
        )
        effects = compute_terminal_effects(
            ThreadStatus.CANCELLED, has_cancel_action=True
        )
        await set_thread_repair_state(
            db,
            thread_id,
            repair_status=effects.repair_status,
            repair_reason=effects.repair_reason,
            execution_readiness=effects.repair_status.value,
            last_applied_action=effects.last_applied_action,
        )
        await db.commit()
        return True


async def _persist_proven_failure(
    factory: async_sessionmaker[AsyncSession],
    *,
    thread_id: str,
    evidence: GraphFailureEvidence,
    failure_reason: str,
    provider_condition: ProviderCondition,
    last_sequence: int | None,
) -> bool:
    """Elect and settle one failure for the exact current graph action."""
    from ..database import (
        ThreadStatusElectionOutcome,
        elect_thread_status,
        expire_pending_permission_requests,
        get_control_action_by_dispatch_id,
        get_thread,
        mark_control_action_applied,
        set_thread_approval_state,
        set_thread_repair_state,
        successor_thread_write_authority,
        thread_write_expectation,
    )
    from ..thread.enums import NON_ACTIVE_STATUSES
    from .dispatch_receipts import validate_current_graph_receipt

    async with factory() as db:
        thread = await get_thread(db, thread_id)
        action = await get_control_action_by_dispatch_id(
            db, thread_id=thread_id, dispatch_id=evidence.action.dispatch_id
        )
        if (
            thread is None
            or action is None
            or ThreadStatus(thread.status) in NON_ACTIVE_STATUSES
            or validate_current_graph_receipt(thread, action) != evidence.action
        ):
            await db.rollback()
            return False
        expectation = thread_write_expectation(thread)
        election = await elect_thread_status(
            db,
            thread_id,
            expectation=expectation,
            status=ThreadStatus.FAILED,
            successor=successor_thread_write_authority(
                expectation,
                action_type=evidence.action.action_type,
                action_receipt_id=evidence.action.dispatch_id,
            ),
            failure_reason=failure_reason,
            provider_condition=provider_condition.value,
        )
        if election.outcome is not ThreadStatusElectionOutcome.WON:
            await db.rollback()
            return False
        if last_sequence is not None:
            thread.last_sequence = last_sequence
        await mark_control_action_applied(db, action.id)
        await expire_pending_permission_requests(db, thread_id=thread_id)
        await set_thread_approval_state(
            db,
            thread_id,
            approval_status=None,
            approval_request_id=None,
            approval_reason=None,
            approval_response_action_id=None,
        )
        effects = compute_terminal_effects(ThreadStatus.FAILED, has_cancel_action=False)
        await set_thread_repair_state(
            db,
            thread_id,
            repair_status=effects.repair_status,
            repair_reason=effects.repair_reason,
            execution_readiness=effects.repair_status.value,
            last_applied_action=effects.last_applied_action,
        )
        await db.commit()
        return True


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


def _json_object(encoded: str) -> dict[str, object] | None:
    """Decode a JSON object without leaking untyped decoder output."""
    try:
        return _JSON_OBJECT.validate_json(encoded)
    except ValidationError:
        return None


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
    from ..control.config import settings

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
    if thread is None or not thread.thread_metadata:
        return None
    data = _json_object(thread.thread_metadata)
    if data is None:
        return None
    lease = coerce_object_mapping(data.get(_RUN_LEASE_METADATA_KEY))
    if lease is None:
        return None
    lease_id: object = lease.get("lease_id")
    return lease_id if isinstance(lease_id, str) and lease_id else None


async def _handle_terminal_event(
    thread_id: str,
    payload: dict[str, object],
    *,
    aggregator: EventAggregator | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    checkpointer: Checkpointer | None = None,
    drain_gate: DrainGate | None = None,
) -> None:
    """Update thread DB status when a ``thread_terminal`` event arrives.

    Called from both the WS and HTTP POST relay paths.  Imports are kept
    local to avoid circular dependencies at module level.

    When *aggregator* is provided, prune stale permissions and sequence
    counters for the terminated thread.

    When *drain_gate* is provided, this is the run's primary release site: a
    validated terminal event is the end of the run's execution, so the run
    leaves the drain gate's active set here and a drain can finally quiesce.
    """
    if not is_terminal_event(payload):
        return
    # Captured HERE, before anything else runs, and never re-read later: the
    # ordering is the whole fix (F19). aggregator.clear_thread_state below (in
    # the finally block, after the durable write commits) prunes this exact
    # thread's counter from the aggregator's in-memory _sequences dict, so a
    # value read after that point is always the pruned default (0) -- which is
    # what a REST client reading run-status after a run settles always saw,
    # since that read is the only moment its reconnect-cursor comparison
    # matters. Capturing before the durable write below, rather than near it,
    # means a future reordering of the write can never accidentally re-open
    # this race by moving the read closer to the prune.
    last_sequence = (
        aggregator.get_sequence(thread_id) if aggregator is not None else None
    )
    payload_status = payload.get("status")
    status_str = (
        _TERMINAL_STATUS_MAP.get(payload_status)
        if isinstance(payload_status, str)
        else None
    )
    if not status_str:
        return
    terminal_status = ThreadStatus(status_str)
    factory = _session_factory(session_factory)
    raw_cancellation_evidence = payload.get("cancellation_evidence")
    raw_failure_evidence = payload.get("failure_evidence")
    if (
        raw_cancellation_evidence is not None
        and terminal_status is not ThreadStatus.CANCELLED
    ):
        logger.warning(
            "Refusing cancellation evidence on non-cancelled terminal for %s",
            thread_id,
        )
        return
    if raw_failure_evidence is not None and terminal_status is not ThreadStatus.FAILED:
        logger.warning(
            "Refusing failure evidence on non-failed terminal for %s",
            thread_id,
        )
        return
    if terminal_status is ThreadStatus.COMPLETED:
        if factory is None:
            _skip_without_database("the completion reconciliation", thread_id)
            return
        if checkpointer is None:
            logger.warning(
                "Refusing completion for %s: no checkpointer is available",
                thread_id,
                extra={
                    "thread_id": thread_id,
                    "action": "completion_proof_unavailable",
                },
            )
            return
        from ..domain_config import domain_config
        from .recovery_authority import RecoveryTrigger, reconcile_run_checkpoint

        async with factory() as db:
            observation = await reconcile_run_checkpoint(
                db,
                checkpointer,
                thread_id,
                trigger=RecoveryTrigger.WORKER_EVENT,
                checkpoint_timeout_seconds=domain_config.aget_state_timeout_seconds,
                last_sequence=last_sequence,
            )
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
            return
        _schedule_terminal_settlement(thread_id, terminal_status, factory)
        if drain_gate is not None:
            await drain_gate.release(thread_id)
        if aggregator is not None:
            aggregator.clear_thread_state(thread_id)
        return
    if raw_cancellation_evidence is not None:
        try:
            cancellation_evidence = CancellationEvidence.model_validate(
                raw_cancellation_evidence
            )
        except ValidationError:
            logger.warning(
                "Refusing invalid cancellation evidence for thread %s",
                thread_id,
                extra={
                    "thread_id": thread_id,
                    "action": "invalid_cancellation_evidence",
                },
            )
            return
        cancellation_factory = _session_factory(session_factory)
        if cancellation_factory is None:
            _skip_without_database("the cancellation terminal election", thread_id)
            return
        accepted = await _persist_proven_cancellation(
            cancellation_factory,
            thread_id=thread_id,
            evidence=cancellation_evidence,
            last_sequence=last_sequence,
        )
        if not accepted:
            logger.warning(
                "Refusing stale cancellation evidence for thread %s",
                thread_id,
                extra={
                    "thread_id": thread_id,
                    "dispatch_id": cancellation_evidence.dispatch_id,
                    "action": "stale_cancellation_evidence",
                },
            )
            return
        _schedule_terminal_settlement(
            thread_id, ThreadStatus.CANCELLED, cancellation_factory
        )
        if drain_gate is not None:
            await drain_gate.release(thread_id)
        if aggregator is not None:
            aggregator.clear_thread_state(thread_id)
        return
    if terminal_status is ThreadStatus.CANCELLED:
        logger.warning(
            "Refusing cancellation without exact cessation evidence for %s",
            thread_id,
            extra={"thread_id": thread_id, "action": "missing_cancellation_evidence"},
        )
        return
    if terminal_status is ThreadStatus.FAILED:
        if raw_failure_evidence is None:
            logger.warning(
                "Refusing failure without exact action evidence for %s",
                thread_id,
                extra={"thread_id": thread_id, "action": "missing_failure_evidence"},
            )
            return
        try:
            failure_evidence = GraphFailureEvidence.model_validate(raw_failure_evidence)
        except ValidationError:
            logger.warning(
                "Refusing invalid failure evidence for thread %s",
                thread_id,
                extra={"thread_id": thread_id, "action": "invalid_failure_evidence"},
            )
            return
        error_detail = payload.get("error_detail")
        raw_condition = payload.get("provider_condition")
        if not isinstance(error_detail, str) or not error_detail:
            return
        try:
            provider_condition = ProviderCondition(raw_condition)
        except (TypeError, ValueError):
            return
        if (
            failure_evidence.detail_fingerprint
            != failure_detail_fingerprint(error_detail)
            or failure_evidence.provider_condition != provider_condition.value
        ):
            logger.warning(
                "Refusing mismatched failure evidence for thread %s",
                thread_id,
                extra={"thread_id": thread_id, "action": "mismatched_failure_evidence"},
            )
            return
        if factory is None:
            _skip_without_database("the failure terminal election", thread_id)
            return
        accepted = await _persist_proven_failure(
            factory,
            thread_id=thread_id,
            evidence=failure_evidence,
            failure_reason=error_detail,
            provider_condition=provider_condition,
            last_sequence=last_sequence,
        )
        if not accepted:
            logger.warning(
                "Refusing stale failure evidence for thread %s",
                thread_id,
                extra={"thread_id": thread_id, "action": "stale_failure_evidence"},
            )
            return
        _schedule_terminal_settlement(thread_id, terminal_status, factory)
        if drain_gate is not None:
            await drain_gate.release(thread_id)
        if aggregator is not None:
            aggregator.clear_thread_state(thread_id)
        return


_PERMISSION_REQUEST_EVENT_TYPES = frozenset(
    {"permission_request", "plan_approval_request", "document_approval_request"}
)


async def _persist_permission_request(
    db: AsyncSession,
    thread_id: str,
    payload: dict[str, object],
    *,
    event_type: str,
) -> None:
    """Persist a fresh permission/approval request into the durable journal.

    Supersedes any competing pending requests, records the request row and its
    creation control action, and projects the resulting pause onto thread status,
    repair state, and - for a plan approval - approval state. A payload with no
    request id is ignored, matching the prior inline guard.
    """
    from ..database import (
        ThreadStatusElectionOutcome,
        elect_thread_status,
        get_thread,
        record_permission_request,
        reserve_control_action,
        set_thread_approval_state,
        set_thread_repair_state,
        successor_thread_write_authority,
        supersede_permission_requests,
        thread_write_expectation,
    )
    from ..thread.enums import (
        ApprovalStatus,
        ControlActionResultStatus,
        ControlActionType,
    )

    request_value = payload.get("request_id")
    request_id = request_value if isinstance(request_value, str) else ""
    if not request_id:
        return
    tool_value = payload.get("tool_call")
    tool_call = tool_value if isinstance(tool_value, str) else None
    pause_reason_type = (
        event_type
        if event_type in {"plan_approval_request", "document_approval_request"}
        else classify_permission_pause_reason(tool_call)
    )
    fx = compute_permission_request_effects(pause_reason_type)
    thread = await get_thread(db, thread_id)
    if thread is None:
        return
    expectation = thread_write_expectation(thread)
    description_value = payload.get("description")
    # The same declaration the streamed permission frame truncates at, so the
    # row a reload replays from cannot hold less than the operator was shown.
    description = (
        description_value[:MAX_PERMISSION_DESCRIPTION_CHARS]
        if isinstance(description_value, str)
        else ""
    )
    allowed_options = _option_mappings(payload.get("options"))
    reservation = await reserve_control_action(
        db,
        thread_id=thread_id,
        action_type=ControlActionType.PERMISSION_REQUEST_CREATED,
        request_id=request_id,
        idempotency_key=f"permission-request:{request_id}",
        payload={"description": description},
    )
    if not reservation.payload_matches:
        await db.rollback()
        return
    action = reservation.action
    action.result_status = ControlActionResultStatus.APPLIED.value
    if action.dispatch_id is None:
        await db.rollback()
        raise RuntimeError("permission-request action has no durable receipt")
    if (
        expectation.status is fx.thread_status
        and expectation.authority.action_type
        is ControlActionType.PERMISSION_REQUEST_CREATED
        and expectation.authority.action_receipt_id == action.dispatch_id
    ):
        await db.rollback()
        return
    if not reservation.created:
        # A persisted creation receipt proves only that this event was handled
        # before. Once a newer action owns the run, replaying the old event must
        # never reinstall its receipt or reopen the old permission pause.
        await db.rollback()
        return
    election = await elect_thread_status(
        db,
        thread_id,
        expectation=expectation,
        status=fx.thread_status,
        successor=successor_thread_write_authority(
            expectation,
            action_type=ControlActionType.PERMISSION_REQUEST_CREATED,
            action_receipt_id=action.dispatch_id,
        ),
    )
    if election.outcome is not ThreadStatusElectionOutcome.WON:
        await db.rollback()
        return
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
        allowed_options=allowed_options,
        tool_call=tool_call,
    )
    await set_thread_repair_state(
        db,
        thread_id,
        repair_status=fx.repair_status,
        repair_reason=fx.repair_reason,
        execution_readiness=fx.repair_status.value,
        last_applied_action=fx.last_applied_action,
    )
    if fx.is_plan_approval:
        await set_thread_approval_state(
            db,
            thread_id,
            approval_status=ApprovalStatus.PENDING,
            approval_request_id=request_id,
            approval_reason=description,
            approval_response_action_id=None,
        )


async def _apply_permission_resolution(
    db: AsyncSession,
    thread_id: str,
    payload: dict[str, object],
) -> None:
    """Finalize a worker-applied permission resolution into the journal.

    Only a request still in ``answered_pending_apply`` is settled: its row is
    marked applied and the resolution is projected onto the applied control
    action, repair state, and - for a plan approval - approval state. Any other
    state is a no-op, matching the prior inline guard.
    """
    from ..database import (
        create_control_action,
        get_control_action_by_idempotency_key,
        get_permission_request,
        mark_control_action_applied,
        mark_permission_request_applied,
        set_thread_approval_state,
        set_thread_repair_state,
    )
    from ..thread.enums import ControlActionResultStatus
    from .permission_service import permission_response_action_key

    request_value = payload.get("request_id")
    request_id = request_value if isinstance(request_value, str) else ""
    permission = await get_permission_request(db, request_id)
    if permission is None or permission.request_status != "answered_pending_apply":
        return
    fx_res = compute_permission_resolution_effects(
        permission.response_option_id,
        permission.pause_reason_type,
        permission.allowed_options_json,
    )
    await mark_permission_request_applied(
        db, request_id=request_id, status=fx_res.target_status
    )
    submitted = await get_control_action_by_idempotency_key(
        db,
        thread_id=thread_id,
        idempotency_key=permission_response_action_key(request_id),
    )
    if submitted is not None and submitted.applied_at is None:
        await mark_control_action_applied(db, submitted.id)
    await create_control_action(
        db,
        thread_id=thread_id,
        action_type=fx_res.last_applied_action,
        request_id=request_id,
        idempotency_key=f"permission-response-applied:{request_id}",
        payload={"request_id": request_id},
        result_status=ControlActionResultStatus.APPLIED,
    )
    await set_thread_repair_state(
        db,
        thread_id,
        repair_status=fx_res.repair_status,
        repair_reason=fx_res.repair_reason,
        execution_readiness=fx_res.repair_status.value,
        last_applied_action=fx_res.last_applied_action,
    )
    if fx_res.is_plan_approval:
        await set_thread_approval_state(
            db,
            thread_id,
            approval_status=fx_res.approval_status,
            approval_request_id=request_id,
            approval_reason=permission.description,
        )


async def _handle_permission_event(
    thread_id: str,
    payload: dict[str, object],
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> None:
    """Persist worker permission events into the durable journal.

    Validates the payload as a permission event, then dispatches to the request
    persistence stage or the resolution stage under one committed transaction.
    """
    if not is_permission_event(payload):
        return
    event_value = payload.get("type")
    event_type = event_value if isinstance(event_value, str) else ""
    factory = _session_factory(session_factory)
    if factory is None:
        _skip_without_database("the durable permission journal", thread_id)
        return
    async with factory() as db:
        if event_type in _PERMISSION_REQUEST_EVENT_TYPES:
            await _persist_permission_request(
                db, thread_id, payload, event_type=event_type
            )
        else:
            await _apply_permission_resolution(db, thread_id, payload)
        await db.commit()


async def _handle_progress_event(
    thread_id: str,
    payload: dict[str, object],
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    checkpointer: Checkpointer | None = None,
) -> str | None:
    """Settle one exact control action from a private worker receipt."""
    if payload.get("type") != "dispatch_applied":
        return
    from ..database import (
        ControlActionModel,
        ThreadModel,
        get_control_action_by_dispatch_id,
        get_thread,
        mark_control_action_applied,
        update_thread_status,
    )
    from ..thread.checkpoint_evidence import read_checkpoint_evidence
    from ..thread.enums import ControlActionType
    from .repair_transitions import mark_message_followup_applied

    try:
        application = DispatchApplicationReceiptPayload.model_validate(payload)
    except ValidationError:
        logger.warning(
            "Refusing invalid dispatch application receipt for thread %s",
            thread_id,
            extra={"thread_id": thread_id, "action": "invalid_application_receipt"},
        )
        return
    if application.graph_action_receipt.thread_id != thread_id:
        logger.warning(
            "Refusing cross-thread dispatch application receipt for thread %s",
            thread_id,
            extra={
                "thread_id": thread_id,
                "action": "cross_thread_application_receipt",
            },
        )
        return
    receipt_action = application.graph_action_receipt.action_type
    expected_transport_action = (
        "ingest"
        if receipt_action
        in {
            ControlActionType.INGEST,
            ControlActionType.MESSAGE_FOLLOWUP_REQUESTED,
        }
        else "resume"
    )
    if application.action != expected_transport_action:
        logger.warning(
            "Refusing mismatched dispatch application verb for thread %s",
            thread_id,
            extra={"thread_id": thread_id, "action": "mismatched_application_verb"},
        )
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
        action = await get_control_action_by_dispatch_id(
            db,
            thread_id=thread_id,
            dispatch_id=application.dispatch_id,
        )
        thread = await get_thread(db, thread_id)
        if action is None or thread is None or action.applied_at is not None:
            return
        from .dispatch_receipts import validate_current_graph_receipt

        stored_receipt = validate_current_graph_receipt(thread, action)
        if stored_receipt != application.graph_action_receipt:
            logger.warning(
                "Refusing non-current dispatch application receipt for thread %s",
                thread_id,
                extra={
                    "thread_id": thread_id,
                    "dispatch_id": application.dispatch_id,
                    "action": "non_current_application_receipt",
                },
            )
            return
        await db.commit()
        from ..domain_config import domain_config

        evidence = await read_checkpoint_evidence(
            checkpointer,
            stored_receipt,
            timeout_seconds=domain_config.aget_state_timeout_seconds,
            checkpoint_id=application.checkpoint_id,
        )
        if not evidence.incorporated:
            logger.warning(
                "Refusing %s dispatch application receipt for thread %s",
                evidence.kind.value,
                thread_id,
                extra={
                    "thread_id": thread_id,
                    "dispatch_id": application.dispatch_id,
                    "checkpoint_id": application.checkpoint_id,
                    "condition": evidence.kind.value,
                    "action": "unincorporated_application_receipt",
                },
            )
            return
        from sqlalchemy import select

        thread = await db.scalar(
            select(ThreadModel)
            .where(ThreadModel.id == thread_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        action = await db.scalar(
            select(ControlActionModel)
            .where(
                ControlActionModel.thread_id == thread_id,
                ControlActionModel.dispatch_id == application.dispatch_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            action is None
            or thread is None
            or action.applied_at is not None
            or validate_current_graph_receipt(thread, action) != stored_receipt
        ):
            return
        if action.action_type == ControlActionType.MESSAGE_FOLLOWUP_REQUESTED.value:
            await mark_control_action_applied(db, action.id)
            await mark_message_followup_applied(db, thread_id)
            await db.commit()
            return
        if (
            action.action_type == ControlActionType.PERMISSION_RESPONSE_SUBMITTED.value
            and action.request_id is not None
        ):
            await _apply_permission_resolution(
                db,
                thread_id,
                {"request_id": action.request_id},
            )
            await update_thread_status(db, thread_id, ThreadStatus.RUNNING)
            await db.commit()
            return action.request_id
        from .verdict_subscriber import settle_verdict_dispatch_receipt

        if await settle_verdict_dispatch_receipt(db, action):
            await db.commit()


async def _handle_execution_state_event(
    thread_id: str,
    payload: dict[str, object],
    *,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> None:
    """Persist worker-owned execution-state projection events."""
    if payload.get("type") != "execution_state_projection":
        return

    from ..database import record_thread_execution_state

    projection = ExecutionStateProjectionPayload.model_validate(payload)
    snapshot_created_at: datetime | None = None
    if projection.snapshot_created_at is not None:
        try:
            snapshot_created_at = datetime.fromisoformat(projection.snapshot_created_at)
        except ValueError:
            snapshot_created_at = None

    factory = _session_factory(session_factory)
    if factory is None:
        _skip_without_database("the execution-state projection", thread_id)
        return
    async with factory() as db:
        await record_thread_execution_state(
            db,
            thread_id=thread_id,
            checkpoint_id=projection.checkpoint_id,
            parent_checkpoint_id=projection.parent_checkpoint_id,
            snapshot_created_at=snapshot_created_at,
            task_count=projection.task_count,
            interrupt_count=projection.interrupt_count,
            next_nodes=list(projection.next_nodes),
            interrupt_types=list(projection.interrupt_types),
            tasks=[task.model_dump(mode="json") for task in projection.tasks],
            degraded_reasons=list(projection.degraded_reasons),
        )
        await db.commit()


async def relay_event(
    thread_id: str,
    payload: dict[str, object],
    *,
    aggregator: EventAggregator | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    checkpointer: Checkpointer | None = None,
    drain_gate: DrainGate | None = None,
) -> None:
    """Consolidated relay: run all 4 event handlers in sequence.

    This replaces the 3x duplicated handler call sequence that previously
    appeared in ``_relay_worker_event``, ``receive_worker_event``, and
    ``receive_worker_event_batch``.

    Callers are responsible for routing execution-state projections before this
    general relay, broadcasting to WS clients via ConnectionManager, and syncing
    non-projection events into the aggregator.

    This function handles the DB-side event processing:
    permission journal, progress inference, execution state persistence,
    and terminal status updates with aggregator GC.
    """
    await _handle_permission_event(
        thread_id,
        payload,
        session_factory=session_factory,
    )
    await _handle_execution_state_event(
        thread_id,
        payload,
        session_factory=session_factory,
    )
    applied_permission_id = await _handle_progress_event(
        thread_id,
        payload,
        session_factory=session_factory,
        checkpointer=checkpointer,
    )
    if applied_permission_id is not None and aggregator is not None:
        aggregator.resolve_permission(applied_permission_id)
    # Terminal status update + aggregator GC + drain-gate release.
    await _handle_terminal_event(
        thread_id,
        payload,
        aggregator=aggregator,
        session_factory=session_factory,
        checkpointer=checkpointer,
        drain_gate=drain_gate,
    )
