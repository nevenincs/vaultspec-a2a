"""Blackboard content mounting node (ADR-020, ADR R5)."""

from __future__ import annotations

import asyncio
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

__all__ = ["create_mount_node"]

_logger = logging.getLogger(__name__)

_DOC_SEPARATOR = "--- MOUNTED: {path} ---"
_DOC_FOOTER = "--- END ---"
_QUEUE_PHASES = frozenset({PipelinePhase.PLAN, PipelinePhase.EXEC})


def _select_paths(state: TeamState, workspace_root: Path) -> list[Path]:
    """Select documents to mount: ADRs always, then current-phase docs.

    Priority order (used when budget is exceeded):
    1. ADR documents (always binding, always first)
    2. Current-phase documents in filesystem sort order
    """
    vault_index: dict[str, list[str]] = state.get("vault_index") or {}
    phase: str | None = state.get("pipeline_phase")

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
    cache: dict[tuple[str, float], str] = {}

    async def _read_vault_doc(path: Path) -> str:
        """Read a .vault/ document asynchronously with mtime-keyed cache."""

        def _read_with_stat() -> tuple[tuple[str, float], str]:
            mtime = path.stat().st_mtime
            key = (str(path), mtime)
            return key, path.read_text(encoding="utf-8")

        key, content = await asyncio.to_thread(_read_with_stat)
        if key not in cache:
            cache[key] = content
        return cache[key]

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
        """Preprocessing node: read .vault/ documents and assemble mounted_context."""
        if workspace_root is None:
            return {"mounted_context": None}

        if not state.get("active_feature"):
            return {"mounted_context": None}

        blocks: list[str] = []
        tokens_used = 0

        for path in _select_paths(state, workspace_root):
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
            return {"mounted_context": None}

        return {"mounted_context": "\n\n".join(blocks)}

    return mount_node
