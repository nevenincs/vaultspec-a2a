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

from ..ipc.schemas import ExecutionStateProjectionPayload
from ..providers import ProviderCondition
from ..thread.enums import InvalidTransitionError, ThreadStatus
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

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
) -> async_sessionmaker[AsyncSession]:
    """Select the injected session factory or the application factory."""
    if configured is not None:
        return configured
    from ..database import get_session_factory

    return get_session_factory()


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


def _object_mapping(value: object) -> dict[str, object] | None:
    """Validate a nested JSON-object value at the boundary."""
    try:
        return _JSON_OBJECT.validate_python(value)
    except ValidationError:
        return None


def _durable_provider_condition(value: object, *, status: ThreadStatus) -> str | None:
    """Resolve a relayed terminal's provider condition for the durable write.

    Only a member of the closed vocabulary is admitted. The column is read by a
    second repository that validates it against the same closed set, so relaying
    an unrecognised string through would hand that consumer a value it must
    reject - worse than the floor, which it can at least render.

    A FAILED terminal always yields a condition, falling back to the floor when
    the payload carried none or carried something unrecognised. That is the
    invariant this campaign establishes: a null condition on a failed run is a
    defect rather than a normal outcome, and enforcing it at the durable write
    means it holds however the terminal reached here. Any other status yields
    nothing at all, since the floor on a run that did not fail would read as a
    provider failure nobody observed.
    """
    if status != ThreadStatus.FAILED:
        return None
    if isinstance(value, str):
        try:
            return ProviderCondition(value).value
        except ValueError:
            logger.warning(
                "Discarding an unrecognised provider condition %r from a terminal"
                " event; recording the floor instead",
                value[:64],
            )
    return ProviderCondition.UNKNOWN.value


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
    lease = _object_mapping(data.get(_RUN_LEASE_METADATA_KEY))
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
    payload_status = payload.get("status")
    status_str = (
        _TERMINAL_STATUS_MAP.get(payload_status)
        if isinstance(payload_status, str)
        else None
    )
    if not status_str:
        return
    try:
        from ..database import (
            expire_pending_permission_requests,
            get_latest_control_action,
            mark_control_action_applied,
            set_thread_approval_state,
            set_thread_repair_state,
            update_thread_status,
        )
        from ..thread.enums import ControlActionType

        factory = _session_factory(session_factory)
        # error_detail rides the same thread_terminal payload the SSE relay
        # already surfaces it through (012840a4); threading it into the
        # durable status write here is the only additional step needed for a
        # reloaded panel (run-status alone, never the live stream) to recover
        # it too. update_thread_status leaves the column untouched on every
        # other outcome (completed, cancelled) since failure_reason is falsy.
        error_detail = payload.get("error_detail")
        failure_reason = error_detail if isinstance(error_detail, str) else None
        # The condition rides the same payload as the detail and is persisted
        # beside it, because the reason answers what happened and the condition
        # answers what the reader should do. A client that had to derive the
        # second from the first would be back to matching vendor prose, which is
        # the pattern this campaign exists to stop setting.
        provider_condition = _durable_provider_condition(
            payload.get("provider_condition"),
            status=ThreadStatus(status_str),
        )

        async with factory() as db:
            thread = await update_thread_status(
                db,
                thread_id,
                ThreadStatus(status_str),
                failure_reason=failure_reason,
                provider_condition=provider_condition,
            )
            await expire_pending_permission_requests(db, thread_id=thread_id)
            if thread is not None:
                await set_thread_approval_state(
                    db,
                    thread_id,
                    approval_status=None,
                    approval_request_id=None,
                    approval_reason=None,
                    approval_response_action_id=None,
                )
            latest_cancel = await get_latest_control_action(
                db, thread_id=thread_id, action_type=ControlActionType.CANCEL
            )
            effects = compute_terminal_effects(
                ThreadStatus(status_str),
                has_cancel_action=latest_cancel is not None,
            )
            if effects.should_finalize_cancel and latest_cancel is not None:
                await mark_control_action_applied(
                    db, latest_cancel.id, applied_at=_time_now_utc()
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
        logger.info(
            "Thread %s status updated to %s",
            thread_id,
            status_str,
            extra={
                "thread_id": thread_id,
                "status": status_str,
                "event_type": payload.get("event_type", ""),
                "action": "thread_terminal_status_updated",
            },
        )
        # The terminal status has just been persisted, and only the first terminal
        # event for a run reaches this point (a duplicate raises
        # InvalidTransitionError below), so this is the idempotent once-per-run
        # settlement trigger for complete, cancel, and fail. It authenticates to
        # the dashboard with attach-control only - never worker IPC - and carries
        # only the run and its non-secret lease identity.
        _schedule_terminal_settlement(thread_id, ThreadStatus(status_str), factory)
    except InvalidTransitionError:
        # Race condition — cancel endpoint already set terminal status.
        # This is expected and not an error.
        logger.info(
            "Thread %s transition to %s skipped (already terminal)",
            thread_id,
            status_str,
            extra={
                "thread_id": thread_id,
                "status": status_str,
                "event_type": payload.get("event_type", ""),
                "action": "thread_terminal_status_skipped",
            },
        )
    finally:
        # Release the run's admission on every exit above, including a failed
        # status write. The gate counts live executions, not successful
        # bookkeeping: the terminal event says the work is over, so releasing
        # after a failed write cannot let a drain quiesce over live work, while
        # withholding it there would strand exactly the flaky-database runs a
        # drain most needs to count correctly. Release is idempotent, so racing
        # with the cancel verb's release for the same run is safe.
        if drain_gate is not None:
            await drain_gate.release(thread_id)
        # The terminal status either committed or was already terminal, and every
        # other database exception still propagates after this finally block. Keep
        # the in-memory relay state aligned with that terminal observation only
        # after releasing the idempotent admission gate.
        if aggregator is not None:
            aggregator.clear_thread_state(thread_id)


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
        create_control_action,
        record_permission_request,
        set_thread_approval_state,
        set_thread_repair_state,
        supersede_permission_requests,
        update_thread_status,
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
    await supersede_permission_requests(
        db,
        thread_id=thread_id,
        except_request_id=request_id,
    )
    description_value = payload.get("description")
    description = description_value[:4096] if isinstance(description_value, str) else ""
    allowed_options = _option_mappings(payload.get("options"))
    await record_permission_request(
        db,
        request_id=request_id,
        thread_id=thread_id,
        pause_reason_type=pause_reason_type,
        description=description,
        allowed_options=allowed_options,
        tool_call=tool_call,
    )
    await create_control_action(
        db,
        thread_id=thread_id,
        action_type=ControlActionType.PERMISSION_REQUEST_CREATED,
        request_id=request_id,
        idempotency_key=f"permission-request:{request_id}",
        payload={"description": description},
        result_status=ControlActionResultStatus.APPLIED,
    )
    await update_thread_status(db, thread_id, fx.thread_status)
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
) -> str | None:
    """Settle one exact control action from a private worker receipt."""
    if payload.get("type") != "dispatch_applied":
        return
    from ..database import (
        get_control_action_by_dispatch_id,
        mark_control_action_applied,
        update_thread_status,
    )
    from ..thread.enums import ControlActionType
    from .repair_transitions import mark_message_followup_applied

    factory = _session_factory(session_factory)
    async with factory() as db:
        dispatch_value = payload.get("dispatch_id")
        dispatch_id = dispatch_value if isinstance(dispatch_value, str) else ""
        if not dispatch_id:
            return
        action = await get_control_action_by_dispatch_id(
            db,
            thread_id=thread_id,
            dispatch_id=dispatch_id,
        )
        if action is None or action.applied_at is not None:
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
    )
    if applied_permission_id is not None and aggregator is not None:
        aggregator.resolve_permission(applied_permission_id)
    # Terminal status update + aggregator GC + drain-gate release.
    await _handle_terminal_event(
        thread_id,
        payload,
        aggregator=aggregator,
        session_factory=session_factory,
        drain_gate=drain_gate,
    )
