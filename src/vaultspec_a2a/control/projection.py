"""Helpers for repair-aware thread snapshot projection."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from pydantic import TypeAdapter, ValidationError

from ..database import (
    actionable_pending_permissions,
    count_queued_continuations,
    get_pending_permission_requests,
    get_thread_execution_state,
)
from ..utils.coercion import coerce_object_mapping

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from ..database import (
        PendingPermission,
        ThreadExecutionStateModel,
        ThreadModel,
    )

from ..graph.acp_options import option_id_of, option_kind
from ..graph.enums import PermissionType
from ..streaming.types import classify_tool_kind
from ..thread.clarification import pending_clarification
from ..thread.enums import (
    TERMINAL_STATUS_VALUES,
    ApprovalStatus,
    DegradedReason,
    RepairStatus,
    ReplayStatus,
    ThreadStatus,
    TranscriptAvailability,
)
from ..thread.snapshots import (
    PERMISSION_REQUEST_EVENT_TYPES,
    PLAN_APPROVAL_PAUSE_CAUSES,
    CheckpointProjection,
    ExecutionStateProjection,
    ExecutionTaskSnapshot,
    PermissionOptionSnapshot,
    PermissionSnapshot,
    ThreadStateSnapshot,
    record_repair_posture,
)
from .permission_options import pending_option_ids

__all__ = [
    "apply_authoring_completion_check",
    "apply_checkpoint_projection",
    "apply_execution_state_projection",
    "classify_transcript_availability",
    "clear_permissions_without_checkpoint_truth",
    "enrich_snapshot_from_durable_state",
    "enrich_snapshot_from_execution_state",
    "finalize_snapshot_replay_status",
    "mark_degraded",
    "project_execution_state_model",
    "reconcile_checkpoint_permissions_with_durable_state",
    "withhold_terminal_interrupt_disclosure",
]

_JSON_LIST_ADAPTER = TypeAdapter(list[object])
_EXECUTION_TASK_ADAPTER = TypeAdapter(ExecutionTaskSnapshot)

#: How far each degraded repair posture holds a run back. The postures absent
#: here (healthy, paused, cancel pending) demand nothing and yield to all of them.
_REPAIR_SEVERITY: dict[RepairStatus, int] = {
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


def escalate_repair_posture(
    current: RepairStatus | None, demanded: RepairStatus
) -> RepairStatus:
    """Apply a demanded repair posture to *current*, fail-closed.

    The posture moves to *demanded* unless it already demands at least as much,
    so a cause found late in a read can never talk a run back down from the
    posture an earlier cause put it in.
    """
    demanded_severity = _REPAIR_SEVERITY.get(demanded, 0)
    if current is None or _REPAIR_SEVERITY.get(current, 0) < demanded_severity:
        return demanded
    return current


def mark_degraded(
    snapshot: ThreadStateSnapshot,
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


def finalize_snapshot_replay_status(
    snapshot: ThreadStateSnapshot,
    *,
    checkpoint_loaded: bool,
    checkpoint_present: bool,
    checkpoint_error: bool,
    thread_status: str,
) -> ThreadStateSnapshot:
    """Apply the reconnect snapshot replay/degradation contract.

    Excuses an absent checkpoint in ``_PRE_TRANSCRIPT_STATUSES``, the same
    window :func:`classify_transcript_availability` excuses, because both answer
    from the SAME four facts: a window one of them calls normal startup while the
    other calls a lost record is a disagreement about one run, and the one that
    fires on healthy traffic teaches every reader to ignore it.

    The gap ESCALATES the repair posture rather than replacing it. ``replay_gap``
    is the mildest degraded posture, so overwriting let this last step of a read
    undo what an earlier one established and list a run recorded as
    ``checkpoint_unavailable`` as a mere replay gap.
    """
    if checkpoint_loaded:
        snapshot.replay_status = ReplayStatus.DURABLE.value
    elif checkpoint_error:
        snapshot.snapshot_complete = False
        snapshot.replay_status = ReplayStatus.UNKNOWN.value
    elif checkpoint_present:
        snapshot.snapshot_complete = False
        snapshot.replay_status = ReplayStatus.BEST_EFFORT.value
    elif thread_status in _PRE_TRANSCRIPT_STATUSES:
        # Completeness is left as the read found it. Asserting it here would let
        # the absence a run is EXCUSED for overwrite a degradation some earlier
        # step of the same read established.
        snapshot.replay_status = ReplayStatus.UNKNOWN.value
    else:
        # The probe succeeded and found nothing, so the history a replay would
        # rebuild from is provably absent: a replay gap, not the unknown that an
        # unavailable checkpoint reports.
        mark_degraded(
            snapshot,
            DegradedReason.CHECKPOINT_MISSING,
            repair=RepairStatus.REPLAY_GAP,
        )
        snapshot.replay_status = ReplayStatus.GAP_DETECTED.value
    return snapshot


def classify_transcript_availability(
    *,
    checkpoint_loaded: bool,
    checkpoint_present: bool,
    checkpoint_error: bool,
    thread_status: str,
) -> TranscriptAvailability:
    """Classify whether a run's conversation is readable from its checkpoint.

    Takes the SAME four facts as :func:`finalize_snapshot_replay_status`, excuses
    the same ``_PRE_TRANSCRIPT_STATUSES`` window, and sits beside it
    deliberately: both answer from one checkpoint read, and splitting them across
    modules would let the replay verdict and the transcript verdict drift out of
    agreement on the same run.

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


