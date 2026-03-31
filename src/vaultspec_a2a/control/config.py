"""Infrastructure configuration and backwards-compatible Settings facade.

``InfraConfig`` holds every field that touches external services: ports, hosts,
database URLs, API keys, filesystem paths, pool sizes, service timeouts, etc.

``Settings`` composes ``DomainConfig`` (Layer 1 behavioural knobs) with
``InfraConfig`` via multiple inheritance, producing a single object that is
a drop-in replacement for the former ``core.config.Settings``.
"""

from pathlib import Path
from typing import Literal, Self

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..domain_config import DomainSettingsConfig
from ..utils.enums import Environment, LogLevel

# Defaults for path-override fields.  Computed once at module import relative to
# this file: control/config.py → control → vaultspec_a2a → src → project-root.
_DEFAULT_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent.parent
_DEFAULT_UI_BUILD_DIR: Path = _DEFAULT_PROJECT_ROOT / "src" / "ui" / "dist"


class InfraConfig(BaseSettings):
    """Infrastructure fields — ports, hosts, URLs, keys, filesystem paths."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="VAULTSPEC_",
        extra="ignore",
    )

    environment: Environment = Field(default=Environment.DEVELOPMENT)
    log_level: LogLevel = Field(default=LogLevel.INFO)
    database_backend: Literal["sqlite", "postgres"] = Field(
        default="sqlite",
        alias="VAULTSPEC_DATABASE_BACKEND",
        description=(
            "Primary application database backend.  SQLite is the local/dev "
            "default (ADR-035).  Production deployments set 'postgres' via env."
        ),
    )
    checkpoint_backend: Literal["sqlite", "postgres"] = Field(
        default="sqlite",
        alias="VAULTSPEC_CHECKPOINT_BACKEND",
        description=(
            "LangGraph checkpointer persistence backend.  Follows the same "
            "convention as database_backend: sqlite for dev, postgres for prod."
        ),
    )
    database_url: str = Field(
        default="sqlite+aiosqlite:///vaultspec.db",
        description=(
            "SQLAlchemy async database URL.  Must match the selected "
            "database_backend scheme (sqlite+aiosqlite or postgresql+asyncpg)."
        ),
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
    db_pool_size: int = Field(
        default=5,
        alias="VAULTSPEC_DB_POOL_SIZE",
        description="SQLAlchemy QueuePool pool_size for Postgres engine.",
    )
    db_pool_max_overflow: int = Field(
        default=10,
        alias="VAULTSPEC_DB_POOL_MAX_OVERFLOW",
        description="SQLAlchemy QueuePool max_overflow for Postgres engine.",
    )
    workspace_root: Path = Field(default=Path("./workspaces"))
    project_root: Path = Field(
        default_factory=lambda: _DEFAULT_PROJECT_ROOT,
        alias="VAULTSPEC_PROJECT_ROOT",
        description=(
            "Absolute path to the repository root.  Computed from __file__ by "
            "default; override in Docker non-editable installs where __file__ "
            "resolves inside site-packages."
        ),
    )
    ui_build_dir: Path = Field(
        default_factory=lambda: _DEFAULT_UI_BUILD_DIR,
        alias="VAULTSPEC_UI_BUILD_DIR",
        description=(
            "Absolute path to the React SPA build output (src/ui/dist).  "
            "Computed from project_root by default; override in Docker "
            "non-editable installs."
        ),
    )
    mock_api_base: str | None = Field(
        default=None,
        alias="MOCK_API_BASE",
        description=(
            "Base URL for the VidaiMock tape-replay server.  Used by "
            "MockChatModel when Provider.MOCK is selected.  "
            "Example: http://vidaimock:8100"
        ),
    )
    provider_timeout_seconds: int = Field(
        default=120,
        description="Global timeout (seconds) for LLM provider API calls.",
    )
    # API Keys — bare ecosystem names only; no VAULTSPEC_ prefix aliases.
    anthropic_api_key: str | None = Field(
        default=None,
        validation_alias="ANTHROPIC_API_KEY",
    )
    gemini_api_key: str | None = Field(
        default=None,
        validation_alias="GEMINI_API_KEY",
    )
    google_api_key: str | None = Field(
        default=None,
        validation_alias="GOOGLE_API_KEY",
    )
    google_application_credentials: str | None = Field(
        default=None,
        validation_alias="GOOGLE_APPLICATION_CREDENTIALS",
    )
    google_cloud_project: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "GOOGLE_CLOUD_PROJECT",
            "GOOGLE_CLOUD_PROJECT_ID",
        ),
    )
    google_cloud_location: str | None = Field(
        default=None,
        validation_alias="GOOGLE_CLOUD_LOCATION",
    )
    gemini_cli_home: str | None = Field(
        default=None,
        validation_alias="GEMINI_CLI_HOME",
    )
    openai_api_key: str | None = Field(
        default=None,
        validation_alias="OPENAI_API_KEY",
    )
    zhipu_api_key: str | None = Field(
        default=None,
        validation_alias="ZHIPU_API_KEY",
    )
    claude_code_oauth_token: str | None = Field(
        default=None,
        validation_alias="CLAUDE_CODE_OAUTH_TOKEN",
    )

    host: str = Field(
        default="0.0.0.0",
        description="Bind host for the uvicorn server (VAULTSPEC_HOST).",
    )
    port: int = Field(
        default=8000,
        description="Bind port for the uvicorn server (VAULTSPEC_PORT).",
    )

    gateway_url: str = Field(
        default="",
        validation_alias=AliasChoices(
            "VAULTSPEC_GATEWAY_URL",
            "VAULTSPEC_MCP_API_BASE_URL",
        ),
        description=(
            "Base URL for reaching the gateway HTTP API. Used by the worker "
            "IPC bridge and the MCP tool server. Auto-derived from host+port "
            "when not set explicitly."
        ),
    )
    mcp_host: str = Field(
        default="0.0.0.0",
        alias="VAULTSPEC_MCP_HOST",
        description="Bind host for MCP streamable-http transport.",
    )
    mcp_port: int = Field(
        default=8200,
        alias="VAULTSPEC_MCP_PORT",
        description="Bind port for MCP streamable-http transport.",
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
        default="",
        description=(
            "Worker base URL for dispatch calls. "
            "Auto-derived from worker_host + worker_port."
        ),
        alias="VAULTSPEC_WORKER_URL",
    )
    internal_token: str | None = Field(
        default=None,
        alias="VAULTSPEC_INTERNAL_TOKEN",
        description=(
            "Bearer token for worker<->control IPC. None disables auth (dev mode)."
        ),
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

    # LangSmith tracing — bare ecosystem names only
    langsmith_tracing: bool = Field(
        default=False,
        validation_alias="LANGSMITH_TRACING",
        description=(
            "Enable LangSmith tracing. Defaults OFF"
            " to avoid unexpected quota consumption."
        ),
    )
    langsmith_api_key: str | None = Field(
        default=None,
        validation_alias="LANGSMITH_API_KEY",
    )
    langsmith_project: str | None = Field(
        default=None,
        validation_alias="LANGSMITH_PROJECT",
    )
    langsmith_endpoint: str | None = Field(
        default=None,
        validation_alias="LANGSMITH_ENDPOINT",
    )

    # Worker gateway — heartbeat & circuit-breaker (D-10, D-11)
    worker_heartbeat_timeout_seconds: float = Field(
        default=90.0,
        alias="VAULTSPEC_WORKER_HEARTBEAT_TIMEOUT_SECONDS",
        description=(
            "Seconds without a heartbeat before the worker is considered disconnected."
        ),
    )
    cb_failure_threshold: int = Field(
        default=3,
        alias="VAULTSPEC_CB_FAILURE_THRESHOLD",
        description="Consecutive dispatch failures before the circuit breaker opens.",
    )
    cb_recovery_timeout_seconds: float = Field(
        default=30.0,
        alias="VAULTSPEC_CB_RECOVERY_TIMEOUT_SECONDS",
        description="Seconds before a OPEN circuit breaker probes the worker again.",
    )

    # Worker health-poll adaptive back-off (D-12)
    worker_poll_initial_interval_seconds: float = Field(
        default=0.1,
        alias="VAULTSPEC_WORKER_POLL_INITIAL_INTERVAL_SECONDS",
        description=(
            "Initial poll interval when waiting for the worker to become ready."
        ),
    )
    worker_poll_max_interval_seconds: float = Field(
        default=2.0,
        alias="VAULTSPEC_WORKER_POLL_MAX_INTERVAL_SECONDS",
        description="Maximum back-off poll interval when waiting for the worker.",
    )
    worker_poll_backoff_factor: float = Field(
        default=1.5,
        alias="VAULTSPEC_WORKER_POLL_BACKOFF_FACTOR",
        description="Multiplicative back-off factor for worker health polling.",
    )
    worker_poll_log_interval_seconds: float = Field(
        default=5.0,
        alias="VAULTSPEC_WORKER_POLL_LOG_INTERVAL_SECONDS",
        description="Seconds between 'still waiting for worker' log messages.",
    )

    # Worker watchdog (D-13)
    watchdog_poll_interval_seconds: float = Field(
        default=5.0,
        alias="VAULTSPEC_WATCHDOG_POLL_INTERVAL_SECONDS",
        description="How often the watchdog checks worker liveness (seconds).",
    )
    watchdog_max_retries: int = Field(
        default=3,
        alias="VAULTSPEC_WATCHDOG_MAX_RETRIES",
        description="Maximum restart attempts before the watchdog gives up.",
    )
    watchdog_backoff_base_seconds: float = Field(
        default=2.0,
        alias="VAULTSPEC_WATCHDOG_BACKOFF_BASE_SECONDS",
        description=(
            "Exponential back-off base (seconds) between watchdog restart attempts."
        ),
    )

    # WebSocket (D-14)
    ws_heartbeat_interval_seconds: float = Field(
        default=30.0,
        alias="VAULTSPEC_WS_HEARTBEAT_INTERVAL_SECONDS",
        description="ADR-011 §5: WebSocket heartbeat cadence (seconds).",
    )
    ws_dead_client_timeout_seconds: float = Field(
        default=90.0,
        alias="VAULTSPEC_WS_DEAD_CLIENT_TIMEOUT_SECONDS",
        description="ADR-011 §5: disconnect WebSocket clients silent for this long.",
    )
    ws_max_message_bytes: int = Field(
        default=1_048_576,
        alias="VAULTSPEC_WS_MAX_MESSAGE_BYTES",
        description=(
            "M14: maximum WebSocket frame size (bytes) to prevent memory exhaustion."
        ),
    )

    # Internal IPC frame/body limits (D-15)
    internal_max_frame_bytes: int = Field(
        default=1_048_576,
        alias="VAULTSPEC_INTERNAL_MAX_FRAME_BYTES",
        description="Maximum worker→gateway WebSocket frame size (bytes).",
    )
    internal_max_http_body_bytes: int = Field(
        default=1_048_576,
        alias="VAULTSPEC_INTERNAL_MAX_HTTP_BODY_BYTES",
        description=(
            "Maximum HTTP body accepted on internal /dispatch and /events endpoints."
        ),
    )

    # Worker IPC bridge (D-19)
    ipc_flush_interval_seconds: float = Field(
        default=0.05,
        alias="VAULTSPEC_IPC_FLUSH_INTERVAL_SECONDS",
        description="CRIT-02: batch flush cadence for the worker→gateway event bridge.",
    )
    ipc_max_flush_retries: int = Field(
        default=3,
        alias="VAULTSPEC_IPC_MAX_FLUSH_RETRIES",
        description="IPC-03: maximum relay retry attempts per event batch.",
    )
    ipc_retry_backoff_base_seconds: float = Field(
        default=0.1,
        alias="VAULTSPEC_IPC_RETRY_BACKOFF_BASE_SECONDS",
        description=(
            "IPC-03: back-off base (seconds) between relay retries"
            " (doubles each attempt)."
        ),
    )
    ipc_max_event_buffer: int = Field(
        default=10_000,
        alias="VAULTSPEC_IPC_MAX_EVENT_BUFFER",
        description="IPC-03: drop-oldest cap on the in-memory event buffer.",
    )

    # ACP provider (D-23, D-24)
    acp_startup_timeout_seconds: float = Field(
        default=300.0,
        alias="VAULTSPEC_ACP_STARTUP_TIMEOUT_SECONDS",
        description="Seconds to wait for the ACP subprocess to become ready.",
    )
    acp_fs_read_max_bytes: int = Field(
        default=10_485_760,
        alias="VAULTSPEC_ACP_FS_READ_MAX_BYTES",
        description="Maximum file read size (bytes) surfaced through ACP tool calls.",
    )
    acp_rpc_timeout_seconds: float = Field(
        default=15.0,
        alias="VAULTSPEC_ACP_RPC_TIMEOUT_SECONDS",
        description=(
            "Seconds to wait for a quick ACP management RPC response"
            " (list_sessions, set_mode, set_model, set_config_option, authenticate)."
        ),
    )
    acp_interactive_auth_timeout_seconds: float = Field(
        default=900.0,
        alias="VAULTSPEC_ACP_INTERACTIVE_AUTH_TIMEOUT_SECONDS",
        description=(
            "Watchdog timeout (seconds) for interactive ACP browser auth flows."
            " This is a backstop for authenticate/login prompts, not the normal"
            " success path."
        ),
    )
    acp_chunk_queue_maxsize: int = Field(
        default=1024,
        alias="VAULTSPEC_ACP_CHUNK_QUEUE_MAXSIZE",
        description=(
            "Bound on the per-session chunk queue used to buffer ACP streaming"
            " output before it is consumed by the model invocation loop."
        ),
    )

    # Gemini OAuth (D-25)
    oauth_expiry_buffer_seconds: int = Field(
        default=120,
        alias="VAULTSPEC_OAUTH_EXPIRY_BUFFER_SECONDS",
        description="Seconds before OAuth token expiry to trigger a proactive refresh.",
    )

    # MCP server (D-26)
    mcp_create_timeout_seconds: float = Field(
        default=30.0,
        alias="VAULTSPEC_MCP_CREATE_TIMEOUT_SECONDS",
        description="MCP tool: timeout (seconds) for thread-create operations.",
    )
    mcp_query_timeout_seconds: float = Field(
        default=15.0,
        alias="VAULTSPEC_MCP_QUERY_TIMEOUT_SECONDS",
        description=(
            "MCP tool: timeout (seconds) for thread-query and status operations."
        ),
    )
    mcp_max_initial_message_chars: int = Field(
        default=32_000,
        alias="VAULTSPEC_MCP_MAX_INITIAL_MESSAGE_CHARS",
        description=(
            "MCP tool: maximum characters in the initial message before truncation."
        ),
    )
    mcp_preview_truncate_len: int = Field(
        default=200,
        alias="VAULTSPEC_MCP_PREVIEW_TRUNCATE_LEN",
        description="MCP tool: character limit for inline message previews.",
    )

    # Environment Flags
    ci: bool = Field(default=False, validation_alias=AliasChoices("VAULTSPEC_CI", "CI"))
    no_color: bool = Field(
        default=False,
        validation_alias=AliasChoices("VAULTSPEC_NO_COLOR", "NO_COLOR"),
    )

    @field_validator("internal_token", mode="before")
    @classmethod
    def _normalize_blank_internal_token(cls, value: object) -> object:
        """Treat blank env-var tokens as auth-disabled in dev/test stacks."""
        if isinstance(value, str) and not value.strip():
            return None
        return value


class Settings(DomainSettingsConfig, InfraConfig):
    """Backwards-compatible composed settings.

    Inherits all ~18 domain fields from ``DomainConfig`` and all ~75
    infrastructure fields from ``InfraConfig``.  The resulting object is
    a drop-in replacement for the former ``core.config.Settings``.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="VAULTSPEC_",
        extra="ignore",
    )

    @model_validator(mode="after")
    def _derive_service_urls(self) -> Self:
        """Auto-derive gateway_url and worker_url from host+port when not set."""
        if not self.gateway_url:
            host = "127.0.0.1" if self.host in ("0.0.0.0", "::") else self.host
            self.gateway_url = f"http://{host}:{self.port}"
        if not self.worker_url:
            self.worker_url = f"http://{self.worker_host}:{self.worker_port}"
        return self

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
        """Extract the plain file path from the SQLAlchemy database URL."""
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

    def validate_postgres_requirement(self) -> None:
        """Fail fast when Postgres-backed dependencies are required but absent."""
        if not self.postgres_required:
            return

        problems: list[str] = []
        if self.resolved_database_backend != "postgres":
            problems.append(
                "VAULTSPEC_POSTGRES_REQUIRED=true requires "
                "VAULTSPEC_DATABASE_BACKEND=postgres"
            )
        if self.resolved_checkpoint_backend != "postgres":
            problems.append(
                "VAULTSPEC_POSTGRES_REQUIRED=true requires "
                "VAULTSPEC_CHECKPOINT_BACKEND=postgres"
            )
        if problems:
            raise ValueError("; ".join(problems))


# Global settings instance
settings = Settings()
