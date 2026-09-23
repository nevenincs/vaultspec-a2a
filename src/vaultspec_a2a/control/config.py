"""Infrastructure configuration and backwards-compatible Settings facade.

``InfraConfig`` holds every field that touches external services: ports, hosts,
database URLs, API keys, filesystem paths, pool sizes, service timeouts, etc.

``Settings`` composes ``DomainConfig`` (Layer 1 behavioural knobs) with
``InfraConfig`` via multiple inheritance, producing a single object that is
a drop-in replacement for the former ``core.config.Settings``.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Literal, Self

from pydantic import (
    PrivateAttr,
    model_validator,
)
from pydantic_settings import SettingsConfigDict

from ..domain_config import DomainSettingsConfig
from ..utils.enums import Environment
from .env_prefix import ENV_PREFIX
from .infra_config import (
    InfraConfig,
    _synchronous_url,
    _warn_seating_discard,
)
from .settings_base import env_name, is_absolute_path, resolve_against
from .state_layout import (
    ENGINE_DISCOVERY_RECORD,
    StateLayout,
    UnsafeStateHomeError,
    seal_state_home,
    state_layout,
)

__all__ = [
    "Settings",
    "setting_env",
    "settings",
]

if TYPE_CHECKING:
    from ..desktop.credentials import DesktopCredentialPaths


class Settings(DomainSettingsConfig, InfraConfig):
    """Backwards-compatible composed settings.

    Inherits all ~18 domain fields from ``DomainConfig`` and all ~75
    infrastructure fields from ``InfraConfig``.  The resulting object is
    a drop-in replacement for the former ``core.config.Settings``.
    """

    model_config = SettingsConfigDict(
        env_file=InfraConfig.project_dotenv(),
        env_file_encoding="utf-8",
        env_prefix=ENV_PREFIX,
        extra="ignore",
        env_ignore_empty=True,
    )

    # The fields a source actually supplied, captured before any validator below
    # assigns one: an assignment marks a field as set, after which a configured
    # value and a derived one are indistinguishable.
    _configured_fields: frozenset[str] = PrivateAttr(default=frozenset())

    @model_validator(mode="after")
    def _record_configured_fields(self) -> Self:
        self._configured_fields = frozenset(self.model_fields_set)
        return self

    @model_validator(mode="after")
    def _separate_gateway_and_worker_credentials(self) -> Self:
        """Reject configurations that collapse gateway and worker authority."""
        if (
            self.gateway_service_token is not None
            and self.internal_token is not None
            and self.gateway_service_token == self.internal_token
        ):
            msg = (
                "VAULTSPEC_A2A_GATEWAY_TOKEN must differ from "
                "VAULTSPEC_A2A_INTERNAL_TOKEN"
            )
            raise ValueError(msg)
        return self

    # Whether the gateway URL was configured rather than derived. Captured before
    # the derivation below assigns the field, because an assignment marks a field
    # as set and would make the two cases indistinguishable afterwards.
    _gateway_url_configured: bool = PrivateAttr(default=False)

    @model_validator(mode="after")
    def _derive_service_urls(self) -> Self:
        """Auto-derive gateway_url and worker_url from host+port when not set."""
        self._gateway_url_configured = bool(self.gateway_url)
        if not self.gateway_url:
            host = "127.0.0.1" if self.host in ("0.0.0.0", "::") else self.host
            self.gateway_url = f"http://{host}:{self.port}"
        if not self.worker_url:
            self.worker_url = f"http://{self.worker_host}:{self.worker_port}"
        return self

    @model_validator(mode="after")
    def _resolve_against_project_root(self) -> Self:
        """Resolve every relative path setting against the project root.

        One rule for every path setting, operator-supplied or defaulted: an
        absolute value is taken as is, and a relative one is joined onto the
        project root - never onto the working directory, which is how two
        processes of one project would otherwise open two different stores.
        The state home's own default is the relative ``.vault/data/agents``, so
        it lands in the project by the same rule a relative override does.

        Runs before the desktop seating, which derives from the application home
        and therefore needs it absolute first.
        """
        root = self.project_root
        self.a2a_home = resolve_against(root, self.a2a_home)
        self.install_root = resolve_against(root, self.install_root)
        for field in (
            "desktop_app_home",
            "capsule_assets_root",
            "workspace_root",
            "procs_home",
            "procs_toml",
            "engine_service_json",
        ):
            value = getattr(self, field)
            if value is not None:
                setattr(self, field, resolve_against(root, value))
        self.database_url = _resolve_sqlite_url(root, self.database_url)
        if self.checkpoint_database_url is not None:
            self.checkpoint_database_url = _resolve_sqlite_url(
                root, self.checkpoint_database_url
            )
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
        actually displaces one, it says so. ``_configured_fields`` distinguishes a
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

        explicit = self._configured_fields
        if "a2a_home" in explicit:
            _warn_seating_discard("VAULTSPEC_A2A_HOME", self.a2a_home, state.app_home)
        if "workspace_root" in explicit:
            _warn_seating_discard(
                "VAULTSPEC_A2A_WORKSPACE_ROOT",
                self.workspace_root,
                state.workspaces_root,
            )
        if "database_url" in explicit:
            _warn_seating_discard(
                "VAULTSPEC_A2A_DATABASE_URL", self.database_url, derived_database_url
            )
        if "checkpoint_database_url" in explicit:
            _warn_seating_discard(
                "VAULTSPEC_A2A_CHECKPOINT_DATABASE_URL",
                self.checkpoint_database_url,
                derived_checkpoint_url,
            )

        self.a2a_home = state.app_home
        self.workspace_root = state.workspaces_root
        self.database_url = derived_database_url
        self.checkpoint_database_url = derived_checkpoint_url
        return self

    @model_validator(mode="after")
    def _refuse_a_home_that_holds_the_project(self) -> Self:
        """Refuse a state home that is the project root or one of its ancestors.

        Every writer seals the home by writing an ignore-everything file into it,
        so a home that contains the project would take the project's own sources
        out of version control. That is a configuration mistake to stop at boot,
        before any writer runs.
        """
        home, root = self.a2a_home, self.project_root
        if root == home or root.is_relative_to(home):
            msg = (
                f"{setting_env('a2a_home')}={home} contains the project root {root}; "
                "a2a seals its state home against version control, which would hide "
                "the project itself. Choose a directory inside or outside the "
                "project that holds only a2a state."
            )
            raise UnsafeStateHomeError(msg)
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
        _synchronous_url(self.database_url, setting="VAULTSPEC_A2A_DATABASE_URL")
        if self.checkpoint_database_url is not None:
            _synchronous_url(
                self.checkpoint_database_url,
                setting="VAULTSPEC_A2A_CHECKPOINT_DATABASE_URL",
            )
        return self

    @model_validator(mode="after")
    def _place_default_stores(self) -> Self:
        """Put the stores nobody configured into the state home's layout.

        Left unset, the application database and the checkpoint store are two
        files under ``<state home>/state``, the same layout the desktop profile
        and ``start`` use, so every entrypoint opens the same pair. A configured
        database URL with no checkpoint URL keeps the one-store arrangement it
        always had: the checkpoint store follows the configured database.

        Configured means supplied by a source, as recorded before any validator
        assigned a field. The armed desktop profile seats both stores itself, so
        this leaves an armed profile's stores alone.
        """
        configured = self._configured_fields
        layout = self.state_layout
        if self.desktop_profile_armed:
            return self._check_backends()
        if "database_url" not in configured:
            self.database_url = _sqlite_url(layout.database_path)
            if "checkpoint_database_url" not in configured:
                self.checkpoint_database_url = _sqlite_url(layout.checkpoint_path)
        return self._check_backends()

    def _check_backends(self) -> Self:
        # Resolving the backends here raises when a declared backend and its URL
        # disagree, which the synchronous admin engines built from these values
        # have no other seam to catch.
        _ = self.resolved_database_backend
        if self.checkpoint_database_url is not None:
            _ = self.resolved_checkpoint_backend
        return self

    @property
    def state_layout(self) -> StateLayout:
        """Every mutable path a2a writes, derived from the state home."""
        return state_layout(self.a2a_home)

    def prepare_state_dir(self, directory: Path) -> Path:
        """Create ``directory`` so that nothing a2a writes can be committed.

        Every writer that creates a directory for a2a state goes through here.
        Inside the state home, the home is sealed first, whichever writer runs
        first. A store relocated elsewhere inside the project is sealed at the
        outermost directory a2a itself creates for it; a directory that already
        existed is the operator's, and a2a writes no ignore file into it.
        Outside the project, version control is not a2a's concern.
        """
        home = self.a2a_home
        if directory == home or directory.is_relative_to(home):
            seal_state_home(home)
        elif directory.is_relative_to(self.project_root):
            created = _outermost_missing(directory, self.project_root)
            if created is not None:
                seal_state_home(created)
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    @property
    def registry_home(self) -> Path:
        """The development process registry, its reservations and leases."""
        if self.procs_home is not None:
            return self.procs_home
        return self.state_layout.procs_dir

    @property
    def procs_table_path(self) -> Path:
        """The managed-process table the registry serves roles from."""
        if self.procs_toml is not None:
            return self.procs_toml
        return self.project_root / "procs.toml"

    @property
    def engine_discovery_path(self) -> Path:
        """The vaultspec engine's discovery record a2a attaches through."""
        if self.engine_service_json is not None:
            return self.engine_service_json
        return self.project_root / ENGINE_DISCOVERY_RECORD

    @property
    def gateway_url_configured(self) -> bool:
        """Whether the gateway URL came from configuration rather than host+port."""
        return self._gateway_url_configured

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
    def temp_homes_dir(self) -> Path:
        """The root per-run provider configuration homes are created inside.

        Inside the state home, so every home a run leaves behind is accounted
        for with the rest of a2a's state rather than scattered through the
        system temporary directory.
        """
        return self.state_layout.temp_homes_dir

    @property
    def resolved_database_backend(self) -> Literal["sqlite", "postgres"]:
        """Validate the configured application database backend against the URL."""
        url = self.database_url
        if self.database_backend == "sqlite" and not url.startswith("sqlite"):
            msg = (
                "VAULTSPEC_A2A_DATABASE_BACKEND=sqlite requires "
                "VAULTSPEC_A2A_DATABASE_URL to use a sqlite SQLAlchemy URL."
            )
            raise ValueError(msg)
        if self.database_backend == "postgres" and not url.startswith("postgresql"):
            msg = (
                "VAULTSPEC_A2A_DATABASE_BACKEND=postgres requires "
                "VAULTSPEC_A2A_DATABASE_URL to use a postgresql SQLAlchemy URL."
            )
            raise ValueError(msg)
        return self.database_backend

    @property
    def resolved_checkpoint_backend(self) -> Literal["sqlite", "postgres"]:
        """Validate the configured checkpoint backend against the configured DSN."""
        url = self.checkpoint_database_url or self.database_url
        if self.checkpoint_backend == "sqlite" and not url.startswith("sqlite"):
            msg = (
                "VAULTSPEC_A2A_CHECKPOINT_BACKEND=sqlite requires the checkpoint URL "
                "to use a sqlite-compatible scheme."
            )
            raise ValueError(msg)
        if self.checkpoint_backend == "postgres" and not url.startswith("postgresql"):
            msg = (
                "VAULTSPEC_A2A_CHECKPOINT_BACKEND=postgres requires the checkpoint URL "
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
        return _synchronous_url(self.database_url, setting="VAULTSPEC_A2A_DATABASE_URL")

    @property
    def checkpoint_sync_url(self) -> str:
        """Return a synchronous SQLAlchemy URL for the checkpoint store.

        Falls back to the application database when no dedicated checkpoint URL
        is configured, matching the runtime savers: the two stores share one file
        by default and split only when explicitly configured.
        """
        if self.checkpoint_database_url is None:
            return _synchronous_url(
                self.database_url, setting="VAULTSPEC_A2A_DATABASE_URL"
            )
        return _synchronous_url(
            self.checkpoint_database_url,
            setting="VAULTSPEC_A2A_CHECKPOINT_DATABASE_URL",
        )

    def validate_postgres_requirement(self) -> None:
        """Fail fast when Postgres-backed dependencies are required but absent."""
        if not self.postgres_required:
            return

        problems: list[str] = []
        if self.resolved_database_backend != "postgres":
            problems.append(
                "VAULTSPEC_A2A_POSTGRES_REQUIRED=true requires "
                "VAULTSPEC_A2A_DATABASE_BACKEND=postgres"
            )
        if self.resolved_checkpoint_backend != "postgres":
            problems.append(
                "VAULTSPEC_A2A_POSTGRES_REQUIRED=true requires "
                "VAULTSPEC_A2A_CHECKPOINT_BACKEND=postgres"
            )
        if problems:
            raise ValueError("; ".join(problems))


def _sqlite_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.as_posix()}"


