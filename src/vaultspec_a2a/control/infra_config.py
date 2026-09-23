"""Infrastructure settings fields and shared configuration path helpers."""

import json
import logging
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import NoDecode, SettingsConfigDict

from ..utils.enums import CodexWebSearchMode, Environment, LogLevel
from .env_prefix import ENV_PREFIX
from .settings_base import (
    ProjectSettings,
    env_name,
    resolve_project_root,
)
from .state_layout import DEFAULT_HOME

__all__ = [
    "DEFAULT_MOCK_API_BASE",
    "DEFAULT_OTLP_ENDPOINT",
    "GATEWAY_URL_ENV",
    "INTERNAL_TOKEN_ENV",
    "WORKER_URL_ENV",
    "InfraConfig",
    "_synchronous_url",
    "_warn_seating_discard",
]

# The checkout (or install) root holding this service's shipped non-Python
# assets, such as the ACP adapter's node_modules. Derived from this file:
# control/infra_config.py -> control -> vaultspec_a2a -> src -> checkout root.
# This walk leaves the installed package, which is why it is allowed HERE and
# only here: it is the override seam itself, and it names assets, never state.
_INSTALL_ROOT: Path = (
    Path(__file__).resolve().parent.parent.parent.parent  # storage-anchor-ok
)
# Canonical service-endpoint defaults. This module is the ONE home for every
# production host:port literal; consumers import these rather than repeating
# the value, and each remains environment-overridable at its point of use
# (VAULTSPEC_A2A_MOCK_API_BASE overrides the VidaiMock base;
# OTEL_EXPORTER_OTLP_ENDPOINT is read by the telemetry module at import time
# per the standard OTel contract).
DEFAULT_MOCK_API_BASE = "http://localhost:8100"
DEFAULT_OTLP_ENDPOINT = "http://localhost:4317"

logger = logging.getLogger("vaultspec_a2a.control.config")

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
        "VAULTSPEC_A2A_DESKTOP_APP_HOME is set, so the desktop profile derives every "
        "mutable path: the explicitly configured %s=%r is discarded in favour of "
        "%r. Unset one of the two to resolve the conflict.",
        env_name,
        _loggable(supplied),
        _loggable(derived),
    )


def _loggable(value: object) -> object:
    """Return ``value`` safe to log: a URL's password is masked, never echoed.

    A database URL routinely carries a password, and a server DSN displaced by
    the desktop seating is exactly the value this warning reports.
    """
    text = str(value)
    if "://" not in text:
        return value
    from sqlalchemy.engine.url import make_url
    from sqlalchemy.exc import ArgumentError

    try:
        return make_url(text).render_as_string(hide_password=True)
    except ArgumentError:
        # Unparseable: report that a value was discarded without the value.
        return "<unparseable URL>"


def _valid_kimi_capability(token: str) -> bool:
    return (
        len(token) <= 64
        and token[0].isascii()
        and token[0].isalnum()
        and all(
            character.isascii() and (character.isalnum() or character in "_.:-")
            for character in token
        )
    )


