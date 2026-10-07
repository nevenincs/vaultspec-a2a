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
capsule root, validates both fail-closed, and carries the application home's
:class:`~vaultspec_a2a.control.state_layout.StateLayout`.
:func:`derive_state_paths` adds the desktop profile's refusal of a relative
application home to that one layout; the desktop settings profile delegates its
mutable path derivation to it rather than duplicating the layout.

The capsule root is validated against the installed-runtime asset layout owned by
the provider factory (the bundled Node.js executable and the ACP adapter entry).
That installed layout is the runtime-asset directory the dashboard bundles next
to the frozen gateway binary; the factory constants are its single authority, so
this module reuses them rather than restating asset paths.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from ..control.state_layout import StateLayout, seal_state_home, state_layout
from ._platform_acl import harden_credential_path, path_is_link_like

__all__ = [
    "DesktopProfile",
    "DesktopProfileError",
    "derive_state_paths",
    "ensure_private_state",
    "provisioned_directories",
]


class DesktopProfileError(ValueError):
    """A desktop profile root or asset failed fail-closed validation.

    The message names the offending path and the remediation so an operator can
    correct the installation. This is raised for a non-absolute root, roots that
    are not distinct, an unwritable or uncreatable application home, or a capsule
    root that is missing or lacks its bundled runtime assets.
    """


def derive_state_paths(app_home: Path) -> StateLayout:
    """Derive the mutable-state layout from an explicit application home.

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
    return state_layout(app_home)


def provisioned_directories(state: StateLayout) -> tuple[Path, ...]:
    """Return the directories :meth:`DesktopProfile.ensure` creates and restricts.

    These are the home, the store directory, the runtime log directory and the
    workspace tree. ``discovery_path`` is a file written by the discovery
    authority and its parent is the home. The credential and temporary-home
    directories are created by the writers that own them, and the receipt and
    snapshot directories have no writer, so ``ensure`` never seeds them empty.
    """
    return (
        state.home,
        state.database_path.parent,
        state.checkpoint_path.parent,
        state.logs_dir,
        state.workspaces_root,
    )


def _capsule_asset_paths(capsule_root: Path) -> tuple[Path, Path, Path]:
    """Return the Node, ACP adapter, and Claude CLI paths beneath a capsule root.

    The provider factory owns the installed-runtime asset layout, so its path
    authorities are imported lazily here: the desktop package stays importable
    for the manifest contract without pulling the provider/langchain stack, and
    the asset layout has exactly one definition.
    """
    from ..providers._factory_commands import (
        capsule_acp_entry,
        capsule_claude_executable,
        capsule_node_executable,
    )

    return (
        capsule_node_executable(capsule_root),
        capsule_acp_entry(capsule_root),
        capsule_claude_executable(capsule_root),
    )


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
    node_executable, acp_entry, claude_executable = _capsule_asset_paths(root)
    for asset, description in (
        (node_executable, "bundled Node.js runtime executable"),
        (acp_entry, "bundled ACP adapter entry point"),
        (claude_executable, "bundled Claude CLI executable"),
    ):
        if not asset.is_file():
            raise DesktopProfileError(
                f"desktop capsule root {root} is missing its {description}: {asset}. "
                "Install or repair the desktop capsule before arming the profile."
            )
        if not asset.resolve().is_relative_to(root.resolve()):
            raise DesktopProfileError(
                f"desktop capsule {description} escapes its assets root: {asset}. "
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


def _restrict_state_path(
    path: Path, *, directory: bool, ephemeral: bool = False
) -> None:
    """Refuse aliases before changing permissions on sensitive state."""
    try:
        if path_is_link_like(path):
            raise OSError("linked state paths are not private")
        if directory:
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
        else:
            try:
                info = path.stat(follow_symlinks=False)
            except FileNotFoundError:
                return
            if ephemeral and stat.S_ISREG(info.st_mode) and info.st_nlink == 0:
                return
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise OSError("state files must be regular files without hard links")
        try:
            harden_credential_path(path)
        except FileNotFoundError:
            if not ephemeral:
                raise
            # SQLite removes side files when its last connection closes. A
            # replacement inherits privacy from the already restricted parent.
            return
    except OSError as exc:
        raise DesktopProfileError(
            f"cannot protect desktop state path {path}: {exc}. "
            "Choose an application home on a filesystem supporting owner-only "
            "access and remove linked state paths before starting the desktop."
        ) from exc


def ensure_private_state(state: StateLayout) -> None:
    """Fail closed before opening desktop databases or their SQLite side files.

    The private parent protects future side files; existing files also need
    hardening because Windows files can retain explicit, permissive ACLs.
    """
    # Refuse a linked home before the seal can write through it.
    if path_is_link_like(state.home):
        raise DesktopProfileError(
            f"desktop application home is linked: {state.home}; "
            "choose a real directory with owner-only access."
        )
    try:
        seal_state_home(state.home)
    except OSError as exc:
        raise DesktopProfileError(
            f"cannot prepare desktop application home {state.home}: {exc}; "
            "choose a writable filesystem supporting owner-only access."
        ) from exc
    for directory in dict.fromkeys(provisioned_directories(state)):
        _restrict_state_path(directory, directory=True)
    for database in (state.database_path, state.checkpoint_path):
        for suffix in ("", "-wal", "-shm", "-journal"):
            _restrict_state_path(
                Path(f"{database}{suffix}"), directory=False, ephemeral=bool(suffix)
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
    state: StateLayout

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
        home = state.home
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

        Idempotent: existing state is rechecked and restricted. Only the
        :func:`provisioned_directories` are created; every other directory is left
        to the writer that owns it so ``ensure`` never seeds dead empty state.
        Called once the profile is armed and about to seat live state.

        Each directory is restricted to its owner. The credential files one level
        over already get this treatment, and the state directory holds the
        databases: thread content, the permission-decision log, and the whole of
        every agent conversation in the checkpoint store. Restricting the
        DIRECTORY rather than the database files is deliberate — SQLite writes
        ``-wal`` and ``-shm`` beside each database, and the write-ahead log holds
        recently committed rows, so hardening the files alone would leave the most
        recent data readable.

        Raises:
            DesktopProfileError: If owner-only access cannot be applied and
                verified, or a sensitive state path is linked.
        """
        ensure_private_state(self.state)
