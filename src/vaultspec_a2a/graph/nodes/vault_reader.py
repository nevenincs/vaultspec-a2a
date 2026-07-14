"""Blackboard content mounting node (ADR-020, ADR R5).

The mount node also owns the canonical ``build_initial_vault_index`` scan so the
same glob logic seeds the index at compile time and refreshes it on every mount
pass (ADR authoring-orchestration S01). ``compiler`` re-exports the function to
preserve the historical ``graph.compiler.build_initial_vault_index`` surface.
"""

from __future__ import annotations

import asyncio
import glob as _glob
import logging
from typing import TYPE_CHECKING, Any

from langchain_core.messages.utils import count_tokens_approximately

from vaultspec_a2a.domain_config import domain_config
from vaultspec_a2a.graph.enums import PipelinePhase

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from vaultspec_a2a.thread.state import TeamState

    from ..protocols import TaskQueuePort

from ..tools.task_queue import render_queue_view

__all__ = ["build_initial_vault_index", "create_mount_node"]

_logger = logging.getLogger(__name__)

_DOC_SEPARATOR = "--- MOUNTED: {path} ---"
_DOC_FOOTER = "--- END ---"
_QUEUE_PHASES = frozenset({PipelinePhase.PLAN, PipelinePhase.EXEC})

_VAULT_STAGE_PATTERNS: dict[str, str] = {
    PipelinePhase.RESEARCH: ".vault/research/*{tag}*.md",
    "reference": ".vault/reference/*{tag}*.md",
    PipelinePhase.ADR: ".vault/adr/*{tag}*.md",
    PipelinePhase.PLAN: ".vault/plan/*{tag}*.md",
    PipelinePhase.EXEC: ".vault/exec/*{tag}*/**/*.md",
    PipelinePhase.AUDIT: ".vault/audit/*{tag}*.md",
}


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
    for stage, pattern in _VAULT_STAGE_PATTERNS.items():
        resolved = pattern.replace("{tag}", _glob.escape(feature_tag))
        matches = sorted(workspace_root.glob(resolved))[: domain_config.vault_index_cap]
        if matches:
            index[stage] = [str(m.relative_to(workspace_root)) for m in matches]
    return index


def _merge_index_views(
    existing: dict[str, list[str]],
    refreshed: dict[str, list[str]],
) -> dict[str, list[str]]:
    """Add-only merge of a refreshed on-disk scan onto the state's index.

    Mirrors the ``_merge_vault_index`` reducer semantics so the in-pass mount
    view matches what the reducer will persist: newly produced documents are
    added, prior entries are preserved, and removals are out of scope.
    """
    merged: dict[str, list[str]] = {k: list(v) for k, v in existing.items()}
    for doc_type, paths in refreshed.items():
        seen = set(merged.get(doc_type, []))
        bucket = merged.setdefault(doc_type, [])
        for p in paths:
            if p not in seen:
                bucket.append(p)
                seen.add(p)
    return merged


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


def create_mount_node(
    workspace_root: Path | None,
    task_queue_port: TaskQueuePort | None = None,
) -> Callable:
    """Factory: returns a mount_node with a closure-scoped content cache.

    The cache is scoped to this factory call -- one cache per compiled graph,
    not shared across threads or sessions.  When a ``task_queue_port`` is
    injected, the database-backed queue view (ADR R5) is appended as a
    mounted block during the plan and exec phases, replacing the former
    ``.vault/plan`` markdown interception.
    """
    # One entry per path holding (mtime, content): a re-edited file replaces
    # its entry instead of accreting stale mtime-keyed copies, so the cache is
    # bounded by the number of mounted documents.
    cache: dict[str, tuple[float, str]] = {}

    async def _read_vault_doc(path: Path) -> str:
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

    async def _render_queue_block(state: TeamState) -> str | None:
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
            # no queue block rather than failing the worker turn (parity with
            # the file path skipping a missing document).
            _logger.warning(
                "task-queue injection failed for thread %s", thread_id, exc_info=True
            )
            return None
        queue_text = render_queue_view(feature, entries)
        if not queue_text:
            return None
        header = _DOC_SEPARATOR.format(path="task-queue")
        return f"{header}\n{queue_text}\n{_DOC_FOOTER}"

    async def mount_node(state: TeamState) -> dict[str, Any]:
        """Preprocessing node: read .vault/ documents and assemble mounted_context.

        Each pass re-derives the active feature's vault index from disk so gates
        and mounts observe documents produced earlier in the same run (S01). The
        refresh is add-only: it discovers newly written documents and returns
        them through the ``_merge_vault_index`` reducer; removals are out of
        scope for the merge reducer and are not reflected here.
        """
        if workspace_root is None:
            return {"mounted_context": None}

        active_feature = state.get("active_feature")
        if not active_feature:
            return {"mounted_context": None}

        refreshed_index = await asyncio.to_thread(
            build_initial_vault_index, workspace_root, active_feature
        )
        mount_index = _merge_index_views(
            state.get("vault_index") or {}, refreshed_index
        )
        index_update: dict[str, Any] = (
            {"vault_index": refreshed_index} if refreshed_index else {}
        )

        blocks: list[str] = []
        tokens_used = 0

        for path in _select_paths(
            mount_index, state.get("pipeline_phase"), workspace_root
        ):
            if not path.exists():
                continue

            content = await _read_vault_doc(path)

            rel_path = str(path.relative_to(workspace_root))
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
                block = f"{header}\n{truncated}\n[TRUNCATED]\n{_DOC_FOOTER}"
                blocks.append(block)
                break
            else:
                break

        queue_block = await _render_queue_block(state)
        if queue_block is not None:
            queue_tokens = count_tokens_approximately(queue_block)
            if queue_tokens <= domain_config.mount_token_ceiling - tokens_used:
                blocks.append(queue_block)

        if not blocks:
            return {"mounted_context": None, **index_update}

        return {"mounted_context": "\n\n".join(blocks), **index_update}

    return mount_node
