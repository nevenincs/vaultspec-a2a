"""Manifest-driven, independent execution of cross-store deletion cleanup.

The deletion saga captures a durable manifest of cleanup work; this module
turns that manifest into real store effects. It builds the manifest from a
thread, and executes each item against the store it targets - the LangGraph
checkpoint store or the authoring replay journals.

Every item is executed and recorded on its own. One item's failure is captured
as that item's failure and never aborts, skips, or masks the items after it, so
a stuck checkpoint delete cannot leave replay state behind and a replay store
that cannot be retired cannot leave checkpoint state behind.
"""

from __future__ import annotations

import logging
import os
import pathlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ...authoring._tool_calls import (
    retire_run_tool_calls,
    tool_call_journal_directories,
)
from ...thread.enums import CleanupKind
from ..repositories import (
    CleanupItem,
    CleanupItemResult,
    CleanupItemState,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence

__all__ = [
    "CleanupRunReport",
    "build_cleanup_manifest",
    "execute_cleanup_item",
    "execute_cleanup_manifest",
]

logger = logging.getLogger(__name__)

_MAX_DETAIL_LENGTH = 200

_AUTHORING_REPLAY_KEY_PREFIX = "authoring-replay:"


@dataclass(frozen=True, slots=True)
class CleanupRunReport:
    """The outstanding (not-done) results of one cleanup pass."""

    outstanding: tuple[CleanupItemResult, ...]

    @property
    def complete(self) -> bool:
        """Return whether every attempted item reached ``DONE``."""
        return not self.outstanding


def _short_detail(exc: BaseException) -> str:
    """Return a bounded diagnostic string for a cleanup failure."""
    detail = f"{type(exc).__name__}: {exc}"
    if len(detail) > _MAX_DETAIL_LENGTH:
        return detail[: _MAX_DETAIL_LENGTH - 1] + "…"
    return detail


def build_cleanup_manifest(
    thread: Any,
    *,
    include_checkpoint: bool,
) -> list[CleanupItem]:
    """Capture the immutable cleanup manifest for a thread being deleted.

    The manifest lists the checkpoint (when available) and run-owned replay
    state in the configured journal directories.
    """
    items: list[CleanupItem] = []
    if include_checkpoint:
        items.append(
            CleanupItem(
                kind=CleanupKind.CHECKPOINT,
                key="checkpoint",
                target=thread.id,
            )
        )
    for index, directory in enumerate(tool_call_journal_directories()):
        if os.path.lexists(directory):
            # Replay journals are recorded under the artifact-file kind; the key
            # prefix is what routes them to retirement at execution.
            items.append(
                CleanupItem(
                    kind=CleanupKind.ARTIFACT_FILE,
                    key=f"{_AUTHORING_REPLAY_KEY_PREFIX}{index}",
                    target=thread.id,
                    root=str(directory),
                )
            )
    return items


async def _execute_checkpoint_item(
    item: CleanupItem,
    checkpointer: Any | None,
) -> CleanupItemResult:
    if checkpointer is None:
        return CleanupItemResult(
            item.key,
            CleanupItemState.FAILED,
            detail="no checkpoint store available",
        )
    try:
        await checkpointer.adelete_thread(item.target)
    except Exception as exc:
        # A checkpoint-store failure is captured as this item's failure so the
        # pass can advance the ledger and attempt the remaining items.
        logger.warning(
            "Checkpoint cleanup failed for thread %s", item.target, exc_info=True
        )
        return CleanupItemResult(
            item.key, CleanupItemState.FAILED, detail=_short_detail(exc)
        )
    return CleanupItemResult(item.key, CleanupItemState.DONE)


async def _execute_authoring_replay_item(item: CleanupItem) -> CleanupItemResult:
    try:
        if item.root is None:
            raise ValueError("authoring replay cleanup has no store root")
        await retire_run_tool_calls(item.target, directory=pathlib.Path(item.root))
    except Exception as exc:
        logger.warning(
            "Authoring replay cleanup failed for thread %s",
            item.target,
            exc_info=True,
        )
        return CleanupItemResult(
            item.key, CleanupItemState.FAILED, detail=_short_detail(exc)
        )
    return CleanupItemResult(item.key, CleanupItemState.DONE)


async def execute_cleanup_item(
    item: CleanupItem,
    *,
    checkpointer: Any | None,
) -> CleanupItemResult:
    """Execute one cleanup item against its store, never raising.

    Returns the item's terminal result. A failure is captured in the result
    rather than raised, so a caller can advance the durable ledger and move on
    to the remaining items.
    """
    if item.kind is CleanupKind.CHECKPOINT:
        return await _execute_checkpoint_item(item, checkpointer)
    if item.key.startswith(_AUTHORING_REPLAY_KEY_PREFIX):
        return await _execute_authoring_replay_item(item)
    # A durable manifest can outlive the builder that wrote it. An item with no
    # store here fails on its own, so the saga's attempt ceiling retires it
    # instead of the pass raising or acting on a target it cannot vouch for.
    return CleanupItemResult(
        item.key,
        CleanupItemState.FAILED,
        detail=f"no executor for cleanup kind {item.kind.value}",
    )


async def execute_cleanup_manifest(
    manifest: Sequence[CleanupItem],
    prior_results: Mapping[str, CleanupItemResult],
    *,
    checkpointer: Any | None,
    advance: Callable[[CleanupItemResult], Awaitable[object]],
) -> CleanupRunReport:
    """Execute every not-yet-done manifest item independently.

    Items already recorded ``DONE`` are skipped so a resumed pass does no
    redundant work. Every other item is executed and its result handed to
    ``advance`` for durable recording before the next item is attempted, so one
    item's failure can neither abort the pass nor skip a later item. The report
    lists the items that did not reach ``DONE`` in this pass.
    """
    outstanding: list[CleanupItemResult] = []
    for item in manifest:
        prior = prior_results.get(item.key)
        if prior is not None and prior.state is CleanupItemState.DONE:
            continue
        result = await execute_cleanup_item(item, checkpointer=checkpointer)
        await advance(result)
        if result.state is not CleanupItemState.DONE:
            outstanding.append(result)
    return CleanupRunReport(outstanding=tuple(outstanding))