class InfraConfig(ProjectSettings):
    """Infrastructure fields — ports, hosts, URLs, keys, filesystem paths."""

    model_config = SettingsConfigDict(
        env_file=ProjectSettings.project_dotenv(),
        env_file_encoding="utf-8",
        env_prefix=ENV_PREFIX,
        extra="ignore",
        env_ignore_empty=True,
    )

    environment: Environment = Field(default=Environment.DEVELOPMENT)
    log_level: LogLevel = Field(default=LogLevel.INFO)
    access_log: bool = Field(
        default=False,
        description=(
            "Enable uvicorn per-request access logging at both serve sites. Off "
            "by default: the gateway is polled permanently by design (worker "
            "heartbeat, health probes), so access-line drip buries diagnostics. "
            "OTEL spans carry request tracing; opt in here for a raw access trail."
        ),
    )
    database_backend: Literal["sqlite", "postgres"] = Field(
        default="sqlite",
        description=(
            "Primary application database backend.  SQLite is the local/dev "
            "default.  Production deployments set 'postgres' via env."
        ),
    )
    checkpoint_backend: Literal["sqlite", "postgres"] = Field(
        default="sqlite",
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
            "Left unset, the store is state/vaultspec.db in the state home. A "
            "relative SQLite path resolves against the project root."
        ),
    )
    checkpoint_database_url: str | None = Field(
        default=None,
        description="Optional dedicated checkpoint database URL/DSN.",
    )
    sqlite_busy_timeout_ms: int = Field(
        default=5000,
        description="Busy timeout applied to SQLite connections.",
    )
    postgres_required: bool = Field(
        default=False,
        description=(
            "Fail startup loudly when Postgres-backed dependencies are required."
        ),
    )
    db_pool_size: int = Field(
        default=5,
        description="SQLAlchemy QueuePool pool_size for Postgres engine.",
    )
    db_pool_max_overflow: int = Field(
        default=10,
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
    provider_identity_launcher: Path | None = Field(
        default=None,
        description=(
            "Compose/Linux launcher that drops every provider and tool child to "
            "the configured agent identity. Unset outside the isolated worker."
        ),
    )
    provider_agent_uid: int | None = Field(
        default=None,
        ge=1,
        description="Unprivileged UID selected by provider_identity_launcher.",
    )
    provider_agent_gid: int | None = Field(
        default=None,
        ge=1,
        description="Unprivileged GID selected by provider_identity_launcher.",
    )
    managed_workspace_permissions: bool = Field(
        default=False,
        description=(
            "Compose only: let the container entrypoint take ownership of a "
            "managed workspace volume and share it with the agent identity. "
            "Leave false for an operator-prepared mount, which the entrypoint "
            "then only validates."
        ),
    )
    project_root: Path = Field(
        default_factory=resolve_project_root,
        description=(
            "The project a2a serves and keeps its state under. Unset, it is the "
            "nearest ancestor of the working directory holding .vaultspec/ or "
            ".vault/, then one holding .git, else the working directory. A "
            "relative value resolves against the working directory. Read from "
            "the process environment only: the project's .env is found through "
            "this value, so it cannot also choose it."
        ),
    )
    install_root: Path = Field(
        default_factory=lambda: _INSTALL_ROOT,
        description=(
            "Absolute path of the checkout or install holding this service's "
            "shipped non-Python assets (the ACP adapter's node_modules). Computed "
            "from __file__ by default; override in non-editable container "
            "installs where __file__ resolves inside site-packages. Never a "
            "storage location."
        ),
    )
    a2a_home: Path = Field(
        default=DEFAULT_HOME,
        alias="VAULTSPEC_A2A_HOME",
        description=(
            "State home: the databases, logs, discovery record and its handoff "
            "credential, the process registry and per-run provider homes. "
            "Defaults to .vault/data/agents in the project root, the runtime "
            "subtree vaultspec ignores and never walks. A relative value "
            "resolves against the project root."
        ),
    )
    capsule_assets_root: Path | None = Field(
        default=None,
        alias="VAULTSPEC_A2A_CAPSULE_ASSETS",
        description=(
            "Root of the desktop capsule's owned runtime assets (Node.js and the "
            "ACP adapter), absolute or relative to the project root; a leading "
            "~ is not expanded. When set, the provider factory resolves the default "
            "Node executable and ACP entry point ONLY from this root, with no "
            "checkout or PATH fallback. Unset for the Compose/dev profiles, where "
            "resolution is checkout-relative as before."
        ),
    )
    desktop_app_home: Path | None = Field(
        default=None,
        description=(
            "Explicit mutable-state root for the desktop product profile. When "
            "set, the profile is armed: the database, checkpoint, workspace, and "
            "A2A-home paths derive ONLY from this application home (via the "
            "desktop profile authority), never from the launch directory. Must be "
            "an absolute path. Unset for the Compose/dev profiles, whose path "
            "resolution is unchanged."
        ),
    )
    procs_home: Path | None = Field(
        default=None,
        description=(
            "Directory holding the development process registry, its port "
            "reservations and the test-resource leases. Unset: the registry "
            "directory inside the state home."
        ),
    )
    procs_name: str | None = Field(
        default=None,
        description=(
            "Name a self-registering managed process records itself under. "
            "Written into a child's environment by the lifecycle serve path."
        ),
    )
    procs_owner: str | None = Field(
        default=None,
        description=(
            "Owner label stamped on registry records this process claims, so "
            "concurrent operators hold distinct records. Unset: a label scoped to "
            "this process."
        ),
    )
    procs_toml: Path | None = Field(
        default=None,
        description="Managed-process table. Unset: procs.toml in the project root.",
    )
    engine_service_json: Path | None = Field(
        default=None,
        description=(
            "The vaultspec engine's discovery record, read to attach to it. "
            "Unset: the engine's record inside the project's .vault/data."
        ),
    )
    engine_serve_cmd: str | None = Field(
        default=None,
        description=(
            "Command template the dev process registry serves the engine with; "
            "{port} and {workspace} are substituted."
        ),
    )
    serve_in_process_lanes: bool = Field(
        default=False,
        description=(
            "Serve the in-process provider lanes (deterministic and mock). Off "
            "by default so a deployment sees them only when it arms them."
        ),
    )
    codex_config_home_retain: bool = Field(
        default=False,
        description=(
            "Keep each run's generated Codex config home after the run for "
            "inspection instead of deleting it."
        ),
    )
    desktop_settlement_url: str | None = Field(
        default=None,
        description=(
            "Absolute HTTP(S) URL of the dashboard's terminal-settlement "
            "receiver, published by the dashboard. Unset or malformed disables "
            "settlement."
        ),
    )
    gateway_lifetime_id: str = Field(
        default="",
        description=(
            "Identity of the gateway process that spawned this worker. Written "
            "by the gateway into its worker's environment; never set by hand."
        ),
    )
    worker_generation: str = Field(
        default="",
        description=(
            "Spawn generation this worker belongs to. Written by the gateway "
            "into its worker's environment; never set by hand."
        ),
    )
    otel_service_name: str = Field(
        default="vaultspec-a2a",
        validation_alias=AliasChoices(
            "VAULTSPEC_A2A_OTEL_SERVICE_NAME", "OTEL_SERVICE_NAME"
        ),
        description="Service name emitted on every span.",
    )
    otel_service_version: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "VAULTSPEC_A2A_OTEL_SERVICE_VERSION", "OTEL_SERVICE_VERSION"
        ),
        description="Version emitted on every span. Unset: the package version.",
    )
    otel_exporter_otlp_endpoint: str = Field(
        default=DEFAULT_OTLP_ENDPOINT,
        validation_alias=AliasChoices(
            "VAULTSPEC_A2A_OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_ENDPOINT"
        ),
        description="gRPC endpoint of the OTLP collector.",
    )
    otel_exporter_otlp_insecure: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "VAULTSPEC_A2A_OTEL_EXPORTER_OTLP_INSECURE", "OTEL_EXPORTER_OTLP_INSECURE"
        ),
        description="Disable TLS toward the collector.",
    )
    otel_sdk_disabled: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "VAULTSPEC_A2A_OTEL_SDK_DISABLED", "OTEL_SDK_DISABLED"
        ),
        description="Force the no-op OpenTelemetry implementation.",
    )
    otel_exporter_console: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "VAULTSPEC_A2A_OTEL_EXPORTER_CONSOLE", "OTEL_EXPORTER_CONSOLE"
        ),
        description="Also log spans to stdout (development only).",
    )
    otel_traces_exporter: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "VAULTSPEC_A2A_OTEL_TRACES_EXPORTER", "OTEL_TRACES_EXPORTER"
        ),
        description="'none' builds no span exporter at all.",
    )
    otel_metrics_exporter: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "VAULTSPEC_A2A_OTEL_METRICS_EXPORTER", "OTEL_METRICS_EXPORTER"
        ),
        description="'none' builds no metric reader at all.",
    )
    mock_api_base: str | None = Field(
        default=None,
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
    # Other tools' settings: the a2a name wins, and the owning tool's own name is
    # read as a fallback so an existing login keeps working.
    # ANTHROPIC_API_KEY is deliberately absent. The Claude lane authenticates with
    # claude_code_oauth_token, and every agent subprocess has ANTHROPIC_API_KEY
    # stripped from its environment by the workspace scrub
    # (workspace/environment.py), because the key alongside an OAuth token
    # silently downgrades a flat-rate subscription to pay-as-you-go billing.
    # The scrub is the single removal site: the ACP layer re-injects only the
    # auth a lane intentionally supports and strips nothing itself. Declaring
    # the key here would advertise a credential the code exists to remove.
    # Antigravity ships `agy` OUTSIDE PATH - its installer drops the binary in
    # a per-user application directory and exposes it through a wrapper - so a
    # bare name lookup finds nothing on a machine where the CLI works. This
    # override names the executable directly; when it is unset the lane falls
    # back to a PATH lookup and then to the installer's default location.
    antigravity_cli_path: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "VAULTSPEC_A2A_ANTIGRAVITY_CLI_PATH", "ANTIGRAVITY_CLI_PATH"
        ),
    )
    # The CLI keeps its login beside its own state, not under the Antigravity
    # application directory; the default mirrors where the installer writes it.
    antigravity_cli_home: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "VAULTSPEC_A2A_ANTIGRAVITY_CLI_HOME", "ANTIGRAVITY_CLI_HOME"
        ),
    )
    openai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("VAULTSPEC_A2A_OPENAI_API_KEY", "OPENAI_API_KEY"),
    )
    openai_base_url: str = Field(
        default="https://api.openai.com/v1",
        validation_alias=AliasChoices(
            "VAULTSPEC_A2A_OPENAI_BASE_URL", "OPENAI_BASE_URL"
        ),
        description="Base URL for the OpenAI API execution and catalog lane.",
    )
    zhipu_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("VAULTSPEC_A2A_ZHIPU_API_KEY", "ZHIPU_API_KEY"),
    )
    claude_code_oauth_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "VAULTSPEC_A2A_CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"
        ),
    )
    # Z.ai routes through the Claude ACP path against an Anthropic-Messages-
    # compatible endpoint. The base URL defaults to
    # Z.ai's documented Anthropic gateway; only the auth token must be supplied.
    zai_base_url: str = Field(
        default="https://api.z.ai/api/anthropic",
        validation_alias=AliasChoices(
            "VAULTSPEC_A2A_ZAI_BASE_URL", "ZAI_BASE_URL", "ZAI_ANTHROPIC_BASE_URL"
        ),
        description="Base URL for the Z.ai Anthropic-compatible endpoint.",
    )
    zai_auth_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "VAULTSPEC_A2A_ZAI_AUTH_TOKEN", "ZAI_AUTH_TOKEN", "ZAI_API_KEY"
        ),
    )
    # Codex `app-server` authenticates from a persisted local session in its Codex
    # home (~/.codex by default). This non-secret override points the subprocess at
    # an alternate home for headless/container use; no API key is involved (the
    # ChatGPT-session auth mode is file-based).
    codex_home: str | None = Field(
        default=None,
        validation_alias=AliasChoices("VAULTSPEC_A2A_CODEX_HOME", "CODEX_HOME"),
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
        validation_alias="VAULTSPEC_A2A_CODEX_BASE_URL",
        description=(
            "Point the Codex lane at an alternate API endpoint. Unset serves the "
            "provider's own endpoint."
        ),
    )
    # Kimi Code reads persisted aliases from KIMI_CODE_HOME (default ~/.kimi-code).
    # KIMI_MODEL_* defines a temporary provider and is valid only as a complete
    # name/key/base tuple.
    # Runtime alias selection is not a setting; the factory uses `-m`.
    kimi_code_home: str | None = Field(
        default=None,
        validation_alias=AliasChoices("VAULTSPEC_A2A_KIMI_CODE_HOME", "KIMI_CODE_HOME"),
    )
    kimi_model_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "VAULTSPEC_A2A_KIMI_MODEL_API_KEY", "KIMI_MODEL_API_KEY"
        ),
        exclude=True,
        repr=False,
    )
    kimi_model_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "VAULTSPEC_A2A_KIMI_MODEL_BASE_URL", "KIMI_MODEL_BASE_URL"
        ),
        description="Base URL in a complete temporary Kimi model definition.",
    )
    kimi_temporary_model_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "VAULTSPEC_A2A_KIMI_MODEL_NAME", "KIMI_MODEL_NAME"
        ),
        description="Alias in a complete temporary Kimi model definition.",
    )
    kimi_temporary_model_max_context_size: int | None = Field(
        default=None,
        gt=0,
        le=2_147_483_647,
        validation_alias=AliasChoices(
            "VAULTSPEC_A2A_KIMI_MODEL_MAX_CONTEXT_SIZE", "KIMI_MODEL_MAX_CONTEXT_SIZE"
        ),
        description="Provider-owned context-size value for a temporary Kimi model.",
    )
    kimi_temporary_model_capabilities: str | None = Field(
        default=None,
        max_length=512,
        validation_alias=AliasChoices(
            "VAULTSPEC_A2A_KIMI_MODEL_CAPABILITIES", "KIMI_MODEL_CAPABILITIES"
        ),
        description="Provider-owned capability value for a temporary Kimi model.",
    )

    @property
    def kimi_api_key(self) -> SecretStr | None:
        """Return the configured nonblank temporary-provider key."""
        candidate = self.kimi_model_api_key
        if candidate is not None and candidate.get_secret_value().strip():
            return candidate
        return None

    @property
    def kimi_base_url(self) -> str | None:
        """Return the normalized temporary-provider base URL."""
        candidate = self.kimi_model_base_url
        return (
            candidate.strip() if candidate is not None and candidate.strip() else None
        )

    host: str = Field(
        default="127.0.0.1",
        description="Bind host for the uvicorn server (VAULTSPEC_A2A_HOST).",
    )
    port: int = Field(
        default=18000,
        description="Bind port for the uvicorn server (VAULTSPEC_A2A_PORT).",
    )

    gateway_url: str = Field(
        default="",
        description=(
            "Base URL for reaching the gateway HTTP API. Used by the worker "
            "IPC bridge and the MCP tool server. Auto-derived from host+port "
            "when not set explicitly. It also moves the spawned worker's "
            "heartbeat and pairing target, so a proxy set here redirects both."
        ),
    )
    mcp_host: str = Field(
        default="0.0.0.0",
        description="Bind host for MCP streamable-http transport.",
    )
    mcp_port: int = Field(
        default=8200,
        description="Bind port for MCP streamable-http transport.",
    )
    # NoDecode: without it pydantic-settings JSON-decodes the env value before
    # any validator runs, so the comma form below could never be normalized.
    mcp_allowed_hosts: Annotated[list[str], NoDecode] = Field(
        default=["localhost:*", "127.0.0.1:*"],
        description=(
            "Host header values the MCP streamable-http transport accepts. "
            "Defaults to loopback only; a deployment that fronts MCP under a "
            "real hostname must name it here. Empty disables the Host check."
        ),
    )
    mcp_allowed_origins: Annotated[list[str], NoDecode] = Field(
        default=["http://localhost:*", "http://127.0.0.1:*"],
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
    )
    worker_host: str = Field(
        default="127.0.0.1",
        description="Bind host for locally managed worker processes.",
    )
    worker_url: str = Field(
        default="",
        description=(
            "Worker base URL for dispatch calls. "
            "Auto-derived from worker_host + worker_port."
        ),
    )
    internal_token: str | None = Field(
        default=None,
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
    )
    # Authoring verdict subscriber
    authoring_subscriber_enabled: bool = Field(
        default=False,
        description=(
            "Run the engine authoring-verdict subscriber as a gateway background "
            "task. Consumes GET /authoring/v1/events and resumes parked runs with "
            "reviewer verdicts. Off by default; enable when a live engine is "
            "available to review agent-authored proposals."
        ),
    )
    authoring_subscriber_poll_interval_seconds: float = Field(
        default=3.0,
        description=(
            "Seconds to wait after an empty lifecycle page before re-opening the "
            "engine SSE stream (steady-state poll cadence)."
        ),
    )
    authoring_subscriber_reconnect_base_seconds: float = Field(
        default=2.0,
        description=(
            "Initial exponential back-off (seconds) when the engine is absent or "
            "the lifecycle stream fails."
        ),
    )
    authoring_subscriber_reconnect_max_seconds: float = Field(
        default=30.0,
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
        description=(
            "Seconds without a heartbeat before the worker is considered disconnected."
        ),
    )
    cb_failure_threshold: int = Field(
        default=3,
        description="Consecutive dispatch failures before the circuit breaker opens.",
    )
    cb_recovery_timeout_seconds: float = Field(
        default=30.0,
        description="Seconds before a OPEN circuit breaker probes the worker again.",
    )

    # Worker health-poll adaptive back-off
    worker_poll_initial_interval_seconds: float = Field(
        default=0.1,
        description=(
            "Initial poll interval when waiting for the worker to become ready."
        ),
    )
    worker_poll_max_interval_seconds: float = Field(
        default=2.0,
        description="Maximum back-off poll interval when waiting for the worker.",
    )
    worker_poll_backoff_factor: float = Field(
        default=1.5,
        description="Multiplicative back-off factor for worker health polling.",
    )
    worker_poll_log_interval_seconds: float = Field(
        default=5.0,
        description="Seconds between 'still waiting for worker' log messages.",
    )
    worker_ready_timeout_seconds: float = Field(
        default=30.0,
        description=(
            "Seconds a spawned worker may take to become ready before the spawn"
            " is abandoned and its process tree reaped. Slow cold starts (first"
            " import on a cold filesystem, a contended host) need headroom here."
        ),
    )
    shutdown_total_timeout_seconds: float = Field(
        default=15.0,
        gt=0.0,
        le=600.0,
        description=(
            "One absolute budget for connection drain, active work, worker/bridge "
            "teardown, persistence close, and forced process-tree escalation."
        ),
    )
    shutdown_stream_grace_seconds: int = Field(
        default=2,
        gt=0,
        le=30,
        description="Maximum part of shutdown spent waiting for open HTTP streams.",
    )

    # Worker watchdog
    watchdog_poll_interval_seconds: float = Field(
        default=5.0,
        description="How often the watchdog checks worker liveness (seconds).",
    )
    watchdog_max_retries: int = Field(
        default=3,
        description="Maximum restart attempts before the watchdog gives up.",
    )
    watchdog_backoff_base_seconds: float = Field(
        default=2.0,
        description=(
            "Exponential back-off base (seconds) between watchdog restart attempts."
        ),
    )
    watchdog_restart_cooldown_seconds: float = Field(
        default=30.0,
        description=(
            "Minimum seconds between watchdog restart CYCLES (not attempts within a "
            "cycle). Rate-limits a persistent crash signal so the watchdog cannot "
            "spin restart cycles when the underlying condition has not cleared."
        ),
    )

    # Progress stream
    stream_heartbeat_interval_seconds: float = Field(
        default=30.0,
        description=(
            "Idle cadence at which the progress stream emits a keepalive frame "
            "(seconds). Bounds how long a quiet run can look indistinguishable "
            "from a dead connection to a reader."
        ),
    )

    # Internal IPC frame/body limits
    internal_max_frame_bytes: int = Field(
        default=1_048_576,
        description="Maximum worker→gateway WebSocket frame size (bytes).",
    )
    internal_max_http_body_bytes: int = Field(
        default=1_048_576,
        description=(
            "Maximum HTTP body accepted on internal /dispatch and /events endpoints."
        ),
    )

    # Worker IPC bridge
    ipc_flush_interval_seconds: float = Field(
        default=0.05,
        description="Batch flush cadence for the worker→gateway event bridge.",
    )
    ipc_max_flush_retries: int = Field(
        default=3,
        description="Maximum relay retry attempts per event batch.",
    )
    ipc_retry_backoff_base_seconds: float = Field(
        default=0.1,
        description=(
            "Back-off base (seconds) between relay retries (doubles each attempt)."
        ),
    )
    ipc_max_event_buffer: int = Field(
        default=10_000,
        description="Drop-oldest cap on the in-memory event buffer.",
    )

    # ACP provider
    acp_startup_timeout_seconds: float = Field(
        default=300.0,
        description="Seconds to wait for the ACP subprocess to become ready.",
    )
    acp_fs_read_max_bytes: int = Field(
        default=10_485_760,
        description="Maximum file read size (bytes) surfaced through ACP tool calls.",
    )
    acp_rpc_timeout_seconds: float = Field(
        default=15.0,
        description=(
            "Seconds to wait for a quick ACP management RPC response"
            " (list_sessions, set_mode, authenticate)."
        ),
    )
    acp_interactive_auth_timeout_seconds: float = Field(
        default=900.0,
        description=(
            "Watchdog timeout (seconds) for interactive ACP browser auth flows."
            " This is a backstop for authenticate/login prompts, not the normal"
            " success path."
        ),
    )
    acp_turn_idle_timeout_seconds: float = Field(
        default=600.0,
        description=(
            "Backstop (seconds) on a single ACP turn with no protocol activity."
            " The clock resets on every frame the agent writes, so a working"
            " agent never trips it; it bounds a turn whose subprocess is alive"
            " but has gone silent and would otherwise be awaited forever."
        ),
    )
    acp_chunk_queue_maxsize: int = Field(
        default=1024,
        description=(
            "Bound on the per-session chunk queue used to buffer ACP streaming"
            " output before it is consumed by the model invocation loop."
        ),
    )

    # MCP server
    mcp_create_timeout_seconds: float = Field(
        default=30.0,
        description="MCP tool: timeout (seconds) for thread-create operations.",
    )
    mcp_query_timeout_seconds: float = Field(
        default=15.0,
        description=(
            "MCP tool: timeout (seconds) for thread-query and status operations."
        ),
    )
    mcp_max_initial_message_chars: int = Field(
        default=32_000,
        description=(
            "MCP tool: maximum characters in the initial message before truncation."
        ),
    )
    mcp_preview_truncate_len: int = Field(
        default=200,
        description="MCP tool: character limit for inline message previews.",
    )

    # Environment Flags
    ci: bool = Field(
        default=False, validation_alias=AliasChoices("VAULTSPEC_A2A_CI", "CI")
    )
    no_color: bool = Field(
        default=False,
        validation_alias=AliasChoices("VAULTSPEC_A2A_NO_COLOR", "NO_COLOR"),
    )

    @field_validator("project_root", mode="before")
    @classmethod
    def _resolve_project_root(cls, value: object) -> object:
        """Resolve an explicitly supplied project root exactly as the default is."""
        if isinstance(value, str | Path) and str(value).strip():
            return resolve_project_root({"VAULTSPEC_A2A_PROJECT_ROOT": str(value)})
        return value

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
            if not _valid_kimi_capability(token):
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


# Canonical names for the settings a2a writes into its own children's
# environments (the worker<->gateway pairing). Derived from the schema, so the
# field declaration is the one place each name is spelled.
INTERNAL_TOKEN_ENV = env_name(InfraConfig, "internal_token")
GATEWAY_URL_ENV = env_name(InfraConfig, "gateway_url")
WORKER_URL_ENV = env_name(InfraConfig, "worker_url")
