"""Dual-mode environment resolution for agent workspaces.

Supports both flat-hierarchy and worktree-based layouts (ADR-001 §2).
In flat mode, ``.venv`` is expected next to the workspace root. In
worktree mode, ``.venv`` may live in the container folder (parent of
the worktrees directory) or in the main repository root.
"""

import os

from pathlib import Path


__all__ = [
    "resolve_env_vars",
    "resolve_venv",
]


def resolve_venv(workspace_path: Path) -> Path | None:
    """Locate the nearest Python virtual environment for *workspace_path*.

    Search order:
    1. ``workspace_path / .venv`` (flat hierarchy)
    2. ``workspace_path.parent / .venv`` (container folder for worktrees)
    3. Walk up parents looking for a ``.venv`` alongside a ``.git`` dir
       (main repository root)

    Returns ``None`` if no venv is found.
    """
    # 1. Local .venv (flat mode)
    candidate = workspace_path / ".venv"
    if candidate.is_dir():
        return candidate

    # 2. Container folder (one level up from worktree)
    parent_candidate = workspace_path.parent / ".venv"
    if parent_candidate.is_dir():
        return parent_candidate

    # 3. Walk up to find main repo root (.git dir co-located with .venv)
    current = workspace_path.parent
    for _ in range(10):  # bounded to prevent infinite traversal
        if (current / ".git").exists() and (current / ".venv").is_dir():
            return current / ".venv"
        parent = current.parent
        if parent == current:
            break  # filesystem root
        current = parent

    return None


def resolve_env_vars(workspace_path: Path) -> dict[str, str]:
    """Build an environment dict for an agent running at *workspace_path*.

    Inherits the current process environment, then overlays:
    - ``VIRTUAL_ENV``: points to the resolved venv
    - ``PATH``: prepends the venv's ``Scripts`` (Windows) or ``bin``
      directory
    - ``CWD``: set to *workspace_path* for clarity

    ADR-001 §5: credential injection (``CLAUDE_CODE_OAUTH_TOKEN`` etc.)
    is handled by the provider layer, never by the workspace module.
    """
    env = dict(os.environ)
    env["CWD"] = str(workspace_path)

    venv = resolve_venv(workspace_path)
    if venv is not None:
        env["VIRTUAL_ENV"] = str(venv)

        # Windows uses Scripts/, Unix uses bin/
        scripts_dir = venv / "Scripts"
        if not scripts_dir.is_dir():
            scripts_dir = venv / "bin"

        current_path = env.get("PATH", "")
        env["PATH"] = f"{scripts_dir}{os.pathsep}{current_path}"

    return env
