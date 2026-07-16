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
    "RESEARCH_ADR_NODE_PHASE",
    "AgentLifecycleState",
    "AgentState",
    "Model",
    "PermissionOptionKind",
    "PermissionType",
    "PipelinePhase",
    "Provider",
    "ToolCallStatus",
    "ToolKind",
    "research_adr_semantic_phase",
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

    Maps to the MCP states. Distinct from ``AgentState`` which tracks
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
    CODEX = "codex"
    DETERMINISTIC = "deterministic"
    GEMINI = "gemini"
    MOCK = "mock"
    OPENAI = "openai"
    ZAI = "zai"
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
    # Codex drives `codex app-server`'s JSON-RPC surface directly (non-ACP); the
    # names are real Codex model ids verified against `model/list` on codex-cli
    # 0.144.4 (an unknown id fails the turn). gpt-5.6-sol is the account default.
    Provider.CODEX: {
        Model.LOW: "gpt-5.4-mini",
        Model.MID: "gpt-5.5",
        Model.HIGH: "gpt-5.6-sol",
        Model.MAX: "gpt-5.6-sol",
    },
    # Deterministic in-process acceptance provider: content is role-keyed, not
    # model-keyed, so these names are inert selectors kept only to satisfy the
    # MODEL_MAP contract.
    Provider.DETERMINISTIC: {
        Model.LOW: "deterministic",
        Model.MID: "deterministic",
        Model.HIGH: "deterministic",
        Model.MAX: "deterministic",
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
    # Z.ai serves the same GLM family over an Anthropic-Messages-compatible
    # endpoint consumed through the Claude ACP path; the model names mirror
    # Provider.ZHIPU.
    Provider.ZAI: {
        Model.LOW: "glm-4.7-flash",
        Model.MID: "glm-4.7-flagship",
        Model.HIGH: "glm-5",
        Model.MAX: "glm-5",
    },
}


# Default model mapping (capability level per provider)
PROVIDER_DEFAULT_MODELS: dict[Provider, Model] = {
    Provider.CLAUDE: Model.MID,
    Provider.CODEX: Model.HIGH,
    Provider.DETERMINISTIC: Model.MID,
    Provider.GEMINI: Model.MID,
    Provider.MOCK: Model.MID,
    Provider.OPENAI: Model.HIGH,
    Provider.ZAI: Model.MID,
    Provider.ZHIPU: Model.HIGH,
}


# ---------------------------------------------------------------------------
# research_adr node -> semantic authoring phase
# ---------------------------------------------------------------------------

# Canonical map from a research_adr structural node name to the product-safe
# semantic authoring phase. The node names are graph-owned (the research_adr
# topology in the compiler), so this lives here as the single source both the
# run-status projection (control) and the SSE frame stamping (streaming) import,
# rather than duplicating the vocabulary in each layer. The dispatch/researcher
# fan-out nodes map by prefix (see ``research_adr_semantic_phase``).
RESEARCH_ADR_NODE_PHASE: dict[str, str] = {
    "synthesis": "synthesizing_research",
    "research_review": "reviewing_research",
    "research_gate": "awaiting_research_decision",
    "adr_author": "writing_adr",
    "adr_review": "reviewing_adr",
    "adr_gate": "awaiting_adr_decision",
}


def research_adr_semantic_phase(node_name: str) -> str | None:
    """Map a research_adr node name to its semantic authoring phase, or None.

    Strips the ``mount_`` prefix, resolves the dispatch and researcher
    fan-out nodes to ``researching`` by prefix, and looks up the remaining
    structural nodes in :data:`RESEARCH_ADR_NODE_PHASE`. Returns None for a node
    that is not part of the research_adr topology (a coder node, the supervisor,
    an empty or end marker), so callers never fabricate a phase.
    """
    node = node_name.removeprefix("mount_")
    if not node or node == "__end__":
        return None
    if node.startswith("research_dispatch"):
        return "researching"
    return RESEARCH_ADR_NODE_PHASE.get(node)
