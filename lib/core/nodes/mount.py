"""Blackboard content mounting node (ADR-020)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable

from langchain_core.messages.utils import count_tokens_approximately

from ..state import TeamState

__all__ = ["create_mount_node"]

_MOUNT_TOKEN_CEILING = 20_000
_DOC_SEPARATOR = "--- MOUNTED: {path} ---"
_DOC_FOOTER = "--- END ---"


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


def create_mount_node(workspace_root: Path | None) -> Callable:
    """Factory: returns a mount_node with a closure-scoped content cache.

    The cache is scoped to this factory call — one cache per compiled graph,
    not shared across threads or sessions.
    """
    cache: dict[tuple[str, float], str] = {}

    async def _read_vault_doc(path: Path) -> str:
        """Read a .vault/ document asynchronously with mtime-keyed cache.

        Both stat() and read_text() run inside asyncio.to_thread to avoid
        blocking the event loop. The cache check after the thread call means
        a cache hit on a second concurrent read for the same (path, mtime)
        is still possible; this is safe (idempotent) and acceptable for v1.
        """

        def _read_with_stat() -> tuple[tuple[str, float], str]:
            mtime = path.stat().st_mtime
            key = (str(path), mtime)
            return key, path.read_text(encoding="utf-8")

        key, content = await asyncio.to_thread(_read_with_stat)
        if key not in cache:
            cache[key] = content
        return cache[key]

    async def mount_node(state: TeamState) -> dict[str, Any]:
        """Preprocessing node: read .vault/ documents and assemble mounted_context.

        Runs between supervisor routing and worker invocation.
        Returns {"mounted_context": assembled_text} or {"mounted_context": None}
        when no feature is active, vault_index is empty, or workspace_root is None.
        """
        if workspace_root is None:
            return {"mounted_context": None}

        if not state.get("active_feature"):
            return {"mounted_context": None}

        paths = _select_paths(state, workspace_root)
        if not paths:
            return {"mounted_context": None}

        blocks: list[str] = []
        tokens_used = 0

        for path in paths:
            if not path.exists():
                continue

            content = await _read_vault_doc(path)
            rel_path = str(path.relative_to(workspace_root))

            header = _DOC_SEPARATOR.format(path=rel_path)
            block = f"{header}\n{content}\n{_DOC_FOOTER}"
            block_tokens = count_tokens_approximately(block)

            remaining = _MOUNT_TOKEN_CEILING - tokens_used
            if block_tokens <= remaining:
                blocks.append(block)
                tokens_used += block_tokens
            elif remaining > 100:
                # Truncate to fit remaining budget (10% safety margin)
                ratio = remaining / block_tokens
                truncate_at = int(len(content) * ratio * 0.9)
                truncated = content[:truncate_at]
                block = f"{header}\n{truncated}\n[TRUNCATED]\n{_DOC_FOOTER}"
                blocks.append(block)
                break
            else:
                # No budget remaining — skip
                break

        if not blocks:
            return {"mounted_context": None}

        return {"mounted_context": "\n\n".join(blocks)}

    return mount_node
