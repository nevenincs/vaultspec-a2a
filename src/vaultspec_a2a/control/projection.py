"""Helpers for repair-aware thread snapshot projection."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from ..database.crud import (
    get_pending_permission_requests,
    get_thread_execution_state,
)

if TYPE_CHECKING:
    from langgraph.checkpoint.base import CheckpointTuple
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..database.models import (
        PermissionRequestModel,
        ThreadExecutionStateModel,
        ThreadModel,
    )

from ..api.schemas.snapshots import (
    ExecutionTaskSnapshot,
    ThreadStateSnapshot,
    _PermissionOptionSnapshot,
    _PermissionSnapshot,
)
from ..graph.enums import PermissionOptionKind, PermissionType

_PLAN_APPROVAL_PAUSE_CAUSES = {
    PermissionType.PLAN_APPROVAL.value,
    "plan_approval_request",
}


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
    execution_tasks: list[ExecutionTaskSnapshot] = field(default_factory=list)
    degraded_reasons: list[str] = field(default_factory=list)


def _permission_snapshot_from_model(
    permission: PermissionRequestModel,
) -> _PermissionSnapshot:
    raw_options = json.loads(permission.allowed_options_json)
    options = [
        _PermissionOptionSnapshot(
            option_id=str(option.get("option_id", "")),
            name=str(option.get("name", "")),
            kind=PermissionOptionKind(str(option.get("kind", "allow_once"))),
        )
        for option in raw_options
        if isinstance(option, dict)
    ]
    return _PermissionSnapshot(
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


def _permission_snapshot_from_interrupt(
    interrupt: ProjectedInterrupt,
) -> _PermissionSnapshot | None:
    payload = interrupt.payload
    if interrupt.interrupt_type == "permission_request":
        tool_name = str(payload.get("tool_name", "unknown"))
        raw_options = payload.get("options", [])
        options = []
        if isinstance(raw_options, list):
            for option in raw_options:
                if not isinstance(option, dict):
                    continue
                options.append(
                    _PermissionOptionSnapshot(
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
                        kind=_coerce_permission_kind(
                            option.get("kind", PermissionOptionKind.ALLOW_ONCE.value)
                        ),
                    )
                )
        return _PermissionSnapshot(
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
        return _PermissionSnapshot(
            request_id=interrupt.interrupt_id,
            description=(
                f"Approve plan for feature '{feature}' before routing to "
                f"{exec_worker} ({plan_summary})"
            ),
            options=[
                _PermissionOptionSnapshot(
                    option_id="approve",
                    name="Approve Plan",
                    kind=PermissionOptionKind.ALLOW_ONCE,
                ),
                _PermissionOptionSnapshot(
                    option_id="reject",
                    name="Reject - Revise Plan",
                    kind=PermissionOptionKind.REJECT_ONCE,
                ),
            ],
            tool_call=PermissionType.PLAN_APPROVAL.value,
        )

    return None


def _parse_checkpoint_created_at(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _load_json_list(raw: str | None, *, field_name: str) -> list[Any]:
    if raw is None:
        return []
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = f"Could not decode {field_name}"
        raise ValueError(msg) from exc
    if not isinstance(decoded, list):
        msg = f"{field_name} must decode to a list"
        raise ValueError(msg)
    return decoded


def project_checkpoint_tuple(
    checkpoint_tuple: CheckpointTuple,
    *,
    thread_id: str,
    history_depth: int | None = None,
) -> CheckpointProjection:
    """Project repair-relevant checkpoint data beyond raw channel values."""
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

    return projection


def apply_checkpoint_projection(
    snapshot: ThreadStateSnapshot,
    projection: CheckpointProjection,
) -> ThreadStateSnapshot:
    """Merge a normalized checkpoint projection into the API snapshot."""
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
        permission = _permission_snapshot_from_interrupt(interrupt)
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
    """Project a durable execution-state row into API-facing normalized data."""
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
    execution_tasks: list[ExecutionTaskSnapshot] = []
    for raw_task in raw_tasks:
        if not isinstance(raw_task, dict):
            continue
        execution_tasks.append(
            ExecutionTaskSnapshot(
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
    snapshot: ThreadStateSnapshot,
    projection: ExecutionStateProjection,
) -> ThreadStateSnapshot:
    """Merge a durable execution-state projection into the API snapshot."""
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
    snapshot: ThreadStateSnapshot,
) -> ThreadStateSnapshot:
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
            _permission_snapshot_from_model(permission)
            for permission in durable_permissions
            if permission.request_id not in existing
        )
        if snapshot.approval_status is None:
            for permission in durable_permissions:
                if permission.pause_reason_type in _PLAN_APPROVAL_PAUSE_CAUSES:
                    snapshot.approval_status = "pending"
                    snapshot.approval_request_id = permission.request_id
                    break

    return snapshot


async def enrich_snapshot_from_execution_state(
    session: AsyncSession,
    *,
    thread: ThreadModel,
    snapshot: ThreadStateSnapshot,
    checkpoint_present: bool,
    checkpoint_id: str | None,
) -> ThreadStateSnapshot:
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
