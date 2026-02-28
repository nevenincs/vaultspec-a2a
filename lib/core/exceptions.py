"""Exception types and error taxonomy for the A2A Orchestrator.

Provides a structured error classification system with severity levels
and recovery action hints, enabling the orchestrator to make intelligent
recovery decisions instead of treating every failure as a crash.

See: docs/architecture/2026-25-02-gap-analysis-audit.md (Gap 6)
"""

from enum import StrEnum


class ErrorSeverity(StrEnum):
    """Classification of error permanence.

    Used by the orchestrator to decide whether retrying is worthwhile.
    """

    TRANSIENT = "transient"
    PERMANENT = "permanent"
    UNKNOWN = "unknown"


class RecoveryAction(StrEnum):
    """Suggested recovery action for an error.

    The orchestrator's error-handling logic uses these hints to pick
    a strategy without hard-coding recovery per exception type.
    """

    RETRY = "retry"
    RETRY_WITH_BACKOFF = "retry_with_backoff"
    REASSIGN = "reassign"
    ESCALATE_TO_USER = "escalate_to_user"
    ABORT = "abort"


# ---------------------------------------------------------------------------
# Base exceptions
# ---------------------------------------------------------------------------


class GitWorkspaceError(Exception):
    """Base exception for all Git Workspace operations."""


class VaultspecError(Exception):
    """Base exception for all Vaultspec operations.

    Every VaultspecError carries a ``severity`` and ``recovery_action``
    so that callers can react programmatically.
    """

    severity: ErrorSeverity = ErrorSeverity.UNKNOWN
    recovery_action: RecoveryAction = RecoveryAction.ESCALATE_TO_USER

    def __init__(
        self,
        message: str = "",
        *,
        severity: ErrorSeverity | None = None,
        recovery_action: RecoveryAction | None = None,
    ) -> None:
        """Initialise with an optional message and per-instance overrides."""
        if severity is not None:
            self.severity = severity
        if recovery_action is not None:
            self.recovery_action = recovery_action
        super().__init__(message)


# ---------------------------------------------------------------------------
# Configuration & workspace
# ---------------------------------------------------------------------------


class ConfigError(VaultspecError):
    """Raised when configuration is invalid or missing."""

    severity = ErrorSeverity.PERMANENT
    recovery_action = RecoveryAction.ABORT


class WorkspaceError(VaultspecError):
    """Raised when workspace operations fail."""

    severity = ErrorSeverity.PERMANENT
    recovery_action = RecoveryAction.ESCALATE_TO_USER


# ---------------------------------------------------------------------------
# Agent execution
# ---------------------------------------------------------------------------


class AgentProcessError(VaultspecError):
    """Raised when an agent process fails to start or crashes."""

    severity = ErrorSeverity.TRANSIENT
    recovery_action = RecoveryAction.RETRY_WITH_BACKOFF


# ---------------------------------------------------------------------------
# Protocol bridging
# ---------------------------------------------------------------------------


class ProtocolError(VaultspecError):
    """Raised when encountering invalid states or messages bridging A2A/MCP."""

    severity = ErrorSeverity.PERMANENT
    recovery_action = RecoveryAction.ABORT


# ---------------------------------------------------------------------------
# Event aggregation
# ---------------------------------------------------------------------------


class EventAggregatorError(VaultspecError):
    """Raised when the central event bus or multiplexer encounters errors."""

    severity = ErrorSeverity.TRANSIENT
    recovery_action = RecoveryAction.RETRY


# ---------------------------------------------------------------------------
# Database / persistence
# ---------------------------------------------------------------------------


class DatabaseError(VaultspecError):
    """Raised when database operations (connect, query, migrate) fail."""

    severity = ErrorSeverity.TRANSIENT
    recovery_action = RecoveryAction.RETRY_WITH_BACKOFF


# ---------------------------------------------------------------------------
# Permission engine
# ---------------------------------------------------------------------------


class PermissionDeniedError(VaultspecError):
    """Raised when a requested action is denied by the permission engine."""

    severity = ErrorSeverity.PERMANENT
    recovery_action = RecoveryAction.ESCALATE_TO_USER


# ---------------------------------------------------------------------------
# Token / context budget
# ---------------------------------------------------------------------------


class TokenBudgetExceededError(VaultspecError):
    """Raised when the token budget for a request or session is exhausted."""

    severity = ErrorSeverity.PERMANENT
    recovery_action = RecoveryAction.REASSIGN


class ContextOverflowError(VaultspecError):
    """Raised when the LLM context window cannot fit the required payload."""

    severity = ErrorSeverity.PERMANENT
    recovery_action = RecoveryAction.REASSIGN


# ---------------------------------------------------------------------------
# Merge / workspace conflicts
# ---------------------------------------------------------------------------


class MergeConflictError(WorkspaceError):
    """Raised when a git merge produces conflicts that need resolution."""

    severity = ErrorSeverity.PERMANENT
    recovery_action = RecoveryAction.ESCALATE_TO_USER


# ---------------------------------------------------------------------------
# Agent / team config discovery
# ---------------------------------------------------------------------------


class NicknameConflictError(VaultspecError):
    """Raised when a thread nickname already exists in the database."""

    severity = ErrorSeverity.PERMANENT
    recovery_action = RecoveryAction.ESCALATE_TO_USER

    def __init__(self, nickname: str) -> None:
        """Raise with a descriptive message for the conflicting nickname."""
        super().__init__(f"Thread nickname already exists: {nickname!r}")
        self.nickname = nickname


class AgentConfigNotFoundError(ConfigError):
    """Raised when no agent TOML can be resolved for a given agent_id.

    Checked locations (in order):
    1. {workspace_root}/.vaultspec/agents/{agent_id}.toml
    2. lib/core/presets/agents/{agent_id}.toml
    """

    def __init__(self, agent_id: str) -> None:
        """Raise with a descriptive message for the missing agent_id."""
        super().__init__(
            f"No agent config found for '{agent_id}'. "
            f"Expected workspace override at .vaultspec/agents/{agent_id}.toml "
            f"or bundled preset at lib/core/presets/agents/{agent_id}.toml."
        )
        self.agent_id = agent_id


class TeamConfigNotFoundError(ConfigError):
    """Raised when no team TOML can be resolved for a given team_id.

    Checked locations (in order):
    1. {workspace_root}/.vaultspec/teams/{team_id}.toml
    2. lib/core/presets/teams/{team_id}.toml
    """

    def __init__(self, team_id: str) -> None:
        """Raise with a descriptive message for the missing team_id."""
        super().__init__(
            f"No team config found for '{team_id}'. "
            f"Expected workspace override at .vaultspec/teams/{team_id}.toml "
            f"or bundled preset at lib/core/presets/teams/{team_id}.toml."
        )
        self.team_id = team_id


__all__ = [
    "AgentConfigNotFoundError",
    "AgentProcessError",
    "ConfigError",
    "ContextOverflowError",
    "DatabaseError",
    "ErrorSeverity",
    "EventAggregatorError",
    "GitWorkspaceError",
    "MergeConflictError",
    "NicknameConflictError",
    "PermissionDeniedError",
    "ProtocolError",
    "RecoveryAction",
    "TeamConfigNotFoundError",
    "TokenBudgetExceededError",
    "VaultspecError",
    "WorkspaceError",
]
