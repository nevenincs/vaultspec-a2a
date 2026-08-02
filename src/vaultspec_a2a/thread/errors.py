"""Exception types for the A2A Orchestrator, and the rendering of one failure.

The hierarchy names WHERE a failure happened - configuration, agent process,
protocol bridging, persistence, permissions, budget - so callers can catch at
the granularity they can act on. It deliberately carries no classification of
WHY a provider refused work: that is the provider condition vocabulary's job,
resolved at the lane from the discriminator the provider itself put on the
wire, and a second vocabulary here could only guess at it from the catch site.

The renderers below are the shared half. Every path that has to name a failure
in one client-visible line uses them, so a reason reads the same whether it came
from the graph stream, the executor, or a dispatch that never started.
"""

# Bounds the message portion of one rendered exception identity. A client-visible
# failure reason is assembled from a small number of these, and the durable
# ``threads.failure_reason`` column - and the consumer validating it - are byte
# bounded, so no single link in a cause chain may consume the whole budget.
_MAX_DETAIL_MESSAGE_LEN = 240

# How many links of a ``__cause__`` chain reach a client. The links that carry
# the answer are the first few - the catch site, its wrapper, and the fault that
# started it - and every further link spends the capped budget on framework
# plumbing the reader cannot act on.
_MAX_CHAIN_LINKS = 4

# Bounds a whole rendered chain. Matches the durable ``threads.failure_reason``
# cap, so a reason assembled here survives the durable write intact instead of
# being truncated a second time at a boundary that cannot say what it dropped.
_MAX_CHAIN_LEN = 500


def describe_exception(exc: BaseException) -> str:
    """Render one exception's own identity: its type, its code, and its message.

    Single-line and bounded, so the result is safe to place on a client-visible
    failure reason. The rendering is deliberately NON-recursive - it describes
    *this* exception only and never follows ``__cause__`` - because callers that
    walk a cause chain compose the links themselves, and a self-recursive
    rendering would report the same provider fault twice inside one capped
    string, crowding out the attribution that names where it happened.

    A ``message`` attribute is preferred over ``str(exc)`` when the exception
    publishes one, following the convention the ACP errors already set: that
    attribute is the exception's own cause-free text, whereas ``str`` may fold in
    a wrapped cause or a vendor-shaped payload.
    """
    message = getattr(exc, "message", None)
    if not isinstance(message, str) or not message:
        message = str(exc)
    label = type(exc).__name__
    code = getattr(exc, "code", None)
    if isinstance(code, bool):
        code = None
    if isinstance(code, int):
        label = f"{label}[{code:d}]"
    elif isinstance(code, str) and code:
        label = f"{label}[{code}]"
    message = " ".join(message.split())
    if len(message) > _MAX_DETAIL_MESSAGE_LEN:
        message = message[: _MAX_DETAIL_MESSAGE_LEN - 1] + "…"
    return f"{label}: {message}" if message else label


def describe_exception_chain(exc: BaseException) -> str:
    """Render an exception and the causes it was raised from, oldest link last.

    What reaches a reporting site is rarely the failure itself: a provider fault
    raised inside a worker node arrives as a wrapper, and describing the wrapper
    alone answers where a run died rather than why. So each link is described in
    turn by :func:`describe_exception` and joined, bounded in both the number of
    links and the total length.

    Only ``__cause__`` is followed, never ``__context__``: an explicit
    ``raise ... from`` states that one failure explains another, whereas implicit
    context merely records what happened to be in flight, which is how an
    unrelated cleanup error comes to be reported as the reason a run failed.

    Every path that has to name a failure in one client-visible line shares this
    rendering, so the reason a run failed reads the same whether it was the graph
    stream, the executor's own machinery, or a dispatch that never started.
    """
    links: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and len(links) < _MAX_CHAIN_LINKS:
        if id(current) in seen:  # a chain may be cyclic; describe each link once
            break
        seen.add(id(current))
        links.append(describe_exception(current))
        current = current.__cause__
    detail = " <- ".join(links)
    if len(detail) > _MAX_CHAIN_LEN:
        detail = detail[: _MAX_CHAIN_LEN - 1] + "…"
    return detail


# ---------------------------------------------------------------------------
# Base exceptions
# ---------------------------------------------------------------------------