def apply_authoring_completion_check(
    snapshot: ThreadStateSnapshot,
    *,
    thread_status: str,
    requires_document_authoring: bool,
    proposal_ids: list[str],
    changeset_ids: list[str],
) -> ThreadStateSnapshot:
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


def _clear_non_actionable_pause_state(snapshot: ThreadStateSnapshot) -> None:
    """Clear pause metadata when no user-actionable permission remains."""
    if snapshot.pending_permissions:
        return
    if snapshot.approval_status is not None or snapshot.approval_request_id is not None:
        return
    snapshot.pause_cause = None


def clear_permissions_without_checkpoint_truth(
    snapshot: ThreadStateSnapshot,
) -> ThreadStateSnapshot:
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


def _permission_snapshot_from_pending(
    pending: PendingPermission,
) -> PermissionSnapshot | None:
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
    options: list[PermissionOptionSnapshot] = []
    for raw_option in raw_options:
        option = coerce_object_mapping(raw_option)
        if option is None:
            continue
        options.append(
            PermissionOptionSnapshot(
                option_id=option_id_of(option) or "",
                name=str(option.get("name", "")),
                kind=option_kind(option),
            )
        )
    return PermissionSnapshot(
        request_id=permission.request_id,
        description=permission.description,
        options=options,
        tool_call=tool_call,
        tool_kind=classify_tool_kind(tool_call) if tool_call else None,
    )


def apply_checkpoint_projection(
    snapshot: ThreadStateSnapshot,
    projection: CheckpointProjection,
) -> ThreadStateSnapshot:
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
    snapshot: ThreadStateSnapshot,
    projection: CheckpointProjection,
    *,
    durable_permission_ids: Collection[str] | None = None,
) -> ThreadStateSnapshot:
    """Fail closed when the checkpoint is parked on a permission with no durable row.

    The durable row is the only source of a pending permission's content, so
    ``snapshot.pending_permissions`` holds exactly the readable durable rows and
    the checkpoint contributes nothing but the request ids it is parked on. A
    parked request with no row is a pause the respond route cannot act on: it
    demands reconciliation and withdraws any approval it names.

    *durable_permission_ids*, when supplied, is the FULL set of permission
    request ids that have a durable row - including one withheld from
    disclosure because it offered nothing answerable, which
    ``snapshot.pending_permissions`` alone cannot tell apart from a row that
    never existed. A caller that already collected this set from
    :func:`enrich_snapshot_from_durable_state` should pass it, so a withheld
    row is not ALSO reported as having no durable row at all. Omitted, the
    check falls back to the disclosed set alone, which is the historical
    (narrower) behaviour.
    """
    durable_request_ids = (
        {permission.request_id for permission in snapshot.pending_permissions}
        if durable_permission_ids is None
        else set(durable_permission_ids)
    )
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


def withhold_terminal_interrupt_disclosure(
    snapshot: ThreadStateSnapshot, *, thread_status: str
) -> ThreadStateSnapshot:
    """Withdraw every answerable interrupt from a SETTLED run's disclosure.

    The one terminal gate, and it runs AFTER the checkpoint merge on purpose.
    Settling a run does not rewrite its checkpoint, so the request it parked on
    is still held there: withdrawing the durable half first only let the merge
    put the checkpoint half straight back, which is how a cancelled run went on
    serving the questionnaire it parked on.

    No respond verb accepts a settled run, so anything still disclosed here is
    an offer no caller can take up, and nothing on the wire distinguishes it
    from one that can. The pause cause goes with it: a run that has stopped is
    not paused on anything.

    Degraded reasons are deliberately untouched. That a settled run still holds
    unanswered requests is an operator signal about the record, and this gate
    removes the offer, not the finding.
    """
    if thread_status not in TERMINAL_STATUS_VALUES:
        return snapshot
    snapshot.pending_permissions = []
    snapshot.pending_clarification = None
    snapshot.approval_status = None
    snapshot.approval_request_id = None
    snapshot.pause_cause = None
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
    execution_tasks: list[ExecutionTaskSnapshot] = []
    for raw_task in raw_tasks:
        task_data = coerce_object_mapping(raw_task)
        if task_data is None:
            continue
        try:
            execution_tasks.append(
                _EXECUTION_TASK_ADAPTER.validate_python(
                    {"task_id": "", "name": "", **task_data}
                )
            )
        except ValidationError:
            continue
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
    snapshot: ThreadStateSnapshot,
    projection: ExecutionStateProjection,
) -> ThreadStateSnapshot:
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

    Module-internal since the listing stopped reading the approval on its own and
    took the whole durable step through :func:`enrich_snapshot_from_durable_state`.
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
    if not pending_option_ids(plan_approvals[-1]):
        return None, None
    return ApprovalStatus.PENDING, plan_approvals[-1].request.request_id


