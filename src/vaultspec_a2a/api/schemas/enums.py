"""Wire-protocol enums for the frontend-backend contract.

Domain enums (``ToolKind``, ``PermissionType``, ``PermissionOptionKind``,
``ToolCallStatus``, ``AgentLifecycleState``) are defined in
``vaultspec_a2a.graph.enums`` and re-exported here for backwards compatibility.

API-only enums (``ServerEventType``, ``ClientCommandType``,
``AgentControlAction``, ``PlanEntryStatus``, ``PlanEntryPriority``) remain
local — they are wire-protocol concerns, not domain concepts.

Note: ``Provider`` and ``Model`` live in ``vaultspec_a2a.utils.enums`` and are
imported (not duplicated) where needed.
"""

from enum import StrEnum

from vaultspec_a2a.graph.enums import AgentLifecycleState as AgentLifecycleState
from vaultspec_a2a.graph.enums import PermissionOptionKind as PermissionOptionKind
from vaultspec_a2a.graph.enums import PermissionType as PermissionType
from vaultspec_a2a.graph.enums import ToolCallStatus as ToolCallStatus
from vaultspec_a2a.graph.enums import ToolKind as ToolKind

__all__ = [
    "AgentControlAction",
    "AgentLifecycleState",
    "ClientCommandType",
    "PermissionOptionKind",
    "PermissionType",
    "PlanEntryPriority",
    "PlanEntryStatus",
    "ServerEventType",
    "ToolCallStatus",
    "ToolKind",
]


class ServerEventType(StrEnum):
    """Discriminator for server-to-client WebSocket events."""

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
    CONNECTED = "connected"
    HEARTBEAT = "heartbeat"


class ClientCommandType(StrEnum):
    """Discriminator for client-to-server WebSocket commands."""

    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"
    SEND_MESSAGE = "send_message"
    PERMISSION_RESPONSE = "permission_response"
    AGENT_CONTROL = "agent_control"
    PING = "ping"


class AgentControlAction(StrEnum):
    """Actions a user can issue to control a running agent."""

    PAUSE = "pause"
    RESUME = "resume"
    TERMINATE = "terminate"


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
