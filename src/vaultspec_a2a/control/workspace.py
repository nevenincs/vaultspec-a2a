"""Profile workspace authority shared by admission and execution boundaries."""

from __future__ import annotations

import os
from pathlib import Path

from ..ipc.schemas import canonical_project_root
from .config import settings
from .state_layout import state_layout

__all__ = [
    "WorkspaceUnavailableError",
    "canonical_workspace_root",
    "configured_workspace_boundary",
    "require_admitted_workspace_root",
]


class WorkspaceUnavailableError(ValueError):
    """A run's directory is unavailable, independently of profile authority."""


def canonical_workspace_root(value: str | Path) -> Path:
    """Normalize aliases for authority comparisons, preserving absolute shares.

    The minted spelling keeps any extended-length prefix ``realpath`` leaves on
    it, because durable selectors are derived from that spelling; authority is
    compared without it. The comparison form must still be absolute: a prefixed
    namespace that is neither a drive nor a share would otherwise reduce to a
    path relative to this process's working directory.
    """
    canonical = canonical_project_root(value)
    if os.name == "nt" and canonical.startswith("\\\\?\\"):
        # Extended UNC paths must retain their absolute share authority.
        canonical = (
            "\\\\" + canonical[8:]
            if canonical[4:8].upper() == "UNC\\"
            else canonical[4:]
        )
    root = Path(canonical)
    if not root.is_absolute():
        raise ValueError(
            f"workspace_root does not reduce to an absolute path: {value!r}"
        )
    return root


def configured_workspace_boundary() -> Path | None:
    """Return the trusted profile boundary, refusing redirected desktop trees."""
    if settings.desktop_app_home is not None:
        home = canonical_workspace_root(settings.desktop_app_home)
        expected = state_layout(home).workspaces_root
        boundary = canonical_workspace_root(expected)
        if boundary != expected:
            raise ValueError(
                "configured workspace root redirects outside its desktop tree"
            )
        return boundary
    if settings.workspace_root is None:
        return None
    return canonical_workspace_root(settings.workspace_root)


def require_admitted_workspace_root(value: str | Path) -> Path:
    """Return an existing canonical directory within the profile's authority.

    Desktop attach authority covers only the lifecycle-derived workspace tree.
    Configured services use their managed root; unconfigured development keeps
    caller-selected directories. Resolve aliases before comparing either root.
    """
    minted = Path(canonical_project_root(value))
    canonical = canonical_workspace_root(minted)
    try:
        is_directory = canonical.is_dir()
    except OSError:
        is_directory = False
    if not is_directory:
        raise WorkspaceUnavailableError(
            f"workspace_root is not an existing directory: {value!r}"
        )
    boundary = configured_workspace_boundary()
    if boundary is not None and not canonical.is_relative_to(boundary):
        raise ValueError("workspace_root must be within the configured workspace root")
    # Preserve the IPC spelling so existing durable workspace selectors remain valid.
    return minted