def _merge_durable_permissions(
    snapshot: ThreadStateSnapshot, pending: Sequence[PendingPermission]
) -> None:
    """Disclose the durable rows a response could still be addressed to.

    ONE visibility rule, the same :func:`pending_option_ids` question the team
    status and the listing's approval read ask: a row is disclosed when it offers
    an option a response could name. The respond verb validates an answer against
    the offer, so a row that offers nothing usable is a pause no caller can lift,
    and disclosing it as pending invites an answer that is refused.

    An offer that cannot be READ at all and one that reads as nothing usable are
    withheld alike, and both degrade this read, but under DIFFERENT reasons: an
    unreadable offer (``entry.offered is None``, the column itself did not
    decode) says the row is corrupt, while a readable offer with no usable
    option says the row is intact but unanswerable. Conflating the two under
    one reason would tell an operator reading ``degraded_reasons`` that a row
    is corrupt when it is actually sitting there, readable, just withheld - the
    tool-permission model refuses a request with no usable option at the
    worker, so neither row should exist, but they are not the same fault.
    """
    existing = {permission.request_id for permission in snapshot.pending_permissions}
    disclosed_cause: str | None = None
    for entry in pending:
        if entry.request.request_id not in existing:
            if pending_option_ids(entry):
                projected = _permission_snapshot_from_pending(entry)
            else:
                projected = None
            if projected is None:
                reason = (
                    DegradedReason.PERMISSION_PROJECTION_UNREADABLE
                    if entry.offered is None
                    else DegradedReason.PERMISSION_OFFERS_NO_USABLE_OPTION
                )
                mark_degraded(
                    snapshot,
                    reason,
                    repair=RepairStatus.OPERATOR_INTERVENTION_REQUIRED,
                )
                continue
            snapshot.pending_permissions.append(projected)
        if disclosed_cause is None:
            disclosed_cause = entry.request.pause_reason_type
    # Named by what was DISCLOSED, not by what the query returned: a cause naming
    # a request no surface serves describes a pause the reader cannot see, and the
    # checkpoint - the pause authority - supplies the cause for that run instead.
    if disclosed_cause is not None and snapshot.pause_cause is None:
        snapshot.pause_cause = disclosed_cause


async def enrich_snapshot_from_durable_state(
    session: AsyncSession,
    *,
    thread: ThreadModel,
    snapshot: ThreadStateSnapshot,
    durable_permission_ids: set[str] | None = None,
) -> ThreadStateSnapshot:
    """Merge durable gateway-owned state into a reconnect snapshot.

    *durable_permission_ids*, when supplied, is filled with every permission
    request id this read found a durable row for - disclosed or withheld
    alike. A caller that also calls
    :func:`reconcile_checkpoint_permissions_with_durable_state` should pass the
    same set there, so a row withheld here (it offered nothing answerable) is
    not also reported there as having no durable row at all.
    """
    record_repair_posture(snapshot, thread.repair_status)
    # Read before the terminal branch below returns, so a settled run reports
    # the truth rather than inheriting the default: a run that ends with
    # something still queued on it would be a defect, and this is where it
    # would be visible.
    snapshot.queued_messages = await count_queued_continuations(
        session, thread_id=thread.id
    )
    if thread.status in TERMINAL_STATUS_VALUES:
        # A settled run is outside the live-run query, so what it never
        # answered is read directly. The residue is REPORTED and never
        # DISCLOSED: nothing readable is written onto the snapshot here, so the
        # terminal gate has nothing to undo and the posture it leaves behind is
        # an operator signal rather than an offer to answer.
        residue = await get_pending_permission_requests(
            session,
            thread_id=thread.id,
            include_answered_pending_apply=False,
        )
        if residue or thread.approval_status == ApprovalStatus.PENDING.value:
            mark_degraded(
                snapshot,
                DegradedReason.TERMINAL_THREAD_PENDING_PERMISSION_RESIDUE,
                repair=RepairStatus.NEEDS_RECONCILIATION,
            )
        return snapshot

    approval = thread.approval_status
    snapshot.approval_status = None if approval is None else ApprovalStatus(approval)
    snapshot.approval_request_id = thread.approval_request_id
    pending = await actionable_pending_permissions(session, thread_id=thread.id)
    if durable_permission_ids is not None:
        durable_permission_ids.update(entry.request.request_id for entry in pending)
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
    snapshot: ThreadStateSnapshot,
    checkpoint_present: bool | None,
    checkpoint_id: str | None,
) -> ThreadStateSnapshot:
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
