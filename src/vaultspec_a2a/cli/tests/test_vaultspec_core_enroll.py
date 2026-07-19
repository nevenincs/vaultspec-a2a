"""Real-repository tests for safe Vaultspec Core enrollment."""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from vaultspec_a2a.cli.core_enroll import (
    _assert_tracked_projection,
    _require_clean_owned_paths,
    _seed_runtime_without_overwrite,
)

if TYPE_CHECKING:
    from pathlib import Path


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", *args), cwd=root, check=True, capture_output=True, text=True
    )


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


def test_main_adopts_real_core_projection_and_converges_twice(tmp_path: Path) -> None:
    source = tmp_path / "source"
    consumer = tmp_path / "consumer"
    _repository(source)
    (source / "pyproject.toml").write_text(
        """[project]
name = "core-enrollment-acceptance"
version = "0.0.0"

[dependency-groups]
dev = ["vaultspec-core>=0.1.48,<0.2"]
""",
        encoding="utf-8",
    )
    vault_record = source / ".vault" / "adr" / "decision.md"
    vault_record.parent.mkdir(parents=True)
    vault_record.write_text("# Acceptance decision\n", encoding="utf-8")
    prek = source / "prek.toml"
    prek.write_text("repos = []\n", encoding="utf-8")
    subprocess.run(
        (
            sys.executable,
            "-m",
            "vaultspec_core",
            "install",
            "all",
            "--target",
            str(source),
            "--mode",
            "dev",
            "--force",
            "--no-hints",
        ),
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        (sys.executable, "-m", "vaultspec_a2a.cli.core_enroll"),
        cwd=source,
        check=True,
        capture_output=True,
        text=True,
    )
    for relative in (
        ".vaultspec/providers.json",
        ".vaultspec/mcp-ownership.json",
        ".mcp.json",
        ".mcp.json.lock",
        ".agents/mcp_config.json",
        ".agents/mcp_config.json.lock",
        ".codex/config.toml",
        ".codex/config.toml.lock",
        ".gemini/settings.json",
    ):
        path = source / relative
        if path.is_file():
            path.unlink()
    _git(source, "add", "-A")
    _git(source, "commit", "--quiet", "-m", "track framework projection")
    _git(tmp_path, "clone", "--quiet", "--no-hardlinks", str(source), str(consumer))
    expected_prek = (consumer / "prek.toml").read_bytes()

    for _ in range(2):
        subprocess.run(
            (sys.executable, "-m", "vaultspec_a2a.cli.core_enroll"),
            cwd=consumer,
            check=True,
            capture_output=True,
            text=True,
        )
        assert _git(consumer, "diff", "--exit-code").returncode == 0
        assert (consumer / "prek.toml").read_bytes() == expected_prek

    assert (consumer / ".vaultspec" / "providers.json").is_file()
