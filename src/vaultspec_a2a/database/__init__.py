"""Persistence layer for the orchestrator.

Facade re-exporting all public types from the ``vaultspec_a2a.database`` subpackage.
Consumers should import from this module rather than reaching into
sub-modules directly::

    from vaultspec_a2a.database import init_db, create_thread, ThreadModel
"""

from ..thread.enums import ApprovalStatus as ApprovalStatus
from ..thread.enums import ControlActionResultStatus as ControlActionResultStatus
from ..thread.enums import ControlActionType as ControlActionType
from ..thread.enums import InvalidTransitionError as InvalidTransitionError
from ..thread.enums import PermissionRequestStatus as PermissionRequestStatus
from ..thread.enums import RepairStatus as RepairStatus
from ..thread.enums import ThreadStatus as ThreadStatus
from ._helpers import save_model as save_model
from .artifact_repository import append_cost_record as append_cost_record
from .artifact_repository import append_permission_log as append_permission_log
from .artifact_repository import create_artifact as create_artifact
from .artifact_repository import get_artifact as get_artifact
from .artifact_repository import get_artifacts_by_thread as get_artifacts_by_thread
from .artifact_repository import (
    get_permission_logs_by_thread as get_permission_logs_by_thread,
)
from .artifact_repository import sum_cost_by_agent as sum_cost_by_agent
from .artifact_repository import sum_cost_by_thread as sum_cost_by_thread
from .authoring_cursor_repository import (
    DEFAULT_SUBSCRIBER_ID as DEFAULT_SUBSCRIBER_ID,
)
from .authoring_cursor_repository import (
    get_authoring_cursor as get_authoring_cursor,
)
from .authoring_cursor_repository import (
    set_authoring_cursor as set_authoring_cursor,
)
from .migrate import run_migrations as run_migrations
from .models import ArtifactModel as ArtifactModel
from .models import AuthoringEventCursorModel as AuthoringEventCursorModel
from .models import Base as Base
from .models import CostTrackingModel as CostTrackingModel
from .models import PermissionLogModel as PermissionLogModel
from .models import TaskQueueEntryModel as TaskQueueEntryModel
from .models import ThreadModel as ThreadModel
from .permission_repository import create_control_action as create_control_action
from .permission_repository import (
    expire_pending_permission_requests as expire_pending_permission_requests,
)
from .permission_repository import (
    get_control_action_by_idempotency_key as get_control_action_by_idempotency_key,
)
from .permission_repository import (
    get_latest_control_action as get_latest_control_action,
)
from .permission_repository import (
    get_pending_permission_requests as get_pending_permission_requests,
)
from .permission_repository import get_permission_request as get_permission_request
from .permission_repository import (
    mark_control_action_applied as mark_control_action_applied,
)
from .permission_repository import (
    mark_control_action_duplicate as mark_control_action_duplicate,
)
from .permission_repository import (
    mark_control_action_superseded as mark_control_action_superseded,
)
from .permission_repository import (
    mark_permission_request_applied as mark_permission_request_applied,
)
from .permission_repository import (
    record_permission_request as record_permission_request,
)
from .permission_repository import (
    record_permission_response_submission as record_permission_response_submission,
)
from .permission_repository import (
    reset_permission_response_submission as reset_permission_response_submission,
)
from .permission_repository import (
    supersede_permission_requests as supersede_permission_requests,
)
from .session import close_db as close_db
from .session import get_db as get_db
from .session import get_engine as get_engine
from .session import get_session_factory as get_session_factory
from .session import init_db as init_db
from .session import verify_wal_mode as verify_wal_mode
from .task_queue_repository import MarkCompleteResult as MarkCompleteResult
from .task_queue_repository import get_queue_view as get_queue_view
from .task_queue_repository import mark_task_complete as mark_task_complete
from .task_queue_repository import seed_task_queue as seed_task_queue
from .thread_repository import create_thread as create_thread
from .thread_repository import delete_thread as delete_thread
from .thread_repository import (
    delete_thread_execution_state as delete_thread_execution_state,
)
from .thread_repository import get_thread as get_thread
from .thread_repository import (
    get_thread_execution_state as get_thread_execution_state,
)
from .thread_repository import get_thread_metadata as get_thread_metadata
from .thread_repository import (
    list_non_terminal_threads as list_non_terminal_threads,
)
from .thread_repository import list_threads as list_threads
from .thread_repository import (
    record_thread_execution_state as record_thread_execution_state,
)
from .thread_repository import (
    set_thread_approval_state as set_thread_approval_state,
)
from .thread_repository import set_thread_repair_state as set_thread_repair_state
from .thread_repository import update_thread_metadata as update_thread_metadata
from .thread_repository import update_thread_status as update_thread_status

__all__ = [
    "DEFAULT_SUBSCRIBER_ID",
    "ApprovalStatus",
    "ArtifactModel",
    "AuthoringEventCursorModel",
    "Base",
    "ControlActionResultStatus",
    "ControlActionType",
    "CostTrackingModel",
    "InvalidTransitionError",
    "MarkCompleteResult",
    "PermissionLogModel",
    "PermissionRequestStatus",
    "RepairStatus",
    "TaskQueueEntryModel",
    "ThreadModel",
    "ThreadStatus",
    "append_cost_record",
    "append_permission_log",
    "close_db",
    "create_artifact",
    "create_control_action",
    "create_thread",
    "delete_thread",
    "delete_thread_execution_state",
    "expire_pending_permission_requests",
    "get_artifact",
    "get_artifacts_by_thread",
    "get_authoring_cursor",
    "get_control_action_by_idempotency_key",
    "get_db",
    "get_engine",
    "get_latest_control_action",
    "get_pending_permission_requests",
    "get_permission_logs_by_thread",
    "get_permission_request",
    "get_queue_view",
    "get_session_factory",
    "get_thread",
    "get_thread_execution_state",
    "get_thread_metadata",
    "init_db",
    "list_non_terminal_threads",
    "list_threads",
    "mark_control_action_applied",
    "mark_control_action_duplicate",
    "mark_control_action_superseded",
    "mark_permission_request_applied",
    "mark_task_complete",
    "record_permission_request",
    "record_permission_response_submission",
    "record_thread_execution_state",
    "reset_permission_response_submission",
    "run_migrations",
    "save_model",
    "seed_task_queue",
    "set_authoring_cursor",
    "set_thread_approval_state",
    "set_thread_repair_state",
    "sum_cost_by_agent",
    "sum_cost_by_thread",
    "supersede_permission_requests",
    "update_thread_metadata",
    "update_thread_status",
    "verify_wal_mode",
]
