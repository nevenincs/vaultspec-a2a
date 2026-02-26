from enum import StrEnum


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
    CODEX = "codex"
    GLM5 = "glm5"
