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
That installed layout is the runtime form of the transport capsule assembled by
``scripts/build_desktop_capsule.py``; the factory constants are its single
authority, so this module reuses them rather than restating asset paths.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "DesktopProfile",
    "DesktopProfileError",
    "DesktopStatePaths",
    "derive_state_paths",
]

# The gateway discovery record filename. This mirrors the canonical placement owned
# by ``lifecycle.discovery.service_json_path`` (``<app_home>/service.json``). It is
# restated here as a leaf constant so ``derive_state_paths`` — which the settings
# profile calls from a model validator while ``control.config`` is still being
# constructed — never imports the lifecycle/HTTP stack, which would close a circular
# import back through ``control.config``. ``test_profile_paths`` guards the two names
# against drift.
_DISCOVERY_RECORD_FILENAME = "service.json"


class DesktopProfileError(ValueError):
    """A desktop profile root or asset failed fail-closed validation.

    The message names the offending path and the remediation so an operator can
    correct the installation. This is raised for a non-absolute root, roots that
    are not distinct, an unwritable or uncreatable application home, or a capsule
    root that is missing or lacks its bundled runtime assets.
    """


@dataclass(frozen=True, slots=True)
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
    consuming phases (the consistency-group snapshots of ``W02.P06`` and the
    split credentials of ``W03.P08``) bind one agreed layout. They have no
    consumer yet and are therefore not materialised by :meth:`DesktopProfile.ensure`.
    """

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

    @property
    def provisioned_directories(self) -> tuple[Path, ...]:
        """Return the directories with a live consumer that ``ensure`` creates.

        Only the seated directories are materialised. ``discovery_path`` is a file
        written by the discovery authority and its parent is the application home;
        the reserved directories are omitted until their phases consume them.
        """
        return (
            self.app_home,
            self.database_path.parent,
            self.checkpoint_path.parent,
            self.logs_dir,
            self.workspaces_root,
        )


def _discovery_path(app_home: Path) -> Path:
    """Return the gateway discovery record path for ``app_home``.

    Uses the leaf ``_DISCOVERY_RECORD_FILENAME`` constant rather than importing the
    discovery authority, so this stays callable from the settings model validator
    during ``control.config`` construction without closing an import cycle. The
    placement mirrors ``lifecycle.discovery.service_json_path``; a guard test keeps
    the two in sync.
    """
    return app_home / _DISCOVERY_RECORD_FILENAME


def derive_state_paths(app_home: Path) -> DesktopStatePaths:
    """Derive the explicit mutable-state layout from an explicit application home.

    This is the single authority for the desktop application-home layout. The
    seated paths mirror the operative ``a2a_home`` derivation (runtime logs under
    ``a2a_home/runtime``, the discovery ``service.json`` at the root) so the
    profile describes where state actually lands; the reserved paths fix the
    layout their future consumers will bind. ``app_home`` must be an absolute path
    so that no mutable path can resolve relative to the launch directory.

    Raises:
        DesktopProfileError: If ``app_home`` is not absolute.
    """
    if not app_home.is_absolute():
        raise DesktopProfileError(
            f"desktop application home must be an absolute path, got {app_home!r}; "
            "the desktop profile forbids launch-directory-relative state roots."
        )
    home = Path(os.path.normpath(app_home))
    state = home / "state"
    return DesktopStatePaths(
        app_home=home,
        database_path=state / "vaultspec.db",
        checkpoint_path=state / "checkpoints.db",
        logs_dir=home / "runtime",
        discovery_path=_discovery_path(home),
        workspaces_root=home / "workspaces",
        credentials_dir=home / "credentials",
        receipts_dir=home / "receipts",
        temp_homes_dir=home / "tmp" / "homes",
        snapshots_dir=home / "snapshots",
    )


def _capsule_asset_paths(capsule_root: Path) -> tuple[Path, Path]:
    """Return the (Node executable, ACP entry) paths beneath a capsule root.

    The provider factory owns the installed-runtime asset layout, so its path
    authorities are imported lazily here: the desktop package stays importable
    for the manifest contract without pulling the provider/langchain stack, and
    the asset layout has exactly one definition.
    """
    from ..providers.factory import _capsule_acp_entry, _capsule_node_executable

    return _capsule_node_executable(capsule_root), _capsule_acp_entry(capsule_root)


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
        """
        for directory in self.state.provisioned_directories:
            directory.mkdir(parents=True, exist_ok=True)