class GitWorkspaceError(Exception):
    """Base exception for all Git Workspace operations."""

    __slots__ = ()


class VaultspecError(Exception):
    """Base exception for all Vaultspec operations.

    A common root so a caller can catch everything this project raises without
    also catching the interpreter's own failures. It adds no state of its own:
    what a subclass carries is whatever that subclass's own failure needs.
    """

    __slots__ = ()


# ---------------------------------------------------------------------------
# Configuration & workspace
# ---------------------------------------------------------------------------


class ConfigError(VaultspecError):
    """Raised when configuration is invalid or missing."""

    __slots__ = ()


class ProjectionRefusedError(ConfigError):
    """Raised when the run workspace cannot host a projected ``.mcp.json``.

    The surfacing channel merges the declared MCP set into the run workspace's
    ``.mcp.json`` (the only scope the adapter path surfaces), adding its entries
    alongside any the project already declares. Refusal is narrow: a declared
    server name that collides with an existing NON-projected entry (silently
    shadowing either side is unacceptable), or an existing ``.mcp.json`` that
    cannot be parsed (projecting over a file we cannot reason about would risk the
    project's real config). A sibling of :class:`IsolationRequiredError`: both mean
    the run cannot establish its declared, bounded MCP surface, so it must not
    launch.
    """

    __slots__ = ()


class IsolationRequiredError(ConfigError):
    """Raised when a harness-armed run cannot get its required CLI isolation.

    The agent-harness-provisioning ADR binds a spawned agent's MCP surface to an
    allowlist equal to the declared harness; enforcing that requires a per-run
    isolated ``CLAUDE_CONFIG_DIR`` established from an env-carried provider token.
    An armed run that resolves to ``auth_mode == "none_detected"`` (refused at
    compile) or that reaches the ACP spawn without an isolated home (refused at
    the spawn seam) must fail loud here rather than launch an agent with an
    unbounded MCP surface that inherits ambient and workspace ``.mcp.json``
    servers. A ``ConfigError`` so the compile path wraps it as a
    ``GraphCompilationError``.
    """

    __slots__ = ()


class HarnessToolContractError(ConfigError):
    """Raised when a declared harness MCP server does not serve its declared tools.

    The harness registry declares, per server, the read-only tools the run expects
    it to serve; those names become the autonomous allowlist and the Codex
    ``enabled_tools`` set. That declaration is the compatibility contract with the
    separately released server, and it is verified against the server's own
    ``tools/list`` before the run launches - a declared-but-unchecked contract is
    the defect class this codebase keeps finding. A third sibling of
    :class:`IsolationRequiredError` and :class:`ProjectionRefusedError`: all three
    mean the run cannot establish the declared, bounded MCP surface it was promised,
    so it must refuse rather than launch an agent whose grounding tools are silently
    absent. Raised equally when the probe itself cannot complete, because an
    unverifiable contract is an unmet one.
    """

    __slots__ = ()


# ---------------------------------------------------------------------------
# Agent execution
# ---------------------------------------------------------------------------


class AgentProcessError(VaultspecError):
    """Raised when an agent process fails to start or crashes."""

    __slots__ = ()


class WorkerExecutionError(VaultspecError):
    """Raised when a worker node's model invocation fails after all retries.

    The wrapper names the worker turn that failed AND the failure that caused it.
    Attribution alone - which is all this exception used to carry - identifies
    where a run died and nothing about why: the provider's own type, message and
    numeric code survived only on ``__cause__`` and in the worker's log, so every
    provider fault reached a client as the same opaque sentence. ``str`` therefore
    folds in a rendered identity of *cause*, while ``message`` keeps the
    cause-free attribution for readers composing their own cause chain.
    """

    __slots__ = ("message", "message_count", "model", "worker")

    def __init__(
        self,
        worker: str,
        model: str,
        message_count: int,
        *,
        cause: BaseException | None = None,
    ) -> None:
        """Record worker, model, message count, and the failure being wrapped."""
        attribution = f"worker={worker!r} model={model} messages={message_count}"
        detail = describe_exception(cause) if cause is not None else None
        super().__init__(f"{attribution} | {detail}" if detail else attribution)
        self.worker = worker
        self.model = model
        self.message_count = message_count
        self.message = attribution


