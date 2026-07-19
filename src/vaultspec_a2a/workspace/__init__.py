"""Manage Git worktrees and workspace environments.

:class:`vaultspec_a2a.workspace.git_manager.GitManager` performs Git worktree
operations. :class:`vaultspec_a2a.workspace.git_manager.MergeStrategy`
describes merge behavior.
:class:`vaultspec_a2a.workspace.git_manager.WorktreeInfo` represents a managed
worktree.

Helpers in :mod:`vaultspec_a2a.workspace.environment` resolve virtual
environments and command environments. :mod:`vaultspec_a2a.providers` uses
those helpers to prepare provider processes.
"""

from .environment import resolve_env_vars as resolve_env_vars
from .environment import resolve_venv as resolve_venv
from .git_manager import (
    GitManager as GitManager,
)
from .git_manager import (
    MergeStrategy as MergeStrategy,
)
from .git_manager import (
    WorktreeInfo as WorktreeInfo,
)

__all__ = [
    "GitManager",
    "MergeStrategy",
    "WorktreeInfo",
    "resolve_env_vars",
    "resolve_venv",
]
