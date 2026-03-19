"""Workspace management: git worktree lifecycle and environment resolution."""

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
