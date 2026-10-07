"""Infrastructure settings and the process-wide ``settings`` singleton.

``InfraConfig`` declares every field that touches external services: ports,
hosts, database URLs, API keys, filesystem paths and service timeouts.
``Settings`` adds the derivation and path-anchoring validators and the
properties built on the resolved values.

Behavioural knobs are not declared here: they belong to
:mod:`vaultspec_a2a.domain_config`, and no field is reachable through both.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Self

from pydantic import (
    PrivateAttr,
    model_validator,
)

from ..utils.enums import Environment
from .infra_config import (
    InfraConfig,
    _warn_seating_discard,
)
from .settings_base import (
    built_at_first_use,
    env_name,
    is_absolute_path,
    read_configuration,
    resolve_against,
)
from .state_layout import (
    StateLayout,
    UnsafeStateHomeError,
    engine_discovery_path,
    seal_state_home,
    state_layout,
)

__all__ = [
    "Settings",
    "setting_env",
    "settings",
]

if TYPE_CHECKING:
    from sqlalchemy.engine.url import URL

    from ..desktop.credentials import DesktopCredentialPaths

_ONLY_SQLITE = "SQLite is the only supported store"


class Settings(InfraConfig):
    """The infrastructure settings, with their derived values and anchored paths."""

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
        for field in (
            "a2a_home",
            "install_root",
            "desktop_app_home",
            "capsule_assets_root",
            "claude_cli_executable",
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
        unarmed (the development profile), this is a no-op and the
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
        # the desktop package, preserving the development import surface.
        from ..desktop.profile import derive_state_paths

        state = derive_state_paths(self.desktop_app_home)
        derived_database_url = f"sqlite+aiosqlite:///{state.database_path.as_posix()}"
        derived_checkpoint_url = (
            f"sqlite+aiosqlite:///{state.checkpoint_path.as_posix()}"
        )

        # One rule, stated once, over the four fields the application home
        # seats: each carries the variable an operator would have set it with,
        # so a displaced value is reported in the operator's own vocabulary.
        seated: dict[str, tuple[str, object]] = {
            "a2a_home": ("VAULTSPEC_A2A_HOME", state.home),
            "workspace_root": (
                "VAULTSPEC_A2A_WORKSPACE_ROOT",
                state.workspaces_root,
            ),
            "database_url": ("VAULTSPEC_A2A_DATABASE_URL", derived_database_url),
            "checkpoint_database_url": (
                "VAULTSPEC_A2A_CHECKPOINT_DATABASE_URL",
                derived_checkpoint_url,
            ),
        }
        explicit = self._configured_fields
        for field, (variable, derived) in seated.items():
            if field in explicit:
                _warn_seating_discard(variable, getattr(self, field), derived)
            setattr(self, field, derived)
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
    def _refuse_every_store_but_sqlite(self) -> Self:
        """Refuse each input that would select a store other than SQLite.

        A retired backend selector, a retired requirement flag or a store URL
        naming another database would otherwise be ignored - booting an empty
        SQLite store beside the database the operator believes is in use - or
        fail wherever the first engine built from it happens to be created. Every
        problem is reported together, and no URL is ever echoed: it routinely
        carries a password.

        Declared after the desktop seating so it validates the URLs the process
        will actually use, not the ones the seating is about to replace.
        """
        problems = [
            f"{setting_env(field)}={value!r} is refused because {_ONLY_SQLITE}"
            for field, value in (
                ("database_backend", self.database_backend),
                ("checkpoint_backend", self.checkpoint_backend),
            )
            if value != "sqlite"
        ]
        if self.postgres_required:
            problems.append(
                f"{setting_env('postgres_required')}=true is refused because "
                f"{_ONLY_SQLITE}"
            )
        for field, url in (
            ("database_url", self.database_url),
            ("checkpoint_database_url", self.checkpoint_database_url),
        ):
            if url is None:
                continue
            problem = _store_url_problem(setting_env(field), url)
            if problem is not None:
                problems.append(problem)
        if problems:
            raise ValueError("; ".join(problems))
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
            return self
        if "database_url" not in configured:
            self.database_url = _sqlite_url(layout.database_path)
            if "checkpoint_database_url" not in configured:
                self.checkpoint_database_url = _sqlite_url(layout.checkpoint_path)
        return self

    @property
    def state_layout(self) -> StateLayout:
        """Every mutable path a2a writes, derived from the state home."""
        return state_layout(self.a2a_home)

    def prepare_state_dir(self, directory: Path) -> Path:
        """Create ``directory`` so that nothing a2a writes can be committed.

        Every writer that creates a directory for a2a state goes through here.
        Inside the state home, the home is sealed first, whichever writer runs
        first, when a2a owns it (see :func:`seal_state_home`). A store relocated
        elsewhere inside the project is sealed at the outermost directory a2a
        itself creates for it. A directory that already existed is the
        operator's, and a2a writes no ignore file into it. Outside the project,
        version control is not a2a's concern.
        """
        home = self.a2a_home
        if self.desktop_profile_armed and (
            directory == home or directory.is_relative_to(home)
        ):
            from ..desktop.profile import derive_state_paths, ensure_private_state

            ensure_private_state(derive_state_paths(home))
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
        return engine_discovery_path(self.project_root)

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

        Returns ``None`` while the profile is unarmed (the development profile),
        so no credential path resolves relative to a launch directory and the
        unarmed import surface never pulls the desktop package.
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
    def internal_max_event_batch_bytes(self) -> int:
        """Return the largest worker event batch the gateway will accept.

        One home for the figure, read by the gateway that enforces it and by the
        worker that has to size its batches under it. The worker used to post its
        whole buffer and the gateway used to refuse anything over this, with the
        number written on each side: a post-outage backlog then met a refusal the
        worker could do nothing about and re-sent it unchanged, forever.
        """
        return self.internal_max_http_body_bytes * (
            self.internal_event_batch_body_multiplier
        )

    @property
    def database_path(self) -> Path:
        """Extract the plain file path from the SQLAlchemy database URL."""
        return _sqlite_file(self.database_url)

    @property
    def checkpoint_path(self) -> Path:
        """Return the SQLite checkpoint path."""
        return _sqlite_file(self.checkpoint_database_url or self.database_url)

    @property
    def checkpoint_connection_string(self) -> str:
        """Return the file path (or ``:memory:``) the LangGraph SQLite saver opens."""
        url = self.checkpoint_database_url or self.database_url
        if ":///" not in url:
            msg = f"Unsupported SQLite checkpoint URL: {url!r}"
            raise ValueError(msg)
        raw = url.split("///", 1)[1]
        if raw == ":memory:":
            return ":memory:"
        return str(Path(raw).resolve())


def _sqlite_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.as_posix()}"


def _sqlite_file(url: str) -> Path:
    """Return the file a SQLite URL names, or ``:memory:`` for an in-memory store."""
    raw = url.split("///", 1)[1] if ":///" in url else "vaultspec.db"
    if raw == ":memory:":
        return Path(":memory:")
    return Path(raw).resolve()


def _parsed_url(url: str) -> "URL | None":
    """Parse a SQLAlchemy URL, or return ``None`` when it cannot be parsed."""
    # Imported lazily: SQLAlchemy costs roughly a quarter-second to import, and the
    # settings module sits on the CLI startup path.
    from sqlalchemy.engine.url import make_url
    from sqlalchemy.exc import ArgumentError

    try:
        return make_url(url)
    except ArgumentError:
        return None


def _store_url_problem(setting: str, url: str) -> str | None:
    """Say why ``url`` cannot name a store, or ``None`` when it names SQLite.

    The URL itself is never echoed: it routinely carries a password.
    """
    parsed = _parsed_url(url)
    if parsed is None:
        return f"{setting} is not a parseable SQLAlchemy URL"
    backend = parsed.get_backend_name()
    if backend != "sqlite":
        return f"{setting} names the {backend!r} backend, but {_ONLY_SQLITE}"
    return None


def _resolve_sqlite_url(root: Path, url: str) -> str:
    """Return ``url`` with a relative SQLite file path resolved against ``root``.

    Anything that is not a relative SQLite file - another database's URL, an
    in-memory store, an absolute path, an unparseable value - is returned
    unchanged; the store-URL validator reports the ones it cannot use.
    """
    parsed = _parsed_url(url)
    if parsed is None:
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


#: The process-wide settings, built the first time one is read rather than
#: when this module is imported. A configuration the settings refuse - a
#: named file that is not there, a value of the wrong shape - is then a
#: named error at the site that started the process, not a pydantic
#: traceback handed to whichever module imported this one first.
settings = built_at_first_use(lambda: read_configuration(Settings))
