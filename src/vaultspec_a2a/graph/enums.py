"""Domain enums for the graph orchestration layer.

These enums define domain-level discriminators and status types used by the
graph compiler, event aggregator, and domain event dataclasses.

``Model``, ``Provider``, ``MODEL_MAP``, and ``PROVIDER_DEFAULT_MODELS`` are
canonical Layer 1 definitions. All consumers import directly from here.
"""

from enum import StrEnum

__all__ = [
    "MODEL_MAP",
    "PROVIDER_DEFAULT_MODELS",
    "REJECT_OPTION_IDS",
    "AgentLifecycleState",
    "AgentState",
    "Model",
    "PermissionOptionKind",
    "PermissionType",
    "PipelinePhase",
    "Provider",
    "ToolCallStatus",
    "ToolKind",
]


class PipelinePhase(StrEnum):
    """Canonical pipeline phases for supervisor routing and vault gating."""

    RESEARCH = "research"
    ADR = "adr"
    PLAN = "plan"
    EXEC = "exec"
    AUDIT = "audit"


class AgentState(StrEnum):
    """Lifecycle states for LangGraph agents/nodes."""

    INIT = "init"
    READY = "ready"
    RUNNING = "running"
    ERROR = "error"
    DONE = "done"


class AgentLifecycleState(StrEnum):
    """Observable agent states exposed to the frontend.

    Maps to ADR-003 MCP states. Distinct from ``AgentState`` which tracks
    internal process lifecycle (init/ready/running/error/done).
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


REJECT_OPTION_IDS: frozenset[str] = frozenset(
    member.value for member in PermissionOptionKind if member.value.startswith("reject")
)


class PermissionType(StrEnum):
    """Discriminator for permission request categories.

    TOOL_PERMISSION: Standard ACP tool call approval.
    PLAN_APPROVAL: Supervisor plan approval before routing to exec worker.
    """

    TOOL_PERMISSION = "tool_permission"
    PLAN_APPROVAL = "plan_approval"


# ---------------------------------------------------------------------------
# LLM provider / capability enums — canonical definitions (Layer 1)
# ---------------------------------------------------------------------------


class Provider(StrEnum):
    """Supported LLM providers."""

    CLAUDE = "claude"
    GEMINI = "gemini"
    MOCK = "mock"
    OPENAI = "openai"
    ZHIPU = "zhipu"


class Model(StrEnum):
    """LLM capability levels.

    Abstracts specific version strings to reduce maintenance burden.
    """

    LOW = "low"
    MID = "mid"
    HIGH = "high"
    MAX = "max"


# Concrete model name mapping as of February 2026
MODEL_MAP: dict[Provider, dict[Model, str]] = {
    Provider.CLAUDE: {
        Model.LOW: "claude-4.5-haiku",
        Model.MID: "claude-4.6-sonnet",
        Model.HIGH: "claude-4.6-opus",
        Model.MAX: "claude-4.6-opus",
    },
    Provider.GEMINI: {
        Model.LOW: "gemini-2.5-flash",
        Model.MID: "gemini-3-flash-preview",
        Model.HIGH: "gemini-3.1-pro-preview",
        Model.MAX: "gemini-3.1-pro-preview",
    },
    Provider.OPENAI: {
        Model.LOW: "gpt-5-mini",
        Model.MID: "gpt-5.2-pro",
        Model.HIGH: "gpt-5.3-codex",
        Model.MAX: "gpt-5.3-codex",
    },
    Provider.MOCK: {
        Model.LOW: "mock-low",
        Model.MID: "mock-mid",
        Model.HIGH: "mock-high",
        Model.MAX: "mock-max",
    },
    Provider.ZHIPU: {
        Model.LOW: "glm-4.7-flash",
        Model.MID: "glm-4.7-flagship",
        Model.HIGH: "glm-5",
        Model.MAX: "glm-5",
    },
}


# Default model mapping (capability level per provider)
PROVIDER_DEFAULT_MODELS: dict[Provider, Model] = {
    Provider.CLAUDE: Model.MID,
    Provider.GEMINI: Model.MID,
    Provider.MOCK: Model.MID,
    Provider.OPENAI: Model.HIGH,
    Provider.ZHIPU: Model.HIGH,
}