# ---------------------------------------------------------------------------
# Protocol bridging
# ---------------------------------------------------------------------------


class ProtocolError(VaultspecError):
    """Raised when encountering invalid states or messages bridging A2A/MCP."""

    __slots__ = ()


# ---------------------------------------------------------------------------
# Provider session
# ---------------------------------------------------------------------------


class ProviderSessionError(VaultspecError):
    """Raised when a provider session (e.g. ACP) encounters a fatal error.

    Used by graph/ to wrap provider-specific exceptions (like AcpSessionError)
    so that Layer 1 code never imports from the providers layer.
    """

    __slots__ = ()


# ---------------------------------------------------------------------------
# Event aggregation
# ---------------------------------------------------------------------------


class EventAggregatorError(VaultspecError):
    """Raised when the central event bus or multiplexer encounters errors."""

    __slots__ = ()


# ---------------------------------------------------------------------------
# Database / persistence
# ---------------------------------------------------------------------------


class DatabaseError(VaultspecError):
    """Raised when database operations (connect, query, migrate) fail."""

    __slots__ = ()


# ---------------------------------------------------------------------------
# Permission engine
# ---------------------------------------------------------------------------


class PermissionDeniedError(VaultspecError):
    """Raised when a requested action is denied by the permission engine."""

    __slots__ = ()


# ---------------------------------------------------------------------------
# Token / context budget
# ---------------------------------------------------------------------------


class TokenBudgetExceededError(VaultspecError):
    """Raised when the token budget for a request or session is exhausted."""

    __slots__ = ()


class ContextOverflowError(VaultspecError):
    """Raised when the LLM context window cannot fit the required payload."""

    __slots__ = ()


# ---------------------------------------------------------------------------
# Agent / team config discovery
# ---------------------------------------------------------------------------


class NicknameConflictError(VaultspecError):
    """Raised when a thread nickname already exists in the database."""

    __slots__ = ("nickname",)

    def __init__(self, nickname: str) -> None:
        """Raise with a descriptive message for the conflicting nickname."""
        super().__init__(f"Thread nickname already exists: {nickname!r}")
        self.nickname = nickname


class AgentConfigNotFoundError(ConfigError):
    """Raised when no agent TOML can be resolved for a given agent_id.

    Checked locations (in order):
    1. {workspace_root}/.vaultspec/agents/{agent_id}.toml
    2. src/vaultspec_a2a/team/presets/agents/{agent_id}.toml
    """

    __slots__ = ("agent_id",)

    def __init__(self, agent_id: str) -> None:
        """Raise with a descriptive message for the missing agent_id."""
        super().__init__(
            f"No agent config found for '{agent_id}'. "
            f"Expected workspace override at .vaultspec/agents/{agent_id}.toml "
            "or bundled preset at "
            f"src/vaultspec_a2a/team/presets/agents/{agent_id}.toml."
        )
        self.agent_id = agent_id


class TeamConfigNotFoundError(ConfigError):
    """Raised when no team TOML can be resolved for a given team_id.

    Checked locations (in order):
    1. {workspace_root}/.vaultspec/teams/{team_id}.toml
    2. src/vaultspec_a2a/team/presets/teams/{team_id}.toml
    """

    __slots__ = ("team_id",)

    def __init__(self, team_id: str) -> None:
        """Raise with a descriptive message for the missing team_id."""
        super().__init__(
            f"No team config found for '{team_id}'. "
            f"Expected workspace override at .vaultspec/teams/{team_id}.toml "
            f"or bundled preset at src/vaultspec_a2a/team/presets/teams/{team_id}.toml."
        )
        self.team_id = team_id


__all__ = [
    "AgentConfigNotFoundError",
    "AgentProcessError",
    "ConfigError",
    "ContextOverflowError",
    "DatabaseError",
    "EventAggregatorError",
    "GitWorkspaceError",
    "HarnessToolContractError",
    "IsolationRequiredError",
    "NicknameConflictError",
    "PermissionDeniedError",
    "ProjectionRefusedError",
    "ProtocolError",
    "ProviderSessionError",
    "TeamConfigNotFoundError",
    "TokenBudgetExceededError",
    "VaultspecError",
    "WorkerExecutionError",
    "describe_exception",
    "describe_exception_chain",
]
