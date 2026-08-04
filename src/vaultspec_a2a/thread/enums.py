"""Domain enums for thread lifecycle, control actions, and permissions.

These are Layer 1 domain types — consumed by infrastructure services
(database, control, api) but defined here as the canonical source.
"""

from enum import StrEnum

__all__ = [
    "ACTIVE_STATUSES",
    "NON_ACTIVE_STATUSES",
    "TERMINAL_STATUSES",
    "TERMINAL_STATUS_VALUES",
    "ApprovalStatus",
    "CleanupKind",
    "ControlActionResultStatus",
    "ControlActionType",
    "InvalidTransitionError",
    "PermissionRequestStatus",
    "RepairStatus",
    "TaskQueueStatus",
    "ThreadStatus",
    "TranscriptAvailability",
]


#: The reviewer verdict vocabulary, shared by the authoring lifecycle and the
#: graph's phase gate. It lives here rather than in either consumer because
#: neither can import the other: `authoring.submitter` already imports the
#: phase-gate seam signal, so the reverse direction would cycle. This module
#: imports nothing but ``StrEnum``, which is what makes it reachable from both.
#:
#: Left as plain strings rather than a StrEnum deliberately: these values cross
#: the engine boundary as raw JSON in both directions, and both consumers
#: compare them against decoded wire values.
VERDICT_APPROVED = "approved"
VERDICT_REJECTED = "rejected"
VERDICT_REQUEST_CHANGES = "request_changes"


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
    DELETING = "deleting"


class RepairStatus(StrEnum):
    """Repair and readiness classification distinct from lifecycle.

    Types BOTH durable columns that carry this classification:
    ``threads.repair_status`` and ``threads.execution_readiness``. The two ask
    different questions — what is wrong with this run, and is it fit to resume —
    but they answer from this one closed set, so a new member becomes available
    to both at once and neither can drift into a private vocabulary.
    """

    HEALTHY = "healthy"
    PAUSED_RESUMABLE = "paused_resumable"
    CANCEL_PENDING = "cancel_pending"
    REPLAY_GAP = "replay_gap"
    CHECKPOINT_UNAVAILABLE = "checkpoint_unavailable"
    NEEDS_RECONCILIATION = "needs_reconciliation"
    OPERATOR_INTERVENTION_REQUIRED = "operator_intervention_required"


class TranscriptAvailability(StrEnum):
    """Why a run's conversation is, or is not, readable from its checkpoint.

    A run's transcript lives only in the checkpoint, so an unread checkpoint
    yields an empty message list that is indistinguishable from a run that
    genuinely said nothing. This classification is what tells the two apart, and
    it exists so no reader has to infer loss from an empty list.

    ``NOT_YET_RECORDED`` is the only non-fault absence: the run has not been
    dispatched, so there is nothing to have lost. ``MISSING`` and ``UNREADABLE``
    are both faults and differ in whether the checkpoint is gone or merely
    unreachable right now.

    A run whose transcript was deliberately released under a retention policy
    would be a fourth, non-fault member. It is deliberately absent: no
    production seam prunes a checkpoint today, so every absence really is a
    fault, and a member with no producer would let a genuine loss be dismissed
    as intended.
    """

    AVAILABLE = "available"
    NOT_YET_RECORDED = "not_yet_recorded"
    MISSING = "missing"
    UNREADABLE = "unreadable"


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


class CleanupKind(StrEnum):
    """The kind of thread-owned state one deletion cleanup item removes.

    Deliberately a kind and never a locator: it names *what class of state* a
    delete touched, so both the durable cleanup manifest and the delete
    response can speak it, while the concrete checkpoint id or artifact path
    stays inside the control plane.
    """

    CHECKPOINT = "checkpoint"
    ARTIFACT_FILE = "artifact_file"


TERMINAL_STATUSES: frozenset[ThreadStatus] = frozenset(
    {
        ThreadStatus.COMPLETED,
        ThreadStatus.FAILED,
        ThreadStatus.CANCELLED,
    }
)

#: The same set as the wire and column strings it is stored and served as.
#:
#: Every consumer that compares a DECODED value - a database column, a JSON
#: body, a relay frame - needs the strings rather than the members, and each was
#: rebuilding them inline. That is not merely repetition: an inline rebuild is a
#: set comprehension re-evaluated on every call in per-thread projection code,
#: and the hand-written variants had already drifted, one of them naming an
#: "error" status this vocabulary has never had. Derived from the authority
#: directly above, so a member added there arrives here in the same edit.
TERMINAL_STATUS_VALUES: frozenset[str] = frozenset(
    status.value for status in TERMINAL_STATUSES
)

NON_ACTIVE_STATUSES: frozenset[ThreadStatus] = TERMINAL_STATUSES | frozenset(
    {
        ThreadStatus.ARCHIVED,
        # DELETING is a durable teardown marker, not a settled outcome: the run
        # is being torn down across the checkpoint, artifact, and control stores
        # and must never be dispatched, cancelled, or messaged again. It is
        # deliberately excluded from TERMINAL_STATUSES (archive eligibility and
        # the terminal-transition invariant apply only to settled outcomes) and
        # from ACTIVE_STATUSES (discovery and product reads hide it).
        ThreadStatus.DELETING,
    }
)

# Active-run discovery is an explicit allowlist. A new lifecycle state remains
# undiscoverable until it is deliberately classified here and in the invariant
# test covering the complete vocabulary.
ACTIVE_STATUSES: frozenset[ThreadStatus] = frozenset(
    {
        ThreadStatus.SUBMITTED,
        ThreadStatus.RUNNING,
        ThreadStatus.INPUT_REQUIRED,
        ThreadStatus.CANCELLING,
        ThreadStatus.REPAIR_NEEDED,
        ThreadStatus.RECONCILING,
    }
)


class InvalidTransitionError(ValueError):
    """Raised when a thread status transition is not allowed."""
