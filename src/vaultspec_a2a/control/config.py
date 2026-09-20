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
    model_validator,
)
from pydantic_settings import SettingsConfigDict

from ..domain_config import DomainSettingsConfig
from ..utils.enums import Environment
from .infra_config import (
    _CHECKOUT_ENV_FILE,
    InfraConfig,
    _is_absolute_path,
    _require_absolute_sqlite_path,
    _synchronous_url,
    _warn_seating_discard,
)

__all__ = [
    "Settings",
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
