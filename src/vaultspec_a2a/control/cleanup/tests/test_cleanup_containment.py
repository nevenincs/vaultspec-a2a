"""Workspace containment of manifest-driven artifact file removal.

Deletion removes artifact files from the caller-supplied workspace root, which
in practice is the user's real checkout. The only thing separating that from
deleting arbitrary files elsewhere on the host is a containment check, and a
safety predicate nobody executes is a predicate nobody can trust.

These drive the real manifest build and execution against real files in real
directories using the real ORM types - no mocks, no patched filesystem - and
assert on what survives on disk. The escape cases matter most: an absolute
path, a parent traversal, and a symlink pointing outside the root each resolve
outside the workspace, are refused at manifest build, and never enter the plan,
while removal still proceeds for legitimate siblings.
"""

from __future__ import annotations

import json
import pathlib
from contextlib import chdir
from typing import TYPE_CHECKING

import pytest

from ....control.cleanup import (
    build_cleanup_manifest,
    execute_cleanup_manifest,
    resolve_contained_artifact_path,
)
from ....database.models import ArtifactModel, ThreadModel

if TYPE_CHECKING:
    from ....control.repositories import CleanupItemResult


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


async def _run_cleanup(
    thread: ThreadModel, artifacts: list[ArtifactModel]
) -> list[CleanupItemResult]:
    """Build the manifest for a thread and execute every artifact cleanup item."""
    manifest = build_cleanup_manifest(thread, artifacts, include_checkpoint=False)
    recorded: list[CleanupItemResult] = []

    async def _advance(result: CleanupItemResult) -> None:
        recorded.append(result)

    await execute_cleanup_manifest(manifest, {}, checkpointer=None, advance=_advance)
    return recorded


@pytest.mark.asyncio
async def test_confined_artifact_file_is_removed(tmp_path: pathlib.Path) -> None:
    """A path inside the workspace root is removed."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "generated.txt"
    target.write_text("generated", encoding="utf-8")

    await _run_cleanup(_thread(workspace), [_artifact("generated.txt")])

    assert not target.exists()


@pytest.mark.asyncio
async def test_absolute_path_outside_the_workspace_is_refused(
    tmp_path: pathlib.Path,
) -> None:
    """An absolute artifact path outside the root must not be unlinked."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outsider = tmp_path / "outside.txt"
    outsider.write_text("precious", encoding="utf-8")

    await _run_cleanup(_thread(workspace), [_artifact(str(outsider))])

    assert outsider.read_text(encoding="utf-8") == "precious"


@pytest.mark.asyncio
async def test_a_relative_workspace_root_is_refused_rather_than_resolved(
    tmp_path: pathlib.Path,
) -> None:
    """A relative stored root must not be anchored to the serving process's cwd.

    Containment is judged against the checkout the thread declared. A relative
    root has no such checkout - it names a different directory for every process
    that reads it - so resolving one would let the gateway's own working
    directory decide which files count as inside the workspace.

    The test runs from a directory where that relative root DOES name a real
    workspace holding a real file, which is the only condition under which the
    old behaviour was destructive: resolve it and the file is contained and gets
    unlinked. The liveness assertion below is what keeps this honest - without
    it, a refusal for some unrelated reason would look identical.
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "generated.txt"
    target.write_text("precious", encoding="utf-8")
    thread = ThreadModel(
        id="t-cleanup", thread_metadata=json.dumps({"workspace_root": "workspace"})
    )

    with chdir(tmp_path):
        assert pathlib.Path("workspace").resolve() == workspace.resolve(), (
            "the trap must be live: the relative root has to name the real "
            "workspace from here, or this test proves nothing"
        )
        await _run_cleanup(thread, [_artifact("generated.txt")])

    assert target.read_text(encoding="utf-8") == "precious"


@pytest.mark.asyncio
async def test_parent_traversal_is_refused(tmp_path: pathlib.Path) -> None:
    """A ``..`` traversal escaping the root must not be unlinked."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outsider = tmp_path / "outside.txt"
    outsider.write_text("precious", encoding="utf-8")

    await _run_cleanup(_thread(workspace), [_artifact("../outside.txt")])

    assert outsider.read_text(encoding="utf-8") == "precious"


def test_symlink_escaping_the_workspace_is_refused(tmp_path: pathlib.Path) -> None:
    """A symlink inside the root resolving outside it is refused at build.

    Resolution happens before the containment check, so the link target is what
    is judged. On a host that forbids symlink creation the guarantee cannot be
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

    assert resolve_contained_artifact_path(workspace, "link.txt") is None
    assert outsider.read_text(encoding="utf-8") == "precious"


@pytest.mark.asyncio
async def test_one_escaping_artifact_does_not_abort_the_rest(
    tmp_path: pathlib.Path,
) -> None:
    """A refused escape must not stop legitimate siblings from being removed."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outsider = tmp_path / "outside.txt"
    outsider.write_text("precious", encoding="utf-8")
    survivor_target = workspace / "generated.txt"
    survivor_target.write_text("generated", encoding="utf-8")

    await _run_cleanup(
        _thread(workspace),
        [_artifact(str(outsider)), _artifact("generated.txt")],
    )

    assert outsider.read_text(encoding="utf-8") == "precious"
    assert not survivor_target.exists()


@pytest.mark.asyncio
async def test_absent_workspace_metadata_removes_nothing(
    tmp_path: pathlib.Path,
) -> None:
    """Without a workspace root there is no basis for containment, so nothing goes."""
    stray = tmp_path / "stray.txt"
    stray.write_text("precious", encoding="utf-8")

    await _run_cleanup(_thread(None), [_artifact(str(stray))])

    assert stray.read_text(encoding="utf-8") == "precious"


@pytest.mark.asyncio
async def test_directory_matching_an_artifact_path_is_not_removed(
    tmp_path: pathlib.Path,
) -> None:
    """Only regular files are unlinked; a directory of the same name survives."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    directory = workspace / "generated.txt"
    directory.mkdir()

    await _run_cleanup(_thread(workspace), [_artifact("generated.txt")])

    assert directory.is_dir()


@pytest.mark.asyncio
async def test_an_already_removed_file_is_a_completed_item(
    tmp_path: pathlib.Path,
) -> None:
    """Re-running cleanup on an already-removed file converges as done.

    Idempotent unlink is what lets a resumed or replayed deletion finish rather
    than stall on files a prior pass already removed.
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "generated.txt"
    target.write_text("generated", encoding="utf-8")

    thread = _thread(workspace)
    artifacts = [_artifact("generated.txt")]
    await _run_cleanup(thread, artifacts)
    assert not target.exists()

    second = await _run_cleanup(thread, artifacts)

    assert all(result.state.value == "done" for result in second), second
