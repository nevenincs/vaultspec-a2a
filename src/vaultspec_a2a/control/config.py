"""Infrastructure configuration and backwards-compatible Settings facade.

``InfraConfig`` holds every field that touches external services: ports, hosts,
database URLs, API keys, filesystem paths, pool sizes, service timeouts, etc.

``Settings`` composes ``DomainConfig`` (Layer 1 behavioural knobs) with
``InfraConfig`` via multiple inheritance, producing a single object that is
a drop-in replacement for the former ``core.config.Settings``.
"""

import json
import logging
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING, Annotated, Literal, Self

from pydantic import (
    AliasChoices,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from ..domain_config import DomainSettingsConfig
from ..utils.enums import CodexWebSearchMode, Environment, LogLevel

if TYPE_CHECKING:
    from ..desktop.credentials import DesktopCredentialPaths

# Defaults for path-override fields.  Computed once at module import relative to
# this file: control/config.py → control → vaultspec_a2a → src → project-root.
# This walk leaves the installed package, which is exactly what the storage-anchor
# gate refuses everywhere else.  It is allowed HERE and only here because this is
# the override seam itself: the value exists to be replaced by
# VAULTSPEC_PROJECT_ROOT, and a deployment that does not replace it holds no
# canonical data at this path — the database and the A2A home anchor elsewhere.
_DEFAULT_PROJECT_ROOT: Path = (
    Path(__file__).resolve().parent.parent.parent.parent  # storage-anchor-ok
)
# Machine-global A2A home for runtime state.  Kept outside the repo and
# outside .vault/ — vaultspec firmware rejects foreign directories inside the vault.
_DEFAULT_A2A_HOME: Path = Path.home() / ".vaultspec-a2a"
# The ONE dotenv file this package ever reads, resolved from __file__ rather than
# from the process working directory.  pydantic-settings resolves a bare ".env"
# against the launch directory, so any directory a process happened to start in
# could inject configuration — ports, endpoints, API keys — into a served process.
# Anchoring the lookup here keeps a checkout-local .env working for developers
# while making the launch directory irrelevant; in a non-editable install the
# path lands beside the installed package, where no such file is shipped, so a
# deployed process is configured only by its real environment.
_CHECKOUT_ENV_FILE: Path = _DEFAULT_PROJECT_ROOT / ".env"

# Canonical env-var names for the worker<->gateway pairing. Defined here (the owner
# of these settings) and imported wherever the value is written into a child
# environment, so the name lives in exactly one place (never a mirrored literal).
INTERNAL_TOKEN_ENV = "VAULTSPEC_INTERNAL_TOKEN"
GATEWAY_URL_ENV = "VAULTSPEC_GATEWAY_URL"
# The MCP-scoped alternate spelling of GATEWAY_URL_ENV (see the gateway_url Field
# below): a single named constant so the alias lives in one place rather than as a
# literal repeated at every explicit-configuration check.
GATEWAY_URL_ALT_ENV = "VAULTSPEC_MCP_API_BASE_URL"
WORKER_URL_ENV = "VAULTSPEC_WORKER_URL"

# Canonical service-endpoint defaults. This module is the ONE home for every
# production host:port literal; consumers import these rather than repeating
# the value, and each remains environment-overridable at its point of use
# (MOCK_API_BASE overrides the VidaiMock base through the mock_api_base field;
# OTEL_EXPORTER_OTLP_ENDPOINT is read by the telemetry module at import time
# per the standard OTel contract).
DEFAULT_MOCK_API_BASE = "http://localhost:8100"
DEFAULT_OTLP_ENDPOINT = "http://localhost:4317"

DEFAULT_REPAIR_JOURNAL_RETENTION_BOOTS: int = 10
"""Boots of startup-repair history retained per thread.

Startup reconciliation appends a ``repair_started``/``repair_finished`` pair per
non-terminal thread on every boot, keyed by a recovery epoch the same pass
increments, so the key never repeats and the class grows with restart count
rather than with work.

Counted in BOOTS rather than rows deliberately. This is NOT a recovery horizon
and must not be read as one: no code path reads a repair row back, so the value
that would be safe on recovery grounds is zero. What it buys is operator
hindsight - how many restarts of repair history survive for someone diagnosing a
thread that will not resume - which is a legibility judgement, not a derivation.
Rows would hide that judgement behind a boot-frequency conversion; boots state it
plainly.
"""

logger = logging.getLogger(__name__)

# The synchronous SQLAlchemy driver this project ships for each supported backend.
# Keyed on the SQLAlchemy *backend* name rather than on the full drivername, so the
# mapping resolves identically for a bare scheme (``postgresql://``), an async
# driver (``postgresql+asyncpg://``), and an already-synchronous one
# (``postgresql+psycopg://``). Only psycopg v3 and the stdlib sqlite driver are
# declared dependencies; psycopg2 - which SQLAlchemy would otherwise select for a
# bare ``postgresql://`` scheme - is not installed.
_SYNC_DRIVERNAMES: dict[str, str] = {
    "postgresql": "postgresql+psycopg",
    "sqlite": "sqlite",
}


def _synchronous_url(url: str, *, setting: str) -> str:
    """Return the synchronous SQLAlchemy URL equivalent of ``url``.

    The driver is replaced through the parsed URL structure rather than by
    substring substitution: a substring replace is a silent no-op on a URL that
    declares no driver, and it corrupts any URL whose password or query value
    happens to contain the replaced text.

    Raises ``ValueError`` when the URL cannot be parsed or names a backend with no
    synchronous driver shipped here, so a broken URL is refused at its source
    rather than reaching ``create_engine`` inside a destructive admin command.
    """
    # Imported lazily: SQLAlchemy costs roughly a quarter-second to import, and the
    # settings module sits on the CLI startup path. Every consumer of the derived
    # URL has already paid that cost.
    from sqlalchemy.engine.url import make_url
    from sqlalchemy.exc import ArgumentError

    try:
        parsed = make_url(url)
    except ArgumentError as exc:
        # The URL itself is never echoed: it routinely carries a password.
        msg = f"{setting} is not a parseable SQLAlchemy URL."
        raise ValueError(msg) from exc

    backend = parsed.get_backend_name()
    drivername = _SYNC_DRIVERNAMES.get(backend)
    if drivername is None:
        msg = (
            f"{setting} names the {backend!r} backend, which has no synchronous "
            f"driver in this project; expected one of {sorted(_SYNC_DRIVERNAMES)}."
        )
        raise ValueError(msg)

    return parsed.set(drivername=drivername).render_as_string(hide_password=False)


def _warn_seating_discard(env_name: str, supplied: object, derived: object) -> None:
    """Report that the desktop profile discarded an explicitly configured value.

    The desktop profile is the single derivation authority for mutable paths, so
    the override itself is correct and deliberate. Only its silence was a defect:
    an operator who sets both the application home and an explicit path had no
    signal that the latter never took effect.
    """
    logger.warning(
        "VAULTSPEC_DESKTOP_APP_HOME is set, so the desktop profile derives every "
        "mutable path: the explicitly configured %s=%r is discarded in favour of "
        "%r. Unset one of the two to resolve the conflict.",
        env_name,
        supplied,
        derived,
    )


def _is_absolute_path(raw: str) -> bool:
    """Return whether ``raw`` is absolute under either path convention.

    These settings name paths on the DEPLOYMENT host, which is not necessarily the
    host validating them: a Windows workstation legitimately reads a container
    configuration naming ``/app/data``, and ``pathlib`` there calls that relative.
    Accepting either convention keeps the check aimed at the hazard — a path
    resolved against whatever working directory the process inherited — rather than
    at the validating machine's operating system.
    """
    return PurePosixPath(raw).is_absolute() or PureWindowsPath(raw).is_absolute()


def _require_absolute_sqlite_path(url: str, *, setting: str) -> None:
    """Reject a SQLite URL whose file path is working-directory relative.

    Call only for a store whose RESOLVED backend is sqlite. A Postgres URL's path
    component names a database on a server rather than a file, so it has no
    absoluteness to check; ``:memory:`` names no file either. Neither can be
    relocated by a working directory, so neither carries the hazard.

    Assumes the URL already parses — the synchronous-derivation validator runs
    first and refuses anything that does not.
    """
    from sqlalchemy.engine.url import make_url

    database = make_url(url).database
    if database is None or database == ":memory:" or _is_absolute_path(database):
        return

    msg = (
        f"{setting} must be absolute. A relative URL resolves against the process "
        "working directory, so the gateway and CLI can silently open different files."
    )
    raise ValueError(msg)


class InfraConfig(BaseSettings):
    """Infrastructure fields — ports, hosts, URLs, keys, filesystem paths."""

    model_config = SettingsConfigDict(
        env_file=_CHECKOUT_ENV_FILE,
        env_file_encoding="utf-8",
        env_prefix="VAULTSPEC_",
        extra="ignore",
    )

    environment: Environment = Field(default=Environment.DEVELOPMENT)
    log_level: LogLevel = Field(default=LogLevel.INFO)
    access_log: bool = Field(
        default=False,
        alias="VAULTSPEC_ACCESS_LOG",
        description=(
            "Enable uvicorn per-request access logging at both serve sites. Off "
            "by default: the gateway is polled permanently by design (worker "
            "heartbeat, health probes), so access-line drip buries diagnostics. "
            "OTEL spans carry request tracing; opt in here for a raw access trail."
        ),
    )
    database_backend: Literal["sqlite", "postgres"] = Field(
        default="sqlite",
        alias="VAULTSPEC_DATABASE_BACKEND",
        description=(
            "Primary application database backend.  SQLite is the local/dev "
            "default.  Production deployments set 'postgres' via env."
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
            "database_backend scheme (sqlite+aiosqlite or postgresql+asyncpg).  "
            "Left unset, the bare file name above is anchored to a2a_home, so "
            "the store is ~/.vaultspec-a2a/vaultspec.db rather than a "
            "launch-relative file."
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
    workspace_root: Path | None = Field(
        default=None,
        description=(
            "Optional label for the workspace this process serves. It sites NO "
            "agent: agent working directories come from the per-run "
            "metadata.workspace_root the caller supplies, and the only readers of "
            "this field pass it as the 'workspace' label on a dev process-registry "
            "record. Unset by default, because the former './workspaces' default "
            "advertised a managed store that is never created and never used; the "
            "armed desktop profile seats its own derived workspace tree here."
        ),
    )
    project_root: Path = Field(
        default_factory=lambda: _DEFAULT_PROJECT_ROOT,
        alias="VAULTSPEC_PROJECT_ROOT",
        description=(
            "Absolute path to the repository root.  Computed from __file__ by "
            "default; override in Docker non-editable installs where __file__ "
            "resolves inside site-packages."
        ),
    )
    a2a_home: Path = Field(
        default_factory=lambda: _DEFAULT_A2A_HOME,
        alias="VAULTSPEC_A2A_HOME",
        description=(
            "Machine-global A2A home for runtime state (process logs, graph "
            "cache, queues, tmp) and the service discovery file.  Defaults to "
            "~/.vaultspec-a2a.  Relocated out of .vault/ because "
            "vaultspec firmware rejects foreign directories inside the vault."
        ),
    )
    capsule_assets_root: Path | None = Field(
        default=None,
        alias="VAULTSPEC_CAPSULE_ASSETS",
        description=(
            "Root of the desktop capsule's owned runtime assets (Node.js and the "
            "ACP adapter). When set, the provider factory resolves the default "
            "Node executable and ACP entry point ONLY from this root, with no "
            "checkout or PATH fallback. Unset for the Compose/dev profiles, where "
            "resolution is checkout-relative as before."
        ),
    )
    desktop_app_home: Path | None = Field(
        default=None,
        alias="VAULTSPEC_DESKTOP_APP_HOME",
        description=(
            "Explicit mutable-state root for the desktop product profile. When "
            "set, the profile is armed: the database, checkpoint, workspace, and "
            "A2A-home paths derive ONLY from this application home (via the "
            "desktop profile authority), never from the launch directory. Must be "
            "an absolute path. Unset for the Compose/dev profiles, whose path "
            "resolution is unchanged."
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
    # ANTHROPIC_API_KEY is deliberately absent. The Claude lane authenticates with
    # claude_code_oauth_token, and every agent subprocess has ANTHROPIC_API_KEY
    # stripped from its environment by the workspace scrub
    # (workspace/environment.py), because the key alongside an OAuth token
    # silently downgrades a flat-rate subscription to pay-as-you-go billing.
    # The scrub is the single removal site: the ACP layer re-injects only the
    # auth a lane intentionally supports and strips nothing itself. Declaring
    # the key here would advertise a credential the code exists to remove.
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
    gemini_cli_home: str | None = Field(
        default=None,
        validation_alias="GEMINI_CLI_HOME",
    )
    # Antigravity ships `agy` OUTSIDE PATH - its installer drops the binary in
    # a per-user application directory and exposes it through a wrapper - so a
    # bare name lookup finds nothing on a machine where the CLI works. This
    # override names the executable directly; when it is unset the lane falls
    # back to a PATH lookup and then to the installer's default location.
    antigravity_cli_path: str | None = Field(
        default=None,
        validation_alias="ANTIGRAVITY_CLI_PATH",
    )
    # The CLI keeps its login beside its own state, not under the Antigravity
    # application directory; the default mirrors where the installer writes it.
    antigravity_cli_home: str | None = Field(
        default=None,
        validation_alias="ANTIGRAVITY_CLI_HOME",
    )
    openai_api_key: str | None = Field(
        default=None,
        validation_alias="OPENAI_API_KEY",
    )
    openai_base_url: str = Field(
        default="https://api.openai.com/v1",
        validation_alias="OPENAI_BASE_URL",
        description="Base URL for the OpenAI API execution and catalog lane.",
    )
    zhipu_api_key: str | None = Field(
        default=None,
        validation_alias="ZHIPU_API_KEY",
    )
    claude_code_oauth_token: str | None = Field(
        default=None,
        validation_alias="CLAUDE_CODE_OAUTH_TOKEN",
    )
    # Z.ai routes through the Claude ACP path against an Anthropic-Messages-
    # compatible endpoint. The base URL defaults to
    # Z.ai's documented Anthropic gateway; only the auth token must be supplied.
    zai_base_url: str = Field(
        default="https://api.z.ai/api/anthropic",
        validation_alias=AliasChoices("ZAI_BASE_URL", "ZAI_ANTHROPIC_BASE_URL"),
        description="Base URL for the Z.ai Anthropic-compatible endpoint.",
    )
    zai_auth_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ZAI_AUTH_TOKEN", "ZAI_API_KEY"),
    )
    # Codex `app-server` authenticates from a persisted local session in its Codex
    # home (~/.codex by default). This non-secret override points the subprocess at
    # an alternate home for headless/container use; no API key is involved (the
    # ChatGPT-session auth mode is file-based). Mirrors gemini_cli_home.
    codex_home: str | None = Field(
        default=None,
        validation_alias="CODEX_HOME",
    )
    # The Codex lane's web-grounding posture. Unset means a lane carrying web
    # proof serves live retrieval, which is what keeps a multi-provider graph's
    # findings differing by evidence rather than by which lane happened to run.
    # A deployment that prefers zero egress sets "cached" - genuine search
    # against a provider-maintained index with no outbound request from the agent
    # host. This preference applies only ABOVE the lane-admission gate: it can
    # narrow a proven lane's reach, never grant reach to an unproven one.
    codex_web_search_mode: CodexWebSearchMode | None = Field(
        default=None,
        validation_alias="VAULTSPEC_CODEX_WEB_SEARCH_MODE",
        description=(
            "Override the Codex lane's web-search mode (disabled, cached, "
            "indexed, live). Unset serves live on a web-proven lane."
        ),
    )
    # Redirects the Codex lane's API traffic at a named endpoint. Codex resolves
    # its endpoint from its config home rather than an environment variable, so
    # without this the lane cannot be pointed anywhere - and a lane that only ever
    # succeeds cannot demonstrate what it does when a provider refuses. Unset in
    # every served deployment; set it only to drive a provider-refusal proof.
    codex_base_url_override: str | None = Field(
        default=None,
        validation_alias="VAULTSPEC_CODEX_BASE_URL",
        description=(
            "Point the Codex lane at an alternate API endpoint. Unset serves the "
            "provider's own endpoint."
        ),
    )
    # Kimi Code reads persisted aliases from KIMI_CODE_HOME (default ~/.kimi-code).
    # KIMI_MODEL_* defines a temporary provider and is valid only as a complete
    # name/key/base tuple. Current names precede retained legacy key/base aliases.
    # Runtime alias selection is not a setting; the factory uses `-m`.
    kimi_code_home: str | None = Field(
        default=None,
        validation_alias="KIMI_CODE_HOME",
    )
    kimi_model_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="KIMI_MODEL_API_KEY",
        exclude=True,
        repr=False,
    )
    kimi_legacy_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="KIMI_API_KEY",
        exclude=True,
        repr=False,
    )
    kimi_model_base_url: str | None = Field(
        default=None,
        validation_alias="KIMI_MODEL_BASE_URL",
        description="Base URL in a complete temporary Kimi model definition.",
    )
    kimi_legacy_base_url: str | None = Field(
        default=None,
        validation_alias="KIMI_BASE_URL",
        exclude=True,
        repr=False,
    )
    kimi_temporary_model_name: str | None = Field(
        default=None,
        validation_alias="KIMI_MODEL_NAME",
        description="Alias in a complete temporary Kimi model definition.",
    )
    kimi_temporary_model_max_context_size: int | None = Field(
        default=None,
        gt=0,
        le=2_147_483_647,
        validation_alias="KIMI_MODEL_MAX_CONTEXT_SIZE",
        description="Provider-owned context-size value for a temporary Kimi model.",
    )
    kimi_temporary_model_capabilities: str | None = Field(
        default=None,
        max_length=512,
        validation_alias="KIMI_MODEL_CAPABILITIES",
        description="Provider-owned capability value for a temporary Kimi model.",
    )

    @property
    def kimi_api_key(self) -> SecretStr | None:
        """Return the nonblank current key, then the nonblank migration key."""
        for candidate in (self.kimi_model_api_key, self.kimi_legacy_api_key):
            if candidate is not None and candidate.get_secret_value().strip():
                return candidate
        return None

    @property
    def kimi_base_url(self) -> str | None:
        """Return the normalized current base URL, then its migration fallback."""
        for candidate in (self.kimi_model_base_url, self.kimi_legacy_base_url):
            if candidate is not None and candidate.strip():
                return candidate.strip()
        return None

    host: str = Field(
        default="127.0.0.1",
        description="Bind host for the uvicorn server (VAULTSPEC_HOST).",
    )
    port: int = Field(
        default=18000,
        description="Bind port for the uvicorn server (VAULTSPEC_PORT).",
    )

    gateway_url: str = Field(
        default="",
        validation_alias=AliasChoices(
            GATEWAY_URL_ENV,
            GATEWAY_URL_ALT_ENV,
        ),
        description=(
            "Base URL for reaching the gateway HTTP API. Used by the worker "
            "IPC bridge and the MCP tool server. Auto-derived from host+port "
            "when not set explicitly. VAULTSPEC_MCP_API_BASE_URL is an alternate "
            "spelling of the same single field rather than an MCP-scoped "
            "override: it also moves the spawned worker's heartbeat and pairing "
            "target, so a proxy set through either name redirects both."
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
    # NoDecode: without it pydantic-settings JSON-decodes the env value before
    # any validator runs, so the comma form below could never be normalized.
    mcp_allowed_hosts: Annotated[list[str], NoDecode] = Field(
        default=["localhost:*", "127.0.0.1:*"],
        alias="VAULTSPEC_MCP_ALLOWED_HOSTS",
        description=(
            "Host header values the MCP streamable-http transport accepts. "
            "Defaults to loopback only; a deployment that fronts MCP under a "
            "real hostname must name it here. Empty disables the Host check."
        ),
    )
    mcp_allowed_origins: Annotated[list[str], NoDecode] = Field(
        default=["http://localhost:*", "http://127.0.0.1:*"],
        alias="VAULTSPEC_MCP_ALLOWED_ORIGINS",
        description=(
            "Origin header values the MCP streamable-http transport accepts. "
            "Guards against DNS-rebinding from a browser context. A request "
            "with no Origin header (the normal non-browser MCP client) passes."
        ),
    )

    # Worker process settings
    worker_port: int = Field(
        default=18001,
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
        alias=WORKER_URL_ENV,
    )
    internal_token: str | None = Field(
        default=None,
        alias=INTERNAL_TOKEN_ENV,
        description=(
            "Bearer token for worker<->control IPC. It is never accepted by the "
            "engine-facing /v1 gateway."
        ),
    )
    gateway_service_token: str | None = Field(
        default=None,
        alias="VAULTSPEC_A2A_GATEWAY_TOKEN",
        description=(
            "Optional dedicated bearer for the engine-facing /v1 gateway. "
            "When absent, the gateway generates a per-process credential; it "
            "is never shared with worker IPC or embedded in discovery."
        ),
    )
    auto_spawn_worker: bool = Field(
        default=True,
        description=("Auto-spawn worker as child process on gateway startup."),
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
    repair_journal_retention_boots: int = Field(
        default=DEFAULT_REPAIR_JOURNAL_RETENTION_BOOTS,
        ge=0,
        description=(
            "Boots of startup-repair history kept per thread. Reconciliation "
            "appends a started/finished pair per non-terminal thread on every "
            "boot under a key that never repeats, so the class grows with "
            "restart count rather than with work. No code path reads a repair "
            "row, so this bounds operator hindsight only - never a recovery, "
            "replay, or redrive window. Zero retains every row."
        ),
        alias="VAULTSPEC_REPAIR_JOURNAL_RETENTION_BOOTS",
    )

    # Authoring verdict subscriber
    authoring_subscriber_enabled: bool = Field(
        default=False,
        alias="VAULTSPEC_AUTHORING_SUBSCRIBER_ENABLED",
        description=(
            "Run the engine authoring-verdict subscriber as a gateway background "
            "task. Consumes GET /authoring/v1/events and resumes parked runs with "
            "reviewer verdicts. Off by default; enable when a live engine is "
            "available to review agent-authored proposals."
        ),
    )
    authoring_subscriber_poll_interval_seconds: float = Field(
        default=3.0,
        alias="VAULTSPEC_AUTHORING_SUBSCRIBER_POLL_INTERVAL_SECONDS",
        description=(
            "Seconds to wait after an empty lifecycle page before re-opening the "
            "engine SSE stream (steady-state poll cadence)."
        ),
    )
    authoring_subscriber_reconnect_base_seconds: float = Field(
        default=2.0,
        alias="VAULTSPEC_AUTHORING_SUBSCRIBER_RECONNECT_BASE_SECONDS",
        description=(
            "Initial exponential back-off (seconds) when the engine is absent or "
            "the lifecycle stream fails."
        ),
    )
    authoring_subscriber_reconnect_max_seconds: float = Field(
        default=30.0,
        alias="VAULTSPEC_AUTHORING_SUBSCRIBER_RECONNECT_MAX_SECONDS",
        description="Maximum back-off (seconds) between subscriber reconnect attempts.",
    )

    # ACP backend selection
    acp_backend: Literal["node", "binary"] = Field(
        default="node",
        description=(
            "ACP gateway backend: 'node' uses the npm-installed index.js, "
            "'binary' uses the precompiled Bun executable in src/vaultspec_a2a/bin/. "
            "node is the default; binary mode is experimental."
        ),
        alias="VAULTSPEC_ACP_BACKEND",
    )

    # LangSmith tracing is deliberately NOT a setting. Its only consumer is the
    # langsmith SDK, which resolves LANGSMITH_*/LANGCHAIN_* out of os.environ
    # itself (langsmith.utils.get_env_var). Settings loads .env into this object,
    # never into os.environ, so a field here could not switch tracing on or off —
    # it would only mint a second, non-authoritative answer that disagrees with the
    # SDK. The process environment is the single home; telemetry/instrumentation.py
    # mirrors it for reporting.

    # Worker gateway — heartbeat & circuit-breaker
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

    # Worker health-poll adaptive back-off
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
    worker_ready_timeout_seconds: float = Field(
        default=30.0,
        alias="VAULTSPEC_WORKER_READY_TIMEOUT_SECONDS",
        description=(
            "Seconds a spawned worker may take to become ready before the spawn"
            " is abandoned and its process tree reaped. Slow cold starts (first"
            " import on a cold filesystem, a contended host) need headroom here."
        ),
    )

    # Worker watchdog
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
    watchdog_restart_cooldown_seconds: float = Field(
        default=30.0,
        alias="VAULTSPEC_WATCHDOG_RESTART_COOLDOWN_SECONDS",
        description=(
            "Minimum seconds between watchdog restart CYCLES (not attempts within a "
            "cycle). Rate-limits a persistent crash signal so the watchdog cannot "
            "spin restart cycles when the underlying condition has not cleared."
        ),
    )

    # Progress stream
    stream_heartbeat_interval_seconds: float = Field(
        default=30.0,
        alias="VAULTSPEC_STREAM_HEARTBEAT_INTERVAL_SECONDS",
        description=(
            "Idle cadence at which the progress stream emits a keepalive frame "
            "(seconds). Bounds how long a quiet run can look indistinguishable "
            "from a dead connection to a reader."
        ),
    )

    # Internal IPC frame/body limits
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

    # Worker IPC bridge
    ipc_flush_interval_seconds: float = Field(
        default=0.05,
        alias="VAULTSPEC_IPC_FLUSH_INTERVAL_SECONDS",
        description="Batch flush cadence for the worker→gateway event bridge.",
    )
    ipc_max_flush_retries: int = Field(
        default=3,
        alias="VAULTSPEC_IPC_MAX_FLUSH_RETRIES",
        description="Maximum relay retry attempts per event batch.",
    )
    ipc_retry_backoff_base_seconds: float = Field(
        default=0.1,
        alias="VAULTSPEC_IPC_RETRY_BACKOFF_BASE_SECONDS",
        description=(
            "Back-off base (seconds) between relay retries (doubles each attempt)."
        ),
    )
    ipc_max_event_buffer: int = Field(
        default=10_000,
        alias="VAULTSPEC_IPC_MAX_EVENT_BUFFER",
        description="Drop-oldest cap on the in-memory event buffer.",
    )

    # ACP provider
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
            " (list_sessions, set_mode, authenticate)."
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
    acp_turn_idle_timeout_seconds: float = Field(
        default=600.0,
        alias="VAULTSPEC_ACP_TURN_IDLE_TIMEOUT_SECONDS",
        description=(
            "Backstop (seconds) on a single ACP turn with no protocol activity."
            " The clock resets on every frame the agent writes, so a working"
            " agent never trips it; it bounds a turn whose subprocess is alive"
            " but has gone silent and would otherwise be awaited forever."
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

    # Gemini OAuth
    oauth_expiry_buffer_seconds: int = Field(
        default=120,
        alias="VAULTSPEC_OAUTH_EXPIRY_BUFFER_SECONDS",
        description="Seconds before OAuth token expiry to trigger a proactive refresh.",
    )

    # MCP server
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

    @field_validator("internal_token", "gateway_service_token", mode="before")
    @classmethod
    def _normalize_blank_internal_token(cls, value: object) -> object:
        """Treat blank configured tokens as absent."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("kimi_temporary_model_max_context_size", mode="before")
    @classmethod
    def _blank_kimi_context_size_is_absent(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("kimi_temporary_model_capabilities", mode="before")
    @classmethod
    def _normalise_kimi_capabilities(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        if not value.strip():
            return None
        tokens = tuple(part.strip() for part in value.split(","))
        if any(not token for token in tokens):
            raise ValueError("Kimi model capabilities must not contain blank tokens")
        if len(tokens) > 16:
            raise ValueError("Kimi model capabilities must contain at most 16 tokens")
        ordered_unique = tuple(dict.fromkeys(tokens))
        for token in ordered_unique:
            if (
                len(token) > 64
                or not token[0].isascii()
                or not token[0].isalnum()
                or any(
                    not character.isascii()
                    or not (character.isalnum() or character in "_.:-")
                    for character in token
                )
            ):
                raise ValueError("Kimi model capability contains an invalid token")
        return ",".join(ordered_unique)

    @field_validator("mcp_allowed_hosts", "mcp_allowed_origins", mode="before")
    @classmethod
    def _split_comma_separated_list(cls, value: object) -> object:
        """Accept a comma-separated or JSON-array env value for these settings.

        These fields carry ``NoDecode``, so the raw environment string arrives
        here undecoded. Plain ``a,b`` is the documented form - pydantic-settings
        would otherwise JSON-parse it and fail startup on the obvious spelling.
        A JSON array is still honoured, because silently reading ``["a","b"]``
        as two malformed comma items would be worse than either supporting it
        or rejecting it.
        """
        if not isinstance(value, str):
            return value
        text = value.strip()
        if text.startswith("["):
            return json.loads(text)
        return [item.strip() for item in text.split(",") if item.strip()]


class Settings(DomainSettingsConfig, InfraConfig):
    """Backwards-compatible composed settings.

    Inherits all ~18 domain fields from ``DomainConfig`` and all ~75
    infrastructure fields from ``InfraConfig``.  The resulting object is
    a drop-in replacement for the former ``core.config.Settings``.
    """

    model_config = SettingsConfigDict(
        env_file=_CHECKOUT_ENV_FILE,
        env_file_encoding="utf-8",
        env_prefix="VAULTSPEC_",
        extra="ignore",
    )

    @model_validator(mode="after")
    def _separate_gateway_and_worker_credentials(self) -> Self:
        """Reject configurations that collapse gateway and worker authority."""
        if (
            self.gateway_service_token is not None
            and self.internal_token is not None
            and self.gateway_service_token == self.internal_token
        ):
            msg = (
                "VAULTSPEC_A2A_GATEWAY_TOKEN must differ from VAULTSPEC_INTERNAL_TOKEN"
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _derive_service_urls(self) -> Self:
        """Auto-derive gateway_url and worker_url from host+port when not set."""
        if not self.gateway_url:
            host = "127.0.0.1" if self.host in ("0.0.0.0", "::") else self.host
            self.gateway_url = f"http://{host}:{self.port}"
        if not self.worker_url:
            self.worker_url = f"http://{self.worker_host}:{self.worker_port}"
        return self

    @model_validator(mode="after")
    def _seat_desktop_profile(self) -> Self:
        """Seat every mutable path under the explicit desktop application home.

        The desktop profile is armed only when ``desktop_app_home`` is set. While
        unarmed (the Compose and development profiles), this is a no-op and the
        configuration is byte-for-byte unchanged — including the import surface,
        since the desktop path authority is imported only on the armed branch.

        When armed, the database, checkpoint, workspace, and A2A-home paths derive
        from the application home through the desktop profile's single derivation
        authority, so no mutable path resolves relative to the launch directory.
        That derivation outranks an explicitly configured value by design; when it
        actually displaces one, it says so. ``model_fields_set`` distinguishes a
        genuinely supplied value from an untouched default, so an unconfigured boot
        stays silent rather than emitting noise every operator learns to ignore.
        """
        if self.desktop_app_home is None:
            return self

        # Imported lazily and only when armed: unarmed construction never pulls
        # the desktop package, preserving the Compose/dev import surface.
        from ..desktop.profile import derive_state_paths

        state = derive_state_paths(self.desktop_app_home)
        derived_database_url = f"sqlite+aiosqlite:///{state.database_path.as_posix()}"
        derived_checkpoint_url = (
            f"sqlite+aiosqlite:///{state.checkpoint_path.as_posix()}"
        )

        # Read before any assignment below: assigning a field marks it as set.
        explicit = self.model_fields_set
        if "a2a_home" in explicit:
            _warn_seating_discard("VAULTSPEC_A2A_HOME", self.a2a_home, state.app_home)
        if "workspace_root" in explicit:
            _warn_seating_discard(
                "VAULTSPEC_WORKSPACE_ROOT", self.workspace_root, state.workspaces_root
            )
        if "database_url" in explicit:
            _warn_seating_discard(
                "VAULTSPEC_DATABASE_URL", self.database_url, derived_database_url
            )
        if "checkpoint_database_url" in explicit:
            _warn_seating_discard(
                "VAULTSPEC_CHECKPOINT_DATABASE_URL",
                self.checkpoint_database_url,
                derived_checkpoint_url,
            )

        self.a2a_home = state.app_home
        self.workspace_root = state.workspaces_root
        self.database_url = derived_database_url
        self.checkpoint_database_url = derived_checkpoint_url
        return self

    @model_validator(mode="after")
    def _validate_synchronous_url_derivation(self) -> Self:
        """Refuse a configured URL that has no synchronous SQLAlchemy equivalent.

        The admin and command-line paths - schema creation and the destructive
        ``db clear`` - run on synchronous engines built from these URLs. Leaving the
        check to those call sites means a shipped-configuration typo first surfaces
        part-way through a destructive command; here it surfaces at boot.

        Declared after the desktop seating so it validates the URLs the process will
        actually use, not the ones the seating is about to replace. The anchoring
        that follows only ever swaps a relative SQLite path for an absolute one, so
        it cannot change the backend or driver this validator just accepted.
        """
        _synchronous_url(self.database_url, setting="VAULTSPEC_DATABASE_URL")
        if self.checkpoint_database_url is not None:
            _synchronous_url(
                self.checkpoint_database_url,
                setting="VAULTSPEC_CHECKPOINT_DATABASE_URL",
            )
        return self

    @model_validator(mode="after")
    def _anchor_and_require_absolute_paths(self) -> Self:
        """Anchor unset mutable paths, then refuse any that stayed relative.

        A working-directory-relative store is a silent split-brain: the gateway and
        the CLI resolve the same configured value against different directories and
        open different files, each convinced it holds the whole picture. The ruling
        is to fail loud rather than resolve quietly, so an explicitly supplied
        relative value is rejected and never rewritten.

        The shipped database DEFAULT was itself relative, and
        ``settings = Settings()`` runs at module import — rejecting it would make
        the package unimportable on a fresh checkout. So a default the operator
        never touched is anchored instead, which keeps the store in one place
        without the working-directory dependence. ``model_fields_set`` separates
        the two cases.

        The anchor is ``a2a_home``, NOT ``project_root``. Two reasons, and the
        second is the decisive one:

        * ``project_root`` defaults to a ``__file__``-derived constant. In a
          non-editable install that constant resolves into the Python library
          directory, so anchoring there writes the default store to
          ``.../lib/vaultspec.db`` — inside the interpreter's own tree, where an
          upgrade or a reinstall discards it.
        * The schema is already built for ONE machine-global store. Runs are
          partitioned by ``threads.workspace_key``, hashed from the per-run
          ``metadata.workspace_root`` the caller supplies, and the ``0008``/``0009``
          migrations backfill and index on exactly that column. A per-checkout
          database fragments that partitioned store across as many files as there
          happen to be checkouts. ``a2a_home`` is where the machine-global runtime
          state already lives — process logs, the discovery ``service.json`` — so
          the database joins its own kind rather than founding a third convention.

        ORDERING: declared after ``_seat_desktop_profile``, which replaces every
        mutable path with an absolute derived from the application home. Run before
        it — or as a field validator, which fires earlier still — and every armed
        desktop boot would be rejected on the relative default it was about to
        discard. ``cli.service`` injects absolute URLs into the child environment for
        the same reason, and those arrive as explicitly-set values that pass here
        untouched.
        """
        # ``as_posix`` before the check, never ``str``: a container path arriving on
        # a Windows host is a ``WindowsPath`` whose ``str`` uses backslashes, which
        # neither pure flavour then reads as absolute.
        if not _is_absolute_path(self.a2a_home.as_posix()):
            msg = (
                "VAULTSPEC_A2A_HOME must be absolute: it anchors the default "
                "database location and every runtime-state directory."
            )
            raise ValueError(msg)
        if not _is_absolute_path(self.project_root.as_posix()):
            msg = (
                "VAULTSPEC_PROJECT_ROOT must be absolute: checkout-relative "
                "assets are resolved against it."
            )
            raise ValueError(msg)

        explicit = self.model_fields_set
        if "database_url" not in explicit:
            anchored = (self.a2a_home / "vaultspec.db").as_posix()
            self.database_url = f"sqlite+aiosqlite:///{anchored}"

        # Resolving the backends here is load-bearing twice over. It raises when a
        # declared backend and its URL disagree — the synchronous admin engines
        # built from these values have no other validation seam — and it decides
        # which stores carry a filesystem path at all, since only a SQLite store
        # can be relocated by a working directory. Reading it here rather than in
        # the sync-URL properties keeps that enforcement at boot and out of a
        # discarded binding a later cleanup would take for dead code.
        if self.resolved_database_backend == "sqlite":
            _require_absolute_sqlite_path(
                self.database_url, setting="VAULTSPEC_DATABASE_URL"
            )
        if (
            self.checkpoint_database_url is not None
            and self.resolved_checkpoint_backend == "sqlite"
        ):
            _require_absolute_sqlite_path(
                self.checkpoint_database_url,
                setting="VAULTSPEC_CHECKPOINT_DATABASE_URL",
            )
        # Nothing to anchor: the field carries no default to repair, so a value
        # here is always one an operator or the desktop seating actually supplied.
        if self.workspace_root is not None and not _is_absolute_path(
            self.workspace_root.as_posix()
        ):
            msg = (
                "VAULTSPEC_WORKSPACE_ROOT must be absolute. A relative path "
                "resolves against the process working directory, so the gateway "
                "and CLI can silently open different directories."
            )
            raise ValueError(msg)
        return self

    @property
    def environment_declared(self) -> bool:
        """Whether the operator DECLARED an environment rather than inheriting one.

        The environment setting has a default, so its value alone cannot say
        whether anyone chose it. Security decisions that key on the development
        environment need that difference: reading a defaulted value as consent
        turns "nobody configured this" into "authentication is off".
        """
        return "environment" in self.model_fields_set

    @property
    def is_dev(self) -> bool:
        """Check if running in development environment."""
        return self.environment == Environment.DEVELOPMENT

    @property
    def desktop_profile_armed(self) -> bool:
        """Return whether the desktop product profile is armed.

        This is the single authority for desktop-profile detection. The profile
        is armed exactly when an explicit application home is configured; every
        seam that must behave differently under the desktop profile (non-mutating
        schema validation, checkpointer setup suppression) branches on this one
        predicate rather than re-deriving arming from raw configuration.
        """
        return self.desktop_app_home is not None

    @property
    def desktop_credential_paths(self) -> "DesktopCredentialPaths | None":
        """Return the three desktop credential file references, or ``None``.

        The desktop profile authenticates three disjoint trust planes, each backed
        by its own owner-restricted file beneath the application home's credentials
        directory: the dashboard-created attach-control credential, the
        receipt-bound ownership (lifecycle) capability, and the gateway-owned worker
        interprocess-communication secret. This is the single settings-side
        authority for those references; it derives them through the desktop profile
        path authority rather than restating the layout.

        Returns ``None`` while the profile is unarmed (the Compose and development
        profiles), so no credential path resolves relative to a launch directory and
        the unarmed import surface never pulls the desktop package.
        """
        if self.desktop_app_home is None:
            return None

        # Imported lazily and only when armed, mirroring the path-seating validator:
        # unarmed construction never pulls the desktop credential package.
        from ..desktop.credentials import credential_paths
        from ..desktop.profile import derive_state_paths

        state = derive_state_paths(self.desktop_app_home)
        return credential_paths(state.credentials_dir)

    @property
    def desktop_temp_homes_dir(self) -> Path | None:
        """Return the armed desktop profile's root for per-run temporary homes.

        A packaged desktop install keeps its ephemeral working directories inside
        its own application home rather than scattering them through the operating
        system temporary directory, so an uninstall can account for them and a
        system-wide temp sweep cannot delete a home out from under a live run.

        Returns ``None`` while the profile is unarmed, leaving the development and
        Compose profiles on the operating system temporary directory.
        """
        if self.desktop_app_home is None:
            return None

        from ..desktop.profile import derive_state_paths

        return derive_state_paths(self.desktop_app_home).temp_homes_dir

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
        """Return a synchronous SQLAlchemy URL for admin/CLI operations.

        URL/backend agreement is enforced at construction rather than here, so this
        reads as the pure derivation it is.
        """
        return _synchronous_url(self.database_url, setting="VAULTSPEC_DATABASE_URL")

    @property
    def checkpoint_sync_url(self) -> str:
        """Return a synchronous SQLAlchemy URL for the checkpoint store.

        Falls back to the application database when no dedicated checkpoint URL
        is configured, matching the runtime savers: the two stores share one file
        by default and split only when explicitly configured.
        """
        if self.checkpoint_database_url is None:
            return _synchronous_url(self.database_url, setting="VAULTSPEC_DATABASE_URL")
        return _synchronous_url(
            self.checkpoint_database_url,
            setting="VAULTSPEC_CHECKPOINT_DATABASE_URL",
        )

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
