"""Helpers for repair-aware thread snapshot projection."""

from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncSession

from ..database.crud import get_pending_permission_requests
from ..database.models import PermissionRequestModel, ThreadModel
from .schemas.enums import PermissionOptionKind
from .schemas.snapshots import (
    ThreadStateSnapshot,
    _PermissionOptionSnapshot,
    _PermissionSnapshot,
)


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


async def enrich_snapshot_from_durable_state(
    session: AsyncSession,
    *,
    thread: ThreadModel,
    snapshot: ThreadStateSnapshot,
) -> ThreadStateSnapshot:
    """Merge durable gateway-owned state into a reconnect snapshot."""
    snapshot.repair_status = thread.repair_status
    snapshot.execution_readiness = thread.execution_readiness

    durable_permissions = await get_pending_permission_requests(
        session, thread_id=thread.id
    )
    if durable_permissions:
        existing = {
            permission.request_id for permission in snapshot.pending_permissions
        }
        snapshot.pending_permissions.extend(
            _permission_snapshot_from_model(permission)
            for permission in durable_permissions
            if permission.request_id not in existing
        )

    return snapshot
