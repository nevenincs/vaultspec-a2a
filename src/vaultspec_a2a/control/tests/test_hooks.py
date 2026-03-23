"""Real-behavior tests for the repo-managed Git hook installer."""

from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING

from vaultspec_a2a.control import hooks

if TYPE_CHECKING:
    from pathlib import Path


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def test_install_hook_writes_portable_shim_into_common_hooks_dir(
    tmp_path: Path,
) -> None:
    """A linked worktree should install the hook into the shared Git hooks dir."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "--initial-branch=main")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "README.md").write_text("root\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "init")

    worktree = tmp_path / "repo-worktree"
    _git(repo, "worktree", "add", str(worktree))

    hook_path = hooks.install_hook(repo_root=worktree)

    assert hook_path == repo / ".git" / "hooks" / "pre-commit"
    text = hook_path.read_text(encoding="utf-8")
    assert "Managed by vaultspec_a2a.control.hooks" in text
    assert 'ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"' in text
    assert 'export UV_CACHE_DIR="${UV_CACHE_DIR:-$ROOT/.uv-cache}"' in text
    assert 'export PREK_HOME="${PREK_HOME:-$ROOT/.prek-home}"' in text
    assert 'exec uv run --project "$ROOT" --group dev --no-sync --frozen \\' in text
    assert '--hook-type=pre-commit -- "$@"' in text
    assert ".venv\\Scripts\\prek.exe" not in text
    assert os.access(hook_path, os.X_OK)


def test_install_hook_refuses_to_replace_unmanaged_hook_without_force(
    tmp_path: Path,
) -> None:
    """Manual hook files are preserved unless replacement is explicit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "--initial-branch=main")
    hook_dir = repo / ".git" / "hooks"
    hook_dir.mkdir(parents=True, exist_ok=True)
    hook_path = hook_dir / "pre-commit"
    hook_path.write_text("#!/bin/sh\necho custom\n", encoding="utf-8")

    try:
        hooks.install_hook(repo_root=repo)
    except RuntimeError as exc:
        assert "refusing to overwrite unmanaged hook" in str(exc)
    else:
        raise AssertionError("expected unmanaged hook overwrite to be refused")
