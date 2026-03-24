"""Utility enums and constants for the vaultspec-a2a library."""

from enum import IntEnum, StrEnum

__all__ = [
    "AcpRequestId",
    "AgentState",
    "Environment",
    "LogLevel",
]


class AgentState(StrEnum):
    """Lifecycle states for LangGraph agents/nodes."""

    INIT = "init"
    READY = "ready"
    RUNNING = "running"
    ERROR = "error"
    DONE = "done"


class LogLevel(StrEnum):
    """Standard logging levels."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class Environment(StrEnum):
    """Deployment environments."""

    DEVELOPMENT = "development"
    TESTING = "testing"
    STAGING = "staging"
    PRODUCTION = "production"


class AcpRequestId(IntEnum):
    """Reserved JSON-RPC identifiers for ACP Control Plane operations."""

    INITIALIZE = 1000
    SESSION_SETUP = 1001  # Handles session/new and session/load
    SESSION_PROMPT = 1002
    AUTHENTICATE = 1003
    SESSION_FORK = 1004
    SESSION_LIST = 1005
    SESSION_SET_MODE = 1006
    SESSION_SET_MODEL = 1007
    SESSION_SET_CONFIG_OPTION = 1008
    SESSION_CANCEL = 1009
