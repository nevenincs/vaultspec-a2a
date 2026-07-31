"""Wire-protocol enums for the frontend-backend contract.

API-only enums (``ServerEventType``, ``PlanEntryStatus``,
``PlanEntryPriority``) remain local — they are wire-protocol concerns, not
domain concepts.

Domain enums (``ToolKind``, ``PermissionType``, ``PermissionOptionKind``,
``ToolCallStatus``, ``AgentLifecycleState``) are defined in
``vaultspec_a2a.graph.enums``; import them from there directly.

Note: ``Provider`` and ``Model`` live in ``vaultspec_a2a.utils.enums`` and are
imported (not duplicated) where needed.
"""

from enum import StrEnum

__all__ = [
    "PlanEntryPriority",
    "PlanEntryStatus",
    "ServerEventType",
]


class ServerEventType(StrEnum):
    """Discriminator for server-to-client progress-stream events."""

    AGENT_STATUS = "agent_status"
    MESSAGE_CHUNK = "message_chunk"
    THOUGHT_CHUNK = "thought_chunk"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_UPDATE = "tool_call_update"
    PERMISSION_REQUEST = "permission_request"
    ARTIFACT_UPDATE = "artifact_update"
    PLAN_UPDATE = "plan_update"
    TEAM_STATUS = "team_status"
    ERROR = "error"
    HEARTBEAT = "heartbeat"


class PlanEntryStatus(StrEnum):
    """Execution status of a plan entry."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class PlanEntryPriority(StrEnum):
    """Priority level for a plan entry."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
