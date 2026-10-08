"""Domain enums for the graph orchestration layer.

These enums define domain-level discriminators and status types used by the
graph compiler, event producer, and domain event dataclasses.

``Provider`` is the canonical Layer 1 lane discriminator. Concrete model
values come only from served provider catalogs.
"""

from enum import StrEnum

__all__ = [
    "RESEARCH_ADR_NODE_PHASE",
    "AgentLifecycleState",
    "PermissionOptionKind",
    "PermissionType",
    "PipelinePhase",
    "Provider",
    "ProviderCondition",
    "SemanticPhase",
    "ServerEventType",
    "StreamFrameKind",
    "ToolCallStatus",
    "ToolKind",
    "research_adr_semantic_phase",
]


class ServerEventType(StrEnum):
    """Discriminator for server-to-client progress-stream events.

    Sited here rather than beside the wire schemas because both sides of the
    worker-to-gateway boundary need it: the schema package types its frames on
    it, and the interprocess serializer decides a frame's kind from it. It had
    been declared once as an API-only enum and restated as eleven string
    literals in that serializer - a closed vocabulary copied by hand, which is
    how an event kind added on one side and missed on the other relays with no
    kind at all. The serializer's own docstring records that happening.
    """

    AGENT_STATUS = "agent_status"
    MESSAGE_CHUNK = "message_chunk"
    THOUGHT_CHUNK = "thought_chunk"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_UPDATE = "tool_call_update"
    PERMISSION_REQUEST = "permission_request"
    # Snake_case because this is a FRAME KIND, and every frame kind is snake_case.
    # The originating specification writes it hyphenated, but that is its house
    # style for naming things rather than evidence about the token: it hyphenates
    # the edge verbs too, and those genuinely ARE hyphenated on the wire
    # (``/ops/a2a/run-start`` is a real URL). So two spellings coexist here on
    # purpose - edge verbs hyphenated, progress-stream frame kinds snake_case -
    # and this member belongs to the second family. Do not "align" the verbs to
    # match it; that would break the edge. A consumer-visible spelling stays a
    # one-line change here if the hyphen ever proves literal for frame kinds too.
    CLARIFICATION_PENDING = "clarification_pending"
    ARTIFACT_UPDATE = "artifact_update"
    PLAN_UPDATE = "plan_update"
    TEAM_STATUS = "team_status"
    ERROR = "error"
    # No graph event produces this one: it is a transport-level keepalive the
    # stream emits on its own. So this vocabulary is deliberately WIDER than the
    # serializer's dispatch, and a reader comparing the two must not treat the
    # difference as a missing case.
    HEARTBEAT = "heartbeat"


class StreamFrameKind(StrEnum):
    """Discriminator for the progress-stream frames no graph event produces.

    The stream mints these about itself - where the run stood at attachment,
    why a stream was refused, what a viewer lost - and the worker's terminal
    relay names the run's outcome with one. They sit beside
    :class:`ServerEventType` rather than inside it because the interprocess
    serializer dispatches on that vocabulary, and a member here has no domain
    event to dispatch from. The keepalive stays there: the worker's own
    heartbeat posts already share that member.
    """

    STREAM_SNAPSHOT = "stream_snapshot"
    THREAD_TERMINAL = "thread_terminal"
    STREAM_REJECTED = "stream_rejected"
    PROGRESS_DROPPED = "progress_dropped"


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

    # Antigravity is its own lane: `agy` has a separate login and serves models
    # from multiple vendors, so the selected lane must remain explicit.
    ANTIGRAVITY = "antigravity"
    CLAUDE = "claude"
    CODEX = "codex"
    DETERMINISTIC = "deterministic"
    KIMI = "kimi"
    OPENAI = "openai"
    ZAI = "zai"
    ZHIPU = "zhipu"


