"""Wire-protocol enums for the frontend-backend contract.

These enums define the discriminators and status types used in WebSocket
messages and REST payloads between the backend orchestrator and the
SvelteKit control surface.

Note: ``Provider`` and ``Model`` live in ``lib.utils.enums`` and are
imported (not duplicated) where needed.
"""

from enum import StrEnum


__all__ = [
    "AgentControlAction",
    "AgentLifecycleState",
    "ClientCommandType",
    "PermissionOptionKind",
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


class AgentLifecycleState(StrEnum):
    """Observable agent states exposed to the frontend.

    Maps to ADR-003 MCP states. Distinct from ``lib.utils.enums.AgentState``
    which tracks internal process lifecycle (init/ready/running/error/done).
    """

    SUBMITTED = "submitted"
    IDLE = "idle"
    WORKING = "working"
    INPUT_REQUIRED = "input_required"
    AUTH_REQUIRED = "auth_required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ToolKind(StrEnum):
    """ACP tool categories (mirrors agentclientprotocol.com schema)."""

    READ = "read"
    EDIT = "edit"
    DELETE = "delete"
    MOVE = "move"
    SEARCH = "search"
    EXECUTE = "execute"
    THINK = "think"
    FETCH = "fetch"
    SWITCH_MODE = "switch_mode"
    OTHER = "other"


class ToolCallStatus(StrEnum):
    """Lifecycle states for a single tool invocation."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class PermissionOptionKind(StrEnum):
    """User permission response options (mirrors ACP PermissionOption.kind).

    M12: Documented for OpenAPI schema generation.

    Values:
        ALLOW_ONCE: Allow the tool call this time only.
        ALLOW_ALWAYS: Allow all future invocations of this tool without prompting.
        REJECT_ONCE: Deny the tool call this time only.
        REJECT_ALWAYS: Deny all future invocations of this tool without prompting.
    """

    ALLOW_ONCE = "allow_once"
    ALLOW_ALWAYS = "allow_always"
    REJECT_ONCE = "reject_once"
    REJECT_ALWAYS = "reject_always"


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
