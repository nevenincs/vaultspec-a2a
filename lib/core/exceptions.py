"""Exception types for the A2A Orchestrator."""


class GitWorkspaceError(Exception):
    """Base exception for all Git Workspace operations."""


class VaultspecError(Exception):
    """Base exception for all Vaultspec operations."""


class ConfigError(VaultspecError):
    """Raised when configuration is invalid or missing."""


class WorkspaceError(VaultspecError):
    """Raised when workspace operations fail."""


class AgentProcessError(VaultspecError):
    """Raised when an agent process fails to start or crashes."""


class ProtocolError(VaultspecError):
    """Raised when encountering invalid states or messages bridging A2A/MCP."""
