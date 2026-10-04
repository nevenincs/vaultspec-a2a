"""Blackboard content mounting.

Mounting is split in two, because the two halves have opposite persistence
needs. The vault index is a handle list the run must keep, so the graph's mount
node refreshes it into state before each worker. The mounted document text is
large and derivable, so it is expanded by the worker itself at invocation and
never enters state - a state channel is checkpointed at every superstep, which
would persist up to the whole mount budget per worker turn for the life of the
run, and would still be missing when a resumed worker re-executes.

This module also owns the canonical ``build_initial_vault_index`` scan so the
same glob logic seeds the index at compile time and refreshes it on every mount
pass. Callers seeding an index import it from here; the ``graph`` package's lazy
entry point resolves to this module for the same reason.
"""

from __future__ import annotations

import asyncio
import glob as _glob
import logging
from typing import TYPE_CHECKING, Any, Protocol

from langchain_core.messages.utils import count_tokens_approximately

from ...context.stage import VAULT_STAGE_PATTERNS
from ...domain_config import domain_config
from ...graph.enums import PipelinePhase

if TYPE_CHECKING:
    from pathlib import Path

    from ...thread.state import TeamState
    from ..protocols import TaskQueuePort

from ..tools.task_queue import render_queue_view

__all__ = [
    "ContextMounter",
    "build_initial_vault_index",
    "create_context_mounter",
    "create_mount_node",
    "refresh_vault_index",
]


class MountNode(Protocol):
    """Node callable shape for the mount stage: state-only, no routing.

    A plain ``Callable[[TeamState], Any]`` erases the ``state`` parameter name,
    which langgraph's node protocols match on, not just position -- so this
    named-parameter ``Protocol`` is what let ``add_node`` bind it without a
    ``reportArgumentType`` mismatch at every call site.
    """

    async def __call__(self, state: TeamState) -> dict[str, Any]:
        """Execute the mount pass, returning a state update."""
        ...


class ContextMounter(Protocol):
    """Expands the vault documents one worker turn is grounded in."""

    async def __call__(self, state: TeamState) -> str | None:
        """Return the mounted document text for *state*, or ``None``."""
        ...


_logger = logging.getLogger(__name__)

_DOC_SEPARATOR = "--- MOUNTED: {path} ---"
_DOC_FOOTER = "--- END ---"
_QUEUE_PHASES = frozenset({PipelinePhase.PLAN, PipelinePhase.EXEC})


def build_initial_vault_index(
    workspace_root: Path | None,
    feature_tag: str,
) -> dict[str, list[str]]:
    """Scan .vault/ for files matching feature_tag.

    Returns empty dict when workspace_root is None.
    """
    if workspace_root is None:
        return {}
    index: dict[str, list[str]] = {}
    for stage, pattern in VAULT_STAGE_PATTERNS.items():
        resolved = pattern.replace("{tag}", _glob.escape(feature_tag))
        # The TAIL, not the head. Identifiers sort ascending (W01-P01-S01 first),
        # so truncating from the front kept a feature's OLDEST records and
        # discarded everything recent - which inverts what a resuming run needs,
        # and does it silently. Two features in this repository's own vault hold
        # 130 and 97 execution records against a cap of 50, so this bound is not
        # hypothetical: those runs were grounding on their first fifty steps.
        #
        # The ordering is lexicographic, so recency here is APPROXIMATE: it is
        # exact across waves and phases, and degrades within a phase once step
        # numbers pass two digits (S144 sorts before S87). Approximate recency is
        # strictly better than guaranteed staleness, and a true ordering needs a
        # numeric key over the canonical identifier segments rather than a
        # filesystem timestamp, which a checkout rewrites.
        cap = domain_config.vault_index_cap
        matches = sorted(workspace_root.glob(resolved))[-cap:]
        if matches:
            index[stage] = [m.relative_to(workspace_root).as_posix() for m in matches]
    return index


def _select_paths(
    vault_index: dict[str, list[str]],
    phase: str | None,
    workspace_root: Path,
) -> list[Path]:
    """Select documents to mount: ADRs always, then current-phase docs.

    Priority order (used when budget is exceeded):
    1. ADR documents (always binding, always first)
    2. Current-phase documents in filesystem sort order
    """
    adr_paths = [workspace_root / p for p in vault_index.get("adr", [])]
    phase_paths: list[Path] = []
    if phase and phase != "adr":
        phase_paths = [workspace_root / p for p in vault_index.get(phase, [])]

    return adr_paths + phase_paths


async def _render_queue_block(
    state: TeamState, task_queue_port: TaskQueuePort | None
) -> str | None:
    """Render the database-backed queue view as a mounted block, if any."""
    if task_queue_port is None:
        return None
    feature = state.get("active_feature")
    phase: str | None = state.get("pipeline_phase")
    thread_id = state.get("thread_id")
    if not feature or phase not in _QUEUE_PHASES or not thread_id:
        return None
    try:
        entries = await task_queue_port.get_queue_view(
            thread_id,
            state.get("current_task_id"),
            domain_config.task_queue_pending_horizon,
        )
    except Exception:
        # Best-effort context assembly: a queue read failure degrades to
        # no queue block rather than failing the worker turn.
        _logger.warning(
            "task-queue injection failed for thread %s", thread_id, exc_info=True
        )
        return None
    queue_text = render_queue_view(feature, entries)
    if not queue_text:
        return None
    header = _DOC_SEPARATOR.format(path="task-queue")
    return f"{header}\n{queue_text}\n{_DOC_FOOTER}"


