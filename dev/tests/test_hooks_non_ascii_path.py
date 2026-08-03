"""Hook installation into a repository whose path is not ASCII.

Git reports paths as UTF-8 on every platform, but a subprocess reading them in
text mode without an explicit encoding decodes with the host locale - cp1252 on a
stock Windows. The resulting path is mojibake that resolves nowhere, so the hook
lands in the wrong place or the install dies on a byte the code page leaves
undefined. Nothing about an ASCII checkout can reveal that, which is why these
tests drive a real repository under a non-ASCII directory name.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from dev.repo import hooks

if TYPE_CHECKING:
    from pathlib import Path

# Three-byte CJK, a combining accent, and an astral-plane character, all legal in
# a directory name on both NTFS and POSIX filesystems.
_NON_ASCII_DIR_NAMES = [
    pytest.param("プロジェクト", id="cjk"),
    pytest.param("dépôt-café", id="combining"),
    pytest.param("repo-\U0001f680", id="astral"),
]


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _init_repo(root: Path) -> None:
    root.mkdir(parents=True)
    _git(root, "init", "--initial-branch=main")
    _git(root, "config", "user.name", "Test User")
    _git(root, "config", "user.email", "test@example.com")
    (root / "README.md").write_text("root\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(root, "commit", "-m", "init")


@pytest.mark.parametrize("dir_name", _NON_ASCII_DIR_NAMES)
def test_repo_root_resolves_under_a_non_ascii_path(
    tmp_path: Path, dir_name: str
) -> None:
    """The resolved root must be the real directory, not a mojibake lookalike."""
    repo = tmp_path / dir_name
    _init_repo(repo)

    resolved = hooks._resolve_repo_root(repo)

    assert resolved.exists(), f"resolved a path that does not exist: {resolved}"
    assert resolved.samefile(repo)
    # The directory name survives intact rather than arriving re-encoded.
    assert resolved.name == dir_name


@pytest.mark.parametrize("dir_name", _NON_ASCII_DIR_NAMES)
def test_hook_installs_under_a_non_ascii_path(tmp_path: Path, dir_name: str) -> None:
    """The end-to-end install must place the hook inside the real repository."""
    repo = tmp_path / dir_name
    _init_repo(repo)

    hook_path = hooks.install_hook(repo_root=repo)

    assert hook_path == repo / ".git" / "hooks" / "pre-commit"
    assert hook_path.is_file()
    assert "Managed by the vaultspec-a2a development harness" in hook_path.read_text(
        encoding="utf-8"
    )
