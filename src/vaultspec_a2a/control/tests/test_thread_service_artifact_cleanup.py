"""Workspace containment of hard-delete artifact file removal.

Hard thread delete removes artifact files from the caller-supplied workspace
root, which in practice is the user's real checkout.  The only thing separating
that from deleting arbitrary files elsewhere on the host is a containment check,
and a safety predicate nobody executes is a predicate nobody can trust.

These tests drive the production removal against real files in real directories
using the real ORM types - no mocks, no patched filesystem - and assert on what
survives on disk.  The escape cases matter most: an absolute path, a parent
traversal, and a symlink pointing outside the root each resolve outside the
workspace and must be refused while the removal still proceeds for legitimate
siblings.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from vaultspec_a2a.control.thread_service import _cleanup_artifact_files
from vaultspec_a2a.database.models import ArtifactModel, ThreadModel

if TYPE_CHECKING:
    import pathlib


def _thread(workspace_root: pathlib.Path | None) -> ThreadModel:
    """Return a real thread row carrying the workspace metadata under test."""
    metadata: dict[str, object] = {}
    if workspace_root is not None:
        metadata["workspace_root"] = str(workspace_root)
    return ThreadModel(id="t-cleanup", thread_metadata=json.dumps(metadata))


def _artifact(path: str) -> ArtifactModel:
    """Return a real artifact row naming ``path`` relative to the workspace."""
    return ArtifactModel(
        id=f"a-{abs(hash(path))}", thread_id="t-cleanup", type="file", path=path
    )


def test_confined_artifact_file_is_removed(tmp_path: pathlib.Path) -> None:
    """A path inside the workspace root is removed."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "generated.txt"
    target.write_text("generated", encoding="utf-8")

    _cleanup_artifact_files(_thread(workspace), [_artifact("generated.txt")])

    assert not target.exists()


def test_absolute_path_outside_the_workspace_is_refused(tmp_path: pathlib.Path) -> None:
    """An absolute artifact path outside the root must not be unlinked."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outsider = tmp_path / "outside.txt"
    outsider.write_text("precious", encoding="utf-8")

    _cleanup_artifact_files(_thread(workspace), [_artifact(str(outsider))])

    assert outsider.read_text(encoding="utf-8") == "precious"


def test_parent_traversal_is_refused(tmp_path: pathlib.Path) -> None:
    """A ``..`` traversal escaping the root must not be unlinked."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outsider = tmp_path / "outside.txt"
    outsider.write_text("precious", encoding="utf-8")

    _cleanup_artifact_files(_thread(workspace), [_artifact("../outside.txt")])

    assert outsider.read_text(encoding="utf-8") == "precious"


def test_symlink_escaping_the_workspace_is_refused(tmp_path: pathlib.Path) -> None:
    """A symlink inside the root resolving outside it must not be unlinked.

    Resolution happens before the containment check, so the link target is what
    is judged.  On a host that forbids symlink creation the guarantee cannot be
    exercised, and the test skips rather than passing vacuously.
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outsider = tmp_path / "outside.txt"
    outsider.write_text("precious", encoding="utf-8")
    link = workspace / "link.txt"
    try:
        link.symlink_to(outsider)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"host cannot create symlinks: {exc}")

    _cleanup_artifact_files(_thread(workspace), [_artifact("link.txt")])

    assert outsider.read_text(encoding="utf-8") == "precious"


def test_one_escaping_artifact_does_not_abort_the_rest(tmp_path: pathlib.Path) -> None:
    """A refused escape must not stop legitimate siblings from being removed."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outsider = tmp_path / "outside.txt"
    outsider.write_text("precious", encoding="utf-8")
    survivor_target = workspace / "generated.txt"
    survivor_target.write_text("generated", encoding="utf-8")

    _cleanup_artifact_files(
        _thread(workspace),
        [_artifact(str(outsider)), _artifact("generated.txt")],
    )

    assert outsider.read_text(encoding="utf-8") == "precious"
    assert not survivor_target.exists()


def test_absent_workspace_metadata_removes_nothing(tmp_path: pathlib.Path) -> None:
    """Without a workspace root there is no basis for containment, so nothing goes."""
    stray = tmp_path / "stray.txt"
    stray.write_text("precious", encoding="utf-8")

    _cleanup_artifact_files(_thread(None), [_artifact(str(stray))])

    assert stray.read_text(encoding="utf-8") == "precious"


def test_directory_matching_an_artifact_path_is_not_removed(
    tmp_path: pathlib.Path,
) -> None:
    """Only regular files are unlinked; a directory of the same name survives."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    directory = workspace / "generated.txt"
    directory.mkdir()

    _cleanup_artifact_files(_thread(workspace), [_artifact("generated.txt")])

    assert directory.is_dir()
