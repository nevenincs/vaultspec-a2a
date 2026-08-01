"""Domain enums for the graph orchestration layer.

These enums define domain-level discriminators and status types used by the
graph compiler, event aggregator, and domain event dataclasses.

``Model``, ``Provider``, ``MODEL_MAP``, and ``PROVIDER_DEFAULT_MODELS`` are
canonical Layer 1 definitions. All consumers import directly from here.
"""

from enum import StrEnum

from .acp_options import option_id_of

__all__ = [
    "MODEL_MAP",
    "PROVIDER_DEFAULT_MODELS",
    "REJECT_OPTION_IDS",
    "REJECT_OPTION_KINDS",
    "RESEARCH_ADR_NODE_PHASE",
    "AgentLifecycleState",
    "Model",
    "PermissionOptionKind",
    "PermissionType",
    "PipelinePhase",
    "Provider",
    "ToolCallStatus",
    "ToolKind",
    "is_rejection_response",
    "research_adr_semantic_phase",
]


class PipelinePhase(StrEnum):
    """Canonical pipeline phases for supervisor routing and vault gating."""

    RESEARCH = "research"
    ADR = "adr"
    PLAN = "plan"
    EXEC = "exec"
    AUDIT = "audit"


class AgentLifecycleState(StrEnum):
    """Observable agent states exposed to the frontend.

    Maps to the MCP states. Tracks
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


REJECT_OPTION_KINDS: frozenset[str] = frozenset(
    member.value for member in PermissionOptionKind if member.value.startswith("reject")
)
"""The closed set of ``PermissionOptionKind`` values that deny a request.

A *kind* is drawn from the ACP schema enum, so this set is total over it. It is
matched against an option's ``kind`` field — never against an option *id*, which
is a different, provider-defined namespace (see :data:`REJECT_OPTION_IDS`).
"""


REJECT_OPTION_IDS: frozenset[str] = REJECT_OPTION_KINDS | frozenset(
    {"reject", "deny", "deny_once", "deny_always"}
)
"""The rejecting option *ids* this system is known to mint or receive.

Unlike a kind, an option id is free-form and provider-defined: Kimi offers a bare
``"reject"`` whose kind is ``reject_once``, the plan and document approval gates
mint ``"reject"``, the no-options fallback mints ``"deny_once"``, the ACP handlers
fall back to the bare literals ``"deny"`` and ``"reject"``, and providers that
spell an id with its kind offer ``"reject_once"``/``"reject_always"`` — hence the
union with :data:`REJECT_OPTION_KINDS`.

This set is therefore a *best-effort* recogniser and can never be complete, which
is precisely why :func:`is_rejection_response` consults the declared kind first
and reaches for this only when no kind is available.
"""


def is_rejection_response(options: object, option_id: str | None) -> bool:
    """Report whether the chosen option denies the request it answered.

    This is the single rejection verdict for the whole system. Every settlement
    site — the submission stamp, the ``permission_resolved`` projection, and the
    progress-inferred fallback — asks this one question, so a denial cannot be
    recorded as an approval by one path and a rejection by another.

    The verdict prefers the option's declared ``kind`` because a kind is a closed
    vocabulary: it is total over :class:`PermissionOptionKind` and so classifies a
    provider id this module has never seen. Only when the chosen option cannot be
    found among ``options``, or carries no usable kind, does it fall back to the
    id spellings in :data:`REJECT_OPTION_IDS` — a legacy or malformed durable row
    still gets the best answer available rather than silently reading as approved.

    Args:
        options:   The options that were offered, as decoded from the durable
                   ``allowed_options_json`` column or an in-flight payload. Both
                   the ACP ``optionId`` and snake_case ``option_id`` spellings are
                   accepted. Anything that is not a list of dicts simply offers
                   no kind, which routes the verdict to the id fallback.
        option_id: The id the responder chose. ``None`` or empty means nothing was
                   chosen, which is not a rejection.

    Returns:
        True when the response denied the request.
    """
    if not option_id:
        return False
    if isinstance(options, list):
        for option in options:
            if option_id_of(option) != option_id:
                continue
            kind = option.get("kind") if isinstance(option, dict) else None
            # ``kind`` may arrive as a PermissionOptionKind or its bare value; a
            # StrEnum compares equal to its value, so normalising to str covers
            # both without narrowing to one transport's spelling.
            if isinstance(kind, str) and kind:
                return kind in REJECT_OPTION_KINDS
            break
    return option_id in REJECT_OPTION_IDS


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
    KIMI = "kimi"
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
    # Kimi (Moonshot AI) drives its own `kimi acp` agent; KIMI_MODEL_NAME
    # selects the model. The names are the kimi-k2 family the installed
    # kimi-cli 1.49.0 recognizes (source guards on `startswith("kimi-k2")`),
    # with the thinking variant at the higher tiers. The account's exact
    # available ids are confirmed only on KIMI_API_KEY arrival (P05).
    Provider.KIMI: {
        Model.LOW: "kimi-k2",
        Model.MID: "kimi-k2",
        Model.HIGH: "kimi-k2-thinking",
        Model.MAX: "kimi-k2-thinking",
    },
}


# Default model mapping (capability level per provider)
PROVIDER_DEFAULT_MODELS: dict[Provider, Model] = {
    Provider.CLAUDE: Model.MID,
    Provider.CODEX: Model.HIGH,
    Provider.DETERMINISTIC: Model.MID,
    Provider.GEMINI: Model.MID,
    Provider.KIMI: Model.MID,
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