# A failed run has to tell a client something it can act on, and the actions are
# genuinely different: wait, re-authenticate, top up, raise a spend limit, shorten
# the request, or report a bug. The vocabulary below names those outcomes once, so
# every served lane maps its own wire discriminator into the same set and no
# consumer has to pattern-match vendor prose to work out which one happened.
#
# It sits here, beside the lane discriminator and importing nothing but StrEnum,
# because the run read model carries it: a vocabulary declared under `providers/`
# could not be named by a Layer-1 field, so run-history published the condition as
# an unconstrained string while run-status published the enumeration.
#
# The vocabulary is deliberately SMALLER than the set of distinctions the providers
# collectively make, because it admits only distinctions at least one served lane
# can actually carry. Where a lane's wire cannot separate two members, that lane
# maps to the coarser one rather than guessing; the finer member is emitted only by
# a lane whose wire names it. Two members are asymmetric in exactly this way and
# are documented on the members themselves.
#
# Mapping into this vocabulary is TOTAL by contract: every lane mapper in
# `providers/conditions.py` accepts any input and returns a member, with UNKNOWN as
# the floor. A mapper may not raise and may not return nothing, because it runs on
# a path that is already failing and a second failure there costs the client the
# only diagnosis it was going to get.
#
# This is a wire contract consumed by a second repository, so it is additive-only:
# a member may be added, but no member's spelling or meaning may change.


class ProviderCondition(StrEnum):
    """Why a provider failed, in terms a client can act on.

    The value is the wire form: lowercase, underscore-separated, and stable.
    """

    NETWORK_UNREACHABLE = "network_unreachable"
    """The provider could not be reached at all.

    A transport-level failure before any model was engaged. Distinct from
    :attr:`PROVIDER_OVERLOADED`, which is the provider answering to refuse.
    """

    PROVIDER_OVERLOADED = "provider_overloaded"
    """The provider answered that it is temporarily over capacity.

    Retryable and not the caller's fault. Reserved for a wire discriminator
    that names overload specifically; a generic server-side fault is NOT this
    member, because reporting one as overload asserts a cause and a remedy
    (wait) that the wire never stated.
    """

    UNAUTHENTICATED = "unauthenticated"
    """The credential was missing, rejected, or not permitted for this account.

    The remedy is a credential action - log in again, supply a key, or switch
    account - as opposed to waiting or paying.
    """

    THROTTLED = "throttled"
    """The request was refused for rate, and retrying later is the remedy.

    On lanes whose wire cannot separate a short-term rate refusal from an
    exhausted usage window, this is the member both collapse to. That is a hard
    information limit on those lanes rather than an implementation gap: their
    adapter assigns one kind to both cases and consumes the distinguishing
    signal internally, so emitting :attr:`USAGE_EXHAUSTED` there would assert a
    distinction the wire does not carry.
    """

    USAGE_EXHAUSTED = "usage_exhausted"
    """A usage allowance for the plan or period is spent.

    Waiting helps only when the window rolls over, so the remedy is usually a
    plan change rather than a retry. Emitted ONLY by a lane whose wire names
    usage-limit exhaustion in its own right; a lane that reports rate refusals
    and window exhaustion identically emits :attr:`THROTTLED` instead.
    """

    CREDITS_EXHAUSTED = "credits_exhausted"
    """The account's billable balance cannot fund the request.

    The remedy is a billing action. Distinct from :attr:`BUDGET_EXHAUSTED`,
    which is a self-imposed ceiling the operator can lift without paying.
    """

    BUDGET_EXHAUSTED = "budget_exhausted"
    """A configured spend or session budget stopped the request.

    The ceiling is the caller's own, so the remedy is to raise or reset it.
    Emitted only by a lane whose wire names a budget control specifically.
    """

    INVALID_REQUEST = "invalid_request"
    """The request cannot succeed as sent; changing it is the remedy.

    The operative property is that retrying the SAME request cannot help - the
    request itself has to change. That is what a consumer should act on, and it
    is the only claim every mapped discriminator supports.

    Deliberately wider than "the provider rejected it as malformed". Three
    distinct shapes land here, and only the first is a malformed-input refusal:
    a bad shape or unknown model; a policy refusal the provider understood and
    declined on its own terms; and an output or context ceiling reached, which
    may be a CLIENT-configured cap rather than a provider limit and may mean a
    response was truncated rather than refused. Copy written for this member
    must not tell a user their request was invalid, because for the ceiling case
    nothing was wrong with it.
    """

    UNKNOWN = "unknown"
    """The failure carried no discriminator this lane can resolve.

    The floor of every mapping, and a normal outcome rather than a defect: a
    lane may fail in ways its wire does not classify, and saying so plainly is
    more useful than promising a condition that was never observed. It is what
    an unrecognised or absent discriminator resolves to, which is what keeps a
    mapper total when a provider adds a discriminator this vocabulary predates.
    """


