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
    OPENAI = "openai"
    ZHIPU = "zhipu"


class Model(StrEnum):
    """
    LLM Model version tags as of March 2026.
    Centralized here to avoid hardcoded strings throughout the codebase.
    """

    # Anthropic
    CLAUDE_4_6_OPUS = "claude-4.6-opus"
    CLAUDE_4_6_SONNET = "claude-4.6-sonnet"
    CLAUDE_4_5_HAIKU = "claude-4.5-haiku"

    # Google
    GEMINI_3_1_PRO = "gemini-3.1-pro"
    GEMINI_3_PRO = "gemini-3-pro"
    GEMINI_3_FLASH = "gemini-3-flash"
    GEMINI_3_FLASH_PREVIEW = "gemini-3-flash-preview"

    # OpenAI
    GPT_5_2_CODEX = "gpt-5.2-codex"
    GPT_5_2_PRO = "gpt-5.2-pro"
    GPT_5_MINI = "gpt-5-mini"
    GPT_5_NANO = "gpt-5-nano"

    # Zhipu AI (GLM)
    GLM_5 = "glm-5"
    GLM_4_7_FLAGSHIP = "glm-4.7-flagship"
    GLM_4_7_FLASH = "glm-4.7-flash"


# Default model mapping to avoid logic duplication in factory
PROVIDER_DEFAULT_MODELS: dict[Provider, Model] = {
    Provider.CLAUDE: Model.CLAUDE_4_6_SONNET,
    Provider.GEMINI: Model.GEMINI_3_FLASH_PREVIEW,
    Provider.OPENAI: Model.GPT_5_2_CODEX,
    Provider.ZHIPU: Model.GLM_5,
}
