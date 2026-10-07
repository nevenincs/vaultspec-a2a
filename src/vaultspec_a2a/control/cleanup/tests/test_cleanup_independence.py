"""One cleanup item's failure must not skip, abort, or mask the others.

Independent execution is what stops a cross-store deletion from silently
leaving one store behind: a stuck checkpoint delete cannot skip the replay
journals, and a replay journal that cannot be retired cannot skip the
checkpoint. These drive the real executor against a real replay journal, using
the manifest the production builder captures, and assert that every item is
attempted and recorded regardless of a sibling's failure, in either order.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ....authoring._tool_calls import ToolCallJournal, tool_call_journal_path
from ....control.cleanup import (
    CleanupRunReport,
    build_cleanup_manifest,
    execute_cleanup_manifest,
)
from ....control.deletion_saga import (
    CleanupItem,
    CleanupItemResult,
    CleanupItemState,
)
from ....database import ThreadModel
from ....testing import settings_override
from ....tests._write_authority import make_test_thread_authority_columns
from ....thread.enums import CleanupKind

if TYPE_CHECKING:
    import pathlib

_RUN_ID = "t-independence"


async def _build(refs: dict[str, str | None]) -> tuple[dict[str, str | None], str]:
    return {}, "idk:retained"


async def _captured_items() -> tuple[ToolCallJournal, CleanupItem, CleanupItem]:
    """Seed a real replay journal and capture the items its deletion would plan.

    The manifest comes from the production builder, so the replay item is the
    one a saga would really record rather than one shaped by hand.
    """
    journal = ToolCallJournal(
        tool_call_journal_path(_RUN_ID, "writer"), _RUN_ID, "writer"
    )
    await journal.prepare("call-1", "input", _build)
    thread = ThreadModel(**make_test_thread_authority_columns(), id=_RUN_ID)
    checkpoint, replay = build_cleanup_manifest(thread, include_checkpoint=True)
    return journal, checkpoint, replay


async def _assert_replay_retired(journal: ToolCallJournal) -> None:
    with pytest.raises(ValueError, match="retired"):
        await journal.prepare("call-1", "input", _build)


async def _run(
    manifest: list[CleanupItem],
) -> tuple[CleanupRunReport, dict[str, CleanupItemResult]]:
    recorded: dict[str, CleanupItemResult] = {}

    async def _advance(result: CleanupItemResult) -> None:
        recorded[result.key] = result

    # With no checkpoint store the checkpoint item fails deterministically,
    # exercising the per-item aggregation without patching a real store.
    report = await execute_cleanup_manifest(
        manifest, {}, checkpointer=None, advance=_advance
    )
    return report, recorded


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure_first",
    [True, False],
    ids=["failure-does-not-skip-a-later-item", "failure-does-not-undo-an-earlier-item"],
)
async def test_a_failed_item_leaves_its_neighbour_done(
    tmp_path: pathlib.Path, failure_first: bool
) -> None:
    """A failed checkpoint item neither skips nor undoes the replay item beside it."""
    with settings_override(a2a_home=tmp_path / "state", workspace_root=None):
        journal, checkpoint, replay = await _captured_items()
        order = [checkpoint, replay] if failure_first else [replay, checkpoint]

        _report, recorded = await _run(order)

        assert recorded[checkpoint.key].state is CleanupItemState.FAILED
        assert recorded[replay.key].state is CleanupItemState.DONE
        await _assert_replay_retired(journal)


@pytest.mark.asyncio
async def test_the_report_lists_only_the_unfinished_items(
    tmp_path: pathlib.Path,
) -> None:
    """The run report surfaces exactly the items that did not reach done."""
    with settings_override(a2a_home=tmp_path / "state", workspace_root=None):
        _journal, checkpoint, replay = await _captured_items()

        report, _recorded = await _run([checkpoint, replay])

    assert report.complete is False
    assert [result.key for result in report.outstanding] == [checkpoint.key]


@pytest.mark.asyncio
async def test_an_item_no_builder_emits_fails_alone_and_touches_nothing(
    tmp_path: pathlib.Path,
) -> None:
    """A manifest item with no executor is refused without acting on its target."""
    stray = tmp_path / "generated.txt"
    stray.write_text("precious", encoding="utf-8")
    unsupported = CleanupItem(
        kind=CleanupKind.ARTIFACT_FILE,
        key="artifact:a1",
        target=str(stray),
        root=str(tmp_path),
    )
    with settings_override(a2a_home=tmp_path / "state", workspace_root=None):
        journal, _checkpoint, replay = await _captured_items()

        report, recorded = await _run([unsupported, replay])

        assert recorded[unsupported.key].state is CleanupItemState.FAILED
        assert recorded[replay.key].state is CleanupItemState.DONE
        await _assert_replay_retired(journal)

    assert [result.key for result in report.outstanding] == [unsupported.key]
    assert stray.read_text(encoding="utf-8") == "precious"
