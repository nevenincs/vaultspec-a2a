"""Helpers for repair-aware thread snapshot projection."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from ..database import (
    get_pending_permission_requests,
    get_thread_execution_state,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..database.models import (
        PermissionRequestModel,
        ThreadExecutionStateModel,
        ThreadModel,
    )

from ..graph.enums import PermissionOptionKind, PermissionType
from ..thread.enums import ApprovalStatus
from ..thread.snapshots import (
    PLAN_APPROVAL_PAUSE_CAUSES,
    CheckpointProjection,
    ExecutionStateProjection,
    ExecutionTaskData,
    PermissionData,
    PermissionOptionData,
    ProjectedInterrupt,
    ThreadStateData,
    _load_json_list,
)

_PLAN_APPROVAL_PAUSE_CAUSES = PLAN_APPROVAL_PAUSE_CAUSES


def _permission_data_from_model(
    permission: PermissionRequestModel,
) -> PermissionData:
    raw_options = json.loads(permission.allowed_options_json)
    options = [
        PermissionOptionData(
            option_id=str(option.get("option_id", "")),
            name=str(option.get("name", "")),
            kind=str(PermissionOptionKind(str(option.get("kind", "allow_once")))),
        )
        for option in raw_options
        if isinstance(option, dict)
    ]
    return PermissionData(
        request_id=permission.request_id,
        description=permission.description,
        options=options,
        tool_call=permission.tool_call,
    )


def _coerce_permission_kind(value: object) -> PermissionOptionKind:
    try:
        return PermissionOptionKind(str(value))
    except ValueError:
        return PermissionOptionKind.ALLOW_ONCE


def _permission_data_from_interrupt(
    interrupt: ProjectedInterrupt,
) -> PermissionData | None:
    payload = interrupt.payload
    if interrupt.interrupt_type == "permission_request":
        tool_name = str(payload.get("tool_name", "unknown"))
        raw_options = payload.get("options", [])
        options: list[PermissionOptionData] = []
        if isinstance(raw_options, list):
            for option in raw_options:
                if not isinstance(option, dict):
                    continue
                options.append(
                    PermissionOptionData(
                        option_id=str(
                            option.get(
                                "optionId",
                                option.get("option_id", "allow_once"),
                            )
                        ),
                        name=str(
                            option.get(
                                "name",
                                option.get(
                                    "label",
                                    option.get("optionId", "allow_once"),
                                ),
                            )
                        ),
                        kind=str(
                            _coerce_permission_kind(
                                option.get(
                                    "kind", PermissionOptionKind.ALLOW_ONCE.value
                                )
                            )
                        ),
                    )
                )
        return PermissionData(
            request_id=interrupt.interrupt_id,
            description=f"Approval required for tool '{tool_name}'",
            options=options,
            tool_call=tool_name,
        )

    if interrupt.interrupt_type == "plan_approval_request":
        feature = str(payload.get("feature", "unknown"))
        plan_paths = payload.get("plan_paths", [])
        exec_worker = str(payload.get("exec_worker", "unknown"))
        plan_summary = (
            f"{len(plan_paths)} plan document(s)"
            if isinstance(plan_paths, list) and plan_paths
            else "no plan documents"
        )
        return PermissionData(
            request_id=interrupt.interrupt_id,
            description=(
                f"Approve plan for feature '{feature}' before routing to "
                f"{exec_worker} ({plan_summary})"
            ),
            options=[
                PermissionOptionData(
                    option_id="approve",
                    name="Approve Plan",
                    kind=str(PermissionOptionKind.ALLOW_ONCE),
                ),
                PermissionOptionData(
                    option_id="reject",
                    name="Reject - Revise Plan",
                    kind=str(PermissionOptionKind.REJECT_ONCE),
                ),
            ],
            tool_call=PermissionType.PLAN_APPROVAL.value,
        )

    return None


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

    existing = {permission.request_id for permission in snapshot.pending_permissions}
    for interrupt in projection.pending_interrupts:
        permission = _permission_data_from_interrupt(interrupt)
        if permission is None or permission.request_id in existing:
            continue
        snapshot.pending_permissions.append(permission)
        existing.add(permission.request_id)

    for reason in projection.degraded_reasons:
        if reason not in snapshot.degraded_reasons:
            snapshot.degraded_reasons.append(reason)

    return snapshot


def project_execution_state_model(
    model: ThreadExecutionStateModel,
) -> ExecutionStateProjection:
    """Project a durable execution-state row into normalized data."""
    next_nodes = [
        str(item)
        for item in _load_json_list(model.next_nodes_json, field_name="next_nodes_json")
    ]
    interrupt_types = [
        str(item)
        for item in _load_json_list(
            model.interrupt_types_json,
            field_name="interrupt_types_json",
        )
    ]
    raw_tasks = _load_json_list(model.tasks_json, field_name="tasks_json")
    execution_tasks: list[ExecutionTaskData] = []
    for raw_task in raw_tasks:
        if not isinstance(raw_task, dict):
            continue
        execution_tasks.append(
            ExecutionTaskData(
                task_id=str(raw_task.get("task_id", "")),
                name=str(raw_task.get("name", "")),
                path=[
                    str(item)
                    for item in raw_task.get("path", [])
                    if isinstance(item, str)
                ],
                has_error=bool(raw_task.get("has_error", False)),
                error_type=(
                    str(raw_task["error_type"])
                    if raw_task.get("error_type") is not None
                    else None
                ),
                interrupt_ids=[
                    str(item)
                    for item in raw_task.get("interrupt_ids", [])
                    if isinstance(item, str)
                ],
                interrupt_types=[
                    str(item)
                    for item in raw_task.get("interrupt_types", [])
                    if isinstance(item, str)
                ],
                has_nested_state=bool(raw_task.get("has_nested_state", False)),
                has_result=bool(raw_task.get("has_result", False)),
            )
        )
    degraded_reasons = [
        str(item)
        for item in _load_json_list(
            model.degraded_reasons_json,
            field_name="degraded_reasons_json",
        )
    ]
    return ExecutionStateProjection(
        checkpoint_id=model.checkpoint_id,
        parent_checkpoint_id=model.parent_checkpoint_id,
        recovery_epoch=model.recovery_epoch,
        task_count=model.task_count,
        interrupt_count=model.interrupt_count,
        next_nodes=next_nodes,
        interrupt_types=interrupt_types,
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
        if reason not in snapshot.degraded_reasons:
            snapshot.degraded_reasons.append(reason)
    return snapshot


async def enrich_snapshot_from_durable_state(
    session: AsyncSession,
    *,
    thread: ThreadModel,
    snapshot: ThreadStateData,
) -> ThreadStateData:
    """Merge durable gateway-owned state into a reconnect snapshot."""
    snapshot.repair_status = thread.repair_status
    snapshot.execution_readiness = thread.execution_readiness
    snapshot.approval_status = thread.approval_status
    snapshot.approval_request_id = thread.approval_request_id

    durable_permissions = await get_pending_permission_requests(
        session, thread_id=thread.id
    )
    if durable_permissions:
        if snapshot.pause_cause is None:
            snapshot.pause_cause = durable_permissions[0].pause_reason_type
        existing = {
            permission.request_id for permission in snapshot.pending_permissions
        }
        snapshot.pending_permissions.extend(
            _permission_data_from_model(permission)
            for permission in durable_permissions
            if permission.request_id not in existing
        )
        if snapshot.approval_status is None:
            for permission in durable_permissions:
                if permission.pause_reason_type in _PLAN_APPROVAL_PAUSE_CAUSES:
                    snapshot.approval_status = ApprovalStatus.PENDING
                    snapshot.approval_request_id = permission.request_id
                    break

    return snapshot


async def enrich_snapshot_from_execution_state(
    session: AsyncSession,
    *,
    thread: ThreadModel,
    snapshot: ThreadStateData,
    checkpoint_present: bool,
    checkpoint_id: str | None,
) -> ThreadStateData:
    """Merge durable execution-state truth and classify freshness."""
    row = await get_thread_execution_state(session, thread.id)
    if row is None:
        if checkpoint_present:
            snapshot.snapshot_complete = False
            if "execution_state_projection_missing" not in snapshot.degraded_reasons:
                snapshot.degraded_reasons.append("execution_state_projection_missing")
        return snapshot

    try:
        projection = project_execution_state_model(row)
    except ValueError:
        snapshot.snapshot_complete = False
        if "execution_state_projection_unreadable" not in snapshot.degraded_reasons:
            snapshot.degraded_reasons.append("execution_state_projection_unreadable")
        return snapshot

    snapshot = apply_execution_state_projection(snapshot, projection)

    if row.recovery_epoch != thread.recovery_epoch:
        snapshot.snapshot_complete = False
        if "execution_state_projection_stale" not in snapshot.degraded_reasons:
            snapshot.degraded_reasons.append("execution_state_projection_stale")

    if (
        checkpoint_present
        and checkpoint_id is not None
        and row.checkpoint_id != checkpoint_id
    ):
        snapshot.snapshot_complete = False
        if "execution_state_projection_stale" not in snapshot.degraded_reasons:
            snapshot.degraded_reasons.append("execution_state_projection_stale")

    return snapshot
