"""Manage workspace environments and shared workspace concurrency.

Helpers in :mod:`vaultspec_a2a.workspace.environment` resolve virtual
environments and command environments. :mod:`vaultspec_a2a.providers` uses
those helpers to prepare provider processes.
:data:`vaultspec_a2a.workspace.concurrency.git_workspace_mutex` serializes
repository-wide operations across every subsystem that writes the working tree.
"""

from .concurrency import git_workspace_mutex as git_workspace_mutex
from .environment import resolve_env_vars as resolve_env_vars
from .environment import resolve_venv as resolve_venv

__all__ = [
    "git_workspace_mutex",
    "resolve_env_vars",
    "resolve_venv",
]
