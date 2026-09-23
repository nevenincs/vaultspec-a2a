"""Desktop profile: explicit immutable-runtime and mutable-state roots.

The desktop product profile has two separate authorities. The *capsule root* is
the target-specific, immutable runtime generation the dashboard unpacks and runs
against; its Node.js and Agent Client Protocol (ACP) assets are resolved by the
:mod:`vaultspec_a2a.providers.factory` provider factory. The *application home*
is the mutable-state root that survives immutable runtime replacement. Databases,
checkpoints, logs, credentials, discovery state, receipts, workspaces, temporary
provider homes, and snapshots all live under the application home and never
derive from the launch directory.

:class:`DesktopProfile` binds one explicit application home to one explicit
capsule root, validates both fail-closed, and derives every mutable sub-path as
an explicit field. :func:`derive_state_paths` is the single authority for the
application-home path math; the desktop settings profile delegates its mutable
path derivation to it rather than duplicating the layout.

The capsule root is validated against the installed-runtime asset layout owned by
the provider factory (the bundled Node.js executable and the ACP adapter entry).
That installed layout is the runtime-asset directory the dashboard bundles next
to the frozen gateway binary; the factory constants are its single authority, so
this module reuses them rather than restating asset paths.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, Unpack, cast

from ..control.state_layout import state_layout

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "DesktopProfile",
    "DesktopProfileError",
    "DesktopStatePaths",
    "derive_state_paths",
]

logger = logging.getLogger(__name__)


class DesktopProfileError(ValueError):
    """A desktop profile root or asset failed fail-closed validation.

    The message names the offending path and the remediation so an operator can
    correct the installation. This is raised for a non-absolute root, roots that
    are not distinct, an unwritable or uncreatable application home, or a capsule
    root that is missing or lacks its bundled runtime assets.
    """


_MISSING_DESKTOP_STATE_PATH = object()
_DESKTOP_STATE_PATH_FIELDS = (
    "app_home",
    "database_path",
    "checkpoint_path",
    "logs_dir",
    "discovery_path",
    "workspaces_root",
    "credentials_dir",
    "receipts_dir",
    "temp_homes_dir",
    "snapshots_dir",
)
_DESKTOP_STATE_PATH_DEFAULTS = (_MISSING_DESKTOP_STATE_PATH,) * len(
    _DESKTOP_STATE_PATH_FIELDS
)


def _bind_desktop_state_paths(
    args: tuple[object, ...],
    options: Mapping[str, object],
) -> tuple[object, ...]:
    """Bind the original public field order for state-path construction."""
    if len(args) > len(_DESKTOP_STATE_PATH_FIELDS):
        raise TypeError(
            "expected at most "
            f"{len(_DESKTOP_STATE_PATH_FIELDS)} positional arguments, "
            f"got {len(args)}"
        )
    unknown = next(
        (name for name in options if name not in _DESKTOP_STATE_PATH_FIELDS),
        None,
    )
    if unknown is not None:
        raise TypeError(f"unexpected keyword argument {unknown!r}")
    duplicate = next(
        (name for name in _DESKTOP_STATE_PATH_FIELDS[: len(args)] if name in options),
        None,
    )
    if duplicate is not None:
        raise TypeError(f"multiple values for argument {duplicate!r}")
    return tuple(
        args[index]
        if index < len(args)
        else options.get(name, _DESKTOP_STATE_PATH_DEFAULTS[index])
        for index, name in enumerate(_DESKTOP_STATE_PATH_FIELDS)
    )


def _required_desktop_state_path(name: str, value: object) -> Path:
    if value is _MISSING_DESKTOP_STATE_PATH:
        raise TypeError(f"missing required argument {name!r}")
    return cast("Path", value)


@dataclass(frozen=True, slots=True)
class _DesktopSeatedPaths:
    """Mutable paths with an active runtime consumer."""

    app_home: Path
    database_path: Path
    checkpoint_path: Path
    logs_dir: Path
    discovery_path: Path
    workspaces_root: Path


@dataclass(frozen=True, slots=True)
class _DesktopReservedPaths:
    """Mutable paths reserved for consumers that have not landed yet."""

    credentials_dir: Path
    receipts_dir: Path
    temp_homes_dir: Path
    snapshots_dir: Path


class _DesktopStatePathsOptions(TypedDict, total=False):
    app_home: Path
    database_path: Path
    checkpoint_path: Path
    logs_dir: Path
    discovery_path: Path
    workspaces_root: Path
    credentials_dir: Path
    receipts_dir: Path
    temp_homes_dir: Path
    snapshots_dir: Path


@dataclass(frozen=True, slots=True, init=False)
class DesktopStatePaths:
    """The explicit mutable-state sub-paths derived from an application home.

    Every field is an absolute path beneath the application home. The fields fall
    into two groups. The *seated* paths describe where live runtime state already
    lands once the application home is bound: ``database_path`` and
    ``checkpoint_path`` are the SQLite files the settings profile derives;
    ``workspaces_root`` is the workspace tree; ``logs_dir`` is the runtime log
    directory (``a2a_home/runtime``, matching the gateway and worker logging
    convention); and ``discovery_path`` is the gateway discovery ``service.json``
    file at the application-home root (the location owned by
    ``lifecycle.discovery.service_json_path``). These mirror the operative
    ``a2a_home`` derivation rather than inventing a parallel layout.

    The *reserved* paths — ``credentials_dir``, ``receipts_dir``,
    ``temp_homes_dir``, and ``snapshots_dir`` — are declared here so the
    consistency-group snapshot and split-credential consumers bind one agreed
    layout. They have no consumer yet and are therefore not materialised by
    :meth:`DesktopProfile.ensure`.
    """

    _seated: _DesktopSeatedPaths
    _reserved: _DesktopReservedPaths

    def __init__(
        self,
        *args: object,
        **options: Unpack[_DesktopStatePathsOptions],
    ) -> None:
        values = _bind_desktop_state_paths(args, options)
        object.__setattr__(
            self,
            "_seated",
            _DesktopSeatedPaths(
                app_home=_required_desktop_state_path("app_home", values[0]),
                database_path=_required_desktop_state_path("database_path", values[1]),
                checkpoint_path=_required_desktop_state_path(
                    "checkpoint_path", values[2]
                ),
                logs_dir=_required_desktop_state_path("logs_dir", values[3]),
                discovery_path=_required_desktop_state_path(
                    "discovery_path", values[4]
                ),
                workspaces_root=_required_desktop_state_path(
                    "workspaces_root", values[5]
                ),
            ),
        )
        object.__setattr__(
            self,
            "_reserved",
            _DesktopReservedPaths(
                credentials_dir=_required_desktop_state_path(
                    "credentials_dir", values[6]
                ),
                receipts_dir=_required_desktop_state_path("receipts_dir", values[7]),
                temp_homes_dir=_required_desktop_state_path(
                    "temp_homes_dir", values[8]
                ),
                snapshots_dir=_required_desktop_state_path("snapshots_dir", values[9]),
            ),
        )

    @property
    def app_home(self) -> Path:
        return self._seated.app_home

    @property
    def database_path(self) -> Path:
        return self._seated.database_path

    @property
    def checkpoint_path(self) -> Path:
        return self._seated.checkpoint_path

    @property
    def logs_dir(self) -> Path:
        return self._seated.logs_dir

    @property
    def discovery_path(self) -> Path:
        return self._seated.discovery_path

    @property
    def workspaces_root(self) -> Path:
        return self._seated.workspaces_root

    @property
    def credentials_dir(self) -> Path:
        return self._reserved.credentials_dir

    @property
    def receipts_dir(self) -> Path:
        return self._reserved.receipts_dir

    @property
    def temp_homes_dir(self) -> Path:
        return self._reserved.temp_homes_dir

    @property
    def snapshots_dir(self) -> Path:
        return self._reserved.snapshots_dir

    @property
    def provisioned_directories(self) -> tuple[Path, ...]:
        """Return the directories with a live consumer that ``ensure`` creates.

        Only the seated directories are materialised. ``discovery_path`` is a file
        written by the discovery authority and its parent is the application home;
        the reserved directories are omitted until their phases consume them.
        """
        return (
            self._seated.app_home,
            self._seated.database_path.parent,
            self._seated.checkpoint_path.parent,
            self._seated.logs_dir,
            self._seated.workspaces_root,
        )


def derive_state_paths(app_home: Path) -> DesktopStatePaths:
    """Derive the explicit mutable-state layout from an explicit application home.

    The layout itself is :func:`~vaultspec_a2a.control.state_layout.state_layout`,
    the one shape every state home takes; this adds the desktop profile's
    refusal of a relative application home. ``app_home`` must be an absolute path
    so that no mutable path can resolve relative to the launch directory.

    Raises:
        DesktopProfileError: If ``app_home`` is not absolute.
    """
    if not app_home.is_absolute():
        raise DesktopProfileError(
            f"desktop application home must be an absolute path, got {app_home!r}; "
            "the desktop profile forbids launch-directory-relative state roots."
        )
    layout = state_layout(app_home)
    return DesktopStatePaths(
        app_home=layout.home,
        database_path=layout.database_path,
        checkpoint_path=layout.checkpoint_path,
        logs_dir=layout.logs_dir,
        discovery_path=layout.discovery_path,
        workspaces_root=layout.workspaces_root,
        credentials_dir=layout.credentials_dir,
        receipts_dir=layout.receipts_dir,
        temp_homes_dir=layout.temp_homes_dir,
        snapshots_dir=layout.snapshots_dir,
    )


def _capsule_asset_paths(capsule_root: Path) -> tuple[Path, Path]:
    """Return the (Node executable, ACP entry) paths beneath a capsule root.

    The provider factory owns the installed-runtime asset layout, so its path
    authorities are imported lazily here: the desktop package stays importable
    for the manifest contract without pulling the provider/langchain stack, and
    the asset layout has exactly one definition.
    """
    from ..providers._factory_commands import capsule_acp_entry, capsule_node_executable

    return capsule_node_executable(capsule_root), capsule_acp_entry(capsule_root)


def _validate_capsule_root(capsule_root: Path) -> Path:
    """Validate that ``capsule_root`` is a real capsule carrying runtime assets."""
    if not capsule_root.is_absolute():
        raise DesktopProfileError(
            f"desktop capsule root must be an absolute path, got {capsule_root!r}; "
            "install or repair the desktop capsule before arming the profile."
        )
    root = Path(os.path.normpath(capsule_root))
    if not root.is_dir():
        raise DesktopProfileError(
            f"desktop capsule root is not a directory: {root}. "
            "Install or repair the desktop capsule before arming the profile."
        )
    node_executable, acp_entry = _capsule_asset_paths(root)
    for asset, description in (
        (node_executable, "bundled Node.js runtime executable"),
        (acp_entry, "bundled ACP adapter entry point"),
    ):
        if not asset.is_file():
            raise DesktopProfileError(
                f"desktop capsule root {root} is missing its {description}: {asset}. "
                "Install or repair the desktop capsule before arming the profile."
            )
    return root


def _validate_app_home(app_home: Path) -> None:
    """Validate that the application home exists writable or can be created."""
    existing = app_home
    while not existing.exists():
        parent = existing.parent
        if parent == existing:
            raise DesktopProfileError(
                f"desktop application home {app_home} has no existing ancestor; "
                "provide a creatable absolute state root."
            )
        existing = parent
    if not existing.is_dir():
        raise DesktopProfileError(
            f"desktop application home path is blocked by a non-directory: "
            f"{existing}. Provide a writable absolute state root."
        )
    if not os.access(existing, os.W_OK):
        raise DesktopProfileError(
            f"desktop application home is not writable or creatable: {existing} "
            f"(resolving {app_home}). Grant write access or choose another root."
        )


@dataclass(frozen=True, slots=True)
class DesktopProfile:
    """One armed desktop profile binding a mutable app home and immutable capsule.

    Construct instances with :meth:`resolve`, which validates both roots
    fail-closed and derives the explicit mutable-state layout. Direct
    construction bypasses validation and is reserved for callers that have
    already validated their inputs.
    """

    app_home: Path
    capsule_root: Path
    state: DesktopStatePaths

    @classmethod
    def resolve(cls, app_home: Path, capsule_root: Path) -> DesktopProfile:
        """Validate ``app_home`` and ``capsule_root`` and derive the profile.

        Both roots must be absolute and distinct (neither may nest inside the
        other, so mutable state never lives within an immutable runtime
        generation). The capsule root must exist and carry the bundled runtime
        assets; the application home must exist writable or be creatable.

        Raises:
            DesktopProfileError: If any root or asset fails validation.
        """
        state = derive_state_paths(app_home)
        capsule = _validate_capsule_root(capsule_root)
        home = state.app_home
        nested = home.is_relative_to(capsule) or capsule.is_relative_to(home)
        if home == capsule or nested:
            raise DesktopProfileError(
                f"desktop application home {home} and capsule root {capsule} must be "
                "distinct and non-nested; mutable state must live outside the "
                "immutable runtime generation."
            )
        _validate_app_home(home)
        return cls(app_home=home, capsule_root=capsule, state=state)

    @property
    def capsule_assets_root(self) -> Path:
        """Return the capsule-owned asset root consumed by the provider factory.

        The provider factory resolves the bundled Node executable and ACP entry
        relative to this root, so it is the capsule root itself. Binding
        ``settings.capsule_assets_root`` to this value keeps the provider seam
        coherent with the armed profile.
        """
        return self.capsule_root

    def ensure(self) -> None:
        """Create the provisioned mutable-state directories beneath the app home.

        Idempotent: existing directories are left untouched. Only directories with
        a live consumer are created; the reserved directories are left for their
        consuming phases so ``ensure`` never seeds dead empty state. Called once
        the profile is armed and about to seat live state.

        Each directory is restricted to its owner. The credential files one level
        over already get this treatment, and the state directory holds the
        databases: thread content, the permission-decision log, and the whole of
        every agent conversation in the checkpoint store. Restricting the
        DIRECTORY rather than the database files is deliberate — SQLite writes
        ``-wal`` and ``-shm`` beside each database, and the write-ahead log holds
        recently committed rows, so hardening the files alone would leave the most
        recent data readable.
        """
        from ._platform_acl import harden_credential_path

        for directory in self.state.provisioned_directories:
            directory.mkdir(parents=True, exist_ok=True)
            # Best effort: a filesystem that cannot express owner-only access
            # (a network share, a mount without ACL support) must not stop the
            # profile from arming — the store still has to work there.
            try:
                harden_credential_path(directory)
            except OSError:
                logger.warning(
                    "Could not restrict %s to its owner; the databases beneath it "
                    "may be readable by other local users.",
                    directory,
                    exc_info=True,
                )