async def _read_vault_doc(path: Path, cache: dict[str, tuple[float, str]]) -> str:
    """Read a .vault/ document asynchronously with an mtime-validated cache."""

    def _read_with_stat() -> tuple[float, str]:
        mtime = path.stat().st_mtime
        cached = cache.get(str(path))
        if cached is not None and cached[0] == mtime:
            return cached
        return mtime, path.read_text(encoding="utf-8")

    mtime, content = await asyncio.to_thread(_read_with_stat)
    cache[str(path)] = (mtime, content)
    return content


async def _mount_document_blocks(
    vault_index: dict[str, list[str]],
    phase: str | None,
    workspace_root: Path,
    cache: dict[str, tuple[float, str]],
) -> tuple[list[str], int]:
    """Read selected documents within the mount token budget."""
    blocks: list[str] = []
    tokens_used = 0
    for path in _select_paths(vault_index, phase, workspace_root):
        if not path.exists():
            continue

        content = await _read_vault_doc(path, cache)
        rel_path = path.relative_to(workspace_root).as_posix()
        header = _DOC_SEPARATOR.format(path=rel_path)
        block = f"{header}\n{content}\n{_DOC_FOOTER}"
        block_tokens = count_tokens_approximately(block)

        remaining = domain_config.mount_token_ceiling - tokens_used
        if block_tokens <= remaining:
            blocks.append(block)
            tokens_used += block_tokens
        elif remaining > domain_config.min_remaining_tokens_for_mount:
            ratio = remaining / block_tokens
            truncate_at = int(len(content) * ratio * 0.9)
            truncated = content[:truncate_at]
            blocks.append(f"{header}\n{truncated}\n[TRUNCATED]\n{_DOC_FOOTER}")
            break
        else:
            break
    return blocks, tokens_used


async def refresh_vault_index(
    state: TeamState, workspace_root: Path | None
) -> dict[str, list[str]]:
    """Re-derive the active feature's vault index from disk.

    The one refresh both the mount node and the supervisor's gates use.
    Returns an empty mapping when there is nothing to scan - no workspace or
    no active feature - which the callers read as "leave the index alone".
    Add-only by construction: it discovers documents and the merge reducer
    unions them, so a removal is not reflected.

    Off the loop: the scan globs the vault tree from disk.
    """
    active_feature = state.get("active_feature")
    if workspace_root is None or not active_feature:
        return {}
    return await asyncio.to_thread(
        build_initial_vault_index, workspace_root, active_feature
    )


def create_mount_node(workspace_root: Path | None) -> MountNode:
    """Factory: the graph node that refreshes the vault index before a worker.

    Each pass re-derives the active feature's vault index from disk so gates
    and the mounter observe documents produced earlier in the same run. The
    refresh is add-only: it discovers newly written documents and returns them
    through the ``_merge_vault_index`` reducer; removals are out of scope for
    the merge reducer and are not reflected here.
    """

    async def mount_node(state: TeamState) -> dict[str, Any]:
        """Refresh the active feature's vault index into state."""
        refreshed_index = await refresh_vault_index(state, workspace_root)
        return {"vault_index": refreshed_index} if refreshed_index else {}

    return mount_node


def create_context_mounter(
    workspace_root: Path | None,
    task_queue_port: TaskQueuePort | None = None,
) -> ContextMounter:
    """Factory: expands phase-scoped vault documents for one worker invocation.

    The content cache is scoped to this factory call -- one cache per compiled
    worker, not shared across threads or sessions. When a ``task_queue_port``
    is injected, the database-backed queue view is appended as a mounted block
    during the plan and exec phases.
    """
    # One entry per path holding (mtime, content): a re-edited file replaces
    # its entry instead of accreting stale mtime-keyed copies, so the cache is
    # bounded by the number of mounted documents.
    cache: dict[str, tuple[float, str]] = {}

    async def mount_context(state: TeamState) -> str | None:
        """Assemble the mounted text from the index the mount node refreshed."""
        if workspace_root is None or not state.get("active_feature"):
            return None

        blocks, tokens_used = await _mount_document_blocks(
            state.get("vault_index") or {},
            state.get("pipeline_phase"),
            workspace_root,
            cache,
        )

        queue_block = await _render_queue_block(state, task_queue_port)
        if queue_block is not None:
            queue_tokens = count_tokens_approximately(queue_block)
            if queue_tokens <= domain_config.mount_token_ceiling - tokens_used:
                blocks.append(queue_block)

        return "\n\n".join(blocks) if blocks else None

    return mount_context
