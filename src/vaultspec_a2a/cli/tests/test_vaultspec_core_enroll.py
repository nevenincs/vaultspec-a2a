"""Real-repository tests for safe Vaultspec Core enrollment."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest

from vaultspec_a2a.cli.core_enroll import (
    _assert_tracked_projection,
    _require_clean_owned_paths,
    _seed_runtime_without_overwrite,
)

if TYPE_CHECKING:
    from pathlib import Path


def _git(root: Path, *args: str) -> None:
    subprocess.run(("git", *args), cwd=root, check=True, capture_output=True, text=True)


def _repository(root: Path) -> None:
    root.mkdir()
    _git(root, "init", "--quiet")
    _git(root, "config", "user.email", "acceptance@example.invalid")
    _git(root, "config", "user.name", "Acceptance Test")
    (root / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    _git(root, "add", ".gitignore")
    _git(root, "commit", "--quiet", "-m", "seed")


def test_enrollment_rejects_untracked_owned_file_without_mutation(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repo"
    _repository(repository)
    protected = repository / ".mcp.json"
    expected = b'{"user":"preserve"}\n'
    protected.write_bytes(expected)

    with pytest.raises(SystemExit, match=r"\?\? \.mcp\.json"):
        _require_clean_owned_paths(repository)

    assert protected.read_bytes() == expected


def test_projection_comparison_rejects_tracked_byte_drift(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    staged = tmp_path / "staged"
    _repository(repository)
    staged.mkdir()
    (staged / ".gitignore").write_text("dist/\n", encoding="utf-8")

    with pytest.raises(SystemExit, match=r"\.gitignore"):
        _assert_tracked_projection(repository, staged)

    assert (repository / ".gitignore").read_text(encoding="utf-8") == ".venv/\n"


def test_runtime_seed_refuses_existing_destination_without_mutation(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repo"
    staged = tmp_path / "staged"
    destination = repository / ".vaultspec" / "providers.json"
    source = staged / ".vaultspec" / "providers.json"
    destination.parent.mkdir(parents=True)
    source.parent.mkdir(parents=True)
    destination.write_bytes(b'{"owner":"user"}\n')
    source.write_bytes(b'{"owner":"core"}\n')

    with pytest.raises(SystemExit, match="concurrently created runtime state"):
        _seed_runtime_without_overwrite(repository, staged)

    assert destination.read_bytes() == b'{"owner":"user"}\n'
