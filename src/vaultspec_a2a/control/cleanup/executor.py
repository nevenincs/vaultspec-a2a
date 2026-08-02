"""Manifest-driven, independent execution of cross-store deletion cleanup.

The deletion saga captures a durable manifest of cleanup work; this module
turns that manifest into real store effects. It builds the manifest from a
thread and its artifacts, and executes each item against the store it targets -
the LangGraph checkpoint store or the workspace filesystem.

Two properties matter here and are enforced by construction:

- **Containment.** An artifact file is only ever a cleanup target when it
  resolves inside the thread's workspace root. Escaping paths (absolute paths,
  parent traversals, symlinks pointing outside) are refused at manifest build
  and re-checked before any unlink, so a delete can never remove a file the
  thread does not own.
- **Independence.** Every item is executed and recorded on its own. One item's
  failure is captured as that item's failure and never aborts, skips, or masks
  the items after it, so a stuck checkpoint delete cannot leave artifact files
  behind and a locked artifact cannot leave checkpoint state behind.
"""

from __future__ import annotations

import json
import logging
import pathlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeIs

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
    "resolve_contained_artifact_path",
]

logger = logging.getLogger(__name__)

_MAX_DETAIL_LENGTH = 200


def _is_json_object(value: object) -> TypeIs[dict[str, object]]:
    """Return whether a decoded JSON value is a string-keyed object."""
    # ``json.loads`` only constructs string-keyed object values; this helper is
    # called only on its decoded result after it has been erased to ``object``.
    return isinstance(value, dict)


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


def _workspace_root_from_thread(thread: Any) -> pathlib.Path | None:
    """Return the resolved, existing workspace root recorded on a thread.

    The root is read from the thread's own metadata so containment is judged
    against the checkout the thread declared, and only an existing directory is
    returned so a stale or missing root refuses every artifact rather than
    resolving relative paths against the process working directory.
    """
    metadata_json = getattr(thread, "thread_metadata", None)
    if not metadata_json:
        return None
    try:
        meta: object = json.loads(metadata_json)
    except (json.JSONDecodeError, TypeError):
        return None
    if not _is_json_object(meta):
        return None
    workspace_root_str = meta.get("workspace_root")
    if not workspace_root_str or not isinstance(workspace_root_str, str):
        return None
    workspace_root = pathlib.Path(workspace_root_str).resolve()
    if not workspace_root.is_dir():
        return None
    return workspace_root


def resolve_contained_artifact_path(
    workspace_root: pathlib.Path,
    path: str,
) -> pathlib.Path | None:
    """Resolve an artifact path against the root, or ``None`` if it escapes.

    Resolution happens before the containment check, so a symlink is judged by
    its target. An absolute path, a parent traversal, or a link pointing
    outside the root each resolve outside it and are refused.
    """
    try:
        target = (workspace_root / path).resolve()
    except (OSError, ValueError):
        return None
    if not target.is_relative_to(workspace_root):
        return None
    return target


def build_cleanup_manifest(
    thread: Any,
    artifacts: Sequence[Any],
    *,
    include_checkpoint: bool,
) -> list[CleanupItem]:
    """Capture the immutable cleanup manifest for a thread being deleted.

    The manifest lists the checkpoint (when a checkpoint store is available) and
    each contained artifact file. Escaping artifact paths are refused here and
    never enter the manifest, so the durable plan can only ever remove files the
    thread owns.
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
    workspace_root = _workspace_root_from_thread(thread)
    if workspace_root is None:
        return items
    for artifact in artifacts:
        resolved = resolve_contained_artifact_path(workspace_root, artifact.path)
        if resolved is None:
            continue
        items.append(
            CleanupItem(
                kind=CleanupKind.ARTIFACT_FILE,
                key=f"artifact:{artifact.id}",
                target=str(resolved),
                root=str(workspace_root),
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


def _execute_artifact_item(item: CleanupItem) -> CleanupItemResult:
    if item.root is None:
        return CleanupItemResult(
            item.key,
            CleanupItemState.FAILED,
            detail="artifact cleanup item carries no workspace root",
        )
    try:
        root = pathlib.Path(item.root).resolve()
        target = pathlib.Path(item.target).resolve()
        if not target.is_relative_to(root):
            return CleanupItemResult(
                item.key,
                CleanupItemState.FAILED,
                detail="artifact path escapes its workspace root",
            )
        # An already-removed file is a completed cleanup, not a failure: the
        # unlink is idempotent so a resumed pass converges rather than stalls.
        if target.is_file():
            target.unlink()
    except (OSError, ValueError) as exc:
        logger.warning("Artifact cleanup failed for %s", item.target, exc_info=True)
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
    return _execute_artifact_item(item)


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
