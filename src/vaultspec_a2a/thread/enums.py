"""Domain enums for thread lifecycle, control actions, and permissions.

These are Layer 1 domain types — consumed by infrastructure services
(database, control, api) but defined here as the canonical source.
"""

from enum import StrEnum


class ThreadStatus(StrEnum):
    """Durable lifecycle states for orchestration threads."""

    SUBMITTED = "submitted"
    RUNNING = "running"
    INPUT_REQUIRED = "input_required"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"
    ARCHIVED = "archived"
    REPAIR_NEEDED = "repair_needed"
    RECONCILING = "reconciling"


class RepairStatus(StrEnum):
    """Repair and readiness classification distinct from lifecycle."""

    HEALTHY = "healthy"
    PAUSED_RESUMABLE = "paused_resumable"
    CANCEL_PENDING = "cancel_pending"
    REPLAY_GAP = "replay_gap"
    CHECKPOINT_UNAVAILABLE = "checkpoint_unavailable"
    NEEDS_RECONCILIATION = "needs_reconciliation"
    OPERATOR_INTERVENTION_REQUIRED = "operator_intervention_required"


class ControlActionType(StrEnum):
    """Durable journaled control action types."""

    INGEST = "ingest"
    RESUME = "resume"
    CANCEL = "cancel"
    PERMISSION_REQUEST_CREATED = "permission_request_created"
    PERMISSION_RESPONSE_SUBMITTED = "permission_response_submitted"
    PERMISSION_RESPONSE_APPLIED = "permission_response_applied"
    MESSAGE_FOLLOWUP_REQUESTED = "message_followup_requested"
    MESSAGE_FOLLOWUP_APPLIED = "message_followup_applied"
    REPAIR_STARTED = "repair_started"
    REPAIR_FINISHED = "repair_finished"


class ControlActionResultStatus(StrEnum):
    """Journaled outcome states for control actions."""

    ACCEPTED_NOT_APPLIED = "accepted_not_applied"
    APPLIED = "applied"
    REJECTED_INVALID_STATE = "rejected_invalid_state"
    SUPERSEDED = "superseded"
    DUPLICATE = "duplicate"


class PermissionRequestStatus(StrEnum):
    """Durable lifecycle for permission requests."""

    PENDING = "pending"
    ANSWERED_PENDING_APPLY = "answered_pending_apply"
    APPLIED = "applied"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    EXPIRED_BY_TERMINAL_STATE = "expired_by_terminal_state"


class ApprovalStatus(StrEnum):
    """Durable lifecycle for plan approval state on a thread."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class TaskQueueStatus(StrEnum):
    """Durable execution states for a worker task-queue entry."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


TERMINAL_STATUSES: frozenset[ThreadStatus] = frozenset(
    {
        ThreadStatus.COMPLETED,
        ThreadStatus.FAILED,
        ThreadStatus.CANCELLED,
    }
)

NON_ACTIVE_STATUSES: frozenset[ThreadStatus] = TERMINAL_STATUSES | frozenset(
    {
        ThreadStatus.ARCHIVED,
    }
)


class InvalidTransitionError(ValueError):
    """Raised when a thread status transition is not allowed."""
