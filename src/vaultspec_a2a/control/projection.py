"""Helpers for repair-aware thread snapshot projection."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pydantic import TypeAdapter, ValidationError

from ..database import (
    actionable_pending_permissions,
    get_pending_permission_requests,
    get_thread_execution_state,
)
from ..utils.coercion import coerce_object_mapping
from .repositories.continuation_queue import count_queued_continuations

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from ..database import (
        PendingPermission,
        ThreadExecutionStateModel,
        ThreadModel,
    )

from ..graph.acp_options import option_id_of, option_kind
from ..graph.enums import PermissionType
from ..ipc.schemas import ExecutionTaskProjectionPayload
from ..streaming.types import classify_tool_kind
from ..thread.clarification import pending_clarification
from ..thread.enums import (
    TERMINAL_STATUS_VALUES,
    ApprovalStatus,
    DegradedReason,
    RepairStatus,
    ThreadStatus,
)
from ..thread.snapshots import (
    PERMISSION_REQUEST_EVENT_TYPES,
    PLAN_APPROVAL_PAUSE_CAUSES,
    CheckpointProjection,
    ExecutionStateProjection,
    ExecutionTaskData,
    PermissionData,
    PermissionOptionData,
    ThreadStateData,
    record_repair_posture,
)

__all__ = [
    "apply_authoring_completion_check",
    "apply_checkpoint_projection",
    "apply_execution_state_projection",
    "clear_permissions_without_checkpoint_truth",
    "durable_approval",
    "enrich_snapshot_from_durable_state",
    "enrich_snapshot_from_execution_state",
    "escalate_repair_posture",
    "execution_state_is_stale",
    "mark_degraded",
    "project_execution_state_model",
    "reconcile_checkpoint_permissions_with_durable_state",
]

_JSON_LIST_ADAPTER = TypeAdapter(list[object])

#: How far each degraded repair posture holds a run back. The postures absent
#: here (healthy, paused, cancel pending) demand nothing and yield to all of them.
_REPAIR_SEVERITY: dict[str, int] = {
    RepairStatus.REPLAY_GAP: 1,
    RepairStatus.NEEDS_RECONCILIATION: 2,
    RepairStatus.CHECKPOINT_UNAVAILABLE: 3,
    RepairStatus.OPERATOR_INTERVENTION_REQUIRED: 4,
}


def _decode_json_list(raw: str | None, *, field_name: str) -> list[object]:
    """Decode a persisted JSON list at the projection trust boundary."""
    if raw is None:
        return []
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = f"Could not decode {field_name}"
        raise ValueError(msg) from exc
    try:
        return _JSON_LIST_ADAPTER.validate_python(decoded)
    except ValidationError as exc:
        msg = f"{field_name} must decode to a list"
        raise ValueError(msg) from exc


def escalate_repair_posture(current: str | None, demanded: RepairStatus) -> str:
    """Apply a demanded repair posture to *current*, fail-closed.

    The posture moves to *demanded* unless it already demands at least as much,
    so a cause found late in a read can never talk a run back down from the
    posture an earlier cause put it in.
    """
    demanded_severity = _REPAIR_SEVERITY.get(demanded, 0)
    if current is None or _REPAIR_SEVERITY.get(current, 0) < demanded_severity:
        return demanded.value
    return current


def mark_degraded(
    snapshot: ThreadStateData,
    reason: DegradedReason,
    *,
    repair: RepairStatus | None = None,
) -> None:
    """Record why *snapshot* is less than complete, once per reason.

    *repair* is the repair posture the cause demands of the run, applied through
    :func:`escalate_repair_posture`. A cause that says nothing about checkpoint
    lineage passes none and leaves the posture as it is.
    """
    snapshot.snapshot_complete = False
    if reason not in snapshot.degraded_reasons:
        snapshot.degraded_reasons.append(reason)
    if repair is not None:
        record_repair_posture(
            snapshot, escalate_repair_posture(snapshot.repair_status, repair)
        )


def apply_authoring_completion_check(
    snapshot: ThreadStateData,
    *,
    thread_status: str,
    requires_document_authoring: bool,
    proposal_ids: list[str],
    changeset_ids: list[str],
) -> ThreadStateData:
    """Flag a completed document-authoring run that produced no artifact.

    A document-authoring preset (the research_adr phase machine or the solo
    doc-editor lane) reaching ``completed`` with both
    ``authoring_proposal_ids`` and ``authoring_changeset_ids`` empty means the
    run's authoring tool call never landed - a silent-success gap where
    ``status: completed`` reported clean while nothing was produced. Scoped to
    the literal ``completed`` status (not the broader "completed" semantic
    phase, which also covers ``archived``): the reported gap was a freshly
    completed run, and archival is a distinct post-completion lifecycle this
    check has not been proven against.

    Non-authoring presets, and threads that have not reached this exact
    status, pass through untouched. Callers must gate this on a checkpoint
    that was actually read (``proposal_ids``/``changeset_ids`` derived from a
    successfully loaded snapshot) - an unreadable checkpoint already carries
    its own "unavailable" degraded reason, and asserting emptiness on top of
    that would misreport "unread" as "produced nothing".
    """
    if (
        requires_document_authoring
        and thread_status == ThreadStatus.COMPLETED.value
        and not proposal_ids
        and not changeset_ids
    ):
        # No repair posture: the repair columns classify checkpoint-lineage
        # integrity, and this checkpoint is healthy. Demanding reconciliation
        # here would make that signal ambiguous between corruption and an
        # empty result.
        mark_degraded(snapshot, DegradedReason.AUTHORING_RUN_PRODUCED_NO_PROPOSAL)
    return snapshot


def _clear_non_actionable_pause_state(snapshot: ThreadStateData) -> None:
    """Clear pause metadata when no user-actionable permission remains."""
    if snapshot.pending_permissions:
        return
    if snapshot.approval_status is not None or snapshot.approval_request_id is not None:
        return
    snapshot.pause_cause = None


def clear_permissions_without_checkpoint_truth(
    snapshot: ThreadStateData,
) -> ThreadStateData:
    """Fail closed when pending approval state has no checkpoint authority."""
    had_actionable_permission_state = bool(snapshot.pending_permissions) or bool(
        snapshot.approval_status
        or snapshot.approval_request_id
        or snapshot.pause_cause
        or snapshot.pending_clarification
    )
    snapshot.pending_permissions = []
    snapshot.pending_clarification = None
    snapshot.approval_status = None
    snapshot.approval_request_id = None
    _clear_non_actionable_pause_state(snapshot)
    if had_actionable_permission_state:
        mark_degraded(
            snapshot, DegradedReason.PENDING_PERMISSION_WITHOUT_CHECKPOINT_TRUTH
        )
    return snapshot


def _permission_data_from_pending(
    pending: PendingPermission,
) -> PermissionData | None:
    """Project one pending request, or None when its options are unreadable."""
    raw_options = pending.offered
    if raw_options is None:
        return None
    permission = pending.request
    tool_call = permission.tool_call
    if (
        tool_call in (None, "")
        and permission.pause_reason_type in PLAN_APPROVAL_PAUSE_CAUSES
    ):
        tool_call = PermissionType.PLAN_APPROVAL.value
    options: list[PermissionOptionData] = []
    for raw_option in raw_options:
        option = coerce_object_mapping(raw_option)
        if option is None:
            continue
        options.append(
            PermissionOptionData(
                option_id=option_id_of(option) or "",
                name=str(option.get("name", "")),
                kind=str(option_kind(option)),
            )
        )
    return PermissionData(
        request_id=permission.request_id,
        description=permission.description,
        options=options,
        tool_call=tool_call,
        tool_kind=str(classify_tool_kind(tool_call)) if tool_call else None,
    )


def apply_checkpoint_projection(
    snapshot: ThreadStateData,
    projection: CheckpointProjection,
) -> ThreadStateData:
    """Merge a normalized checkpoint projection into the snapshot."""
    snapshot.checkpoint_id = projection.checkpoint_id
    snapshot.checkpoint_created_at = projection.checkpoint_created_at
    snapshot.checkpoint_parent_id = projection.checkpoint_parent_id
    snapshot.checkpoint_source = projection.checkpoint_source
    snapshot.checkpoint_step = projection.checkpoint_step
    snapshot.checkpoint_updated_channels = list(projection.checkpoint_updated_channels)
    snapshot.pending_write_channels = list(projection.pending_write_channels)
    snapshot.pending_write_count = projection.pending_write_count
    snapshot.history_depth = projection.history_depth
    if snapshot.pause_cause is None:
        snapshot.pause_cause = projection.pause_cause
    # Checkpoint-truth disclosure only: the parked questionnaire is read from
    # this projection and from nowhere else.
    snapshot.pending_clarification = pending_clarification(projection)

    for reason in projection.degraded_reasons:
        mark_degraded(snapshot, reason)
    if any(
        interrupt_type in PERMISSION_REQUEST_EVENT_TYPES
        for interrupt_type in projection.unnamed_interrupt_types
    ):
        # A permission naming no request still holds the run, and no answer can
        # be addressed to it, so the run needs reconciling exactly as when a
        # parked permission has no durable row.
        mark_degraded(
            snapshot,
            DegradedReason.INTERRUPT_PAYLOAD_UNREADABLE,
            repair=RepairStatus.NEEDS_RECONCILIATION,
        )

    return snapshot


def reconcile_checkpoint_permissions_with_durable_state(
    snapshot: ThreadStateData,
    projection: CheckpointProjection,
) -> ThreadStateData:
    """Fail closed when the checkpoint is parked on a permission with no durable row.

    The durable row is the only source of a pending permission's content, so
    ``snapshot.pending_permissions`` holds exactly the readable durable rows and
    the checkpoint contributes nothing but the request ids it is parked on. A
    parked request with no row is a pause the respond route cannot act on: it
    demands reconciliation and withdraws any approval it names.
    """
    durable_request_ids = {
        permission.request_id for permission in snapshot.pending_permissions
    }
    orphaned_request_ids = {
        interrupt.interrupt_id
        for interrupt in projection.pending_interrupts
        if interrupt.interrupt_type in PERMISSION_REQUEST_EVENT_TYPES
        and interrupt.interrupt_id not in durable_request_ids
    }
    if not orphaned_request_ids:
        return snapshot

    mark_degraded(
        snapshot,
        DegradedReason.CHECKPOINT_PERMISSION_WITHOUT_DURABLE_ROW,
        repair=RepairStatus.NEEDS_RECONCILIATION,
    )

    if snapshot.approval_request_id in orphaned_request_ids:
        snapshot.approval_status = None
        snapshot.approval_request_id = None
    _clear_non_actionable_pause_state(snapshot)

    return snapshot


def project_execution_state_model(
    model: ThreadExecutionStateModel,
) -> ExecutionStateProjection:
    """Project a durable execution-state row into normalized data."""
    next_nodes = [
        str(item)
        for item in _decode_json_list(
            model.next_nodes_json,
            field_name="next_nodes_json",
        )
    ]
    raw_tasks = _decode_json_list(model.tasks_json, field_name="tasks_json")
    execution_tasks: list[ExecutionTaskData] = []
    for raw_task in raw_tasks:
        task_data = coerce_object_mapping(raw_task)
        if task_data is None:
            continue
        try:
            persisted_task = ExecutionTaskProjectionPayload.model_validate(
                {"task_id": "", "name": "", **task_data}
            )
        except ValidationError:
            continue
        execution_tasks.append(
            ExecutionTaskData(
                task_id=persisted_task.task_id,
                name=persisted_task.name,
                path=persisted_task.path,
                has_error=persisted_task.has_error,
                error_type=persisted_task.error_type,
                interrupt_ids=persisted_task.interrupt_ids,
                interrupt_types=persisted_task.interrupt_types,
                has_nested_state=persisted_task.has_nested_state,
                has_result=persisted_task.has_result,
            )
        )
    # A reason outside the vocabulary makes the row unreadable here, at the
    # trust boundary, rather than failing the narrowed field it would reach.
    degraded_reasons = [
        DegradedReason(str(item))
        for item in _decode_json_list(
            model.degraded_reasons_json,
            field_name="degraded_reasons_json",
        )
    ]
    return ExecutionStateProjection(
        task_count=model.task_count,
        interrupt_count=model.interrupt_count,
        next_nodes=next_nodes,
        execution_tasks=execution_tasks,
        degraded_reasons=degraded_reasons,
    )


def apply_execution_state_projection(
    snapshot: ThreadStateData,
    projection: ExecutionStateProjection,
) -> ThreadStateData:
    """Merge a durable execution-state projection into the snapshot."""
    snapshot.next_nodes = list(projection.next_nodes)
    snapshot.task_count = projection.task_count
    snapshot.pending_interrupt_count = projection.interrupt_count
    snapshot.execution_tasks = list(projection.execution_tasks)
    for reason in projection.degraded_reasons:
        mark_degraded(snapshot, reason)
    return snapshot


def durable_approval(
    pending: Sequence[PendingPermission],
) -> tuple[ApprovalStatus | None, str | None]:
    """Return the plan approval a run's live pending requests leave actionable.

    The latest plan-approval request is pending when it offers an option the
    respond route would accept. An unreadable plan-approval request withholds the
    approval altogether: once one of them cannot be read, the run's approval
    state can no longer be trusted, whichever request it would have named.
    """
    plan_approvals = [
        entry
        for entry in pending
        if entry.request.pause_reason_type in PLAN_APPROVAL_PAUSE_CAUSES
    ]
    if not plan_approvals:
        return None, None
    if any(entry.offered is None for entry in plan_approvals):
        return None, None
    if not plan_approvals[-1].option_ids:
        return None, None
    return ApprovalStatus.PENDING, plan_approvals[-1].request.request_id


def _merge_durable_permissions(
    snapshot: ThreadStateData, pending: Sequence[PendingPermission]
) -> None:
    if pending and snapshot.pause_cause is None:
        snapshot.pause_cause = pending[0].request.pause_reason_type
    existing = {permission.request_id for permission in snapshot.pending_permissions}
    for entry in pending:
        if entry.request.request_id in existing:
            continue
        projected = _permission_data_from_pending(entry)
        if projected is None:
            mark_degraded(
                snapshot,
                DegradedReason.PERMISSION_PROJECTION_UNREADABLE,
                repair=RepairStatus.OPERATOR_INTERVENTION_REQUIRED,
            )
            continue
        snapshot.pending_permissions.append(projected)


async def enrich_snapshot_from_durable_state(
    session: AsyncSession,
    *,
    thread: ThreadModel,
    snapshot: ThreadStateData,
) -> ThreadStateData:
    """Merge durable gateway-owned state into a reconnect snapshot."""
    record_repair_posture(snapshot, thread.repair_status)
    snapshot.approval_status = thread.approval_status
    snapshot.approval_request_id = thread.approval_request_id
    # Read before the terminal branch below returns, so a settled run reports
    # the truth rather than inheriting the default: a run that ends with
    # something still queued on it would be a defect, and this is where it
    # would be visible.
    snapshot.queued_messages = await count_queued_continuations(
        session, thread_id=thread.id
    )
    if thread.status in TERMINAL_STATUS_VALUES:
        # A settled run is outside the live-run query, so what it never
        # answered is read directly.
        residue = await get_pending_permission_requests(
            session,
            thread_id=thread.id,
            include_answered_pending_apply=False,
        )
        if residue or snapshot.approval_status == ApprovalStatus.PENDING:
            mark_degraded(
                snapshot,
                DegradedReason.TERMINAL_THREAD_PENDING_PERMISSION_RESIDUE,
                repair=RepairStatus.NEEDS_RECONCILIATION,
            )
        snapshot.pending_permissions = []
        snapshot.pending_clarification = None
        snapshot.approval_status = None
        snapshot.approval_request_id = None
        return snapshot

    pending = await actionable_pending_permissions(session, thread_id=thread.id)
    _merge_durable_permissions(snapshot, pending)
    snapshot.approval_status, snapshot.approval_request_id = durable_approval(pending)
    _clear_non_actionable_pause_state(snapshot)

    return snapshot


def execution_state_is_stale(
    row: ThreadExecutionStateModel,
    *,
    checkpoint_present: bool,
    checkpoint_id: str | None,
) -> bool:
    """Return whether a durable execution-state row has lost its lineage.

    The row is stale when no checkpoint backs it, or when it describes a
    checkpoint other than the run's current one.
    """
    if not checkpoint_present:
        return True
    return checkpoint_id is not None and row.checkpoint_id != checkpoint_id


async def enrich_snapshot_from_execution_state(
    session: AsyncSession,
    *,
    thread: ThreadModel,
    snapshot: ThreadStateData,
    checkpoint_present: bool | None,
    checkpoint_id: str | None,
) -> ThreadStateData:
    """Merge durable execution-state truth and classify freshness.

    ``checkpoint_present`` is ``None`` when the caller read no checkpoint at
    all. The row is still decoded, because an unreadable row says nothing about
    the checkpoint, but with nothing to compare it against its lineage is not
    judged.
    """
    row = await get_thread_execution_state(session, thread.id)
    if row is None:
        if checkpoint_present:
            mark_degraded(snapshot, DegradedReason.EXECUTION_STATE_PROJECTION_MISSING)
        return snapshot

    try:
        projection = project_execution_state_model(row)
    except ValueError:
        mark_degraded(
            snapshot,
            DegradedReason.EXECUTION_STATE_PROJECTION_UNREADABLE,
            repair=RepairStatus.OPERATOR_INTERVENTION_REQUIRED,
        )
        return snapshot

    # Terminal threads should not merge execution state —
    # out-of-order terminal events can leave stale metadata on the row.
    is_terminal = thread.status in TERMINAL_STATUS_VALUES
    if is_terminal:
        return snapshot

    if checkpoint_present is not None and execution_state_is_stale(
        row,
        checkpoint_present=checkpoint_present,
        checkpoint_id=checkpoint_id,
    ):
        # The row's own diagnostics still describe the run, so they are carried
        # forward even though its lineage is not.
        for reason in projection.degraded_reasons:
            mark_degraded(snapshot, reason)
        mark_degraded(
            snapshot,
            DegradedReason.EXECUTION_STATE_PROJECTION_STALE,
            repair=RepairStatus.NEEDS_RECONCILIATION,
        )
        return snapshot

    return apply_execution_state_projection(snapshot, projection)
