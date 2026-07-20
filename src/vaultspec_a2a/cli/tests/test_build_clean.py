"""Real-filesystem tests for build artifact cleanup."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from vaultspec_a2a.cli.build_clean import _remove_directory, clean_build_artifacts

if TYPE_CHECKING:
    from pathlib import Path


def test_clean_build_artifacts_removes_only_declared_generated_directories(
    tmp_path: Path,
) -> None:
    generated = (
        tmp_path / "dist",
        tmp_path / "docs" / "_build",
        tmp_path / "src" / "package" / "__pycache__",
        tmp_path / "src" / "package.egg-info",
        tmp_path / "docs" / "extension" / "__pycache__",
    )
    for directory in generated:
        directory.mkdir(parents=True)
        (directory / "artifact").write_text("generated", encoding="utf-8")
    retained = tmp_path / "src" / "package" / "module.py"
    retained.parent.mkdir(parents=True, exist_ok=True)
    retained.write_text("VALUE = 1\n", encoding="utf-8")

    removed = clean_build_artifacts(tmp_path)

    assert set(removed) == {directory.relative_to(tmp_path) for directory in generated}
    assert all(not directory.exists() for directory in generated)
    assert retained.read_text(encoding="utf-8") == "VALUE = 1\n"


def test_remove_directory_refuses_target_outside_repository(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    outside = tmp_path / "outside"
    repository.mkdir()
    outside.mkdir()

    with pytest.raises(ValueError, match="outside repository"):
        _remove_directory(repository, outside)

    assert outside.is_dir()
