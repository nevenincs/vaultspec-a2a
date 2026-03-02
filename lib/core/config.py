"""Configuration settings for the A2A Orchestrator."""

from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..utils.enums import Environment, LogLevel, Model, Provider


class Settings(BaseSettings):
    """Core settings for Vaultspec A2A Orchestrator."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="VAULTSPEC_",
        extra="ignore",
    )

    environment: Environment = Field(default=Environment.DEVELOPMENT)
    log_level: LogLevel = Field(default=LogLevel.INFO)
    database_url: str = Field(default="sqlite+aiosqlite:///vaultspec.db")
    workspace_root: Path = Field(default=Path("./workspaces"))
    default_provider: Provider = Field(default=Provider.CLAUDE)
    default_model: Model | None = Field(default=None)
    provider_timeout_seconds: int = Field(
        default=120, description="Global timeout for LLM provider API calls."
    )
    graph_node_timeout_seconds: int = Field(
        default=300,
        description="Per-node step timeout for LangGraph Pregel execution (seconds).",
    )
    # API Keys & Auth (bare ecosystem names take precedence over VAULTSPEC_ prefix)
    anthropic_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "ANTHROPIC_API_KEY", "VAULTSPEC_ANTHROPIC_API_KEY"
        ),
    )
    gemini_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GEMINI_API_KEY", "VAULTSPEC_GEMINI_API_KEY"),
    )
    google_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("GOOGLE_API_KEY", "VAULTSPEC_GOOGLE_API_KEY"),
    )
    openai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_API_KEY", "VAULTSPEC_OPENAI_API_KEY"),
    )
    zhipu_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ZHIPU_API_KEY", "VAULTSPEC_ZHIPU_API_KEY"),
    )
    claude_code_oauth_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "CLAUDE_CODE_OAUTH_TOKEN", "VAULTSPEC_CLAUDE_CODE_OAUTH_TOKEN"
        ),
    )

    host: str = Field(
        default="0.0.0.0",
        description="Bind host for the uvicorn server (VAULTSPEC_HOST).",
    )
    port: int = Field(
        default=8000,
        description="Bind port for the uvicorn server (VAULTSPEC_PORT).",
    )

    api_base_url: str = Field(
        default="http://localhost:8000",
        description="Base URL of this server; used by MCP tools for loopback calls.",
    )

    cors_allowed_origins: list[str] = Field(
        default=[
            "http://localhost:5173",  # Vite dev server
            "http://localhost:4173",  # Vite preview
            "http://localhost:8000",  # FastAPI itself
            "http://127.0.0.1:5173",
            "http://127.0.0.1:4173",
            "http://127.0.0.1:8000",
        ],
        description="Allowed CORS origins for production deployments.",
    )

    # Worker process settings (ADR-019)
    worker_port: int = Field(
        default=8001,
        description="Internal worker HTTP port",
        alias="VAULTSPEC_WORKER_PORT",
    )
    worker_url: str = Field(
        default="http://127.0.0.1:8001",
        description="Worker base URL for dispatch calls",
        alias="VAULTSPEC_WORKER_URL",
    )
    auto_spawn_worker: bool = Field(
        default=True,
        description=(
            "Auto-spawn worker as child process (pip install mode). "
            "Set False for Docker/systemd where worker runs independently."
        ),
        alias="VAULTSPEC_AUTO_SPAWN_WORKER",
    )

    # Environment Flags
    ci: bool = Field(default=False, validation_alias=AliasChoices("VAULTSPEC_CI", "CI"))
    no_color: bool = Field(
        default=False, validation_alias=AliasChoices("VAULTSPEC_NO_COLOR", "NO_COLOR")
    )

    @property
    def is_dev(self) -> bool:
        """Check if running in development environment."""
        return self.environment == Environment.DEVELOPMENT

    @property
    def database_path(self) -> Path:
        """Extract the plain file path from the SQLAlchemy database URL.

        Parses ``sqlite+aiosqlite:///path/to/db.sqlite`` to ``Path(...)``.
        Returns ``:memory:`` for in-memory databases.
        """
        url = self.database_url
        raw = url.split("///", 1)[1] if ":///" in url else "vaultspec.db"
        if raw == ":memory:":
            return Path(":memory:")
        return Path(raw).resolve()


# Global settings instance
settings = Settings()
