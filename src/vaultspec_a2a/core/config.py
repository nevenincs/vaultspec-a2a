"""Configuration settings for the A2A Orchestrator."""

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..utils.enums import Environment, LogLevel


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
    database_backend: Literal["sqlite", "postgres"] = Field(
        default="postgres",
        alias="VAULTSPEC_DATABASE_BACKEND",
        description="Primary application database backend.",
    )
    checkpoint_backend: Literal["sqlite", "postgres"] = Field(
        default="postgres",
        alias="VAULTSPEC_CHECKPOINT_BACKEND",
        description="LangGraph checkpointer persistence backend.",
    )
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/vaultspec"
    )
    checkpoint_database_url: str | None = Field(
        default=None,
        alias="VAULTSPEC_CHECKPOINT_DATABASE_URL",
        description="Optional dedicated checkpoint database URL/DSN.",
    )
    sqlite_busy_timeout_ms: int = Field(
        default=5000,
        description="Busy timeout applied to SQLite connections.",
        alias="VAULTSPEC_SQLITE_BUSY_TIMEOUT_MS",
    )
    postgres_required: bool = Field(
        default=False,
        alias="VAULTSPEC_POSTGRES_REQUIRED",
        description=(
            "Fail startup loudly when Postgres-backed dependencies are required."
        ),
    )
    workspace_root: Path = Field(default=Path("./workspaces"))
    provider_timeout_seconds: int = Field(
        default=300, description="Global timeout for LLM provider API calls."
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

    mcp_api_base_url: str = Field(
        default="http://localhost:8000",
        description="Base URL for MCP tool loopback calls.",
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

    # Worker process settings (ADR-031)
    worker_port: int = Field(
        default=8001,
        description="Internal worker HTTP port",
        alias="VAULTSPEC_WORKER_PORT",
    )
    worker_host: str = Field(
        default="127.0.0.1",
        description="Bind host for locally managed worker processes.",
        alias="VAULTSPEC_WORKER_HOST",
    )
    worker_url: str = Field(
        default="http://127.0.0.1:8001",
        description="Worker base URL for dispatch calls",
        alias="VAULTSPEC_WORKER_URL",
    )
    internal_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("VAULTSPEC_INTERNAL_TOKEN", "INTERNAL_TOKEN"),
        description=(
            "Bearer token for worker<->control IPC. None disables auth (dev mode)."
        ),
    )
    max_concurrent_threads: int = Field(
        default=5,
        description="Max concurrent graph executions per worker (WPA-001).",
        alias="VAULTSPEC_MAX_CONCURRENT_THREADS",
    )
    auto_spawn_worker: bool = Field(
        default=True,
        description=(
            "Auto-spawn worker as child process on gateway startup (ADR-031 §2.4)."
        ),
        alias="VAULTSPEC_AUTO_SPAWN_WORKER",
    )
    repair_on_startup: bool = Field(
        default=True,
        description="Run durable thread reconciliation during gateway startup.",
        alias="VAULTSPEC_REPAIR_ON_STARTUP",
    )
    repair_strategy: Literal["conservative", "mark_repair_needed"] = Field(
        default="conservative",
        description="Startup reconciliation strategy for non-terminal threads.",
        alias="VAULTSPEC_REPAIR_STRATEGY",
    )

    # ACP backend selection (ADR-002 §5.1)
    acp_backend: Literal["node", "binary"] = Field(
        default="node",
        description=(
            "ACP gateway backend: 'node' uses the npm-installed index.js, "
            "'binary' uses the precompiled Bun executable in src/vaultspec_a2a/bin/. "
            "ADR-002 §5.1 mandates node as default; binary mode is experimental."
        ),
        alias="VAULTSPEC_ACP_BACKEND",
    )

    # LangSmith tracing (bare ecosystem names, no VAULTSPEC_ prefix)
    langsmith_tracing: bool = Field(
        default=False,
        validation_alias=AliasChoices("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2"),
        description=(
            "Enable LangSmith tracing. Defaults OFF"
            " to avoid unexpected quota consumption."
        ),
    )
    langsmith_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("LANGSMITH_API_KEY", "LANGCHAIN_API_KEY"),
    )
    langsmith_project: str | None = Field(
        default=None,
        validation_alias=AliasChoices("LANGSMITH_PROJECT", "LANGCHAIN_PROJECT"),
    )
    langsmith_endpoint: str | None = Field(
        default=None,
        validation_alias=AliasChoices("LANGSMITH_ENDPOINT", "LANGCHAIN_ENDPOINT"),
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
    def resolved_database_backend(self) -> Literal["sqlite", "postgres"]:
        """Validate the configured application database backend against the URL."""
        url = self.database_url
        if self.database_backend == "sqlite" and not url.startswith("sqlite"):
            msg = (
                "VAULTSPEC_DATABASE_BACKEND=sqlite requires "
                "VAULTSPEC_DATABASE_URL to use a sqlite SQLAlchemy URL."
            )
            raise ValueError(msg)
        if self.database_backend == "postgres" and not url.startswith("postgresql"):
            msg = (
                "VAULTSPEC_DATABASE_BACKEND=postgres requires "
                "VAULTSPEC_DATABASE_URL to use a postgresql SQLAlchemy URL."
            )
            raise ValueError(msg)
        return self.database_backend

    @property
    def resolved_checkpoint_backend(self) -> Literal["sqlite", "postgres"]:
        """Validate the configured checkpoint backend against the configured DSN."""
        url = self.checkpoint_database_url or self.database_url
        if self.checkpoint_backend == "sqlite" and not url.startswith("sqlite"):
            msg = (
                "VAULTSPEC_CHECKPOINT_BACKEND=sqlite requires the checkpoint URL "
                "to use a sqlite-compatible scheme."
            )
            raise ValueError(msg)
        if self.checkpoint_backend == "postgres" and not url.startswith("postgresql"):
            msg = (
                "VAULTSPEC_CHECKPOINT_BACKEND=postgres requires the checkpoint URL "
                "to use a postgresql-compatible scheme."
            )
            raise ValueError(msg)
        return self.checkpoint_backend

    @property
    def database_path(self) -> Path:
        """Extract the plain file path from the SQLAlchemy database URL.

        Parses ``sqlite+aiosqlite:///path/to/db.sqlite`` to ``Path(...)``.
        Returns ``:memory:`` for in-memory databases.
        """
        if self.resolved_database_backend != "sqlite":
            msg = "database_path is only valid when the database backend is SQLite."
            raise ValueError(msg)
        url = self.database_url
        raw = url.split("///", 1)[1] if ":///" in url else "vaultspec.db"
        if raw == ":memory:":
            return Path(":memory:")
        return Path(raw).resolve()

    @property
    def checkpoint_path(self) -> Path:
        """Return the SQLite checkpoint path when the checkpoint backend is SQLite."""
        if self.resolved_checkpoint_backend != "sqlite":
            msg = "checkpoint_path is only valid when the checkpoint backend is SQLite."
            raise ValueError(msg)
        url = self.checkpoint_database_url or self.database_url
        raw = url.split("///", 1)[1] if ":///" in url else "vaultspec.db"
        if raw == ":memory:":
            return Path(":memory:")
        return Path(raw).resolve()

    @property
    def checkpoint_connection_string(self) -> str:
        """Return the backend-specific DSN expected by the LangGraph saver."""
        url = self.checkpoint_database_url or self.database_url
        if self.resolved_checkpoint_backend == "sqlite":
            if ":///" not in url:
                msg = f"Unsupported SQLite checkpoint URL: {url!r}"
                raise ValueError(msg)
            raw = url.split("///", 1)[1]
            if raw == ":memory:":
                return ":memory:"
            return str(Path(raw).resolve())

        return url.replace("postgresql+asyncpg://", "postgresql://", 1).replace(
            "postgresql+psycopg://", "postgresql://", 1
        )

    @property
    def database_sync_url(self) -> str:
        """Return a synchronous SQLAlchemy URL for admin/CLI operations."""
        if self.resolved_database_backend == "sqlite":
            return self.database_url.replace("+aiosqlite", "", 1)
        return self.database_url.replace("+asyncpg", "+psycopg", 1)


# Global settings instance
settings = Settings()
