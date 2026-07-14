"""Shared helpers used by the domain-specific repository modules."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from ..thread.enums import (
    ApprovalStatus,
    ControlActionResultStatus,
    ControlActionType,
    PermissionRequestStatus,
    RepairStatus,
    ThreadStatus,
)
from .models import (
    ArtifactModel,
    ControlActionModel,
    CostTrackingModel,
    PermissionLogModel,
    PermissionRequestModel,
    TaskQueueEntryModel,
    ThreadExecutionStateModel,
    ThreadModel,
)

__all__ = [
    "_UNSET",
    "_UnsetType",
    "_coerce_approval_status",
    "_coerce_control_action_type",
    "_coerce_control_result",
    "_coerce_permission_request_status",
    "_coerce_repair_status",
    "_coerce_status",
    "_utcnow",
    "save_model",
]


async def save_model[
    M: (
        ThreadModel,
        ArtifactModel,
        PermissionLogModel,
        PermissionRequestModel,
        ControlActionModel,
        CostTrackingModel,
        ThreadExecutionStateModel,
        TaskQueueEntryModel,
    )
](session: AsyncSession, model: M) -> M:
    """Persist any database model instance."""
    session.add(model)
    await session.flush()
    return model


def _utcnow() -> datetime:
    return datetime.now(UTC)


class _UnsetType:
    """Typed sentinel for distinguishing 'not provided' from ``None``."""

    _instance: _UnsetType | None = None

    def __new__(cls) -> _UnsetType:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "<UNSET>"


_UNSET = _UnsetType()


def _coerce_status(status: ThreadStatus | str) -> ThreadStatus:
    if isinstance(status, ThreadStatus):
        return status
    try:
        return ThreadStatus(status)
    except ValueError:
        valid = ", ".join(s.value for s in ThreadStatus)
        msg = f"Invalid thread status: {status!r}. Must be one of: {valid}"
        raise ValueError(msg) from None


def _coerce_repair_status(status: RepairStatus | str) -> RepairStatus:
    if isinstance(status, RepairStatus):
        return status
    try:
        return RepairStatus(status)
    except ValueError:
        valid = ", ".join(s.value for s in RepairStatus)
        msg = f"Invalid repair status: {status!r}. Must be one of: {valid}"
        raise ValueError(msg) from None


def _coerce_control_action_type(
    action_type: ControlActionType | str,
) -> ControlActionType:
    if isinstance(action_type, ControlActionType):
        return action_type
    return ControlActionType(action_type)


def _coerce_control_result(
    status: ControlActionResultStatus | str,
) -> ControlActionResultStatus:
    if isinstance(status, ControlActionResultStatus):
        return status
    return ControlActionResultStatus(status)


def _coerce_permission_request_status(
    status: PermissionRequestStatus | str,
) -> PermissionRequestStatus:
    if isinstance(status, PermissionRequestStatus):
        return status
    return PermissionRequestStatus(status)


def _coerce_approval_status(status: ApprovalStatus | str) -> ApprovalStatus:
    if isinstance(status, ApprovalStatus):
        return status
    return ApprovalStatus(status)