# ---------------------------------------------------------------------------
# research_adr node -> semantic authoring phase
# ---------------------------------------------------------------------------


class SemanticPhase(StrEnum):
    """What a run is product-visibly doing, in terms that name no graph node.

    The one vocabulary for a run's semantic position, served on run-status as
    ``semantic_phase``, on the run-start and commit acknowledgements as
    ``semantic_status``, and stamped onto progress frames. Those three fields
    ask the same question at different moments, so they answer from this set.

    It is deliberately wider than the authoring phases alone. A run outside the
    research_adr topology, or between nodes, is honestly ``RUNNING`` rather than
    given a fabricated authoring phase, and a run that has not dispatched is
    ``STARTING``. The terminal members collapse the lifecycle pairs a product
    reader cannot act on separately: an archived run reads ``COMPLETED`` and a
    cancelling one reads ``CANCELLED``, because the distinction is a lifecycle
    fact and this vocabulary is a product one.

    ``RECOVERY_REQUIRED`` is the only member that is not a position: it says the
    run cannot advance until it is repaired, which is what a reader needs before
    any phase detail matters.
    """

    STARTING = "starting"
    RUNNING = "running"
    RESEARCHING = "researching"
    SYNTHESIZING_RESEARCH = "synthesizing_research"
    REVIEWING_RESEARCH = "reviewing_research"
    AWAITING_RESEARCH_DECISION = "awaiting_research_decision"
    WRITING_ADR = "writing_adr"
    REVIEWING_ADR = "reviewing_adr"
    AWAITING_ADR_DECISION = "awaiting_adr_decision"
    WRITING_PLAN = "writing_plan"
    REVIEWING_PLAN = "reviewing_plan"
    AWAITING_PLAN_DECISION = "awaiting_plan_decision"
    RECOVERY_REQUIRED = "recovery_required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Canonical map from a research_adr structural node name to the product-safe
# semantic authoring phase. The node names are graph-owned (the research_adr
# topology in the compiler), so this lives here as the single source both the
# run-status projection (control) and the SSE frame stamping (streaming) import,
# rather than duplicating the vocabulary in each layer. The dispatch/researcher
# fan-out nodes map by prefix (see ``research_adr_semantic_phase``).
#
# Valued by :class:`SemanticPhase` member rather than by literal, so a node
# mapped to a phase this vocabulary does not contain cannot be written here.
RESEARCH_ADR_NODE_PHASE: dict[str, SemanticPhase] = {
    "synthesis": SemanticPhase.SYNTHESIZING_RESEARCH,
    "research_review": SemanticPhase.REVIEWING_RESEARCH,
    "research_gate": SemanticPhase.AWAITING_RESEARCH_DECISION,
    "adr_author": SemanticPhase.WRITING_ADR,
    "adr_review": SemanticPhase.REVIEWING_ADR,
    "adr_gate": SemanticPhase.AWAITING_ADR_DECISION,
    "plan_author": SemanticPhase.WRITING_PLAN,
    "plan_review": SemanticPhase.REVIEWING_PLAN,
    "plan_gate": SemanticPhase.AWAITING_PLAN_DECISION,
}


def research_adr_semantic_phase(node_name: str) -> SemanticPhase | None:
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
        return SemanticPhase.RESEARCHING
    return RESEARCH_ADR_NODE_PHASE.get(node)
