"""Enums and constants for the vaultspec-a2a library."""

from enum import IntEnum, StrEnum


__all__ = [
    "MODEL_MAP",
    "PROVIDER_DEFAULT_MODELS",
    "AcpRequestId",
    "AgentState",
    "Environment",
    "LogLevel",
    "Model",
    "Provider",
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


class Provider(StrEnum):
    """Supported LLM providers."""

    CLAUDE = "claude"
    GEMINI = "gemini"
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
    Provider.OPENAI: Model.HIGH,
    Provider.ZHIPU: Model.HIGH,
}


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