def _resolve_sqlite_url(root: Path, url: str) -> str:
    """Return ``url`` with a relative SQLite file path resolved against ``root``.

    Anything that is not a relative SQLite file - a server URL, an in-memory
    store, an absolute path, an unparseable value - is returned unchanged; the
    synchronous-derivation validator reports an unparseable one.
    """
    from sqlalchemy.engine.url import make_url
    from sqlalchemy.exc import ArgumentError

    try:
        parsed = make_url(url)
    except ArgumentError:
        return url
    database = parsed.database
    if (
        parsed.get_backend_name() != "sqlite"
        or not database
        or database == ":memory:"
        or is_absolute_path(database)
    ):
        return url
    resolved = resolve_against(root, database)
    return parsed.set(database=resolved.as_posix()).render_as_string(
        hide_password=False
    )


def _outermost_missing(directory: Path, root: Path) -> Path | None:
    """The outermost ancestor of ``directory`` below ``root`` that does not exist."""
    missing: Path | None = None
    current = directory
    while current != root and current.is_relative_to(root):
        if current.exists():
            break
        missing = current
        current = current.parent
    return missing


def setting_env(field: str) -> str:
    """Return the environment name a setting is read from.

    Every site that writes a setting into a child process's environment takes
    the name from here, so the field declaration is its only spelling.
    """
    return env_name(Settings, field)


# Global settings instance
settings = Settings()
