"""Expose persistence boundaries for runtime state.

:mod:`vaultspec_a2a.database.models` defines SQLAlchemy models, and
:mod:`vaultspec_a2a.database.session` owns asynchronous sessions. Repository
modules manage audit logs, authoring cursors, the control action journal,
deletion sagas, permissions, and threads.

Migration support belongs to :mod:`vaultspec_a2a.database.migrations`.
Persistence stores :mod:`vaultspec_a2a.thread` state for
:mod:`vaultspec_a2a.control` services.

Choose the model, session, or repository boundary that matches the
operation. This package re-exports the supported persistence API.
"""

from ._helpers import save_model as save_model
from ._leases import CONTROL_ACTION_LEASE_TTL as CONTROL_ACTION_LEASE_TTL
from ._leases import DELETION_SAGA_CLAIM_LEASE as DELETION_SAGA_CLAIM_LEASE
from ._leases import RECOVERY_CLAIM_TTL as RECOVERY_CLAIM_TTL
from ._leases import clear_lease as clear_lease
from ._leases import lease_free_from as lease_free_from
from ._leases import new_claim_token as new_claim_token
from ._leases import require_lease_window as require_lease_window
from .artifact_repository import append_cost_record as append_cost_record
from .artifact_repository import append_permission_log as append_permission_log
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
from .checkpoints import CheckpointRead as CheckpointRead
from .checkpoints import CheckpointReadStatus as CheckpointReadStatus
from .checkpoints import read_latest_checkpoint as read_latest_checkpoint
from .compatibility import SchemaCompatibilityError as SchemaCompatibilityError
from .compatibility import supported_migration_head as supported_migration_head
from .compatibility import validate_desktop_schema as validate_desktop_schema
from .control_action_repository import (
    ControlActionReservation as ControlActionReservation,
)
from .control_action_repository import (
    acquire_control_action_lease as acquire_control_action_lease,
)
from .control_action_repository import (
    commit_control_action_lease as commit_control_action_lease,
)
from .control_action_repository import (
    count_queued_continuations as count_queued_continuations,
)
from .control_action_repository import create_control_action as create_control_action
from .control_action_repository import enqueue_continuation as enqueue_continuation
from .control_action_repository import get_control_action as get_control_action
from .control_action_repository import (
    get_control_action_by_dispatch_id as get_control_action_by_dispatch_id,
)
from .control_action_repository import (
    get_control_action_by_idempotency_key as get_control_action_by_idempotency_key,
)
from .control_action_repository import (
    get_latest_control_action as get_latest_control_action,
)
from .control_action_repository import (
    get_unapplied_control_actions as get_unapplied_control_actions,
)
from .control_action_repository import get_writer_action as get_writer_action
from .control_action_repository import (
    has_live_queued_continuation_lease as has_live_queued_continuation_lease,
)
from .control_action_repository import (
    idempotency_key_admitted as idempotency_key_admitted,
)
from .control_action_repository import (
    mark_control_action_applied as mark_control_action_applied,
)
from .control_action_repository import (
    mark_control_action_duplicate as mark_control_action_duplicate,
)
from .control_action_repository import (
    mark_control_action_superseded as mark_control_action_superseded,
)
from .control_action_repository import next_queue_position as next_queue_position
from .control_action_repository import (
    overdue_recovery_actions as overdue_recovery_actions,
)
from .control_action_repository import (
    persist_graph_action_receipt as persist_graph_action_receipt,
)
from .control_action_repository import (
    read_next_queued_continuation as read_next_queued_continuation,
)
from .control_action_repository import (
    reject_queued_continuations as reject_queued_continuations,
)
from .control_action_repository import (
    release_control_action_lease as release_control_action_lease,
)
from .control_action_repository import reserve_control_action as reserve_control_action
from .control_action_repository import (
    select_recoverable_actions as select_recoverable_actions,
)
from .control_action_repository import (
    settle_control_action_lease as settle_control_action_lease,
)
from .deletion_saga_repository import (
    claim_deletion_saga_row as claim_deletion_saga_row,
)
from .deletion_saga_repository import get_deletion_saga_row as get_deletion_saga_row
from .deletion_saga_repository import (
    insert_deletion_saga_row as insert_deletion_saga_row,
)
from .deletion_saga_repository import lock_deletion_saga_row as lock_deletion_saga_row
from .deletion_saga_repository import read_cleanup_ledger as read_cleanup_ledger
from .deletion_saga_repository import (
    release_deletion_saga_claim as release_deletion_saga_claim,
)
from .deletion_saga_repository import (
    remove_deletion_saga_row as remove_deletion_saga_row,
)
from .deletion_saga_repository import swap_cleanup_ledger as swap_cleanup_ledger
from .migrate import build_migration_config as build_migration_config
from .migrate import migration_script_location as migration_script_location
from .migrate import run_migrations as run_migrations
from .migrations import backfill_teamstate_sdd_fields as backfill_teamstate_sdd_fields
from .migrations import count_pending_sdd_backfill as count_pending_sdd_backfill
from .models import ArtifactModel as ArtifactModel
from .models import AuthoringEventCursorModel as AuthoringEventCursorModel
from .models import Base as Base
from .models import ControlActionModel as ControlActionModel
from .models import CostTrackingModel as CostTrackingModel
from .models import PermissionLogModel as PermissionLogModel
from .models import PermissionRequestModel as PermissionRequestModel
from .models import ProviderRuntimeIdentityModel as ProviderRuntimeIdentityModel
from .models import RecoveryAttemptModel as RecoveryAttemptModel
from .models import RunEventModel as RunEventModel
from .models import ThreadDeletionSagaModel as ThreadDeletionSagaModel
from .models import ThreadExecutionStateModel as ThreadExecutionStateModel
from .models import ThreadModel as ThreadModel
from .permission_repository import PendingPermission as PendingPermission
from .permission_repository import (
    actionable_pending_permissions as actionable_pending_permissions,
)
from .permission_repository import (
    expire_pending_permission_requests as expire_pending_permission_requests,
)
from .permission_repository import (
    get_pending_permission_requests as get_pending_permission_requests,
)
from .permission_repository import get_permission_request as get_permission_request
from .permission_repository import (
    mark_permission_request_applied as mark_permission_request_applied,
)
from .permission_repository import (
    outstanding_permission_pause as outstanding_permission_pause,
)
from .permission_repository import (
    pending_document_approval_thread as pending_document_approval_thread,
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
from .recovery_attempt_repository import RecoveryFailureArgs as RecoveryFailureArgs
from .recovery_attempt_repository import (
    RecoveryRescheduleArgs as RecoveryRescheduleArgs,
)
from .recovery_attempt_repository import (
    claim_recovery_attempt as claim_recovery_attempt,
)
from .recovery_attempt_repository import (
    due_recovery_attempt_ids as due_recovery_attempt_ids,
)
from .recovery_attempt_repository import (
    release_recovery_claim as release_recovery_claim,
)
from .recovery_attempt_repository import (
    reschedule_recovery_claim as reschedule_recovery_claim,
)
from .recovery_attempt_repository import (
    schedule_recovery_attempt as schedule_recovery_attempt,
)
from .recovery_attempt_repository import (
    settle_expired_recovery_attempt as settle_expired_recovery_attempt,
)
from .recovery_attempt_repository import (
    settle_recovery_claim as settle_recovery_claim,
)
from .recovery_attempt_repository import (
    unscheduled_recovery_actions as unscheduled_recovery_actions,
)
from .run_event_repository import RunEventRecord as RunEventRecord
from .run_event_repository import RunEventStore as RunEventStore
from .runtime_identity_repository import (
    RuntimeIdentityConflictError as RuntimeIdentityConflictError,
)
from .runtime_identity_repository import (
    record_provider_runtime_identity as record_provider_runtime_identity,
)
from .session import application_session_factory as application_session_factory
from .session import begin_write_transaction as begin_write_transaction
from .session import close_db as close_db
from .session import configure_sqlite_engine as configure_sqlite_engine
from .session import (
    configure_sqlite_transactions as configure_sqlite_transactions,
)
from .session import get_db as get_db
from .session import get_engine as get_engine
from .session import get_session_factory as get_session_factory
from .session import init_db as init_db
from .session import inspect_sqlite_database as inspect_sqlite_database
from .session import resolve_session_factory as resolve_session_factory
from .session import retry_write_contention as retry_write_contention
from .session import seat_sqlite_posture as seat_sqlite_posture
from .session import verify_wal_mode as verify_wal_mode
from .thread_repository import ActiveThreadProjection as ActiveThreadProjection
from .thread_repository import (
    ThreadStatusElectionOutcome as ThreadStatusElectionOutcome,
)
from .thread_repository import (
    ThreadStatusElectionResult as ThreadStatusElectionResult,
)
from .thread_repository import create_thread as create_thread
from .thread_repository import delete_thread as delete_thread
from .thread_repository import elect_thread_deleting as elect_thread_deleting
from .thread_repository import elect_thread_status as elect_thread_status
from .thread_repository import get_thread as get_thread
from .thread_repository import (
    get_thread_execution_state as get_thread_execution_state,
)
from .thread_repository import (
    list_active_thread_page as list_active_thread_page,
)
from .thread_repository import (
    list_non_terminal_threads as list_non_terminal_threads,
)
from .thread_repository import list_threads as list_threads
from .thread_repository import lock_thread_row as lock_thread_row
from .thread_repository import (
    normalize_workspace_identity as normalize_workspace_identity,
)
from .thread_repository import (
    path_safe_run_id_clause as path_safe_run_id_clause,
)
from .thread_repository import (
    record_thread_execution_state as record_thread_execution_state,
)
from .thread_repository import (
    set_thread_approval_state as set_thread_approval_state,
)
from .thread_repository import set_thread_repair_state as set_thread_repair_state
from .thread_repository import thread_owned_by as thread_owned_by
from .thread_repository import (
    thread_write_expectation as thread_write_expectation,
)

__all__ = [
    "CONTROL_ACTION_LEASE_TTL",
    "DEFAULT_SUBSCRIBER_ID",
    "DELETION_SAGA_CLAIM_LEASE",
    "RECOVERY_CLAIM_TTL",
    "ActiveThreadProjection",
    "ArtifactModel",
    "AuthoringEventCursorModel",
    "Base",
    "CheckpointRead",
    "CheckpointReadStatus",
    "ControlActionModel",
    "ControlActionReservation",
    "CostTrackingModel",
    "PendingPermission",
    "PermissionLogModel",
    "PermissionRequestModel",
    "RecoveryAttemptModel",
    "RecoveryFailureArgs",
    "RecoveryRescheduleArgs",
    "RunEventModel",
    "RunEventRecord",
    "RunEventStore",
    "SchemaCompatibilityError",
    "ThreadDeletionSagaModel",
    "ThreadExecutionStateModel",
    "ThreadModel",
    "ThreadStatusElectionOutcome",
    "ThreadStatusElectionResult",
    "acquire_control_action_lease",
    "actionable_pending_permissions",
    "append_cost_record",
    "append_permission_log",
    "application_session_factory",
    "backfill_teamstate_sdd_fields",
    "begin_write_transaction",
    "build_migration_config",
    "claim_deletion_saga_row",
    "claim_recovery_attempt",
    "clear_lease",
    "close_db",
    "commit_control_action_lease",
    "configure_sqlite_engine",
    "configure_sqlite_transactions",
    "count_pending_sdd_backfill",
    "count_queued_continuations",
    "create_control_action",
    "create_thread",
    "delete_thread",
    "due_recovery_attempt_ids",
    "elect_thread_deleting",
    "elect_thread_status",
    "enqueue_continuation",
    "expire_pending_permission_requests",
    "get_authoring_cursor",
    "get_control_action",
    "get_control_action_by_dispatch_id",
    "get_control_action_by_idempotency_key",
    "get_db",
    "get_deletion_saga_row",
    "get_engine",
    "get_latest_control_action",
    "get_pending_permission_requests",
    "get_permission_logs_by_thread",
    "get_permission_request",
    "get_session_factory",
    "get_thread",
    "get_thread_execution_state",
    "get_unapplied_control_actions",
    "get_writer_action",
    "has_live_queued_continuation_lease",
    "idempotency_key_admitted",
    "init_db",
    "insert_deletion_saga_row",
    "inspect_sqlite_database",
    "lease_free_from",
    "list_active_thread_page",
    "list_non_terminal_threads",
    "list_threads",
    "lock_deletion_saga_row",
    "lock_thread_row",
    "mark_control_action_applied",
    "mark_control_action_duplicate",
    "mark_control_action_superseded",
    "mark_permission_request_applied",
    "migration_script_location",
    "new_claim_token",
    "next_queue_position",
    "normalize_workspace_identity",
    "outstanding_permission_pause",
    "overdue_recovery_actions",
    "path_safe_run_id_clause",
    "pending_document_approval_thread",
    "persist_graph_action_receipt",
    "read_cleanup_ledger",
    "read_latest_checkpoint",
    "read_next_queued_continuation",
    "record_permission_request",
    "record_permission_response_submission",
    "record_thread_execution_state",
    "reject_queued_continuations",
    "release_control_action_lease",
    "release_deletion_saga_claim",
    "release_recovery_claim",
    "remove_deletion_saga_row",
    "require_lease_window",
    "reschedule_recovery_claim",
    "reserve_control_action",
    "reset_permission_response_submission",
    "resolve_session_factory",
    "retry_write_contention",
    "run_migrations",
    "save_model",
    "schedule_recovery_attempt",
    "seat_sqlite_posture",
    "select_recoverable_actions",
    "set_authoring_cursor",
    "set_thread_approval_state",
    "set_thread_repair_state",
    "settle_control_action_lease",
    "settle_expired_recovery_attempt",
    "settle_recovery_claim",
    "sum_cost_by_agent",
    "sum_cost_by_thread",
    "supersede_permission_requests",
    "supported_migration_head",
    "swap_cleanup_ledger",
    "thread_owned_by",
    "thread_write_expectation",
    "unscheduled_recovery_actions",
    "validate_desktop_schema",
    "verify_wal_mode",
]
