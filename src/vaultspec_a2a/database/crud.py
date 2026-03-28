"""Async CRUD operations for durable orchestration state.

Shared utilities live in ``_crud_helpers``. Domain-specific operations are in:
- ``crud_threads``: thread lifecycle, repair, approval, execution state, metadata
- ``crud_permissions``: permission requests and control action journal
- ``crud_artifacts``: artifacts, permission logs, cost tracking

This module re-exports all public symbols so that existing
``from database.crud import X`` import paths continue to resolve.
"""

from __future__ import annotations

from ..thread.enums import (
    ApprovalStatus as ApprovalStatus,
)
from ..thread.enums import (
    ControlActionResultStatus as ControlActionResultStatus,
)
from ..thread.enums import (
    ControlActionType as ControlActionType,
)
from ..thread.enums import (
    InvalidTransitionError as InvalidTransitionError,
)
from ..thread.enums import (
    PermissionRequestStatus as PermissionRequestStatus,
)
from ..thread.enums import (
    RepairStatus as RepairStatus,
)
from ..thread.enums import (
    ThreadStatus as ThreadStatus,
)
from ._crud_helpers import (
    _UNSET as _UNSET,
)
from ._crud_helpers import (
    _coerce_approval_status as _coerce_approval_status,
)
from ._crud_helpers import (
    _coerce_control_action_type as _coerce_control_action_type,
)
from ._crud_helpers import (
    _coerce_control_result as _coerce_control_result,
)
from ._crud_helpers import (
    _coerce_permission_request_status as _coerce_permission_request_status,
)
from ._crud_helpers import (
    _coerce_repair_status as _coerce_repair_status,
)
from ._crud_helpers import (
    _coerce_status as _coerce_status,
)
from ._crud_helpers import (
    _UnsetType as _UnsetType,
)
from ._crud_helpers import (
    _utcnow as _utcnow,
)
from ._crud_helpers import (
    save_model as save_model,
)
from .crud_artifacts import (
    append_cost_record as append_cost_record,
)
from .crud_artifacts import (
    append_permission_log as append_permission_log,
)
from .crud_artifacts import (
    create_artifact as create_artifact,
)
from .crud_artifacts import (
    get_artifact as get_artifact,
)
from .crud_artifacts import (
    get_artifacts_by_thread as get_artifacts_by_thread,
)
from .crud_artifacts import (
    get_permission_logs_by_thread as get_permission_logs_by_thread,
)
from .crud_artifacts import (
    sum_cost_by_agent as sum_cost_by_agent,
)
from .crud_artifacts import (
    sum_cost_by_thread as sum_cost_by_thread,
)
from .crud_permissions import (
    create_control_action as create_control_action,
)
from .crud_permissions import (
    expire_pending_permission_requests as expire_pending_permission_requests,
)
from .crud_permissions import (
    get_control_action_by_idempotency_key as get_control_action_by_idempotency_key,
)
from .crud_permissions import (
    get_latest_control_action as get_latest_control_action,
)
from .crud_permissions import (
    get_pending_permission_requests as get_pending_permission_requests,
)
from .crud_permissions import (
    get_permission_request as get_permission_request,
)
from .crud_permissions import (
    mark_control_action_applied as mark_control_action_applied,
)
from .crud_permissions import (
    mark_control_action_duplicate as mark_control_action_duplicate,
)
from .crud_permissions import (
    mark_control_action_superseded as mark_control_action_superseded,
)
from .crud_permissions import (
    mark_permission_request_applied as mark_permission_request_applied,
)
from .crud_permissions import (
    record_permission_request as record_permission_request,
)
from .crud_permissions import (
    record_permission_response_submission as record_permission_response_submission,
)
from .crud_permissions import (
    supersede_permission_requests as supersede_permission_requests,
)
from .crud_threads import (
    create_thread as create_thread,
)
from .crud_threads import (
    delete_thread as delete_thread,
)
from .crud_threads import (
    delete_thread_execution_state as delete_thread_execution_state,
)
from .crud_threads import (
    get_thread as get_thread,
)
from .crud_threads import (
    get_thread_execution_state as get_thread_execution_state,
)
from .crud_threads import (
    get_thread_metadata as get_thread_metadata,
)
from .crud_threads import (
    list_non_terminal_threads as list_non_terminal_threads,
)
from .crud_threads import (
    list_threads as list_threads,
)
from .crud_threads import (
    record_thread_execution_state as record_thread_execution_state,
)
from .crud_threads import (
    set_thread_approval_state as set_thread_approval_state,
)
from .crud_threads import (
    set_thread_repair_state as set_thread_repair_state,
)
from .crud_threads import (
    update_thread_metadata as update_thread_metadata,
)
from .crud_threads import (
    update_thread_status as update_thread_status,
)

__all__ = [
    "ApprovalStatus",
    "ControlActionResultStatus",
    "ControlActionType",
    "InvalidTransitionError",
    "PermissionRequestStatus",
    "RepairStatus",
    "ThreadStatus",
    "append_cost_record",
    "append_permission_log",
    "create_artifact",
    "create_control_action",
    "create_thread",
    "delete_thread",
    "delete_thread_execution_state",
    "expire_pending_permission_requests",
    "get_artifact",
    "get_artifacts_by_thread",
    "get_control_action_by_idempotency_key",
    "get_latest_control_action",
    "get_pending_permission_requests",
    "get_permission_logs_by_thread",
    "get_permission_request",
    "get_thread",
    "get_thread_execution_state",
    "get_thread_metadata",
    "list_non_terminal_threads",
    "list_threads",
    "mark_control_action_applied",
    "mark_control_action_duplicate",
    "mark_control_action_superseded",
    "mark_permission_request_applied",
    "record_permission_request",
    "record_permission_response_submission",
    "record_thread_execution_state",
    "save_model",
    "set_thread_approval_state",
    "set_thread_repair_state",
    "sum_cost_by_agent",
    "sum_cost_by_thread",
    "supersede_permission_requests",
    "update_thread_metadata",
    "update_thread_status",
]
