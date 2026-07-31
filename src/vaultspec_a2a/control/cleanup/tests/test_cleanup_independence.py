"""One cleanup item's failure must not skip, abort, or mask the others.

Independent execution is what stops a cross-store deletion from silently
leaving one store behind: a stuck checkpoint delete cannot skip the artifact
files, and a failed artifact cannot skip the checkpoint. These drive the real
executor against real files and assert that every item is attempted and
recorded regardless of a sibling's failure, in either order.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ....control.cleanup import execute_cleanup_manifest
from ....control.repositories import (
    CleanupItem,
    CleanupItemResult,
    CleanupItemState,
)
from ....thread.enums import CleanupKind

if TYPE_CHECKING:
    import pathlib


def _artifact_item(target: pathlib.Path, root: pathlib.Path) -> CleanupItem:
    return CleanupItem(
        kind=CleanupKind.ARTIFACT_FILE,
        key="artifact:a1",
        target=str(target.resolve()),
        root=str(root.resolve()),
    )


def _failing_checkpoint_item() -> CleanupItem:
    # With no checkpoint store the checkpoint item fails deterministically,
    # exercising the per-item aggregation without patching a real store.
    return CleanupItem(kind=CleanupKind.CHECKPOINT, key="checkpoint", target="t1")


async def _run(manifest: list[CleanupItem]) -> dict[str, CleanupItemResult]:
    recorded: dict[str, CleanupItemResult] = {}

    async def _advance(result: CleanupItemResult) -> None:
        recorded[result.key] = result

    await execute_cleanup_manifest(manifest, {}, checkpointer=None, advance=_advance)
    return recorded


@pytest.mark.asyncio
async def test_an_earlier_failure_does_not_skip_a_later_item(
    tmp_path: pathlib.Path,
) -> None:
    """A failed checkpoint item must not stop the artifact item after it."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "generated.txt"
    target.write_text("generated", encoding="utf-8")

    recorded = await _run(
        [_failing_checkpoint_item(), _artifact_item(target, workspace)]
    )

    assert recorded["checkpoint"].state is CleanupItemState.FAILED
    assert recorded["artifact:a1"].state is CleanupItemState.DONE
    assert not target.exists()


@pytest.mark.asyncio
async def test_a_later_failure_does_not_undo_an_earlier_item(
    tmp_path: pathlib.Path,
) -> None:
    """A failed checkpoint item after a done artifact leaves the artifact done."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "generated.txt"
    target.write_text("generated", encoding="utf-8")

    recorded = await _run(
        [_artifact_item(target, workspace), _failing_checkpoint_item()]
    )

    assert recorded["artifact:a1"].state is CleanupItemState.DONE
    assert recorded["checkpoint"].state is CleanupItemState.FAILED
    assert not target.exists()


@pytest.mark.asyncio
async def test_the_report_lists_only_the_unfinished_items(
    tmp_path: pathlib.Path,
) -> None:
    """The run report surfaces exactly the items that did not reach done."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "generated.txt"
    target.write_text("generated", encoding="utf-8")

    recorded: dict[str, CleanupItemResult] = {}

    async def _advance(result: CleanupItemResult) -> None:
        recorded[result.key] = result

    report = await execute_cleanup_manifest(
        [_failing_checkpoint_item(), _artifact_item(target, workspace)],
        {},
        checkpointer=None,
        advance=_advance,
    )

    assert report.complete is False
    assert [result.key for result in report.outstanding] == ["checkpoint"]
